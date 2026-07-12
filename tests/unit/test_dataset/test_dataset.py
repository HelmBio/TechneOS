"""Tests for the dataset service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from dataset_service.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestDatasetHealth:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "dataset"


class TestDatasetCRUD:
    """Test dataset CRUD operations via mocked session."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_create_dataset(self, mock_session):
        from core.schemas.dataset import DatasetCreate
        from dataset_service.crud.datasets import create_dataset

        # Mock slug uniqueness check
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = DatasetCreate(
            name="Test Dataset",
            slug="test-dataset",
            description="A test",
            data_type="tabular",
            data_schema={
                "type": "object",
                "required": ["smiles"],
                "properties": {"smiles": {"type": "string"}},
            },
        )
        ds = await create_dataset(mock_session, data, org_id="org-1", user_id="user-1")

        assert ds.name == "Test Dataset"
        assert ds.slug == "test-dataset"
        assert ds.org_id == "org-1"
        assert ds.created_by == "user-1"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    async def test_create_dataset_duplicate_slug(self, mock_session):
        from core.exceptions import AlreadyExistsError
        from core.schemas.dataset import DatasetCreate
        from dataset_service.crud.datasets import create_dataset

        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = DatasetCreate(
            name="Dup",
            slug="existing-slug",
            data_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        with pytest.raises(AlreadyExistsError):
            await create_dataset(mock_session, data, org_id="org-1", user_id="user-1")

    async def test_get_dataset_not_found(self, mock_session):
        from core.exceptions import NotFoundError
        from dataset_service.crud.datasets import get_dataset

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_dataset(mock_session, "nonexistent-id")

    async def test_search_datasets_empty(self, mock_session):
        from core.schemas.dataset import DatasetSearchParams
        from dataset_service.crud.datasets import search_datasets

        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        # Mock items query
        items_result = MagicMock()
        items_scalars = MagicMock()
        items_scalars.all.return_value = []
        items_result.scalars.return_value = items_scalars

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])

        params = DatasetSearchParams(q="nothing", skip=0, limit=10)
        items, total = await search_datasets(mock_session, params)

        assert total == 0
        assert items == []


class TestDatasetSchemas:
    """Test Pydantic schema validation."""

    def test_dataset_create_valid(self):
        from core.schemas.dataset import DatasetCreate

        ds = DatasetCreate(
            name="Test",
            slug="test-ds",
            data_type="molecular",
            data_schema={"type": "object", "properties": {"smiles": {"type": "string"}}},
        )
        assert ds.name == "Test"
        assert ds.data_type == "molecular"
        assert ds.tags == []
        assert ds.is_public is False

    def test_dataset_create_invalid_slug(self):
        from pydantic import ValidationError

        from core.schemas.dataset import DatasetCreate

        with pytest.raises(ValidationError):
            DatasetCreate(
                name="Test",
                slug="INVALID SLUG!",
                data_schema={"type": "object"},
            )

    def test_dataset_create_invalid_data_type(self):
        from pydantic import ValidationError

        from core.schemas.dataset import DatasetCreate

        with pytest.raises(ValidationError):
            DatasetCreate(
                name="Test",
                slug="test",
                data_type="invalid",
                data_schema={"type": "object"},
            )

    def test_dataset_create_requires_data_schema(self):
        from pydantic import ValidationError

        from core.schemas.dataset import DatasetCreate

        # Omitted entirely
        with pytest.raises(ValidationError):
            DatasetCreate(name="Test", slug="test-ds")

        # Empty dict is also rejected
        with pytest.raises(ValidationError):
            DatasetCreate(name="Test", slug="test-ds", data_schema={})

    def test_dataset_update_partial(self):
        from core.schemas.dataset import DatasetUpdate

        update = DatasetUpdate(name="New Name")
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {"name": "New Name"}

    def test_dataset_version_response_from_attributes(self):
        from core.schemas.dataset import DatasetVersionResponse

        # Verify the model_config allows from_attributes
        assert DatasetVersionResponse.model_config.get("from_attributes") is True
