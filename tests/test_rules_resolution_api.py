from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.core.models import (
    ActionLogEntry,
    AttackResolution,
    CampaignScene,
    CharacterSheet,
    DamageResolution,
    Encounter,
    EncounterParticipant,
    HealingResolution,
    PlayMode,
)
import app.web.campaign_routes as routes
from app.rules.procedures.gm_flow import GM_DECISION_START


class DummyCampaign:
    play_mode = PlayMode.RULES
    system_pack = "d20-fantasy-core"


class DummyScene:
    id = "scene-1"
    campaign_id = "camp-1"


class DummySheetStore:
    def __init__(self, sheet: CharacterSheet):
        self.sheet = sheet

    def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player") -> CharacterSheet:
        return self.sheet

    def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs) -> CharacterSheet:
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.sheet, key, value)
        return self.sheet


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry) -> None:
        self.saved.append(entry)


class DummyRuleAuditStore:
    def __init__(self):
        self.saved = []

    def save(self, entry) -> None:
        self.saved.append(entry)

    def get_recent(self, campaign_id: str, n: int = 50):
        return self.saved[:n]


class DummyEncounterStore:
    def __init__(self, encounter=None):
        self.encounter = encounter
        self.saved = []

    def get_active(self, campaign_id: str, scene_id: str | None = None):
        return self.encounter

    def save(self, encounter):
        self.encounter = encounter
        self.saved.append(encounter)


def test_attack_resolution_route_logs_attack(monkeypatch):
    log_store = DummyActionLogStore()
    audit_store = DummyRuleAuditStore()
    encounter_store = DummyEncounterStore()
    sheet_store = DummySheetStore(CharacterSheet(campaign_id="camp-1", name="Aria"))

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(
        routes,
        "resolve_d20_attack",
        lambda **kwargs: AttackResolution(
            attack_roll=17,
            dice_rolls=[17],
            modifier=5,
            total=22,
            target_armor_class=15,
            hit=True,
            critical_hit=False,
            outcome="hit",
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )
    monkeypatch.setattr(
        routes,
        "resolve_damage_roll",
        lambda **kwargs: DamageResolution(
            roll_expression="1d8+3",
            damage_type="slashing",
            dice_total=6,
            dice_rolls=[6],
            modifier=3,
            total=9,
            critical_hit=False,
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )

    result = routes.resolve_campaign_attack(
        "camp-1",
        routes.ResolveAttackRequest(
            source="strength",
            target_armor_class=15,
            damage_roll_expression="1d8",
            damage_modifier=3,
            damage_type="slashing",
            reason="Sword slash",
        ),
    )
    assert result["attack"]["hit"] is True
    assert result["damage"]["total"] == 9
    assert len(log_store.saved) == 1
    assert log_store.saved[0].action_type == "attack"
    assert log_store.saved[0].details["attack"]["total"] == 22
    assert log_store.saved[0].details["damage"]["damage_type"] == "slashing"
    assert len(audit_store.saved) == 1
    assert audit_store.saved[0].event_type == "attack"
    listed = routes.get_rule_audits("camp-1", n=10)
    assert listed[0]["event_type"] == "attack"


def test_healing_resolution_route_applies_to_sheet_and_logs(monkeypatch):
    log_store = DummyActionLogStore()
    audit_store = DummyRuleAuditStore()
    encounter_store = DummyEncounterStore()
    sheet_store = DummySheetStore(CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        current_hp=5,
        max_hp=12,
        resource_pools={"spell_slot_1": {"current": 2, "max": 4, "restores_on": "long_rest"}},
    ))

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(
        routes,
        "resolve_healing_roll",
        lambda **kwargs: HealingResolution(
            roll_expression="1d4+2",
            dice_total=3,
            dice_rolls=[3],
            modifier=2,
            total=5,
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )

    result = routes.resolve_campaign_healing(
        "camp-1",
        routes.ResolveHealingRequest(
            source="healing_word",
            roll_expression="1d4",
            modifier=2,
            apply_to_sheet=True,
            reason="A quick burst of magic",
            resource_costs={"spell_slot_1": 1},
        ),
    )
    assert result["healing"]["total"] == 5
    assert result["sheet"]["current_hp"] == 10
    assert result["summary"] == "recovered 5 HP"
    assert len(log_store.saved) == 1
    assert log_store.saved[0].action_type == "healing"
    assert log_store.saved[0].details["sheet"]["current_hp"] == 10
    assert log_store.saved[0].details["resources_consumed"][0]["resource"] == "spell_slot_1"
    assert result["sheet"]["resource_pools"]["spell_slot_1"]["current"] == 1
    assert len(audit_store.saved) == 1
    assert audit_store.saved[0].event_type == "healing"


def test_attack_resolution_rejects_out_of_range_target(monkeypatch):
    encounter_store = DummyEncounterStore(
        Encounter(
            campaign_id="camp-1",
            scene_id="scene-1",
            participants=[
                EncounterParticipant(id="actor-1", owner_type="player", owner_id="player", name="Aria", team="player", initiative_total=18, current_hp=12, max_hp=12),
                EncounterParticipant(id="target-1", owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_total=10, armor_class=13, current_hp=11, max_hp=11),
            ],
        )
    )
    sheet_store = DummySheetStore(CharacterSheet(campaign_id="camp-1", name="Aria"))

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: DummyActionLogStore())
    monkeypatch.setattr(routes, "_rule_audits", lambda: DummyRuleAuditStore())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)

    import pytest
    with pytest.raises(routes.HTTPException, match="out of range"):
        routes.resolve_campaign_attack(
            "camp-1",
            routes.ResolveAttackRequest(
                source="shortbow",
                target_participant_id="target-1",
                target_armor_class=13,
                range_feet=30,
                target_distance_feet=60,
                damage_roll_expression="1d6",
            ),
        )


