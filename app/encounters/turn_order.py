from __future__ import annotations

from app.core.models import EncounterParticipant


def sort_initiative_order(participants: list[EncounterParticipant]) -> list[EncounterParticipant]:
    return sorted(
        participants,
        key=lambda p: (
            -int(p.initiative_total),
            -int(p.initiative_modifier),
            p.name.lower(),
            p.id,
        ),
    )
