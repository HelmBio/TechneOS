"""Shared OpenAPI helpers for the platform's services."""

from __future__ import annotations

from fastapi.routing import APIRoute


def short_operation_id(route: APIRoute) -> str:
    """A compact operationId: ``{tag}_{endpoint function}``.

    FastAPI's default id is the function name plus the full path and method. For a
    route taking form/file params it also names the body model FastAPI synthesises
    for it (``Body_{operationId}``), which yields schema names like::

        Body_replace_version_files_endpoint_api_v1_datasets__dataset_id__versions__version_id__files_put

    Tag + function name is unique in practice (FastAPI warns on a duplicate id) and
    keeps both the operationId — which the docs' deep links are built from — and
    that generated model name readable.
    """
    tag = str(route.tags[0]) if route.tags else ""
    name = route.name
    return f"{tag}_{name}".strip("_").replace("-", "_") if tag else name
