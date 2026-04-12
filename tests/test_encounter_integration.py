from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.web.campaign_routes as routes
from app.core.models import ActionLogEntry, CharacterSheet, PlayMode


class DummyEncounterStore:
    def __init__(self):
        self.entries = {}

    def save(self, encounter):
        self.entries[encounter.id] = encounter

    def get(self, encounter_id: str):
        return self.entries.get(encounter_id)

    def get_all(self, campaign_id: str):
        return [value for value in self.entries.values() if value.campaign_id == campaign_id]

    def get_active(self, campaign_id: str, scene_id: str | None = None):
        for encounter in self.get_all(campaign_id):
            if encounter.status != "active":
                continue
            if scene_id is not None and encounter.scene_id != scene_id:
                continue
            return encounter
        return None


class DummyActionLogStore:
    def __init__(self):
        self.saved: list[ActionLogEntry] = []

    def save(self, entry: ActionLogEntry):
        self.saved.append(entry)


def test_create_encounter_route_sorts_participants_and_logs(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria", abilities={"dexterity": 14})
    npc_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="guard-1", name="Guard", abilities={"dexterity": 12})

    class DummySheets:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return player_sheet
            if owner_type == "npc" and owner_id == "guard-1":
                return npc_sheet
            return None

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get": lambda self, scene_id: SimpleNamespace(id=scene_id, campaign_id="camp-1"), "get_active": lambda self, campaign_id: SimpleNamespace(id="scene-1", campaign_id="camp-1")})())
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheets())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: SimpleNamespace(name="Aria")})())
    monkeypatch.setattr(routes, "_npcs", lambda: type("NpcStore", (), {"get": lambda self, npc_id: SimpleNamespace(id=npc_id, name="Guard")})())

    result = routes.create_encounter(
        "camp-1",
        routes.CreateEncounterRequest(
            name="Gate Fight",
            scene_id="scene-1",
            participants=[
                routes.EncounterParticipantRequest(owner_type="npc", owner_id="guard-1", team="enemy", initiative_roll=10),
                routes.EncounterParticipantRequest(owner_type="player", owner_id="player", team="player", initiative_roll=15),
            ],
        ),
    )

    assert result["participants"][0]["name"] == "Aria"
    assert result["current_participant"]["name"] == "Aria"
    assert action_logs.saved[0].action_type == "encounter_start"
    assert audits[0]["event_type"] == "encounter_start"


def test_advance_and_complete_encounter_routes_update_state(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    synced = []
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sync_all_encounter_participants_to_sheets", lambda campaign_id, encounter: synced.append({"encounter_id": encounter.id}) or [{"participant_id": "p1"}])

    created = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=15, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(created)

    advanced = routes.advance_campaign_encounter_turn(
        "camp-1",
        created.id,
        routes.AdvanceEncounterTurnRequest(note="Aria ends her turn."),
    )
    assert advanced["current_turn_index"] == 1
    assert action_logs.saved[0].action_type == "encounter_turn_advance"

    completed = routes.complete_campaign_encounter(
        "camp-1",
        created.id,
        routes.CompleteEncounterRequest(summary="The guards are defeated."),
    )
    assert completed["status"] == "completed"
    assert completed["summary"] == "The guards are defeated."
    assert completed["sheet_sync"] == [{"participant_id": "p1"}]
    assert synced[0]["encounter_id"] == created.id
    assert audits[0]["event_type"] == "encounter_complete"


def test_player_action_routes_are_blocked_when_not_players_turn(monkeypatch):
    encounter_store = DummyEncounterStore()
    guard_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=9, initiative_modifier=2),
        ],
    )
    encounter_store.save(guard_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: SimpleNamespace(id="scene-1", campaign_id="camp-1")})())
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())

    with pytest.raises(routes.HTTPException, match="Guard's turn"):
        routes.resolve_campaign_check(
            "camp-1",
            routes.ResolveCheckRequest(source="stealth", difficulty=12),
        )


