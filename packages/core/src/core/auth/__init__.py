"""Auth package — provider abstraction, RBAC, and FastAPI dependencies."""

from core.auth.dependencies import get_current_user
from core.auth.rbac import check_permission

__all__ = ["check_permission", "get_current_user"]
