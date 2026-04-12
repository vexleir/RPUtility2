from __future__ import annotations

import random

from app.core.models import (
    AttackResolution,
    CharacterSheet,
    CheckResolution,
    ContestedCheckParticipant,
    ContestedCheckResolution,
    DamageResolution,
    HealingResolution,
)
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


def resolve_d20_attack(
    *,
    attacker: CharacterSheet | None,
    source: str,
    target_armor_class: int,
    roll_expression: str = "d20",
    advantage_state: str = "normal",
    reason: str = "",
    rng: random.Random | None = None,
) -> AttackResolution:
    expr = roll_expression.strip().lower()
    modifier = attacker.resolve_modifier(source) if attacker else 0

    if expr == "d20" and advantage_state in {"advantage", "disadvantage"}:
        a, b = roll_d20_pair(rng=rng)
        chosen = max(a, b) if advantage_state == "advantage" else min(a, b)
        total = chosen + modifier
        critical_hit = chosen == 20
        automatic_miss = chosen == 1
        hit = critical_hit or (not automatic_miss and total >= target_armor_class)
        outcome = "critical_hit" if critical_hit else ("hit" if hit else "miss")
        return AttackResolution(
            roll_expression=expr,
            attack_roll=chosen,
            dice_rolls=[a, b],
            modifier=modifier,
            total=total,
            target_armor_class=target_armor_class,
            hit=hit,
            critical_hit=critical_hit,
            outcome=outcome,
            advantage_state=advantage_state,
            reason=reason,
            source=source,
        )

    rolls, dice_total = roll_expression_result(expr, rng=rng)
    total = dice_total + modifier
    count, sides, _ = parse_dice_expression(expr)
    critical_hit = count == 1 and sides == 20 and rolls[0] == 20
    automatic_miss = count == 1 and sides == 20 and rolls[0] == 1
    hit = critical_hit or (not automatic_miss and total >= target_armor_class)
    outcome = "critical_hit" if critical_hit else ("hit" if hit else "miss")
    return AttackResolution(
        roll_expression=expr,
        attack_roll=dice_total,
        dice_rolls=rolls,
        modifier=modifier,
        total=total,
        target_armor_class=target_armor_class,
        hit=hit,
        critical_hit=critical_hit,
        outcome=outcome,
        advantage_state="normal",
        reason=reason,
        source=source,
    )


def resolve_damage_roll(
    *,
    roll_expression: str,
    modifier: int = 0,
    critical_hit: bool = False,
    damage_type: str = "",
    reason: str = "",
    source: str = "",
    rng: random.Random | None = None,
) -> DamageResolution:
    expr = _critical_damage_expression(roll_expression) if critical_hit else roll_expression.strip().lower()
    rolls, dice_total = roll_expression_result(expr, rng=rng)
    total = max(0, dice_total + modifier)
    return DamageResolution(
        roll_expression=expr,
        damage_type=damage_type,
        dice_total=dice_total,
        dice_rolls=rolls,
        modifier=modifier,
        total=total,
        critical_hit=critical_hit,
        reason=reason,
        source=source,
    )


def resolve_healing_roll(
    *,
    roll_expression: str,
    modifier: int = 0,
    reason: str = "",
    source: str = "",
    rng: random.Random | None = None,
) -> HealingResolution:
    expr = roll_expression.strip().lower()
    rolls, dice_total = roll_expression_result(expr, rng=rng)
    total = max(0, dice_total + modifier)
    return HealingResolution(
        roll_expression=expr,
        dice_total=dice_total,
        dice_rolls=rolls,
        modifier=modifier,
        total=total,
        reason=reason,
        source=source,
    )


def _critical_damage_expression(expr: str) -> str:
    count, sides, modifier = parse_dice_expression(expr)
    doubled = count * 2
    if modifier > 0:
        return f"{doubled}d{sides}+{modifier}"
    if modifier < 0:
        return f"{doubled}d{sides}{modifier}"
    return f"{doubled}d{sides}"


def resolve_contested_d20_check(
    *,
    actor_sheet: CharacterSheet | None,
    actor_name: str,
    actor_source: str,
    opponent_sheet: CharacterSheet | None,
    opponent_name: str,
    opponent_source: str,
    opponent_modifier: int | None = None,
    roll_expression: str = "d20",
    actor_advantage_state: str = "normal",
    opponent_advantage_state: str = "normal",
    reason: str = "",
    rng: random.Random | None = None,
) -> ContestedCheckResolution:
    actor = _resolve_contested_participant(
        sheet=actor_sheet,
        name=actor_name,
        source=actor_source,
        modifier_override=None,
        roll_expression=roll_expression,
        advantage_state=actor_advantage_state,
        reason=reason,
        rng=rng,
    )
    opponent = _resolve_contested_participant(
        sheet=opponent_sheet,
        name=opponent_name,
        source=opponent_source,
        modifier_override=opponent_modifier,
        roll_expression=roll_expression,
        advantage_state=opponent_advantage_state,
        reason=reason,
        rng=rng,
    )
    if actor.total > opponent.total:
        winner = "actor"
    elif opponent.total > actor.total:
        winner = "opponent"
    else:
        winner = "tie"
    return ContestedCheckResolution(
        actor=actor,
        opponent=opponent,
        winner=winner,
        margin=abs(actor.total - opponent.total),
        reason=reason,
    )


def _resolve_contested_participant(
    *,
    sheet: CharacterSheet | None,
    name: str,
    source: str,
    modifier_override: int | None,
    roll_expression: str,
    advantage_state: str,
    reason: str,
    rng: random.Random | None,
) -> ContestedCheckParticipant:
    expr = roll_expression.strip().lower()
    modifier = int(modifier_override) if modifier_override is not None else (sheet.resolve_modifier(source) if sheet else 0)

    if expr == "d20" and advantage_state in {"advantage", "disadvantage"}:
        a, b = roll_d20_pair(rng=rng)
        chosen = max(a, b) if advantage_state == "advantage" else min(a, b)
        return ContestedCheckParticipant(
            name=name,
            source=source,
            roll_expression=expr,
            dice_total=chosen,
            dice_rolls=[a, b],
            modifier=modifier,
            total=chosen + modifier,
            advantage_state=advantage_state,
            reason=reason,
        )

    rolls, dice_total = roll_expression_result(expr, rng=rng)
    return ContestedCheckParticipant(
        name=name,
        source=source,
        roll_expression=expr,
        dice_total=dice_total,
        dice_rolls=rolls,
        modifier=modifier,
        total=dice_total + modifier,
        advantage_state="normal",
        reason=reason,
    )

