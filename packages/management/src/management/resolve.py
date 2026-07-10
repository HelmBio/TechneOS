from __future__ import annotations

import json
import sys
from typing import Any, cast


def resolve_resource(client: Any, resource_type: str, ref: str) -> dict[str, Any]:
    # Try as UUID
    code, body = client.get(f"/api/v1/{resource_type}/{ref}")
    if code == 200:
        return cast(dict[str, Any], json.loads(body))

    # Try by-slug endpoint (tools, etc.)
    code, body = client.get(f"/api/v1/{resource_type}/by-slug/{ref}")
    if code == 200:
        return cast(dict[str, Any], json.loads(body))

    # List all and search by slug or id
    code, body = client.get(f"/api/v1/{resource_type}?skip=0&limit=500")
    if code == 200:
        data = json.loads(body)
        items = data.get("items", data if isinstance(data, list) else [])
        for item in items:
            if item.get("slug") == ref or item.get("id") == ref:
                return cast(dict[str, Any], item)

    print(f"Error: {resource_type.rstrip('s')} not found: {ref}", file=sys.stderr)
    sys.exit(1)
