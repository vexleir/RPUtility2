from __future__ import annotations

import pytest

from app.core.models import EncounterParticipant
from app.encounters.engine import apply_damage_to_participant, build_encounter, consume_participant_action, generate_encounter_summary, resolve_participant_concentration_check, set_participant_concentration, stabilize_participant


def test_consume_participant_action_supports_reaction_cost():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, speed=30),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, speed=30),
        ],
    )

    updated, actor = consume_participant_action(
        encounter,
        participant_id=encounter.participants[0].id,
        cost="reaction",
        note="Hero lashes out with an opportunity attack.",
    )
    assert actor.reaction_available is False
    assert updated.participants[0].reaction_available is False
    assert updated.participants[0].action_available is True


def test_consume_participant_action_blocks_second_reaction():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, speed=30, reaction_available=False),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, speed=30),
        ],
    )

    with pytest.raises(ValueError, match="reaction"):
        consume_participant_action(
            encounter,
            participant_id=encounter.participants[0].id,
            cost="reaction",
        )


def test_apply_damage_to_participant_marks_downed_at_zero_hp():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, current_hp=8, max_hp=8),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, current_hp=6, max_hp=6),
        ],
    )

    updated, participant = apply_damage_to_participant(
        encounter,
        participant_id=encounter.participants[1].id,
        damage_total=6,
    )
    assert participant.current_hp == 0
    assert participant.life_state == "down"
    assert "unconscious" in participant.conditions
    assert updated.participants[1].life_state == "down"


def test_stabilize_participant_marks_target_stable():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, current_hp=8, max_hp=8),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, current_hp=0, max_hp=6, life_state="down", conditions=["unconscious"]),
        ],
    )

    updated, participant = stabilize_participant(
        encounter,
        participant_id=encounter.participants[1].id,
    )
    assert participant.life_state == "stable"
    assert "stable" in participant.conditions
    assert updated.participants[1].life_state == "stable"


def test_damage_to_concentrating_participant_sets_pending_concentration_dc():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, current_hp=8, max_hp=8, concentration_label="Bless"),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, current_hp=6, max_hp=6),
        ],
    )

    updated, participant = apply_damage_to_participant(
        encounter,
        participant_id=encounter.participants[0].id,
        damage_total=7,
    )
    assert participant.pending_concentration_dc == 10
    assert updated.participants[0].pending_concentration_dc == 10


def test_resolve_failed_concentration_check_clears_concentration():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, concentration_label="Bless", pending_concentration_dc=10),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2),
        ],
    )

    updated, participant = resolve_participant_concentration_check(
        encounter,
        participant_id=encounter.participants[0].id,
        success=False,
    )
    assert participant.concentration_label == ""
    assert participant.pending_concentration_dc is None
    assert updated.participants[0].concentration_label == ""


def test_generate_encounter_summary_mentions_survivors_and_dead():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3, life_state="active"),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, life_state="dead"),
            EncounterParticipant(name="Cleric", initiative_total=12, initiative_modifier=1, life_state="stable"),
        ],
    )
    encounter.round_number = 3

    summary = generate_encounter_summary(encounter)

    assert "3 rounds" in summary
    assert "Hero" in summary
    assert "Cleric" in summary
    assert "Goblin" in summary
