"""
Builds the message list for campaign scene play.

Unlike the session engine, campaigns use a player-authoritative world model:
the world document (facts, NPCs, places, threads, factions) is the source of truth.
No extraction happens — the player confirms what is canon.
"""

from __future__ import annotations

import re as _re
from collections import defaultdict

from app.characters.derivation import derive_sheet_state
from app.campaigns.procedures import world_time_snapshot
from app.core.models import PlayMode
from app.rules.procedures.gm_flow import build_gm_procedure_guidance
from app.rules.registry import get_system_pack, list_rulebooks
from app.prompting.budget import apply_context_budget
from app.core.config import config as _global_config

# Maximum chronicle entries sent to AI. When the total exceeds this, we keep
# the first CHRON_ANCHOR entries (world-setting context) and the last
# CHRON_TAIL entries (recent events). Everything in between is omitted to
# avoid flooding the context window.
_CHRON_ANCHOR = 2
_CHRON_TAIL = 6
_CHRON_THRESHOLD = _CHRON_ANCHOR + _CHRON_TAIL   # below this → send all

# Rolling scene summary: if a scene has more than this many turns, keep only
# the most recent _SCENE_TURNS_KEEP turns verbatim and add a header noting
# how many earlier exchanges occurred.
_SCENE_TURNS_THRESHOLD = 40
_SCENE_TURNS_KEEP = 30

# How many recent turns to scan for keyword-triggered world facts.
_KEYWORD_SCAN_TURNS = 8

# Strip [Turn N] / [Turn N-M] labels the summary AI adds for human review.
# They are useful during editing but waste tokens in the AI context.
_TURN_LABEL_RE = _re.compile(r"^\s*-?\s*\[Turn\s+\d+(?:[–\-]\d+)?\]\s*", _re.IGNORECASE | _re.MULTILINE)


def _compress_chronicle(text: str) -> str:
    """Remove [Turn N] prefixes from a confirmed chronicle entry before injecting into context."""
    return _TURN_LABEL_RE.sub("- ", text).strip()


def _select_chronicle_entries(sorted_entries: list, recent_text: str) -> list:
    """
    Select chronicle entries to inject when the total exceeds _CHRON_THRESHOLD.

    Strategy (two modes):
      1. Semantic (when Ollama embedding model is configured):
         Always keep the first entry (world-setting anchor) and the last 2
         (recency).  Fill remaining slots with the top-scoring entries by
         cosine similarity to recent_text.  Falls back to heuristic on any error.
      2. Heuristic fallback:
         Keep first _CHRON_ANCHOR entries + last _CHRON_TAIL entries.
    """
    from app.memory.embedder import embed_text, cosine_similarity

    anchor_count = _CHRON_ANCHOR
    tail_count   = _CHRON_TAIL
    total_budget = anchor_count + tail_count   # same total as heuristic

    anchor = sorted_entries[:anchor_count]
    tail   = sorted_entries[-2:]               # always keep last 2 for recency
    anchor_ids = {e.id for e in anchor}
    tail_ids   = {e.id for e in tail}
    middle     = [e for e in sorted_entries if e.id not in anchor_ids and e.id not in tail_ids]

    if not middle:
        # Nothing to pick from — just return anchor + de-duped tail
        seen: set = set()
        result = []
        for e in anchor + tail:
            if e.id not in seen:
                result.append(e)
                seen.add(e.id)
        return result

    # Try semantic scoring if embedding model is configured
    semantic_ok = False
    if _global_config.embedding_model and _global_config.provider == "ollama" and recent_text.strip():
        try:
            query_vec = embed_text(
                recent_text[:800],
                _global_config.ollama_base_url,
                _global_config.embedding_model,
            )
            if query_vec:
                scored = []
                for e in middle:
                    entry_vec = embed_text(
                        e.content[:600],
                        _global_config.ollama_base_url,
                        _global_config.embedding_model,
                    )
                    sim = cosine_similarity(query_vec, entry_vec) if entry_vec else 0.0
                    scored.append((e, sim))
                scored.sort(key=lambda x: x[1], reverse=True)

                fill_slots = max(0, total_budget - anchor_count - len(tail))
                selected_middle = [e for e, _ in scored[:fill_slots]]
                selected_middle.sort(key=lambda e: e.scene_range_start)
                semantic_ok = True

                seen_ids: set = set()
                result_sem = []
                for e in anchor + selected_middle + tail:
                    if e.id not in seen_ids:
                        result_sem.append(e)
                        seen_ids.add(e.id)
                return result_sem
        except Exception:
            pass  # fall through to heuristic

    if not semantic_ok:
        # Heuristic fallback: first _CHRON_ANCHOR + last _CHRON_TAIL
        heuristic_tail = [e for e in sorted_entries[-tail_count:] if e.id not in anchor_ids]
        seen_h: set = set()
        result_h = []
        for e in anchor + heuristic_tail:
            if e.id not in seen_h:
                result_h.append(e)
                seen_h.add(e.id)
        return result_h


