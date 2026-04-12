from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

from app.characters.derivation import derive_ability_modifiers, derive_sheet_state, derive_skill_totals
from app.characters.progression import proficiency_bonus_for_level
from app.characters.resources import adjust_currency, consume_resource, total_currency_value_cp
from app.characters.sheets import build_sheet_payload, normalize_prepared_spells, normalize_sheet
from app.characters.store import CharacterSheetStore
from app.core.database import ensure_db
from app.core.models import CharacterSheet
import app.web.campaign_routes as routes


def test_proficiency_bonus_for_level_progression():
    assert proficiency_bonus_for_level(1) == 2
    assert proficiency_bonus_for_level(5) == 3
    assert proficiency_bonus_for_level(9) == 4
    assert proficiency_bonus_for_level(13) == 5
    assert proficiency_bonus_for_level(17) == 6


def test_normalize_sheet_clamps_and_fills_defaults():
    sheet = CharacterSheet(
        campaign_id="c",
        level=0,
        max_hp=0,
        current_hp=999,
        temp_hp=-4,
        armor_class=-1,
        speed=-20,
        abilities={"strength": 16},
        currencies={"gp": 4, "pp": 2, "sp": -5},
        prepared_spells=["Bless", " bless ", "", "Healing-Word"],
        equipped_items={"Body": "Leather-Armor", "": "bad"},
        item_charges={"Healing-Wand": {"current": 5, "max": 3, "restores_on": "LONG_REST"}},
        conditions=["poisoned", "", "blessed"],
    )
    normalized = normalize_sheet(sheet)
    assert normalized.level == 1
    assert normalized.max_hp == 1
    assert normalized.current_hp == 1
    assert normalized.temp_hp == 0
    assert normalized.armor_class == 0
    assert normalized.speed == 0
    assert normalized.abilities["dexterity"] == 10
    assert normalized.currencies["gp"] == 4
    assert normalized.currencies["sp"] == 0
    assert normalized.currencies["cp"] == 0
    assert normalized.prepared_spells == ["bless", "healing-word"]
    assert normalized.equipped_items == {"body": "leather-armor"}
    assert normalized.item_charges["healing-wand"]["current"] == 3
    assert normalized.conditions == ["poisoned", "blessed"]


def test_normalize_prepared_spells_deduplicates_and_normalizes():
    assert normalize_prepared_spells(["Bless", "bless", " Healing-Word ", ""]) == ["bless", "healing-word"]


def test_derive_sheet_state_computes_modifiers_skills_and_passives():
    sheet = CharacterSheet(
        campaign_id="c",
        level=5,
        proficiency_bonus=3,
        abilities={
            "strength": 8,
            "dexterity": 14,
            "constitution": 12,
            "intelligence": 10,
            "wisdom": 16,
            "charisma": 18,
        },
        skill_modifiers={"stealth": 5, "persuasion": 7},
        save_modifiers={"wisdom": 6},
        current_hp=12,
        max_hp=20,
        currencies={"gp": 7, "sp": 3},
    )
    derived = derive_sheet_state(sheet)
    assert derived["ability_modifiers"]["strength"] == -1
    assert derived["ability_modifiers"]["wisdom"] == 3
    assert derived["skill_totals"]["stealth"] == 5
    assert derived["skill_totals"]["perception"] == 3
    assert derived["save_totals"]["wisdom"] == 6
    assert derived["initiative"] == 2
    assert derived["passive_perception"] == 13
    assert derived["expected_proficiency_bonus"] == 3
    assert derived["proficiency_matches_level"] is True
    assert derived["bloodied"] is False
    assert derived["currency_total_cp"] == 730


def test_build_sheet_payload_contains_normalized_sheet_and_derived_block():
    payload = build_sheet_payload(
        CharacterSheet(campaign_id="c", abilities={"strength": 15}, currencies={"gp": 2})
    )
    assert payload["sheet"].abilities["dexterity"] == 10
    assert payload["derived"]["ability_modifiers"]["strength"] == 2
    assert "passive_perception" in payload["derived"]


def test_character_sheet_serialization_round_trip():
    sheet = CharacterSheet(
        campaign_id="c",
        name="Serah",
        abilities={"strength": 13, "dexterity": 12, "constitution": 14, "intelligence": 11, "wisdom": 10, "charisma": 8},
        skill_modifiers={"athletics": 3},
        save_modifiers={"constitution": 4},
        currencies={"gp": 9},
        conditions=["blessed"],
    )
    restored = CharacterSheet.model_validate(sheet.model_dump())
    assert restored.name == "Serah"
    assert restored.skill_modifiers["athletics"] == 3
    assert restored.conditions == ["blessed"]


