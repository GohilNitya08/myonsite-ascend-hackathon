"""Pydantic models for document integrity monitoring requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


EventId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
DocumentId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
EventType = Annotated[str, StringConstraints(strip_whitespace=True)]


class DocumentEventCreateRequest(BaseModel):
    """Incoming event for document integrity monitoring."""

    model_config = ConfigDict(extra="forbid")

    event_id: EventId
    document_id: DocumentId
    event_type: EventType
    user_id: UserId
    event_timestamp: datetime = Field(description="ISO 8601 datetime (UTC)")
    content: str | None = None
    metadata: dict[str, Any] | None = None
    source: Source

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Ensure event_type is one of the allowed values."""
        allowed = {"edit", "delete", "metadata_update", "comment", "share"}
        if v not in allowed:
            raise ValueError(f"event_type must be one of {allowed}")
        return v


class DocumentEventResponse(BaseModel):
    """Response after event ingestion."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    document_id: str
    status: str  # "accepted" or "duplicate"
    message: str


class ResolvedState(BaseModel):
    """Resolved document state."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    metadata: dict[str, Any]
    is_deleted: bool
    version: int


class ConflictRecord(BaseModel):
    """A conflict group with resolution details."""

    model_config = ConfigDict(extra="forbid")

    events: list[str]
    winner: str
    reason: str


class TamperingAlert(BaseModel):
    """A suspicious event flag."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    reason: str


class AuditLogEntry(BaseModel):
    """Single audit log entry."""

    model_config = ConfigDict(extra="forbid")

    step: str
    event_id: str
    detail: str
    timestamp: str | None = None


class AuditResponse(BaseModel):
    """Complete audit trail for a document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    resolved: ResolvedState
    conflicts: list[ConflictRecord]
    tampering_alerts: list[TamperingAlert]
    audit_log: list[AuditLogEntry]
    event_count: int
