from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.rules.validators import (
    validate_action_cost,
    validate_advantage_state,
    validate_contested_check_inputs,
    validate_dice_expression,
    validate_resource_costs,
)
from app.core.models import CharacterSheet, PlayMode
import app.web.campaign_routes as routes


def test_validate_advantage_state_rejects_unknown_value():
    with pytest.raises(ValueError, match="advantage_state"):
        validate_advantage_state("triple")


def test_validate_action_cost_rejects_unknown_value():
    with pytest.raises(ValueError, match="action_cost"):
        validate_action_cost("reaction")


def test_validate_dice_expression_can_restrict_allowed_sides():
    with pytest.raises(ValueError, match="Dice sides"):
        validate_dice_expression("2d6", allowed_sides={20})


def test_validate_resource_costs_rejects_negative_amount():
    with pytest.raises(ValueError, match="resource_costs"):
        validate_resource_costs({"spell_slot_1": -1})


def test_validate_contested_check_inputs_requires_opponent_reference_or_modifier():
    with pytest.raises(ValueError, match="Contested checks require"):
        validate_contested_check_inputs(
            opponent_owner_type=None,
            opponent_owner_id=None,
            opponent_modifier=None,
        )


def test_resolve_campaign_check_rejects_invalid_advantage_state(monkeypatch):
    class DummyCampaign:
        play_mode = PlayMode.RULES
        system_pack = "d20-fantasy-core"

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(
        routes,
        "_sheets",
        lambda: type("SheetStore", (), {"get_for_owner": lambda self, campaign_id, owner_type="player", owner_id="player": CharacterSheet(campaign_id=campaign_id, name="Aria")})(),
    )

    with pytest.raises(HTTPException) as exc:
        routes.resolve_campaign_check(
            "camp-1",
            routes.ResolveCheckRequest(
                source="stealth",
                difficulty=15,
                advantage_state="super-advantage",
            ),
        )
    assert exc.value.status_code == 400
    assert "advantage_state" in str(exc.value.detail)


def test_resolve_campaign_contested_check_rejects_missing_opponent_info(monkeypatch):
    class DummyCampaign:
        play_mode = PlayMode.RULES
        system_pack = "d20-fantasy-core"

    monkeypatch.setattr(routes, "_require_campaign", lambda campaign_id: DummyCampaign())
    monkeypatch.setattr(
        routes,
        "_sheets",
        lambda: type("SheetStore", (), {"get_for_owner": lambda self, campaign_id, owner_type="player", owner_id="player": CharacterSheet(campaign_id=campaign_id, name="Aria")})(),
    )

    with pytest.raises(HTTPException) as exc:
        routes.resolve_campaign_contested_check(
            "camp-1",
            routes.ResolveContestedCheckRequest(
                actor_source="stealth",
                opponent_source="perception",
            ),
        )
    assert exc.value.status_code == 400
    assert "Contested checks require" in str(exc.value.detail)
