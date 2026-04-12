from __future__ import annotations

from app.rules.procedures.gm_flow import (
    GM_DECISION_END,
    GM_DECISION_START,
    build_gm_decision_preview,
    build_gm_procedure_guidance,
    build_gm_procedure_plan,
    build_gm_suggested_actions,
    classify_resolution_kind,
    parse_gm_response_envelope,
)


def test_classify_resolution_kind_detects_attack():
    trigger, resolution, should_consult = classify_resolution_kind("I attack the bandit with my sword.")
    assert trigger == "hostile_action"
    assert resolution == "attack"
    assert should_consult is True


def test_classify_resolution_kind_detects_contested_action():
    trigger, resolution, should_consult = classify_resolution_kind("I try to grapple the guard and force him back.")
    assert trigger == "opposed_action"
    assert resolution == "contested_check"
    assert should_consult is True


def test_build_gm_procedure_plan_defaults_to_freeform_when_no_rule_trigger():
    plan = build_gm_procedure_plan("I sit by the fire and ask about the village.")
    assert plan.trigger_type == "freeform"
    assert plan.resolution_kind == "none"
    assert plan.should_consult_rules is False
    assert "frame_situation" in plan.procedure_steps


def test_build_gm_procedure_guidance_includes_hidden_contract():
    text = build_gm_procedure_guidance("I sneak past the guards.")
    assert "GM PROCEDURE LOOP" in text
    assert "HIDDEN GM CONTRACT" in text
    assert "Suggested resolution kind: check" in text
    assert "Consult rules now: yes" in text
    assert GM_DECISION_START in text
    assert GM_DECISION_END in text


def test_parse_gm_response_envelope_extracts_hidden_contract():
    raw = (
        "The guard glances away and you slip through the gate.\n"
        f"{GM_DECISION_START}\n"
        '{"trigger_type":"uncertain_action","resolution_kind":"check","consult_rules":true,"ask_for_roll":false,"ask_follow_up":false,"follow_up_question":"","player_facing_mode":"narration"}\n'
        f"{GM_DECISION_END}"
    )
    envelope = parse_gm_response_envelope(raw)
    assert "slip through the gate" in envelope.visible_text
    assert envelope.gm_decision is not None
    assert envelope.gm_decision.resolution_kind == "check"


def test_build_gm_decision_preview_marks_attack_as_rules_handoff():
    decision = build_gm_decision_preview("I attack the raider.")
    assert decision.consult_rules is True
    assert decision.ask_for_roll is True
    assert decision.player_facing_mode == "rules_handoff"


def test_build_gm_suggested_actions_for_attack_points_to_attack_endpoint():
    decision = build_gm_decision_preview("I attack the raider.")
    actions = build_gm_suggested_actions(decision)
    assert actions[0].action_type == "attack"
    assert actions[0].endpoint.endswith("/attacks/resolve")


def test_build_gm_suggested_actions_for_bless_uses_compendium_entry():
    decision = build_gm_decision_preview("I cast bless on the party.")
    actions = build_gm_suggested_actions(
        decision,
        user_message="I cast bless on the party.",
        system_pack="d20-fantasy-core",
    )
    assert actions[0].action_type == "compendium_action"
    assert actions[0].payload_template["slug"] == "bless"


def test_build_gm_suggested_actions_for_second_wind_uses_compendium_entry():
    decision = build_gm_decision_preview("I use second wind.")
    actions = build_gm_suggested_actions(
        decision,
        user_message="I use second wind.",
        system_pack="d20-fantasy-core",
    )
    assert actions[0].action_type == "compendium_action"
    assert actions[0].payload_template["slug"] == "second-wind"


def test_build_gm_suggested_actions_for_magic_missile_uses_compendium_entry():
    decision = build_gm_decision_preview("I cast magic missile at the goblin.")
    actions = build_gm_suggested_actions(
        decision,
        user_message="I cast magic missile at the goblin.",
        system_pack="d20-fantasy-core",
    )
    assert actions[0].action_type == "compendium_action"
    assert actions[0].payload_template["slug"] == "magic-missile"


def test_classify_resolution_kind_detects_passive_awareness():
    trigger, resolution, should_consult = classify_resolution_kind("I keep watch for danger while the others sleep.")
    assert trigger == "passive_awareness"
    assert resolution == "passive_check"
    assert should_consult is True


def test_build_gm_decision_preview_infers_passive_sources():
    decision = build_gm_decision_preview("I read the room and keep an eye out for trouble.")
    assert decision.resolution_kind == "passive_check"
    assert "insight" in decision.passive_sources
    assert "perception" in decision.passive_sources
    assert decision.ask_for_roll is False


def test_parse_gm_response_envelope_falls_back_when_contract_is_invalid():
    raw = (
        "You pause and listen for movement in the dark hall.\n"
        f"{GM_DECISION_START}\n"
        '{"trigger_type":"passive_awareness","resolution_kind":"passive_check","consult_rules":tru\n'
        f"{GM_DECISION_END}"
    )
    envelope = parse_gm_response_envelope(raw)
    assert envelope.visible_text.startswith("You pause and listen")
    assert envelope.gm_decision is not None
    assert envelope.gm_decision.resolution_kind == "passive_check"
    assert envelope.contract_parse_error
    assert envelope.used_fallback_preview is True
