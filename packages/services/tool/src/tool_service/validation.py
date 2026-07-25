import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

from core.schemas.tool import RuntimeValidationResponse

logger = logging.getLogger(__name__)


def _codeartifact_index_url(url: str | None) -> str | None:
    """Return *url* with a CodeArtifact auth token injected, if applicable."""
    if not url:
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if ".d.codeartifact." not in hostname or "amazonaws.com" not in hostname:
        return url

    from techneos_aws import codeartifact

    domain = os.getenv("CODEARTIFACT_DOMAIN", "techneos")
    domain_owner = os.getenv("CODEARTIFACT_DOMAIN_OWNER") or os.getenv("AWS_ACCOUNT_ID")
    if not domain_owner:
        logger.warning("CODEARTIFACT_DOMAIN_OWNER not set — pip may fail with 401")
        return url
    token = codeartifact.mint_token(domain, domain_owner)
    if not token:
        logger.warning("Failed to mint CodeArtifact token — pip may fail with 401")
        return url

    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    new_netloc = f"aws:{token}@{netloc}"
    return urlunparse(parsed._replace(netloc=new_netloc))

# Validation timeouts and limits — applied to run_package_validation
SCRIPT_TIMEOUT = 15
DEPS_INSTALL_TIMEOUT = 120
MAX_OUTPUT_BYTES = 65536


def validate_version_content(tool_type: str, data: Any) -> None:
    if tool_type in ("container", "api"):
        if not data.docker_image:
            raise HTTPException(
                status_code=422,
                detail="Docker image is required for container/api tool types",
            )

    elif tool_type == "pypi":
        if not all([data.package_name, data.package_version, data.entry_point]):
            raise HTTPException(
                status_code=422,
                detail="Pypi tool must have all of 'package_name', 'package_version', 'entry_point'",
            )

    elif tool_type == "human":
        pass  # No Docker image or package required; config is optional

    elif tool_type == "module":
        # 'module' tools are not supported; pypi wheels are the delivery path.
        raise HTTPException(
            status_code=422,
            detail=(
                "tool_type='module' is not supported. Re-register the tool as "
                "tool_type='pypi' (publish a wheel exposing run(inputs, params) "
                "-> dict)."
            ),
        )


def validate_version_create(tool_type: str, data: Any) -> None:
    """Validate a new version; delegates to validate_version_content."""
    validate_version_content(tool_type, data)


async def run_package_validation(
    package_name: str,
    package_version: str,
    entry_point: str,
    package_index_url: str | None = None,
    test_script: str | None = None,
) -> RuntimeValidationResponse:
    """Validate a pip-installable package-based module tool.

    Installs the package from the specified index, then:
    - If test_script is provided: runs it (should import and test the package)
    - Otherwise: attempts to import and call the entry point with dummy inputs

    Returns validation results.
    """
    with tempfile.TemporaryDirectory(prefix="pkg_val_") as tmpdir:
        venv_dir = Path(tmpdir) / "venv"

        try:
            # Create venv
            proc = await asyncio.create_subprocess_exec(
                "python3",
                "-m",
                "venv",
                str(venv_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=DEPS_INSTALL_TIMEOUT)
            if proc.returncode != 0:
                err = stderr.decode(errors="replace")[:500]
                return RuntimeValidationResponse(
                    passed=False,
                    error=f"Failed to create venv: {err}",
                )

            venv_python = venv_dir / "bin" / "python3"
            pip_cmd = [str(venv_python), "-m", "pip", "install"]

            # Install package
            pkg_spec = f"{package_name}=={package_version}"
            cmd = [*pip_cmd, pkg_spec]
            resolved_index = _codeartifact_index_url(package_index_url)
            if resolved_index:
                cmd.extend(["--index-url", resolved_index])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=DEPS_INSTALL_TIMEOUT
            )
            if proc.returncode != 0:
                err = stderr.decode(errors="replace")[:500]
                return RuntimeValidationResponse(
                    passed=False,
                    error=f"Failed to install package {pkg_spec}: {err}",
                )

            logger.info("Installed package %s from index", pkg_spec)

            # Run test or dummy invocation
            if test_script:
                test_path = Path(tmpdir) / "test_pkg.py"
                test_path.write_text(test_script)

                proc = await asyncio.create_subprocess_exec(
                    str(venv_python),
                    str(test_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmpdir,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            else:
                # Default: try to import and call entry point
                test_code = f"""
import sys
try:
    module_path, func_name = "{entry_point}".rsplit(":", 1)
    module = __import__(module_path, fromlist=[func_name])
    func = getattr(module, func_name)
    # Call with dummy inputs
    result = func({{"test": True}}, {{"verbose": True}})
    if result is None:
        print("OK: Entry point executed")
    else:
        print(f"OK: Entry point returned: {{result}}")
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
                test_path = Path(tmpdir) / "test_import.py"
                test_path.write_text(test_code)

                proc = await asyncio.create_subprocess_exec(
                    str(venv_python),
                    str(test_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmpdir,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return RuntimeValidationResponse(
                    passed=False,
                    error=f"Package test timed out after {SCRIPT_TIMEOUT}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            passed = proc.returncode == 0

            return RuntimeValidationResponse(
                passed=passed,
                exit_code=proc.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
                error=None if passed else stderr_str.strip() or f"Exit code {proc.returncode}",
            )

        except TimeoutError:
            return RuntimeValidationResponse(
                passed=False,
                error="Package validation timed out",
            )
        except Exception as exc:
            return RuntimeValidationResponse(
                passed=False,
                error=str(exc),
            )
