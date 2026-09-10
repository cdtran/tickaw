"""Bounded raw-body CSV uploads: no multipart spool before size validation."""
import unicodedata
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.schemas.dataset import DatasetResponse
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])
CSV_MIME_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}


def validate_filename(filename: str) -> None:
    if (not filename or len(filename.encode("utf-8")) > 255
            or filename != filename.strip() or "/" in filename or "\\" in filename
            or any(unicodedata.category(char).startswith("C") for char in filename)
            or not filename.lower().endswith(".csv") or not filename[:-4].strip(" .")):
        raise HTTPException(422, "Use a plain filename ending in .csv (maximum 255 UTF-8 bytes).")


@router.get("/upload-config")
def upload_config() -> dict[str, int]:
    return {"max_upload_bytes": get_settings().max_upload_bytes}


@router.get("", response_model=list[DatasetResponse])
def get_datasets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    with get_session_factory()() as session:
        return dataset_service.list_datasets(session, offset, limit)


@router.post("/uploads", response_model=DatasetResponse, status_code=201)
async def upload(request: Request, filename: str = Query(..., max_length=255),
                 dataset_id: UUID | None = None):
    validate_filename(filename)
    mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in CSV_MIME_TYPES:
        raise HTTPException(415, "Use a CSV MIME type: text/csv, application/csv, text/plain, or application/vnd.ms-excel.")
    maximum = get_settings().max_upload_bytes
    declared_size = request.headers.get("content-length")
    if declared_size is not None:
        try:
            length = int(declared_size)
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length.") from None
        if length < 0:
            raise HTTPException(400, "Invalid Content-Length.")
        if length > maximum:
            raise HTTPException(413, f"CSV exceeds the {maximum}-byte upload limit.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(413, f"CSV exceeds the {maximum}-byte upload limit.")
        body.extend(chunk)
    if not body:
        raise HTTPException(422, "The CSV file is empty.")
    # MIME and extensions are claims. Reject binary/non-UTF-8 files before storage;
    # CSV structure, schema and parsing limits belong to the ingestion milestone.
    try:
        decoded = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Save the CSV with UTF-8 encoding and try again.") from None
    if not decoded.strip() or any(ord(char) < 32 and char not in "\t\r\n" for char in decoded):
        raise HTTPException(422, "The CSV must contain text, without binary control characters.")

    def persist():
        with get_session_factory()() as session:
            return dataset_service.upload_csv(session, filename, bytes(body), dataset_id)

    # Boto3 and SQLAlchemy are synchronous; keep their I/O off the async event loop.
    return await run_in_threadpool(persist)
