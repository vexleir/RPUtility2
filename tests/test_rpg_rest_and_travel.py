from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.campaigns.procedures import build_campaign_events, generate_travel_event
from app.core.models import ActionLogEntry, CampaignEvent, CampaignEventStatus, PlayMode


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

    def get(self, event_id: str):
        for event in self.saved:
            if event.id == event_id:
                return event
        return None

    def get_all(self, campaign_id: str):
        return [event for event in self.saved if event.campaign_id == campaign_id]


class DummyEncounterStore:
    def __init__(self):
        self.saved = []

    def save(self, encounter):
        self.saved.append(encounter)

    def get_active(self, campaign_id: str, scene_id: str | None):
        return None


def test_generate_travel_event_is_deterministic():
    first = generate_travel_event(campaign_id="camp-1", world_time_hours=12, destination="Old Watchtower")
    second = generate_travel_event(campaign_id="camp-1", world_time_hours=12, destination="Old Watchtower")

    assert first.event_type == second.event_type
    assert first.title == second.title
    assert "Old Watchtower" in first.content
    assert first.details["destination"] == "Old Watchtower"


def test_build_campaign_events_adds_travel_and_day_rollover():
    events = build_campaign_events(
        campaign_id="camp-1",
        start_hours=20,
        end_hours=28,
        procedure_type="travel",
        destination="Stone Ford",
    )

    assert len(events) == 2
    assert events[0].event_type.startswith("travel_")
    assert events[1].event_type == "time_pressure"


def test_advance_time_procedure_generates_and_returns_events(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Travel Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=2,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 9),
        updated_at=datetime(2026, 4, 9),
    )
    action_logs = DummyActionLogStore()
    event_store = DummyEventStore()
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_events", lambda: event_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_factions", lambda: type("FactionStore", (), {"get": lambda self, faction_id: None})())
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.advance_campaign_time_procedure(
        "camp-1",
        routes.AdvanceCampaignTimeRequest(
            hours=6,
            procedure_type="travel",
            destination="Old Watchtower",
        ),
    )

    assert result["events"]
    assert event_store.saved
    assert result["events"][0]["title"] == event_store.saved[0].title
    assert "Generated" in result["summary"]
    assert action_logs.saved[0].details["generated_events"]
    assert audits[0]["payload"]["generated_events"]


def test_generate_encounter_from_campaign_event(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Encounter Hook Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=8,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )
    event = CampaignEvent(
        campaign_id="camp-1",
        event_type="travel_hazard",
        title="Roadside Ambush Signs",
        content="Bandits are closing in.",
        details={"hook_type": "encounter", "enemy_count": 2},
        world_time_hours=8,
    )
    event_store = DummyEventStore()
    event_store.save(event)
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    scene = SimpleNamespace(id="scene-1", campaign_id="camp-1", npc_ids=[])

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_events", lambda: event_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: scene})())
    monkeypatch.setattr(routes, "_npcs", lambda: type("NpcStore", (), {"get_many": lambda self, ids: []})())

    def fake_participant_builder(campaign_id, req):
        return routes.build_encounter_participant(
            owner_type=req.owner_type,
            owner_id=req.owner_id,
            name=req.name or ("Player" if req.owner_type == "player" else "Enemy"),
            team=req.team,
            initiative_roll=req.initiative_roll,
            initiative_modifier=req.initiative_modifier,
            sheet=None,
        )

    monkeypatch.setattr(routes, "_build_encounter_participant_request", fake_participant_builder)

    result = routes.generate_encounter_from_campaign_event("camp-1", event.id)

    assert result["encounter"]["name"] == "Roadside Ambush Signs"
    assert len(result["encounter"]["participants"]) == 3
    assert result["event"]["status"] == CampaignEventStatus.RESOLVED.value
    assert encounter_store.saved
    assert action_logs.saved[0].action_type == "campaign_event"
    assert audits[0]["event_type"] == "campaign_event"
