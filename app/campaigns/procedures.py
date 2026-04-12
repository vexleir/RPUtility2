from __future__ import annotations

from app.core.models import CampaignEvent, CampaignQuest, QuestStatus


_FACTION_STANDINGS = ["hostile", "wary", "neutral", "friendly", "allied"]
_TRAVEL_EVENT_TABLE = [
    {
        "event_type": "travel_hazard",
        "title": "Roadside Ambush Signs",
        "content": "Fresh tracks, broken brush, and a stripped wagon suggest danger on the road ahead.",
        "details": {"hook_type": "encounter", "encounter_theme": "ambush", "enemy_count": 2},
    },
    {
        "event_type": "travel_discovery",
        "title": "Unmarked Shrine",
        "content": "A weathered shrine or landmark offers lore, shelter, or a difficult choice before the journey continues.",
        "details": {"hook_type": "discovery"},
    },
    {
        "event_type": "travel_complication",
        "title": "Supply Trouble",
        "content": "Bad ground, weather, or lost provisions turn the route into a logistical problem that needs attention.",
        "details": {"hook_type": "resource_pressure"},
    },
    {
        "event_type": "travel_opportunity",
        "title": "Helpful Travelers",
        "content": "A caravan, ranger, or guide crosses paths with the party and may change what happens next.",
        "details": {"hook_type": "social"},
    },
]
_DOWNTIME_ACTIVITIES = {"work", "training", "research", "carouse", "craft"}
_TRAINABLE_SKILLS = {
    "athletics", "acrobatics", "sleight_of_hand", "stealth",
    "arcana", "history", "investigation", "nature", "religion",
    "animal_handling", "insight", "medicine", "perception", "survival",
    "deception", "intimidation", "performance", "persuasion",
}
_TRAINABLE_RESOURCE_POOLS = {"spell_slot_1", "superiority", "ki", "luck"}


