from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.campaigns.procedures import generate_treasure_bundle
from app.core.models import ActionLogEntry, CampaignEventStatus, CampaignObjective, CampaignQuest, CharacterSheet, PlayMode, QuestStage


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


def test_generate_treasure_bundle_scales_with_challenge():
    small = generate_treasure_bundle(challenge_rating=1, source_type="loot", source_name="Bandits")
    large = generate_treasure_bundle(challenge_rating=5, source_type="loot", source_name="Ogre Camp")

    assert large["currencies"]["gp"] > small["currencies"]["gp"]
    assert small["item_suggestions"]


def test_generate_campaign_treasure_applies_to_sheet(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Treasure Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=4,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )
    sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"gp": 2, "sp": 0, "cp": 0})
    action_logs = DummyActionLogStore()
    audits = []

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
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

    result = routes.generate_campaign_treasure_procedure(
        "camp-1",
        routes.GenerateTreasureRequest(
            challenge_rating=2,
            source_type="quest",
            source_name="Recovered cache",
            apply_to_player=True,
        ),
    )

    assert result["treasure"]["currencies"]["gp"] > 0
    assert result["player_sheet"]["currencies"]["gp"] > 2
    assert action_logs.saved[0].action_type == "treasure"
    assert audits[0]["event_type"] == "treasure"


def test_complete_encounter_with_treasure_updates_player_sheet(monkeypatch):
    campaign = SimpleNamespace(id="camp-1")
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Roadside Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=15, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="bandit-1", name="Bandit", team="enemy", initiative_roll=10, initiative_modifier=1),
        ],
    )
    sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"gp": 1, "sp": 0, "cp": 0})
    action_logs = DummyActionLogStore()
    audits = []

    class DummyEncounterStore:
        def get(self, encounter_id: str):
            return encounter if encounter_id == encounter.id else None

        def save(self, updated):
            encounter.status = updated.status
            encounter.summary = updated.summary
            encounter.participants = updated.participants

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(sheet, key, value)
            return sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_encounters", lambda: DummyEncounterStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    result = routes.complete_campaign_encounter(
        "camp-1",
        encounter.id,
        routes.CompleteEncounterRequest(
            summary="Bandits driven off.",
            generate_treasure=True,
            treasure_challenge_rating=2,
            apply_treasure_to_player=True,
        ),
    )

    assert result["treasure"]["currencies"]["gp"] > 0
    assert result["player_sheet"]["currencies"]["gp"] > 1
    assert action_logs.saved[0].details["treasure"]
    assert audits[0]["payload"]["treasure"]


def test_advance_quest_with_treasure_updates_player_sheet(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Quest Reward Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=6,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )
    quest = CampaignQuest(
        campaign_id="camp-1",
        title="Clear the Watchpost",
        stages=[QuestStage(description="Defeat the raiders", completed=False, order=0)],
    )
    sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"gp": 0, "sp": 0, "cp": 0})
    action_logs = DummyActionLogStore()
    audits = []

    class DummyQuestStore:
        def get(self, quest_id: str):
            return quest if quest_id == quest.id else None

        def save(self, updated):
            quest.status = updated.status
            quest.stages = updated.stages
            quest.updated_at = updated.updated_at

    class DummyObjectiveStore:
        def get(self, objective_id: str):
            return None

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(sheet, key, value)
            return sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_quests", lambda: DummyQuestStore())
    monkeypatch.setattr(routes, "_objectives", lambda: DummyObjectiveStore())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    result = routes.advance_campaign_quest_procedure(
        "camp-1",
        routes.AdvanceCampaignQuestRequest(
            quest_id=quest.id,
            stage_id=quest.stages[0].id,
            generate_treasure=True,
            treasure_challenge_rating=2,
            apply_treasure_to_player=True,
        ),
    )

    assert result["treasure"]["currencies"]["gp"] > 0
    assert result["player_sheet"]["currencies"]["gp"] > 0
    assert action_logs.saved[0].details["treasure"]
    assert audits[0]["payload"]["treasure"]


def test_resolved_event_with_treasure_updates_player_sheet(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Event Reward Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=7,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )
    sheet = CharacterSheet(campaign_id="camp-1", name="Aria", currencies={"gp": 0, "sp": 0, "cp": 0})
    action_logs = DummyActionLogStore()
    audits = []

    class DummyEventStore:
        def __init__(self):
            self.saved = []

        def get(self, event_id: str):
            return next((event for event in self.saved if event.id == event_id), None)

        def save(self, event):
            existing = self.get(event.id)
            if existing:
                self.saved = [event if item.id == event.id else item for item in self.saved]
            else:
                self.saved.append(event)

    event_store = DummyEventStore()

    class DummySheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return sheet

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            for key, value in kwargs.items():
                if value is not None:
                    setattr(sheet, key, value)
            return sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_events", lambda: event_store)
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheetStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.save_campaign_event(
        "camp-1",
        routes.SaveCampaignEventRequest(
            title="Recovered Tribute Chest",
            event_type="world",
            status=CampaignEventStatus.RESOLVED.value,
            generate_treasure=True,
            treasure_challenge_rating=2,
            apply_treasure_to_player=True,
        ),
    )

    assert result["treasure"]["currencies"]["gp"] > 0
    assert result["player_sheet"]["currencies"]["gp"] > 0
    assert action_logs.saved[0].action_type == "treasure"
    assert audits[0]["event_type"] == "treasure"