def test_contested_check_route_logs_and_audits(monkeypatch):
    log_store = DummyActionLogStore()
    audit_store = DummyRuleAuditStore()
    encounter_store = DummyEncounterStore()
    player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria", skill_modifiers={"stealth": 5})
    npc_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="guard-1", name="Gate Guard", skill_modifiers={"perception": 2})

    class ContestedSheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return player_sheet
            if owner_type == "npc" and owner_id == "guard-1":
                return npc_sheet
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            return player_sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: ContestedSheetStore())
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)

    result = routes.resolve_campaign_contested_check(
        "camp-1",
        routes.ResolveContestedCheckRequest(
            actor_source="stealth",
            opponent_source="perception",
            opponent_owner_type="npc",
            opponent_owner_id="guard-1",
            reason="Slip by the gate",
        ),
    )
    assert result["winner"] in {"actor", "opponent", "tie"}
    assert len(log_store.saved) == 1
    assert log_store.saved[0].action_type == "contested_check"
    assert log_store.saved[0].details["resolution"]["opponent"]["name"] == "Gate Guard"
    assert len(audit_store.saved) == 1
    assert audit_store.saved[0].event_type == "contested_check"


def test_stream_delta_filter_hides_gm_contract_marker():
    emit, buffer, saw = routes._consume_visible_stream_delta("", "Visible text ", False)
    assert emit == ""
    assert saw is False

    emit, buffer, saw = routes._consume_visible_stream_delta(buffer, f"more text {GM_DECISION_START}", False)
    assert "Visible text more text " in emit
    assert saw is True
    assert GM_DECISION_START in buffer


def test_scene_gm_procedure_preview_returns_plan_and_recent_decisions(monkeypatch):
    class PreviewCampaign:
        play_mode = PlayMode.RULES
        system_pack = "d20-fantasy-core"

    scene = DummyScene()
    audit_store = DummyRuleAuditStore()
    audit_store.saved = [
        type(
            "AuditEvent",
            (),
            {
                "id": "a1",
                "campaign_id": "camp-1",
                "scene_id": "scene-1",
                "event_type": "gm_decision",
                "actor_name": "GM",
                "source": "check",
                "reason": "old turn",
                "payload": {"resolution_kind": "check"},
                "created_at": __import__("datetime").datetime(2026, 4, 8),
            },
        )()
    ]

    def get_recent_filtered(campaign_id: str, *, scene_id=None, event_type=None, n=50):
        return audit_store.saved[:n]

    audit_store.get_recent_filtered = get_recent_filtered

    monkeypatch.setattr(routes, "_campaigns", lambda: type("CampaignStore", (), {"get": lambda self, campaign_id: PreviewCampaign()})())
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get": lambda self, scene_id: scene})())
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)

    result = routes.get_scene_gm_procedure_preview(
        "camp-1",
        "scene-1",
        routes.GMProcedurePreviewRequest(message="I sneak past the guards."),
    )
    assert result["plan"]["resolution_kind"] == "check"
    assert result["suggested_decision"]["consult_rules"] is True
    assert result["suggested_actions"][0]["action_type"] == "check"
    assert result["recent_gm_decisions"][0]["event_type"] == "gm_decision"


