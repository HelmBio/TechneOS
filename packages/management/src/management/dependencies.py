from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DependencyResult:
    resource_type: str
    id_: str
    name: str
    status: str
    active: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class DependencyScanner:
    def scan(self, client: Any, resource: dict[str, Any]) -> list[DependencyResult]:
        raise NotImplementedError

    def cancel_active(self, client: Any, dependents: list[DependencyResult]) -> None:
        raise NotImplementedError
