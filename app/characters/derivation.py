from __future__ import annotations

from app.core.models import CharacterSheet
from .progression import proficiency_bonus_for_level
from .resources import normalize_currencies, normalize_resource_pools, total_currency_value_cp


DEFAULT_ABILITIES = {
    "strength": 10,
    "dexterity": 10,
    "constitution": 10,
    "intelligence": 10,
    "wisdom": 10,
    "charisma": 10,
}

SKILL_TO_ABILITY = {
    "athletics": "strength",
    "acrobatics": "dexterity",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    "animal_handling": "wisdom",
    "insight": "wisdom",
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    "deception": "charisma",
    "intimidation": "charisma",
    "performance": "charisma",
    "persuasion": "charisma",
}


def derive_ability_modifiers(sheet: CharacterSheet) -> dict[str, int]:
    return {
        ability: (int(sheet.abilities.get(ability, score)) - 10) // 2
        for ability, score in DEFAULT_ABILITIES.items()
    }


def derive_skill_totals(sheet: CharacterSheet) -> dict[str, int]:
    ability_modifiers = derive_ability_modifiers(sheet)
    totals = {
        skill: ability_modifiers[ability]
        for skill, ability in SKILL_TO_ABILITY.items()
    }
    for skill, value in (sheet.skill_modifiers or {}).items():
        totals[str(skill).lower()] = int(value)
    return totals


def derive_save_totals(sheet: CharacterSheet) -> dict[str, int]:
    ability_modifiers = derive_ability_modifiers(sheet)
    totals = dict(ability_modifiers)
    for save_name, value in (sheet.save_modifiers or {}).items():
        totals[str(save_name).lower()] = int(value)
    return totals


def derive_sheet_state(sheet: CharacterSheet) -> dict:
    ability_modifiers = derive_ability_modifiers(sheet)
    skill_totals = derive_skill_totals(sheet)
    save_totals = derive_save_totals(sheet)
    expected_proficiency = proficiency_bonus_for_level(sheet.level)
    current_hp = max(0, min(int(sheet.current_hp), int(sheet.max_hp)))
    max_hp = max(1, int(sheet.max_hp))
    currencies = normalize_currencies(sheet.currencies)
    resource_pools = normalize_resource_pools(sheet.resource_pools)
    return {
        "ability_modifiers": ability_modifiers,
        "skill_totals": skill_totals,
        "save_totals": save_totals,
        "initiative": ability_modifiers["dexterity"],
        "passive_perception": 10 + skill_totals["perception"],
        "passive_investigation": 10 + skill_totals["investigation"],
        "passive_insight": 10 + skill_totals["insight"],
        "expected_proficiency_bonus": expected_proficiency,
        "proficiency_matches_level": int(sheet.proficiency_bonus) == expected_proficiency,
        "hp_ratio": round(current_hp / max_hp, 3),
        "bloodied": current_hp <= max_hp // 2,
        "currencies": currencies,
        "resource_pools": resource_pools,
        "currency_total_cp": total_currency_value_cp(currencies),
    }
