"""Business logic for document integrity monitoring and reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.repositories.integrity_repository import DocumentEvent, IntegrityRepository
from app.schemas.integrity import (
    AuditLogEntry,
    AuditResponse,
    ConflictRecord,
    DocumentEventCreateRequest,
    DocumentEventResponse,
    ResolvedState,
    TamperingAlert,
)
from app.services.reconciliation_engine import ReconciliationEngine, ReconciliationResult


class IntegrityError(Exception):
    """Base class for integrity monitoring domain errors."""


class InvalidTimestampError(IntegrityError):
    """Raised when event timestamp is invalid."""


class EventAlreadyExistsError(IntegrityError):
    """Raised when duplicate event_id is encountered."""


class AuditNotFoundError(IntegrityError):
    """Raised when no audit exists for a document."""


class IntegrityService:
    """Coordinate event ingestion, reconciliation, and audit persistence."""

    def __init__(self, repository: IntegrityRepository, engine: ReconciliationEngine) -> None:
        self._repository = repository
        self._engine = engine

    def ingest_event(self, payload: DocumentEventCreateRequest) -> DocumentEventResponse:
        """
        Process incoming event with validation and reconciliation.

        Returns:
            DocumentEventResponse with status "accepted" or "duplicate"

        Raises:
            InvalidTimestampError: if timestamp is invalid
        """
        # Validate timestamp (within 24 hours window)
        self._validate_timestamp(payload.event_timestamp)

        # Normalize event for repository storage
        event_data = self._normalize_event(payload)

        # Check if event_id already exists (idempotency)
        existing = self._repository.get_event_by_id(payload.event_id)
        if existing:
            return DocumentEventResponse(
                event_id=payload.event_id,
                document_id=payload.document_id,
                status="duplicate",
                message="Event already processed (idempotent)",
            )

        try:
            # Insert the new event
            inserted = self._repository.insert_event(event_data)
            if not inserted:
                # This shouldn't happen if idempotency check passed, but handle gracefully
                return DocumentEventResponse(
                    event_id=payload.event_id,
                    document_id=payload.document_id,
                    status="duplicate",
                    message="Event already processed (idempotent)",
                )

            # Retrieve all events for the document and reconcile
            all_events = self._repository.get_events_by_document(payload.document_id)
            reconciliation_result = self._engine.reconcile(all_events)

            # Persist the audit snapshot
            audit_snapshot_data = self._audit_snapshot_from_result(
                payload.document_id, reconciliation_result
            )
            self._repository.upsert_audit_snapshot(audit_snapshot_data)

            # Commit the transaction
            self._repository.commit()

            return DocumentEventResponse(
                event_id=payload.event_id,
                document_id=payload.document_id,
                status="accepted",
                message="Event accepted and reconciled",
            )
        except Exception as error:
            self._repository.rollback()
            raise

    def get_audit(self, document_id: str) -> AuditResponse:
        """
        Retrieve the current audit snapshot for a document.

        Raises:
            AuditNotFoundError: if no audit exists for the document
        """
        snapshot = self._repository.get_audit_snapshot(document_id)
        if snapshot is None:
            raise AuditNotFoundError(f"No audit exists for document {document_id}")

        # Parse JSON fields from snapshot (stored as JSON strings in database)
        import json
        resolved_data = json.loads(snapshot.resolved) if isinstance(snapshot.resolved, str) else snapshot.resolved
        conflicts_data = json.loads(snapshot.conflicts) if isinstance(snapshot.conflicts, str) else snapshot.conflicts
        alerts_data = json.loads(snapshot.tampering_alerts) if isinstance(snapshot.tampering_alerts, str) else snapshot.tampering_alerts
        audit_log_data = json.loads(snapshot.audit_log) if isinstance(snapshot.audit_log, str) else snapshot.audit_log

        # Reconstruct typed response from snapshot data
        return AuditResponse(
            document_id=snapshot.document_id,
            resolved=ResolvedState(**resolved_data),
            conflicts=[ConflictRecord(**conflict) for conflict in conflicts_data],
            tampering_alerts=[
                TamperingAlert(**alert) for alert in alerts_data
            ],
            audit_log=[AuditLogEntry(**entry) for entry in audit_log_data],
            event_count=snapshot.event_count,
        )

    # ========== Private: Validation ==========

    @staticmethod
    def _validate_timestamp(ts: datetime) -> None:
        """
        Validate that timestamp is within 24 hours from now.

        Rejects future timestamps and timestamps older than 24 hours.

        Raises:
            InvalidTimestampError
        """
        now = datetime.now(timezone.utc) if ts.tzinfo else datetime.now()
        window_start = now - timedelta(hours=24)
        window_end = now

        if ts > window_end:
            raise InvalidTimestampError("Event timestamp cannot be in the future")
        if ts < window_start:
            raise InvalidTimestampError("Event timestamp is older than 24 hours")

    # ========== Private: Normalization ==========

    @staticmethod
    def _normalize_event(payload: DocumentEventCreateRequest) -> Mapping[str, Any]:
        """
        Normalize request event to repository insertion format.

        Converts metadata to JSON if needed, ensures all required fields are present.
        """
        # Serialize metadata to JSON for storage
        metadata_json = None
        if payload.metadata:
            metadata_json = json.dumps(payload.metadata) if isinstance(payload.metadata, dict) else payload.metadata

        # Use model_dump_json() for proper JSON serialization with datetime handling
        normalized_payload_json = payload.model_dump_json()

        return {
            "event_id": payload.event_id,
            "document_id": payload.document_id,
            "event_type": payload.event_type,
            "user_id": payload.user_id,
            "event_timestamp": payload.event_timestamp,
            "content": payload.content,
            "metadata": metadata_json,
            "source": payload.source,
            "normalized_payload": normalized_payload_json,
        }

    # ========== Private: Audit Snapshot Construction ==========

    @staticmethod
    def _audit_snapshot_from_result(
        document_id: str, result: ReconciliationResult
    ) -> Mapping[str, Any]:
        """Convert ReconciliationResult to audit snapshot storage format."""
        return {
            "document_id": document_id,
            "resolved": json.dumps(result.resolved),
            "conflicts": json.dumps(result.conflicts),
            "tampering_alerts": json.dumps(result.tampering_alerts),
            "audit_log": json.dumps(result.audit_log),
            "event_count": result.event_count,
        }
