from __future__ import annotations

import random

from app.core.models import CharacterSheet, CheckResolution
from .dice import parse_dice_expression, roll_d20_pair, roll_expression


def resolve_d20_check(
    *,
    sheet: CharacterSheet | None,
    source: str,
    difficulty: int,
    roll_expression: str = "d20",
    advantage_state: str = "normal",
    reason: str = "",
    rng: random.Random | None = None,
) -> CheckResolution:
    """
    Resolve a d20-style check deterministically from a sheet and source key.
    `source` can be an ability, skill, or save key already present on the sheet.
    """
    expr = roll_expression.strip().lower()
    modifier = sheet.resolve_modifier(source) if sheet else 0

    if expr == "d20" and advantage_state in {"advantage", "disadvantage"}:
        a, b = roll_d20_pair(rng=rng)
        chosen = max(a, b) if advantage_state == "advantage" else min(a, b)
        total = chosen + modifier
        success = total >= difficulty
        if chosen == 20:
            outcome = "critical_success"
        elif chosen == 1:
            outcome = "critical_failure"
        else:
            outcome = "success" if success else "failure"
        return CheckResolution(
            roll_expression=expr,
            dice_total=chosen,
            dice_rolls=[a, b],
            modifier=modifier,
            total=total,
            difficulty=difficulty,
            success=success,
            outcome=outcome,
            advantage_state=advantage_state,
            reason=reason,
            source=source,
        )

    rolls, dice_total = roll_expression_result(expr, rng=rng)
    total = dice_total + modifier
    count, sides, _ = parse_dice_expression(expr)
    success = total >= difficulty
    if count == 1 and sides == 20 and rolls[0] == 20:
        outcome = "critical_success"
    elif count == 1 and sides == 20 and rolls[0] == 1:
        outcome = "critical_failure"
    else:
        outcome = "success" if success else "failure"
    return CheckResolution(
        roll_expression=expr,
        dice_total=dice_total,
        dice_rolls=rolls,
        modifier=modifier,
        total=total,
        difficulty=difficulty,
        success=success,
        outcome=outcome,
        advantage_state="normal",
        reason=reason,
        source=source,
    )


def roll_expression_result(expr: str, *, rng: random.Random | None = None) -> tuple[list[int], int]:
    return roll_expression(expr, rng=rng)

