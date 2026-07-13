"""Agent service FastAPI application."""

import contextlib
import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import entry_points

from dotenv import load_dotenv

# Load .env so that provider API keys are available in os.environ before the registry resolves them.
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import select  # noqa: E402

from agent_service.routes import agents, assistant, conversations, runs  # noqa: E402
from core.agent.registry import load_providers_from_db  # noqa: E402
from core.agent.tool_registry import get_tool_registry  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.database.postgres import dispose_engine, get_async_session_context  # noqa: E402
from core.exceptions import (  # noqa: E402
    AlreadyExistsError,
    AuthError,
    InsufficientPermissionsError,
    NotFoundError,
    PlatformError,
    ValidationError,
)
from core.models.agent import AgentDefinition  # noqa: E402
from core.models.tool import PypiConfig, ToolVersion  # noqa: E402


async def _install_registered_agent_packages() -> list[str]:
    """Install Python packages for every AgentDefinition with a populated
    ``package_config`` JSONB column.

    This is the runtime side of the wheel-publish lifecycle: the agent's
    register script publishes a wheel to DevPI/CodeArtifact and writes
    the coords into the DB row; here at startup we read the rows and
    `pip install` each package so the subsequent entry-point discovery
    can find them. pip is idempotent — already-installed packages at
    the right version are no-ops.

    Returns the list of entry-point group names that should now be
    enumerable (one per installed package).
    """
    async with get_async_session_context() as session:
        result = await session.execute(
            select(AgentDefinition).where(AgentDefinition.package_config.isnot(None))
        )
        agents_with_pkgs = result.scalars().all()

    installed: list[str] = []
    if not agents_with_pkgs:
        return installed

    default_index = get_settings().package_index_url

    for agent_def in agents_with_pkgs:
        cfg = agent_def.package_config or {}
        name = cfg.get("name")
        version = cfg.get("version")
        index_url = cfg.get("index_url") or default_index
        if not name or not version:
            print(
                f"  Skipping agent '{agent_def.slug}': package_config missing name/version "
                f"(got {cfg!r})"
            )
            continue
        spec = f"{name}=={version}"
        cmd = ["uv", "pip", "install", "--quiet", spec]
        if index_url:
            cmd.extend(["--index-url", index_url])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"  Installed agent package: {spec}")
            installed.append(name)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            print(
                f"  Failed to install agent package {spec} for '{agent_def.slug}': {stderr or exc}"
            )
        except FileNotFoundError:
            print(
                f"  Failed to install agent package {spec}: `uv` not found in this Python env",
            )
    return installed


