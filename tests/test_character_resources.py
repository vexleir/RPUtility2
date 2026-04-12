from __future__ import annotations

from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.characters.resources import restore_resource_pools
from app.core.models import ActionLogEntry, CharacterSheet, PlayMode


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


def test_restore_resource_pools_respects_short_and_long_rest():
    pools = {
        "ki": {"current": 0, "max": 3, "restores_on": "short_rest"},
        "spell_slot_1": {"current": 1, "max": 4, "restores_on": "long_rest"},
    }

    short_restored, short_events = restore_resource_pools(pools, rest_type="short_rest")
    assert short_restored["ki"]["current"] == 3
    assert short_restored["spell_slot_1"]["current"] == 1
    assert short_events[0]["resource"] == "ki"

    long_restored, long_events = restore_resource_pools(short_restored, rest_type="long_rest")
    assert long_restored["ki"]["current"] == 3
    assert long_restored["spell_slot_1"]["current"] == 4
    assert any(event["resource"] == "spell_slot_1" for event in long_events)


def test_rest_route_restores_resource_pools_and_item_charges(monkeypatch):
    sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        resource_pools={
            "spell_slot_1": {"current": 1, "max": 4, "restores_on": "long_rest"},
            "ki": {"current": 0, "max": 3, "restores_on": "short_rest"},
        },
        item_charges={
            "healing-wand": {"current": 1, "max": 3, "restores_on": "long_rest"},
        },
    )

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str, owner_id: str):
            return sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(sheet, key, value)
            return sheet

    log_store = DummyActionLogStore()
    audits = []

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    short_result = routes.rest_character_resources(
        "camp-1",
        "player",
        "player",
        routes.RestCharacterResourcesRequest(rest_type="short_rest"),
    )
    assert short_result["sheet"]["resource_pools"]["ki"]["current"] == 3
    assert short_result["sheet"]["resource_pools"]["spell_slot_1"]["current"] == 1

    long_result = routes.rest_character_resources(
        "camp-1",
        "player",
        "player",
        routes.RestCharacterResourcesRequest(rest_type="long_rest"),
    )
    assert long_result["sheet"]["resource_pools"]["spell_slot_1"]["current"] == 4
    assert long_result["sheet"]["item_charges"]["healing-wand"]["current"] == 3
    assert log_store.saved[-1].action_type == "rest"
    assert audits[-1]["event_type"] == "rest"