def test_player_action_spends_action_in_active_encounter(monkeypatch):
    encounter_store = DummyEncounterStore()
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: SimpleNamespace(id="scene-1", campaign_id="camp-1")})())
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: SimpleNamespace(name="Aria")})())
    monkeypatch.setattr(routes, "_action_logs", lambda: DummyActionLogStore())
    monkeypatch.setattr(routes, "_rule_audits", lambda: type("AuditStore", (), {"save": lambda self, entry: None})())

    result = routes.resolve_campaign_check(
        "camp-1",
        routes.ResolveCheckRequest(source="stealth", difficulty=12),
    )
    assert result["success"] in {True, False}
    active = encounter_store.get_active("camp-1", "scene-1")
    assert active.participants[0].action_available is False


def test_player_bonus_action_spends_bonus_action_in_active_encounter(monkeypatch):
    encounter_store = DummyEncounterStore()
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: SimpleNamespace(id="scene-1", campaign_id="camp-1")})())
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: SimpleNamespace(name="Aria")})())
    monkeypatch.setattr(routes, "_action_logs", lambda: DummyActionLogStore())
    monkeypatch.setattr(routes, "_rule_audits", lambda: type("AuditStore", (), {"save": lambda self, entry: None})())

    result = routes.resolve_campaign_check(
        "camp-1",
        routes.ResolveCheckRequest(source="stealth", difficulty=12, action_cost="bonus_action"),
    )
    assert result["success"] in {True, False}
    active = encounter_store.get_active("camp-1", "scene-1")
    assert active.participants[0].bonus_action_available is False
    assert active.participants[0].action_available is True


def test_spent_bonus_action_blocks_second_bonus_action_check(monkeypatch):
    encounter_store = DummyEncounterStore()
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    player_first.participants[0].bonus_action_available = False
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_scenes", lambda: type("SceneStore", (), {"get_active": lambda self, campaign_id: SimpleNamespace(id="scene-1", campaign_id="camp-1")})())
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())
    monkeypatch.setattr(routes, "_pcs", lambda: type("PcStore", (), {"get": lambda self, campaign_id: SimpleNamespace(name="Aria")})())
    monkeypatch.setattr(routes, "_action_logs", lambda: DummyActionLogStore())
    monkeypatch.setattr(routes, "_rule_audits", lambda: type("AuditStore", (), {"save": lambda self, entry: None})())

    with pytest.raises(routes.HTTPException, match="bonus action"):
        routes.resolve_campaign_check(
            "camp-1",
            routes.ResolveCheckRequest(source="stealth", difficulty=12, action_cost="bonus_action"),
        )


def test_spend_encounter_movement_route_updates_remaining_distance(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    result = routes.spend_campaign_encounter_movement(
        "camp-1",
        player_first.id,
        routes.SpendEncounterMovementRequest(distance=15),
    )
    assert result["participant"]["movement_remaining"] == 15
    assert result["encounter"]["current_participant"]["movement_remaining"] == 15
    assert action_logs.saved[0].action_type == "movement"
    assert audits[0]["event_type"] == "movement"


def test_use_encounter_reaction_route_spends_player_reaction(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    result = routes.use_campaign_encounter_reaction(
        "camp-1",
        player_first.id,
        routes.UseEncounterReactionRequest(note="Opportunity attack."),
    )
    assert result["participant"]["reaction_available"] is False
    assert result["encounter"]["participants"][0]["reaction_available"] is False
    assert action_logs.saved[0].action_type == "reaction"
    assert audits[0]["event_type"] == "reaction"


def test_use_compendium_help_applies_helped_condition(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    class DummySheets:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return CharacterSheet(campaign_id="camp-1", name="Aria")
            if owner_type == "npc":
                return CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id=owner_id, name="Guard")
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **updates):
            return CharacterSheet(
                campaign_id=campaign_id,
                owner_type=owner_type,
                owner_id=owner_id,
                name="Aria" if owner_type == "player" else "Guard",
                current_hp=updates.get("current_hp") if updates.get("current_hp") is not None else 10,
                max_hp=updates.get("max_hp") if updates.get("max_hp") is not None else 10,
                conditions=updates.get("conditions", []),
            )

    monkeypatch.setattr(routes, "_sheets", lambda: DummySheets())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(
            slug="help",
            actor_participant_id=encounter.participants[0].id,
            target_participant_ids=[encounter.participants[1].id],
        ),
    )

    assert "helped" in result["targets"][0]["conditions"]
    assert result["targets"][0]["condition_durations"]["helped"] == 1
    assert action_logs.saved[0].action_type == "compendium_action"
    assert audits[0]["event_type"] == "compendium_action"


