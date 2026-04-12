from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import RuleAuditEvent


class RuleAuditStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, event: RuleAuditEvent) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO rule_audit_events
                    (id, campaign_id, scene_id, event_type, actor_name, source, reason, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.campaign_id,
                    event.scene_id,
                    event.event_type,
                    event.actor_name,
                    event.source,
                    event.reason,
                    json_encode(event.payload),
                    event.created_at.isoformat(),
                ),
            )

    def get_recent(self, campaign_id: str, n: int = 50) -> list[RuleAuditEvent]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM rule_audit_events WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
                (campaign_id, n),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def get_recent_filtered(
        self,
        campaign_id: str,
        *,
        scene_id: str | None = None,
        event_type: str | None = None,
        n: int = 50,
    ) -> list[RuleAuditEvent]:
        query = "SELECT * FROM rule_audit_events WHERE campaign_id=?"
        params: list = [campaign_id]
        if scene_id is not None:
            query += " AND scene_id=?"
            params.append(scene_id)
        if event_type is not None:
            query += " AND event_type=?"
            params.append(event_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(n)
        with get_connection(self._db) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_row_to_event(row) for row in rows]


def _row_to_event(row) -> RuleAuditEvent:
    return RuleAuditEvent(
        id=row["id"],
        campaign_id=row["campaign_id"],
        scene_id=row["scene_id"],
        event_type=row["event_type"],
        actor_name=row["actor_name"],
        source=row["source"],
        reason=row["reason"],
        payload=json_decode(row["payload"]) or {},
        created_at=datetime.fromisoformat(row["created_at"]),
    )
