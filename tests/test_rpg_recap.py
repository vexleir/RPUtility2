from __future__ import annotations

from datetime import datetime

import app.web.campaign_routes as routes
from app.core.models import ActionLogEntry, CampaignEvent, ChronicleEntry


def test_build_campaign_recap_items_merges_multiple_sources():
    chronicle_entries = [
        ChronicleEntry(campaign_id="camp-1", scene_range_start=1, scene_range_end=1, content="The player reached the ruined gate.")
    ]
    action_logs = [
        ActionLogEntry(
            campaign_id="camp-1",
            action_type="treasure",
            source="quest",
            summary="Quest reward paid out.",
            details={"world_time": {"label": "Day 2, 03:00"}},
            created_at=datetime(2026, 4, 10, 3, 0, 0),
        )
    ]
    events = [
        CampaignEvent(
            campaign_id="camp-1",
            event_type="travel_hazard",
            title="Roadside Ambush Signs",
            content="Trouble waits on the north road.",
            world_time_hours=27,
            created_at=datetime(2026, 4, 10, 2, 0, 0),
            updated_at=datetime(2026, 4, 10, 2, 0, 0),
        )
    ]

    items = routes._build_campaign_recap_items(
        chronicle_entries=chronicle_entries,
        action_logs=action_logs,
        events=events,
        limit=10,
    )

    assert len(items) == 3
    assert {item["kind"] for item in items} == {"chronicle", "event", "mechanic"}
    event_item = next(item for item in items if item["kind"] == "event")
    assert event_item["escalation_level"] == 0


def test_build_campaign_recap_items_can_filter_by_kind():
    items = routes._build_campaign_recap_items(
        chronicle_entries=[
            ChronicleEntry(campaign_id="camp-1", scene_range_start=1, scene_range_end=1, content="Chronicle item")
        ],
        action_logs=[
            ActionLogEntry(campaign_id="camp-1", action_type="treasure", source="quest", summary="Mechanical item")
        ],
        events=[
            CampaignEvent(
                campaign_id="camp-1",
                event_type="travel_hazard",
                title="Escalated Trouble",
                content="Event item",
                details={"escalation_level": 2, "hook_type": "encounter"},
                world_time_hours=30,
            )
        ],
        limit=10,
        kind="event",
    )

    assert len(items) == 1
    assert items[0]["kind"] == "event"
    assert items[0]["escalation_level"] == 2
    assert items[0]["hook_type"] == "encounter"


def test_get_campaign_recap_returns_items_and_summary(monkeypatch):
    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: object())
    monkeypatch.setattr(routes, "_chronicle", lambda: type("ChronStore", (), {
        "get_all": lambda self, campaign_id: [
            ChronicleEntry(campaign_id=campaign_id, scene_range_start=1, scene_range_end=1, content="The party entered the mines.")
        ]
    })())
    monkeypatch.setattr(routes, "_action_logs", lambda: type("ActionStore", (), {
        "get_recent": lambda self, campaign_id, n=24: [
            ActionLogEntry(campaign_id=campaign_id, action_type="campaign_procedure", source="travel", summary="Advanced 6 hour(s) via travel.")
        ]
    })())
    monkeypatch.setattr(routes, "_events", lambda: type("EventStore", (), {
        "get_all": lambda self, campaign_id: [
            CampaignEvent(campaign_id=campaign_id, event_type="time_pressure", title="A New Day Begins", content="A new day dawns.", world_time_hours=24)
        ]
    })())

    result = routes.get_campaign_recap("camp-1", limit=6)

    assert len(result["items"]) == 3
    assert result["summary"]