def test_use_compendium_second_wind_heals_actor(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter.participants[0].current_hp = 4
    encounter.participants[0].max_hp = 12
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    class DummySheets:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return CharacterSheet(campaign_id="camp-1", name="Aria", current_hp=4, max_hp=12)

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **updates):
            return CharacterSheet(
                campaign_id=campaign_id,
                owner_type=owner_type,
                owner_id=owner_id,
                name="Aria",
                current_hp=updates.get("current_hp") if updates.get("current_hp") is not None else 4,
                max_hp=updates.get("max_hp") if updates.get("max_hp") is not None else 12,
                conditions=updates.get("conditions", []),
            )

    monkeypatch.setattr(routes, "_sheets", lambda: DummySheets())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(
            slug="second-wind",
            actor_participant_id=encounter.participants[0].id,
        ),
    )

    assert result["actor"]["current_hp"] > 4
    assert result["healing"]["total"] > 0
    assert result["resources_consumed"] == []
    assert action_logs.saved[0].action_type == "compendium_action"
    assert audits[0]["event_type"] == "compendium_action"


def test_use_compendium_healing_word_heals_target_and_consumes_slot(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="ally-1", name="Companion", team="player", initiative_roll=12, initiative_modifier=1),
        ],
    )
    encounter.participants[1].current_hp = 2
    encounter.participants[1].max_hp = 10
    encounter_store.save(encounter)

    actor_sheet = CharacterSheet(
        campaign_id="camp-1",
        name="Aria",
        resource_pools={"spell_slot_1": {"current": 2, "max": 2}},
        prepared_spells=["healing-word"],
    )
    target_sheet = CharacterSheet(
        campaign_id="camp-1",
        owner_type="npc",
        owner_id="ally-1",
        name="Companion",
        current_hp=2,
        max_hp=10,
    )

    class DummySheets:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return actor_sheet
            if owner_type == "npc" and owner_id == "ally-1":
                return target_sheet
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **updates):
            if owner_type == "player":
                actor_sheet.resource_pools = updates.get("resource_pools", actor_sheet.resource_pools)
                actor_sheet.current_hp = updates.get("current_hp", actor_sheet.current_hp)
                actor_sheet.max_hp = updates.get("max_hp", actor_sheet.max_hp)
                actor_sheet.conditions = updates.get("conditions", actor_sheet.conditions)
                return actor_sheet
            target_sheet.current_hp = updates.get("current_hp", target_sheet.current_hp)
            target_sheet.max_hp = updates.get("max_hp", target_sheet.max_hp)
            target_sheet.conditions = updates.get("conditions", target_sheet.conditions)
            return target_sheet

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: DummySheets())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(
            slug="healing-word",
            actor_participant_id=encounter.participants[0].id,
            target_participant_ids=[encounter.participants[1].id],
        ),
    )

    assert result["targets"][0]["current_hp"] > 2
    assert result["resources_consumed"][0]["resource"] == "spell_slot_1"
    assert result["resources_consumed"][0]["amount"] == 1
    assert result["healing"]["total"] > 0
    assert action_logs.saved[0].action_type == "compendium_action"
    assert audits[0]["event_type"] == "compendium_action"


