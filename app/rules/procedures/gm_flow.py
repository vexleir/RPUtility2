from __future__ import annotations

import json

from pydantic import BaseModel, Field
from app.compendium.store import CompendiumStore


GM_DECISION_START = "<<GM_DECISION>>"
GM_DECISION_END = "<</GM_DECISION>>"


class GMProcedurePlan(BaseModel):
    trigger_type: str = "none"
    resolution_kind: str = "none"
    should_consult_rules: bool = False
    hidden_gm_notes: list[str] = Field(default_factory=list)
    procedure_steps: list[str] = Field(default_factory=lambda: [
        "frame_situation",
        "gather_intent",
        "determine_rule_trigger",
        "resolve_mechanics",
        "apply_consequences",
        "narrate_outcome",
        "present_next_decision_point",
    ])


class GMDecisionContract(BaseModel):
    trigger_type: str = "none"
    resolution_kind: str = "none"
    consult_rules: bool = False
    ask_for_roll: bool = False
    ask_follow_up: bool = False
    follow_up_question: str = ""
    passive_sources: list[str] = Field(default_factory=list)
    player_facing_mode: str = "narration"   # narration | clarification | rules_handoff


class GMResponseEnvelope(BaseModel):
    visible_text: str
    gm_decision: GMDecisionContract | None = None
    raw_contract: str = ""
    contract_parse_error: str = ""
    used_fallback_preview: bool = False


class GMSuggestedAction(BaseModel):
    action_type: str = "narration"
    endpoint: str = ""
    summary: str = ""
    payload_template: dict = Field(default_factory=dict)


def classify_resolution_kind(user_message: str) -> tuple[str, str, bool]:
    text = (user_message or "").strip().lower()
    if not text:
        return "none", "none", False

    if any(term in text for term in ("keep watch", "watch for", "scan for danger", "do i notice", "what do i notice", "listen for", "read the room", "keep an eye out", "look for trouble", "spot anything")):
        return "passive_awareness", "passive_check", True
    if any(term in text for term in ("dash", "dodge", "disengage", "second wind", "healing word", "cure wounds", "magic missile", "bless", "help")):
        return "named_rule_action", "compendium_action", True
    if any(term in text for term in ("attack", "strike", "shoot", "slash", "stab", "swing at")):
        return "hostile_action", "attack", True
    if any(term in text for term in ("heal", "bandage", "restore", "cure", "healing word")):
        return "recovery", "healing", True
    if any(term in text for term in ("grapple", "wrestle", "shove", "contest", "opposed")):
        return "opposed_action", "contested_check", True
    if any(term in text for term in ("sneak", "hide", "pick", "climb", "convince", "persuade", "investigate", "search", "recall", "notice")):
        return "uncertain_action", "check", True
    return "freeform", "none", False


def build_gm_procedure_plan(user_message: str) -> GMProcedurePlan:
    trigger_type, resolution_kind, should_consult_rules = classify_resolution_kind(user_message)
    notes = [
        "Keep mechanical reasoning in hidden GM context; player-facing output should stay in-fiction.",
        "If a rule trigger is unclear, ask a focused follow-up instead of inventing mechanics.",
    ]
    if should_consult_rules:
        notes.append(f"Likely resolution kind for this turn: {resolution_kind}.")
        if resolution_kind == "passive_check":
            notes.append("Prefer passive scores first; only ask for a roll if the fiction becomes actively risky or contested.")
    else:
        notes.append("No obvious deterministic procedure is required unless the fiction introduces uncertainty or risk.")

    return GMProcedurePlan(
        trigger_type=trigger_type,
        resolution_kind=resolution_kind,
        should_consult_rules=should_consult_rules,
        hidden_gm_notes=notes,
    )


def build_gm_procedure_guidance(user_message: str) -> str:
    plan = build_gm_procedure_plan(user_message)
    lines = [
        "[GM PROCEDURE LOOP]",
        "1. Frame the current situation from established fiction.",
        "2. Identify the player's concrete intent before narrating an outcome.",
        "3. Decide whether a rule procedure is required.",
        "4. If required, resolve mechanics before finalizing state.",
        "5. Apply consequences to the world and mechanical state.",
        "6. Narrate only the outcome the mechanics support.",
        "7. End with a clear next decision point for the player.",
        "[HIDDEN GM CONTRACT]",
        f"Trigger type: {plan.trigger_type}",
        f"Suggested resolution kind: {plan.resolution_kind}",
        f"Consult rules now: {'yes' if plan.should_consult_rules else 'no'}",
    ]
    lines.extend(f"• {note}" for note in plan.hidden_gm_notes)
    lines.extend([
        "[RESPONSE CONTRACT]",
        "Write normal player-facing narration first.",
        "If you need hidden GM structure, append a final JSON block using these exact delimiters:",
        f"{GM_DECISION_START}",
        '{"trigger_type":"...","resolution_kind":"...","consult_rules":true,"ask_for_roll":false,"ask_follow_up":false,"follow_up_question":"","player_facing_mode":"narration"}',
        GM_DECISION_END,
        "Never mention the hidden block in player-facing prose.",
    ])
    return "\n".join(lines)


def build_gm_decision_preview(user_message: str) -> GMDecisionContract:
    plan = build_gm_procedure_plan(user_message)
    ask_for_roll = plan.resolution_kind in {"check", "attack", "contested_check"}
    passive_sources = infer_passive_sources(user_message) if plan.resolution_kind == "passive_check" else []
    return GMDecisionContract(
        trigger_type=plan.trigger_type,
        resolution_kind=plan.resolution_kind,
        consult_rules=plan.should_consult_rules,
        ask_for_roll=ask_for_roll,
        ask_follow_up=False,
        follow_up_question="",
        passive_sources=passive_sources,
        player_facing_mode="rules_handoff" if plan.should_consult_rules else "narration",
    )


