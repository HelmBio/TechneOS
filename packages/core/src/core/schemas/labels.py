"""Pydantic schemas for platform UI label overrides."""

import re

from pydantic import BaseModel, Field, field_validator

# Dotted lowercase identifier, e.g. ``resource.pipeline.plural`` or
# ``section.executions``.
_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)+$")
_MAX_KEYS = 100
_MAX_VALUE_LEN = 100


class LabelOverrides(BaseModel):
    """A flat map of label keys to display strings.

    The canonical key set + English defaults live in the web app, which falls
    back to its default for any key not present here. We therefore validate
    *shape* (key format, value length, count) rather than an exact key set, so
    the backend doesn't drift out of sync with the frontend's label catalog.
    """

    overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def _validate_overrides(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > _MAX_KEYS:
            raise ValueError(f"Too many label overrides (max {_MAX_KEYS})")
        for key, value in v.items():
            if not _KEY_RE.match(key):
                raise ValueError(f"Invalid label key: {key!r}")
            if not value or not value.strip():
                raise ValueError(f"Empty value for label key: {key!r}")
            if len(value) > _MAX_VALUE_LEN:
                raise ValueError(f"Label value too long for {key!r} (max {_MAX_VALUE_LEN} chars)")
        return v


class LabelOverridesResponse(BaseModel):
    overrides: dict[str, str] = Field(default_factory=dict)
