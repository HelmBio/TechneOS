"""Unit tests for pure helpers in task_service.crud.runs (no DB)."""

from datetime import UTC, datetime

from core.models.task_run import TaskRunArtifact
from task_service.crud.runs import (
    _artifact_info,
    _display_status,
    _merge_outputs,
)


def _artifact(action_type: str, file_name: str = "f.csv") -> TaskRunArtifact:
    return TaskRunArtifact(
        id=f"art-{action_type}",
        task_run_id="run-1",
        org_id="org-1",
        action_type=action_type,
        name=file_name,
        file_name=file_name,
        file_size=10,
        content_type="text/csv",
        storage_bucket="techneos-data",
        storage_key=f"task-runs/t/v1/run-1/{action_type}/art/{file_name}",
        status="active",
        created_by="user-1",
    )


# ── _display_status ──────────────────────────────────────────────────────


def test_display_status_active_states():
    assert _display_status("pending", None, None) == "pending"
    assert _display_status("accepted", None, None) == "accepted"
    assert _display_status("in_progress", None, None) == "in progress"


def test_display_status_terminal_outcomes():
    assert _display_status("terminal", "completed", None) == "completed"
    assert _display_status("terminal", "declined", None) == "declined"
    assert _display_status("terminal", "cancelled", None) == "cancelled"
    assert _display_status("terminal", "expired", None) == "cancelled"


def test_display_status_escalation_wins():
    now = datetime.now(UTC)
    assert _display_status("accepted", None, now) == "escalated"
    # Escalation overrides even an active status.
    assert _display_status("pending", None, now) == "escalated"


# ── _merge_outputs ───────────────────────────────────────────────────────


def test_merge_outputs_none_passthrough():
    assert _merge_outputs(None, []) is None


def test_merge_outputs_no_artifacts():
    assert _merge_outputs({"score": 1}, []) == {"score": 1}


def test_merge_outputs_includes_finish_only():
    # output_data.attachments carries the final deliverables (finish only);
    # start inputs and threaded update files are excluded.
    artifacts = [
        _artifact("start", "input.sdf"),  # input — excluded
        _artifact("finish", "result.csv"),
        _artifact("update", "note.txt"),  # threaded update file — excluded here
    ]
    merged = _merge_outputs({"score": 1}, artifacts)
    assert merged["score"] == 1
    names = {a["file_name"] for a in merged["attachments"]}
    assert names == {"result.csv"}
    assert "input.sdf" not in names
    assert "note.txt" not in names


def test_merge_outputs_only_inputs_yields_no_attachments():
    merged = _merge_outputs({"score": 1}, [_artifact("start")])
    assert "attachments" not in merged


# ── _artifact_info ───────────────────────────────────────────────────────


def test_artifact_info_maps_fields():
    art = _artifact("finish", "out.csv")
    art.event_id = "ev-1"
    info = _artifact_info(art)
    assert info.id == "art-finish"
    assert info.action_type == "finish"
    assert info.file_name == "out.csv"
    assert info.event_id == "ev-1"
    assert info.status == "active"
