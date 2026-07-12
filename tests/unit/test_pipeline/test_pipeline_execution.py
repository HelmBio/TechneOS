"""Tests for new pipeline route endpoints — step status callback, sync, schemas."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.schemas.pipeline import StepStatusUpdate


class TestStepStatusUpdateSchema:
    """Test the new StepStatusUpdate schema."""

    def test_valid_statuses(self):
        for status in ("pending", "running", "completed", "failed", "skipped"):
            update = StepStatusUpdate(status=status)
            assert update.status == status

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            StepStatusUpdate(status="invalid")

    def test_with_error_message(self):
        update = StepStatusUpdate(status="failed", error_message="OOM killed")
        assert update.error_message == "OOM killed"

    def test_with_outputs(self):
        update = StepStatusUpdate(
            status="completed",
            outputs={"score": 0.95, "poses": 10},
        )
        assert update.outputs["score"] == 0.95


class TestUpdateStepRunByName:
    """Test the new CRUD function update_step_run_by_name."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        return session

    async def test_updates_status_to_running(self, mock_session):
        from pipeline_service.crud.runs import update_step_run_by_name

        mock_sr = MagicMock()
        mock_sr.status = "pending"
        mock_sr.started_at = None
        mock_sr.finished_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sr
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await update_step_run_by_name(
            mock_session, run_id="run-1", step_name="dock", status="running"
        )
        assert result.status == "running"
        assert result.started_at is not None

    async def test_updates_status_to_completed(self, mock_session):
        from pipeline_service.crud.runs import update_step_run_by_name

        mock_sr = MagicMock()
        mock_sr.status = "running"
        mock_sr.started_at = MagicMock()
        mock_sr.finished_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sr
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await update_step_run_by_name(
            mock_session,
            run_id="run-1",
            step_name="dock",
            status="completed",
            outputs={"best_score": -9.2},
        )
        assert result.status == "completed"
        assert result.finished_at is not None
        assert result.outputs == {"best_score": -9.2}

    async def test_auto_creates_when_not_found(self, mock_session):
        """When step run doesn't exist, it auto-creates one."""
        from pipeline_service.crud.runs import update_step_run_by_name

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()

        result = await update_step_run_by_name(
            mock_session, run_id="run-1", step_name="missing", status="running"
        )
        assert result.step_name == "missing"
        assert result.status == "running"
        mock_session.add.assert_called_once()


class TestPipelineHealthWithNewRoutes:
    """Verify the pipeline service still boots with the new routes registered."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from pipeline_service.main import app

        return TestClient(app)

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "pipeline"
