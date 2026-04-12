from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import Encounter, EncounterParticipant


class EncounterStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, encounter: Encounter) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO encounters
                    (id, campaign_id, scene_id, name, status, round_number, current_turn_index,
                     participants, encounter_log, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    scene_id=excluded.scene_id,
                    name=excluded.name,
                    status=excluded.status,
                    round_number=excluded.round_number,
                    current_turn_index=excluded.current_turn_index,
                    participants=excluded.participants,
                    encounter_log=excluded.encounter_log,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at
                """,
                (
                    encounter.id,
                    encounter.campaign_id,
                    encounter.scene_id,
                    encounter.name,
                    encounter.status,
                    encounter.round_number,
                    encounter.current_turn_index,
                    json_encode([participant.model_dump() for participant in encounter.participants]),
                    json_encode(encounter.encounter_log),
                    encounter.summary,
                    encounter.created_at.isoformat(),
                    encounter.updated_at.isoformat(),
                ),
            )

    def get(self, encounter_id: str) -> Encounter | None:
        with get_connection(self._db) as conn:
            row = conn.execute("SELECT * FROM encounters WHERE id=?", (encounter_id,)).fetchone()
        return _row_to_encounter(row) if row else None

    def get_all(self, campaign_id: str) -> list[Encounter]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM encounters WHERE campaign_id=? ORDER BY created_at DESC",
                (campaign_id,),
            ).fetchall()
        return [_row_to_encounter(row) for row in rows]

    def get_active(self, campaign_id: str, scene_id: str | None = None) -> Encounter | None:
        query = "SELECT * FROM encounters WHERE campaign_id=? AND status='active'"
        params: list[str] = [campaign_id]
        if scene_id is not None:
            query += " AND scene_id=?"
            params.append(scene_id)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with get_connection(self._db) as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return _row_to_encounter(row) if row else None


def _row_to_encounter(row) -> Encounter:
    participants = [
        EncounterParticipant(**payload)
        for payload in (json_decode(row["participants"]) or [])
    ]
    return Encounter(
        id=row["id"],
        campaign_id=row["campaign_id"],
        scene_id=row["scene_id"],
        name=row["name"],
        status=row["status"],
        round_number=row["round_number"],
        current_turn_index=row["current_turn_index"],
        participants=participants,
        encounter_log=json_decode(row["encounter_log"]) or [],
        summary=row["summary"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
