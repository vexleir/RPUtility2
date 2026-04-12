from __future__ import annotations

from app.core.models import CharacterSheet
from .progression import clamp_level, proficiency_bonus_for_level


_BASE_ABILITY_ORDER = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
_ANCESTRY_OPTIONS = {
    "human": {
        "ability_bonuses": {name: 1 for name in _BASE_ABILITY_ORDER},
        "speed": 30,
        "notes": "Versatile and adaptable.",
    },
    "elf": {
        "ability_bonuses": {"dexterity": 2, "intelligence": 1},
        "speed": 30,
        "notes": "Keen senses and graceful movement.",
    },
    "dwarf": {
        "ability_bonuses": {"constitution": 2, "wisdom": 1},
        "speed": 25,
        "notes": "Sturdy frame and enduring will.",
    },
    "halfling": {
        "ability_bonuses": {"dexterity": 2, "charisma": 1},
        "speed": 25,
        "notes": "Lucky, nimble, and hard to pin down.",
    },
}
_CLASS_OPTIONS = {
    "fighter": {
        "abilities": {"strength": 15, "dexterity": 12, "constitution": 14, "intelligence": 10, "wisdom": 10, "charisma": 8},
        "hit_die": 10,
        "save_proficiencies": ["strength", "constitution"],
        "skill_proficiencies": ["athletics", "perception", "intimidation", "survival"],
        "currencies": {"gp": 12, "sp": 6, "cp": 0},
        "equipped_items": {"body": "leather-armor", "off_hand": "shield"},
        "starter_note": "A disciplined martial combatant ready for front-line action.",
    },
    "rogue": {
        "abilities": {"strength": 10, "dexterity": 15, "constitution": 12, "intelligence": 13, "wisdom": 12, "charisma": 10},
        "hit_die": 8,
        "save_proficiencies": ["dexterity", "intelligence"],
        "skill_proficiencies": ["stealth", "sleight_of_hand", "deception", "investigation", "perception"],
        "currencies": {"gp": 10, "sp": 8, "cp": 0},
        "equipped_items": {"body": "leather-armor"},
        "starter_note": "A quick, cautious operator built for stealth and tricks.",
    },
    "cleric": {
        "abilities": {"strength": 12, "dexterity": 10, "constitution": 14, "intelligence": 10, "wisdom": 15, "charisma": 12},
        "hit_die": 8,
        "save_proficiencies": ["wisdom", "charisma"],
        "skill_proficiencies": ["insight", "medicine", "persuasion", "religion"],
        "currencies": {"gp": 10, "sp": 5, "cp": 0},
        "equipped_items": {"body": "leather-armor", "off_hand": "shield"},
        "resource_pools": {"spell_slot_1": {"current": 2, "max": 2, "restores_on": "long_rest"}},
        "prepared_spells": ["bless", "healing-word"],
        "starter_note": "A divine caster with healing and support magic prepared.",
    },
    "wizard": {
        "abilities": {"strength": 8, "dexterity": 14, "constitution": 12, "intelligence": 15, "wisdom": 12, "charisma": 10},
        "hit_die": 6,
        "save_proficiencies": ["intelligence", "wisdom"],
        "skill_proficiencies": ["arcana", "history", "investigation", "perception"],
        "currencies": {"gp": 9, "sp": 4, "cp": 0},
        "resource_pools": {"spell_slot_1": {"current": 2, "max": 2, "restores_on": "long_rest"}},
        "prepared_spells": ["magic-missile"],
        "starter_note": "An arcane scholar prepared to solve problems with spells.",
    },
}
_BACKGROUND_SKILL = {
    "soldier": "athletics",
    "acolyte": "religion",
    "scholar": "arcana",
    "criminal": "stealth",
    "wanderer": "survival",
}


def list_quick_build_options() -> dict:
    return {
        "classes": sorted(_CLASS_OPTIONS.keys()),
        "ancestries": sorted(_ANCESTRY_OPTIONS.keys()),
        "backgrounds": sorted(_BACKGROUND_SKILL.keys()),
    }


