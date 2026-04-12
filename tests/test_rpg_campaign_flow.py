from __future__ import annotations

from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.campaigns.procedures import shift_faction_standing, world_time_snapshot
from app.core.models import ActionLogEntry, CampaignEvent, CampaignFaction, CharacterSheet, PlayMode


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


class DummyEventStore:
    def __init__(self):
        self.saved = []

    def save(self, event):
        for index, existing in enumerate(self.saved):
            if existing.id == event.id:
                self.saved[index] = event
                break
        else:
            self.saved.append(event)

    def get_all(self, campaign_id: str):
        return [event for event in self.saved if event.campaign_id == campaign_id]


def test_world_time_snapshot_formats_day_and_hour():
    snap = world_time_snapshot(27)
    assert snap["day"] == 2
    assert snap["hour"] == 3
    assert snap["label"] == "Day 2, 03:00"


def test_shift_faction_standing_clamps_within_known_range():
    assert shift_faction_standing("neutral", 1) == "friendly"
    assert shift_faction_standing("neutral", -2) == "hostile"
    assert shift_faction_standing("allied", 3) == "allied"


def test_advance_time_procedure_updates_world_time_restores_resources_and_factions(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Test Campaign",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=10,
        notes="",
        cover_image=None,
        created_at=__import__("datetime").datetime(2026, 4, 9),
        updated_at=__import__("datetime").datetime(2026, 4, 9),
    )
    player_sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        resource_pools={"spell_slot_1": {"current": 1, "max": 4, "restores_on": "long_rest"}},
        item_charges={"healing-wand": {"current": 1, "max": 3, "restores_on": "long_rest"}},
    )
    faction = CampaignFaction(campaign_id="camp-1", name="Town Guard", standing_with_player="neutral")
    action_logs = DummyActionLogStore()
    events = DummyEventStore()
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return player_sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(player_sheet, key, value)
            return player_sheet

    class DummyFactionStore:
        def get(self, faction_id: str):
            return faction if faction_id == faction.id else None

        def save(self, updated):
            faction.standing_with_player = updated.standing_with_player
            faction.relationship_notes = updated.relationship_notes

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_factions", lambda: DummyFactionStore())
    monkeypatch.setattr(routes, "_events", lambda: events)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.advance_campaign_time_procedure(
        "camp-1",
        routes.AdvanceCampaignTimeRequest(
            hours=8,
            procedure_type="travel",
            destination="Old Watchtower",
            rest_type="long_rest",
            faction_effects=[routes.FactionTimeEffectRequest(faction_id=faction.id, delta=1, note="Safe escort for the caravan.")],
        ),
    )

    assert result["world_time"]["total_hours"] == 18
    assert result["player_sheet"]["resource_pools"]["spell_slot_1"]["current"] == 4
    assert result["player_sheet"]["item_charges"]["healing-wand"]["current"] == 3
    assert result["faction_updates"][0]["to"] == "friendly"
    assert action_logs.saved[0].action_type == "campaign_procedure"
    assert audits[0]["event_type"] == "campaign_procedure"


def test_advance_time_procedure_matures_pending_event(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Escalation Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=10,
        notes="",
        cover_image=None,
        created_at=__import__("datetime").datetime(2026, 4, 10),
        updated_at=__import__("datetime").datetime(2026, 4, 10),
    )
    pending_event = CampaignEvent(
        campaign_id="camp-1",
        event_type="travel_hazard",
        title="Roadside Ambush Signs",
        content="Bandits are watching the road.",
        details={"hook_type": "encounter", "enemy_count": 2, "escalation_hours": 6},
        world_time_hours=10,
    )
    action_logs = DummyActionLogStore()
    events = DummyEventStore()
    events.save(pending_event)
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_events", lambda: events)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_factions", lambda: type("FactionStore", (), {"get": lambda self, faction_id: None})())
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.advance_campaign_time_procedure(
        "camp-1",
        routes.AdvanceCampaignTimeRequest(hours=6, procedure_type="downtime"),
    )

    assert result["matured_events"]
    assert result["matured_events"][0]["title"].endswith("(Escalated)")
    assert result["matured_events"][0]["details"]["enemy_count"] == 3
    assert "Escalated 1 pending event" in result["summary"]


def test_advance_time_procedure_applies_matured_event_consequences(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Consequence Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=12,
        notes="",
        cover_image=None,
        created_at=__import__("datetime").datetime(2026, 4, 10),
        updated_at=__import__("datetime").datetime(2026, 4, 10),
    )
    player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"sp": 5, "gp": 0, "cp": 0})
    faction = CampaignFaction(campaign_id="camp-1", name="River Guild", standing_with_player="neutral")
    quest = routes.CampaignQuest(campaign_id="camp-1", title="Beat the Deadline", description="", stages=[])
    events = DummyEventStore()
    events.save(CampaignEvent(
        campaign_id="camp-1",
        event_type="travel_complication",
        title="Supply Trouble",
        content="Supplies are running thin.",
        details={"hook_type": "resource_pressure", "escalation_hours": 4, "supply_cost_sp": 2},
        world_time_hours=12,
    ))
    events.save(CampaignEvent(
        campaign_id="camp-1",
        event_type="travel_opportunity",
        title="Helpful Travelers",
        content="Talk on the road turns tense.",
        details={"hook_type": "social", "escalation_hours": 4, "faction_id": faction.id},
        world_time_hours=12,
    ))
    events.save(CampaignEvent(
        campaign_id="camp-1",
        event_type="time_pressure",
        title="A New Day Begins",
        content="Delay is costly.",
        details={"hook_type": "time_pressure", "escalation_hours": 4, "quest_id": quest.id},
        world_time_hours=12,
    ))
    action_logs = DummyActionLogStore()
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return player_sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(player_sheet, key, value)
            return player_sheet

    class DummyFactionStore:
        def get(self, faction_id: str):
            return faction if faction_id == faction.id else None

        def get_all(self, campaign_id: str):
            return [faction]

        def save(self, updated):
            faction.standing_with_player = updated.standing_with_player
            faction.relationship_notes = updated.relationship_notes

    class DummyQuestStore:
        def get(self, quest_id: str):
            return quest if quest_id == quest.id else None

        def save(self, updated):
            quest.description = updated.description
            quest.updated_at = updated.updated_at
            quest.status = updated.status

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_factions", lambda: DummyFactionStore())
    monkeypatch.setattr(routes, "_quests", lambda: DummyQuestStore())
    monkeypatch.setattr(routes, "_events", lambda: events)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.advance_campaign_time_procedure(
        "camp-1",
        routes.AdvanceCampaignTimeRequest(hours=4, procedure_type="downtime"),
    )

    assert result["player_sheet"]["currencies"]["sp"] == 3
    assert result["faction_updates"][-1]["to"] == "wary"
    assert "Pressure increased on" in result["quest_updates"][0]["description"]
    assert len(result["matured_event_consequences"]) == 3
