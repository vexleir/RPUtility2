from __future__ import annotations

from app.core.models import CharacterSheet


def apply_sheet_state_change(
    sheet: CharacterSheet,
    *,
    damage: int = 0,
    healing: int = 0,
    temp_hp_delta: int = 0,
    add_conditions: list[str] | None = None,
    remove_conditions: list[str] | None = None,
    notes_append: str = "",
) -> tuple[CharacterSheet, str]:
    updated = sheet.model_copy(deep=True)
    add_conditions = [c.strip() for c in (add_conditions or []) if c and c.strip()]
    remove_conditions = [c.strip().lower() for c in (remove_conditions or []) if c and c.strip()]

    if damage > 0:
        absorbed = min(updated.temp_hp, damage)
        remaining = damage - absorbed
        updated.temp_hp = max(0, updated.temp_hp - absorbed)
        updated.current_hp = max(0, updated.current_hp - remaining)

    if healing > 0:
        updated.current_hp = min(updated.max_hp, updated.current_hp + healing)

    if temp_hp_delta:
        updated.temp_hp = max(0, updated.temp_hp + temp_hp_delta)

    conditions = list(updated.conditions or [])
    existing_lut = {condition.lower(): condition for condition in conditions}

    for condition in add_conditions:
        key = condition.lower()
        if key not in existing_lut:
            conditions.append(condition)
            existing_lut[key] = condition

    if remove_conditions:
        conditions = [condition for condition in conditions if condition.lower() not in remove_conditions]

    updated.conditions = conditions

    note = notes_append.strip()
    if note:
        updated.notes = f"{updated.notes}\n{note}".strip() if updated.notes else note

    summary_parts: list[str] = []
    if damage > 0:
        summary_parts.append(f"took {damage} damage")
    if healing > 0:
        summary_parts.append(f"recovered {healing} HP")
    if temp_hp_delta > 0:
        summary_parts.append(f"gained {temp_hp_delta} temp HP")
    elif temp_hp_delta < 0:
        summary_parts.append(f"lost {abs(temp_hp_delta)} temp HP")
    if add_conditions:
        summary_parts.append("gained conditions: " + ", ".join(add_conditions))
    removed_labels = [condition for condition in (remove_conditions or []) if condition]
    if removed_labels:
        summary_parts.append("removed conditions: " + ", ".join(removed_labels))
    if note:
        summary_parts.append(f"note: {note}")

    summary = "; ".join(summary_parts) if summary_parts else "updated sheet state"
    return updated, summary
