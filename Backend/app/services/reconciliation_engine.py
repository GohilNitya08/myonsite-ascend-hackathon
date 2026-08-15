"""Pure document reconciliation and conflict detection engine.

This module implements deterministic document state reconstruction from event logs.
It is stateless, database-free, and produces identical results regardless of event arrival order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.repositories.integrity_repository import DocumentEvent


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Output of the reconciliation engine after replaying events."""

    resolved: dict[str, Any]
    """Final document state: {content, metadata, is_deleted, version}."""

    conflicts: list[dict[str, Any]]
    """Detected conflicting edit groups with resolution details."""

    tampering_alerts: list[dict[str, Any]]
    """Events flagged as suspicious (e.g., sync source without user confirmation)."""

    audit_log: list[dict[str, Any]]
    """Chronological record of all events processed and decisions made."""

    event_count: int
    """Total number of unique events processed."""


class ReconciliationEngine:
    """Orchestrate deterministic document state reconstruction and conflict resolution."""

    def reconcile(self, events: list[DocumentEvent]) -> ReconciliationResult:
        """
        Reconstruct final document state from event log.

        Args:
            events: List of document events (in any order).

        Returns:
            ReconciliationResult with resolved state, conflicts, tampering, and audit trail.

        The result is deterministic: same events produce same result regardless of input order.
        """
        # Deduplicate by event_id (idempotency)
        unique_events = self._deduplicate_by_event_id(events)
        if not unique_events:
            return self._empty_result()

        # Sort deterministically
        sorted_events = self._sort_events_deterministically(unique_events)

        # Full replay
        resolved, conflicts, tampering_alerts, audit_log = self._replay_events(sorted_events)

        return ReconciliationResult(
            resolved=resolved,
            conflicts=conflicts,
            tampering_alerts=tampering_alerts,
            audit_log=audit_log,
            event_count=len(unique_events),
        )

    # ========== Private: Deduplication ==========

    @staticmethod
    def _deduplicate_by_event_id(events: list[DocumentEvent]) -> list[DocumentEvent]:
        """Return unique events by event_id, keeping first occurrence."""
        seen = {}
        for event in events:
            if event.event_id not in seen:
                seen[event.event_id] = event
        return list(seen.values())

    # ========== Private: Deterministic Sorting ==========

    @staticmethod
    def _source_priority(source: str) -> int:
        """Return priority for event source (lower = higher priority)."""
        priority_map = {"web": 0, "mobile": 1, "sync": 2}
        return priority_map.get(source, 3)

    def _event_sort_key(self, event: DocumentEvent) -> tuple:
        """Build deterministic sort key for events."""
        return (
            event.event_timestamp,  # 1. Timestamp ascending
            self._source_priority(event.source),  # 2. Source priority (web < mobile < sync < other)
            event.user_id,  # 3. User ID lexicographically
            event.event_id,  # 4. Event ID (final tie-breaker)
        )

    def _sort_events_deterministically(
        self, events: list[DocumentEvent]
    ) -> list[DocumentEvent]:
        """Sort events by PRD deterministic order."""
        return sorted(events, key=self._event_sort_key)

    # ========== Private: Conflict Detection ==========

    @staticmethod
    def _detect_conflict_groups(
        events: list[DocumentEvent],
    ) -> dict[str, list[DocumentEvent]]:
        """
        Identify conflicting EDIT events.

        Two EDITs conflict if timestamps are exactly equal OR within 1 second window.
        Returns dict mapping from a group key to list of conflicting events.
        """
        edit_events = [e for e in events if e.event_type == "edit"]
        groups = {}

        for event in edit_events:
            group_key = None

            # Check if this event overlaps with any existing group
            for existing_key, group_events in groups.items():
                # If any event in the group overlaps with this event, merge them
                if any(
                    abs((event.event_timestamp - e.event_timestamp).total_seconds()) <= 1
                    for e in group_events
                ):
                    group_key = existing_key
                    break

            # If no overlapping group found, create a new one
            if group_key is None:
                group_key = event.event_id

            # Add event to the group
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(event)

        # Return only groups with 2+ events (actual conflicts)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def _resolve_conflict(self, conflict_group: list[DocumentEvent]) -> str:
        """
        Determine winner of a conflict group using PRD rules.

        Rules (in order):
        1. Prefer source: web > mobile > sync > other
        2. If source same, prefer latest timestamp
        3. If timestamp same, prefer lexicographically earlier user_id
        4. If all equal, use event_id as final tie-breaker

        Returns: event_id of the winning event.
        """
        # Sort by (source_priority, timestamp desc, user_id asc, event_id asc)
        winner = min(
            conflict_group,
            key=lambda e: (
                self._source_priority(e.source),  # Lower is better
                -e.event_timestamp.timestamp(),  # Later timestamp (negate for desc)
                e.user_id,  # Earlier user_id (lex)
                e.event_id,  # Earlier event_id
            ),
        )
        return winner.event_id

    # ========== Private: Tampering Detection ==========

    @staticmethod
    def _detect_tampering(event: DocumentEvent) -> bool:
        """
        Check if an EDIT or METADATA_UPDATE event should be flagged as tampering.

        Tampering if: source == "sync" AND metadata.user_confirmed != true
        """
        if event.event_type not in ("edit", "metadata_update"):
            return False

        if event.source != "sync":
            return False

        # Check metadata for user_confirmed flag
        if not event.metadata:
            return True  # No metadata = not confirmed

        return event.metadata.get("user_confirmed") is not True

    # ========== Private: State Transitions ==========

    @staticmethod
    def _initial_state() -> dict[str, Any]:
        """Create the initial document state."""
        return {
            "content": None,
            "metadata": {},
            "is_deleted": False,
            "version": 0,
        }

    def _apply_event_to_state(self, state: dict[str, Any], event: DocumentEvent) -> None:
        """Apply a single event to the document state (in-place mutation)."""
        if event.event_type == "edit":
            state["content"] = event.content
            state["is_deleted"] = False
            state["version"] += 1

        elif event.event_type == "metadata_update":
            # Merge metadata, don't replace
            if event.metadata:
                state["metadata"].update(event.metadata)
            state["version"] += 1

        elif event.event_type == "delete":
            state["is_deleted"] = True
            state["version"] += 1

        # comment and share are audit-only: no state change
        elif event.event_type in ("comment", "share"):
            pass

    # ========== Private: Audit Logging ==========

    @staticmethod
    def _build_audit_entry(
        step: str, event_id: str, detail: str, timestamp: datetime | None = None
    ) -> dict[str, Any]:
        """Build a single audit log entry."""
        entry = {
            "step": step,
            "event_id": event_id,
            "detail": detail,
        }
        if timestamp:
            entry["timestamp"] = timestamp.isoformat()
        return entry

    @staticmethod
    def _build_conflict_entry(
        conflict_group: list[DocumentEvent], winner_id: str, reason: str
    ) -> dict[str, Any]:
        """Build a conflict record for the audit output."""
        return {
            "events": [e.event_id for e in conflict_group],
            "winner": winner_id,
            "reason": reason,
        }

    @staticmethod
    def _build_tampering_alert(event: DocumentEvent) -> dict[str, Any]:
        """Build a tampering alert record."""
        return {
            "event_id": event.event_id,
            "reason": f"{event.event_type} from sync source without user confirmation",
        }

    # ========== Private: Event Replay ==========

    def _replay_events(
        self, events: list[DocumentEvent]
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Replay events in deterministic order to reconstruct final state.

        Returns:
            (resolved_state, conflicts, tampering_alerts, audit_log)
        """
        state = self._initial_state()
        conflicts = []
        tampering_alerts = []
        audit_log = []

        # Detect conflict groups first (all EDITs)
        conflict_groups = self._detect_conflict_groups(events)
        winning_event_ids = set()

        for group_key, conflict_group in conflict_groups.items():
            winner_id = self._resolve_conflict(conflict_group)
            winning_event_ids.add(winner_id)

            # Determine the reason for resolution
            reason = self._conflict_reason(conflict_group, winner_id)

            # Record the conflict
            conflicts.append(self._build_conflict_entry(conflict_group, winner_id, reason))

            # Audit entry
            audit_log.append(
                self._build_audit_entry(
                    step="conflict_resolved",
                    event_id=winner_id,
                    detail=f"Conflict resolved: {reason}",
                )
            )

        # Now apply events in order
        for event in events:
            # Check for tampering (do this regardless of conflicts)
            if self._detect_tampering(event):
                tampering_alerts.append(self._build_tampering_alert(event))
                audit_log.append(
                    self._build_audit_entry(
                        step="tampering_flagged",
                        event_id=event.event_id,
                        detail=f"{event.event_type} from untrusted sync source",
                    )
                )

            # For conflicting EDITs, only apply if this is the winner
            if event.event_type == "edit" and event.event_id in conflict_groups.get(
                event.event_id, []
            ):
                # This is a losing edit in a conflict
                if event.event_id not in winning_event_ids:
                    audit_log.append(
                        self._build_audit_entry(
                            step="event_rejected",
                            event_id=event.event_id,
                            detail="Losing edit in conflict (not applied to state)",
                        )
                    )
                    continue

            # Apply the event to state
            self._apply_event_to_state(state, event)

            # Audit entry for applied event
            if event.event_type in ("comment", "share"):
                audit_log.append(
                    self._build_audit_entry(
                        step="audit_only",
                        event_id=event.event_id,
                        detail=f"{event.event_type} recorded (no state change)",
                        timestamp=event.event_timestamp,
                    )
                )
            else:
                audit_log.append(
                    self._build_audit_entry(
                        step="event_applied",
                        event_id=event.event_id,
                        detail=f"{event.event_type} applied from {event.source}",
                        timestamp=event.event_timestamp,
                    )
                )

        return state, conflicts, tampering_alerts, audit_log

    def _conflict_reason(
        self, conflict_group: list[DocumentEvent], winner_id: str
    ) -> str:
        """Generate a human-readable reason for conflict resolution."""
        winner = next(e for e in conflict_group if e.event_id == winner_id)

        # Determine reason based on resolution priority
        sources = {e.source for e in conflict_group}
        if len(sources) > 1:
            return f"{winner.source} source preferred over other sources"

        # All same source, check timestamp
        timestamps = {e.event_timestamp for e in conflict_group}
        if len(timestamps) > 1:
            return "latest timestamp wins"

        # All same timestamp, check user_id
        user_ids = {e.user_id for e in conflict_group}
        if len(user_ids) > 1:
            return "lexicographically earlier user_id wins"

        return "event_id tie-breaker"

    # ========== Private: Empty Result ==========

    @staticmethod
    def _empty_result() -> ReconciliationResult:
        """Return result for empty event list."""
        return ReconciliationResult(
            resolved=ReconciliationEngine._initial_state(),
            conflicts=[],
            tampering_alerts=[],
            audit_log=[],
            event_count=0,
        )
