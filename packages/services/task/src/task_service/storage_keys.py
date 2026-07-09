"""Canonical MinIO key layout for task-run artifacts.

All files for a run live under a single prefix keyed by the run id, with the
action that produced them as the next segment::

    task-runs/{tool_slug}/v{N}/{task_run_id}/{action_type}/{file_name}

Files are uploaded first to *scratch space* — an ephemeral area that may be
cleared periodically and is NOT tracked in the database — then copied to the
canonical key on bind (inputs) / submit (outputs). Scratch mirrors the
canonical layout::

    scratch-space/task-runs/{tool_slug}/v{N}/{upload_id}/{file_name}       # inputs
    scratch-space/task-runs/{tool_slug}/v{N}/{task_run_id}/{file_name}     # outputs

Inputs are staged against a known version (preselected from the version card)
so the version number is always known. Inputs use a per-upload id for
namespacing; outputs use the run id.
"""

from __future__ import annotations

import re

TASK_RUNS_PREFIX = "task-runs"
# Ephemeral staging area (safe to clear periodically; not in the DB).
STAGING_PREFIX = "scratch-space/task-runs"


def _safe(name: str | None, default: str) -> str:
    """Sanitise a filename for use in an object key."""
    n = (name or default).replace("/", "_").replace("\\", "_").strip()
    return n or default


def input_staging_prefix(tool_slug: str, version: int, upload_id: str) -> str:
    """Scratch prefix for one staged input (version is known at upload)."""
    return f"{STAGING_PREFIX}/{tool_slug}/v{version}/{upload_id}/"


def input_staging_key(
    tool_slug: str, version: int, upload_id: str, file_name: str | None
) -> str:
    """Key for a staged input file, before the run exists."""
    return f"{input_staging_prefix(tool_slug, version, upload_id)}{_safe(file_name, 'input')}"


def output_staging_prefix(tool_slug: str, version: int, task_run_id: str) -> str:
    """Scratch prefix for a run's staged outputs (run + version are known)."""
    return f"{STAGING_PREFIX}/{tool_slug}/v{version}/{task_run_id}/"


def output_staging_key(
    tool_slug: str, version: int, task_run_id: str, file_name: str | None
) -> str:
    """Key for a staged output file (relocated to finish/ on submit)."""
    return f"{output_staging_prefix(tool_slug, version, task_run_id)}{_safe(file_name, 'output')}"


def run_prefix(
    *,
    tool_slug: str,
    version: int,
    task_run_id: str,
) -> str:
    """Prefix (folder) holding every file for one run, across all actions."""
    return f"{TASK_RUNS_PREFIX}/{tool_slug}/v{version}/{task_run_id}/"


def action_prefix(
    *,
    tool_slug: str,
    version: int,
    task_run_id: str,
    action_type: str,
) -> str:
    """Prefix (folder) holding all files for one run + action."""
    return (
        f"{run_prefix(tool_slug=tool_slug, version=version, task_run_id=task_run_id)}{action_type}/"
    )


def canonical_key(
    *,
    tool_slug: str,
    version: int,
    task_run_id: str,
    action_type: str,
    file_name: str | None,
) -> str:
    """Canonical key for a task-run file, scoped to the run + action.

    An action can carry multiple files; they share the ``{action_type}/``
    prefix and are distinguished by filename (each is its own
    ``task_run_artifacts`` row)::

        task-runs/{tool_slug}/v{N}/{task_run_id}/{action_type}/{file_name}
    """
    prefix = action_prefix(
        tool_slug=tool_slug, version=version, task_run_id=task_run_id, action_type=action_type
    )
    return f"{prefix}{_safe(file_name, 'file')}"


def next_available_name(existing: set[str], file_name: str) -> str:
    """Return ``file_name``, or a non-colliding variant with ``-N`` appended.

    If ``file_name`` already exists in ``existing``, append ``-N`` before the
    extension, where N is one past the largest existing ``{stem}-{N}{ext}``
    (the bare ``{stem}{ext}`` counts as 0). E.g. with
    {report.csv, report-1.csv} an incoming ``report.csv`` becomes
    ``report-2.csv``.
    """
    if file_name not in existing:
        return file_name
    stem, dot, rest = file_name.rpartition(".")
    if dot and stem:
        ext = f".{rest}"
    else:
        stem, ext = file_name, ""
    pat = re.compile(rf"^{re.escape(stem)}-(\d+){re.escape(ext)}$")
    largest = 0
    for name in existing:
        m = pat.match(name)
        if m:
            largest = max(largest, int(m.group(1)))
    return f"{stem}-{largest + 1}{ext}"
