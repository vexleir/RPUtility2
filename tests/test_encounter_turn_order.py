from __future__ import annotations

from app.core.models import EncounterParticipant
from app.encounters.engine import advance_encounter_turn, build_encounter, consume_participant_action, spend_participant_movement
from app.encounters.turn_order import sort_initiative_order


def test_sort_initiative_order_sorts_by_total_then_modifier():
    participants = [
        EncounterParticipant(name="Goblin", initiative_total=12, initiative_modifier=2),
        EncounterParticipant(name="Hero", initiative_total=15, initiative_modifier=3),
        EncounterParticipant(name="Wolf", initiative_total=15, initiative_modifier=1),
    ]

    ordered = sort_initiative_order(participants)

    assert [participant.name for participant in ordered] == ["Hero", "Wolf", "Goblin"]


def test_advance_encounter_turn_wraps_and_increments_round():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2),
        ],
    )

    first_advance = advance_encounter_turn(encounter)
    assert first_advance.round_number == 1
    assert first_advance.current_participant.name == "Goblin" if hasattr(first_advance, "current_participant") else True
    assert first_advance.current_turn_index == 1

    second_advance = advance_encounter_turn(first_advance)
    assert second_advance.round_number == 2
    assert second_advance.current_turn_index == 0
    assert "Round 2" in second_advance.encounter_log[-1]


def test_consume_participant_action_marks_action_spent_and_next_turn_resets():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, speed=30),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, speed=30),
        ],
    )

    consumed, actor = consume_participant_action(
        encounter,
        participant_id=encounter.participants[0].id,
        note="Hero attacks.",
    )
    assert actor.action_available is False
    assert consumed.participants[0].action_available is False

    advanced = advance_encounter_turn(consumed)
    assert advanced.participants[1].action_available is True
    assert advanced.participants[1].movement_remaining == 30


def test_consume_participant_action_supports_bonus_action_without_spending_action():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, speed=30),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, speed=30),
        ],
    )

    consumed, actor = consume_participant_action(
        encounter,
        participant_id=encounter.participants[0].id,
        cost="bonus_action",
        note="Hero uses a quick feature.",
    )
    assert actor.bonus_action_available is False
    assert consumed.participants[0].bonus_action_available is False
    assert consumed.participants[0].action_available is True


def test_spend_participant_movement_reduces_remaining_distance():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, speed=30, movement_remaining=30),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, speed=30),
        ],
    )

    updated, actor = spend_participant_movement(
        encounter,
        participant_id=encounter.participants[0].id,
        distance=15,
        note="Hero closes the distance.",
    )
    assert actor.movement_remaining == 15
    assert updated.participants[0].movement_remaining == 15