def test_character_sheet_store_round_trip_and_npc_support():
    base = Path(tempfile.gettempdir()) / f"rputility-sheet-store-{uuid.uuid4().hex}"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    db_path = str(base / "sheet_store.db")
    try:
        ensure_db(db_path)
        campaign_id = f"camp-{uuid.uuid4().hex}"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO campaigns (id, name, model_name, play_mode, system_pack, feature_flags, style_guide, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (campaign_id, "Phase 2 Test", None, "rules", "d20-fantasy-core", "{}", "{}"),
        )
        conn.commit()
        conn.close()
        store = CharacterSheetStore(db_path)

        player = store.save_for_owner(
            campaign_id,
            "player",
            "player",
            name="Aria",
            level=5,
            proficiency_bonus=3,
            abilities={"strength": 10, "dexterity": 16},
            skill_modifiers={"stealth": 6},
            current_hp=18,
            max_hp=18,
            currencies={"gp": 12},
            resource_pools={"spell_slot_1": {"current": 2, "max": 4, "restores_on": "long_rest"}},
            prepared_spells=["bless"],
            equipped_items={"body": "leather-armor"},
            item_charges={"healing-wand": {"current": 2, "max": 3, "restores_on": "long_rest"}},
        )
        store.save_for_owner(
            campaign_id,
            "npc",
            "guard-captain",
            name="Guard Captain",
            armor_class=16,
            current_hp=22,
            max_hp=22,
        )

        loaded_player = store.get(player.id)
        loaded_all = store.get_all(campaign_id)

        assert loaded_player is not None
        assert loaded_player.abilities["constitution"] == 10
        assert loaded_player.currencies["gp"] == 12
        assert loaded_player.skill_modifiers["stealth"] == 6
        assert loaded_player.resource_pools["spell_slot_1"]["current"] == 2
        assert loaded_player.prepared_spells == ["bless"]
        assert loaded_player.equipped_items["body"] == "leather-armor"
        assert loaded_player.item_charges["healing-wand"]["current"] == 2
        assert len(loaded_all) == 2
        assert any(sheet.owner_type == "npc" and sheet.owner_id == "guard-captain" for sheet in loaded_all)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_resource_helpers_adjust_and_total_currency():
    wallet = adjust_currency({"gp": 3, "sp": 5}, "gp", -1)
    wallet = adjust_currency(wallet, "cp", 7)
    assert wallet["gp"] == 2
    assert wallet["cp"] == 7
    assert total_currency_value_cp(wallet) == 257


def test_resource_pool_consumption_updates_remaining_uses():
    pools, slot = consume_resource(
        {"spell_slot_1": {"current": 3, "max": 4, "restores_on": "long_rest"}},
        "spell_slot_1",
        2,
    )
    assert pools["spell_slot_1"]["current"] == 1
    assert slot["max"] == 4


def test_skill_derivation_defaults_to_governing_ability():
    sheet = CharacterSheet(campaign_id="c", abilities={"wisdom": 14})
    totals = derive_skill_totals(sheet)
    assert totals["perception"] == 2
    assert totals["survival"] == 2
    assert totals["arcana"] == 0
    assert derive_ability_modifiers(sheet)["wisdom"] == 2


def test_owner_specific_sheet_route_supports_npc_sheets(monkeypatch):
    class DummySheetStore:
        def __init__(self):
            self.saved = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="guard-1", name="Guard")

        def get_for_owner(self, campaign_id: str, owner_type: str, owner_id: str):
            if owner_type == "npc" and owner_id == "guard-1":
                return self.saved
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(self.saved, key, value)
            self.saved.campaign_id = campaign_id
            self.saved.owner_type = owner_type
            self.saved.owner_id = owner_id
            return self.saved

        def get_all(self, campaign_id: str):
            return [self.saved]

    store = DummySheetStore()
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_sheets", lambda: store)

    saved = routes.save_character_sheet_for_owner(
        "camp-1",
        "npc",
        "guard-1",
        routes.SaveCharacterSheetRequest(name="Guard Captain", armor_class=16, current_hp=22, max_hp=22),
    )
    listed = routes.get_all_character_sheets("camp-1")

    assert saved["owner_type"] == "npc"
    assert saved["owner_id"] == "guard-1"
    assert saved["name"] == "Guard Captain"
    assert saved["derived"]["initiative"] == 0
    assert len(listed) == 1


def test_prepare_spell_route_updates_sheet(monkeypatch):
    class DummySheetStore:
        def __init__(self):
            self.saved = CharacterSheet(campaign_id="camp-1", name="Aria", prepared_spells=["bless"])

        def get_for_owner(self, campaign_id: str, owner_type: str, owner_id: str):
            return self.saved

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(self.saved, key, value)
            return self.saved

    store = DummySheetStore()
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: type("Campaign", (), {"play_mode": routes.PlayMode.RULES, "system_pack": "d20-fantasy-core"})())
    monkeypatch.setattr(routes, "_sheets", lambda: store)
    monkeypatch.setattr(routes, "_compendium_store", lambda: type("Compendium", (), {"get": lambda self, slug, system_pack=None: routes.CompendiumEntry(slug=slug, name="Healing Word", category="spell", system_pack="d20-fantasy-core")})())

    result = routes.set_prepared_character_spell(
        "camp-1",
        "player",
        "player",
        routes.PrepareCharacterSpellRequest(slug="healing-word", prepared=True),
    )

    assert result["prepared"] is True
    assert result["sheet"]["prepared_spells"] == ["bless", "healing-word"]


def test_equipment_route_updates_slot_and_armor_class(monkeypatch):
    class DummySheetStore:
        def __init__(self):
            self.saved = CharacterSheet(campaign_id="camp-1", name="Aria", armor_class=10)

        def get_for_owner(self, campaign_id: str, owner_type: str, owner_id: str):
            return self.saved

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(self.saved, key, value)
            return self.saved

    store = DummySheetStore()
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: type("Campaign", (), {"play_mode": routes.PlayMode.RULES, "system_pack": "d20-fantasy-core"})())
    monkeypatch.setattr(routes, "_sheets", lambda: store)
    monkeypatch.setattr(routes, "_compendium_store", lambda: type("Compendium", (), {"get": lambda self, slug, system_pack=None: routes.CompendiumEntry(slug=slug, name="Shield", category="armor", system_pack="d20-fantasy-core", equipment_slot="off_hand", armor_class_bonus=2)})())

    result = routes.set_character_equipment(
        "camp-1",
        "player",
        "player",
        routes.EquipCharacterItemRequest(slug="shield", equipped=True),
    )

    assert result["equipped"] is True
    assert result["sheet"]["equipped_items"]["off_hand"] == "shield"
    assert result["sheet"]["armor_class"] == 12
