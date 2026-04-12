from __future__ import annotations

from app.core.models import CharacterSheet
from .derivation import DEFAULT_ABILITIES, derive_sheet_state
from .progression import clamp_level, proficiency_bonus_for_level
from .resources import normalize_currencies, normalize_resource_pools


def normalize_prepared_spells(spells: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in spells or []:
        slug = str(raw).strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
    return normalized


def normalize_equipped_items(items: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_slot, raw_slug in (items or {}).items():
        slot = str(raw_slot).strip().lower()
        slug = str(raw_slug).strip().lower()
        if not slot or not slug:
            continue
        normalized[slot] = slug
    return normalized


def normalize_item_charges(charges: dict[str, dict] | None) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for raw_slug, raw_data in (charges or {}).items():
        slug = str(raw_slug).strip().lower()
        if not slug:
            continue
        data = raw_data or {}
        maximum = max(0, int(data.get("max", 0) or 0))
        current = max(0, min(int(data.get("current", maximum) or 0), maximum))
        normalized[slug] = {
            "current": current,
            "max": maximum,
            "restores_on": str(data.get("restores_on", "") or ""),
        }
    return normalized


def normalize_sheet(sheet: CharacterSheet) -> CharacterSheet:
    updated = sheet.model_copy(deep=True)
    updated.level = clamp_level(updated.level)
    updated.proficiency_bonus = max(1, int(updated.proficiency_bonus or proficiency_bonus_for_level(updated.level)))

    abilities = dict(DEFAULT_ABILITIES)
    for key, value in (updated.abilities or {}).items():
        abilities[str(key).lower()] = int(value)
    updated.abilities = abilities

    updated.skill_modifiers = {
        str(key).lower(): int(value)
        for key, value in (updated.skill_modifiers or {}).items()
    }
    updated.save_modifiers = {
        str(key).lower(): int(value)
        for key, value in (updated.save_modifiers or {}).items()
    }
    updated.max_hp = max(1, int(updated.max_hp))
    updated.current_hp = max(0, min(int(updated.current_hp), updated.max_hp))
    updated.temp_hp = max(0, int(updated.temp_hp))
    updated.armor_class = max(0, int(updated.armor_class))
    updated.speed = max(0, int(updated.speed))
    updated.currencies = normalize_currencies(updated.currencies)
    updated.resource_pools = normalize_resource_pools(updated.resource_pools)
    updated.prepared_spells = normalize_prepared_spells(updated.prepared_spells)
    updated.equipped_items = normalize_equipped_items(updated.equipped_items)
    updated.item_charges = normalize_item_charges(updated.item_charges)
    updated.conditions = [str(condition) for condition in (updated.conditions or []) if str(condition).strip()]
    return updated


def build_sheet_payload(sheet: CharacterSheet) -> dict:
    normalized = normalize_sheet(sheet)
    return {
        "sheet": normalized,
        "derived": derive_sheet_state(normalized),
    }
