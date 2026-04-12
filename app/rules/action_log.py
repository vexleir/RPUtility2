from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import ActionLogEntry


class ActionLogStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, entry: ActionLogEntry) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO action_logs
                    (id, campaign_id, scene_id, actor_name, action_type, source, summary, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id, entry.campaign_id, entry.scene_id, entry.actor_name,
                    entry.action_type, entry.source, entry.summary,
                    json_encode(entry.details), entry.created_at.isoformat(),
                ),
            )

    def get_recent(self, campaign_id: str, n: int = 20) -> list[ActionLogEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM action_logs WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
                (campaign_id, n),
            ).fetchall()
        return [_row_to_action_log(r) for r in rows]

    def get_recent_for_scene(self, campaign_id: str, scene_id: str, n: int = 20) -> list[ActionLogEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                """
                SELECT * FROM action_logs
                WHERE campaign_id=? AND scene_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (campaign_id, scene_id, n),
            ).fetchall()
        return [_row_to_action_log(r) for r in rows]


def _row_to_action_log(row) -> ActionLogEntry:
    return ActionLogEntry(
        id=row["id"],
        campaign_id=row["campaign_id"],
        scene_id=row["scene_id"],
        actor_name=row["actor_name"],
        action_type=row["action_type"],
        source=row["source"],
        summary=row["summary"],
        details=json_decode(row["details"]) or {},
        created_at=datetime.fromisoformat(row["created_at"]),
    )

