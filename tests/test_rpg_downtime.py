from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.campaigns.procedures import build_downtime_activity_result
from app.core.models import (
    ActionLogEntry,
    CampaignEvent,
    CampaignFaction,
    CampaignObjective,
    CampaignQuest,
    CharacterSheet,
    PlayMode,
)


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


class DummyEventStore:
    def __init__(self):
        self.saved: list[CampaignEvent] = []

    def save(self, event):
        for index, existing in enumerate(self.saved):
            if existing.id == event.id:
                self.saved[index] = event
                break
        else:
            self.saved.append(event)

    def get_all(self, campaign_id: str):
        return [event for event in self.saved if event.campaign_id == campaign_id]


def _campaign_stub(world_time_hours: int = 0):
    return SimpleNamespace(
        id="camp-1",
        name="Downtime Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=world_time_hours,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )


def test_build_downtime_activity_result_is_deterministic_for_work():
    first = build_downtime_activity_result(
        campaign_id="camp-1",
        activity_type="work",
        days=2,
        subject="dock labor",
        world_time_hours=48,
    )
    second = build_downtime_activity_result(
        campaign_id="camp-1",
        activity_type="work",
        days=2,
        subject="dock labor",
        world_time_hours=48,
    )

    assert first["currency_delta"] == second["currency_delta"]
    assert first["summary"] == second["summary"]
    assert first["currency_delta"]["gp"] >= 1


def test_run_campaign_downtime_work_updates_wallet_and_logs(monkeypatch):
    campaign = _campaign_stub(world_time_hours=24)
    player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"gp": 1, "sp": 0, "cp": 0})
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

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_events", lambda: DummyEventStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="work", days=2, subject="dock labor"),
    )

    assert result["world_time"]["total_hours"] == 72
    assert result["reward_currencies"]["gp"] >= 1
    assert result["player_sheet"]["currencies"]["gp"] > 1
    assert action_logs.saved[0].action_type == "campaign_procedure"
    assert audits[0]["event_type"] == "campaign_procedure"


def test_run_campaign_downtime_updates_targets_and_generates_events(monkeypatch):
    campaign = _campaign_stub(world_time_hours=48)
    faction = CampaignFaction(campaign_id="camp-1", name="Silver Circle", standing_with_player="neutral")
    quest = CampaignQuest(campaign_id="camp-1", title="Find the Archive", description="", stages=[])
    objective = CampaignObjective(campaign_id="camp-1", title="Sharpen Technique", description="")
    action_logs = DummyActionLogStore()
    event_store = DummyEventStore()
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    class DummyFactionStore:
        def get(self, faction_id: str):
            return faction if faction_id == faction.id else None

        def save(self, updated):
            faction.standing_with_player = updated.standing_with_player
            faction.relationship_notes = updated.relationship_notes
            faction.updated_at = updated.updated_at

    class DummyQuestStore:
        def get(self, quest_id: str):
            return quest if quest_id == quest.id else None

        def save(self, updated):
            quest.description = updated.description
            quest.updated_at = updated.updated_at

    class DummyObjectiveStore:
        def get(self, objective_id: str):
            return objective if objective_id == objective.id else None

        def save(self, updated):
            objective.description = updated.description
            objective.updated_at = updated.updated_at

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_factions", lambda: DummyFactionStore())
    monkeypatch.setattr(routes, "_quests", lambda: DummyQuestStore())
    monkeypatch.setattr(routes, "_objectives", lambda: DummyObjectiveStore())
    monkeypatch.setattr(routes, "_events", lambda: event_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    research = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="research", days=1, subject="the archive", quest_id=quest.id),
    )
    training = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="training", days=1, subject="sword drills", objective_id=objective.id, quest_id=quest.id),
    )
    carouse = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="carouse", days=2, subject="guild elders", faction_id=faction.id),
    )

    assert research["events"]
    assert event_store.saved
    assert "Research during downtime uncovered a lead" in quest.description
    assert "Training on sword drills continued" in objective.description
    assert carouse["faction_updates"][0]["to"] == "friendly"
    assert len(action_logs.saved) == 3
    assert len(audits) == 3


def test_run_campaign_downtime_training_applies_sheet_rewards(monkeypatch):
    campaign = _campaign_stub(world_time_hours=24)
    player_sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        skill_modifiers={"athletics": 2},
        resource_pools={"ki": {"current": 2, "max": 2, "restores_on": "short_rest"}},
    )
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

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_events", lambda: DummyEventStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    skill_result = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="training", days=3, subject="athletics"),
    )
    assert skill_result["training_updates"]["skill_increases"] == {"athletics": 1}
    assert skill_result["player_sheet"]["skill_modifiers"]["athletics"] == 3

    pool_result = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="training", days=3, subject="ki"),
    )
    assert pool_result["training_updates"]["resource_pool_increases"] == {"ki": 1}
    assert pool_result["player_sheet"]["resource_pools"]["ki"]["max"] == 3
    assert pool_result["player_sheet"]["resource_pools"]["ki"]["current"] == 3
    assert len(action_logs.saved) == 2
    assert len(audits) == 2


def test_run_campaign_downtime_craft_updates_wallet_and_item_state(monkeypatch):
    campaign = _campaign_stub(world_time_hours=24)
    player_sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        armor_class=10,
        currencies={"gp": 10, "sp": 0, "cp": 0},
    )
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

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_events", lambda: DummyEventStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    expected_activity = build_downtime_activity_result(
        campaign_id="camp-1",
        activity_type="craft",
        days=2,
        subject="shield",
        world_time_hours=72,
    )
    result = routes.run_campaign_downtime_procedure(
        "camp-1",
        routes.RunDowntimeRequest(activity_type="craft", days=2, subject="shield"),
    )

    assert result["reward_currencies"]["gp"] == -expected_activity["crafted_item"]["cost_gp"]
    assert result["player_sheet"]["currencies"]["gp"] == 10 - expected_activity["crafted_item"]["cost_gp"]
    assert result["crafted_item"]["entry"]["slug"] == "shield"
    assert result["crafted_item"]["auto_equipped"] is True
    assert result["player_sheet"]["equipped_items"]["off_hand"] == "shield"
    assert result["player_sheet"]["armor_class"] == 12
    assert "[Crafted] Shield completed during downtime." in result["player_sheet"]["notes"]
    assert action_logs.saved[0].summary.endswith("Crafted Shield.")
    assert audits[0]["event_type"] == "campaign_procedure"
