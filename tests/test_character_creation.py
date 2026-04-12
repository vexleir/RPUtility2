from __future__ import annotations

from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.characters.quickbuild import build_quick_character_sheet, list_quick_build_options
from app.core.models import CharacterSheet, PlayMode


def test_quick_build_options_include_supported_templates():
    options = list_quick_build_options()
    assert "fighter" in options["classes"]
    assert "wizard" in options["classes"]
    assert "human" in options["ancestries"]
    assert "wanderer" in options["backgrounds"]


def test_build_quick_character_sheet_creates_playable_cleric():
    sheet = build_quick_character_sheet(
        campaign_id="camp-1",
        name="Serah",
        character_class="cleric",
        ancestry="dwarf",
        background="acolyte",
    )

    assert sheet.name == "Serah"
    assert sheet.character_class == "Cleric"
    assert sheet.ancestry == "Dwarf"
    assert sheet.level == 1
    assert sheet.max_hp >= 10
    assert sheet.armor_class >= 13
    assert sheet.prepared_spells == ["bless", "healing-word"]
    assert sheet.resource_pools["spell_slot_1"]["max"] == 2
    assert sheet.skill_modifiers["religion"] >= 2


def test_quick_build_route_updates_player_character_and_sheet(monkeypatch):
    campaign = SimpleNamespace(id="camp-1", play_mode=PlayMode.RULES, system_pack="d20-fantasy-core")
    saved_sheet = None
    saved_pc = None

    class DummySheetStore:
        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            nonlocal saved_sheet
            saved_sheet = CharacterSheet(
                campaign_id=campaign_id,
                owner_type=owner_type,
                owner_id=owner_id,
                name=kwargs["name"],
                ancestry=kwargs["ancestry"],
                character_class=kwargs["character_class"],
                background=kwargs["background"],
                level=kwargs["level"],
                proficiency_bonus=kwargs["proficiency_bonus"],
                abilities=kwargs["abilities"],
                skill_modifiers=kwargs["skill_modifiers"],
                save_modifiers=kwargs["save_modifiers"],
                max_hp=kwargs["max_hp"],
                current_hp=kwargs["current_hp"],
                armor_class=kwargs["armor_class"],
                speed=kwargs["speed"],
                currencies=kwargs["currencies"],
                resource_pools=kwargs["resource_pools"],
                prepared_spells=kwargs["prepared_spells"],
                equipped_items=kwargs["equipped_items"],
                notes=kwargs["notes"],
            )
            return saved_sheet

    class DummyPcStore:
        def get(self, campaign_id: str):
            return None

        def save(self, pc):
            nonlocal saved_pc
            saved_pc = pc

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_pcs", lambda: DummyPcStore())

    result = routes.quick_build_character_sheet(
        "camp-1",
        "player",
        "player",
        routes.QuickBuildCharacterRequest(
            name="Lysa",
            character_class="wizard",
            ancestry="elf",
            background="scholar",
        ),
    )

    assert result["sheet"]["name"] == "Lysa"
    assert result["sheet"]["character_class"] == "Wizard"
    assert result["sheet"]["prepared_spells"] == ["magic-missile"]
    assert result["player_character"]["name"] == "Lysa"
    assert saved_pc.background == "scholar"