def test_scene_gm_decisions_endpoint_filters_scene(monkeypatch):
    scene = DummyScene()
    audit_store = DummyRuleAuditStore()
    audit_store.saved = [
        type(
            "AuditEvent",
            (),
            {
                "id": "a1",
                "campaign_id": "camp-1",
                "scene_id": "scene-1",
                "event_type": "gm_decision",
                "actor_name": "GM",
                "source": "attack",
                "reason": "chat",
                "payload": {"resolution_kind": "attack"},
                "created_at": __import__("datetime").datetime(2026, 4, 8),
            },
        )()
    ]

    def get_recent_filtered(campaign_id: str, *, scene_id=None, event_type=None, n=50):
        assert scene_id == "scene-1"
        assert event_type == "gm_decision"
        return audit_store.saved[:n]

    audit_store.get_recent_filtered = get_recent_filtered

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get": lambda self, scene_id: scene})())
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)

    result = routes.get_scene_gm_decisions("camp-1", "scene-1", n=10)
    assert result[0]["source"] == "attack"


def test_attack_resolution_can_apply_damage_to_active_encounter(monkeypatch):
    log_store = DummyActionLogStore()
    audit_store = DummyRuleAuditStore()
    player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria")
    actor = EncounterParticipant(
        id="actor-1",
        owner_type="player",
        owner_id="player",
        name="Aria",
        team="player",
        armor_class=13,
        current_hp=12,
        max_hp=12,
        initiative_total=16,
    )
    target = EncounterParticipant(
        id="target-1",
        owner_type="npc",
        owner_id="guard-1",
        name="Gate Guard",
        team="enemy",
        armor_class=15,
        current_hp=11,
        max_hp=11,
        initiative_total=10,
    )
    encounter = Encounter(campaign_id="camp-1", scene_id="scene-1", name="Fight", participants=[actor, target], current_turn_index=0)
    encounter_store = DummyEncounterStore(encounter)

    class EncounterAwareSheets(DummySheetStore):
        def __init__(self):
            super().__init__(player_sheet)
            self.npc_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="guard-1", name="Gate Guard", current_hp=11, max_hp=11)

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            if owner_type == "npc" and owner_id == "guard-1":
                for key, value in kwargs.items():
                    if value is not None:
                        setattr(self.npc_sheet, key, value)
                return self.npc_sheet
            return super().save_for_owner(campaign_id, owner_type, owner_id, **kwargs)

    sheet_store = EncounterAwareSheets()

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(
        routes,
        "resolve_d20_attack",
        lambda **kwargs: AttackResolution(
            attack_roll=16,
            dice_rolls=[16],
            modifier=5,
            total=21,
            target_armor_class=15,
            hit=True,
            critical_hit=False,
            outcome="hit",
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )
    monkeypatch.setattr(
        routes,
        "resolve_damage_roll",
        lambda **kwargs: DamageResolution(
            roll_expression="1d8+3",
            damage_type="slashing",
            dice_total=5,
            dice_rolls=[5],
            modifier=3,
            total=8,
            critical_hit=False,
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )

    result = routes.resolve_campaign_attack(
        "camp-1",
        routes.ResolveAttackRequest(
            source="strength",
            target_participant_id="target-1",
            target_armor_class=10,
            damage_roll_expression="1d8",
            damage_modifier=3,
            damage_type="slashing",
            reason="Sword slash",
        ),
    )

    assert result["target_participant"]["current_hp"] == 3
    assert result["encounter"]["participants"][1]["current_hp"] == 3
    assert sheet_store.npc_sheet.current_hp == 3


def test_healing_resolution_can_apply_to_active_encounter_participant(monkeypatch):
    log_store = DummyActionLogStore()
    audit_store = DummyRuleAuditStore()
    sheet_store = DummySheetStore(CharacterSheet(campaign_id="camp-1", name="Aria", current_hp=5, max_hp=12))
    target = EncounterParticipant(
        id="ally-1",
        owner_type="player",
        owner_id="player",
        name="Aria",
        team="player",
        current_hp=4,
        max_hp=12,
        initiative_total=12,
    )
    encounter = Encounter(campaign_id="camp-1", scene_id="scene-1", name="Fight", participants=[target], current_turn_index=0)
    encounter_store = DummyEncounterStore(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: DummyScene()})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_action_logs", lambda: log_store)
    monkeypatch.setattr(routes, "_rule_audits", lambda: audit_store)
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(
        routes,
        "resolve_healing_roll",
        lambda **kwargs: HealingResolution(
            roll_expression="1d4+2",
            dice_total=3,
            dice_rolls=[3],
            modifier=2,
            total=5,
            source=kwargs["source"],
            reason=kwargs["reason"],
        ),
    )

    result = routes.resolve_campaign_healing(
        "camp-1",
        routes.ResolveHealingRequest(
            source="healing_word",
            roll_expression="1d4",
            modifier=2,
            apply_to_sheet=False,
            target_participant_id="ally-1",
            reason="A quick burst of magic",
        ),
    )

    assert result["target_participant"]["current_hp"] == 9
    assert result["encounter"]["participants"][0]["current_hp"] == 9
    assert sheet_store.sheet.current_hp == 9


def test_scene_mechanics_followup_stream_persists_assistant_turn(monkeypatch):
    scene = CampaignScene(campaign_id="camp-1", scene_number=1, title="Fight", location="Bridge")
    scene.id = "scene-1"
    scene.turns = []
    scene.confirmed = False

    saved_audits = []

    class DummySceneStore:
        def get(self, scene_id: str):
            return scene if scene_id == "scene-1" else None

        def save(self, value):
            nonlocal scene
            scene = value

    class DummyCampaignStore:
        def get(self, campaign_id: str):
            return SimpleNamespace(
                model_name="test-model",
                play_mode=PlayMode.RULES,
                system_pack="d20-fantasy-core",
                gen_settings=SimpleNamespace(
                    temperature=0.8,
                    top_p=0.95,
                    top_k=0,
                    min_p=0.05,
                    repeat_penalty=1.1,
                    max_tokens=128,
                    seed=-1,
                    context_window=4096,
                ),
            )

    class DummyStreamResponse:
        def __init__(self, lines):
            self._lines = lines

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(self._lines)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(routes, "_campaigns", lambda: DummyCampaignStore())
    monkeypatch.setattr(routes, "_scenes", lambda: DummySceneStore())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: None})())
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: None})())
    monkeypatch.setattr(routes, "_facts", lambda: type("FactStore", (), {"get_all": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_threads", lambda: type("ThreadStore", (), {"get_active": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_chronicle", lambda: type("ChronStore", (), {"get_all": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_places", lambda: type("PlaceStore", (), {"get_all": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_factions", lambda: type("FactionStore", (), {"get_all": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_npcs", lambda: type("NpcStore", (), {"get_many": lambda self, ids: [], "get_all": lambda self, campaign_id: []})())
    monkeypatch.setattr(routes, "_npc_relationships", lambda: type("RelStore", (), {"get_for_npcs": lambda self, campaign_id, npc_ids: []})())
    monkeypatch.setattr(routes, "_action_logs", lambda: type("ActionStore", (), {"get_recent_for_scene": lambda self, campaign_id, scene_id, n=6: []})())
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: saved_audits.append(kwargs))
    monkeypatch.setattr(routes, "build_scene_messages", lambda **kwargs: [{"role": "system", "content": "test"}])

    import httpx

    lines = [
        json.dumps({"message": {"content": "The blow lands hard."}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]
    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: DummyStreamResponse(lines))

    response = routes.scene_mechanics_followup_stream(
        "camp-1",
        "scene-1",
        routes.SceneMechanicsFollowupRequest(prompt="Resolved attack: hit for 7 damage."),
    )

    async def consume(resp):
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(consume(response))
    assert "The blow lands hard." in body
    assert scene.turns[-1].role == "assistant"
    assert scene.turns[-1].content == "The blow lands hard."
    assert saved_audits[0]["event_type"] == "mechanics_followup"