def _fact_is_active(fact, recent_text: str) -> bool:
    """
    Return True if this fact should be included in the current system prompt.
    - Critical facts: always included.
    - Facts with no trigger keywords: always included (unless background priority).
    - Background facts with no triggers: excluded (only appear when triggered).
    - Facts with trigger keywords: included only if any keyword appears in recent_text.
    """
    if fact.priority == "critical":
        return True
    if not fact.trigger_keywords:
        # Background facts without triggers are too general — skip them unless
        # nothing else fires. For now: normal = always, background = skip unless triggered.
        return fact.priority != "background"
    return any(kw.lower() in recent_text for kw in fact.trigger_keywords)


def build_scene_messages(
    *,
    campaign,
    player_character,
    character_sheet=None,
    recent_action_logs: list = [],
    world_facts: list,
    npcs_in_scene: list,
    active_threads: list,
    objectives: list = [],
    quests: list = [],
    chronicle: list = [],
    places: list = [],
    factions: list = [],
    npc_relationships: list = [],
    all_world_npcs: list = [],
    allow_unselected_npcs: bool = False,
    scene,
    user_message: str,
    user_name: str = "Player",
    campaign_memories: list = [],
    character_profiles: list = [],
) -> list[dict]:
    """
    Return an Ollama-compatible messages list for one turn of scene play.

    Structure:
      [system]  — world document + chronicle + scene context
      [user/assistant alternating history from scene.turns, possibly truncated]
      [user]    — current player input
    """
    # Build recent-text for keyword matching (last N turns + current message)
    recent_turns = scene.turns[-_KEYWORD_SCAN_TURNS:] if scene else []
    recent_text = " ".join(t.content.lower() for t in recent_turns) + " " + user_message.lower()

    system = _build_system(campaign, player_character, character_sheet, recent_action_logs, world_facts,
                           npcs_in_scene, active_threads, objectives, quests, chronicle,
                           places, factions, npc_relationships, scene,
                           all_world_npcs=all_world_npcs,
                           allow_unselected_npcs=allow_unselected_npcs,
                           recent_text=recent_text,
                           campaign_memories=campaign_memories,
                           character_profiles=character_profiles)

    messages: list[dict] = [{"role": "system", "content": system}]

    # ── Scene working memory (R2.5) ──────────────────────────────────────────
    # If the scene has an extracted event log, inject it right after the system
    # prompt so key earlier events remain visible even when turn history is trimmed.
    if scene and scene.scene_event_log:
        event_text = "\n".join(f"• {e}" for e in scene.scene_event_log)
        messages.append({
            "role": "system",
            "content": f"[EARLIER IN THIS SCENE — key events so far]\n{event_text}",
        })

    # ── Rolling scene summary ────────────────────────────────────────────────
    # If the scene has accumulated many turns, keep only the most recent
    # _SCENE_TURNS_KEEP verbatim and add a brief header for the rest.
    turns = scene.turns if scene else []
    if len(turns) > _SCENE_TURNS_THRESHOLD:
        omitted = len(turns) - _SCENE_TURNS_KEEP
        recent = turns[-_SCENE_TURNS_KEEP:]
        messages.append({
            "role": "system",
            "content": (
                f"[Earlier in this scene — {omitted} exchanges preceded the visible history below. "
                "Continue naturally from where the conversation picks up.]"
            ),
        })
        for turn in recent:
            messages.append({"role": turn.role, "content": turn.content})
    else:
        for turn in turns:
            messages.append({"role": turn.role, "content": turn.content})

    # Current player input
    if user_name and user_name.lower() not in ("player", "user", "", "__continue__"):
        messages.append({"role": "user", "content": f"[{user_name}]: {user_message}"})
    else:
        messages.append({"role": "user", "content": user_message})

    return apply_context_budget(messages, _global_config.context_window)


