from __future__ import annotations

import random
from datetime import UTC, datetime

from app.characters.derivation import derive_sheet_state
from app.core.models import CharacterSheet, Encounter, EncounterParticipant

from .turn_order import sort_initiative_order


def _now() -> datetime:
    return datetime.now(UTC)


def build_encounter_participant(
    *,
    owner_type: str,
    owner_id: str,
    name: str,
    team: str = "enemy",
    sheet: CharacterSheet | None = None,
    initiative_roll: int | None = None,
    initiative_modifier: int | None = None,
    rng: random.Random | None = None,
) -> EncounterParticipant:
    derived_initiative = derive_sheet_state(sheet)["initiative"] if sheet else 0
    modifier = initiative_modifier if initiative_modifier is not None else int(derived_initiative)
    rolled = initiative_roll if initiative_roll is not None else random.randint(1, 20) if rng is None else rng.randint(1, 20)
    total = int(rolled) + int(modifier)
    speed = int(sheet.speed) if sheet else 30
    return EncounterParticipant(
        owner_type=owner_type,
        owner_id=owner_id,
        name=name,
        team=team,
        initiative_modifier=int(modifier),
        initiative_roll=int(rolled),
        initiative_total=int(total),
        armor_class=sheet.armor_class if sheet else None,
        speed=speed,
        current_hp=sheet.current_hp if sheet else None,
        max_hp=sheet.max_hp if sheet else None,
        life_state="active",
        conditions=list(sheet.conditions) if sheet else [],
        condition_durations={},
        concentration_label="",
        pending_concentration_dc=None,
        action_available=True,
        bonus_action_available=True,
        reaction_available=True,
        movement_remaining=speed,
    )


def build_encounter(
    *,
    campaign_id: str,
    scene_id: str | None,
    name: str,
    participants: list[EncounterParticipant],
) -> Encounter:
    ordered = sort_initiative_order(participants)
    encounter = Encounter(
        campaign_id=campaign_id,
        scene_id=scene_id,
        name=name or "Encounter",
        participants=ordered,
        encounter_log=[],
    )
    if ordered:
        encounter.encounter_log.append(
            f"Round 1 begins. {ordered[0].name} acts first."
        )
    return encounter


def advance_encounter_turn(encounter: Encounter, *, note: str = "") -> Encounter:
    if not encounter.participants:
        return encounter
    updated = encounter.model_copy(deep=True)
    previous = updated.participants[updated.current_turn_index]
    next_index = updated.current_turn_index + 1
    if next_index >= len(updated.participants):
        updated.round_number += 1
        next_index = 0
    updated.current_turn_index = next_index
    current = updated.participants[next_index]
    current.action_available = True
    current.bonus_action_available = True
    current.reaction_available = True
    current.movement_remaining = int(current.speed or 0)
    expired_conditions: list[str] = []
    updated_durations: dict[str, int] = {}
    for condition_name, rounds_remaining in (current.condition_durations or {}).items():
        remaining = int(rounds_remaining) - 1
        if remaining > 0:
            updated_durations[str(condition_name)] = remaining
        else:
            expired_conditions.append(str(condition_name))
    if expired_conditions:
        current.conditions = [condition for condition in current.conditions if condition not in expired_conditions]
    current.condition_durations = updated_durations
    updated.participants[next_index] = current
    if note:
        updated.encounter_log.append(note)
    updated.encounter_log.append(
        f"{previous.name}'s turn ends. Round {updated.round_number}, {current.name} is up."
    )
    for condition_name in expired_conditions:
        updated.encounter_log.append(f"{current.name} is no longer {condition_name}.")
    updated.updated_at = _now()
    return updated


def add_encounter_log_entry(encounter: Encounter, text: str) -> Encounter:
    updated = encounter.model_copy(deep=True)
    if text.strip():
        updated.encounter_log.append(text.strip())
    updated.updated_at = _now()
    return updated


