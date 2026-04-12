from __future__ import annotations

from types import SimpleNamespace

import app.web.campaign_routes as routes


def test_record_gm_envelope_audits_records_parse_error_and_fallback(monkeypatch):
    recorded = []
    monkeypatch.setattr(routes, "_record_rule_audit", lambda **kwargs: recorded.append(kwargs))

    envelope = SimpleNamespace(
        raw_contract='{"consult_rules":tru}',
        visible_text="You keep watch through the rain.",
        contract_parse_error="Expecting value",
        used_fallback_preview=True,
        gm_decision=SimpleNamespace(
            resolution_kind="passive_check",
            model_dump=lambda: {
                "trigger_type": "passive_awareness",
                "resolution_kind": "passive_check",
                "consult_rules": True,
                "ask_for_roll": False,
                "ask_follow_up": False,
                "follow_up_question": "",
                "passive_sources": ["perception"],
                "player_facing_mode": "rules_handoff",
            },
        ),
    )

    routes._record_gm_envelope_audits(
        campaign_id="camp-1",
        scene_id="scene-1",
        reason="I keep watch.",
        envelope=envelope,
    )

    assert recorded[0]["event_type"] == "gm_decision_error"
    assert recorded[0]["payload"]["used_fallback_preview"] is True
    assert recorded[1]["event_type"] == "gm_decision"
    assert recorded[1]["payload"]["_fallback_preview"] is True