def _build_system(
    campaign,
    player_character,
    character_sheet,
    recent_action_logs: list,
    world_facts: list,
    npcs_in_scene: list,
    active_threads: list,
    objectives: list,
    quests: list,
    chronicle: list,
    places: list,
    factions: list,
    npc_relationships: list,
    scene,
    *,
    all_world_npcs: list = [],
    allow_unselected_npcs: bool = False,
    recent_text: str = "",
    campaign_memories: list = [],
    character_profiles: list = [],
) -> str:
    parts: list[str] = []

    # ── Role instruction ──────────────────────────────────────────────────────
    sg = campaign.style_guide if campaign else None
    tone = sg.tone if sg else ""
    style = sg.prose_style if sg else ""
    avoids = sg.avoids if sg else ""
    magic = sg.magic_system if sg else ""

    role_lines = [
        "You are a collaborative storytelling AI running a roleplay campaign.",
        "Your role is to play the world — narrate events, voice NPCs, describe consequences.",
        "You do NOT play the player character. Respond to what the player does.",
        "Keep responses immersive, vivid, and grounded in the world document below.",
        "",
        "WORLD FIDELITY RULES:",
        "- [WORLD FACTS] and [STORY SO FAR] are the established truth of this world. Never contradict or undo them.",
        "- You may freely invent new lore, NPC backstory, history, and detail — but only if it does not conflict with what is already established.",
        "- If something has already happened in the story, treat it as fixed fact.",
    ]
    if style:
        role_lines.append(f"Narration style: {style}")
    if tone:
        role_lines.append(f"Tone: {tone}")
    if avoids:
        role_lines.append(f"Avoid: {avoids}")
    if not allow_unselected_npcs:
        role_lines.append(
            "Do not introduce named NPCs from the world document who are not listed in "
            "[NPCs IN THIS SCENE]. You may freely create entirely new named characters "
            "who do not exist in the world document."
        )

    parts.append("\n".join(role_lines))

    # ── Rules mode / system pack guidance ───────────────────────────────────
    if campaign and getattr(campaign, "play_mode", PlayMode.NARRATIVE) == PlayMode.RULES:
        pack = get_system_pack(getattr(campaign, "system_pack", "") or "")
        if pack:
            rule_lines = [
                f"[SYSTEM PACK: {pack.name}]",
                pack.description,
                "Apply the system pack's procedures consistently.",
                "Use rules to determine uncertainty, risk, and action legality before narrating outcomes.",
            ]
            rulebook = next(
                (rb for rb in list_rulebooks() if rb.slug == pack.recommended_rulebook_slug),
                None,
            )
            if rulebook and rulebook.sections:
                rule_lines.append("[CORE RULES]")
                for section in sorted(rulebook.sections, key=lambda s: s.priority, reverse=True)[:5]:
                    rule_lines.append(f"• {section.title}: {section.content}")
            rule_lines.append(build_gm_procedure_guidance(recent_text))
            parts.append("\n".join(rule_lines))

    if campaign:
        snapshot = world_time_snapshot(getattr(campaign, "world_time_hours", 0))
        parts.append(f"[WORLD TIME]\n{snapshot['label']} ({snapshot['total_hours']} total hours elapsed)")

    active_objectives = [objective for objective in objectives if getattr(objective, "status", "") == "active"]
    if active_objectives:
        objective_lines = ["[ACTIVE OBJECTIVES]"]
        for objective in active_objectives:
            suffix = f" — {objective.description}" if getattr(objective, "description", "") else ""
            objective_lines.append(f"• {objective.title}{suffix}")
        parts.append("\n".join(objective_lines))

    active_quests = [quest for quest in quests if getattr(quest, "status", "") == "active"]
    if active_quests:
        quest_lines = ["[ACTIVE QUESTS]"]
        for quest in active_quests:
            progress = f" [{quest.progress_label}]" if getattr(quest, "stages", None) else ""
            context = []
            if getattr(quest, "giver_npc_name", ""):
                context.append(f"giver: {quest.giver_npc_name}")
            if getattr(quest, "location_name", ""):
                context.append(f"location: {quest.location_name}")
            context_text = f" ({'; '.join(context)})" if context else ""
            description = f" — {quest.description}" if getattr(quest, "description", "") else ""
            quest_lines.append(f"• {quest.title}{context_text}{progress}{description}")
            for stage in sorted(getattr(quest, "stages", []), key=lambda item: item.order):
                marker = "✓" if stage.completed else "○"
                quest_lines.append(f"  {marker} {stage.description}")
        parts.append("\n".join(quest_lines))

    # ── World facts (priority-sorted, keyword-filtered) ───────────────────────
    fact_texts = [f for f in world_facts if f.content and _fact_is_active(f, recent_text)]
    if fact_texts:
        # Critical facts first, then normal, then background (in case any background
        # facts passed the keyword trigger check)
        priority_order = {"critical": 0, "normal": 1, "background": 2}
        fact_texts.sort(key=lambda f: priority_order.get(f.priority, 1))

        # Group by category
        grouped: dict[str, list] = defaultdict(list)
        for f in fact_texts:
            cat = (f.category or "").strip()
            grouped[cat].append(f)

        fact_block_lines = ["[WORLD FACTS — established truth; do not contradict these]"]
        # Critical facts always at top under a CRITICAL marker
        critical = [f for f in fact_texts if f.priority == "critical"]
        if critical:
            fact_block_lines.append("  [CRITICAL — never contradict]")
            for f in critical:
                fact_block_lines.append(f"• {f.content}")

        # Remaining facts grouped by category
        for cat in sorted(grouped.keys(), key=lambda c: ("" if not c else c.lower())):
            cat_facts = [f for f in grouped[cat] if f.priority != "critical"]
            if not cat_facts:
                continue
            if cat:
                fact_block_lines.append(f"  [{cat.upper()}]")
            for f in cat_facts:
                fact_block_lines.append(f"• {f.content}")

        parts.append("\n".join(fact_block_lines))

    # ── Magic / technology rules ───────────────────────────────────────────────
    if magic:
        parts.append(f"[MAGIC / TECHNOLOGY]\n{magic}")

    # ── Chronicle (smart recap — anchor + recent tail, turn labels stripped) ──
    confirmed = [e for e in chronicle if e.content]
    if confirmed:
        confirmed_sorted = sorted(confirmed, key=lambda x: x.scene_range_start)
        if len(confirmed_sorted) <= _CHRON_THRESHOLD:
            recap = confirmed_sorted
        else:
            recap = _select_chronicle_entries(confirmed_sorted, recent_text)

        chron_lines = ["[STORY SO FAR — events that have already occurred; treat as fixed history]"]
        if len(confirmed_sorted) > _CHRON_THRESHOLD:
            skipped = len(confirmed_sorted) - len(recap)
            if skipped > 0:
                chron_lines.append(f"(earlier events summarised — {skipped} entries omitted for brevity)")
        for e in recap:
            if e.scene_range_start == e.scene_range_end:
                label = f"Scene {e.scene_range_start}"
            else:
                label = f"Scenes {e.scene_range_start}–{e.scene_range_end}"
            chron_lines.append(f"[{label}]\n{_compress_chronicle(e.content)}")
        parts.append("\n".join(chron_lines))

    # ── Campaign memories (extracted from past scenes) ────────────────────────
    if campaign_memories:
        from app.core.models import ImportanceLevel, CertaintyLevel

        crit_mems = [m for m in campaign_memories if m.importance == ImportanceLevel.CRITICAL]
        epic_mems = [m for m in campaign_memories if m.importance != ImportanceLevel.CRITICAL]

        if crit_mems:
            crit_lines = ["[CRITICAL STORY FACTS — must never be contradicted]"]
            for m in crit_mems:
                crit_lines.append(f"  !! {m.title}: {m.content}")
            parts.append("\n".join(crit_lines))

        if epic_mems:
            mem_lines = ["[STORY MEMORIES — established facts from previous scenes]"]
            for m in epic_mems:
                cert = ""
                if m.certainty == CertaintyLevel.RUMOR:
                    cert = " [RUMOR]"
                elif m.certainty == CertaintyLevel.SUSPICION:
                    cert = " [SUSPICION]"
                elif m.certainty == CertaintyLevel.LIE:
                    cert = " [LIE]"
                entities_tag = f" ({', '.join(m.entities)})" if m.entities else ""
                mem_lines.append(f"  • {m.title}{cert}{entities_tag}: {m.content}")
            parts.append("\n".join(mem_lines))

    # ── Character Memory Profiles ─────────────────────────────────────────────
    if character_profiles:
        profile_lines = ["[CHARACTER PROFILES — accumulated history; treat as established fact]"]
        for p in character_profiles:
            profile_lines.append(f"\n{p.character_name}:")
            if p.profile_summary:
                profile_lines.append(f"  {p.profile_summary}")
            if p.confirmed_traits:
                profile_lines.append(f"  Established traits: {'; '.join(p.confirmed_traits)}")
            if p.known_secrets:
                profile_lines.append(f"  Secrets known to player: {'; '.join(p.known_secrets)}")
            if p.last_known_state:
                profile_lines.append(f"  Current state: {p.last_known_state}")
        parts.append("\n".join(profile_lines))

    # ── Player character ──────────────────────────────────────────────────────
    if player_character and player_character.name:
        pc = player_character
        pc_lines = [f"[PLAYER CHARACTER: {pc.name}]"]
        if pc.appearance:    pc_lines.append(f"Appearance: {pc.appearance}")
        if pc.personality:   pc_lines.append(f"Personality: {pc.personality}")
        if pc.background:    pc_lines.append(f"Background: {pc.background}")
        if pc.wants:         pc_lines.append(f"Wants: {pc.wants}")
        if pc.fears:         pc_lines.append(f"Fears: {pc.fears}")
        if pc.dev_log:
            recent = pc.dev_log[-8:]
            pc_lines.append("Character development:")
            for entry in recent:
                label = f"Scene {entry.scene_number}: " if entry.scene_number else ""
                pc_lines.append(f"  • {label}{entry.note}")
        parts.append("\n".join(pc_lines))

    if character_sheet and campaign and getattr(campaign, "play_mode", PlayMode.NARRATIVE) == PlayMode.RULES:
        derived = derive_sheet_state(character_sheet)
        sheet_lines = [
            f"[CHARACTER SHEET: {character_sheet.name}]",
            f"Class: {character_sheet.character_class or 'Adventurer'}",
            f"Ancestry: {character_sheet.ancestry or 'Unspecified'}",
            f"Level: {character_sheet.level}",
            f"HP: {character_sheet.current_hp}/{character_sheet.max_hp}" + (f" (+{character_sheet.temp_hp} temp)" if character_sheet.temp_hp else ""),
            f"AC: {character_sheet.armor_class}",
            f"Speed: {character_sheet.speed}",
            f"Proficiency Bonus: {character_sheet.proficiency_bonus:+d}",
            f"Initiative: {derived['initiative']:+d}",
            f"Passive Perception: {derived['passive_perception']}",
            "Abilities: " + ", ".join(
                f"{k[:3].upper()} {v} ({character_sheet.ability_modifier(k):+d})"
                for k, v in character_sheet.abilities.items()
            ),
        ]
        if character_sheet.skill_modifiers:
            top_skills = sorted(character_sheet.skill_modifiers.items())[:8]
            sheet_lines.append("Skills: " + ", ".join(f"{k} {int(v):+d}" for k, v in top_skills))
        if character_sheet.conditions:
            sheet_lines.append("Conditions: " + ", ".join(character_sheet.conditions))
        if character_sheet.notes:
            sheet_lines.append(f"Notes: {character_sheet.notes}")
        parts.append("\n".join(sheet_lines))

    if recent_action_logs and campaign and getattr(campaign, "play_mode", PlayMode.NARRATIVE) == PlayMode.RULES:
        action_lines = ["[RECENT MECHANICAL OUTCOMES]"]
        for entry in recent_action_logs[:6]:
            action_lines.append(f"• {_format_action_log_for_prompt(entry)}")
        parts.append("\n".join(action_lines))

    # ── NPCs in this scene ────────────────────────────────────────────────────
    if npcs_in_scene:
        npc_block = ["[NPCs IN THIS SCENE]"]
        pc_name = player_character.name if player_character else "player"
        for n in npcs_in_scene:
            # Resolve active form vs base form
            active_form = _get_active_form(n)

            status_str = ""
            if hasattr(n, "status") and n.status and n.status != "active":
                status_str = f" [{n.status.upper()}]"
                if hasattr(n, "status_reason") and n.status_reason:
                    status_str += f" ({n.status_reason})"

            form_label = f" [{active_form.label}]" if active_form else ""
            line = f"• {n.name}{status_str}{form_label}"
            if n.role:          line += f" ({n.role})"

            # Use active form's appearance/personality if set, else base
            appearance  = active_form.appearance  if active_form and active_form.appearance  else n.appearance
            personality = active_form.personality if active_form and active_form.personality else n.personality
            curr_state  = active_form.current_state if active_form and active_form.current_state else n.current_state

            if personality:   line += f" — {personality}"
            if curr_state:    line += f" | Currently: {curr_state}"
            npc_block.append(line)

            if appearance:
                npc_block.append(f"  Appearance: {appearance}")

            # If in a different form, note original identity
            if active_form:
                orig_parts = []
                if n.appearance and n.appearance != appearance:
                    orig_parts.append(f"appearance: {n.appearance}")
                if n.personality and n.personality != personality:
                    orig_parts.append(f"personality: {n.personality}")
                if orig_parts:
                    npc_block.append(f"  Original form: {'; '.join(orig_parts)}")

            if n.relationship_to_player:
                npc_block.append(f"  Relationship to {pc_name}: {n.relationship_to_player}")
            if hasattr(n, "history_with_player") and n.history_with_player:
                npc_block.append(f"  History: {n.history_with_player}")
            if hasattr(n, "short_term_goal") and n.short_term_goal:
                npc_block.append(f"  Immediate goal: {n.short_term_goal}")
            if hasattr(n, "long_term_goal") and n.long_term_goal:
                npc_block.append(f"  Long-term goal: {n.long_term_goal}")
            if hasattr(n, "secrets") and n.secrets:
                npc_block.append(f"  [Hidden: {n.secrets}]")
        parts.append("\n".join(npc_block))

    # ── Other world NPCs available (when flag is set) ────────────────────────
    if allow_unselected_npcs and all_world_npcs:
        scene_npc_ids = {n.id for n in npcs_in_scene}
        available = [n for n in all_world_npcs if n.id not in scene_npc_ids]
        if available:
            avail_block = [
                "[OTHER AVAILABLE NPCs]",
                "These characters exist in the world and may appear if narratively fitting:",
            ]
            for n in available:
                status_str = ""
                if hasattr(n, "status") and n.status and n.status != "active":
                    status_str = f" [{n.status.upper()}]"
                active_form = _get_active_form(n)
                form_label = f" [{active_form.label}]" if active_form else ""
                line = f"• {n.name}{status_str}{form_label}"
                if n.role:        line += f" ({n.role})"
                personality = active_form.personality if active_form and active_form.personality else n.personality
                if personality: line += f" — {personality}"
                avail_block.append(line)
            parts.append("\n".join(avail_block))

    # ── NPC-to-NPC relationships ──────────────────────────────────────────────
    if npc_relationships:
        npc_map = {n.id: n.name for n in npcs_in_scene}
        rel_lines = ["[NPC DYNAMICS]"]
        for r in npc_relationships:
            a = npc_map.get(r.npc_id_a, r.npc_id_a)
            b = npc_map.get(r.npc_id_b, r.npc_id_b)
            line = f"• {a} ↔ {b}"
            if r.dynamic:   line += f": {r.dynamic}"
            if r.trust:     line += f" | Trust: {r.trust}"
            if r.hostility: line += f" | Hostility: {r.hostility}"
            rel_lines.append(line)
            if r.history:
                rel_lines.append(f"  History: {r.history}")
        if len(rel_lines) > 1:
            parts.append("\n".join(rel_lines))

    # ── Places ────────────────────────────────────────────────────────────────
    if places:
        place_block = ["[KNOWN LOCATIONS]"]
        for p in places:
            line = f"• {p.name}"
            if p.description:   line += f" — {p.description}"
            if p.current_state: line += f" (currently: {p.current_state})"
            place_block.append(line)
        parts.append("\n".join(place_block))

    # ── Factions ──────────────────────────────────────────────────────────────
    if factions:
        faction_block = ["[FACTIONS]"]
        for f in factions:
            line = f"• {f.name}"
            if f.description: line += f" — {f.description}"
            if hasattr(f, "standing_with_player") and f.standing_with_player:
                line += f" | Standing with player: {f.standing_with_player}"
            faction_block.append(line)
            if f.goals:   faction_block.append(f"  Goals: {f.goals}")
            if f.methods: faction_block.append(f"  Methods: {f.methods}")
            if hasattr(f, "relationship_notes") and f.relationship_notes:
                faction_block.append(f"  History with player: {f.relationship_notes}")
        parts.append("\n".join(faction_block))

    # ── Active narrative threads ──────────────────────────────────────────────
    if active_threads:
        thread_block = ["[ACTIVE NARRATIVE THREADS]"]
        for t in active_threads:
            line = f"• {t.title}"
            if t.description: line += f": {t.description}"
            thread_block.append(line)
        parts.append("\n".join(thread_block))

    # ── Scene context ─────────────────────────────────────────────────────────
    if scene:
        scene_lines = ["[CURRENT SCENE]"]
        if scene.title:    scene_lines.append(f"Title: {scene.title}")
        if scene.location: scene_lines.append(f"Location: {scene.location}")
        if scene.intent:   scene_lines.append(f"Intent: {scene.intent}")
        if scene.tone:     scene_lines.append(f"Scene tone: {scene.tone}")
        scene_lines.append(f"Scene #{scene.scene_number}")
        parts.append("\n".join(scene_lines))

    return "\n\n".join(parts)


