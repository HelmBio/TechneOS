"""Tests for the shared version-status lifecycle policy."""

import pytest

from core.exceptions import ConflictError
from core.version_lifecycle import (
    InvalidStatusTransitionError,
    definition_editable,
    validate_status_transition,
)

# (current, new) pairs that are permitted.
LEGAL = [
    ("draft", "testing"),
    ("testing", "draft"),
    ("testing", "active"),
    ("active", "deprecated"),
    ("deprecated", "active"),
    # no-ops are always allowed
    ("draft", "draft"),
    ("active", "active"),
    ("deprecated", "deprecated"),
]

# (current, new) pairs that must be rejected.
ILLEGAL = [
    ("draft", "active"),  # must pass through testing
    ("draft", "deprecated"),  # deprecation only from active
    ("testing", "deprecated"),  # deprecation only from active
    ("active", "draft"),
    ("active", "testing"),
    ("deprecated", "draft"),
    ("deprecated", "testing"),
    ("testing", "bogus"),  # unknown status
]


@pytest.mark.parametrize(("current", "new"), LEGAL)
def test_legal_transitions_pass(current, new):
    # Should not raise.
    validate_status_transition(current, new)


@pytest.mark.parametrize(("current", "new"), ILLEGAL)
def test_illegal_transitions_raise(current, new):
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition(current, new)


def test_invalid_transition_is_a_conflict_error():
    # InvalidStatusTransitionError maps to HTTP 409 via the ConflictError handler.
    assert issubclass(InvalidStatusTransitionError, ConflictError)


@pytest.mark.parametrize(
    ("status", "has_runs", "expected"),
    [
        ("draft", False, True),
        ("testing", False, True),
        ("draft", True, False),
        ("testing", True, False),
        ("active", False, False),
        ("active", True, False),
        ("deprecated", False, False),
        ("deprecated", True, False),
    ],
)
def test_definition_editable(status, has_runs, expected):
    assert definition_editable(status, has_runs) is expected
