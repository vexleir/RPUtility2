from __future__ import annotations

import random
import shutil
from pathlib import Path

from app.core.config import config
from app.core.models import CharacterSheet
from app.rules.dice import parse_dice_expression
from app.rules.resolution import (
    resolve_contested_d20_check,
    resolve_d20_attack,
    resolve_d20_check,
    resolve_damage_roll,
    resolve_healing_roll,
)
from app.rules.store import RulebookStore
from app.core.models import Rulebook, RuleSection


class FixedRng:
    def __init__(self, values: list[int]):
        self._values = list(values)

    def randint(self, _low: int, _high: int) -> int:
        return self._values.pop(0)


def test_parse_dice_expression_supports_modifier():
    assert parse_dice_expression("2d6+3") == (2, 6, 3)
    assert parse_dice_expression("d20") == (1, 20, 0)
    assert parse_dice_expression("1d8-1") == (1, 8, -1)


def test_character_sheet_resolve_modifier_prefers_skill_then_save_then_ability():
    sheet = CharacterSheet(
        campaign_id="c",
        abilities={"strength": 16, "dexterity": 14, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 8},
        skill_modifiers={"stealth": 5},
        save_modifiers={"dexterity": 4},
    )
    assert sheet.resolve_modifier("stealth") == 5
    assert sheet.resolve_modifier("dexterity") == 4
    assert sheet.resolve_modifier("strength") == 3
    assert sheet.resolve_modifier("charisma") == -1


def test_resolve_d20_check_success_with_advantage():
    sheet = CharacterSheet(
        campaign_id="c",
        abilities={"strength": 10, "dexterity": 16, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
        skill_modifiers={"stealth": 5},
    )
    result = resolve_d20_check(
        sheet=sheet,
        source="stealth",
        difficulty=15,
        advantage_state="advantage",
        rng=random.Random(7),
        reason="Hide in the reeds",
    )
    assert result.advantage_state == "advantage"
    assert len(result.dice_rolls) == 2
    assert result.total >= result.difficulty
    assert result.success is True


def test_resolve_d20_check_failure_with_disadvantage():
    sheet = CharacterSheet(
        campaign_id="c",
        abilities={"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
    )
    result = resolve_d20_check(
        sheet=sheet,
        source="wisdom",
        difficulty=18,
        advantage_state="disadvantage",
        rng=random.Random(11),
        reason="Read the warding script under pressure",
    )
    assert result.advantage_state == "disadvantage"
    assert len(result.dice_rolls) == 2
    assert result.success is False


def test_resolve_d20_attack_critical_hit_beats_target_ac():
    attacker = CharacterSheet(
        campaign_id="c",
        abilities={"strength": 16, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
    )
    result = resolve_d20_attack(
        attacker=attacker,
        source="strength",
        target_armor_class=30,
        rng=FixedRng([20]),
        reason="Heavy swing",
    )
    assert result.attack_roll == 20
    assert result.critical_hit is True
    assert result.hit is True
    assert result.outcome == "critical_hit"


def test_resolve_d20_attack_nat1_is_miss_even_with_high_modifier():
    attacker = CharacterSheet(
        campaign_id="c",
        abilities={"strength": 30, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
    )
    result = resolve_d20_attack(
        attacker=attacker,
        source="strength",
        target_armor_class=5,
        rng=FixedRng([1]),
    )
    assert result.attack_roll == 1
    assert result.hit is False
    assert result.outcome == "miss"


def test_resolve_damage_roll_doubles_dice_on_critical_hit():
    result = resolve_damage_roll(
        roll_expression="1d8+2",
        critical_hit=True,
        damage_type="slashing",
        rng=FixedRng([4, 7]),
    )
    assert result.roll_expression == "2d8+2"
    assert result.dice_rolls == [4, 7]
    assert result.total == 13
    assert result.damage_type == "slashing"


def test_resolve_healing_roll_never_goes_below_zero():
    result = resolve_healing_roll(
        roll_expression="1d4",
        modifier=-10,
        rng=FixedRng([1]),
        source="potion",
    )
    assert result.total == 0
    assert result.source == "potion"


def test_resolve_contested_d20_check_player_wins():
    actor = CharacterSheet(campaign_id="c", skill_modifiers={"stealth": 5})
    opponent = CharacterSheet(campaign_id="c", skill_modifiers={"perception": 2})
    result = resolve_contested_d20_check(
        actor_sheet=actor,
        actor_name="Player",
        actor_source="stealth",
        opponent_sheet=opponent,
        opponent_name="Guard",
        opponent_source="perception",
        rng=FixedRng([14, 9]),
        reason="Slip past the sentry",
    )
    assert result.winner == "actor"
    assert result.margin == 8
    assert result.actor.total == 19
    assert result.opponent.total == 11


def test_resolve_contested_d20_check_supports_opponent_modifier_override_and_tie():
    actor = CharacterSheet(campaign_id="c", abilities={"strength": 12})
    result = resolve_contested_d20_check(
        actor_sheet=actor,
        actor_name="Player",
        actor_source="strength",
        opponent_sheet=None,
        opponent_name="Ogre",
        opponent_source="athletics",
        opponent_modifier=3,
        rng=FixedRng([12, 10]),
    )
    assert result.winner == "tie"
    assert result.margin == 0
    assert result.actor.total == 13
    assert result.opponent.total == 13


def test_rulebook_store_save_and_get():
    base = Path.cwd() / ".tmp" / "rulebook-store-test"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    old_rules_dir = config.rules_dir
    config.rules_dir = str(base)
    try:
        store = RulebookStore()
        rulebook = Rulebook(
            name="Custom Test Rules",
            slug="custom-test-rules",
            description="Test rulebook",
            system_pack="d20-fantasy-core",
            sections=[
                RuleSection(title="Core", content="Roll a d20 for uncertain actions.", priority=10),
            ],
        )
        store.save(rulebook)
        loaded = store.get("custom-test-rules")
        assert loaded is not None
        assert loaded.slug == "custom-test-rules"
        assert loaded.sections[0].title == "Core"
    finally:
        config.rules_dir = old_rules_dir
        shutil.rmtree(base, ignore_errors=True)