def world_time_snapshot(total_hours: int) -> dict:
    hours = max(0, int(total_hours or 0))
    day = (hours // 24) + 1
    hour = hours % 24
    return {
        "total_hours": hours,
        "day": day,
        "hour": hour,
        "label": f"Day {day}, {hour:02d}:00",
    }


def shift_faction_standing(current: str, delta: int) -> str:
    normalized = str(current or "").strip().lower() or "neutral"
    if normalized not in _FACTION_STANDINGS:
        normalized = "neutral"
    index = _FACTION_STANDINGS.index(normalized)
    next_index = max(0, min(len(_FACTION_STANDINGS) - 1, index + int(delta or 0)))
    return _FACTION_STANDINGS[next_index]


def advance_campaign_quest(
    quest: CampaignQuest,
    *,
    stage_id: str | None = None,
    status: str | None = None,
) -> CampaignQuest:
    updated = quest.model_copy(deep=True)

    if stage_id:
        for stage in updated.stages:
            if stage.id == stage_id:
                stage.completed = True
                break
        else:
            raise ValueError(f"Quest stage not found: {stage_id}")

    if status:
        updated.status = QuestStatus(status)

    if updated.status == QuestStatus.ACTIVE and updated.stages and all(stage.completed for stage in updated.stages):
        updated.status = QuestStatus.COMPLETED

    return updated


def generate_travel_event(*, campaign_id: str, world_time_hours: int, destination: str = "") -> CampaignEvent:
    basis = sum(ord(ch) for ch in f"{destination}|{world_time_hours}")
    entry = _TRAVEL_EVENT_TABLE[basis % len(_TRAVEL_EVENT_TABLE)]
    suffix = f" Destination: {destination}." if destination else ""
    details = dict(entry.get("details", {}))
    if destination:
        details["destination"] = destination
    return CampaignEvent(
        campaign_id=campaign_id,
        event_type=entry["event_type"],
        title=entry["title"],
        content=f"{entry['content']}{suffix}",
        details=details,
        world_time_hours=max(0, int(world_time_hours or 0)),
    )


def build_campaign_events(
    *,
    campaign_id: str,
    start_hours: int,
    end_hours: int,
    procedure_type: str,
    destination: str = "",
) -> list[CampaignEvent]:
    events: list[CampaignEvent] = []
    hours_elapsed = max(0, int(end_hours or 0) - int(start_hours or 0))
    if procedure_type == "travel" and hours_elapsed >= 4:
        events.append(generate_travel_event(
            campaign_id=campaign_id,
            world_time_hours=end_hours,
            destination=destination,
        ))
    if (start_hours // 24) != (end_hours // 24):
        events.append(CampaignEvent(
            campaign_id=campaign_id,
            event_type="time_pressure",
            title="A New Day Begins",
            content="A new in-world day has begun, and unresolved threads may now evolve.",
            details={"hook_type": "time_pressure"},
            world_time_hours=end_hours,
        ))
    return events


def generate_treasure_bundle(
    *,
    challenge_rating: int,
    source_type: str = "loot",
    source_name: str = "",
) -> dict:
    cr = max(0, int(challenge_rating or 0))
    basis = max(1, cr + len(str(source_name or "")) + len(str(source_type or "")))
    gp = basis * 3
    sp = basis * 2 if cr < 5 else basis
    cp = basis * 5 if cr <= 2 else 0
    item_suggestions: list[str] = []
    if cr >= 3:
        item_suggestions.append("healing-wand")
    elif cr >= 1:
        item_suggestions.append("shield")
    return {
        "currencies": {
            "cp": cp,
            "sp": sp,
            "gp": gp,
        },
        "item_suggestions": item_suggestions,
        "summary": f"Generated treasure for {source_type}: {gp} gp, {sp} sp, {cp} cp.",
    }


def build_downtime_activity_result(
    *,
    campaign_id: str,
    activity_type: str,
    days: int,
    world_time_hours: int,
    subject: str = "",
) -> dict:
    activity = str(activity_type or "work").strip().lower()
    if activity not in _DOWNTIME_ACTIVITIES:
        raise ValueError(f"Unsupported downtime activity: {activity}")

    total_days = max(1, int(days or 1))
    normalized_subject = str(subject or "").strip()
    basis = sum(ord(ch) for ch in f"{campaign_id}|{activity}|{normalized_subject}|{world_time_hours}|{total_days}")
    snapshot = world_time_snapshot(world_time_hours)
    result = {
        "activity_type": activity,
        "days": total_days,
        "subject": normalized_subject,
        "currency_delta": {},
        "faction_delta": 0,
        "events": [],
        "objective_note": "",
        "quest_note": "",
        "skill_increases": {},
        "resource_pool_increases": {},
        "crafted_item": None,
        "summary": "",
    }

    if activity == "work":
        gp = max(1, (total_days * 2) + (basis % 3))
        sp = total_days + (basis % 2)
        result["currency_delta"] = {"gp": gp, "sp": sp}
        result["summary"] = f"Worked for {total_days} day(s) and earned {gp} gp, {sp} sp."
        return result

    if activity == "training":
        focus = normalized_subject or "general practice"
        result["objective_note"] = f"Training on {focus} continued through {snapshot['label']} for {total_days} day(s)."
        result["quest_note"] = f"Training progress recorded for {focus} during downtime."
        normalized_focus = focus.strip().lower().replace(" ", "_").replace("-", "_")
        if total_days >= 3 and normalized_focus in _TRAINABLE_SKILLS:
            result["skill_increases"] = {normalized_focus: 1}
            result["summary"] = f"Spent {total_days} day(s) training in {focus} and improved that skill."
        elif total_days >= 3 and normalized_focus in _TRAINABLE_RESOURCE_POOLS:
            result["resource_pool_increases"] = {normalized_focus: 1}
            result["summary"] = f"Spent {total_days} day(s) training {focus} and expanded that resource pool."
        else:
            result["summary"] = f"Spent {total_days} day(s) training in {focus}."
        return result

    if activity == "research":
        topic = normalized_subject or "an unresolved mystery"
        result["quest_note"] = f"Research during downtime uncovered a lead about {topic}."
        result["events"] = [
            CampaignEvent(
                campaign_id=campaign_id,
                event_type="downtime_discovery",
                title=f"Research Lead: {topic.title()}",
                content=f"Downtime research produced a fresh lead involving {topic}.",
                details={"hook_type": "discovery", "subject": topic, "activity_type": activity},
                world_time_hours=world_time_hours,
            )
        ]
        result["summary"] = f"Spent {total_days} day(s) researching {topic}."
        return result

    if activity == "craft":
        target_slug = normalized_subject.strip().lower().replace(" ", "-")
        craft_cost_gp = max(1, total_days + (basis % 3))
        result["currency_delta"] = {"gp": -craft_cost_gp}
        result["crafted_item"] = {
            "slug": target_slug,
            "days": total_days,
            "cost_gp": craft_cost_gp,
        }
        result["summary"] = f"Spent {total_days} day(s) crafting {target_slug or 'an item'} for {craft_cost_gp} gp in materials."
        return result

    contact = normalized_subject or "local contacts"
    result["faction_delta"] = 1 if total_days >= 2 or (basis % 2 == 0) else 0
    result["events"] = [
        CampaignEvent(
            campaign_id=campaign_id,
            event_type="downtime_social",
            title="Rumors from Carousing",
            content=f"Downtime socializing with {contact} stirred up fresh rumors, favors, or obligations.",
            details={"hook_type": "social", "subject": contact, "activity_type": activity},
            world_time_hours=world_time_hours,
        )
    ]
    if result["faction_delta"] > 0:
        result["summary"] = f"Spent {total_days} day(s) carousing with {contact} and improved a faction relationship."
    else:
        result["summary"] = f"Spent {total_days} day(s) carousing with {contact} and gathered useful social rumors."
    return result


def mature_campaign_event(
    event: CampaignEvent,
    *,
    end_hours: int,
) -> CampaignEvent | None:
    if str(getattr(event, "status", "")).split(".")[-1].lower() != "pending":
        return None

    details = dict(event.details or {})
    escalation_hours = max(1, int(details.get("escalation_hours", 12) or 12))
    last_escalated_at = int(details.get("last_escalated_at_hours", int(event.world_time_hours or 0)) or int(event.world_time_hours or 0))
    if int(end_hours or 0) - last_escalated_at < escalation_hours:
        return None

    updated = event.model_copy(deep=True)
    updated_details = dict(updated.details or {})
    previous_level = int(updated_details.get("escalation_level", 0) or 0)
    next_level = previous_level + 1
    hook_type = str(updated_details.get("hook_type", "") or "").strip().lower()
    updated_details["escalation_level"] = next_level
    updated_details["last_escalated_at_hours"] = int(end_hours or 0)
    updated.details = updated_details
    updated.world_time_hours = int(end_hours or 0)

    if hook_type == "encounter":
        updated.title = f"{event.title} (Escalated)"
        updated.content = f"{event.content} The threat has grown more immediate."
        updated.details["enemy_count"] = max(1, int(updated.details.get("enemy_count", 1) or 1) + 1)
    elif hook_type == "time_pressure":
        updated.content = f"{event.content} The cost of delay is becoming harder to ignore."
    else:
        updated.content = f"{event.content} The situation has intensified over time."

    return updated