def consume_participant_action(
    encounter: Encounter,
    *,
    participant_id: str,
    cost: str = "action",
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        normalized_cost = str(cost or "action").strip().lower()
        if normalized_cost == "action":
            if not participant.action_available:
                raise ValueError(f"{participant.name} has already used their action this turn")
            participant.action_available = False
        elif normalized_cost == "bonus_action":
            if not participant.bonus_action_available:
                raise ValueError(f"{participant.name} has already used their bonus action this turn")
            participant.bonus_action_available = False
        elif normalized_cost == "reaction":
            if not participant.reaction_available:
                raise ValueError(f"{participant.name} has already used their reaction this round")
            participant.reaction_available = False
        elif normalized_cost == "free":
            pass
        else:
            raise ValueError("Unsupported encounter action cost")
        updated.participants[index] = participant
        if note.strip():
            updated.encounter_log.append(note.strip())
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def apply_damage_to_participant(
    encounter: Encounter,
    *,
    participant_id: str,
    damage_total: int,
    damage_type: str = "",
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        current_hp = participant.current_hp if participant.current_hp is not None else 0
        max_hp = participant.max_hp if participant.max_hp is not None else current_hp
        incoming_damage = max(0, int(damage_total))
        participant.current_hp = max(0, int(current_hp) - incoming_damage)
        if participant.concentration_label and incoming_damage > 0:
            participant.pending_concentration_dc = max(10, incoming_damage // 2)
        if participant.current_hp <= 0 and max_hp > 0:
            if incoming_damage >= current_hp + max_hp:
                participant.life_state = "dead"
                participant.is_active = False
                participant.conditions = [condition for condition in participant.conditions if condition not in {"unconscious", "stable"}]
                participant.concentration_label = ""
                participant.pending_concentration_dc = None
            else:
                participant.life_state = "down"
                participant.conditions = [condition for condition in participant.conditions if condition != "stable"]
                if "unconscious" not in participant.conditions:
                    participant.conditions.append("unconscious")
        updated.participants[index] = participant
        damage_label = f"{damage_total} {damage_type}".strip()
        summary = f"{participant.name} takes {damage_label} damage and is now at {participant.current_hp}/{max_hp} HP."
        if participant.pending_concentration_dc:
            summary += f" Concentration check DC {participant.pending_concentration_dc}."
        if participant.life_state == "down":
            summary += f" {participant.name} is down."
        elif participant.life_state == "dead":
            summary += f" {participant.name} dies."
        if note.strip():
            summary = f"{note.strip()} {summary}"
        updated.encounter_log.append(summary)
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def apply_healing_to_participant(
    encounter: Encounter,
    *,
    participant_id: str,
    healing_total: int,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        current_hp = participant.current_hp if participant.current_hp is not None else 0
        max_hp = participant.max_hp if participant.max_hp is not None else current_hp
        participant.current_hp = min(max_hp, int(current_hp) + max(0, int(healing_total)))
        if participant.current_hp > 0 and participant.life_state in {"down", "stable"}:
            participant.life_state = "active"
            participant.is_active = True
            participant.conditions = [condition for condition in participant.conditions if condition not in {"unconscious", "stable"}]
        updated.participants[index] = participant
        summary = f"{participant.name} recovers {healing_total} HP and is now at {participant.current_hp}/{max_hp} HP."
        if note.strip():
            summary = f"{note.strip()} {summary}"
        updated.encounter_log.append(summary)
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def spend_participant_movement(
    encounter: Encounter,
    *,
    participant_id: str,
    distance: int,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    distance_int = int(distance)
    if distance_int < 0:
        raise ValueError("Movement distance must be non-negative")
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        remaining = int(participant.movement_remaining or 0)
        if distance_int > remaining:
            raise ValueError(f"{participant.name} only has {remaining} feet of movement remaining")
        participant.movement_remaining = remaining - distance_int
        updated.participants[index] = participant
        if note.strip():
            updated.encounter_log.append(note.strip())
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def grant_participant_movement(
    encounter: Encounter,
    *,
    participant_id: str,
    distance: int,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    distance_int = int(distance)
    if distance_int < 0:
        raise ValueError("Movement distance must be non-negative")
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        participant.movement_remaining = int(participant.movement_remaining or 0) + distance_int
        updated.participants[index] = participant
        updated.encounter_log.append(note.strip() or f"{participant.name} gains {distance_int} feet of movement.")
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def apply_condition_to_participant(
    encounter: Encounter,
    *,
    participant_id: str,
    condition: str,
    duration_rounds: int | None = None,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    normalized_condition = str(condition or "").strip().lower()
    if not normalized_condition:
        raise ValueError("Condition must not be empty")
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        conditions = list(participant.conditions or [])
        if normalized_condition not in conditions:
            conditions.append(normalized_condition)
        participant.conditions = conditions
        durations = dict(participant.condition_durations or {})
        if duration_rounds is not None:
            rounds = int(duration_rounds)
            if rounds <= 0:
                raise ValueError("duration_rounds must be positive when provided")
            durations[normalized_condition] = rounds
        participant.condition_durations = durations
        updated.participants[index] = participant
        summary = note.strip() or f"{participant.name} gains condition {normalized_condition}."
        updated.encounter_log.append(summary)
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def stabilize_participant(
    encounter: Encounter,
    *,
    participant_id: str,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        if participant.life_state == "dead":
            raise ValueError(f"{participant.name} is dead and cannot be stabilized")
        if (participant.current_hp or 0) > 0:
            raise ValueError(f"{participant.name} is not at 0 HP")
        participant.life_state = "stable"
        if "unconscious" not in participant.conditions:
            participant.conditions.append("unconscious")
        if "stable" not in participant.conditions:
            participant.conditions.append("stable")
        updated.participants[index] = participant
        updated.encounter_log.append(note.strip() or f"{participant.name} is stabilized.")
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def set_participant_concentration(
    encounter: Encounter,
    *,
    participant_id: str,
    label: str = "",
    active: bool = True,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    normalized_label = str(label or "").strip()
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        if active:
            participant.concentration_label = normalized_label or "Concentration"
            participant.pending_concentration_dc = None
        else:
            participant.concentration_label = ""
            participant.pending_concentration_dc = None
        updated.participants[index] = participant
        updated.encounter_log.append(
            note.strip() or (
                f"{participant.name} begins concentrating on {participant.concentration_label}."
                if active else
                f"{participant.name} is no longer concentrating."
            )
        )
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def resolve_participant_concentration_check(
    encounter: Encounter,
    *,
    participant_id: str,
    success: bool,
    note: str = "",
) -> tuple[Encounter, EncounterParticipant]:
    updated = encounter.model_copy(deep=True)
    for index, participant in enumerate(updated.participants):
        if participant.id != participant_id:
            continue
        dc = participant.pending_concentration_dc
        if dc is None:
            raise ValueError(f"{participant.name} has no pending concentration check")
        if success:
            participant.pending_concentration_dc = None
            text = note.strip() or f"{participant.name} maintains concentration."
        else:
            label = participant.concentration_label or "their effect"
            participant.concentration_label = ""
            participant.pending_concentration_dc = None
            text = note.strip() or f"{participant.name} loses concentration on {label}."
        updated.participants[index] = participant
        updated.encounter_log.append(text)
        updated.updated_at = _now()
        return updated, participant
    raise ValueError("Encounter participant not found")


def generate_encounter_summary(encounter: Encounter) -> str:
    participants = encounter.participants or []
    if not participants:
        return f"Encounter ended after {encounter.round_number} rounds."
    survivors = [participant.name for participant in participants if participant.life_state in {"active", "stable"}]
    defeated = [participant.name for participant in participants if participant.life_state == "dead"]
    downed = [participant.name for participant in participants if participant.life_state == "down"]
    fragments = [f"Encounter ended after {encounter.round_number} rounds."]
    if survivors:
        fragments.append(f"Survivors: {', '.join(survivors)}.")
    if downed:
        fragments.append(f"Down but not out: {', '.join(downed)}.")
    if defeated:
        fragments.append(f"Dead: {', '.join(defeated)}.")
    return " ".join(fragments)


def complete_encounter(encounter: Encounter, *, summary: str = "") -> Encounter:
    updated = encounter.model_copy(deep=True)
    updated.status = "completed"
    for index, participant in enumerate(updated.participants):
        participant.action_available = True
        participant.bonus_action_available = True
        participant.reaction_available = True
        participant.movement_remaining = int(participant.speed or 0)
        participant.pending_concentration_dc = None
        updated.participants[index] = participant
    final_summary = summary.strip() or generate_encounter_summary(updated)
    updated.summary = final_summary
    if final_summary:
        updated.encounter_log.append(f"Encounter completed: {final_summary}")
    else:
        updated.encounter_log.append("Encounter completed.")
    updated.updated_at = _now()
    return updated
