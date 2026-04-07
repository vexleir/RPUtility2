from __future__ import annotations

import random
import re


def parse_dice_expression(expr: str) -> tuple[int, int, int]:
    """
    Parse dice expressions like d20, 2d6+3, 1d8-1.
    Returns (count, sides, modifier).
    """
    value = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", value)
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    if count < 1 or sides < 2:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    return count, sides, mod


def roll_expression(expr: str, *, rng: random.Random | None = None) -> tuple[list[int], int]:
    count, sides, mod = parse_dice_expression(expr)
    roller = rng or random
    rolls = [roller.randint(1, sides) for _ in range(count)]
    return rolls, sum(rolls) + mod


def roll_d20_pair(*, rng: random.Random | None = None) -> tuple[int, int]:
    roller = rng or random
    return roller.randint(1, 20), roller.randint(1, 20)

