"""Dataset commands — list, get, create, upload, download, delete."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import typer

from cli.client import (
    ApiError,
    api_delete,
    api_download,
    api_get,
    api_post,
    api_upload,
    require_auth,
)
from cli.output import print_detail, print_error, print_json, print_success, print_table

dataset_app = typer.Typer(name="dataset", help="Dataset management.", no_args_is_help=True)


@dataset_app.command("list")
def list_datasets(
    q: str = typer.Option("", "--query", "-q", help="Search query"),
    data_type: str = typer.Option("", "--type", "-t", help="Filter by data type"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List datasets."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if q:
        params["q"] = q
    if data_type:
        params["data_type"] = data_type

    try:
        data = api_get("/api/v1/datasets", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No datasets found.")
            return
        print_table(
            columns=["ID", "Name", "Type", "Public", "Created"],
            rows=[
                [
                    d["id"][:12] + "…",
                    d["name"],
                    d.get("data_type", "—"),
                    "yes" if d.get("is_public") else "no",
                    d["created_at"][:19],
                ]
                for d in items
            ],
            title=f"Datasets ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@dataset_app.command("get")
def get_dataset(dataset_id: str = typer.Argument(..., help="Dataset ID")) -> None:
    """Get dataset details with version history."""
    require_auth()
    try:
        data = api_get(f"/api/v1/datasets/{dataset_id}")
        versions = data.pop("versions", [])
        print_detail(data, title="Dataset")
        if versions:
            typer.echo("")
            print_table(
                columns=["Version", "File", "Size", "Status", "Created"],
                rows=[
                    [
                        str(v["version"]),
                        v.get("file_name", "—"),
                        _fmt_size(v.get("file_size", 0)),
                        v.get("status", "—"),
                        v["created_at"][:19],
                    ]
                    for v in versions
                ],
                title="Versions",
            )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


def _load_data_schema(data_schema_arg: str) -> dict[str, Any]:
    """Resolve a --data-schema argument that may be a file path or JSON string."""
    import json

    if not data_schema_arg:
        raise typer.BadParameter(
            "--data-schema is required. Pass either a JSON Schema string or a "
            "path to a .json file (e.g. --data-schema ./schema.json)."
        )
    p = Path(data_schema_arg)
    if p.exists() and p.is_file():
        try:
            return cast(dict[Any, Any], json.loads(p.read_text()))
        except json.JSONDecodeError as e:
            raise typer.BadParameter(f"Invalid JSON in {p}: {e}") from None
    try:
        return cast(dict[Any, Any], json.loads(data_schema_arg))
    except json.JSONDecodeError as e:
        raise typer.BadParameter(
            f"--data-schema must be a path to a .json file or a JSON string ({e})"
        ) from None


@dataset_app.command("create")
def create_dataset(
    name: str = typer.Option(..., "--name", help="Dataset name"),
    slug: str = typer.Option(..., "--slug", help="URL-friendly slug"),
    data_schema: str = typer.Option(
        ...,
        "--data-schema",
        help="JSON Schema describing the data (file path or inline JSON). Required.",
    ),
    data_type: str = typer.Option("tabular", "--type", "-t", help="Data type"),
    description: str = typer.Option("", "--desc", "-d", help="Description"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags"),
    metadata_json: str = typer.Option("{}", "--metadata", help="JSON metadata string"),
    public: bool = typer.Option(False, "--public", help="Make publicly visible"),
) -> None:
    """Create a new dataset (metadata only, upload versions separately)."""
    require_auth()
    body: dict[str, object] = {
        "name": name,
        "slug": slug,
        "data_type": data_type,
        "is_public": public,
        "data_schema": _load_data_schema(data_schema),
    }
    if description:
        body["description"] = description
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if metadata_json and metadata_json != "{}":
        import json

        body["metadata"] = json.loads(metadata_json)

    try:
        data = api_post("/api/v1/datasets", json=body)
        print_success(f"Created dataset {data['id']}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@dataset_app.command("register")
def register_dataset(
    file: Path = typer.Argument(..., help="File to upload", exists=True, readable=True),
    name: str = typer.Option(..., "--name", help="Dataset name"),
    slug: str = typer.Option(..., "--slug", help="URL-friendly slug"),
    data_schema: str = typer.Option(
        ...,
        "--data-schema",
        help="JSON Schema describing the data (file path or inline JSON). Required.",
    ),
    data_type: str = typer.Option("tabular", "--type", "-t", help="Data type"),
    description: str = typer.Option("", "--desc", "-d", help="Description"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags"),
    metadata_json: str = typer.Option("{}", "--metadata", help="JSON metadata string"),
    public: bool = typer.Option(False, "--public", help="Make publicly visible"),
    version_desc: str = typer.Option("", "--version-desc", help="Version 1 description"),
) -> None:
    """Create a dataset and upload its first version in one step."""
    import json as json_mod

    require_auth()

    # Step 1: Create dataset metadata
    body: dict[str, object] = {
        "name": name,
        "slug": slug,
        "data_type": data_type,
        "is_public": public,
        "data_schema": _load_data_schema(data_schema),
    }
    if description:
        body["description"] = description
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if metadata_json and metadata_json != "{}":
        body["metadata"] = json_mod.loads(metadata_json)

    try:
        typer.echo(f"Creating dataset '{name}'...")
        data = api_post("/api/v1/datasets", json=body)
        dataset_id = data["id"]
        print_success(f"Created dataset {dataset_id}")

        # Step 2: Upload file as version 1
        params: dict[str, str] = {}
        if version_desc:
            params["description"] = version_desc
        typer.echo(f"Uploading {file.name} as version 1...")
        version_data = api_upload(
            f"/api/v1/datasets/{dataset_id}/versions", str(file), params=params
        )
        print_success(
            f"Uploaded version {version_data.get('version', '?')} "
            f"({_fmt_size(version_data.get('file_size', 0))})"
        )

        # Summary
        typer.echo("")
        print_detail(data, title="Dataset")
        typer.echo("")
        print_json(version_data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@dataset_app.command("upload")
def upload_version(
    dataset_id: str = typer.Argument(..., help="Dataset ID"),
    file: Path = typer.Argument(..., help="File to upload", exists=True, readable=True),
    description: str = typer.Option("", "--desc", "-d", help="Version description"),
) -> None:
    """Upload a new version of a dataset."""
    require_auth()
    params: dict[str, Any] = {}
    if description:
        params["description"] = description

    try:
        data = api_upload(f"/api/v1/datasets/{dataset_id}/versions", str(file), params=params)
        print_success(f"Uploaded version {data.get('version', '?')} of dataset {dataset_id}")
        print_json(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@dataset_app.command("download")
def download_version(
    dataset_id: str = typer.Argument(..., help="Dataset ID"),
    version_id: str = typer.Argument(..., help="Version ID"),
    output: Path = typer.Option(Path("."), "--output", "-o", help="Output directory"),
) -> None:
    """Download a dataset version to a local file."""
    require_auth()
    try:
        data = api_get(f"/api/v1/datasets/{dataset_id}/versions/{version_id}/download")
        url = data["download_url"]
        fname = data.get("file_name", f"dataset-{version_id}")
        dest = output / fname
        api_download(url, str(dest))
        print_success(f"Downloaded to {dest}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@dataset_app.command("delete")
def delete_dataset(
    dataset_id: str = typer.Argument(..., help="Dataset ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a dataset and all its versions."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete dataset {dataset_id}?", abort=True)
    try:
        api_delete(f"/api/v1/datasets/{dataset_id}")
        print_success(f"Deleted dataset {dataset_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


def _fmt_size(size: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
