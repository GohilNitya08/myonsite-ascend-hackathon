"""SQLAlchemy data access for document integrity monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class DocumentEvent:
    """Immutable event record from document_events table."""

    event_id: str
    document_id: str
    event_type: str
    user_id: str
    event_timestamp: datetime
    content: str | None
    metadata: dict[str, Any] | None
    source: str
    normalized_payload: dict[str, Any]
    ingested_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DocumentEvent":
        """Create a DocumentEvent from a SQLAlchemy mapping result."""
        return cls(
            event_id=str(row["event_id"]),
            document_id=str(row["document_id"]),
            event_type=str(row["event_type"]),
            user_id=str(row["user_id"]),
            event_timestamp=row["event_timestamp"],
            content=_optional_string(row["content"]),
            metadata=row["metadata"],
            source=str(row["source"]),
            normalized_payload=row["normalized_payload"],
            ingested_at=row["ingested_at"],
        )


@dataclass(frozen=True, slots=True)
class DocumentAuditSnapshot:
    """Current audit snapshot for a document."""

    document_id: str
    resolved: dict[str, Any]
    conflicts: list[dict[str, Any]]
    tampering_alerts: list[dict[str, Any]]
    audit_log: list[dict[str, Any]]
    event_count: int
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DocumentAuditSnapshot":
        """Create a snapshot from a SQLAlchemy mapping result."""
        return cls(
            document_id=str(row["document_id"]),
            resolved=row["resolved"],
            conflicts=row["conflicts"],
            tampering_alerts=row["tampering_alerts"],
            audit_log=row["audit_log"],
            event_count=int(row["event_count"]),
            updated_at=row["updated_at"],
        )


class IntegrityRepository:
    """Encapsulate document event and audit snapshot persistence."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def insert_event(self, event_data: Mapping[str, Any]) -> bool:
        """
        Insert a document event with idempotency via event_id.

        Returns True if inserted. Returns False if event_id already exists (duplicate).
        If a database error occurs (other than duplicate key), raises the exception.
        """
        event_id = event_data["event_id"]

        # Explicitly check if event_id already exists
        existing = self._db.execute(
            text("SELECT 1 FROM document_events WHERE event_id = :event_id LIMIT 1"),
            {"event_id": event_id},
        ).scalar()

        if existing:
            # Duplicate event - idempotent no-op
            return False

        # Event doesn't exist, insert it (let any database errors propagate)
        self._db.execute(
            text(
                """
                INSERT INTO document_events (
                    event_id, document_id, event_type, user_id, event_timestamp,
                    content, metadata, source, normalized_payload
                ) VALUES (
                    :event_id, :document_id, :event_type, :user_id, :event_timestamp,
                    :content, :metadata, :source, :normalized_payload
                )
                """
            ),
            event_data,
        )
        return True

    def get_event_by_id(self, event_id: str) -> DocumentEvent | None:
        """Retrieve a single event by event_id."""
        row = (
            self._db.execute(
                text(
                    """
                    SELECT event_id, document_id, event_type, user_id, event_timestamp,
                           content, metadata, source, normalized_payload, ingested_at
                    FROM document_events
                    WHERE event_id = :event_id
                    LIMIT 1
                    """
                ),
                {"event_id": event_id},
            )
            .mappings()
            .first()
        )
        return DocumentEvent.from_row(row) if row else None

    def get_events_by_document(self, document_id: str) -> list[DocumentEvent]:
        """
        Retrieve all events for a document in stable order (event_timestamp, then event_id).

        The reconciliation engine owns authoritative sorting per PRD:
        - event_timestamp ascending
        - source priority: web < mobile < sync < other
        - user_id lexicographic ascending
        """
        rows = (
            self._db.execute(
                text(
                    """
                    SELECT event_id, document_id, event_type, user_id, event_timestamp,
                           content, metadata, source, normalized_payload, ingested_at
                    FROM document_events
                    WHERE document_id = :document_id
                    ORDER BY event_timestamp ASC, event_id ASC
                    """
                ),
                {"document_id": document_id},
            )
            .mappings()
            .all()
        )
        return [DocumentEvent.from_row(row) for row in rows]

    def get_audit_snapshot(
        self, document_id: str
    ) -> DocumentAuditSnapshot | None:
        """Retrieve the current audit snapshot for a document."""
        row = (
            self._db.execute(
                text(
                    """
                    SELECT document_id, resolved, conflicts, tampering_alerts,
                           audit_log, event_count, updated_at
                    FROM document_audit_snapshots
                    WHERE document_id = :document_id
                    LIMIT 1
                    """
                ),
                {"document_id": document_id},
            )
            .mappings()
            .first()
        )
        return DocumentAuditSnapshot.from_row(row) if row else None

    def upsert_audit_snapshot(self, snapshot_data: Mapping[str, Any]) -> bool:
        """
        Insert or update an audit snapshot via INSERT ... ON DUPLICATE KEY UPDATE.

        Returns True on success. If a database error occurs, the exception propagates.
        Expected keys: document_id, resolved, conflicts, tampering_alerts,
                       audit_log, event_count
        """
        self._db.execute(
            text(
                """
                INSERT INTO document_audit_snapshots (
                    document_id, resolved, conflicts, tampering_alerts,
                    audit_log, event_count
                ) VALUES (
                    :document_id, :resolved, :conflicts, :tampering_alerts,
                    :audit_log, :event_count
                )
                ON DUPLICATE KEY UPDATE
                    resolved = :resolved,
                    conflicts = :conflicts,
                    tampering_alerts = :tampering_alerts,
                    audit_log = :audit_log,
                    event_count = :event_count,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            snapshot_data,
        )
        return True

    def commit(self) -> None:
        """Commit the current transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self._db.rollback()


def _optional_string(value: Any) -> str | None:
    """Convert a value to string, or None if falsy."""
    return str(value) if value else None
