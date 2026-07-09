"""Shared version-status lifecycle policy.

Single source of truth for the ``draft → testing → active → deprecated``
lifecycle shared by tool/task versions (``ToolVersion``) and pipeline versions
(``PipelineVersion``). Both services import from here so the rules stay
consistent.

Two rules are enforced:

1. **Status transitions** are restricted to the directed map in
   ``ALLOWED_TRANSITIONS``. Anything else (e.g. ``active → draft``) raises
   ``InvalidStatusTransitionError`` (a 409 ``ConflictError``).
2. **In-place definition edits** are only allowed while a version is still
   ``draft``/``testing`` *and* has no recorded runs — see
   ``definition_editable``. Once a version is promoted or has been run, its
   definition is frozen for traceability; callers must create a new version.
"""

from core.exceptions import ConflictError

VERSION_STATUSES: tuple[str, ...] = ("draft", "testing", "active", "deprecated")

# Directed transition map. A status maps to the set of statuses it may move to.
# Same-status (no-op) is always allowed and handled in validate_status_transition.
# Deprecation is only reachable from `active`: a version must progress through
# draft -> testing -> active before it can be deprecated.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"testing"},
    "testing": {"draft", "active"},
    "active": {"deprecated"},
    "deprecated": {"active"},  # restore
}

# Statuses whose definition may still be edited in place (subject to having no
# runs — see definition_editable).
EDITABLE_STATUSES: frozenset[str] = frozenset({"draft", "testing"})


class InvalidStatusTransitionError(ConflictError):
    """Raised when a version-status transition is not permitted."""

    def __init__(self, current: str, new: str) -> None:
        super().__init__(
            f"Cannot change version status from '{current}' to '{new}'. "
            f"Allowed transitions from '{current}': "
            f"{sorted(ALLOWED_TRANSITIONS.get(current, set())) or 'none'}."
        )


def validate_status_transition(current: str, new: str) -> None:
    """Validate a status change, raising InvalidStatusTransitionError if illegal.

    A no-op (``current == new``) is always allowed. Unknown statuses are
    rejected.
    """
    if new == current:
        return
    if new not in VERSION_STATUSES:
        raise InvalidStatusTransitionError(current, new)
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidStatusTransitionError(current, new)


def definition_editable(status: str, has_runs: bool) -> bool:
    """Whether a version's definition may be edited in place.

    Editable only while the version is draft/testing and has no recorded runs.
    Once active/deprecated or run-backed, the definition is frozen and a new
    version must be created instead.
    """
    return status in EDITABLE_STATUSES and not has_runs
