"""Admin routes for the API Gateway — platform-level operations.

Endpoints here are accessible only to users with the ``platform_admin`` role.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth.dependencies import get_current_superuser
from core.models.common import TokenPayload
from core.storage import get_object_store

logger = logging.getLogger(__name__)

router = APIRouter()


class FileRef(BaseModel):
    bucket: str
    key: str


class BulkDeleteRequest(BaseModel):
    files: list[FileRef]


class BulkDeleteResponse(BaseModel):
    deleted: list[str]
    errors: list[dict[str, Any]]


@router.post("/admin/storage/files/delete")
async def bulk_delete_storage_files(
    request: BulkDeleteRequest,
    _admin: TokenPayload = Depends(get_current_superuser),
) -> BulkDeleteResponse:
    """Delete multiple files from the object store in bulk.

    Requires ``platform_admin`` role.
    """
    store = get_object_store()
    deleted: list[str] = []
    errors: list[dict[str, Any]] = []

    for f in request.files:
        try:
            store.delete(f.bucket, f.key)
            deleted.append(f"{f.bucket}/{f.key}")
        except Exception as e:
            logger.warning("Failed to delete %s/%s: %s", f.bucket, f.key, e)
            errors.append({"bucket": f.bucket, "key": f.key, "error": str(e)})

    return BulkDeleteResponse(deleted=deleted, errors=errors)