async def _install_registered_tool_packages() -> list[str]:
    """Install Python packages for every active pypi-type ToolVersion whose
    ``PypiConfig.agent_tools`` column is non-null, and uninstall any
    tool packages that are installed in this environment but no longer
    have ``agent_tools`` set (null/empty) or whose version is inactive.

    These are tool packages that contribute ``techneos.platform_assistant_tools``
    entry points to the Platform Assistant agent. Installing them here makes
    those entry points discoverable by ``load_extra_platform_tools()`` later
    in the startup sequence.
    """
    async with get_async_session_context() as session:
        result = await session.execute(
            select(ToolVersion)
            .join(PypiConfig)
            .where(
                ToolVersion.status == "active",
                PypiConfig.agent_tools.isnot(None),
            )
            .limit(100)
        )
        tool_versions = result.unique().scalars().all()

    installed: list[str] = []
    should_install: dict[str, str] = {}
    default_index = get_settings().package_index_url

    for tv in tool_versions:
        cfg = tv.pypi_config
        if not cfg:
            continue
        package_name = cfg.package_name
        spec = f"{package_name}=={cfg.package_version}"
        should_install[package_name] = spec
        cmd = ["uv", "pip", "install", "--quiet", spec]
        index_url = cfg.package_index_url or default_index
        if index_url:
            cmd.extend(["--index-url", index_url])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"  Installed tool package: {spec}")
            installed.append(package_name)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            print(f"  Failed to install tool package {spec}: {stderr or exc}")
        except FileNotFoundError:
            print(f"  Failed to install tool package {spec}: `uv` not found in this Python env")

    # Uninstall any installed package that has a techneos.platform_assistant_tools
    # entry point but is NOT in the should_install set.  This handles:
    #   - agent_tools set to null/empty via the API
    #   - version deactivated
    #   - tool/version deleted from registry
    # We discover these by scanning the installed Python environment rather
    # than relying on the DB, since deleted records are unreachable.
    try:
        stale_detected: list[str] = []
        for dist in entry_points(group="techneos.platform_assistant_tools"):
            pkg_name = dist.dist.name if dist.dist else None
            if pkg_name and pkg_name not in should_install:
                stale_detected.append(pkg_name)
        for pkg in set(stale_detected):
            try:
                subprocess.run(
                    ["uv", "pip", "uninstall", "--quiet", pkg],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print(f"  Uninstalled stale tool package: {pkg}")
            except subprocess.CalledProcessError:
                pass
            except FileNotFoundError:
                print(f"  Failed to uninstall {pkg}: `uv` not found")
    except Exception as exc:
        print(f"  Warning: stale-tool cleanup scan failed: {exc}")

    return installed


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"Agent service starting (env={settings.environment})")

    # Register built-in platform assistant tools first (always available).
    # Extra tools contributed by catalog packages are discovered lazily
    # after runtime package installs, below.
    from platform_assistant.tools import (
        PLATFORM_TOOLS_BUILTIN,
        load_extra_platform_tools,
    )

    get_tool_registry().register_set(PLATFORM_TOOLS_BUILTIN)

    # Install wheel-delivered agent packages from the DB. AgentDefinitions
    # with package_config=NULL are code-baked (legacy path) and need
    # nothing here — their package is already in the image's site-packages.
    try:
        installed_agents = await _install_registered_agent_packages()
        if installed_agents:
            print(
                f"Installed {len(installed_agents)} agent package(s) from registry: {installed_agents}"
            )
    except Exception as exc:
        print(f"Warning: agent-package install pass failed: {exc}")

    # Install wheel-delivered tool packages that contribute platform
    # assistant tools (those with PypiConfig.agent_tools IS NOT NULL).
    try:
        installed_tools = await _install_registered_tool_packages()
        if installed_tools:
            print(
                f"Installed {len(installed_tools)} tool package(s) from registry: {installed_tools}"
            )
    except Exception as exc:
        print(f"Warning: tool-package install pass failed: {exc}")

    # Force importlib.metadata to re-scan the env so freshly-installed
    # packages' entry points are visible to the discovery loops below.
    import importlib.metadata as _md

    with contextlib.suppress(AttributeError, Exception):
        _md._cache_clear()  # type: ignore[attr-defined]

    # Discover and register extra platform assistant tools contributed by
    # catalog packages (e.g. calculate_molecule_properties from
    # molecule-property-calculator). This runs after the install steps
    # above so the techneos.platform_assistant_tools entry points are findable.
    extras = load_extra_platform_tools()
    if extras:
        get_tool_registry().register_set(extras)
        print(f"Registered {len(extras)} extra platform assistant tool(s)")

    # Discover and import agent packages via entry points. Each loaded module
    # is expected to register its tools — either by re-export of a TOOLS list
    # the loader pulls into the registry, or (legacy) via __init__ side effects.
    for ep in entry_points(group="techneos.agents"):
        try:
            mod = ep.load()
            # New contract: prefer explicit registration over import-time
            # side effects. If the loaded module exposes a `TOOLS` (or
            # `<NAME>_TOOLS`) list, register those callables; otherwise
            # fall back to the legacy side-effect convention where the
            # module's __init__ already called register_set().
            tools_attr = getattr(mod, "TOOLS", None)
            if tools_attr is None:
                # Common naming variant: CHEMBL_TOOLS, FOO_TOOLS, etc.
                for attr_name in dir(mod):
                    if attr_name.endswith("_TOOLS") and isinstance(
                        getattr(mod, attr_name, None), list
                    ):
                        tools_attr = getattr(mod, attr_name)
                        break
            if tools_attr:
                get_tool_registry().register_set(tools_attr)
                print(
                    f"  Registered agent package: {ep.name} "
                    f"({mod.__name__}, {len(tools_attr)} tool(s))"
                )
            else:
                print(
                    f"  Registered agent package: {ep.name} ({mod.__name__}) "
                    "[tools registered via import side effect]"
                )
        except Exception as exc:
            print(f"  Failed to load agent package '{ep.name}': {exc}")

    print(f"Tool registry: {len(get_tool_registry().list_all())} tools registered")

    # Load LLM provider configs from DB into the in-memory registry
    try:
        await load_providers_from_db()
        print("LLM providers loaded into registry")
    except Exception as exc:
        print(f"Warning: could not load LLM providers from DB: {exc}")

    # The built-in Platform Assistant agent is registered by the platform-admin
    # setup step (`python setup/register_platform_assistant.py`), run after
    # seeding and before catalog registration — not on service startup.
    yield
    await dispose_engine()
    print("Agent service stopped")


app = FastAPI(
    title="TechneOS — Agent Service",
    description="Define, execute, and track AI agent runs",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Exception handlers ---


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(AlreadyExistsError)
async def already_exists_handler(request: Request, exc: AlreadyExistsError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": exc.message})


@app.exception_handler(InsufficientPermissionsError)
async def insufficient_permissions_handler(
    request: Request, exc: InsufficientPermissionsError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": exc.message})


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": exc.message})


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.message})


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": exc.message})


# --- Routes ---

settings = get_settings()
prefix = settings.api_v1_prefix

app.include_router(agents.router, prefix=f"{prefix}/agents", tags=["agents"])
app.include_router(assistant.router, prefix=f"{prefix}/assistant", tags=["assistant"])
app.include_router(runs.router, prefix=f"{prefix}/agentic-tasks", tags=["agentic-tasks"])
app.include_router(conversations.router, prefix=f"{prefix}/agentic-runs", tags=["agentic-runs"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "agent"}
