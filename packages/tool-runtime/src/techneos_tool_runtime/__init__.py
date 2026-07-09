"""Shared runtime for TechneOS tools.

See README.md for the run(inputs, params) -> dict contract.
"""

from techneos_tool_runtime import kinds, parsers, standardizers
from techneos_tool_runtime.io import (
    WorkDir,
    artifact_path,
    read_inputs,
    read_params,
    write_artifact,
    write_result,
)
from techneos_tool_runtime.kinds import InputKind

__all__ = [
    "InputKind",
    "WorkDir",
    "artifact_path",
    "kinds",
    "parsers",
    "read_inputs",
    "read_params",
    "standardizers",
    "write_artifact",
    "write_result",
]

__version__ = "0.1.0"
