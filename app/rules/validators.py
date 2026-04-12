from __future__ import annotations

from .dice import parse_dice_expression


VALID_ADVANTAGE_STATES = {"normal", "advantage", "disadvantage"}
VALID_ACTION_COSTS = {"action", "bonus_action", "free"}


def validate_advantage_state(value: str) -> str:
    normalized = str(value or "normal").strip().lower()
    if normalized not in VALID_ADVANTAGE_STATES:
        raise ValueError("advantage_state must be one of: normal, advantage, disadvantage")
    return normalized


def validate_dice_expression(value: str, *, allowed_sides: set[int] | None = None) -> str:
    normalized = str(value or "").strip().lower()
    count, sides, _ = parse_dice_expression(normalized)
    if count < 1:
        raise ValueError("Dice count must be at least 1")
    if allowed_sides is not None and sides not in allowed_sides:
        allowed = ", ".join(str(side) for side in sorted(allowed_sides))
        raise ValueError(f"Dice sides must be one of: {allowed}")
    return normalized


def validate_non_negative_int(value: int, field_name: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def validate_positive_int(value: int, field_name: str, *, minimum: int = 1) -> int:
    number = int(value)
    if number < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return number


def validate_resource_costs(resource_costs: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for raw_name, raw_amount in (resource_costs or {}).items():
        name = str(raw_name).strip().lower()
        if not name:
            raise ValueError("resource_costs keys must not be empty")
        amount = int(raw_amount)
        if amount < 0:
            raise ValueError("resource_costs values must be non-negative")
        normalized[name] = amount
    return normalized


def validate_action_cost(value: str | None) -> str:
    normalized = str(value or "action").strip().lower()
    if normalized not in VALID_ACTION_COSTS:
        raise ValueError("action_cost must be one of: action, bonus_action, free")
    return normalized


def validate_contested_check_inputs(
    *,
    opponent_owner_type: str | None,
    opponent_owner_id: str | None,
    opponent_modifier: int | None,
) -> None:
    has_owner_ref = bool(opponent_owner_type and opponent_owner_id)
    has_manual_modifier = opponent_modifier is not None
    if not has_owner_ref and not has_manual_modifier:
        raise ValueError("Contested checks require either an opponent owner reference or opponent_modifier")
    if bool(opponent_owner_type) != bool(opponent_owner_id):
        raise ValueError("opponent_owner_type and opponent_owner_id must be provided together")
