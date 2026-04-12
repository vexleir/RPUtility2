from __future__ import annotations

from app.core.models import EncounterParticipant
from app.encounters.engine import advance_encounter_turn, apply_condition_to_participant, build_encounter


def test_apply_condition_to_participant_tracks_duration():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2),
        ],
    )

    updated, participant = apply_condition_to_participant(
        encounter,
        participant_id=encounter.participants[1].id,
        condition="poisoned",
        duration_rounds=2,
    )
    assert "poisoned" in participant.conditions
    assert participant.condition_durations["poisoned"] == 2
    assert updated.participants[1].condition_durations["poisoned"] == 2


def test_advance_turn_decrements_new_current_participant_condition_duration():
    encounter = build_encounter(
        campaign_id="camp-1",
        scene_id="scene-1",
        name="Bridge Ambush",
        participants=[
            EncounterParticipant(name="Hero", initiative_total=16, initiative_modifier=3),
            EncounterParticipant(name="Goblin", initiative_total=11, initiative_modifier=2, conditions=["poisoned"], condition_durations={"poisoned": 1}),
        ],
    )

    advanced = advance_encounter_turn(encounter)
    assert advanced.current_turn_index == 1
    assert advanced.participants[1].condition_durations == {}
    assert "poisoned" not in advanced.participants[1].conditions
    assert any("no longer poisoned" in entry for entry in advanced.encounter_log)
