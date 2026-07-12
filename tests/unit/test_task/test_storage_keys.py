"""Unit tests for the canonical task-run MinIO key layout."""

from task_service.storage_keys import (
    canonical_key,
    input_staging_key,
    input_staging_prefix,
    next_available_name,
    output_staging_key,
    output_staging_prefix,
)

# ── next_available_name (filename de-duplication) ────────────────────────


def test_dedupe_no_collision_returns_same():
    assert next_available_name({"a.csv"}, "b.csv") == "b.csv"


def test_dedupe_bare_collision_appends_1():
    assert next_available_name({"report.csv"}, "report.csv") == "report-1.csv"


def test_dedupe_increments_from_largest():
    existing = {"report.csv", "report-1.csv", "report-2.csv"}
    assert next_available_name(existing, "report.csv") == "report-3.csv"


def test_dedupe_uses_largest_even_with_gaps():
    assert next_available_name({"report.csv", "report-5.csv"}, "report.csv") == "report-6.csv"


def test_dedupe_no_extension():
    assert next_available_name({"data"}, "data") == "data-1"


def test_dedupe_multi_dot_extension():
    assert next_available_name({"a.tar.gz"}, "a.tar.gz") == "a.tar-1.gz"


def test_canonical_key_full():
    key = canonical_key(
        tool_slug="hit-triage",
        version=3,
        task_run_id="run-1",
        action_type="start",
        file_name="hits.sdf",
    )
    # No artifact-id segment — files sit directly under {action_type}/.
    assert key == "task-runs/hit-triage/v3/run-1/start/hits.sdf"


def test_canonical_key_multiple_files_share_action_prefix():
    a = canonical_key(
        tool_slug="t",
        version=1,
        task_run_id="r",
        action_type="finish",
        file_name="a.csv",
    )
    b = canonical_key(
        tool_slug="t",
        version=1,
        task_run_id="r",
        action_type="finish",
        file_name="b.csv",
    )
    # Two files of the same action share the {action_type}/ prefix.
    assert a == "task-runs/t/v1/r/finish/a.csv"
    assert b == "task-runs/t/v1/r/finish/b.csv"


def test_canonical_key_sanitises_filename():
    key = canonical_key(
        tool_slug="t",
        version=1,
        task_run_id="r",
        action_type="start",
        file_name="../../etc/passwd",
    )
    assert key.endswith("/.._.._etc_passwd")
    assert key.count("task-runs/") == 1


def test_canonical_key_blank_filename_falls_back():
    key = canonical_key(
        tool_slug="t",
        version=1,
        task_run_id="r",
        action_type="start",
        file_name=None,
    )
    assert key.endswith("/file")


def test_input_staging_key_uses_version_and_upload_id():
    # Inputs are staged with the known version number.
    assert (
        input_staging_key("hit-triage", 1, "up-1", "in.sdf")
        == "scratch-space/task-runs/hit-triage/v1/up-1/in.sdf"
    )


def test_input_staging_key_blank_filename_falls_back():
    assert (
        input_staging_key("hit-triage", 1, "up-1", None)
        == "scratch-space/task-runs/hit-triage/v1/up-1/input"
    )


def test_input_staging_prefix_matches_key():
    prefix = input_staging_prefix("hit-triage", 1, "up-1")
    assert prefix == "scratch-space/task-runs/hit-triage/v1/up-1/"
    assert input_staging_key("hit-triage", 1, "up-1", "in.sdf").startswith(prefix)


def test_output_staging_key_is_run_scoped():
    # Outputs are staged against an existing run → run id + version, no extra id.
    assert (
        output_staging_key("hit-triage", 2, "run-1", "result.json")
        == "scratch-space/task-runs/hit-triage/v2/run-1/result.json"
    )


def test_output_staging_prefix_matches_key():
    prefix = output_staging_prefix("hit-triage", 2, "run-1")
    assert prefix == "scratch-space/task-runs/hit-triage/v2/run-1/"
    assert output_staging_key("hit-triage", 2, "run-1", "r.json").startswith(prefix)
