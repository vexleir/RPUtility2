from __future__ import annotations

from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.characters.progression import apply_level_progression
from app.core.models import ActionLogEntry, CharacterSheet, PlayMode


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


def test_apply_level_progression_updates_level_hp_and_resources():
    sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        level=4,
        proficiency_bonus=2,
        current_hp=18,
        max_hp=18,
        abilities={"strength": 10, "dexterity": 14, "constitution": 14, "intelligence": 10, "wisdom": 12, "charisma": 8},
        resource_pools={"spell_slot_1": {"current": 2, "max": 4, "restores_on": "long_rest"}},
        notes="Existing note.",
    )

    updated = apply_level_progression(
        sheet,
        target_level=5,
        hit_point_gain=7,
        ability_increases={"constitution": 2},
        resource_pool_increases={"spell_slot_1": 1},
        feature_note="Extra attack unlocked.",
    )

    assert updated.level == 5
    assert updated.proficiency_bonus == 3
    assert updated.max_hp == 25
    assert updated.current_hp == 25
    assert updated.abilities["constitution"] == 16
    assert updated.resource_pools["spell_slot_1"]["max"] == 5
    assert updated.resource_pools["spell_slot_1"]["current"] == 3
    assert "[Level 5] Extra attack unlocked." in updated.notes


def test_level_up_route_updates_sheet_and_records_audit(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
    )
    sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        character_class="fighter",
        level=4,
        proficiency_bonus=2,
        current_hp=20,
        max_hp=20,
        abilities={"strength": 16, "dexterity": 12, "constitution": 14, "intelligence": 10, "wisdom": 10, "charisma": 8},
        resource_pools={"superiority": {"current": 2, "max": 2, "restores_on": "short_rest"}},
    )
    action_logs = DummyActionLogStore()
    audits = []

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str, owner_id: str):
            return sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(sheet, key, value)
            return sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.level_up_character_sheet(
        "camp-1",
        "player",
        "player",
        routes.LevelUpCharacterRequest(
            target_level=5,
            hit_point_gain=8,
            ability_increases={"strength": 2},
            resource_pool_increases={"superiority": 1},
            feature_note="Martial prowess deepens.",
        ),
    )

    assert result["to_level"] == 5
    assert result["sheet"]["proficiency_bonus"] == 3
    assert result["sheet"]["max_hp"] == 28
    assert result["sheet"]["abilities"]["strength"] == 18
    assert result["sheet"]["resource_pools"]["superiority"]["max"] == 3
    assert action_logs.saved[0].action_type == "level_up"
    assert audits[0]["event_type"] == "level_up"