def test_apply_encounter_condition_route_persists_condition(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    target = player_first.participants[1]
    result = routes.apply_campaign_encounter_condition(
        "camp-1",
        player_first.id,
        routes.ApplyEncounterConditionRequest(participant_id=target.id, condition="poisoned", duration_rounds=2),
    )
    assert "poisoned" in result["participant"]["conditions"]
    assert result["participant"]["condition_durations"]["poisoned"] == 2
    assert action_logs.saved[0].action_type == "condition"
    assert audits[0]["event_type"] == "condition"


def test_stabilize_encounter_participant_route_updates_life_state(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    player_first.participants[1].current_hp = 0
    player_first.participants[1].max_hp = 11
    player_first.participants[1].life_state = "down"
    player_first.participants[1].conditions = ["unconscious"]
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    target = player_first.participants[1]
    result = routes.stabilize_campaign_encounter_participant(
        "camp-1",
        player_first.id,
        routes.StabilizeEncounterParticipantRequest(participant_id=target.id),
    )
    assert result["participant"]["life_state"] == "stable"
    assert "stable" in result["participant"]["conditions"]
    assert action_logs.saved[0].action_type == "stabilize"
    assert audits[0]["event_type"] == "stabilize"


def test_set_encounter_concentration_route_updates_participant(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    player_first = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter_store.save(player_first)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))

    target = player_first.participants[0]
    result = routes.set_campaign_encounter_concentration(
        "camp-1",
        player_first.id,
        routes.SetEncounterConcentrationRequest(participant_id=target.id, active=True, label="Bless"),
    )
    assert result["participant"]["concentration_label"] == "Bless"
    assert action_logs.saved[0].action_type == "concentration"
    assert audits[0]["event_type"] == "concentration"


def test_complete_encounter_clears_pending_concentration_dc(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter.participants[0].pending_concentration_dc = 10
    encounter.participants[0].movement_remaining = 5
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sync_all_encounter_participants_to_sheets", lambda campaign_id, encounter: [{"participant_id": encounter.participants[0].id}])

    result = routes.complete_campaign_encounter(
        "camp-1",
        encounter.id,
        routes.CompleteEncounterRequest(summary="Done."),
    )
    assert result["participants"][0]["pending_concentration_dc"] is None
    assert result["participants"][0]["movement_remaining"] == result["participants"][0]["speed"]
    assert result["sheet_sync"] == [{"participant_id": encounter.participants[0].id}]


def test_complete_encounter_generates_summary_when_missing(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="guard-1", name="Guard", team="enemy", initiative_roll=9, initiative_modifier=1),
        ],
    )
    encounter.round_number = 2
    encounter.participants[1].life_state = "dead"
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sync_all_encounter_participants_to_sheets", lambda campaign_id, encounter: [])

    result = routes.complete_campaign_encounter(
        "camp-1",
        encounter.id,
        routes.CompleteEncounterRequest(summary=""),
    )
    assert result["summary"]
    assert "2 rounds" in result["summary"]
    assert "Guard" in result["summary"]


def test_use_compendium_dash_grants_extra_movement(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria"), "save_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="dash"),
    )
    assert result["actor"]["movement_remaining"] == result["actor"]["speed"] * 2
    assert action_logs.saved[0].action_type == "compendium_action"
    assert audits[0]["event_type"] == "compendium_action"


def test_use_compendium_dodge_applies_dodging_condition(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria"), "save_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria", conditions=["dodging"])})())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="dodge"),
    )
    assert "dodging" in result["actor"]["conditions"]
    assert action_logs.saved[0].source == "dodge"