def build_quick_character_sheet(
    *,
    campaign_id: str,
    name: str,
    character_class: str,
    ancestry: str,
    background: str = "",
    level: int = 1,
) -> CharacterSheet:
    class_key = str(character_class or "").strip().lower()
    ancestry_key = str(ancestry or "").strip().lower()
    background_key = str(background or "").strip().lower()
    if class_key not in _CLASS_OPTIONS:
        raise ValueError(f"Unsupported class template: {class_key}")
    if ancestry_key not in _ANCESTRY_OPTIONS:
        raise ValueError(f"Unsupported ancestry template: {ancestry_key}")

    current_level = clamp_level(level)
    class_data = _CLASS_OPTIONS[class_key]
    ancestry_data = _ANCESTRY_OPTIONS[ancestry_key]
    abilities = dict(class_data["abilities"])
    for ability_name, bonus in ancestry_data["ability_bonuses"].items():
        abilities[ability_name] = int(abilities.get(ability_name, 10)) + int(bonus or 0)

    proficiency_bonus = proficiency_bonus_for_level(current_level)
    ability_modifiers = {key: (int(value) - 10) // 2 for key, value in abilities.items()}

    skill_modifiers = {}
    for skill_name in class_data["skill_proficiencies"]:
        governing_ability = _skill_ability(skill_name)
        skill_modifiers[skill_name] = ability_modifiers.get(governing_ability, 0) + proficiency_bonus
    background_skill = _BACKGROUND_SKILL.get(background_key)
    if background_skill and background_skill not in skill_modifiers:
        skill_modifiers[background_skill] = ability_modifiers.get(_skill_ability(background_skill), 0) + proficiency_bonus

    save_modifiers = {
        ability_name: ability_modifiers.get(ability_name, 0) + proficiency_bonus
        for ability_name in class_data["save_proficiencies"]
    }

    hit_die = int(class_data["hit_die"])
    constitution_mod = ability_modifiers.get("constitution", 0)
    max_hp = max(1, hit_die + constitution_mod + max(0, current_level - 1) * (max(1, (hit_die // 2) + 1 + constitution_mod)))
    dexterity_mod = ability_modifiers.get("dexterity", 0)
    base_ac = 10 + dexterity_mod
    equipped_items = dict(class_data.get("equipped_items", {}))
    if equipped_items.get("body") == "leather-armor":
        base_ac = 11 + dexterity_mod
    if equipped_items.get("off_hand") == "shield":
        base_ac += 2

    resource_pools = {}
    for pool_name, pool in (class_data.get("resource_pools") or {}).items():
        state = dict(pool)
        if pool_name == "spell_slot_1":
            slots = 2 if current_level <= 1 else min(4, current_level + 1)
            state["current"] = slots
            state["max"] = slots
        resource_pools[pool_name] = state

    notes = [class_data["starter_note"], ancestry_data["notes"]]
    if background_key:
        notes.append(f"Background: {background_key.title()}.")
    return CharacterSheet(
        campaign_id=campaign_id,
        name=name or f"{ancestry_key.title()} {class_key.title()}",
        ancestry=ancestry_key.title(),
        character_class=class_key.title(),
        background=background_key.title() if background_key else "",
        level=current_level,
        proficiency_bonus=proficiency_bonus,
        abilities=abilities,
        skill_modifiers=skill_modifiers,
        save_modifiers=save_modifiers,
        max_hp=max_hp,
        current_hp=max_hp,
        armor_class=base_ac,
        speed=int(ancestry_data["speed"]),
        currencies=dict(class_data["currencies"]),
        resource_pools=resource_pools,
        prepared_spells=list(class_data.get("prepared_spells") or []),
        equipped_items=equipped_items,
        notes=" ".join(note for note in notes if note),
    )


def _skill_ability(skill_name: str) -> str:
    lookup = {
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
    return lookup.get(str(skill_name or "").strip().lower(), "wisdom")