def _format_action_log_for_prompt(entry) -> str:
    details = getattr(entry, "details", {}) or {}
    action_type = getattr(entry, "action_type", "") or "action"
    base = getattr(entry, "summary", "") or f"{getattr(entry, 'actor_name', 'Player')} performed {action_type}."

    if action_type == "attack" and details.get("attack"):
        attack = details["attack"]
        damage = details.get("damage") or {}
        text = (
            f"{getattr(entry, 'actor_name', 'Player')} resolved {getattr(entry, 'source', 'attack')} "
            f"at {attack.get('total', 0)} vs AC {attack.get('target_armor_class', 0)} "
            f"({str(attack.get('outcome', '')).replace('_', ' ')})"
        )
        if damage:
            dmg_type = damage.get("damage_type") or "damage"
            text += f"; damage dealt: {damage.get('total', 0)} {dmg_type}"
        return text + "."

    if action_type == "healing" and details.get("healing"):
        healing = details["healing"]
        text = f"{getattr(entry, 'actor_name', 'Player')} resolved healing for {healing.get('total', 0)} HP"
        sheet = details.get("sheet") or {}
        if sheet:
            text += f"; current HP is now {sheet.get('current_hp', 0)}/{sheet.get('max_hp', 0)}"
        return text + "."

    if action_type == "contested_check" and details.get("resolution"):
        resolution = details["resolution"]
        actor = resolution.get("actor") or {}
        opponent = resolution.get("opponent") or {}
        winner = str(resolution.get("winner", "tie")).replace("_", " ")
        return (
            f"{actor.get('name', 'Actor')} and {opponent.get('name', 'Opponent')} resolved a contested check: "
            f"{actor.get('total', 0)} vs {opponent.get('total', 0)}; winner: {winner}."
        )

    if action_type == "check" and details.get("resolution"):
        resolution = details["resolution"]
        return (
            f"{getattr(entry, 'actor_name', 'Player')} resolved {resolution.get('source') or getattr(entry, 'source', 'check')} "
            f"at {resolution.get('total', 0)} vs DC {resolution.get('difficulty', 0)} "
            f"({str(resolution.get('outcome', '')).replace('_', ' ')})."
        )

    return base


def _get_active_form(npc):
    """Return the NpcForm object for the NPC's active_form, or None if on base form."""
    if not hasattr(npc, "active_form") or not npc.active_form:
        return None
    if not hasattr(npc, "forms") or not npc.forms:
        return None
    for form in npc.forms:
        if form.label == npc.active_form:
            return form
    return None
