"""High-level catalog-item registration orchestrators.

Built on the Layer-1 helpers in :mod:`management.registration`
(:class:`~management.registration.Session`, ``start_session``,
``publish_wheel_and_record``, ``read_package_meta``). A catalog
``build_and_register.py`` becomes: load ``*_def.json`` + call one of these.

The Docker-image path (container tools / the ``techneos/tool-runtime`` image) is not
consolidated here yet — those scripts still call the Layer-1 primitives directly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import httpx

from management.registration import (
    Session,
    build_image_and_record,
    find_resource_by_slug,
    publish_wheel_and_record,
    upload_wheel_to_gateway,
    upload_image_to_gateway,
    read_package_meta,
)


def _post(session: Session, path: str, body: dict[str, Any], *, what: str) -> str:
    resp = httpx.post(f"{session.api_url}{path}", json=body, headers=session.headers)
    if not resp.is_success:
        print(
            f"Error: failed to create {what} (HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    return cast(str, resp.json()["id"])


def _delete(session: Session, collection: str, resource_id: str) -> None:
    resp = httpx.delete(
        f"{session.api_url}/api/v1/{collection}/{resource_id}", headers=session.headers
    )
    if not resp.is_success:
        print(
            f"Error: failed to delete {collection}/{resource_id} "
            f"(HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)


def _read_readme(package_dir: Path) -> str:
    readme = package_dir / "README.md"
    return readme.read_text() if readme.exists() else ""


def recreate_or_get(
    session: Session,
    collection: str,
    slug: str,
    *,
    upsert: bool,
    list_query: str = "?limit=500",
) -> str | None:
    """Resolve a resource by slug for an upsert flow.

    Returns the existing id when it exists and ``upsert`` is false; deletes it and
    returns ``None`` (→ create fresh) when ``upsert`` is true; returns ``None`` when
    absent.
    """
    existing = find_resource_by_slug(
        session.api_url, session.headers, f"/api/v1/{collection}{list_query}", slug
    )
    if existing is None:
        return None
    if not upsert:
        return existing
    print(f"  Recreating (--upsert) — deleting {collection}/{existing} ...")
    _delete(session, collection, existing)
    return None


def upsert_tool(
    session: Session,
    tool_def: dict[str, Any],
    package_dir: Path,
    *,
    tool_type: str,
    upsert: bool,
    list_query: str = "?limit=500",
) -> str:
    """Find-or-create the Tool (recreate on ``--upsert``). Returns the tool id.

    ``list_query`` is the slug-lookup filter — the default ``/api/v1/tools`` list
    excludes human-type tools, so a human task must pass ``?tool_type=human&…``.
    """
    existing = recreate_or_get(session, "tools", tool_def["slug"], upsert=upsert, list_query=list_query)
    if existing is not None:
        print(f"  Tool exists: {existing} (use --upsert to recreate)")
        return existing
    body = {
        "name": tool_def["name"],
        "slug": tool_def["slug"],
        "description": tool_def.get("description", ""),
        "category": tool_def.get("category", "general"),
        "tool_type": tool_type,
        "tags": tool_def.get("tags", []),
        "is_public": tool_def.get("is_public", True),
        "readme": tool_def.get("readme") or _read_readme(package_dir),
    }
    tool_id = _post(session, "/api/v1/tools", body, what="tool")
    print(f"  Created tool: {tool_id}")
    return tool_id


def register_pypi_tool(
    session: Session,
    package_dir: Path | str,
    tool_def: dict[str, Any],
    *,
    skip_build: bool = False,
    skip_publish: bool = False,
    upsert: bool = False,
    use_gateway: bool = True,
) -> tuple[str, str]:
    """Register a pypi-delivered tool end-to-end.

    Upsert the Tool, publish+record the wheel (skipped with ``--skip-build``), then
    create the pypi ``ToolVersion``. Returns ``(tool_id, version_id)``.

    When ``use_gateway`` is True (default), the wheel is uploaded to the gateway
    which handles index publishing. When False, uses direct publish (legacy).
    """
    package_dir = Path(package_dir)
    meta = read_package_meta(package_dir)
    tool_id = upsert_tool(
        session, tool_def, package_dir, tool_type=tool_def.get("tool_type", "pypi"), upsert=upsert
    )
    if not skip_build:
        if use_gateway:
            version = upload_wheel_to_gateway(
                session, package_dir, origin="catalog", entry_point=meta.entry_point,
            )
        else:
            version = publish_wheel_and_record(
                session, package_dir, origin="catalog", entry_point=meta.entry_point,
                publish=not skip_publish,
            )
    else:
        version = meta.version
        print(f"  Package version: {version} (--skip-build)")
    body = {
        "package_name": meta.name,
        "package_version": version,
        "entry_point": meta.entry_point,
        # Platform-assistant tool names this pypi tool contributes (None if it
        # contributes none) — see molecule-property-calculator.
        "agent_tools": tool_def.get("agent_tools"),
        "input_schema": tool_def.get("input_schema", {}),
        "output_schema": tool_def.get("output_schema", {}),
        "parameters_schema": tool_def.get("parameters_schema", {}),
        "resource_requirements": tool_def.get("resource_requirements", {}),
    }
    version_id = _post(session, f"/api/v1/tools/{tool_id}/versions", body, what="version")
    print(f"  Created version: {version_id}")
    return tool_id, version_id


def register_task(
    session: Session,
    package_dir: Path | str,
    task_def: dict[str, Any],
    *,
    upsert: bool = False,
) -> tuple[str, str]:
    """Register a human task — structurally identical to a tool registration, minus
    the artifact: a human task has no wheel/image to build, publish, or record.

    Upserts a ``tool_type="human"`` Tool and creates a ToolVersion carrying the
    human-assignment config (assignment_type / assignee / due / attachments) +
    schemas. Returns ``(tool_id, version_id)``.
    """
    package_dir = Path(package_dir)
    tool_id = upsert_tool(
        session, task_def, package_dir,
        tool_type=task_def.get("tool_type", "human"), upsert=upsert,
        # the default tools list excludes human tools — filter so re-registration
        # finds the existing task instead of 409-ing on create.
        list_query="?tool_type=human&limit=500",
    )
    human_cfg = task_def.get("human_config", {})
    body = {
        "input_schema": task_def.get("input_schema", {}),
        "output_schema": task_def.get("output_schema", {}),
        "parameters_schema": task_def.get("parameters_schema", {}),
        "assignment_type": human_cfg.get("assignment_type", "team"),
        "default_user_email": human_cfg.get("default_user_email"),
        "default_team_slug": human_cfg.get("default_team_slug"),
        # Legacy single-string field still accepted by the API for back-compat.
        "default_assignee": human_cfg.get("default_assignee"),
        "due_in_hours": human_cfg.get("due_in_hours", 168),
        "require_attachments": human_cfg.get("require_attachments", True),
    }
    version_id = _post(session, f"/api/v1/tools/{tool_id}/versions", body, what="version")
    print(f"  Created version: {version_id}")
    return tool_id, version_id


def register_pipeline(
    session: Session,
    package_dir: Path | str,
    pipeline_def: dict[str, Any],
    *,
    upsert: bool = False,
) -> str:
    """Register a pipeline — a definition with no artifact to build/publish.

    Upserts the Pipeline by slug (recreate on ``--upsert``, else return existing)
    and POSTs the ``steps``/``edges``/schema definition. Returns the pipeline id.
    """
    package_dir = Path(package_dir)
    existing = recreate_or_get(session, "pipelines", pipeline_def["slug"], upsert=upsert)
    if existing is not None:
        print(f"  Pipeline exists: {existing} (use --upsert to recreate)")
        return existing
    body = {
        "name": pipeline_def["name"],
        "slug": pipeline_def["slug"],
        "description": pipeline_def.get("description"),
        "readme": pipeline_def.get("readme") or _read_readme(package_dir),
        "steps": pipeline_def.get("steps", []),
        "edges": pipeline_def.get("edges", []),
        "parameters_schema": pipeline_def.get("parameters_schema", {}),
        "default_parameters": pipeline_def.get("default_parameters", {}),
        "tags": pipeline_def.get("tags", []),
        "is_public": pipeline_def.get("is_public", True),
    }
    pipeline_id = _post(session, "/api/v1/pipelines", body, what="pipeline")
    print(f"  Created pipeline: {pipeline_id}")
    return pipeline_id


def resolve_dataset_file(file_arg: str | None, default_dir: Path) -> tuple[Path, int]:
    """Resolve a ``.tsv`` data file from ``--file`` (a path or directory) or
    ``default_dir``; return ``(path, row_count)``. Exits if nothing is found."""
    source = Path(file_arg) if file_arg else default_dir
    if not source.exists():
        print(
            f"ERROR: Path not found: {source}\n  Place data in {default_dir} or use --file PATH",
            file=sys.stderr,
        )
        sys.exit(1)
    if source.is_dir():
        tsvs = sorted(source.glob("*.tsv"))
        if not tsvs:
            print(f"ERROR: No .tsv files found in directory: {source}", file=sys.stderr)
            sys.exit(1)
        data_file = tsvs[0]
    else:
        data_file = source
    print(f"Using file: {data_file}")
    with open(data_file) as fh:
        row_count = sum(1 for _ in fh) - 1
    return data_file, row_count


def register_dataset(
    session: Session,
    dataset_def: dict[str, Any],
    data_file: Path,
    *,
    upsert: bool = False,
    new_version: bool = False,
    upload_description: str = "",
    file_content_type: str = "text/tab-separated-values",
) -> str:
    """Register a dataset and upload ``data_file`` as a version — no artifact to
    build (a dataset is API + object-store, not a packaged wheel/image).

    ``dataset_def`` is the DatasetCreate body (splice any runtime description before
    calling). ``new_version`` uploads to an existing dataset; ``upsert`` recreates;
    otherwise an existing dataset is a no-op. Returns the dataset id.
    """
    base = f"{session.api_url}/api/v1"
    slug = dataset_def["slug"]
    name = dataset_def["name"]
    # Auth-only headers — httpx sets Content-Type per request (json vs multipart),
    # so the metadata POST and the file upload each get the right one.
    headers = {"Authorization": session.headers["Authorization"]}

    with httpx.Client(headers=headers, timeout=60.0) as client:
        print("Checking for existing dataset...")
        resp = client.get(f"{base}/datasets", params={"q": name, "limit": 50})
        resp.raise_for_status()
        existing = [d for d in resp.json().get("items", []) if d["slug"] == slug]

        dataset_id: str | None = None
        reuse = False
        if existing:
            if new_version:
                dataset_id = existing[0]["id"]
                reuse = True
                print(f"  --new-version: uploading to existing dataset {dataset_id}")
            elif upsert:
                dataset_id = existing[0]["id"]
                print(f"  --upsert: deleting existing dataset {dataset_id} ...")
                d = client.delete(f"{base}/datasets/{dataset_id}")
                if d.status_code not in (200, 204):
                    print(f"ERROR: delete failed: {d.status_code} {d.text}", file=sys.stderr)
                    sys.exit(1)
            else:
                print(
                    f"  Dataset '{slug}' already exists (id={existing[0]['id']}); "
                    "use --new-version to add a version or --upsert to recreate."
                )
                return cast(str, existing[0]["id"])

        if not reuse:
            print("Creating dataset...")
            c = client.post(f"{base}/datasets", json=dataset_def)
            if c.status_code == 409 and new_version:
                retry = client.get(f"{base}/datasets", params={"q": name, "is_public": True, "limit": 50})
                found = [d for d in retry.json().get("items", []) if d["slug"] == slug]
                if not found:
                    print(f"ERROR: dataset '{slug}' exists but not found via API.", file=sys.stderr)
                    sys.exit(1)
                dataset_id = found[0]["id"]
                print(f"  Found existing dataset: {dataset_id}")
            elif c.status_code not in (200, 201):
                print(f"ERROR: create failed: {c.status_code} {c.text}", file=sys.stderr)
                sys.exit(1)
            else:
                dataset_id = c.json()["id"]
                print(f"  Created dataset: {dataset_id}")

        print(f"Uploading {data_file.name} ({data_file.stat().st_size:,} bytes)...")
        with open(data_file, "rb") as f:
            up = client.post(
                f"{base}/datasets/{dataset_id}/versions",
                files={"file": (data_file.name, f, file_content_type)},
                params={"description": upload_description},
            )
        if up.status_code not in (200, 201):
            print(f"ERROR: upload failed: {up.status_code} {up.text}", file=sys.stderr)
            sys.exit(1)
        v = up.json()
        files = v.get("files") or []
        print(
            f"  Version: {v.get('version', '?')}  Status: {v.get('status', '?')}  "
            f"Files: {len(files)}  Size: {sum(fl.get('file_size', 0) for fl in files):,} bytes"
        )
        return dataset_id  # type: ignore[return-value]


def register_container_tool(
    session: Session,
    package_dir: Path | str,
    tool_def: dict[str, Any],
    *,
    skip_build: bool = False,
    skip_push: bool = False,
    upsert: bool = False,
    use_gateway: bool = True,
) -> tuple[str, str]:
    """Register a container-delivered tool end-to-end.

    Builds the image (bare ``techneos/<slug>`` tag), pushes to ECR + pre-caches on EC2
    for non-local envs, records the image artifact, upserts the Tool, and creates
    the container ``ToolVersion``. Returns ``(tool_id, version_id)``.

    ``docker_image`` stored on the version is the env-resolved reference
    (``{repo}/<slug>`` — full ECR URL for prod, bare ``techneos/<slug>`` for local),
    which is what the worker pulls.

    When ``use_gateway`` is True (default), the image is uploaded to the gateway
    which handles registry pushing. When False, uses direct push (legacy).
    """
    package_dir = Path(package_dir)
    meta = read_package_meta(package_dir)
    slug = tool_def["slug"]
    version = meta.version

    tool_id = upsert_tool(
        session, tool_def, package_dir,
        tool_type=tool_def.get("tool_type", "container"), upsert=upsert,
    )

    # Build + push + record the image (recorded before the version — tool-version
    # creation is hard-validated against the inventory).
    if use_gateway:
        image_ref = upload_image_to_gateway(
            session, slug=slug, package_dir=package_dir, version=version, origin="catalog",
            build_image=meta.docker_image,
        )
    else:
        image_ref = build_image_and_record(
            session, slug=slug, package_dir=package_dir, version=version, origin="catalog",
            build_image=meta.docker_image, skip_build=skip_build, skip_push=skip_push,
        )

    body = {
        "docker_image": image_ref,
        "docker_tag": version,
        "input_schema": tool_def.get("input_schema", {}),
        "output_schema": tool_def.get("output_schema", {}),
        "parameters_schema": tool_def.get("parameters_schema", {}),
        "resource_requirements": tool_def.get("resource_requirements", {}),
    }
    version_id = _post(session, f"/api/v1/tools/{tool_id}/versions", body, what="version")
    print(f"  Created version: {version_id}")
    return tool_id, version_id


def register_app(
    session: Session,
    package_dir: Path | str,
    app_def: dict[str, Any],
    *,
    version: str,
    skip_build: bool = False,
    skip_push: bool = False,
    skip_deploy: bool = False,
    upsert: bool = False,
    use_gateway: bool = True,
) -> str:
    """Register an embedded App: build + push + record the image (the same mechanism
    as container tools), upsert the App row, and trigger a deploy.

    The image is built/pushed via the shared ``build_image_and_record`` (buildx
    cross-arch + ECR for prod); the inventory record is non-fatal (App registration
    isn't hard-validated). On an existing row the image/tag are PATCHed; ``--upsert``
    recreates. ``version`` is the image tag (an app's source of truth is package.json,
    not pyproject.toml). Returns the app id.

    When ``use_gateway`` is True (default), the image is uploaded to the gateway
    which handles registry pushing. When False, uses direct push (legacy).
    """
    package_dir = Path(package_dir)
    slug = app_def["slug"]
    if use_gateway:
        image_ref = upload_image_to_gateway(
            session, slug=slug, package_dir=package_dir, version=version, origin="catalog",
        )
    else:
        image_ref = build_image_and_record(
            session, slug=slug, package_dir=package_dir, version=version, origin="catalog",
            skip_build=skip_build, skip_push=skip_push, fatal=False,
        )

    existing = recreate_or_get(session, "apps", slug, upsert=upsert)
    if existing is not None:
        print(f"  App exists: {existing} — updating image/tag via PATCH")
        resp = httpx.patch(
            f"{session.api_url}/api/v1/apps/{existing}",
            json={"docker_image": image_ref, "docker_tag": version},
            headers=session.headers,
        )
        if not resp.is_success:
            print(f"Error: PATCH failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
            sys.exit(1)
        app_id = existing
    else:
        app_id = _post(
            session, "/api/v1/apps",
            {**app_def, "docker_image": image_ref, "docker_tag": version}, what="app",
        )
        print(f"  Created app: {app_id}")

    if not skip_deploy:
        print(f"  Triggering deploy for {app_id} ...")
        resp = httpx.post(f"{session.api_url}/api/v1/apps/{app_id}/deploy", headers=session.headers)
        if resp.status_code != 200:
            print(f"Error: deploy failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
            sys.exit(1)
    return app_id


def register_agent(
    session: Session,
    package_dir: Path | str,
    agent_def: dict[str, Any],
    *,
    skip_build: bool = False,
    skip_publish: bool = False,
    upsert: bool = False,
    use_gateway: bool = True,
) -> str:
    """Register a wheel-delivered agent end-to-end.

    Publish+record the wheel, then upsert the ``AgentDefinition`` with
    ``package_config``: PATCH ``model_config``+``package_config`` on an existing row
    (so portal edits to system_prompt/tags aren't clobbered); ``--upsert`` forces a
    full replace. Returns the agent id.

    When ``use_gateway`` is True (default), the wheel is uploaded to the gateway
    which handles index publishing. When False, uses direct publish (legacy).
    """
    package_dir = Path(package_dir)
    meta = read_package_meta(package_dir)
    if not skip_build:
        if use_gateway:
            version = upload_wheel_to_gateway(
                session, package_dir, origin="catalog", entry_point=meta.entry_point,
            )
        else:
            version = publish_wheel_and_record(
                session, package_dir, origin="catalog", entry_point=meta.entry_point,
                publish=not skip_publish,
            )
    else:
        version = meta.version
        print(f"  Package version: {version} (--skip-build)")
    package_config = {"name": meta.name, "version": version, "entry_point": meta.entry_point}

    existing = recreate_or_get(
        session, "agents", agent_def["slug"], upsert=upsert,
        list_query="?include_platform=true&limit=200",
    )
    if existing is not None:
        print(f"  Updating existing agent {existing} (PATCH model_config + package_config)")
        resp = httpx.patch(
            f"{session.api_url}/api/v1/agents/{existing}",
            json={"model_config": agent_def["model_config"], "package_config": package_config},
            headers=session.headers,
        )
        if not resp.is_success:
            print(f"Error: PATCH failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
            sys.exit(1)
        return existing
    return _post(
        session, "/api/v1/agents", {**agent_def, "package_config": package_config}, what="agent"
    )