def build_gm_suggested_actions(
    decision: GMDecisionContract,
    *,
    user_message: str = "",
    system_pack: str | None = None,
) -> list[GMSuggestedAction]:
    kind = decision.resolution_kind
    if kind == "compendium_action":
        suggestions = CompendiumStore().suggest_for_resolution(
            system_pack=system_pack,
            resolution_kind=kind,
            user_message=user_message,
        )
        if suggestions:
            return [
                GMSuggestedAction(
                    action_type="compendium_action",
                    endpoint="/api/campaigns/{campaign_id}/encounters/{encounter_id}/use-compendium",
                    summary=f"Use structured compendium entry: {entry.name}.",
                    payload_template={
                        "slug": entry.slug,
                        "entry_name": entry.name,
                        "action_cost": entry.action_cost,
                        "range_feet": entry.range_feet,
                        "resource_costs": entry.resource_costs,
                    },
                )
                for entry in suggestions
            ]
        return [
            GMSuggestedAction(
                action_type="compendium_action",
                endpoint="/api/campaigns/{campaign_id}/encounters/{encounter_id}/use-compendium",
                summary="A named compendium action or spell likely applies here.",
                payload_template={"slug": ""},
            )
        ]
    if kind == "check":
        return [
            GMSuggestedAction(
                action_type="check",
                endpoint="/api/campaigns/{campaign_id}/checks/resolve",
                summary="Resolve a skill or ability check before final narration.",
                payload_template={
                    "source": "",
                    "difficulty": 15,
                    "roll_expression": "d20",
                    "advantage_state": "normal",
                    "reason": "",
                },
            )
        ]
    if kind == "attack":
        return [
            GMSuggestedAction(
                action_type="attack",
                endpoint="/api/campaigns/{campaign_id}/attacks/resolve",
                summary="Resolve an attack roll and any hit damage before final narration.",
                payload_template={
                    "source": "",
                    "target_armor_class": 10,
                    "roll_expression": "d20",
                    "advantage_state": "normal",
                    "damage_roll_expression": "1d6",
                    "damage_modifier": 0,
                    "damage_type": "",
                    "reason": "",
                },
            )
        ]
    if kind == "healing":
        return [
            GMSuggestedAction(
                action_type="healing",
                endpoint="/api/campaigns/{campaign_id}/healing/resolve",
                summary="Resolve healing and optionally apply it to the active sheet.",
                payload_template={
                    "source": "healing",
                    "roll_expression": "1d4",
                    "modifier": 0,
                    "apply_to_sheet": True,
                    "reason": "",
                },
            )
        ]
    if kind == "contested_check":
        return [
            GMSuggestedAction(
                action_type="contested_check",
                endpoint="/api/campaigns/{campaign_id}/contested-checks/resolve",
                summary="Resolve opposed d20 rolls for both sides before narrating the outcome.",
                payload_template={
                    "actor_source": "",
                    "opponent_source": "",
                    "opponent_owner_type": "npc",
                    "opponent_owner_id": "",
                    "opponent_name": "Opponent",
                    "roll_expression": "d20",
                    "actor_advantage_state": "normal",
                    "opponent_advantage_state": "normal",
                    "reason": "",
                },
            )
        ]
    if kind == "passive_check":
        passive_sources = decision.passive_sources or []
        return [
            GMSuggestedAction(
                action_type="passive_check",
                endpoint="",
                summary=f"Consult passive {' / '.join(passive_sources) if passive_sources else 'awareness'} before asking for an active roll.",
                payload_template={
                    "passive_sources": passive_sources,
                },
            )
        ]
    return [
        GMSuggestedAction(
            action_type="narration",
            endpoint="",
            summary="No deterministic mechanic is strongly indicated yet; continue with narration or clarification.",
            payload_template={},
        )
    ]


def parse_gm_response_envelope(text: str) -> GMResponseEnvelope:
    raw = text or ""
    start = raw.find(GM_DECISION_START)
    end = raw.find(GM_DECISION_END)
    if start == -1 or end == -1 or end < start:
        return GMResponseEnvelope(visible_text=raw.strip())

    visible = (raw[:start] + raw[end + len(GM_DECISION_END):]).strip()
    raw_contract = raw[start + len(GM_DECISION_START):end].strip()
    try:
        data = json.loads(raw_contract)
        decision = GMDecisionContract(**data)
        return GMResponseEnvelope(
            visible_text=visible,
            gm_decision=decision,
            raw_contract=raw_contract,
        )
    except Exception as exc:
        fallback = build_gm_decision_preview(visible or raw)
        return GMResponseEnvelope(
            visible_text=visible,
            gm_decision=fallback if fallback.consult_rules else None,
            raw_contract=raw_contract,
            contract_parse_error=str(exc),
            used_fallback_preview=bool(fallback.consult_rules),
        )


def infer_passive_sources(user_message: str) -> list[str]:
    text = (user_message or "").strip().lower()
    sources: list[str] = []
    if any(term in text for term in ("read the room", "motive", "lying", "intent")):
        sources.append("insight")
    if any(term in text for term in ("search", "investigate", "examine", "study")):
        sources.append("investigation")
    if any(term in text for term in ("listen", "watch", "notice", "spot", "keep an eye out", "scan", "look for", "danger")):
        sources.append("perception")
    return sources or ["perception"]