def test_use_compendium_bless_consumes_resource_and_applies_targets(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="ally-1", name="Lysa", team="player", initiative_roll=12, initiative_modifier=1),
        ],
    )
    encounter_store.save(encounter)

    class SheetStore:
        def __init__(self):
            self.player_sheet = CharacterSheet(campaign_id="camp-1", name="Aria", resource_pools={"spell_slot_1": {"current": 2, "max": 4, "restores_on": "long_rest"}}, prepared_spells=["bless"])
            self.ally_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="ally-1", name="Lysa")

        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return self.player_sheet
            if owner_type == "npc" and owner_id == "ally-1":
                return self.ally_sheet
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            target = self.player_sheet if owner_type == "player" else self.ally_sheet
            for key, value in kwargs.items():
                if value is not None:
                    setattr(target, key, value)
            return target

    sheet_store = SheetStore()

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="bless", target_participant_ids=[encounter.participants[0].id, encounter.participants[1].id]),
    )
    assert result["actor"]["concentration_label"] == "Bless"
    assert len(result["targets"]) == 2
    assert all("blessed" in target["conditions"] for target in result["targets"])
    assert sheet_store.player_sheet.resource_pools["spell_slot_1"]["current"] == 1
    assert action_logs.saved[0].source == "bless"


def test_use_compendium_spell_requires_preparation(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter_store.save(encounter)

    class SheetStore:
        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            return CharacterSheet(
                campaign_id="camp-1",
                name="Aria",
                resource_pools={"spell_slot_1": {"current": 2, "max": 4, "restores_on": "long_rest"}},
                prepared_spells=[],
            )

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            return self.get_for_owner(campaign_id, owner_type, owner_id)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: SheetStore())

    with pytest.raises(routes.HTTPException, match="has not prepared Bless"):
        routes.use_campaign_encounter_compendium_entry(
            "camp-1",
            encounter.id,
            routes.UseEncounterCompendiumEntryRequest(slug="bless"),
        )


def test_use_compendium_healing_wand_consumes_charge_and_heals(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="ally-1", name="Lysa", team="player", initiative_roll=12, initiative_modifier=1),
        ],
    )
    encounter.participants[1].current_hp = 4
    encounter.participants[1].max_hp = 12
    encounter_store.save(encounter)

    class SheetStore:
        def __init__(self):
            self.player_sheet = CharacterSheet(
                campaign_id="camp-1",
                name="Aria",
                equipped_items={"main_hand": "healing-wand"},
                item_charges={"healing-wand": {"current": 2, "max": 3, "restores_on": "long_rest"}},
            )
            self.ally_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="ally-1", name="Lysa", current_hp=4, max_hp=12)

        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return self.player_sheet
            if owner_type == "npc" and owner_id == "ally-1":
                return self.ally_sheet
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            target = self.player_sheet if owner_type == "player" else self.ally_sheet
            for key, value in kwargs.items():
                if value is not None:
                    setattr(target, key, value)
            return target

    sheet_store = SheetStore()

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="healing-wand", target_participant_ids=[encounter.participants[1].id]),
    )

    assert result["targets"][0]["current_hp"] > 4
    assert result["resources_consumed"][-1]["resource"] == "healing-wand_charge"
    assert result["resources_consumed"][-1]["remaining"] == 1
    assert sheet_store.player_sheet.item_charges["healing-wand"]["current"] == 1
    assert action_logs.saved[0].source == "healing-wand"


def test_use_compendium_disengage_applies_condition(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
        ],
    )
    encounter_store.save(encounter)

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: type("SheetStore", (), {"get_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria"), "save_for_owner": lambda self, *args, **kwargs: CharacterSheet(campaign_id="camp-1", name="Aria")})())

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="disengage"),
    )

    assert "disengaging" in result["actor"]["conditions"]
    assert result["actor"]["condition_durations"]["disengaging"] == 1
    assert action_logs.saved[0].source == "disengage"


