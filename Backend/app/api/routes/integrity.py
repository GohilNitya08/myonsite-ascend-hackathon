"""Document integrity monitoring HTTP endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.repositories.integrity_repository import IntegrityRepository
from app.schemas.integrity import AuditResponse, DocumentEventCreateRequest, DocumentEventResponse
from app.services.integrity_service import (
    AuditNotFoundError,
    IntegrityService,
    InvalidTimestampError,
)
from app.services.reconciliation_engine import ReconciliationEngine

router = APIRouter(tags=["integrity"])
DocumentId = Annotated[str, Path(min_length=1, max_length=255)]


def get_integrity_service(
    db: Annotated[Session, Depends(get_db)],
) -> IntegrityService:
    """Build the request-scoped integrity service."""
    repository = IntegrityRepository(db)
    engine = ReconciliationEngine()
    return IntegrityService(repository, engine)


@router.post(
    "/events",
    response_model=DocumentEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a document event",
)
def ingest_event(
    payload: DocumentEventCreateRequest,
    service: Annotated[IntegrityService, Depends(get_integrity_service)],
) -> DocumentEventResponse:
    """
    Accept a document operation event for integrity monitoring.

    Required fields:
    - event_id: Unique identifier (required for idempotency)
    - document_id: Document being modified
    - event_type: One of edit, delete, metadata_update, comment, share
    - user_id: User performing the action
    - event_timestamp: ISO 8601 timestamp (UTC, within 24 hours)
    - source: Event source (e.g., web, mobile, sync)

    Optional fields:
    - content: For edit events
    - metadata: JSON metadata for metadata_update events

    Returns 202 Accepted for new events, 200 OK for duplicate (idempotent).
    """
    try:
        return service.ingest_event(payload)
    except InvalidTimestampError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


@router.get(
    "/audit/{document_id}",
    response_model=AuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Get document audit trail",
)
def get_audit(
    document_id: DocumentId,
    service: Annotated[IntegrityService, Depends(get_integrity_service)],
) -> AuditResponse:
    """
    Retrieve the complete audit trail and resolved state for a document.

    Returns:
    - resolved: Final document state (content, metadata, is_deleted, version)
    - conflicts: List of detected conflicts with resolution details
    - tampering_alerts: List of suspicious events
    - audit_log: Chronological record of all processing decisions
    - event_count: Total number of unique events processed

    Returns 404 Not Found if no events have been processed for this document.
    """
    try:
        return service.get_audit(document_id)
    except AuditNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit found for document {document_id}",
        ) from error
