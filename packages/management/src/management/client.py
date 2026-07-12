from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


class TechneOSClient:
    def __init__(self, api_url: str, token: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, data: bytes | None = None) -> tuple[int, str]:
        url = f"{self.api_url}{path}"
        req = urllib.request.Request(url, data=data, method=method)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode()
                return resp.status, body
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except urllib.error.URLError as e:
            return 0, str(e)

    def get(self, path: str) -> tuple[int, str]:
        return self._request("GET", path)

    def delete(self, path: str) -> tuple[int, str]:
        return self._request("DELETE", path)

    def post(self, path: str, data: dict[str, Any] | None = None) -> tuple[int, str]:
        body = json.dumps(data or {}).encode()
        return self._request("POST", path, data=body)

    def delete_storage_files(self, files: list[dict[str, Any]]) -> tuple[int, str]:
        """Delete files from the object store via the admin API.

        Args:
            files: List of ``{"bucket": str, "key": str}`` pairs.

        Returns:
            ``(status_code, response_body)``. On success (200) the body
            contains ``{"deleted": [...], "errors": [...]}``.
        """
        return self.post("/api/v1/admin/storage/files/delete", {"files": files})

    def paginate(
        self,
        path: str,
        limit: int = 100,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skip = 0
        while True:
            sep = "&" if "?" in path else "?"
            code, body = self.get(f"{path}{sep}skip={skip}&limit={limit}")
            if code != 200:
                break
            data = json.loads(body)
            if isinstance(data, list):
                # A bare-list endpoint isn't paginated — take the one page and stop.
                batch = data
                if filter_fn:
                    batch = [item for item in batch if filter_fn(item)]
                items.extend(batch)
                break
            batch = data.get("items", [])
            if filter_fn:
                batch = [item for item in batch if filter_fn(item)]
            items.extend(batch)
            total = data.get("total", 0)
            skip += limit
            if skip >= total or not batch:
                break
        return items