def test_use_compendium_cure_wounds_heals_target_and_consumes_slot(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="ally-1", name="Lysa", team="player", initiative_roll=12, initiative_modifier=1),
        ],
    )
    encounter.participants[1].current_hp = 5
    encounter.participants[1].max_hp = 14
    encounter_store.save(encounter)

    class SheetStore:
        def __init__(self):
            self.player_sheet = CharacterSheet(
                campaign_id="camp-1",
                name="Aria",
                resource_pools={"spell_slot_1": {"current": 2, "max": 2, "restores_on": "long_rest"}},
                prepared_spells=["cure-wounds"],
            )
            self.ally_sheet = CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id="ally-1", name="Lysa", current_hp=5, max_hp=14)

        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return self.player_sheet
            if owner_type == "npc" and owner_id == "ally-1":
                return self.ally_sheet
            return None

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            target = self.player_sheet if owner_type == "player" else self.ally_sheet
            for key, value in kwargs.items():
                if value is not None:
                    setattr(target, key, value)
            return target

    sheet_store = SheetStore()
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(slug="cure-wounds", target_participant_ids=[encounter.participants[1].id]),
    )

    assert result["targets"][0]["current_hp"] > 5
    assert sheet_store.player_sheet.resource_pools["spell_slot_1"]["current"] == 1
    assert action_logs.saved[0].source == "cure-wounds"


def test_use_compendium_magic_missile_damages_targets_and_consumes_slot(monkeypatch):
    encounter_store = DummyEncounterStore()
    action_logs = DummyActionLogStore()
    audits = []
    encounter = routes.build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Skirmish",
        participants=[
            routes.build_encounter_participant(owner_type="player", owner_id="player", name="Aria", team="player", initiative_roll=18, initiative_modifier=2),
            routes.build_encounter_participant(owner_type="npc", owner_id="enemy-1", name="Goblin One", team="enemy", initiative_roll=12, initiative_modifier=1),
            routes.build_encounter_participant(owner_type="npc", owner_id="enemy-2", name="Goblin Two", team="enemy", initiative_roll=10, initiative_modifier=1),
        ],
    )
    encounter.participants[1].current_hp = 10
    encounter.participants[1].max_hp = 10
    encounter.participants[2].current_hp = 10
    encounter.participants[2].max_hp = 10
    encounter_store.save(encounter)

    class SheetStore:
        def __init__(self):
            self.player_sheet = CharacterSheet(
                campaign_id="camp-1",
                name="Aria",
                resource_pools={"spell_slot_1": {"current": 2, "max": 2, "restores_on": "long_rest"}},
                prepared_spells=["magic-missile"],
            )

        def get_for_owner(self, campaign_id: str, owner_type: str = "player", owner_id: str = "player"):
            if owner_type == "player":
                return self.player_sheet
            return CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id=owner_id, name=owner_id)

        def save_for_owner(self, campaign_id: str, owner_type: str, owner_id: str, **kwargs):
            if owner_type == "player":
                for key, value in kwargs.items():
                    if value is not None:
                        setattr(self.player_sheet, key, value)
                return self.player_sheet
            return CharacterSheet(campaign_id="camp-1", owner_type="npc", owner_id=owner_id, name=owner_id, **kwargs)

    sheet_store = SheetStore()
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: SimpleNamespace(play_mode=PlayMode.RULES, system_pack="d20-fantasy-core"))
    monkeypatch.setattr(routes, "_encounters", lambda: encounter_store)
    monkeypatch.setattr(routes, "_action_logs", lambda: action_logs)
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: audits.append(kwargs))
    monkeypatch.setattr(routes, "_sheets", lambda: sheet_store)

    result = routes.use_campaign_encounter_compendium_entry(
        "camp-1",
        encounter.id,
        routes.UseEncounterCompendiumEntryRequest(
            slug="magic-missile",
            target_participant_ids=[encounter.participants[1].id, encounter.participants[2].id],
        ),
    )

    assert result["damage"]["total"] > 0
    assert len(result["damage"]["missiles"]) == 3
    assert len(result["targets"]) == 2
    assert sheet_store.player_sheet.resource_pools["spell_slot_1"]["current"] == 1
    assert action_logs.saved[0].source == "magic-missile"
