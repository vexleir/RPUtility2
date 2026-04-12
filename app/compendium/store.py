from __future__ import annotations

import json
from pathlib import Path

from app.compendium.models import CompendiumEntry
from app.core.config import config


BUILTIN_ENTRIES: list[CompendiumEntry] = [
    CompendiumEntry(
        slug="dash",
        name="Dash",
        category="action",
        system_pack="d20-fantasy-core",
        description="Gain extra movement for the turn.",
        rules_text="You gain extra movement for the current turn equal to your speed.",
        tags=["combat", "movement"],
        action_cost="action",
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="leather-armor",
        name="Leather Armor",
        category="armor",
        system_pack="d20-fantasy-core",
        description="Light armor that slightly improves defense.",
        rules_text="While equipped, this armor improves your Armor Class.",
        tags=["armor", "equipment", "defense"],
        equipment_slot="body",
        armor_class_bonus=1,
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="shield",
        name="Shield",
        category="armor",
        system_pack="d20-fantasy-core",
        description="A shield that improves defense while carried in hand.",
        rules_text="While equipped, the shield improves your Armor Class.",
        tags=["armor", "equipment", "defense"],
        equipment_slot="off_hand",
        armor_class_bonus=2,
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="help",
        name="Help",
        category="action",
        system_pack="d20-fantasy-core",
        description="Aid another creature with a task or attack setup.",
        rules_text="A nearby ally gains advantage or direct support on their next immediate effort, depending on context.",
        tags=["combat", "support"],
        action_cost="action",
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="disengage",
        name="Disengage",
        category="action",
        system_pack="d20-fantasy-core",
        description="Move without inviting immediate reprisals.",
        rules_text="Until the end of the turn, your movement avoids immediate parting attacks tied to leaving reach.",
        tags=["combat", "movement", "defense"],
        action_cost="action",
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="dodge",
        name="Dodge",
        category="action",
        system_pack="d20-fantasy-core",
        description="Focus fully on avoiding attacks.",
        rules_text="Until your next turn, attacks against you are hindered and you make Dexterity saves more effectively, if you can act.",
        tags=["combat", "defense"],
        action_cost="action",
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="healing-wand",
        name="Healing Wand",
        category="item",
        system_pack="d20-fantasy-core",
        description="A charged wand that restores health.",
        rules_text="Spend one charge to restore health to a nearby creature.",
        tags=["item", "healing", "charged", "equipment"],
        action_cost="action",
        range_feet=30,
        roll_expression="2d4",
        modifier=2,
        equipment_slot="main_hand",
        charges_max=3,
        restores_on="long_rest",
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="second-wind",
        name="Second Wind",
        category="action",
        system_pack="d20-fantasy-core",
        description="Recover a burst of vitality.",
        rules_text="Regain a small amount of HP as a bonus action.",
        tags=["combat", "healing", "self"],
        action_cost="bonus_action",
        roll_expression="1d10",
        modifier=0,
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="poisoned",
        name="Poisoned",
        category="condition",
        system_pack="d20-fantasy-core",
        description="A harmful condition that hinders performance.",
        rules_text="A poisoned creature is impaired until the condition ends.",
        tags=["condition", "debuff"],
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="bless",
        name="Bless",
        category="spell",
        system_pack="d20-fantasy-core",
        description="Bolster allies with divine favor.",
        rules_text="Up to several allies gain a small ongoing bonus while concentration lasts.",
        tags=["spell", "buff", "concentration"],
        action_cost="action",
        range_feet=30,
        resource_costs={"spell_slot_1": 1},
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="healing-word",
        name="Healing Word",
        category="spell",
        system_pack="d20-fantasy-core",
        description="Restore a small amount of HP at range.",
        rules_text="A quick healing effect that can be delivered at range.",
        tags=["spell", "healing"],
        action_cost="bonus_action",
        range_feet=60,
        roll_expression="1d4",
        modifier=0,
        resource_costs={"spell_slot_1": 1},
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="cure-wounds",
        name="Cure Wounds",
        category="spell",
        system_pack="d20-fantasy-core",
        description="Restore a stronger burst of HP through touch.",
        rules_text="A nearby creature regains a larger amount of health.",
        tags=["spell", "healing", "touch"],
        action_cost="action",
        range_feet=5,
        roll_expression="1d8",
        modifier=3,
        resource_costs={"spell_slot_1": 1},
        is_builtin=True,
    ),
    CompendiumEntry(
        slug="magic-missile",
        name="Magic Missile",
        category="spell",
        system_pack="d20-fantasy-core",
        description="Arcane bolts that strike true and deal reliable force damage.",
        rules_text="Several darts of force fly from your hand and batter a target at range.",
        tags=["spell", "damage", "arcane"],
        action_cost="action",
        range_feet=120,
        roll_expression="3d4",
        modifier=3,
        resource_costs={"spell_slot_1": 1},
        is_builtin=True,
    ),
]


