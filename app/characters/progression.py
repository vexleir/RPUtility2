from __future__ import annotations

from app.core.models import CharacterSheet


_ABILITY_NAMES = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}

def clamp_level(level: int) -> int:
    return max(1, min(20, int(level or 1)))


def proficiency_bonus_for_level(level: int) -> int:
    current = clamp_level(level)
    if current <= 4:
        return 2
    if current <= 8:
        return 3
    if current <= 12:
        return 4
    if current <= 16:
        return 5
    return 6


def apply_level_progression(
    sheet: CharacterSheet,
    *,
    target_level: int,
    hit_point_gain: int = 0,
    ability_increases: dict[str, int] | None = None,
    resource_pool_increases: dict[str, int] | None = None,
    feature_note: str = "",
) -> CharacterSheet:
    current_level = clamp_level(sheet.level)
    next_level = clamp_level(target_level)
    if next_level <= current_level:
        raise ValueError("target_level must be greater than the current level")

    updated = sheet.model_copy(deep=True)
    updated.level = next_level
    updated.proficiency_bonus = proficiency_bonus_for_level(next_level)

    hp_gain = max(0, int(hit_point_gain or 0))
    updated.max_hp = max(1, int(updated.max_hp or 1) + hp_gain)
    updated.current_hp = max(0, int(updated.current_hp or 0) + hp_gain)

    abilities = dict(updated.abilities or {})
    for ability_name, delta in (ability_increases or {}).items():
        normalized = str(ability_name or "").strip().lower()
        if normalized not in _ABILITY_NAMES:
            continue
        abilities[normalized] = max(1, int(abilities.get(normalized, 10)) + int(delta or 0))
    updated.abilities = abilities

    resource_pools = dict(updated.resource_pools or {})
    for pool_name, delta in (resource_pool_increases or {}).items():
        normalized = str(pool_name or "").strip().lower()
        if not normalized:
            continue
        state = dict(resource_pools.get(normalized, {}))
        maximum = max(0, int(state.get("max", state.get("maximum", 0)) or 0))
        current = max(0, int(state.get("current", maximum) or 0))
        increase = int(delta or 0)
        if increase <= 0:
            continue
        state["max"] = maximum + increase
        state["current"] = current + increase
        if "restores_on" in state:
            state["restores_on"] = str(state.get("restores_on", "") or "")
        resource_pools[normalized] = state
    updated.resource_pools = resource_pools

    note = str(feature_note or "").strip()
    if note:
        level_prefix = f"[Level {next_level}] "
        updated.notes = (updated.notes + "\n" if updated.notes else "") + level_prefix + note

    return updated
