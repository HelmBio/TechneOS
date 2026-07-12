"""Tests for the MinIO/S3 object storage abstraction."""

import io
from unittest.mock import MagicMock, patch

import pytest

from core.storage import MinIOStore, ObjectInfo, ObjectStore, get_object_store


class TestObjectInfo:
    def test_basic_fields(self):
        info = ObjectInfo(bucket="test", key="file.csv", size=1024)
        assert info.bucket == "test"
        assert info.key == "file.csv"
        assert info.size == 1024
        assert info.content_type is None
        assert info.metadata == {}

    def test_full_fields(self):
        info = ObjectInfo(
            bucket="b",
            key="k",
            size=100,
            content_type="text/csv",
            metadata={"user": "u1"},
            last_modified="2025-01-01",
        )
        assert info.content_type == "text/csv"
        assert info.metadata == {"user": "u1"}


class TestMinIOStore:
    @patch("core.storage.get_settings")
    @patch("core.storage.MinIOStore.__init__", return_value=None)
    def _make_store(self, mock_init, mock_settings):
        store = MinIOStore.__new__(MinIOStore)
        store._client = MagicMock()
        store._default_bucket = "test-bucket"
        return store

    def test_put_uploads_and_ensures_bucket(self):
        store = self._make_store()
        store._client.bucket_exists.return_value = False
        data = io.BytesIO(b"hello")

        result = store.put("mybucket", "key.txt", data, 5, content_type="text/plain")

        assert result == "key.txt"
        store._client.make_bucket.assert_called_once_with("mybucket")
        store._client.put_object.assert_called_once_with(
            bucket_name="mybucket",
            object_name="key.txt",
            data=data,
            length=5,
            content_type="text/plain",
            metadata=None,
        )

    def test_put_skips_bucket_creation_if_exists(self):
        store = self._make_store()
        store._client.bucket_exists.return_value = True
        data = io.BytesIO(b"x")

        store.put("mybucket", "k", data, 1)
        store._client.make_bucket.assert_not_called()

    def test_get_returns_bytes(self):
        store = self._make_store()
        mock_response = MagicMock()
        mock_response.read.return_value = b"file content"
        store._client.get_object.return_value = mock_response

        result = store.get("bucket", "key")
        assert result == b"file content"
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    def test_get_raises_storage_error(self):
        from core.exceptions import StorageError

        store = self._make_store()
        store._client.get_object.side_effect = Exception("not found")

        with pytest.raises(StorageError, match="Failed to get object"):
            store.get("bucket", "missing")

    def test_delete_calls_remove(self):
        store = self._make_store()
        store.delete("bucket", "key")
        store._client.remove_object.assert_called_once_with("bucket", "key")

    def test_presigned_url(self):
        store = self._make_store()
        store._client.presigned_get_object.return_value = "https://minio/signed"

        url = store.presigned_url("bucket", "key", expires_seconds=7200)
        assert url == "https://minio/signed"
        store._client.presigned_get_object.assert_called_once()

    def test_list_objects(self):
        store = self._make_store()
        mock_obj = MagicMock()
        mock_obj.object_name = "data/file.csv"
        mock_obj.size = 2048
        mock_obj.content_type = "text/csv"
        mock_obj.last_modified = None
        store._client.list_objects.return_value = [mock_obj]

        result = store.list_objects("bucket", prefix="data/")
        assert len(result) == 1
        assert result[0].key == "data/file.csv"
        assert result[0].size == 2048

    def test_ensure_bucket_creates_when_missing(self):
        store = self._make_store()
        store._client.bucket_exists.return_value = False
        store.ensure_bucket("new-bucket")
        store._client.make_bucket.assert_called_once_with("new-bucket")

    def test_ensure_bucket_noop_when_exists(self):
        store = self._make_store()
        store._client.bucket_exists.return_value = True
        store.ensure_bucket("existing")
        store._client.make_bucket.assert_not_called()


class TestGetObjectStore:
    @patch("core.storage._store", None)
    @patch("core.storage.get_settings")
    @patch("minio.Minio")
    def test_returns_singleton(self, mock_minio, mock_settings):
        settings = MagicMock()
        settings.minio_endpoint = "localhost:9000"
        settings.minio_access_key = "key"
        settings.minio_secret_key = "secret"
        settings.minio_secure = False
        settings.minio_bucket = "techneos"
        mock_settings.return_value = settings

        store = get_object_store()
        assert isinstance(store, MinIOStore)


class TestObjectStoreProtocol:
    def test_minio_store_implements_protocol(self):
        """MinIOStore should satisfy the ObjectStore protocol."""
        assert issubclass(MinIOStore, ObjectStore)