def _compendium_dir() -> Path:
    path = Path(config.compendium_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


class CompendiumStore:
    def list_all(self, *, system_pack: str | None = None, category: str | None = None, query: str | None = None) -> list[CompendiumEntry]:
        entries = BUILTIN_ENTRIES[:] + self._load_custom_entries()
        filtered: list[CompendiumEntry] = []
        query_text = str(query or "").strip().lower()
        for entry in entries:
            if system_pack and entry.system_pack != system_pack:
                continue
            if category and entry.category != category:
                continue
            if query_text:
                haystack = " ".join([
                    entry.name,
                    entry.slug,
                    entry.description,
                    entry.rules_text,
                    " ".join(entry.tags),
                ]).lower()
                if query_text not in haystack:
                    continue
            filtered.append(entry)
        filtered.sort(key=lambda entry: (entry.category, entry.name.lower()))
        return filtered

    def get(self, slug: str, *, system_pack: str | None = None) -> CompendiumEntry | None:
        normalized = str(slug or "").strip().lower()
        for entry in self.list_all(system_pack=system_pack):
            if entry.slug.lower() == normalized:
                return entry
        return None

    def save(self, entry: CompendiumEntry) -> Path:
        path = _compendium_dir() / f"{entry.slug.replace('-', '_')}.json"
        payload = entry.model_dump()
        payload["created_at"] = entry.created_at.isoformat()
        payload["updated_at"] = entry.updated_at.isoformat()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def suggest_for_resolution(self, *, system_pack: str | None, resolution_kind: str, user_message: str) -> list[CompendiumEntry]:
        text = str(user_message or "").strip().lower()
        entries = self.list_all(system_pack=system_pack)
        explicit_slugs: list[str] = []
        if "dash" in text:
            explicit_slugs.append("dash")
        if "dodge" in text:
            explicit_slugs.append("dodge")
        if "help" in text:
            explicit_slugs.append("help")
        if "disengage" in text:
            explicit_slugs.append("disengage")
        if "bless" in text:
            explicit_slugs.append("bless")
        if "healing word" in text:
            explicit_slugs.append("healing-word")
        if "cure wounds" in text:
            explicit_slugs.append("cure-wounds")
        if "second wind" in text:
            explicit_slugs.append("second-wind")
        if "magic missile" in text:
            explicit_slugs.append("magic-missile")
        if explicit_slugs:
            return [entry for entry in entries if entry.slug in explicit_slugs]

        category_map = {
            "attack": {"action", "weapon", "spell"},
            "healing": {"spell", "action"},
            "compendium_action": {"action", "spell"},
        }
        allowed = category_map.get(resolution_kind, set())
        return [entry for entry in entries if entry.category in allowed][:3]

    def _load_custom_entries(self) -> list[CompendiumEntry]:
        entries: list[CompendiumEntry] = []
        for path in sorted(_compendium_dir().glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries.append(CompendiumEntry(**data))
            except Exception:
                continue
        return entries
