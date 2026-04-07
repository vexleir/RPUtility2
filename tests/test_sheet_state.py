from app.core.models import CharacterSheet
from app.rules.sheet_state import apply_sheet_state_change


def test_apply_sheet_state_change_damage_consumes_temp_hp_first():
    sheet = CharacterSheet(campaign_id="c", current_hp=12, max_hp=20, temp_hp=5, conditions=["blessed"])
    updated, summary = apply_sheet_state_change(sheet, damage=7)
    assert updated.temp_hp == 0
    assert updated.current_hp == 10
    assert "took 7 damage" in summary


def test_apply_sheet_state_change_healing_and_conditions():
    sheet = CharacterSheet(campaign_id="c", current_hp=4, max_hp=12, temp_hp=0, conditions=["poisoned"], notes="Old note")
    updated, summary = apply_sheet_state_change(
        sheet,
        healing=5,
        temp_hp_delta=3,
        add_conditions=["blessed"],
        remove_conditions=["poisoned"],
        notes_append="Recovered after the shrine ritual.",
    )
    assert updated.current_hp == 9
    assert updated.temp_hp == 3
    assert updated.conditions == ["blessed"]
    assert "Recovered after the shrine ritual." in updated.notes
    assert "recovered 5 HP" in summary
    assert "removed conditions: poisoned" in summary
