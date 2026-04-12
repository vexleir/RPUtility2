from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.web.campaign_routes as routes
from app.campaigns.procedures import advance_campaign_quest
from app.campaigns.scene_prompter import build_scene_messages
from app.core.models import (
    ActionLogEntry,
    CampaignObjective,
    CampaignQuest,
    CampaignScene,
    ObjectiveStatus,
    PlayMode,
    PlayerCharacter,
    QuestStage,
)


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


def test_advance_campaign_quest_marks_stage_and_autocompletes():
    quest = CampaignQuest(
        campaign_id="camp-1",
        title="Recover the Ledger",
        stages=[
            QuestStage(description="Find the hideout", completed=True, order=0),
            QuestStage(description="Recover the ledger", completed=False, order=1),
        ],
    )

    updated = advance_campaign_quest(quest, stage_id=quest.stages[1].id)

    assert updated.stages[1].completed is True
    assert updated.status.value == "completed"


def test_advance_quest_procedure_updates_quest_objective_and_time(monkeypatch):
    campaign = SimpleNamespace(
        id="camp-1",
        name="Quest Test",
        model_name=None,
        summary_model_name=None,
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={},
        style_guide=SimpleNamespace(model_dump=lambda: {}),
        gen_settings=SimpleNamespace(model_dump=lambda: {}),
        world_time_hours=5,
        notes="",
        cover_image=None,
        created_at=datetime(2026, 4, 9),
        updated_at=datetime(2026, 4, 9),
    )
    objective = CampaignObjective(campaign_id="camp-1", title="Learn who hired the smugglers")
    quest = CampaignQuest(
        campaign_id="camp-1",
        title="Smugglers in the Ash Quarter",
        stages=[
            QuestStage(description="Track the courier", completed=False, order=0),
            QuestStage(description="Interrogate the fence", completed=False, order=1),
        ],
    )
    action_logs = DummyActionLogStore()
    audits = []

    class DummyCampaignStore:
        def update(self, campaign_id: str, **kwargs):
            for key, value in kwargs.items():
                setattr(campaign, key, value)
            return campaign

    class DummyQuestStore:
        def get(self, quest_id: str):
            return quest if quest_id == quest.id else None

        def save(self, updated):
            quest.status = updated.status
            quest.updated_at = updated.updated_at
            quest.stages = updated.stages

    class DummyObjectiveStore:
        def get(self, objective_id: str):
            return objective if objective_id == objective.id else None

        def save(self, updated):
            objective.status = updated.status
            objective.updated_at = updated.updated_at

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: campaign)
    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_quests", lambda: DummyQuestStore())
    monkeypatch.setattr(routes, "_objectives", lambda: DummyObjectiveStore())
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: None})())

    result = routes.advance_campaign_quest_procedure(
        "camp-1",
        routes.AdvanceCampaignQuestRequest(
            quest_id=quest.id,
            stage_id=quest.stages[0].id,
            objective_ids=[objective.id],
            advance_hours=4,
            note="The courier was cornered at the canal.",
        ),
    )

    assert result["quest"]["stages"][0]["completed"] is True
    assert result["objective_updates"][0]["to"] == ObjectiveStatus.COMPLETED.value
    assert result["world_time"]["total_hours"] == 9
    assert action_logs.saved[0].action_type == "quest_progress"
    assert audits[0]["event_type"] == "quest_progress"


def test_scene_prompt_includes_active_objectives_and_quests():
    campaign = SimpleNamespace(
        play_mode=PlayMode.NARRATIVE,
        style_guide=SimpleNamespace(tone="", prose_style="", avoids="", magic_system=""),
        world_time_hours=12,
        system_pack=None,
    )
    scene = CampaignScene(campaign_id="camp-1", scene_number=1, turns=[], allow_unselected_npcs=False)
    messages = build_scene_messages(
        campaign=campaign,
        player_character=PlayerCharacter(campaign_id="camp-1", name="Aria"),
        character_sheet=None,
        recent_action_logs=[],
        world_facts=[],
        npcs_in_scene=[],
        active_threads=[],
        objectives=[CampaignObjective(campaign_id="camp-1", title="Reach the lighthouse", description="before dawn")],
        quests=[CampaignQuest(campaign_id="camp-1", title="Lights in the Mist", stages=[QuestStage(description="Secure passage", order=0)])],
        chronicle=[],
        places=[],
        factions=[],
        npc_relationships=[],
        all_world_npcs=[],
        allow_unselected_npcs=False,
        scene=scene,
        user_message="I look for a boat.",
    )

    system_prompt = messages[0]["content"]
    assert "[ACTIVE OBJECTIVES]" in system_prompt
    assert "Reach the lighthouse" in system_prompt
    assert "[ACTIVE QUESTS]" in system_prompt
    assert "Lights in the Mist" in system_prompt
