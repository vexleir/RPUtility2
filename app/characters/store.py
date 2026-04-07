from __future__ import annotations

from datetime import datetime, UTC

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import CharacterSheet


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class CharacterSheetStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, sheet: CharacterSheet) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO character_sheets
                    (id, campaign_id, owner_type, owner_id, name, ancestry, character_class,
                     background, level, proficiency_bonus, abilities, skill_modifiers,
                     save_modifiers, max_hp, current_hp, temp_hp, armor_class, speed,
                     currencies, conditions, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    owner_type=excluded.owner_type,
                    owner_id=excluded.owner_id,
                    name=excluded.name,
                    ancestry=excluded.ancestry,
                    character_class=excluded.character_class,
                    background=excluded.background,
                    level=excluded.level,
                    proficiency_bonus=excluded.proficiency_bonus,
                    abilities=excluded.abilities,
                    skill_modifiers=excluded.skill_modifiers,
                    save_modifiers=excluded.save_modifiers,
                    max_hp=excluded.max_hp,
                    current_hp=excluded.current_hp,
                    temp_hp=excluded.temp_hp,
                    armor_class=excluded.armor_class,
                    speed=excluded.speed,
                    currencies=excluded.currencies,
                    conditions=excluded.conditions,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    sheet.id, sheet.campaign_id, sheet.owner_type, sheet.owner_id, sheet.name,
                    sheet.ancestry, sheet.character_class, sheet.background,
                    sheet.level, sheet.proficiency_bonus,
                    json_encode(sheet.abilities), json_encode(sheet.skill_modifiers),
                    json_encode(sheet.save_modifiers),
                    sheet.max_hp, sheet.current_hp, sheet.temp_hp,
                    sheet.armor_class, sheet.speed,
                    json_encode(sheet.currencies), json_encode(sheet.conditions),
                    sheet.notes, sheet.created_at.isoformat(), sheet.updated_at.isoformat(),
                ),
            )

    def get(self, sheet_id: str) -> CharacterSheet | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM character_sheets WHERE id=?",
                (sheet_id,),
            ).fetchone()
        return _row_to_sheet(row) if row else None

    def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player") -> CharacterSheet | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM character_sheets WHERE campaign_id=? AND owner_type=? AND owner_id=?",
                (campaign_id, owner_type, owner_id),
            ).fetchone()
        return _row_to_sheet(row) if row else None

    def get_all(self, campaign_id: str) -> list[CharacterSheet]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM character_sheets WHERE campaign_id=? ORDER BY owner_type, name",
                (campaign_id,),
            ).fetchall()
        return [_row_to_sheet(r) for r in rows]

    def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs) -> CharacterSheet:
        sheet = self.get_for_owner(campaign_id, owner_type, owner_id)
        if not sheet:
            sheet = CharacterSheet(campaign_id=campaign_id, owner_type=owner_type, owner_id=owner_id)
        for key, value in kwargs.items():
            if hasattr(sheet, key) and value is not None:
                setattr(sheet, key, value)
        sheet.updated_at = _now()
        self.save(sheet)
        return sheet


def _row_to_sheet(row) -> CharacterSheet:
    return CharacterSheet(
        id=row["id"],
        campaign_id=row["campaign_id"],
        owner_type=row["owner_type"],
        owner_id=row["owner_id"],
        name=row["name"],
        ancestry=row["ancestry"],
        character_class=row["character_class"],
        background=row["background"],
        level=row["level"],
        proficiency_bonus=row["proficiency_bonus"],
        abilities=json_decode(row["abilities"]) or {},
        skill_modifiers=json_decode(row["skill_modifiers"]) or {},
        save_modifiers=json_decode(row["save_modifiers"]) or {},
        max_hp=row["max_hp"],
        current_hp=row["current_hp"],
        temp_hp=row["temp_hp"],
        armor_class=row["armor_class"],
        speed=row["speed"],
        currencies=json_decode(row["currencies"]) or {},
        conditions=json_decode(row["conditions"]) or [],
        notes=row["notes"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )

