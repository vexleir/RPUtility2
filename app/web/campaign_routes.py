"""
Campaign system API routes.
Registered as a sub-router in server.py.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, UTC
from typing import Optional

def _new_id() -> str:
    return str(_uuid.uuid4())

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import config
from app.core.database import ensure_db
from app.core.models import (
    StyleGuide, PlayerCharacter, PcDevEntry, PlayMode,
    ActionLogEntry, CharacterSheet, RuleAuditEvent, Rulebook, RuleSection,
    CampaignPlace, NpcCard, NpcStatus, NpcDevEntry,
    NpcRelationship,
    NarrativeThread, ThreadStatus, Encounter,
    CampaignScene, CampaignFaction, CampaignObjective, CampaignQuest,
    CampaignEvent, CampaignEventStatus,
    SceneTurn, ChronicleEntry, ObjectiveStatus, QuestStatus, QuestStage,
    ImportanceLevel,
)
from app.campaigns.store import (
    CampaignStore,
    PlayerCharacterStore,
    WorldFactStore,
    CampaignPlaceStore,
    NpcCardStore,
    NarrativeThreadStore,
    SceneStore,
    ChronicleStore,
    CampaignFactionStore,
    CampaignObjectiveStore,
    CampaignQuestStore,
    CampaignEventStore,
    NpcRelationshipStore,
)
from app.campaigns.world_builder import WorldBuilder, _dict_to_world_build_result
from app.campaigns.procedures import (
    advance_campaign_quest,
    build_campaign_events,
    build_downtime_activity_result,
    generate_treasure_bundle,
    mature_campaign_event,
    shift_faction_standing,
    world_time_snapshot,
)
from app.campaigns.scene_prompter import build_scene_messages
from app.characters.store import CharacterSheetStore
from app.compendium import CompendiumEntry, CompendiumStore
from app.characters.derivation import derive_sheet_state
from app.characters.progression import apply_level_progression
from app.characters.quickbuild import build_quick_character_sheet, list_quick_build_options
from app.characters.sheets import normalize_sheet
from app.characters.resources import adjust_currency, consume_resource, restore_resource_pools
from app.encounters import (
    EncounterStore,
    apply_condition_to_participant,
    apply_damage_to_participant,
    apply_healing_to_participant,
    consume_participant_action,
    advance_encounter_turn,
    build_encounter,
    build_encounter_participant,
    complete_encounter,
    generate_encounter_summary,
    grant_participant_movement,
    resolve_participant_concentration_check,
    set_participant_concentration,
    spend_participant_movement,
    stabilize_participant,
)
from app.rules.registry import list_system_packs, list_rulebooks, get_system_pack
from app.rules.store import RulebookStore
from app.rules.resolution import (
    resolve_contested_d20_check,
    resolve_d20_attack,
    resolve_d20_check,
    resolve_damage_roll,
    resolve_healing_roll,
)
from app.rules.sheet_state import apply_sheet_state_change
from app.rules.action_log import ActionLogStore
from app.rules.audit import RuleAuditStore
from app.rules.procedures import (
    GM_DECISION_START,
    build_gm_decision_preview,
    build_gm_procedure_plan,
    build_gm_suggested_actions,
    parse_gm_response_envelope,
)
from app.rules.validators import (
    validate_action_cost,
    validate_advantage_state,
    validate_contested_check_inputs,
    validate_dice_expression,
    validate_non_negative_int,
    validate_positive_int,
    validate_resource_costs,
)

log = logging.getLogger("rp_utility")

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

# ── Store accessors ────────────────────────────────────────────────────────────

def _db() -> str:
    ensure_db(config.db_path)
    return config.db_path

def _campaigns():           return CampaignStore(_db())
def _pcs():                 return PlayerCharacterStore(_db())
def _facts():               return WorldFactStore(_db())
def _places():              return CampaignPlaceStore(_db())
def _npcs():                return NpcCardStore(_db())
def _threads():             return NarrativeThreadStore(_db())
def _scenes():              return SceneStore(_db())
def _chronicle():           return ChronicleStore(_db())
def _factions():            return CampaignFactionStore(_db())
def _objectives():          return CampaignObjectiveStore(_db())
def _quests():              return CampaignQuestStore(_db())
def _events():              return CampaignEventStore(_db())
def _npc_relationships():   return NpcRelationshipStore(_db())
def _sheets():              return CharacterSheetStore(_db())
def _rulebooks_store():     return RulebookStore()
def _compendium_store():    return CompendiumStore()
def _action_logs():         return ActionLogStore(_db())
def _rule_audits():         return RuleAuditStore(_db())
def _encounters():          return EncounterStore(_db())

def _world_builder() -> WorldBuilder:
    return WorldBuilder(
        base_url=config.ollama_base_url,
        model=config.ollama_model,
    )

# ── Request models ─────────────────────────────────────────────────────────────

class CreateCampaignRequest(BaseModel):
    name: str
    model_name: Optional[str] = None
    play_mode: str = "narrative"
    system_pack: Optional[str] = None
    feature_flags: dict[str, bool] = {}
    prose_style: str = ""
    tone: str = ""
    themes: list[str] = []

class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    summary_model_name: Optional[str] = None
    play_mode: Optional[str] = None
    system_pack: Optional[str] = None
    feature_flags: Optional[dict[str, bool]] = None
    prose_style: Optional[str] = None
    tone: Optional[str] = None
    themes: Optional[list[str]] = None
    magic_system: Optional[str] = None
    notes: Optional[str] = None
    # Gen settings
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None
    context_window: Optional[int] = None

class SavePlayerCharacterRequest(BaseModel):
    name: str = "The Protagonist"
    appearance: str = ""
    personality: str = ""
    background: str = ""
    wants: str = ""
    fears: str = ""
    how_seen: str = ""
    # dev_log is managed via POST /player-character/dev-log; not accepted on PUT


class AppendDevLogRequest(BaseModel):
    note: str
    scene_number: int = 0

class ReplaceWorldFactsRequest(BaseModel):
    facts: list[str]

class SavePlaceRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    current_state: str = ""

class SaveNpcRequest(BaseModel):
    id: Optional[str] = None
    name: str
    appearance: str = ""
    personality: str = ""
    role: str = ""
    gender: str = ""
    age: str = ""
    relationship_to_player: str = ""
    current_location: str = ""
    current_state: str = ""
    is_alive: bool = True          # legacy compat — ignored if status is set
    status: str = "active"
    status_reason: str = ""
    secrets: str = ""
    short_term_goal: str = ""
    long_term_goal: str = ""
    history_with_player: str = ""
    forms: list[dict] = []         # list of NpcForm dicts
    active_form: Optional[str] = None


class AppendNpcDevLogRequest(BaseModel):
    note: str
    scene_number: int = 0


class SaveNpcRelationshipRequest(BaseModel):
    id: Optional[str] = None
    npc_id_a: str
    npc_id_b: str
    dynamic: str = ""
    trust: str = ""
    hostility: str = ""
    history: str = ""

class SaveThreadRequest(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"
    resolution: str = ""
    last_mentioned_scene: int = 0

class SaveFactionRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    goals: str = ""
    methods: str = ""
    standing_with_player: str = ""
    relationship_notes: str = ""


class SaveCampaignObjectiveRequest(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"


class SaveCampaignQuestStageRequest(BaseModel):
    id: Optional[str] = None
    description: str
    completed: bool = False
    order: int = 0


class SaveCampaignQuestRequest(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"
    giver_npc_name: str = ""
    location_name: str = ""
    reward_notes: str = ""
    importance: str = "medium"
    stages: list[SaveCampaignQuestStageRequest] = []
    tags: list[str] = []


class AdvanceCampaignQuestRequest(BaseModel):
    quest_id: str
    stage_id: Optional[str] = None
    status: Optional[str] = None
    note: str = ""
    objective_ids: list[str] = []
    advance_hours: int = 0
    generate_treasure: bool = False
    treasure_challenge_rating: Optional[int] = None
    apply_treasure_to_player: bool = True


class CompleteCampaignQuestStageRequest(BaseModel):
    stage_id: str


class SaveCampaignEventRequest(BaseModel):
    id: Optional[str] = None
    event_type: str = "world"
    title: str
    content: str = ""
    details: dict = {}
    world_time_hours: Optional[int] = None
    status: str = "pending"
    generate_treasure: bool = False
    treasure_challenge_rating: Optional[int] = None
    apply_treasure_to_player: bool = True

class CreateSceneRequest(BaseModel):
    title: str = ""
    location: str = ""
    npc_ids: list[str] = []
    intent: str = ""
    tone: str = ""
    allow_unselected_npcs: bool = False

class PatchSceneRequest(BaseModel):
    npc_ids: Optional[list[str]] = None
    title: Optional[str] = None
    location: Optional[str] = None
    tone: Optional[str] = None

class AddSceneTurnRequest(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ConfirmSceneRequest(BaseModel):
    proposed_summary: str = ""

class GenerateWorldRequest(BaseModel):
    description: str
    model_name: Optional[str] = None  # override model for this generation

class RefineWorldRequest(BaseModel):
    current: dict  # WorldBuildResult as dict
    section: str
    instructions: str
    model_name: Optional[str] = None

class ConfirmWorldRequest(BaseModel):
    world: dict  # WorldBuildResult as dict
    campaign_name: str
    model_name: Optional[str] = None
    play_mode: str = "narrative"
    system_pack: Optional[str] = None
    feature_flags: dict[str, bool] = {}
    prose_style: str = ""
    tone: str = ""


class SaveRulebookRequest(BaseModel):
    name: str
    slug: str
    description: str = ""
    system_pack: Optional[str] = None
    author: str = ""
    version: str = "1.0"
    sections: list[dict]


class SaveCompendiumEntryRequest(BaseModel):
    slug: str
    name: str
    category: str
    system_pack: Optional[str] = None
    description: str = ""
    rules_text: str = ""
    tags: list[str] = []
    action_cost: str = ""
    range_feet: Optional[int] = None
    equipment_slot: str = ""
    armor_class_bonus: int = 0
    charges_max: int = 0
    restores_on: str = ""
    resource_costs: dict[str, int] = {}
    applies_conditions: list[str] = []


class SaveCharacterSheetRequest(BaseModel):
    name: str = "Adventurer"
    ancestry: str = ""
    character_class: str = ""
    background: str = ""
    level: int = 1
    proficiency_bonus: int = 2
    abilities: dict[str, int] = {}
    skill_modifiers: dict[str, int] = {}
    save_modifiers: dict[str, int] = {}
    max_hp: int = 10
    current_hp: int = 10
    temp_hp: int = 0
    armor_class: int = 10
    speed: int = 30
    currencies: dict[str, int] = {}
    resource_pools: dict[str, dict] = {}
    prepared_spells: list[str] = []
    equipped_items: dict[str, str] = {}
    item_charges: dict[str, dict] = {}
    conditions: list[str] = []
    notes: str = ""


class PrepareCharacterSpellRequest(BaseModel):
    slug: str
    prepared: bool = True


class EquipCharacterItemRequest(BaseModel):
    slug: str
    equipped: bool = True


class RestCharacterResourcesRequest(BaseModel):
    rest_type: str = "long_rest"


class LevelUpCharacterRequest(BaseModel):
    target_level: Optional[int] = None
    hit_point_gain: int = 0
    ability_increases: dict[str, int] = {}
    resource_pool_increases: dict[str, int] = {}
    feature_note: str = ""


class QuickBuildCharacterRequest(BaseModel):
    name: str = "Adventurer"
    character_class: str
    ancestry: str
    background: str = ""
    level: int = 1


class FactionTimeEffectRequest(BaseModel):
    faction_id: str
    delta: int = 0
    note: str = ""


class AdvanceCampaignTimeRequest(BaseModel):
    hours: int = 1
    procedure_type: str = "travel"
    reason: str = ""
    destination: str = ""
    rest_type: Optional[str] = None
    faction_effects: list[FactionTimeEffectRequest] = []


class GenerateTreasureRequest(BaseModel):
    challenge_rating: int = 1
    source_type: str = "loot"
    source_name: str = ""
    apply_to_player: bool = True


class RunDowntimeRequest(BaseModel):
    activity_type: str = "work"
    days: int = 1
    subject: str = ""
    reason: str = ""
    faction_id: Optional[str] = None
    quest_id: Optional[str] = None
    objective_id: Optional[str] = None
    apply_rewards_to_player: bool = True


class ResolveCheckRequest(BaseModel):
    source: str
    difficulty: int = 15
    roll_expression: str = "d20"
    advantage_state: str = "normal"
    action_cost: str = "action"
    reason: str = ""
    resource_costs: dict[str, int] = {}


class ResolveAttackRequest(BaseModel):
    source: str
    target_armor_class: int = 10
    target_participant_id: Optional[str] = None
    range_feet: Optional[int] = None
    target_distance_feet: Optional[int] = None
    roll_expression: str = "d20"
    advantage_state: str = "normal"
    action_cost: str = "action"
    damage_roll_expression: str = "1d6"
    damage_modifier: int = 0
    damage_type: str = ""
    reason: str = ""
    resource_costs: dict[str, int] = {}


class ResolveHealingRequest(BaseModel):
    source: str = "healing"
    roll_expression: str = "1d4"
    modifier: int = 0
    apply_to_sheet: bool = True
    target_participant_id: Optional[str] = None
    range_feet: Optional[int] = None
    target_distance_feet: Optional[int] = None
    action_cost: str = "action"
    reason: str = ""
    resource_costs: dict[str, int] = {}


class ResolveContestedCheckRequest(BaseModel):
    actor_source: str
    opponent_source: str
    opponent_owner_type: Optional[str] = None
    opponent_owner_id: Optional[str] = None
    opponent_name: str = "Opponent"
    opponent_modifier: Optional[int] = None
    roll_expression: str = "d20"
    actor_advantage_state: str = "normal"
    opponent_advantage_state: str = "normal"
    action_cost: str = "action"
    reason: str = ""
    resource_costs: dict[str, int] = {}


class EncounterParticipantRequest(BaseModel):
    owner_type: str = "npc"
    owner_id: str = ""
    name: str = ""
    team: str = "enemy"
    initiative_roll: Optional[int] = None
    initiative_modifier: Optional[int] = None


class CreateEncounterRequest(BaseModel):
    name: str = "Encounter"
    scene_id: Optional[str] = None
    participants: list[EncounterParticipantRequest]


class AdvanceEncounterTurnRequest(BaseModel):
    note: str = ""


class CompleteEncounterRequest(BaseModel):
    summary: str = ""
    generate_treasure: bool = False
    treasure_challenge_rating: Optional[int] = None
    apply_treasure_to_player: bool = True


class SpendEncounterMovementRequest(BaseModel):
    distance: int
    note: str = ""


class UseEncounterReactionRequest(BaseModel):
    participant_id: Optional[str] = None
    note: str = ""


class ApplyEncounterConditionRequest(BaseModel):
    participant_id: str
    condition: str
    duration_rounds: Optional[int] = None
    note: str = ""


class StabilizeEncounterParticipantRequest(BaseModel):
    participant_id: str
    note: str = ""


class SetEncounterConcentrationRequest(BaseModel):
    participant_id: str
    active: bool = True
    label: str = ""
    note: str = ""


class ResolveEncounterConcentrationCheckRequest(BaseModel):
    participant_id: str
    success: bool
    note: str = ""


class UseEncounterCompendiumEntryRequest(BaseModel):
    slug: str
    actor_participant_id: Optional[str] = None
    target_participant_ids: list[str] = []
    note: str = ""


class AdjustCharacterSheetStateRequest(BaseModel):
    damage: int = 0
    healing: int = 0
    temp_hp_delta: int = 0
    add_conditions: list[str] = []
    remove_conditions: list[str] = []
    notes_append: str = ""


# ── Campaign CRUD ──────────────────────────────────────────────────────────────

@router.get("")
def list_campaigns():
    campaigns = _campaigns().list_all()
    return [_campaign_dict(c) for c in campaigns]


@router.get("/system-packs")
def api_list_system_packs():
    return [
        {
            "name": p.name,
            "slug": p.slug,
            "description": p.description,
            "default_play_mode": p.default_play_mode.value,
            "recommended_rulebook_slug": p.recommended_rulebook_slug,
            "author": p.author,
            "version": p.version,
            "is_builtin": p.is_builtin,
        }
        for p in list_system_packs()
    ]


@router.get("/rulebooks")
def api_list_rulebooks():
    return [
        {
            "name": r.name,
            "slug": r.slug,
            "description": r.description,
            "system_pack": r.system_pack,
            "author": r.author,
            "version": r.version,
            "is_builtin": r.is_builtin,
            "sections": len(r.sections),
        }
        for r in list_rulebooks()
    ]


@router.get("/rulebooks/{slug}")
def api_get_rulebook(slug: str):
    rulebook = _rulebooks_store().get(slug)
    if not rulebook:
        raise HTTPException(404, "Rulebook not found")
    return _rulebook_dict(rulebook)


@router.get("/compendium")
def api_list_compendium_entries(
    system_pack: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
):
    return [
        _compendium_entry_dict(entry)
        for entry in _compendium_store().list_all(
            system_pack=system_pack,
            category=category,
            query=query,
        )
    ]


@router.get("/compendium/{slug}")
def api_get_compendium_entry(slug: str, system_pack: Optional[str] = None):
    entry = _compendium_store().get(slug, system_pack=system_pack)
    if not entry:
        raise HTTPException(404, "Compendium entry not found")
    return _compendium_entry_dict(entry)


@router.post("/compendium", status_code=201)
def api_save_compendium_entry(req: SaveCompendiumEntryRequest):
    try:
        range_feet = validate_non_negative_int(req.range_feet, "range_feet") if req.range_feet is not None else None
        resource_costs = validate_resource_costs(req.resource_costs)
        entry = CompendiumEntry(
            slug=req.slug,
            name=req.name,
            category=req.category,  # type: ignore[arg-type]
            system_pack=req.system_pack,
            description=req.description,
            rules_text=req.rules_text,
            tags=[str(tag).strip() for tag in (req.tags or []) if str(tag).strip()],
            action_cost=req.action_cost,
            range_feet=range_feet,
            equipment_slot=str(req.equipment_slot or "").strip().lower(),
            armor_class_bonus=int(req.armor_class_bonus or 0),
            charges_max=max(0, int(req.charges_max or 0)),
            restores_on=str(req.restores_on or "").strip().lower(),
            resource_costs=resource_costs,
            applies_conditions=[str(condition).strip().lower() for condition in (req.applies_conditions or []) if str(condition).strip()],
            is_builtin=False,
        )
        _compendium_store().save(entry)
    except Exception as e:
        raise HTTPException(400, f"Could not save compendium entry: {e}")
    return _compendium_entry_dict(entry)


@router.post("/rulebooks", status_code=201)
def api_save_rulebook(req: SaveRulebookRequest):
    sections = [
        RuleSection(
            title=s.get("title", "Untitled Section"),
            content=s.get("content", ""),
            tags=[str(t) for t in s.get("tags", [])],
            priority=int(s.get("priority", 0)),
        )
        for s in req.sections
        if s.get("content")
    ]
    if not sections:
        raise HTTPException(400, "Rulebook must include at least one section")
    rulebook = Rulebook(
        name=req.name,
        slug=req.slug,
        description=req.description,
        system_pack=req.system_pack,
        author=req.author,
        version=req.version,
        is_builtin=False,
        sections=sections,
    )
    _rulebooks_store().save(rulebook)
    return _rulebook_dict(rulebook)


@router.post("", status_code=201)
def create_campaign(req: CreateCampaignRequest):
    try:
        play_mode = PlayMode(req.play_mode)
    except ValueError:
        raise HTTPException(400, "Invalid play mode")
    sg = StyleGuide(
        prose_style=req.prose_style,
        tone=req.tone,
        themes=req.themes,
    )
    c = _campaigns().create(
        name=req.name,
        model_name=req.model_name,
        style_guide=sg,
        play_mode=play_mode,
        system_pack=req.system_pack,
        feature_flags=req.feature_flags,
    )
    return _campaign_dict(c)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str):
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return _campaign_dict(c)


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: str, req: UpdateCampaignRequest):
    store = _campaigns()
    c = store.get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    updates: dict = {}
    if req.name is not None:                 updates["name"] = req.name
    if req.model_name is not None:           updates["model_name"] = req.model_name
    if req.summary_model_name is not None:   updates["summary_model_name"] = req.summary_model_name
    if req.play_mode is not None:
        try:
            updates["play_mode"] = PlayMode(req.play_mode)
        except ValueError:
            raise HTTPException(400, "Invalid play mode")
    if req.system_pack is not None:
        updates["system_pack"] = req.system_pack
    if req.feature_flags is not None:
        updates["feature_flags"] = req.feature_flags
    if any(f is not None for f in [req.prose_style, req.tone, req.themes, req.magic_system]):
        sg = c.style_guide
        if req.prose_style is not None:   sg = sg.model_copy(update={"prose_style": req.prose_style})
        if req.tone is not None:          sg = sg.model_copy(update={"tone": req.tone})
        if req.themes is not None:        sg = sg.model_copy(update={"themes": req.themes})
        if req.magic_system is not None:  sg = sg.model_copy(update={"magic_system": req.magic_system})
        updates["style_guide"] = sg
    if req.notes is not None:
        updates["notes"] = req.notes
    _GS_FIELDS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "max_tokens", "seed", "context_window")
    if any(getattr(req, f) is not None for f in _GS_FIELDS):
        gs = c.gen_settings
        patch = {f: getattr(req, f) for f in _GS_FIELDS if getattr(req, f) is not None}
        gs = gs.model_copy(update=patch)
        updates["gen_settings"] = gs
    updated = store.update(campaign_id, **updates)
    if not updated:
        raise HTTPException(404, "Campaign not found")
    return _campaign_dict(updated)


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str):
    deleted = _campaigns().delete(campaign_id)
    if not deleted:
        raise HTTPException(404, "Campaign not found")


# ── Player Character ───────────────────────────────────────────────────────────

@router.get("/{campaign_id}/player-character")
def get_player_character(campaign_id: str):
    pc = _pcs().get(campaign_id)
    if not pc:
        return {}
    return _pc_dict(pc)


@router.put("/{campaign_id}/player-character")
def save_player_character(campaign_id: str, req: SavePlayerCharacterRequest):
    _require_campaign(campaign_id)
    existing = _pcs().get(campaign_id)
    pc = PlayerCharacter(
        id=existing.id if existing else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        appearance=req.appearance,
        personality=req.personality,
        background=req.background,
        wants=req.wants,
        fears=req.fears,
        how_seen=req.how_seen,
        dev_log=existing.dev_log if existing else [],   # preserve existing log
    )
    _pcs().save(pc)
    return _pc_dict(pc)


@router.post("/{campaign_id}/player-character/dev-log", status_code=201)
def append_pc_dev_log(campaign_id: str, req: AppendDevLogRequest):
    """Append a development log entry to the player character."""
    store = _pcs()
    pc = store.get(campaign_id)
    if not pc:
        raise HTTPException(404, "Player character not found")
    pc.dev_log.append(PcDevEntry(scene_number=req.scene_number, note=req.note))
    store.save(pc)
    return _pc_dict(pc)


# ── World Facts ────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/world-facts")
def get_world_facts(campaign_id: str):
    facts = _facts().get_all(campaign_id)
    return [_fact_dict(f) for f in facts]


@router.put("/{campaign_id}/world-facts")
def replace_world_facts(campaign_id: str, req: ReplaceWorldFactsRequest):
    _require_campaign(campaign_id)
    saved = _facts().replace_all(campaign_id, req.facts)
    return [_fact_dict(f) for f in saved]


@router.delete("/{campaign_id}/world-facts/{fact_id}", status_code=204)
def delete_world_fact(campaign_id: str, fact_id: str):
    _facts().delete(fact_id)


class PatchWorldFactRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None          # "critical" | "normal" | "background"
    trigger_keywords: Optional[list[str]] = None


@router.patch("/{campaign_id}/world-facts/{fact_id}")
def patch_world_fact(campaign_id: str, fact_id: str, req: PatchWorldFactRequest):
    """Update content, category, priority, and/or trigger keywords of a single world fact."""
    updated = _facts().update(
        fact_id,
        content=req.content,
        category=req.category,
        priority=req.priority,
        trigger_keywords=req.trigger_keywords,
    )
    if not updated:
        raise HTTPException(404, "Fact not found")
    return _fact_dict(updated)


# ── Campaign notes (player scratchpad) ────────────────────────────────────────

class PatchNotesRequest(BaseModel):
    notes: str


@router.patch("/{campaign_id}/notes")
def patch_campaign_notes(campaign_id: str, req: PatchNotesRequest):
    """Save the player scratchpad notes for a campaign."""
    updated = _campaigns().update(campaign_id, notes=req.notes)
    return {"notes": updated.notes}


# ── Places ─────────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/places")
def get_places(campaign_id: str):
    return [_place_dict(p) for p in _places().get_all(campaign_id)]


@router.put("/{campaign_id}/places")
def save_place(campaign_id: str, req: SavePlaceRequest):
    _require_campaign(campaign_id)
    existing = _places().get(req.id) if req.id else None
    p = CampaignPlace(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        description=req.description,
        current_state=req.current_state,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _places().save(p)
    return _place_dict(p)


@router.delete("/{campaign_id}/places/{place_id}", status_code=204)
def delete_place(campaign_id: str, place_id: str):
    _places().delete(place_id)


# ── NPC Cards ──────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/npcs")
def get_npcs(campaign_id: str):
    return [_npc_dict(n) for n in _npcs().get_all(campaign_id)]


@router.put("/{campaign_id}/npcs")
def save_npc(campaign_id: str, req: SaveNpcRequest):
    _require_campaign(campaign_id)
    existing = _npcs().get(req.id) if req.id else None
    # Resolve status: prefer explicit status field; fall back to legacy is_alive
    try:
        status = NpcStatus(req.status)
    except ValueError:
        status = NpcStatus.ACTIVE
    if not req.is_alive and status == NpcStatus.ACTIVE:
        status = NpcStatus.DEAD
    # Parse forms list from request dicts
    from app.core.models import NpcForm as _NpcForm
    forms = [_NpcForm(**f) if isinstance(f, dict) else f for f in (req.forms or [])]

    n = NpcCard(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        appearance=req.appearance,
        personality=req.personality,
        role=req.role,
        gender=req.gender,
        age=req.age,
        relationship_to_player=req.relationship_to_player,
        current_location=req.current_location,
        current_state=req.current_state,
        status=status,
        status_reason=req.status_reason,
        secrets=req.secrets,
        short_term_goal=req.short_term_goal,
        long_term_goal=req.long_term_goal,
        history_with_player=req.history_with_player,
        forms=forms,
        active_form=req.active_form,
        portrait_image=existing.portrait_image if existing else None,
        dev_log=existing.dev_log if existing else [],
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _npcs().save(n)
    return _npc_dict(n)


@router.post("/{campaign_id}/npcs/{npc_id}/dev-log", status_code=201)
def append_npc_dev_log(campaign_id: str, npc_id: str, req: AppendNpcDevLogRequest):
    """Append a development log entry to an NPC card."""
    store = _npcs()
    n = store.get(npc_id)
    if not n or n.campaign_id != campaign_id:
        raise HTTPException(404, "NPC not found")
    n.dev_log.append(NpcDevEntry(scene_number=req.scene_number, note=req.note))
    store.save(n)
    return _npc_dict(n)


@router.delete("/{campaign_id}/npcs/{npc_id}", status_code=204)
def delete_npc(campaign_id: str, npc_id: str):
    _npcs().delete(npc_id)
    # Orphaned relationships (pointing to the deleted NPC) are benign;
    # they will not appear in scene prompts and can be removed manually.


# ── NPC Relationships ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/npc-relationships")
def get_npc_relationships(campaign_id: str):
    return [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)]


@router.put("/{campaign_id}/npc-relationships")
def save_npc_relationship(campaign_id: str, req: SaveNpcRelationshipRequest):
    _require_campaign(campaign_id)
    existing = _npc_relationships().get(req.id) if req.id else None
    r = NpcRelationship(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        npc_id_a=req.npc_id_a,
        npc_id_b=req.npc_id_b,
        dynamic=req.dynamic,
        trust=req.trust,
        hostility=req.hostility,
        history=req.history,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _npc_relationships().save(r)
    return _rel_dict(r)


@router.delete("/{campaign_id}/npc-relationships/{rel_id}", status_code=204)
def delete_npc_relationship(campaign_id: str, rel_id: str):
    store = _npc_relationships()
    r = store.get(rel_id)
    if not r or r.campaign_id != campaign_id:
        raise HTTPException(404, "Relationship not found")
    store.delete(rel_id)


# ── Narrative Threads ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/threads")
def get_threads(campaign_id: str):
    return [_thread_dict(t) for t in _threads().get_all(campaign_id)]


@router.put("/{campaign_id}/threads")
def save_thread(campaign_id: str, req: SaveThreadRequest):
    _require_campaign(campaign_id)
    existing = _threads().get(req.id) if req.id else None
    t = NarrativeThread(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        title=req.title,
        description=req.description,
        status=ThreadStatus(req.status),
        resolution=req.resolution,
        last_mentioned_scene=req.last_mentioned_scene if req.last_mentioned_scene else (existing.last_mentioned_scene if existing else 0),
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _threads().save(t)
    return _thread_dict(t)


@router.delete("/{campaign_id}/threads/{thread_id}", status_code=204)
def delete_thread(campaign_id: str, thread_id: str):
    _threads().delete(thread_id)


# ── Factions ───────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/factions")
def get_factions(campaign_id: str):
    return [_faction_dict(f) for f in _factions().get_all(campaign_id)]


@router.put("/{campaign_id}/factions")
def save_faction(campaign_id: str, req: SaveFactionRequest):
    _require_campaign(campaign_id)
    existing = _factions().get(req.id) if req.id else None
    f = CampaignFaction(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        description=req.description,
        goals=req.goals,
        methods=req.methods,
        standing_with_player=req.standing_with_player,
        relationship_notes=req.relationship_notes,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _factions().save(f)
    return _faction_dict(f)


@router.delete("/{campaign_id}/factions/{faction_id}", status_code=204)
def delete_faction(campaign_id: str, faction_id: str):
    _factions().delete(faction_id)


# ── Objectives and Quests ─────────────────────────────────────────────────────

@router.get("/{campaign_id}/objectives")
def get_campaign_objectives(campaign_id: str):
    _require_campaign(campaign_id)
    return [_objective_dict(objective) for objective in _objectives().get_all(campaign_id)]


@router.put("/{campaign_id}/objectives")
def save_campaign_objective(campaign_id: str, req: SaveCampaignObjectiveRequest):
    _require_campaign(campaign_id)
    existing = _objectives().get(req.id) if req.id else None
    objective = CampaignObjective(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        title=req.title,
        description=req.description,
        status=ObjectiveStatus(req.status),
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _objectives().save(objective)
    return _objective_dict(objective)


@router.delete("/{campaign_id}/objectives/{objective_id}", status_code=204)
def delete_campaign_objective(campaign_id: str, objective_id: str):
    _require_campaign(campaign_id)
    _objectives().delete(objective_id)


@router.get("/{campaign_id}/quests")
def get_campaign_quests(campaign_id: str):
    _require_campaign(campaign_id)
    return [_quest_dict(quest) for quest in _quests().get_all(campaign_id)]


@router.put("/{campaign_id}/quests")
def save_campaign_quest(campaign_id: str, req: SaveCampaignQuestRequest):
    _require_campaign(campaign_id)
    existing = _quests().get(req.id) if req.id else None
    stages = [
        QuestStage(
            id=stage.id if stage.id else _new_id(),
            description=stage.description,
            completed=stage.completed,
            order=stage.order,
        )
        for stage in req.stages
    ]
    quest = CampaignQuest(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        title=req.title,
        description=req.description,
        status=QuestStatus(req.status),
        giver_npc_name=req.giver_npc_name,
        location_name=req.location_name,
        reward_notes=req.reward_notes,
        importance=ImportanceLevel(req.importance),
        stages=stages,
        tags=req.tags,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _quests().save(quest)
    return _quest_dict(quest)


@router.delete("/{campaign_id}/quests/{quest_id}", status_code=204)
def delete_campaign_quest(campaign_id: str, quest_id: str):
    _require_campaign(campaign_id)
    _quests().delete(quest_id)


@router.post("/{campaign_id}/quests/{quest_id}/complete-stage")
def complete_campaign_quest_stage(campaign_id: str, quest_id: str, req: CompleteCampaignQuestStageRequest):
    _require_campaign(campaign_id)
    quest = _quests().get(quest_id)
    if not quest or quest.campaign_id != campaign_id:
        raise HTTPException(404, "Quest not found")
    try:
        updated = advance_campaign_quest(quest, stage_id=req.stage_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    updated.updated_at = datetime.now(UTC).replace(tzinfo=None)
    _quests().save(updated)
    return _quest_dict(updated)


@router.get("/{campaign_id}/events")
def get_campaign_events(campaign_id: str):
    _require_campaign(campaign_id)
    return [_campaign_event_dict(event) for event in _events().get_all(campaign_id)]


@router.put("/{campaign_id}/events")
def save_campaign_event(campaign_id: str, req: SaveCampaignEventRequest):
    campaign = _require_campaign(campaign_id)
    existing = _events().get(req.id) if req.id else None
    status = str(req.status or "pending").strip().lower()
    if status not in {state.value for state in CampaignEventStatus}:
        raise HTTPException(400, "status must be pending or resolved")
    event = CampaignEvent(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        event_type=str(req.event_type or "world").strip().lower() or "world",
        title=req.title,
        content=req.content,
        details=dict(req.details or {}),
        world_time_hours=(
            int(req.world_time_hours)
            if req.world_time_hours is not None
            else int(getattr(campaign, "world_time_hours", 0))
        ),
        status=CampaignEventStatus(status),
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _events().save(event)
    treasure_bundle = None
    player_sheet_payload = None
    if (
        req.generate_treasure
        and event.status == CampaignEventStatus.RESOLVED
    ):
        challenge_rating = (
            validate_non_negative_int(req.treasure_challenge_rating, "treasure_challenge_rating")
            if req.treasure_challenge_rating is not None
            else 1
        )
        treasure_bundle = generate_treasure_bundle(
            challenge_rating=challenge_rating,
            source_type="event",
            source_name=event.title,
        )
        if req.apply_treasure_to_player:
            player_sheet_payload = _apply_treasure_bundle_to_player(campaign_id, treasure_bundle)
        scene = _scenes().get_active(campaign_id)
        details = {
            "event": _campaign_event_dict(event),
            "treasure": treasure_bundle,
            "player_sheet": player_sheet_payload,
        }
        _action_logs().save(ActionLogEntry(
            campaign_id=campaign_id,
            scene_id=scene.id if scene else None,
            actor_name="GM",
            action_type="treasure",
            source="event",
            summary=f"Treasure generated from event '{event.title}'.",
            details=details,
        ))
        _record_rule_audit(
            campaign_id=campaign_id,
            scene_id=scene.id if scene else None,
            event_type="treasure",
            actor_name="GM",
            source="event",
            reason=event.title,
            payload=details,
        )
    payload = _campaign_event_dict(event)
    payload["treasure"] = treasure_bundle
    payload["player_sheet"] = player_sheet_payload
    return payload


@router.post("/{campaign_id}/events/{event_id}/generate-encounter")
def generate_encounter_from_campaign_event(campaign_id: str, event_id: str):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    event = _events().get(event_id)
    if not event or event.campaign_id != campaign_id:
        raise HTTPException(404, "Campaign event not found")
    hook_type = str((event.details or {}).get("hook_type", "")).strip().lower()
    if hook_type != "encounter":
        raise HTTPException(400, "This event does not define an encounter hook")

    scene = _scenes().get_active(campaign_id)
    if not scene:
        raise HTTPException(400, "An active scene is required to generate an encounter from an event")
    if _encounters().get_active(campaign_id, scene.id):
        raise HTTPException(400, "An active encounter already exists for this scene")

    participants = [_build_encounter_participant_request(
        campaign_id,
        EncounterParticipantRequest(owner_type="player", owner_id="player", team="player"),
    )]

    desired_enemy_count = max(1, int((event.details or {}).get("enemy_count", 1)))
    available_npcs = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    hostile_npcs = [npc for npc in available_npcs if npc.status == NpcStatus.ACTIVE][:desired_enemy_count]
    for npc in hostile_npcs:
        participants.append(_build_encounter_participant_request(
            campaign_id,
            EncounterParticipantRequest(owner_type="npc", owner_id=npc.id, team="enemy"),
        ))

    synthetic_needed = desired_enemy_count - len(hostile_npcs)
    for index in range(synthetic_needed):
        participants.append(_build_encounter_participant_request(
            campaign_id,
            EncounterParticipantRequest(
                owner_type="npc",
                owner_id="",
                name=f"{event.title} Foe {index + 1}",
                team="enemy",
                initiative_roll=8 + index,
                initiative_modifier=1,
            ),
        ))

    encounter = build_encounter(
        campaign_id=campaign_id,
        scene_id=scene.id,
        name=event.title,
        participants=participants,
    )
    _encounters().save(encounter)

    event.status = CampaignEventStatus.RESOLVED
    event.details = dict(event.details or {})
    event.details["generated_encounter_id"] = encounter.id
    event.updated_at = datetime.now(UTC).replace(tzinfo=None)
    _events().save(event)

    details = {
        "event": _campaign_event_dict(event),
        "encounter": _encounter_dict(encounter),
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id,
        actor_name="GM",
        action_type="campaign_event",
        source=event.title,
        summary=f"Generated encounter '{encounter.name}' from campaign event '{event.title}'.",
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id,
        event_type="campaign_event",
        actor_name="GM",
        source=event.title,
        reason="encounter hook",
        payload=details,
    )
    return {
        "event": _campaign_event_dict(event),
        "encounter": _encounter_dict(encounter),
        "summary": f"Encounter '{encounter.name}' generated from '{event.title}'.",
    }


@router.delete("/{campaign_id}/events/{event_id}", status_code=204)
def delete_campaign_event(campaign_id: str, event_id: str):
    _require_campaign(campaign_id)
    _events().delete(event_id)


# ── Scenes ─────────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/scenes")
def get_scenes(campaign_id: str):
    return [_scene_dict(s) for s in _scenes().get_all(campaign_id)]


@router.get("/{campaign_id}/scenes/active")
def get_active_scene(campaign_id: str):
    scene = _scenes().get_active(campaign_id)
    if not scene:
        return None
    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes", status_code=201)
def create_scene(campaign_id: str, req: CreateSceneRequest):
    _require_campaign(campaign_id)
    scene_num = _scenes().next_scene_number(campaign_id)
    s = CampaignScene(
        campaign_id=campaign_id,
        scene_number=scene_num,
        title=req.title,
        location=req.location,
        npc_ids=req.npc_ids,
        intent=req.intent,
        tone=req.tone,
        allow_unselected_npcs=req.allow_unselected_npcs,
    )
    _scenes().save(s)
    return _scene_dict(s)


@router.patch("/{campaign_id}/scenes/{scene_id}")
def patch_scene(campaign_id: str, scene_id: str, req: PatchSceneRequest):
    """Update mutable scene fields (npc_ids, title, location, tone) mid-scene."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if req.npc_ids is not None:  scene.npc_ids = req.npc_ids
    if req.title is not None:    scene.title = req.title
    if req.location is not None: scene.location = req.location
    if req.tone is not None:     scene.tone = req.tone
    store.save(scene)
    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes/{scene_id}/turns", status_code=201)
def add_scene_turn(campaign_id: str, scene_id: str, req: AddSceneTurnRequest):
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")

    scene.turns.append(SceneTurn(role=req.role, content=req.content))
    store.save(scene)
    return _scene_dict(scene)


@router.delete("/{campaign_id}/scenes/{scene_id}/turns/last")
def undo_last_turns(campaign_id: str, scene_id: str):
    """Remove the last AI response and its preceding user turn (undo one exchange)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot undo turns in a confirmed scene")
    if not scene.turns:
        raise HTTPException(400, "No turns to undo")
    # Pop trailing assistant turn, then any preceding user turn
    if scene.turns and scene.turns[-1].role == "assistant":
        scene.turns.pop()
    if scene.turns and scene.turns[-1].role == "user":
        scene.turns.pop()
    store.save(scene)
    return _scene_dict(scene)


@router.delete("/{campaign_id}/scenes/{scene_id}", status_code=204)
def delete_scene(campaign_id: str, scene_id: str):
    """Delete an unconfirmed scene and all its turns."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot delete a confirmed scene")
    store.delete(scene_id)


@router.put("/{campaign_id}/scenes/{scene_id}/turns/last-assistant")
def replace_last_assistant_turn(campaign_id: str, scene_id: str, req: ReplaceLastAssistantRequest):
    """Replace the content of the last assistant turn (used by the regenerate alternative selector)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot modify a confirmed scene")
    for i in range(len(scene.turns) - 1, -1, -1):
        if scene.turns[i].role == "assistant":
            scene.turns[i] = SceneTurn(role="assistant", content=req.content)
            store.save(scene)
            return {"ok": True}
    raise HTTPException(400, "No assistant turn found")


@router.post("/{campaign_id}/scenes/{scene_id}/regenerate")
def scene_regenerate_stream(campaign_id: str, scene_id: str, req: SceneRegenerateRequest):
    """
    Stream a new AI response for the same user message as the last exchange.
    The previous assistant turn is replaced; the user turn is preserved.
    """
    import json as _json
    import httpx

    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")
    if not scene.turns or scene.turns[-1].role != "assistant":
        raise HTTPException(400, "Last turn is not an assistant turn")

    # Strip the last assistant turn; extract the preceding user message
    scene.turns.pop()
    if not scene.turns or scene.turns[-1].role != "user":
        raise HTTPException(400, "No preceding user turn found")
    last_user_content = scene.turns.pop().content

    # Load context
    pc = _pcs().get(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    objectives_list = _objectives().get_active(campaign_id)
    quests_list = _quests().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = []
    npc_rels_list = []
    if scene.npc_ids:
        npc_list = _npcs().get_many(scene.npc_ids)
        npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []
    recent_action_logs = _action_logs().get_recent_for_scene(campaign_id, scene.id, n=6)

    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        character_sheet=sheet,
        recent_action_logs=recent_action_logs,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=last_user_content,
        user_name="Player",
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    # Re-store the user turn before streaming begins
    scene.turns.append(SceneTurn(role="user", content=last_user_content))

    def _stream():
        full_response: list[str] = []
        visible_buffer = ""
        saw_contract = False
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        scene.turns.append(SceneTurn(role="assistant", content="".join(full_response)))
        scene_store.save(scene)

    return StreamingResponse(_stream(), media_type="text/plain")


@router.get("/{campaign_id}/scenes/{scene_id}/prompt-preview")
def get_prompt_preview(campaign_id: str, scene_id: str):
    """Return the rendered system prompt for the current scene state (debug tool)."""
    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    pc = _pcs().get(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    objectives_list = _objectives().get_active(campaign_id)
    quests_list = _quests().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids) if scene.npc_ids else []
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []
    recent_action_logs = _action_logs().get_recent_for_scene(campaign_id, scene.id, n=6)

    messages = build_scene_messages(
        campaign=campaign, player_character=pc, character_sheet=sheet, recent_action_logs=recent_action_logs, world_facts=world_facts_list,
        npcs_in_scene=npc_list, active_threads=threads_list, objectives=objectives_list, quests=quests_list, chronicle=chronicle_list,
        places=places_list, factions=factions_list, npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list, allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene, user_message="[preview only]", user_name="",
    )
    system_prompt = messages[0]["content"] if messages else ""
    return {"system_prompt": system_prompt, "total_messages": len(messages)}


@router.post("/{campaign_id}/scenes/{scene_id}/confirm")
def confirm_scene(campaign_id: str, scene_id: str, req: ConfirmSceneRequest):
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    summary = req.proposed_summary or scene.proposed_summary
    scene.proposed_summary = summary
    scene.confirmed_summary = summary
    scene.confirmed = True
    store.save(scene)

    # Upsert chronicle entry — update existing if one exists for this scene number
    if summary:
        _upsert_chronicle(campaign_id, scene.scene_number, summary)

    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes/{scene_id}/reopen")
def reopen_scene(campaign_id: str, scene_id: str):
    """Reopen a confirmed scene so turns can be added or edited."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if not scene.confirmed:
        raise HTTPException(400, "Scene is not confirmed")
    scene.confirmed = False
    store.save(scene)
    return _scene_dict(scene)


class UpdateSummaryRequest(BaseModel):
    summary: str


@router.patch("/{campaign_id}/scenes/{scene_id}/summary")
def update_scene_summary(campaign_id: str, scene_id: str, req: UpdateSummaryRequest):
    """Update the confirmed summary text of a scene (confirmed or not)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    scene.confirmed_summary = req.summary
    scene.proposed_summary = req.summary
    store.save(scene)
    # Keep chronicle in sync
    if req.summary:
        _upsert_chronicle(campaign_id, scene.scene_number, req.summary)
    return _scene_dict(scene)


class EditTurnRequest(BaseModel):
    content: str


@router.patch("/{campaign_id}/scenes/{scene_id}/turns/{turn_index}")
def edit_scene_turn(campaign_id: str, scene_id: str, turn_index: int, req: EditTurnRequest):
    """Edit the content of any turn by index (0-based)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if turn_index < 0 or turn_index >= len(scene.turns):
        raise HTTPException(400, f"Turn index {turn_index} out of range (scene has {len(scene.turns)} turns)")
    if not req.content.strip():
        raise HTTPException(400, "Content cannot be empty")
    scene.turns[turn_index] = SceneTurn(role=scene.turns[turn_index].role, content=req.content.strip())
    store.save(scene)
    return _scene_dict(scene)


# ── Chronicle ──────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/chronicle")
def get_chronicle(campaign_id: str):
    return [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)]


@router.get("/{campaign_id}/recap")
def get_campaign_recap(campaign_id: str, limit: int = 12, kind: str = "all"):
    _require_campaign(campaign_id)
    chronicle_entries = _chronicle().get_all(campaign_id)
    action_logs = _action_logs().get_recent(campaign_id, n=max(1, limit * 2))
    events = _events().get_all(campaign_id)
    items = _build_campaign_recap_items(
        chronicle_entries=chronicle_entries,
        action_logs=action_logs,
        events=events,
        limit=max(1, min(int(limit or 12), 50)),
        kind=str(kind or "all").strip().lower() or "all",
    )
    return {
        "items": items,
        "summary": _summarize_campaign_recap(items),
    }


class UpdateChronicleRequest(BaseModel):
    content: str


@router.patch("/{campaign_id}/chronicle/{entry_id}")
def update_chronicle_entry(campaign_id: str, entry_id: str, req: UpdateChronicleRequest):
    """Edit the text of a chronicle entry."""
    store = _chronicle()
    entry = store.get(entry_id)
    if not entry or entry.campaign_id != campaign_id:
        raise HTTPException(404, "Chronicle entry not found")
    updated = store.update_content(entry_id, req.content)
    return _chronicle_dict(updated)


@router.delete("/{campaign_id}/chronicle/{entry_id}", status_code=204)
def delete_chronicle_entry(campaign_id: str, entry_id: str):
    """Delete a chronicle entry."""
    store = _chronicle()
    entry = store.get(entry_id)
    if not entry or entry.campaign_id != campaign_id:
        raise HTTPException(404, "Chronicle entry not found")
    store.delete(entry_id)


_COMPRESS_SYSTEM = """You are a chronicle compressor. You will receive several chronicle entries from a roleplay campaign.
Your ONLY job is to condense them into a single shorter summary.

CRITICAL RULES:
- You are NOT a storyteller. Do NOT write fiction, narration, or creative prose.
- The events described are FINISHED AND FIXED — do not add, extend, or continue them.
- Every fact in your output MUST come directly from the provided entries. Do NOT invent new events, dialogue, characters, or outcomes.
- Do NOT speculate about what might happen next.
- Do NOT embellish or add atmosphere beyond what is stated.

Write in past tense. Be concise but complete. Preserve all essential plot points, character developments, and consequences.
Return only the merged summary text — no preamble, no labels, no commentary."""


@router.post("/{campaign_id}/chronicle/compress")
def compress_chronicle(campaign_id: str, req: UpdateChronicleRequest):
    """
    AI-assisted chronicle compression.
    The client sends the IDs of entries to merge as a newline-separated list in req.content.
    Returns { "summary": "..." } for the client to confirm before replacing.
    """
    import json as _json
    import httpx

    entry_ids: list[str] = [line.strip() for line in req.content.splitlines() if line.strip()]
    if len(entry_ids) < 2:
        raise HTTPException(400, "Need at least 2 entry IDs to compress")

    store = _chronicle()
    entries = [store.get(eid) for eid in entry_ids]
    entries = [e for e in entries if e and e.campaign_id == campaign_id]
    if len(entries) < 2:
        raise HTTPException(400, "Could not find at least 2 valid entries for this campaign")

    entries_sorted = sorted(entries, key=lambda e: e.scene_range_start)
    combined = "\n\n".join(
        f"[Scene {e.scene_range_start}] {e.content}" for e in entries_sorted
    )

    campaign = _campaigns().get(campaign_id)
    model = (getattr(campaign, "summary_model_name", None) if campaign else None) \
            or (campaign.model_name if campaign else None) \
            or config.ollama_model

    user_prompt = (
        f"Below are {len(entries_sorted)} chronicle entries covering "
        f"Scenes {entries_sorted[0].scene_range_start}–{entries_sorted[-1].scene_range_end}.\n"
        "Condense them into a single shorter summary. Do NOT add any new events, characters, or outcomes.\n\n"
        f"{combined}\n\n"
        "--- END OF ENTRIES ---\n\n"
        "Write the condensed summary now, using only the events stated above:"
    )

    import re as _re
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": 512, "num_ctx": 4096},
        }
        resp = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=180.0,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        summary = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()
    except Exception as e:
        raise HTTPException(503, f"AI compression failed: {e}")

    # Apply: replace all selected entries with one merged entry
    start = entries_sorted[0].scene_range_start
    end = entries_sorted[-1].scene_range_end
    for e in entries_sorted:
        store.delete(e.id)
    merged = ChronicleEntry(
        campaign_id=campaign_id,
        scene_range_start=start,
        scene_range_end=end,
        content=summary,
        confirmed=True,
    )
    store.save(merged)
    return _chronicle_dict(merged)


# ── Export & Backup ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/export/markdown")
def export_campaign_markdown(campaign_id: str):
    """Export the full campaign as a formatted Markdown document (download)."""
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    pc     = _pcs().get(campaign_id)
    facts  = _facts().get_all(campaign_id)
    places = _places().get_all(campaign_id)
    npcs   = _npcs().get_all(campaign_id)
    threads = _threads().get_all(campaign_id)
    factions = _factions().get_all(campaign_id)
    scenes = _scenes().get_all(campaign_id)
    chronicle = _chronicle().get_all(campaign_id)
    sg = c.style_guide

    lines: list[str] = []
    lines.append(f"# {c.name}")
    lines.append(f"*Exported {datetime.now(UTC).strftime('%Y-%m-%d')}*\n")

    if sg.prose_style or sg.tone:
        lines.append("## Style")
        if sg.prose_style: lines.append(f"- **Style:** {sg.prose_style}")
        if sg.tone:        lines.append(f"- **Tone:** {sg.tone}")
        lines.append("")

    if facts:
        lines.append("## World Facts")
        for f in facts:
            prefix = f"**[{f.category.upper()}]** " if f.category else ""
            lines.append(f"- {prefix}{f.content}")
        lines.append("")

    if sg.magic_system:
        lines.append("## Magic / Technology")
        lines.append(sg.magic_system)
        lines.append("")

    if pc and pc.name:
        lines.append(f"## Player Character: {pc.name}")
        for label, val in [("Appearance", pc.appearance), ("Personality", pc.personality),
                            ("Background", pc.background), ("Wants", pc.wants), ("Fears", pc.fears)]:
            if val: lines.append(f"**{label}:** {val}")
        if pc.dev_log:
            lines.append("\n### Development Log")
            for e in pc.dev_log:
                prefix = f"Scene {e.scene_number}: " if e.scene_number else ""
                lines.append(f"- {prefix}{e.note}")
        lines.append("")

    if npcs:
        lines.append("## NPCs")
        for n in npcs:
            status = f" [{n.status.upper()}]" if n.status and n.status != "active" else ""
            lines.append(f"### {n.name}{status}")
            for label, val in [("Role", n.role), ("Personality", n.personality),
                                ("Relationship to player", n.relationship_to_player),
                                ("Current state", n.current_state)]:
                if val: lines.append(f"**{label}:** {val}")
        lines.append("")

    if places:
        lines.append("## Places")
        for p in places:
            lines.append(f"### {p.name}")
            if p.description:   lines.append(p.description)
            if p.current_state: lines.append(f"*Currently: {p.current_state}*")
        lines.append("")

    if factions:
        lines.append("## Factions")
        for f in factions:
            lines.append(f"### {f.name}")
            if f.description:          lines.append(f.description)
            if f.goals:                lines.append(f"**Goals:** {f.goals}")
            if f.standing_with_player: lines.append(f"**Standing:** {f.standing_with_player}")
        lines.append("")

    if threads:
        lines.append("## Narrative Threads")
        for t in threads:
            status_str = f" [{t.status.value.upper()}]" if hasattr(t.status, "value") else ""
            lines.append(f"### {t.title}{status_str}")
            if t.description: lines.append(t.description)
            if t.resolution:  lines.append(f"*Resolution: {t.resolution}*")
        lines.append("")

    if chronicle:
        lines.append("## Chronicle")
        for e in sorted(chronicle, key=lambda x: x.scene_range_start):
            label = (f"Scene {e.scene_range_start}" if e.scene_range_start == e.scene_range_end
                     else f"Scenes {e.scene_range_start}–{e.scene_range_end}")
            lines.append(f"**[{label}]** {e.content}")
        lines.append("")

    if scenes:
        lines.append("## Scenes")
        for s in sorted(scenes, key=lambda x: x.scene_number):
            conf = " ✓" if s.confirmed else " (in progress)"
            lines.append(f"### Scene {s.scene_number}{conf}" + (f": {s.title}" if s.title else ""))
            if s.location:           lines.append(f"*Location: {s.location}*")
            if s.confirmed_summary:  lines.append(f"\n**Summary:** {s.confirmed_summary}")
            if s.turns:
                lines.append("")
                for t in s.turns:
                    speaker = "**Player**" if t.role == "user" else "**Narrator**"
                    lines.append(f"{speaker}: {t.content}\n")
        lines.append("")

    if c.notes:
        lines.append("## Player Notes")
        lines.append(c.notes)

    md = "\n".join(lines)
    filename = f"{c.name.replace(' ', '_')}_export.md"
    return _Response(content=md.encode("utf-8"), media_type="text/markdown",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{campaign_id}/export/json")
def export_campaign_json(campaign_id: str):
    """Export the full campaign as a JSON backup (download)."""
    import json as _json
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    data = {
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "campaign": _campaign_dict(c),
        "player_character": _pc_dict(_pcs().get(campaign_id)),
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
        "objectives": [_objective_dict(objective) for objective in _objectives().get_all(campaign_id)],
        "quests": [_quest_dict(quest) for quest in _quests().get_all(campaign_id)],
        "events": [_campaign_event_dict(event) for event in _events().get_all(campaign_id)],
        "scenes": [_scene_dict(s) for s in _scenes().get_all(campaign_id)],
        "chronicle": [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)],
    }
    payload = _json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"{c.name.replace(' ', '_')}_backup.json"
    return _Response(content=payload.encode("utf-8"), media_type="application/json",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class ImportCampaignRequest(BaseModel):
    data: dict              # full JSON backup as parsed object
    campaign_name: Optional[str] = None   # override the auto-generated name


@router.get("/{campaign_id}/export/template")
def export_campaign_template(campaign_id: str):
    """Export world document only (no scenes/chronicle) as a shareable template file."""
    import json as _json
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    data = {
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "campaign": {k: v for k, v in _campaign_dict(c).items() if k != "notes"},
        "player_character": _pc_dict(_pcs().get(campaign_id)),
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
    }
    payload = _json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"{c.name.replace(' ', '_')}_template.json"
    return _Response(content=payload.encode("utf-8"), media_type="application/json",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import", status_code=201)
def import_campaign(req: ImportCampaignRequest):
    """Restore a campaign from a JSON backup. Creates a new campaign with a new ID."""
    import json as _json
    d = req.data
    if d.get("version") != 1:
        raise HTTPException(400, "Unsupported backup version")

    orig = d.get("campaign", {})
    sg_dict = orig.get("style_guide", {})
    sg = StyleGuide(
        prose_style=sg_dict.get("prose_style", ""),
        tone=sg_dict.get("tone", ""),
        themes=sg_dict.get("themes", []),
        magic_system=sg_dict.get("magic_system", ""),
        avoids=sg_dict.get("avoids", ""),
    )
    if req.campaign_name:
        new_name = req.campaign_name
    else:
        new_name = orig.get("name", "Imported Campaign") + " (restored)"
    c = _campaigns().create(name=new_name, model_name=orig.get("model_name"), style_guide=sg)
    if orig.get("notes"):
        _campaigns().update(c.id, notes=orig["notes"])
    cid = c.id
    now = datetime.now(UTC).replace(tzinfo=None)

    # ID remapping so cross-references stay consistent
    npc_id_map: dict[str, str] = {}

    pc_data = d.get("player_character") or {}
    if pc_data.get("name"):
        _pcs().save(PlayerCharacter(
            campaign_id=cid, name=pc_data["name"],
            appearance=pc_data.get("appearance", ""), personality=pc_data.get("personality", ""),
            background=pc_data.get("background", ""), wants=pc_data.get("wants", ""),
            fears=pc_data.get("fears", ""), how_seen=pc_data.get("how_seen", ""),
        ))

    for f in d.get("world_facts", []):
        if f.get("content"):
            from app.core.models import CampaignWorldFact
            _facts().save(CampaignWorldFact(
                campaign_id=cid, content=f["content"],
                category=f.get("category", ""), fact_order=f.get("fact_order", 0),
            ))

    for p in d.get("places", []):
        if p.get("name"):
            _places().save(CampaignPlace(campaign_id=cid, name=p["name"],
                description=p.get("description", ""), current_state=p.get("current_state", ""),
                created_at=now))

    for n in d.get("npcs", []):
        if n.get("name"):
            new_npc = NpcCard(campaign_id=cid, name=n["name"],
                appearance=n.get("appearance", ""), personality=n.get("personality", ""),
                role=n.get("role", ""), relationship_to_player=n.get("relationship_to_player", ""),
                current_location=n.get("current_location", ""),
                current_state=n.get("current_state", ""),
                status=NpcStatus(n["status"]) if n.get("status") else NpcStatus.ACTIVE,
                status_reason=n.get("status_reason", ""), secrets=n.get("secrets", ""),
                short_term_goal=n.get("short_term_goal", ""),
                long_term_goal=n.get("long_term_goal", ""), created_at=now)
            _npcs().save(new_npc)
            npc_id_map[n["id"]] = new_npc.id

    for r in d.get("npc_relationships", []):
        a = npc_id_map.get(r.get("npc_id_a", ""))
        b = npc_id_map.get(r.get("npc_id_b", ""))
        if a and b:
            _npc_relationships().save(NpcRelationship(
                campaign_id=cid, npc_id_a=a, npc_id_b=b,
                dynamic=r.get("dynamic", ""), trust=r.get("trust", ""),
                hostility=r.get("hostility", ""), history=r.get("history", ""),
                created_at=now))

    for t in d.get("threads", []):
        if t.get("title"):
            _threads().save(NarrativeThread(campaign_id=cid, title=t["title"],
                description=t.get("description", ""),
                status=ThreadStatus(t["status"]) if t.get("status") else ThreadStatus.ACTIVE,
                resolution=t.get("resolution", ""), created_at=now))

    for f in d.get("factions", []):
        if f.get("name"):
            _factions().save(CampaignFaction(campaign_id=cid, name=f["name"],
                description=f.get("description", ""), goals=f.get("goals", ""),
                methods=f.get("methods", ""),
                standing_with_player=f.get("standing_with_player", ""),
                relationship_notes=f.get("relationship_notes", ""), created_at=now))

    for objective in d.get("objectives", []):
        if objective.get("title"):
            _objectives().save(CampaignObjective(
                campaign_id=cid,
                title=objective["title"],
                description=objective.get("description", ""),
                status=ObjectiveStatus(objective.get("status", "active")),
                created_at=now,
                updated_at=now,
            ))

    for quest in d.get("quests", []):
        if quest.get("title"):
            stages = [
                QuestStage(
                    description=stage.get("description", ""),
                    completed=bool(stage.get("completed", False)),
                    order=int(stage.get("order", 0)),
                )
                for stage in quest.get("stages", [])
                if stage.get("description")
            ]
            _quests().save(CampaignQuest(
                campaign_id=cid,
                title=quest["title"],
                description=quest.get("description", ""),
                status=QuestStatus(quest.get("status", "active")),
                giver_npc_name=quest.get("giver_npc_name", ""),
                location_name=quest.get("location_name", ""),
                reward_notes=quest.get("reward_notes", ""),
                importance=ImportanceLevel(quest.get("importance", "medium")),
                stages=stages,
                tags=quest.get("tags", []),
                created_at=now,
                updated_at=now,
            ))

    for event in d.get("events", []):
        if event.get("title"):
            _events().save(CampaignEvent(
                campaign_id=cid,
                event_type=event.get("event_type", "world"),
                title=event["title"],
                content=event.get("content", ""),
                details=event.get("details", {}),
                world_time_hours=int(event.get("world_time_hours", 0) or 0),
                status=CampaignEventStatus(event.get("status", "pending")),
                created_at=now,
                updated_at=now,
            ))

    for s in d.get("scenes", []):
        npc_ids = [npc_id_map.get(nid, nid) for nid in s.get("npc_ids", [])]
        turns = [SceneTurn(role=t["role"], content=t["content"]) for t in s.get("turns", [])]
        scene = CampaignScene(campaign_id=cid, scene_number=s.get("scene_number", 1),
            title=s.get("title", ""), location=s.get("location", ""),
            npc_ids=npc_ids, intent=s.get("intent", ""), tone=s.get("tone", ""),
            turns=turns, proposed_summary=s.get("proposed_summary", ""),
            confirmed_summary=s.get("confirmed_summary", ""),
            confirmed=s.get("confirmed", False),
            allow_unselected_npcs=s.get("allow_unselected_npcs", False))
        _scenes().save(scene)

    for e in d.get("chronicle", []):
        if e.get("content"):
            _chronicle().save(ChronicleEntry(campaign_id=cid,
                scene_range_start=e.get("scene_range_start", 0),
                scene_range_end=e.get("scene_range_end", 0),
                content=e["content"], confirmed=e.get("confirmed", True)))

    return {"campaign_id": cid, "name": new_name}


# ── Campaign Statistics ────────────────────────────────────────────────────────

@router.get("/{campaign_id}/stats")
def get_campaign_stats(campaign_id: str):
    """Return aggregate statistics for a campaign."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    scenes_all  = _scenes().get_all(campaign_id)
    npcs_all    = _npcs().get_all(campaign_id)
    threads_all = _threads().get_all(campaign_id)
    facts_all   = _facts().get_all(campaign_id)
    chronicle   = _chronicle().get_all(campaign_id)

    confirmed_scenes = [s for s in scenes_all if s.confirmed]
    active_scenes    = [s for s in scenes_all if not s.confirmed]

    # Word counts
    total_words = sum(
        len(t.content.split())
        for s in scenes_all for t in s.turns
    )
    player_words = sum(
        len(t.content.split())
        for s in scenes_all for t in s.turns if t.role == "user"
    )
    narrator_words = total_words - player_words

    # NPC usage — count scenes each NPC appears in
    npc_counts: dict[str, int] = {}
    for s in scenes_all:
        for nid in s.npc_ids:
            npc_counts[nid] = npc_counts.get(nid, 0) + 1
    npc_name_map = {n.id: n.name for n in npcs_all}
    top_npcs = sorted(
        [{"name": npc_name_map.get(k, k), "scene_count": v} for k, v in npc_counts.items()],
        key=lambda x: -x["scene_count"]
    )[:5]

    # Thread stats
    resolved = sum(1 for t in threads_all if hasattr(t.status, "value") and t.status.value == "resolved")
    active_t = sum(1 for t in threads_all if hasattr(t.status, "value") and t.status.value == "active")
    resolution_rate = round(resolved / len(threads_all) * 100) if threads_all else 0

    return {
        "scenes_total": len(scenes_all),
        "scenes_confirmed": len(confirmed_scenes),
        "scenes_active": len(active_scenes),
        "total_turns": sum(len(s.turns) for s in scenes_all),
        "total_words": total_words,
        "player_words": player_words,
        "narrator_words": narrator_words,
        "npc_count": len(npcs_all),
        "top_npcs": top_npcs,
        "thread_count": len(threads_all),
        "threads_resolved": resolved,
        "threads_active": active_t,
        "thread_resolution_rate": resolution_rate,
        "world_fact_count": len(facts_all),
        "chronicle_entries": len(chronicle),
    }


# ── Scene / turn search ────────────────────────────────────────────────────────

@router.get("/{campaign_id}/search")
def search_turns(campaign_id: str, q: str = "", limit: int = 30):
    """Full-text search across all scene turns. Returns matching excerpts."""
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    scenes = _scenes().get_all(campaign_id)
    results: list[dict] = []
    for s in scenes:
        for i, t in enumerate(s.turns):
            if q_lower in t.content.lower():
                # Find position for excerpt
                pos = t.content.lower().find(q_lower)
                start = max(0, pos - 60)
                end = min(len(t.content), pos + len(q) + 60)
                excerpt = ("…" if start > 0 else "") + t.content[start:end] + ("…" if end < len(t.content) else "")
                results.append({
                    "scene_id": s.id,
                    "scene_number": s.scene_number,
                    "scene_title": s.title,
                    "turn_index": i,
                    "role": t.role,
                    "excerpt": excerpt,
                    "match_pos": pos - start,
                    "match_len": len(q),
                })
                if len(results) >= limit:
                    return results
    return results


# ── Campaign Templates ─────────────────────────────────────────────────────────

class SaveTemplateRequest(BaseModel):
    name: str


@router.post("/{campaign_id}/save-as-template", status_code=201)
def save_as_template(campaign_id: str, req: SaveTemplateRequest):
    """
    Clone the world document of this campaign as a new campaign (template).
    Scenes, chronicle, and player notes are NOT copied — only world facts,
    NPCs, places, threads, factions, and style guide.
    """
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    template = _campaigns().create(
        name=req.name,
        model_name=c.model_name,
        style_guide=c.style_guide,
    )
    tid = template.id
    now = datetime.now(UTC).replace(tzinfo=None)

    pc = _pcs().get(campaign_id)
    if pc and pc.name:
        _pcs().save(PlayerCharacter(campaign_id=tid, name=pc.name,
            appearance=pc.appearance, personality=pc.personality,
            background=pc.background, wants=pc.wants, fears=pc.fears,
            how_seen=pc.how_seen))

    npc_id_map: dict[str, str] = {}
    for n in _npcs().get_all(campaign_id):
        new_n = NpcCard(campaign_id=tid, name=n.name, appearance=n.appearance,
            personality=n.personality, role=n.role,
            relationship_to_player=n.relationship_to_player,
            current_location=n.current_location, current_state=n.current_state,
            status=n.status, secrets=n.secrets,
            short_term_goal=n.short_term_goal, long_term_goal=n.long_term_goal,
            created_at=now)
        _npcs().save(new_n)
        npc_id_map[n.id] = new_n.id

    for r in _npc_relationships().get_all(campaign_id):
        a = npc_id_map.get(r.npc_id_a)
        b = npc_id_map.get(r.npc_id_b)
        if a and b:
            _npc_relationships().save(NpcRelationship(
                campaign_id=tid, npc_id_a=a, npc_id_b=b,
                dynamic=r.dynamic, trust=r.trust, hostility=r.hostility,
                history=r.history, created_at=now))

    for p in _places().get_all(campaign_id):
        _places().save(CampaignPlace(campaign_id=tid, name=p.name,
            description=p.description, current_state=p.current_state, created_at=now))

    for t in _threads().get_all(campaign_id):
        _threads().save(NarrativeThread(campaign_id=tid, title=t.title,
            description=t.description, status=t.status,
            resolution=t.resolution, created_at=now))

    for f in _factions().get_all(campaign_id):
        _factions().save(CampaignFaction(campaign_id=tid, name=f.name,
            description=f.description, goals=f.goals, methods=f.methods,
            standing_with_player=f.standing_with_player,
            relationship_notes=f.relationship_notes, created_at=now))

    from app.core.models import CampaignWorldFact
    for f in _facts().get_all(campaign_id):
        _facts().save(CampaignWorldFact(campaign_id=tid, content=f.content,
            category=f.category, fact_order=f.fact_order))

    return {"campaign_id": tid, "name": req.name}


# ── Image storage ─────────────────────────────────────────────────────────────

class SaveImageRequest(BaseModel):
    data_url: str


@router.patch("/{campaign_id}/cover-image", status_code=204)
def save_campaign_cover_image(campaign_id: str, req: SaveImageRequest):
    """Save a generated image as the campaign cover."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    _campaigns().update(campaign_id, cover_image=req.data_url)


@router.patch("/{campaign_id}/player-character/portrait", status_code=204)
def save_pc_portrait(campaign_id: str, req: SaveImageRequest):
    """Save a generated or uploaded image as the player character portrait."""
    pc = _pcs().get(campaign_id)
    if not pc:
        raise HTTPException(404, "Player character not found")
    pc.portrait_image = req.data_url
    _pcs().save(pc)


@router.patch("/{campaign_id}/npcs/{npc_id}/portrait", status_code=204)
def save_npc_portrait(campaign_id: str, npc_id: str, req: SaveImageRequest):
    """Save a generated image as an NPC portrait."""
    npc = _npcs().get(npc_id)
    if not npc or npc.campaign_id != campaign_id:
        raise HTTPException(404, "NPC not found")
    from app.core.models import NpcDevEntry as _NDE  # noqa: avoid circular at module level
    npc.portrait_image = req.data_url
    _npcs().save(npc)


_CARD_IMPORT_SYSTEM = """You are a campaign integration assistant for collaborative roleplay.

You are given an existing campaign's world document and a SillyTavern-format character card.
Your job is to:
1. Convert the character card into an NPC that fits this campaign's world
2. Identify contradictions between the card and the world (e.g. references to modern technology in a fantasy world, place names that don't exist, anachronistic elements)
3. Suggest world-appropriate alternatives for each contradiction

Output ONLY valid JSON with exactly this structure (no markdown fences, no extra text):
{
  "proposed_npc": {
    "name": "Character name from card",
    "gender": "inferred gender",
    "age": "inferred age or age range",
    "appearance": "physical description adapted to the world",
    "personality": "personality from card",
    "role": "their role in this world",
    "relationship_to_player": "how they might relate to the player character",
    "current_location": "a world-appropriate location",
    "current_state": "their current situation",
    "short_term_goal": "what they want right now",
    "long_term_goal": "their deeper ambition"
  },
  "contradictions": [
    {
      "field": "which NPC field is affected (e.g. 'current_location', 'appearance', 'role')",
      "issue": "description of the contradiction",
      "original": "the original value from the card",
      "suggested": "the world-appropriate alternative"
    }
  ]
}

If there are no contradictions, return an empty array for contradictions.
Keep all text fields concise (1-2 sentences each).
Output ONLY the JSON — no commentary before or after."""


class ImportCardRequest(BaseModel):
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    creator_notes: str = ""
    additional_context: str = ""
    model_name: Optional[str] = None


class GenerateNpcRequest(BaseModel):
    description: str        # free-text intent from the player
    model_name: Optional[str] = None


@router.post("/{campaign_id}/npcs/import-card")
def import_npc_from_card(campaign_id: str, req: ImportCardRequest):
    """Analyse a character card against the campaign world and return a proposed NPC + contradictions."""
    import json as _json
    _require_campaign(campaign_id)
    from app.campaigns.world_builder import _ollama_generate, _extract_json

    # Build world context from DB
    facts = _facts().get_all(campaign_id)
    world_parts: list[str] = []
    if facts:
        world_parts.append("WORLD FACTS:\n" + "\n".join(f"- {f.content}" for f in facts[:15]))
    existing_npcs = _npcs().get_all(campaign_id)
    if existing_npcs:
        world_parts.append("EXISTING NPCS: " + ", ".join(n.name for n in existing_npcs[:20]))
    factions = _factions().get_all(campaign_id)
    if factions:
        world_parts.append("FACTIONS:\n" + "\n".join(f"- {f.name}: {f.description}" for f in factions))
    world_context = "\n\n".join(world_parts) or "No world document established yet."

    # Build card text
    card_parts = [f"NAME: {req.name}"]
    if req.description:
        card_parts.append(f"DESCRIPTION:\n{req.description[:800]}")
    if req.personality:
        card_parts.append(f"PERSONALITY:\n{req.personality[:400]}")
    if req.scenario:
        card_parts.append(f"SCENARIO:\n{req.scenario[:400]}")
    if req.creator_notes:
        card_parts.append(f"CREATOR NOTES:\n{req.creator_notes[:300]}")
    if req.additional_context:
        card_parts.append(f"ADDITIONAL CONTEXT:\n{req.additional_context}")
    card_text = "\n\n".join(card_parts)

    prompt = (
        f"CAMPAIGN WORLD DOCUMENT:\n{world_context}\n\n"
        f"CHARACTER CARD TO IMPORT:\n{card_text}\n\n"
        f"Analyse this card for contradictions with the campaign world and return the integration JSON."
    )

    model = req.model_name or config.ollama_model
    try:
        raw = _ollama_generate(
            config.ollama_base_url, model,
            system=_CARD_IMPORT_SYSTEM,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.3,
        )
    except Exception as e:
        raise HTTPException(503, f"AI unavailable: {e}")

    data = _extract_json(raw)
    if not data or "proposed_npc" not in data:
        raise HTTPException(500, "AI did not return valid analysis. Try a different model or try again.")

    return {
        "proposed_npc": data.get("proposed_npc", {}),
        "contradictions": data.get("contradictions", []),
    }


_GENERATE_NPC_SYSTEM = """You are a character creation assistant for collaborative roleplay.

You are given a campaign world document and a player's description of an NPC they want to create.
Your job is to flesh out all fields for this NPC, staying true to the player's intent and consistent with the world.

Output ONLY valid JSON with exactly this structure (no markdown fences, no extra text):
{
  "name": "Character name",
  "gender": "gender",
  "age": "age or age range (e.g. 'mid-30s', '60s', 'young adult')",
  "appearance": "physical description in 1-2 sentences",
  "personality": "core personality traits in 1-2 sentences",
  "role": "their role or occupation in the world",
  "relationship_to_player": "how they might relate to the player character",
  "current_location": "where they currently are",
  "current_state": "their current situation or mood",
  "short_term_goal": "what they want right now",
  "long_term_goal": "their deeper ambition or life goal",
  "secrets": "something they are hiding (optional, can be empty string)"
}

Rules:
- Honour EVERY detail the player specified — do not contradict their description
- Fill in only what the player left unspecified
- Keep all fields concise (1-2 sentences)
- Make the character internally consistent and fitting for the world
- Output ONLY the JSON object — no commentary before or after"""


@router.post("/{campaign_id}/npcs/generate")
def generate_npc(campaign_id: str, req: GenerateNpcRequest):
    """Generate a fully-populated NPC from a player's free-text description."""
    _require_campaign(campaign_id)
    from app.campaigns.world_builder import _ollama_generate, _extract_json

    # Build world context
    facts = _facts().get_all(campaign_id)
    world_parts: list[str] = []
    if facts:
        world_parts.append("WORLD FACTS:\n" + "\n".join(f"- {f.content}" for f in facts[:15]))
    existing_npcs = _npcs().get_all(campaign_id)
    if existing_npcs:
        world_parts.append("EXISTING NPCS: " + ", ".join(n.name for n in existing_npcs[:20]))
    factions = _factions().get_all(campaign_id)
    if factions:
        world_parts.append("FACTIONS:\n" + "\n".join(f"- {f.name}: {f.description}" for f in factions))
    world_context = "\n\n".join(world_parts) or "No world document established yet."

    prompt = (
        f"CAMPAIGN WORLD:\n{world_context}\n\n"
        f"PLAYER'S NPC DESCRIPTION:\n{req.description.strip()}\n\n"
        f"Generate the complete NPC JSON now."
    )

    model = req.model_name or config.ollama_model
    try:
        raw = _ollama_generate(
            config.ollama_base_url, model,
            system=_GENERATE_NPC_SYSTEM,
            prompt=prompt,
            max_tokens=1024,
            temperature=0.7,
        )
    except Exception as e:
        raise HTTPException(503, f"AI unavailable: {e}")

    data = _extract_json(raw)
    if not data or "name" not in data:
        raise HTTPException(500, "AI did not return a valid NPC. Try again or use a different model.")

    return data


@router.patch("/{campaign_id}/scenes/{scene_id}/scene-image", status_code=204)
def save_scene_image(campaign_id: str, scene_id: str, req: SaveImageRequest):
    """Save a generated image as the scene illustration."""
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    scene.scene_image = req.data_url
    _scenes().save(scene)


# ── Image Prompt Generation ────────────────────────────────────────────────────

_IMG_PROMPT_SYSTEM = (
    "You are an expert Stable Diffusion prompt engineer.\n\n"
    "Your task: write a vivid SD image generation prompt based on the provided context.\n\n"
    "CRITICAL: Do NOT show any thinking, reasoning steps, planning, or explanation. "
    "Output ONLY the final raw prompt text and nothing else.\n\n"
    "Rules:\n"
    "- Comma-separated descriptive tags and short phrases\n"
    "- Lead with subject/composition (e.g. 'lone mage on a clifftop, stormy sky')\n"
    "- Include physical descriptions of each character present: gender, apparent age, hair colour, clothing, expression, pose\n"
    "  If gender or age are not explicitly stated, make a reasonable visual guess based on context\n"
    "- ALWAYS specify the character's gender and apparent age (e.g. 'young woman', 'middle-aged man', 'elderly elf female')\n"
    "- Include environment, lighting, mood, atmosphere\n"
    "- Do NOT include style tags — the user will add those separately\n"
    "- Do NOT include negative prompt syntax\n"
    "- Under 160 words total\n"
    "- Output ONLY the raw prompt text — no labels, no preamble, no explanation, no markdown"
)


class ImagePromptRequest(BaseModel):
    source_type: str          # "campaign" | "scene" | "chat" | "npc"
    scene_id: Optional[str] = None
    npc_id: Optional[str] = None
    model_name: Optional[str] = None
    last_message: Optional[str] = None   # for "chat" type — the last AI response text


@router.post("/{campaign_id}/image-prompt")
def generate_image_prompt(campaign_id: str, req: ImagePromptRequest):
    """Ask the LLM to produce a Stable Diffusion optimised prompt from campaign context."""
    import json as _json
    import httpx

    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    parts: list[str] = []

    if req.source_type == "campaign":
        facts = _facts().get_all(campaign_id)
        world_text = "\n".join(f"- {f.content}" for f in facts[:10] if f.content)
        pc = _pcs().get(campaign_id)
        pc_text = (
            f"{pc.name}: {pc.appearance}".strip()
            if pc and pc.name and pc.appearance else
            (pc.name if pc and pc.name else "")
        )
        sg = c.style_guide
        parts = [
            f"TYPE: Campaign cover image",
            f"CAMPAIGN NAME: {c.name}",
            f"WORLD DOCUMENT:\n{world_text}" if world_text else "",
            f"PLAYER CHARACTER: {pc_text}" if pc_text else "",
            f"TONE / THEMES: {sg.tone}" if sg and sg.tone else "",
            "",
            "Create a cinematic cover image prompt that captures the world's essence and atmosphere.",
        ]

    elif req.source_type == "scene":
        if not req.scene_id:
            raise HTTPException(400, "scene_id required for scene image")
        scene = _scenes().get(req.scene_id)
        if not scene:
            raise HTTPException(404, "Scene not found")
        npc_lines = []
        for nid in (scene.npc_ids or []):
            npc = _npcs().get(nid)
            if npc:
                meta = ", ".join(p for p in [npc.gender, npc.age] if p)
                desc = f"{npc.name}"
                if meta:
                    desc += f" [{meta}]"
                if npc.role:
                    desc += f" ({npc.role})"
                if npc.appearance:
                    desc += f": {npc.appearance[:120]}"
                npc_lines.append(desc)
        pc = _pcs().get(campaign_id)
        pc_text = (
            f"{pc.name}: {pc.appearance[:120]}".strip()
            if pc and pc.name and pc.appearance else
            (pc.name if pc and pc.name else "")
        )
        summary = scene.confirmed_summary or scene.proposed_summary or ""
        parts = [
            "TYPE: Scene illustration",
            f"LOCATION: {scene.location or 'unknown'}",
            f"SCENE TITLE: {scene.title}" if scene.title else "",
            f"SCENE SUMMARY: {summary[:400]}" if summary else "",
            f"SCENE INTENT: {scene.intent[:200]}" if scene.intent else "",
            f"TONE: {scene.tone}" if scene.tone else "",
            "NPCs PRESENT:\n" + "\n".join(f"  - {n}" for n in npc_lines) if npc_lines else "",
            f"PLAYER CHARACTER: {pc_text}" if pc_text else "",
            "",
            "Create an evocative scene illustration prompt that captures this moment in the story.",
        ]

    elif req.source_type == "chat":
        if not req.last_message:
            raise HTTPException(400, "last_message required for chat image")
        scene = _scenes().get(req.scene_id) if req.scene_id else None
        location = (scene.location if scene else None) or "unknown"
        parts = [
            "TYPE: In-story illustration",
            f"LOCATION: {location}",
            "",
            "LAST NARRATIVE TEXT (verbatim):",
            req.last_message[:600],
            "",
            "Create an illustration prompt for exactly this story moment — the characters, action, and atmosphere described above.",
        ]

    elif req.source_type == "pc":
        pc = _pcs().get(campaign_id)
        if not pc:
            raise HTTPException(404, "Player character not found")
        parts = [
            "TYPE: Player character portrait",
            f"NAME: {pc.name}",
            f"APPEARANCE: {pc.appearance}" if pc.appearance else "",
            f"PERSONALITY (for expression clues): {pc.personality[:200]}" if pc.personality else "",
            f"BACKGROUND: {pc.background[:200]}" if pc.background else "",
            f"WANTS: {pc.wants}" if pc.wants else "",
            f"FEARS: {pc.fears}" if pc.fears else "",
            "",
            "Create a character portrait prompt for the player character. ALWAYS lead with gender and apparent age (infer from context if not stated). Emphasise face, expression, clothing, and distinctive visual traits.",
        ]

    elif req.source_type == "npc":
        if not req.npc_id:
            raise HTTPException(400, "npc_id required for character image")
        npc = _npcs().get(req.npc_id)
        if not npc:
            raise HTTPException(404, "NPC not found")
        parts = [
            "TYPE: Character portrait",
            f"NAME: {npc.name}",
            f"GENDER: {npc.gender}" if npc.gender else "GENDER: unspecified — infer from name/context",
            f"AGE: {npc.age}" if npc.age else "AGE: unspecified — make a reasonable visual guess",
            f"ROLE: {npc.role}" if npc.role else "",
            f"APPEARANCE: {npc.appearance}" if npc.appearance else "",
            f"PERSONALITY (for expression clues): {npc.personality[:200]}" if npc.personality else "",
            f"CURRENT STATE: {npc.current_state}" if npc.current_state else "",
            "",
            "Create a character portrait prompt. ALWAYS lead with the character's gender and apparent age. Emphasise face, expression, and distinctive visual traits.",
        ]

    else:
        raise HTTPException(400, f"Unknown source_type: {req.source_type!r}")

    context = "\n".join(p for p in parts if p)
    model = req.model_name or (c.model_name if c.model_name else config.ollama_model)

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _IMG_PROMPT_SYSTEM},
                {"role": "user", "content": context},
            ],
            "stream": False,
            "think": False,   # Qwen3 / QwQ: suppress chain-of-thought output
            "options": {"temperature": 0.75, "num_predict": 350},
        }
        resp = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            # Short connect timeout (localhost), generous read timeout for slow/cold models
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        resp.raise_for_status()
        import re as _re
        raw = resp.json()
        msg = raw.get("message", {})
        content = (msg.get("content") or "").strip()
        # Strip <think>…</think> blocks (DeepSeek-R1, Qwen3 with tags)
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        # Strip plain-text thinking preambles: paragraphs that start with
        # "Thinking", numbered steps, or bullet reasoning before the actual prompt.
        # The real SD prompt is comma-separated tags without markdown list markers.
        # Strategy: take everything after the last blank line that follows a
        # "step" / heading pattern, or just grab the last non-empty paragraph.
        if _re.search(r"(?m)^(Thinking|#+\s|\d+\.\s+\*\*)", content):
            # Split on double newlines and take the last non-empty block
            blocks = [b.strip() for b in _re.split(r"\n{2,}", content) if b.strip()]
            # Prefer the last block that looks like comma-separated tags (no list markers)
            for block in reversed(blocks):
                if not _re.match(r"^(\d+\.|\*|-|#)", block):
                    content = block
                    break
        # Some thinking models leave content empty and put the answer in message.thinking
        prompt_text = content or (msg.get("thinking") or "").strip()
        if not prompt_text:
            raise HTTPException(500,
                "The model returned an empty response. "
                "Try selecting a different model or ensure the model is fully loaded in Ollama.")
        return {"prompt": prompt_text}
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, (
            "Prompt generation timed out (model took >5 min). "
            "This usually means Ollama is loading a large model — wait a moment and try again, "
            "or select a smaller/faster model."
        ))
    except Exception as e:
        raise HTTPException(500, f"Prompt generation failed: {e}")


# ── World Builder ──────────────────────────────────────────────────────────────

@router.post("/world-builder/generate/stream")
def generate_world_stream(req: GenerateWorldRequest):
    """Stream world generation tokens. Client accumulates, then POSTs to /parse."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)

    def _stream():
        try:
            for chunk in wb.generate_stream(req.description):
                yield chunk
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/world-builder/generate")
def generate_world(req: GenerateWorldRequest):
    """Blocking world generation. Returns a WorldBuildResult JSON."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)
    try:
        result = wb.generate(req.description)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return result.model_dump()


@router.post("/world-builder/refine")
def refine_world(req: RefineWorldRequest):
    """Refine a specific section of a WorldBuildResult."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)
    current = _dict_to_world_build_result(req.current)
    try:
        result = wb.refine(current, req.section, req.instructions)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return result.model_dump()


@router.post("/world-builder/refine/stream")
def refine_world_stream(req: RefineWorldRequest):
    """Stream a section refinement. Client accumulates and parses JSON."""
    import json as _json
    import httpx
    from app.campaigns.world_builder import _REFINE_SYSTEM

    model = req.model_name or config.ollama_model
    current = _dict_to_world_build_result(req.current)
    current_json = _json.dumps(current.model_dump(mode="json"), indent=2, ensure_ascii=False)

    prompt = (
        f"Here is the current world document:\n\n"
        f"```json\n{current_json}\n```\n\n"
        f"The player wants to refine the '{req.section}' section:\n\n"
        f"{req.instructions.strip()}\n\n"
        f"Return the complete updated world document JSON."
    )

    def _stream():
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _REFINE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "think": False,
                "options": {"temperature": 0.75, "num_predict": 4096, "num_ctx": 8192},
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


class GenerateFromCardsRequest(BaseModel):
    cards: list[dict] = []
    lorebook_entries: list[dict] = []
    additional_details: str = ""
    model_name: Optional[str] = None


@router.post("/world-builder/from-cards/stream")
def generate_from_cards_stream(req: GenerateFromCardsRequest):
    """Stream world synthesis from character cards and lorebook entries."""
    from app.campaigns.world_builder import WorldBuilder
    model = req.model_name or config.ollama_model
    wb = WorldBuilder(base_url=config.ollama_base_url, model=model)

    def _stream():
        try:
            for chunk in wb.generate_from_cards_stream(
                req.cards, req.lorebook_entries, req.additional_details
            ):
                yield chunk
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/world-builder/confirm", status_code=201)
def confirm_world(req: ConfirmWorldRequest):
    """
    Persist a confirmed WorldBuildResult as a new Campaign with all sub-entities.
    Returns the created campaign id and summary counts.
    """
    world = _dict_to_world_build_result(req.world)
    sg = StyleGuide(
        prose_style=req.prose_style,
        tone=req.tone,
    )
    try:
        play_mode = PlayMode(req.play_mode)
    except ValueError:
        raise HTTPException(400, "Invalid play mode")
    store = _campaigns()
    campaign = store.create(
        name=req.campaign_name,
        model_name=req.model_name,
        style_guide=sg,
        play_mode=play_mode,
        system_pack=req.system_pack,
        feature_flags=req.feature_flags,
    )
    cid = campaign.id

    now = datetime.now(UTC).replace(tzinfo=None)

    # Player character
    pc_data = world.player_character
    if pc_data and pc_data.get("name"):
        _pcs().save(PlayerCharacter(
            campaign_id=cid,
            name=pc_data.get("name", "The Protagonist"),
            appearance=pc_data.get("appearance", ""),
            personality=pc_data.get("personality", ""),
            background=pc_data.get("background", ""),
            wants=pc_data.get("wants", ""),
            fears=pc_data.get("fears", ""),
        ))

    # World facts — premise goes first, then bullet facts
    all_fact_texts: list[str] = []
    if world.premise:
        all_fact_texts.append(world.premise)
    all_fact_texts.extend(world.world_facts)
    if all_fact_texts:
        _facts().replace_all(cid, all_fact_texts)

    # Places
    for place in world.places:
        if place.get("name"):
            _places().save(CampaignPlace(
                campaign_id=cid,
                name=place.get("name", ""),
                description=place.get("description", ""),
                current_state=place.get("current_state", ""),
                created_at=now,
            ))

    # NPCs
    for npc in world.npcs:
        if npc.get("name"):
            _npcs().save(NpcCard(
                campaign_id=cid,
                name=npc.get("name", ""),
                appearance=npc.get("appearance", ""),
                personality=npc.get("personality", ""),
                role=npc.get("role", ""),
                relationship_to_player=npc.get("relationship_to_player", ""),
                current_location=npc.get("current_location", ""),
                current_state=npc.get("current_state", ""),
                created_at=now,
            ))

    # Narrative threads
    for thread in world.narrative_threads:
        if thread.get("title"):
            _threads().save(NarrativeThread(
                campaign_id=cid,
                title=thread.get("title", ""),
                description=thread.get("description", ""),
                created_at=now,
            ))

    # Factions
    for faction in world.factions:
        if faction.get("name"):
            _factions().save(CampaignFaction(
                campaign_id=cid,
                name=faction.get("name", ""),
                description=faction.get("description", ""),
                goals=faction.get("goals", ""),
                methods=faction.get("methods", ""),
                created_at=now,
            ))

    return {
        "campaign_id": cid,
        "name": campaign.name,
        "play_mode": campaign.play_mode.value,
        "system_pack": campaign.system_pack,
        "counts": {
            "world_facts": len(world.world_facts) + (1 if world.premise else 0),
            "places": len(world.places),
            "npcs": len(world.npcs),
            "threads": len(world.narrative_threads),
            "factions": len(world.factions),
        },
    }


@router.post("/demo/d20-fantasy-core", status_code=201)
def create_d20_demo_campaign():
    import json
    from pathlib import Path

    demo_path = Path(config.db_path).parent / "demo" / "d20_fantasy_core_demo_campaign.json"
    if not demo_path.exists():
        raise HTTPException(404, "Demo campaign file not found")

    raw = json.loads(demo_path.read_text(encoding="utf-8"))
    req = ConfirmWorldRequest(
        world=raw["world"],
        campaign_name=raw.get("campaign_name", "The Lantern at Bramblefork"),
        model_name=None,
        play_mode="rules",
        system_pack="d20-fantasy-core",
        feature_flags={
            "rules_mode": True,
            "demo_campaign": True,
        },
        prose_style=raw.get("prose_style", "atmospheric"),
        tone=raw.get("tone", "grounded"),
    )
    result = confirm_world(req)
    _sheets().save_for_owner(
        result["campaign_id"],
        "player",
        "player",
        name="The Wayfarer",
        ancestry="Human",
        character_class="Adventurer",
        background="Wayfarer",
        level=1,
        proficiency_bonus=2,
        abilities={
            "strength": 12,
            "dexterity": 14,
            "constitution": 13,
            "intelligence": 12,
            "wisdom": 14,
            "charisma": 10,
        },
        skill_modifiers={
            "stealth": 4,
            "perception": 4,
            "investigation": 3,
            "persuasion": 2,
            "survival": 4,
        },
        save_modifiers={
            "dexterity": 4,
            "wisdom": 4,
        },
        max_hp=12,
        current_hp=12,
        armor_class=13,
        speed=30,
        currencies={"cp": 0, "sp": 8, "gp": 12},
        notes="Demo character for learning d20-fantasy-core play.",
    )
    return result


# ── Full world state (for overview / scene context) ───────────────────────────

@router.get("/{campaign_id}/world")
def get_full_world(campaign_id: str):
    """Return everything needed for the campaign overview in one call."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    active_scene = _scenes().get_active(campaign_id)
    active_encounter = _encounters().get_active(campaign_id, active_scene.id if active_scene else None)
    return {
        "campaign": _campaign_dict(c),
        "player_character": _pc_dict(_pcs().get(campaign_id)) if _pcs().get(campaign_id) else None,
        "character_sheet": _sheet_dict(_sheets().get_for_owner(campaign_id, "player", "player")) if _sheets().get_for_owner(campaign_id, "player", "player") else None,
        "action_logs": [_action_log_dict(a) for a in _action_logs().get_recent(campaign_id, n=20)],
        "rule_audits": [_rule_audit_dict(event) for event in _rule_audits().get_recent(campaign_id, n=20)],
        "active_encounter": _encounter_dict(active_encounter) if active_encounter else None,
        "encounters": [_encounter_dict(e) for e in _encounters().get_all(campaign_id)],
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
        "objectives": [_objective_dict(objective) for objective in _objectives().get_all(campaign_id)],
        "quests": [_quest_dict(quest) for quest in _quests().get_all(campaign_id)],
        "scenes": [_scene_dict(s) for s in _scenes().get_all(campaign_id)],
        "chronicle": [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)],
    }


@router.get("/{campaign_id}/character-sheet")
def get_character_sheet(campaign_id: str):
    _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    if not sheet:
        return {}
    return _sheet_dict(sheet)


@router.get("/{campaign_id}/character-sheets")
def get_all_character_sheets(campaign_id: str):
    _require_campaign(campaign_id)
    return [_sheet_dict(sheet) for sheet in _sheets().get_all(campaign_id)]


@router.get("/{campaign_id}/character-sheets/{owner_type}/{owner_id}")
def get_character_sheet_for_owner(campaign_id: str, owner_type: str, owner_id: str):
    _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        return {}
    return _sheet_dict(sheet)


@router.put("/{campaign_id}/character-sheet")
def save_character_sheet(campaign_id: str, req: SaveCharacterSheetRequest):
    _require_campaign(campaign_id)
    existing = _sheets().get_for_owner(campaign_id, "player", "player")
    sheet = _save_sheet_request(campaign_id, "player", "player", req, existing)
    return _sheet_dict(sheet)


@router.put("/{campaign_id}/character-sheets/{owner_type}/{owner_id}")
def save_character_sheet_for_owner(campaign_id: str, owner_type: str, owner_id: str, req: SaveCharacterSheetRequest):
    _require_campaign(campaign_id)
    existing = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    sheet = _save_sheet_request(campaign_id, owner_type, owner_id, req, existing)
    return _sheet_dict(sheet)


@router.get("/{campaign_id}/character-sheets/quick-build/options")
def get_character_quick_build_options(campaign_id: str):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    return list_quick_build_options()


@router.post("/{campaign_id}/character-sheets/{owner_type}/{owner_id}/quick-build")
def quick_build_character_sheet(campaign_id: str, owner_type: str, owner_id: str, req: QuickBuildCharacterRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    try:
        built = build_quick_character_sheet(
            campaign_id=campaign_id,
            name=req.name,
            character_class=req.character_class,
            ancestry=req.ancestry,
            background=req.background,
            level=req.level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    updated = _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        name=built.name,
        ancestry=built.ancestry,
        character_class=built.character_class,
        background=built.background,
        level=built.level,
        proficiency_bonus=built.proficiency_bonus,
        abilities=built.abilities,
        skill_modifiers=built.skill_modifiers,
        save_modifiers=built.save_modifiers,
        max_hp=built.max_hp,
        current_hp=built.current_hp,
        armor_class=built.armor_class,
        speed=built.speed,
        currencies=built.currencies,
        resource_pools=built.resource_pools,
        prepared_spells=built.prepared_spells,
        equipped_items=built.equipped_items,
        notes=built.notes,
    )

    pc_payload = None
    if owner_type == "player" and owner_id == "player":
        existing_pc = _pcs().get(campaign_id)
        pc = PlayerCharacter(
            id=existing_pc.id if existing_pc else _new_id(),
            campaign_id=campaign_id,
            name=req.name or built.name,
            appearance=existing_pc.appearance if existing_pc else "",
            personality=existing_pc.personality if existing_pc else "",
            background=req.background or built.background,
            wants=existing_pc.wants if existing_pc else "",
            fears=existing_pc.fears if existing_pc else "",
            how_seen=existing_pc.how_seen if existing_pc else f"{built.ancestry} {built.character_class}",
            dev_log=existing_pc.dev_log if existing_pc else [],
        )
        _pcs().save(pc)
        pc_payload = _pc_dict(pc)

    summary = f"Built a level {updated.level} {updated.ancestry} {updated.character_class} for {updated.name}."
    return {
        "sheet": _sheet_dict(updated),
        "player_character": pc_payload,
        "summary": summary,
    }


@router.post("/{campaign_id}/character-sheets/{owner_type}/{owner_id}/prepared-spells")
def set_prepared_character_spell(campaign_id: str, owner_type: str, owner_id: str, req: PrepareCharacterSpellRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    slug = str(req.slug or "").strip().lower()
    if not slug:
        raise HTTPException(400, "Spell slug is required")
    entry = _compendium_store().get(slug, system_pack=campaign.system_pack)
    if not entry:
        raise HTTPException(404, "Compendium entry not found")
    if entry.category != "spell":
        raise HTTPException(400, "Only compendium spells can be prepared")
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        raise HTTPException(404, "Character sheet not found")
    prepared = [spell for spell in (sheet.prepared_spells or []) if spell != slug]
    if req.prepared:
        prepared.append(slug)
    updated = _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        prepared_spells=prepared,
    )
    return {
        "sheet": _sheet_dict(updated),
        "spell": _compendium_entry_dict(entry),
        "prepared": req.prepared,
        "summary": f"{updated.name} {'prepared' if req.prepared else 'unprepared'} {entry.name}.",
    }


@router.post("/{campaign_id}/character-sheets/{owner_type}/{owner_id}/equipment")
def set_character_equipment(campaign_id: str, owner_type: str, owner_id: str, req: EquipCharacterItemRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    slug = str(req.slug or "").strip().lower()
    if not slug:
        raise HTTPException(400, "Item slug is required")
    entry = _compendium_store().get(slug, system_pack=campaign.system_pack)
    if not entry:
        raise HTTPException(404, "Compendium entry not found")
    if entry.category not in {"item", "weapon", "armor"}:
        raise HTTPException(400, "Only items, weapons, and armor can be equipped")
    if not entry.equipment_slot:
        raise HTTPException(400, f"{entry.name} does not use an equipment slot")
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        raise HTTPException(404, "Character sheet not found")

    equipped_items = dict(sheet.equipped_items or {})
    armor_class = int(sheet.armor_class or 0)
    replaced_slug = equipped_items.get(entry.equipment_slot)
    replaced_entry = _compendium_store().get(replaced_slug, system_pack=campaign.system_pack) if replaced_slug else None

    if req.equipped:
        if replaced_slug and replaced_slug != entry.slug:
            armor_class -= int(replaced_entry.armor_class_bonus or 0) if replaced_entry else 0
        if replaced_slug != entry.slug:
            armor_class += int(entry.armor_class_bonus or 0)
        equipped_items[entry.equipment_slot] = entry.slug
    else:
        removed = False
        for slot, equipped_slug in list(equipped_items.items()):
            if equipped_slug == entry.slug:
                del equipped_items[slot]
                removed = True
        if removed:
            armor_class -= int(entry.armor_class_bonus or 0)

    item_charges = dict(sheet.item_charges or {})
    if req.equipped and entry.charges_max > 0 and entry.slug not in item_charges:
        item_charges[entry.slug] = {
            "current": int(entry.charges_max),
            "max": int(entry.charges_max),
            "restores_on": str(entry.restores_on or ""),
        }

    updated = _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        armor_class=max(0, armor_class),
        equipped_items=equipped_items,
        item_charges=item_charges,
    )
    return {
        "sheet": _sheet_dict(updated),
        "item": _compendium_entry_dict(entry),
        "equipped": req.equipped,
        "replaced_item": _compendium_entry_dict(replaced_entry) if req.equipped and replaced_entry and replaced_entry.slug != entry.slug else None,
        "summary": f"{updated.name} {'equipped' if req.equipped else 'unequipped'} {entry.name}.",
    }


@router.post("/{campaign_id}/character-sheets/{owner_type}/{owner_id}/rest")
def rest_character_resources(campaign_id: str, owner_type: str, owner_id: str, req: RestCharacterResourcesRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    rest_type = str(req.rest_type or "").strip().lower()
    if rest_type not in {"short_rest", "long_rest"}:
        raise HTTPException(400, "rest_type must be 'short_rest' or 'long_rest'")
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        raise HTTPException(404, "Character sheet not found")

    updated, restored_resources, restored_items = _apply_rest_to_sheet(
        campaign_id,
        owner_type,
        owner_id,
        rest_type=rest_type,
    )
    summary = f"{updated.name} completes a {rest_type.replace('_', ' ')}."
    if restored_resources or restored_items:
        summary += f" Restored {len(restored_resources)} resource pool(s) and {len(restored_items)} item charge pool(s)."

    scene = _scenes().get_active(campaign_id)
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=updated.name,
        action_type="rest",
        source=rest_type,
        summary=summary,
        details={
            "rest_type": rest_type,
            "restored_resources": restored_resources,
            "restored_item_charges": restored_items,
            "sheet": _sheet_dict(updated),
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="rest",
        actor_name=updated.name,
        source=rest_type,
        reason="resource recovery",
        payload={
            "rest_type": rest_type,
            "restored_resources": restored_resources,
            "restored_item_charges": restored_items,
            "sheet": _sheet_dict(updated),
        },
    )
    return {
        "sheet": _sheet_dict(updated),
        "rest_type": rest_type,
        "restored_resources": restored_resources,
        "restored_item_charges": restored_items,
        "summary": summary,
    }


@router.post("/{campaign_id}/character-sheets/{owner_type}/{owner_id}/level-up")
def level_up_character_sheet(campaign_id: str, owner_type: str, owner_id: str, req: LevelUpCharacterRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        raise HTTPException(404, "Character sheet not found")

    target_level = validate_positive_int(req.target_level or (int(sheet.level or 1) + 1), "target_level")
    hit_point_gain = validate_non_negative_int(req.hit_point_gain, "hit_point_gain")
    ability_increases = {
        str(key).strip().lower(): int(value or 0)
        for key, value in (req.ability_increases or {}).items()
        if str(key).strip()
    }
    resource_pool_increases = {
        str(key).strip().lower(): int(value or 0)
        for key, value in (req.resource_pool_increases or {}).items()
        if str(key).strip()
    }
    try:
        progressed = apply_level_progression(
            sheet,
            target_level=target_level,
            hit_point_gain=hit_point_gain,
            ability_increases=ability_increases,
            resource_pool_increases=resource_pool_increases,
            feature_note=req.feature_note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    updated = _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        level=progressed.level,
        proficiency_bonus=progressed.proficiency_bonus,
        current_hp=progressed.current_hp,
        max_hp=progressed.max_hp,
        abilities=progressed.abilities,
        resource_pools=progressed.resource_pools,
        notes=progressed.notes,
    )
    scene = _scenes().get_active(campaign_id)
    summary = f"{updated.name} reached level {updated.level}."
    if hit_point_gain:
        summary += f" Gained {hit_point_gain} max HP."
    if ability_increases:
        summary += " Ability scores improved."
    if resource_pool_increases:
        summary += " Resource capacity increased."

    details = {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "from_level": sheet.level,
        "to_level": updated.level,
        "hit_point_gain": hit_point_gain,
        "ability_increases": ability_increases,
        "resource_pool_increases": resource_pool_increases,
        "feature_note": req.feature_note,
        "sheet": _sheet_dict(updated),
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=updated.name,
        action_type="level_up",
        source=updated.character_class or "progression",
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="level_up",
        actor_name=updated.name,
        source=updated.character_class or "progression",
        reason=req.feature_note,
        payload=details,
    )
    return {
        "sheet": _sheet_dict(updated),
        "from_level": sheet.level,
        "to_level": updated.level,
        "summary": summary,
    }


@router.post("/{campaign_id}/procedures/advance-time")
def advance_campaign_time_procedure(campaign_id: str, req: AdvanceCampaignTimeRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    hours = validate_positive_int(req.hours, "hours")
    procedure_type = str(req.procedure_type or "travel").strip().lower()
    if procedure_type not in {"travel", "downtime", "rest", "custom"}:
        raise HTTPException(400, "procedure_type must be travel, downtime, rest, or custom")

    start_hours = max(0, int(getattr(campaign, "world_time_hours", 0)))
    updated_campaign = _campaigns().update(
        campaign_id,
        world_time_hours=start_hours + hours,
    )
    time_snapshot = world_time_snapshot(updated_campaign.world_time_hours)
    generated_events = build_campaign_events(
        campaign_id=campaign_id,
        start_hours=start_hours,
        end_hours=int(getattr(updated_campaign, "world_time_hours", 0)),
        procedure_type=procedure_type,
        destination=str(req.destination or "").strip(),
    )
    matured_events: list = []
    matured_event_consequences: list[dict] = []
    for existing_event in _events().get_all(campaign_id):
        matured = mature_campaign_event(
            existing_event,
            end_hours=int(getattr(updated_campaign, "world_time_hours", 0)),
        )
        if matured:
            _events().save(matured)
            matured_events.append(matured)
    for event in generated_events:
        _events().save(event)

    restored_resources: list[dict] = []
    restored_items: list[dict] = []
    player_sheet_payload = None
    if req.rest_type:
        rest_type = str(req.rest_type or "").strip().lower()
        if rest_type not in {"short_rest", "long_rest"}:
            raise HTTPException(400, "rest_type must be 'short_rest' or 'long_rest'")
        player_sheet, restored_resources, restored_items = _apply_rest_to_sheet(
            campaign_id,
            "player",
            "player",
            rest_type=rest_type,
        )
        player_sheet_payload = _sheet_dict(player_sheet)

    faction_updates: list[dict] = []
    for effect in req.faction_effects or []:
        faction = _factions().get(effect.faction_id)
        if not faction or faction.campaign_id != campaign_id:
            raise HTTPException(404, f"Faction not found: {effect.faction_id}")
        old_standing = faction.standing_with_player or "neutral"
        faction.standing_with_player = shift_faction_standing(old_standing, effect.delta)
        if effect.note:
            note_prefix = f"[{time_snapshot['label']}] "
            faction.relationship_notes = (faction.relationship_notes + "\n" if faction.relationship_notes else "") + note_prefix + effect.note
        faction.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _factions().save(faction)
        faction_updates.append({
            "id": faction.id,
            "name": faction.name,
            "from": old_standing,
            "to": faction.standing_with_player,
            "delta": effect.delta,
        })

    quest_updates: list[dict] = []
    for matured_event in matured_events:
        event_player_sheet, event_faction_updates, event_quest_updates, consequence = _apply_matured_event_consequences(
            campaign_id,
            matured_event,
            time_snapshot=time_snapshot,
        )
        if event_player_sheet:
            player_sheet_payload = event_player_sheet
        if event_faction_updates:
            faction_updates.extend(event_faction_updates)
        if event_quest_updates:
            quest_updates.extend(event_quest_updates)
        if consequence:
            matured_event_consequences.append({
                "event_id": matured_event.id,
                "title": matured_event.title,
                "consequence": consequence,
            })

    destination = str(req.destination or "").strip()
    scene = _scenes().get_active(campaign_id)
    if destination and scene and procedure_type == "travel":
        scene.location = destination
        _scenes().save(scene)

    summary = f"Advanced {hours} hour(s) via {procedure_type}."
    if destination:
        summary += f" Destination: {destination}."
    if req.rest_type:
        summary += f" Applied {req.rest_type.replace('_', ' ')} recovery."
    if faction_updates:
        summary += f" Updated {len(faction_updates)} faction standing(s)."
    if matured_events:
        summary += f" Escalated {len(matured_events)} pending event(s)."
    if matured_event_consequences:
        summary += f" Applied {len(matured_event_consequences)} escalation consequence(s)."
    if generated_events:
        summary += f" Generated {len(generated_events)} campaign event(s)."

    details = {
        "hours": hours,
        "procedure_type": procedure_type,
        "reason": req.reason,
        "destination": destination,
        "world_time": time_snapshot,
        "rest_type": req.rest_type,
        "restored_resources": restored_resources,
        "restored_item_charges": restored_items,
        "faction_updates": faction_updates,
        "quest_updates": quest_updates,
        "matured_events": [_campaign_event_dict(event) for event in matured_events],
        "matured_event_consequences": matured_event_consequences,
        "generated_events": [_campaign_event_dict(event) for event in generated_events],
        "player_sheet": player_sheet_payload,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name="GM",
        action_type="campaign_procedure",
        source=procedure_type,
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="campaign_procedure",
        actor_name="GM",
        source=procedure_type,
        reason=req.reason,
        payload=details,
    )
    return {
        "campaign": _campaign_dict(updated_campaign),
        "world_time": time_snapshot,
        "faction_updates": faction_updates,
        "quest_updates": quest_updates,
        "matured_events": [_campaign_event_dict(event) for event in matured_events],
        "matured_event_consequences": matured_event_consequences,
        "events": [_campaign_event_dict(event) for event in generated_events],
        "player_sheet": player_sheet_payload,
        "summary": summary,
    }


@router.post("/{campaign_id}/procedures/downtime")
def run_campaign_downtime_procedure(campaign_id: str, req: RunDowntimeRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    days = validate_positive_int(req.days, "days")
    activity_type = str(req.activity_type or "work").strip().lower()
    start_hours = max(0, int(getattr(campaign, "world_time_hours", 0)))
    elapsed_hours = days * 24
    updated_campaign = _campaigns().update(
        campaign_id,
        world_time_hours=start_hours + elapsed_hours,
    )
    time_snapshot = world_time_snapshot(updated_campaign.world_time_hours)

    try:
        activity = build_downtime_activity_result(
            campaign_id=campaign_id,
            activity_type=activity_type,
            days=days,
            subject=req.subject,
            world_time_hours=int(getattr(updated_campaign, "world_time_hours", 0)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    player_sheet_payload = None
    reward_currencies: dict[str, int] = {}
    if activity.get("currency_delta") and req.apply_rewards_to_player:
        reward_currencies = {key: int(value or 0) for key, value in (activity.get("currency_delta") or {}).items()}
        if reward_currencies:
            sheet = _sheets().get_for_owner(campaign_id, "player", "player")
            if not sheet:
                raise HTTPException(404, "Character sheet not found")
            updated_wallet = dict(sheet.currencies or {})
            for denomination, amount in reward_currencies.items():
                current_value = int(updated_wallet.get(denomination, 0) or 0)
                if amount < 0 and current_value < abs(amount):
                    raise HTTPException(400, f"Not enough {denomination} to cover downtime cost")
                updated_wallet = adjust_currency(updated_wallet, denomination, amount)
            updated_sheet = _sheets().save_for_owner(campaign_id, "player", "player", currencies=updated_wallet)
            player_sheet_payload = _sheet_dict(updated_sheet)

    training_updates: dict[str, dict] = {}
    if req.apply_rewards_to_player and (activity.get("skill_increases") or activity.get("resource_pool_increases")):
        sheet = _sheets().get_for_owner(campaign_id, "player", "player")
        if not sheet:
            raise HTTPException(404, "Character sheet not found")
        skill_modifiers = dict(sheet.skill_modifiers or {})
        for skill_name, delta in (activity.get("skill_increases") or {}).items():
            skill_modifiers[skill_name] = int(skill_modifiers.get(skill_name, 0) or 0) + int(delta or 0)
        resource_pools = dict(sheet.resource_pools or {})
        for pool_name, delta in (activity.get("resource_pool_increases") or {}).items():
            state = dict(resource_pools.get(pool_name, {}))
            maximum = int(state.get("max", state.get("maximum", 0)) or 0)
            current = int(state.get("current", maximum) or 0)
            increase = max(0, int(delta or 0))
            state["max"] = maximum + increase
            state["current"] = current + increase
            state["restores_on"] = str(state.get("restores_on", "long_rest") or "long_rest")
            resource_pools[pool_name] = state
        updated_sheet = _sheets().save_for_owner(
            campaign_id,
            "player",
            "player",
            skill_modifiers=skill_modifiers,
            resource_pools=resource_pools,
        )
        player_sheet_payload = _sheet_dict(updated_sheet)
        training_updates = {
            "skill_increases": activity.get("skill_increases") or {},
            "resource_pool_increases": activity.get("resource_pool_increases") or {},
        }

    crafted_item_payload = None
    if req.apply_rewards_to_player and activity.get("crafted_item"):
        crafted = dict(activity.get("crafted_item") or {})
        slug = str(crafted.get("slug", "") or "").strip().lower()
        if not slug:
            raise HTTPException(400, "Craft downtime requires an item slug or subject")
        entry = _compendium_store().get(slug, system_pack=campaign.system_pack)
        if not entry:
            raise HTTPException(404, f"Compendium entry not found: {slug}")
        sheet = _sheets().get_for_owner(campaign_id, "player", "player")
        if not sheet:
            raise HTTPException(404, "Character sheet not found")
        equipped_items = dict(sheet.equipped_items or {})
        item_charges = dict(sheet.item_charges or {})
        armor_class = int(sheet.armor_class or 0)
        notes = str(sheet.notes or "")
        auto_equipped = False
        if entry.equipment_slot and entry.equipment_slot not in equipped_items:
            equipped_items[entry.equipment_slot] = entry.slug
            auto_equipped = True
            armor_class += int(entry.armor_class_bonus or 0)
        if entry.charges_max > 0:
            item_charges[entry.slug] = {
                "current": int(entry.charges_max),
                "max": int(entry.charges_max),
                "restores_on": str(entry.restores_on or ""),
            }
        notes = (notes + "\n" if notes else "") + (
            f"[Crafted] {entry.name} completed during downtime."
            if auto_equipped
            else f"[Crafted] {entry.name} completed during downtime and was stowed for later use."
        )
        updated_sheet = _sheets().save_for_owner(
            campaign_id,
            "player",
            "player",
            armor_class=max(0, armor_class),
            equipped_items=equipped_items,
            item_charges=item_charges,
            notes=notes,
        )
        player_sheet_payload = _sheet_dict(updated_sheet)
        crafted_item_payload = {
            "entry": _compendium_entry_dict(entry),
            "auto_equipped": auto_equipped,
            "cost_gp": int(crafted.get("cost_gp", 0) or 0),
            "days": int(crafted.get("days", 0) or 0),
        }

    faction_updates: list[dict] = []
    faction_id = str(req.faction_id or "").strip()
    faction_delta = int(activity.get("faction_delta", 0) or 0)
    if faction_id and faction_delta:
        faction = _factions().get(faction_id)
        if not faction or faction.campaign_id != campaign_id:
            raise HTTPException(404, f"Faction not found: {faction_id}")
        old_standing = faction.standing_with_player or "neutral"
        faction.standing_with_player = shift_faction_standing(old_standing, faction_delta)
        note = f"[{time_snapshot['label']}] Downtime {activity_type}: {req.reason or activity.get('summary', '')}"
        faction.relationship_notes = (faction.relationship_notes + "\n" if faction.relationship_notes else "") + note
        faction.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _factions().save(faction)
        faction_updates.append({
            "id": faction.id,
            "name": faction.name,
            "from": old_standing,
            "to": faction.standing_with_player,
            "delta": faction_delta,
        })

    objective_updates: list[dict] = []
    objective_note = str(activity.get("objective_note", "") or "").strip()
    objective_id = str(req.objective_id or "").strip()
    if objective_note and objective_id:
        objective = _objectives().get(objective_id)
        if not objective or objective.campaign_id != campaign_id:
            raise HTTPException(404, f"Objective not found: {objective_id}")
        objective.description = (objective.description + "\n" if objective.description else "") + objective_note
        objective.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _objectives().save(objective)
        objective_updates.append(_objective_dict(objective))

    quest_updates: list[dict] = []
    quest_note = str(activity.get("quest_note", "") or "").strip()
    quest_id = str(req.quest_id or "").strip()
    if quest_note and quest_id:
        quest = _quests().get(quest_id)
        if not quest or quest.campaign_id != campaign_id:
            raise HTTPException(404, f"Quest not found: {quest_id}")
        quest.description = (quest.description + "\n" if quest.description else "") + quest_note
        quest.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _quests().save(quest)
        quest_updates.append(_quest_dict(quest))

    generated_events = []
    for event in activity.get("events") or []:
        event.details = dict(event.details or {})
        if faction_id and "faction_id" not in event.details:
            event.details["faction_id"] = faction_id
        if quest_id and "quest_id" not in event.details:
            event.details["quest_id"] = quest_id
        _events().save(event)
        generated_events.append(event)

    scene = _scenes().get_active(campaign_id)
    summary = activity.get("summary") or f"Completed {days} day(s) of {activity_type} downtime."
    if req.reason:
        summary += f" Reason: {req.reason}."
    if training_updates:
        summary += " Training rewards applied."
    if crafted_item_payload:
        summary += f" Crafted {crafted_item_payload['entry']['name']}."
    if generated_events:
        summary += f" Generated {len(generated_events)} campaign event(s)."

    details = {
        "activity_type": activity_type,
        "days": days,
        "hours": elapsed_hours,
        "subject": str(req.subject or "").strip(),
        "reason": req.reason,
        "world_time": time_snapshot,
        "reward_currencies": reward_currencies,
        "training_updates": training_updates,
        "crafted_item": crafted_item_payload,
        "faction_updates": faction_updates,
        "objective_updates": objective_updates,
        "quest_updates": quest_updates,
        "generated_events": [_campaign_event_dict(event) for event in generated_events],
        "player_sheet": player_sheet_payload,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name="GM",
        action_type="campaign_procedure",
        source=f"downtime:{activity_type}",
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="campaign_procedure",
        actor_name="GM",
        source=f"downtime:{activity_type}",
        reason=req.reason,
        payload=details,
    )
    return {
        "campaign": _campaign_dict(updated_campaign),
        "world_time": time_snapshot,
        "activity_type": activity_type,
        "reward_currencies": reward_currencies,
        "training_updates": training_updates,
        "crafted_item": crafted_item_payload,
        "faction_updates": faction_updates,
        "objective_updates": objective_updates,
        "quest_updates": quest_updates,
        "events": [_campaign_event_dict(event) for event in generated_events],
        "player_sheet": player_sheet_payload,
        "summary": summary,
    }


@router.post("/{campaign_id}/procedures/advance-quest")
def advance_campaign_quest_procedure(campaign_id: str, req: AdvanceCampaignQuestRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    quest = _quests().get(req.quest_id)
    if not quest or quest.campaign_id != campaign_id:
        raise HTTPException(404, "Quest not found")

    next_status = str(req.status or "").strip().lower() or None
    if next_status and next_status not in {status.value for status in QuestStatus}:
        raise HTTPException(400, "status must be hidden, active, completed, or failed")

    try:
        updated_quest = advance_campaign_quest(
            quest,
            stage_id=req.stage_id,
            status=next_status,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    updated_quest.updated_at = datetime.now(UTC).replace(tzinfo=None)
    _quests().save(updated_quest)

    objective_updates: list[dict] = []
    for objective_id in req.objective_ids or []:
        objective = _objectives().get(objective_id)
        if not objective or objective.campaign_id != campaign_id:
            raise HTTPException(404, f"Objective not found: {objective_id}")
        previous_status = objective.status.value
        objective.status = ObjectiveStatus.COMPLETED
        objective.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _objectives().save(objective)
        objective_updates.append({
            "id": objective.id,
            "title": objective.title,
            "from": previous_status,
            "to": objective.status.value,
        })

    updated_campaign = campaign
    time_snapshot = world_time_snapshot(getattr(campaign, "world_time_hours", 0))
    if req.advance_hours:
        hours = validate_positive_int(req.advance_hours, "advance_hours")
        updated_campaign = _campaigns().update(
            campaign_id,
            world_time_hours=max(0, int(getattr(campaign, "world_time_hours", 0))) + hours,
        )
        time_snapshot = world_time_snapshot(updated_campaign.world_time_hours)

    treasure_bundle = None
    player_sheet_payload = None
    if req.generate_treasure:
        challenge_rating = (
            validate_non_negative_int(req.treasure_challenge_rating, "treasure_challenge_rating")
            if req.treasure_challenge_rating is not None
            else max(1, len(updated_quest.stages) or 1)
        )
        treasure_bundle = generate_treasure_bundle(
            challenge_rating=challenge_rating,
            source_type="quest",
            source_name=updated_quest.title,
        )
        if req.apply_treasure_to_player:
            player_sheet_payload = _apply_treasure_bundle_to_player(campaign_id, treasure_bundle)

    stage = None
    if req.stage_id:
        stage = next((entry for entry in updated_quest.stages if entry.id == req.stage_id), None)

    summary = f"Advanced quest '{updated_quest.title}'."
    if stage:
        summary += f" Completed stage: {stage.description}."
    if updated_quest.status != quest.status:
        summary += f" Status is now {updated_quest.status.value}."
    if objective_updates:
        summary += f" Completed {len(objective_updates)} linked objective(s)."
    if req.advance_hours:
        summary += f" Advanced {req.advance_hours} in-world hour(s)."
    if treasure_bundle:
        summary += " Treasure generated."
    if req.note:
        summary += f" Note: {req.note}"

    scene = _scenes().get_active(campaign_id)
    details = {
        "quest": _quest_dict(updated_quest),
        "completed_stage_id": req.stage_id,
        "objective_updates": objective_updates,
        "world_time": time_snapshot,
        "treasure": treasure_bundle,
        "player_sheet": player_sheet_payload,
        "note": req.note,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name="GM",
        action_type="quest_progress",
        source=updated_quest.title,
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="quest_progress",
        actor_name="GM",
        source=updated_quest.title,
        reason=req.note or "quest progression",
        payload=details,
    )
    return {
        "campaign": _campaign_dict(updated_campaign),
        "world_time": time_snapshot,
        "quest": _quest_dict(updated_quest),
        "objective_updates": objective_updates,
        "treasure": treasure_bundle,
        "player_sheet": player_sheet_payload,
        "summary": summary,
    }


@router.post("/{campaign_id}/procedures/generate-treasure")
def generate_campaign_treasure_procedure(campaign_id: str, req: GenerateTreasureRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    challenge_rating = validate_non_negative_int(req.challenge_rating, "challenge_rating")
    source_type = str(req.source_type or "loot").strip().lower() or "loot"
    bundle = generate_treasure_bundle(
        challenge_rating=challenge_rating,
        source_type=source_type,
        source_name=str(req.source_name or "").strip(),
    )

    player_sheet_payload = None
    if req.apply_to_player:
        player_sheet_payload = _apply_treasure_bundle_to_player(campaign_id, bundle)

    scene = _scenes().get_active(campaign_id)
    summary = bundle.get("summary") or "Treasure generated."
    if req.apply_to_player:
        summary += " Applied to player sheet."
    details = {
        "challenge_rating": challenge_rating,
        "source_type": source_type,
        "source_name": req.source_name,
        "treasure": bundle,
        "player_sheet": player_sheet_payload,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name="GM",
        action_type="treasure",
        source=source_type,
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="treasure",
        actor_name="GM",
        source=source_type,
        reason=req.source_name,
        payload=details,
    )
    return {
        "treasure": bundle,
        "player_sheet": player_sheet_payload,
        "summary": summary,
    }


@router.post("/{campaign_id}/character-sheet/adjust")
def adjust_character_sheet_state(campaign_id: str, req: AdjustCharacterSheetStateRequest):
    campaign = _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    if not sheet:
        raise HTTPException(404, "Character sheet not found")

    updated, summary = apply_sheet_state_change(
        sheet,
        damage=max(0, req.damage),
        healing=max(0, req.healing),
        temp_hp_delta=req.temp_hp_delta,
        add_conditions=req.add_conditions,
        remove_conditions=req.remove_conditions,
        notes_append=req.notes_append,
    )
    saved = _sheets().save_for_owner(
        campaign_id,
        "player",
        "player",
        current_hp=updated.current_hp,
        temp_hp=updated.temp_hp,
        conditions=updated.conditions,
        notes=updated.notes,
    )
    scene = _scenes().get_active(campaign_id)
    actor_name = saved.name or "Player"
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=actor_name,
        action_type="sheet_update",
        source="character_sheet",
        summary=f"{actor_name} {summary}.",
        details={
            "play_mode": campaign.play_mode.value if hasattr(campaign.play_mode, "value") else str(campaign.play_mode),
            "current_hp": saved.current_hp,
            "max_hp": saved.max_hp,
            "temp_hp": saved.temp_hp,
            "conditions": saved.conditions,
            "damage": max(0, req.damage),
            "healing": max(0, req.healing),
            "temp_hp_delta": req.temp_hp_delta,
            "notes_append": req.notes_append,
        },
    ))
    return {
        "sheet": _sheet_dict(saved),
        "summary": summary,
    }


@router.post("/{campaign_id}/checks/resolve")
def resolve_campaign_check(campaign_id: str, req: ResolveCheckRequest):
    campaign = _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    _require_d20_rules_mode(campaign)
    try:
        advantage_state = validate_advantage_state(req.advantage_state)
        roll_expression = validate_dice_expression(req.roll_expression)
        difficulty = validate_non_negative_int(req.difficulty, "difficulty")
        action_cost = validate_action_cost(req.action_cost)
        resource_costs = validate_resource_costs(req.resource_costs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    sheet, consumed_resources = _apply_resource_costs(campaign_id, sheet, resource_costs)
    result = resolve_d20_check(
        sheet=sheet,
        source=req.source,
        difficulty=difficulty,
        roll_expression=roll_expression,
        advantage_state=advantage_state,
        reason=req.reason,
    )
    scene = _scenes().get_active(campaign_id)
    encounter = _require_player_turn_for_scene_encounter(campaign_id, scene.id if scene else None)
    encounter, actor_participant = _consume_player_action_if_needed(
        encounter,
        campaign_id,
        scene.id if scene else None,
        cost=action_cost,
        note=f"Player uses {action_cost.replace('_', ' ')} for a {req.source} check.",
    )
    actor_name = sheet.name if sheet else (_pcs().get(campaign_id).name if _pcs().get(campaign_id) else "Player")
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=actor_name,
        action_type="check",
        source=req.source,
        summary=f"{actor_name} made a {req.source} check against DC {difficulty}: {result.total} ({result.outcome}).",
        details={
            "resolution": result.model_dump(),
            "encounter": _encounter_dict(encounter) if encounter and actor_participant else None,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="check",
        actor_name=actor_name,
        source=req.source,
        reason=req.reason,
        payload={
            "resolution": result.model_dump(),
            "encounter": _encounter_dict(encounter) if encounter and actor_participant else None,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    )
    payload = result.model_dump()
    payload["encounter"] = _encounter_dict(encounter) if encounter and actor_participant else None
    payload["action_cost"] = action_cost
    return payload


@router.post("/{campaign_id}/attacks/resolve")
def resolve_campaign_attack(campaign_id: str, req: ResolveAttackRequest):
    campaign = _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    scene = _scenes().get_active(campaign_id)
    active_turn_encounter = _require_player_turn_for_scene_encounter(campaign_id, scene.id if scene else None)
    active_encounter = _encounters().get_active(campaign_id, scene.id if scene else None)
    _require_d20_rules_mode(campaign)
    try:
        advantage_state = validate_advantage_state(req.advantage_state)
        roll_expression = validate_dice_expression(req.roll_expression, allowed_sides={20})
        damage_roll_expression = validate_dice_expression(req.damage_roll_expression)
        target_armor_class = validate_non_negative_int(req.target_armor_class, "target_armor_class")
        range_feet = validate_non_negative_int(req.range_feet, "range_feet") if req.range_feet is not None else None
        target_distance_feet = validate_non_negative_int(req.target_distance_feet, "target_distance_feet") if req.target_distance_feet is not None else None
        action_cost = validate_action_cost(req.action_cost)
        resource_costs = validate_resource_costs(req.resource_costs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    sheet, consumed_resources = _apply_resource_costs(campaign_id, sheet, resource_costs)

    target_participant = None
    if req.target_participant_id:
        if not active_encounter:
            raise HTTPException(400, "No active encounter found for targeted attack resolution")
        target_participant = next(
            (participant for participant in active_encounter.participants if participant.id == req.target_participant_id),
            None,
        )
        if not target_participant:
            raise HTTPException(404, "Encounter participant not found")
        _validate_target_range(range_feet=range_feet, target_distance_feet=target_distance_feet)
        if target_participant.armor_class is not None:
            target_armor_class = int(target_participant.armor_class)
        if target_participant.life_state == "dead":
            raise HTTPException(400, "Cannot target a dead participant with an attack")

    attack = resolve_d20_attack(
        attacker=sheet,
        source=req.source,
        target_armor_class=target_armor_class,
        roll_expression=roll_expression,
        advantage_state=advantage_state,
        reason=req.reason,
    )
    damage = None
    if attack.hit and damage_roll_expression.strip():
        damage = resolve_damage_roll(
            roll_expression=damage_roll_expression,
            modifier=req.damage_modifier,
            critical_hit=attack.critical_hit,
            damage_type=req.damage_type,
            reason=req.reason,
            source=req.source,
        )

    actor_name = sheet.name if sheet else (_pcs().get(campaign_id).name if _pcs().get(campaign_id) else "Player")
    encounter_after = active_encounter
    target_state = None
    action_participant = None
    encounter_after, action_participant = _consume_player_action_if_needed(
        active_turn_encounter,
        campaign_id,
        scene.id if scene else None,
        cost=action_cost,
        note=f"{actor_name} uses {action_cost.replace('_', ' ')} to attack with {req.source}.",
    )
    if active_encounter and encounter_after and encounter_after.id == active_encounter.id:
        active_encounter = encounter_after
    if damage and target_participant and active_encounter:
        try:
            encounter_after, updated_participant = apply_damage_to_participant(
                active_encounter,
                participant_id=target_participant.id,
                damage_total=damage.total,
                damage_type=damage.damage_type,
                note=f"{actor_name} hits {target_participant.name}.",
            )
            _encounters().save(encounter_after)
            target_state = updated_participant.model_dump()
            _sync_encounter_participant_to_sheet(campaign_id, target_state)
        except ValueError as e:
            raise HTTPException(404, str(e))

    summary = (
        f"{actor_name} attacked with {req.source} against AC {target_armor_class}: "
        f"{attack.total} ({attack.outcome})."
    )
    if damage:
        damage_label = f" {damage.total} damage"
        if damage.damage_type:
            damage_label += f" ({damage.damage_type})"
        summary += damage_label + "."
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=actor_name,
        action_type="attack",
        source=req.source,
        summary=summary,
        details={
            "attack": attack.model_dump(),
            "damage": damage.model_dump() if damage else None,
            "target_participant": target_state,
            "encounter": _encounter_dict(encounter_after) if encounter_after and target_state else None,
            "range_feet": range_feet,
            "target_distance_feet": target_distance_feet,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="attack",
        actor_name=actor_name,
        source=req.source,
        reason=req.reason,
        payload={
            "attack": attack.model_dump(),
            "damage": damage.model_dump() if damage else None,
            "target_participant": target_state,
            "encounter": _encounter_dict(encounter_after) if encounter_after else None,
            "range_feet": range_feet,
            "target_distance_feet": target_distance_feet,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    )
    return {
        "attack": attack.model_dump(),
        "damage": damage.model_dump() if damage else None,
        "target_participant": target_state,
        "encounter": _encounter_dict(encounter_after) if encounter_after else None,
        "range_feet": range_feet,
        "target_distance_feet": target_distance_feet,
        "action_cost": action_cost,
    }


@router.post("/{campaign_id}/healing/resolve")
def resolve_campaign_healing(campaign_id: str, req: ResolveHealingRequest):
    campaign = _require_campaign(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    scene = _scenes().get_active(campaign_id)
    encounter = _require_player_turn_for_scene_encounter(campaign_id, scene.id if scene else None)
    active_encounter = _encounters().get_active(campaign_id, scene.id if scene else None)
    _require_d20_rules_mode(campaign)
    try:
        roll_expression = validate_dice_expression(req.roll_expression)
        range_feet = validate_non_negative_int(req.range_feet, "range_feet") if req.range_feet is not None else None
        target_distance_feet = validate_non_negative_int(req.target_distance_feet, "target_distance_feet") if req.target_distance_feet is not None else None
        action_cost = validate_action_cost(req.action_cost)
        resource_costs = validate_resource_costs(req.resource_costs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    sheet, consumed_resources = _apply_resource_costs(campaign_id, sheet, resource_costs)

    healing = resolve_healing_roll(
        roll_expression=roll_expression,
        modifier=req.modifier,
        reason=req.reason,
        source=req.source,
    )

    saved_sheet = sheet
    encounter_after = active_encounter
    target_state = None
    encounter_after, actor_participant = _consume_player_action_if_needed(
        encounter,
        campaign_id,
        scene.id if scene else None,
        cost=action_cost,
        note=f"{req.source} uses the actor's {action_cost.replace('_', ' ')}.",
    )
    if active_encounter and encounter_after and encounter_after.id == active_encounter.id:
        active_encounter = encounter_after
    summary = f"Recovered {healing.total} HP"
    if req.target_participant_id:
        if not active_encounter:
            raise HTTPException(400, "No active encounter found for targeted healing")
        _validate_target_range(range_feet=range_feet, target_distance_feet=target_distance_feet)
        try:
            encounter_after, updated_participant = apply_healing_to_participant(
                active_encounter,
                participant_id=req.target_participant_id,
                healing_total=healing.total,
                note=f"{req.source} restores vitality.",
            )
            _encounters().save(encounter_after)
            target_state = updated_participant.model_dump()
            _sync_encounter_participant_to_sheet(campaign_id, target_state)
            summary = f"{updated_participant.name} recovered {healing.total} HP"
        except ValueError as e:
            raise HTTPException(404, str(e))
    elif req.apply_to_sheet:
        if not sheet:
            raise HTTPException(404, "Character sheet not found")
        updated, sheet_summary = apply_sheet_state_change(sheet, healing=healing.total)
        saved_sheet = _sheets().save_for_owner(
            campaign_id,
            "player",
            "player",
            current_hp=updated.current_hp,
            temp_hp=updated.temp_hp,
            conditions=updated.conditions,
            notes=updated.notes,
        )
        summary = sheet_summary

    actor_name = saved_sheet.name if saved_sheet else (_pcs().get(campaign_id).name if _pcs().get(campaign_id) else "Player")
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=actor_name,
        action_type="healing",
        source=req.source,
        summary=f"{actor_name} {summary}.",
        details={
            "healing": healing.model_dump(),
            "applied_to_sheet": req.apply_to_sheet,
            "sheet": _sheet_dict(saved_sheet) if saved_sheet else None,
            "target_participant": target_state,
            "encounter": _encounter_dict(encounter_after) if encounter_after else None,
            "range_feet": range_feet,
            "target_distance_feet": target_distance_feet,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="healing",
        actor_name=actor_name,
        source=req.source,
        reason=req.reason,
        payload={
            "healing": healing.model_dump(),
            "applied_to_sheet": req.apply_to_sheet,
            "sheet": _sheet_dict(saved_sheet) if saved_sheet else None,
            "target_participant": target_state,
            "encounter": _encounter_dict(encounter_after) if encounter_after else None,
            "range_feet": range_feet,
            "target_distance_feet": target_distance_feet,
            "action_cost": action_cost,
            "resources_consumed": consumed_resources,
        },
    )
    return {
        "healing": healing.model_dump(),
        "sheet": _sheet_dict(saved_sheet) if saved_sheet else None,
        "target_participant": target_state,
        "encounter": _encounter_dict(encounter_after) if encounter_after else None,
        "range_feet": range_feet,
        "target_distance_feet": target_distance_feet,
        "action_cost": action_cost,
        "summary": summary,
    }


@router.post("/{campaign_id}/contested-checks/resolve")
def resolve_campaign_contested_check(campaign_id: str, req: ResolveContestedCheckRequest):
    campaign = _require_campaign(campaign_id)
    actor_sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    scene = _scenes().get_active(campaign_id)
    encounter = _require_player_turn_for_scene_encounter(campaign_id, scene.id if scene else None)
    _require_d20_rules_mode(campaign)
    try:
        validate_contested_check_inputs(
            opponent_owner_type=req.opponent_owner_type,
            opponent_owner_id=req.opponent_owner_id,
            opponent_modifier=req.opponent_modifier,
        )
        roll_expression = validate_dice_expression(req.roll_expression, allowed_sides={20})
        actor_advantage_state = validate_advantage_state(req.actor_advantage_state)
        opponent_advantage_state = validate_advantage_state(req.opponent_advantage_state)
        action_cost = validate_action_cost(req.action_cost)
        resource_costs = validate_resource_costs(req.resource_costs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    actor_sheet, consumed_resources = _apply_resource_costs(campaign_id, actor_sheet, resource_costs)

    opponent_sheet = None
    opponent_name = req.opponent_name
    if req.opponent_owner_type and req.opponent_owner_id:
        opponent_sheet = _sheets().get_for_owner(campaign_id, req.opponent_owner_type, req.opponent_owner_id)
        if opponent_sheet:
            opponent_name = opponent_sheet.name or opponent_name

    actor_name = actor_sheet.name if actor_sheet else (_pcs().get(campaign_id).name if _pcs().get(campaign_id) else "Player")
    result = resolve_contested_d20_check(
        actor_sheet=actor_sheet,
        actor_name=actor_name,
        actor_source=req.actor_source,
        opponent_sheet=opponent_sheet,
        opponent_name=opponent_name,
        opponent_source=req.opponent_source,
        opponent_modifier=req.opponent_modifier,
        roll_expression=roll_expression,
        actor_advantage_state=actor_advantage_state,
        opponent_advantage_state=opponent_advantage_state,
        reason=req.reason,
    )
    if result.winner == "actor":
        summary = f"{actor_name} wins the contested {req.actor_source} vs {req.opponent_source} check by {result.margin}."
    elif result.winner == "opponent":
        summary = f"{opponent_name} wins the contested {req.actor_source} vs {req.opponent_source} check by {result.margin}."
    else:
        summary = f"{actor_name} and {opponent_name} tie the contested {req.actor_source} vs {req.opponent_source} check."

    encounter_after, actor_participant = _consume_player_action_if_needed(
        encounter,
        campaign_id,
        scene.id if scene else None,
        cost=action_cost,
        note=f"{actor_name} uses {action_cost.replace('_', ' ')} for a contested {req.actor_source} check.",
    )
    payload = {
        "resolution": result.model_dump(),
        "encounter": _encounter_dict(encounter_after) if encounter and actor_participant else None,
        "action_cost": action_cost,
        "resources_consumed": consumed_resources,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        actor_name=actor_name,
        action_type="contested_check",
        source=req.actor_source,
        summary=summary,
        details=payload,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene.id if scene else None,
        event_type="contested_check",
        actor_name=actor_name,
        source=req.actor_source,
        reason=req.reason,
        payload=payload,
    )
    response = result.model_dump()
    response["encounter"] = payload["encounter"]
    response["action_cost"] = action_cost
    return response


@router.post("/{campaign_id}/encounters")
def create_encounter(campaign_id: str, req: CreateEncounterRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    if not req.participants:
        raise HTTPException(400, "Encounter requires at least one participant")

    scene_id = req.scene_id
    scene = None
    if scene_id:
        scene = _scenes().get(scene_id)
        if not scene or scene.campaign_id != campaign_id:
            raise HTTPException(404, "Scene not found")
    else:
        scene = _scenes().get_active(campaign_id)
        scene_id = scene.id if scene else None

    participants = [
        _build_encounter_participant_request(campaign_id, participant)
        for participant in req.participants
    ]
    encounter = build_encounter(
        campaign_id=campaign_id,
        scene_id=scene_id,
        name=req.name,
        participants=participants,
    )
    _encounters().save(encounter)
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene_id,
        actor_name="GM",
        action_type="encounter_start",
        source="encounter",
        summary=f"Encounter started: {encounter.name}.",
        details={"encounter": _encounter_dict(encounter)},
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type="encounter_start",
        actor_name="GM",
        source="encounter",
        reason=req.name,
        payload={"encounter": _encounter_dict(encounter)},
    )
    return _encounter_dict(encounter)


@router.get("/{campaign_id}/encounters")
def get_encounters(campaign_id: str):
    _require_campaign(campaign_id)
    return [_encounter_dict(encounter) for encounter in _encounters().get_all(campaign_id)]


@router.get("/{campaign_id}/encounters/active")
def get_active_encounter(campaign_id: str, scene_id: Optional[str] = None):
    _require_campaign(campaign_id)
    encounter = _encounters().get_active(campaign_id, scene_id=scene_id)
    if not encounter:
        raise HTTPException(404, "No active encounter found")
    return _encounter_dict(encounter)


@router.post("/{campaign_id}/encounters/{encounter_id}/advance")
def advance_campaign_encounter_turn(campaign_id: str, encounter_id: str, req: AdvanceEncounterTurnRequest):
    _require_campaign(campaign_id)
    store = _encounters()
    encounter = store.get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")
    updated = advance_encounter_turn(encounter, note=req.note)
    store.save(updated)
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        actor_name="GM",
        action_type="encounter_turn_advance",
        source="encounter",
        summary=updated.encounter_log[-1] if updated.encounter_log else "Encounter turn advanced.",
        details={"encounter": _encounter_dict(updated)},
    ))
    return _encounter_dict(updated)


@router.post("/{campaign_id}/encounters/{encounter_id}/complete")
def complete_campaign_encounter(campaign_id: str, encounter_id: str, req: CompleteEncounterRequest):
    _require_campaign(campaign_id)
    store = _encounters()
    encounter = store.get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    updated = complete_encounter(encounter, summary=req.summary)
    synced_participants = _sync_all_encounter_participants_to_sheets(campaign_id, updated)
    store.save(updated)
    treasure_bundle = None
    player_sheet_payload = None
    if req.generate_treasure:
        challenge_rating = (
            validate_non_negative_int(req.treasure_challenge_rating, "treasure_challenge_rating")
            if req.treasure_challenge_rating is not None
            else max(1, len([participant for participant in updated.participants if participant.team == "enemy"]))
        )
        treasure_bundle = generate_treasure_bundle(
            challenge_rating=challenge_rating,
            source_type="encounter",
            source_name=updated.name,
        )
        if req.apply_treasure_to_player:
            player_sheet_payload = _apply_treasure_bundle_to_player(campaign_id, treasure_bundle)

    details = {
        "encounter": _encounter_dict(updated),
        "sheet_sync": synced_participants,
        "treasure": treasure_bundle,
        "player_sheet": player_sheet_payload,
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        actor_name="GM",
        action_type="encounter_complete",
        source="encounter",
        summary=updated.summary or "Encounter completed.",
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        event_type="encounter_complete",
        actor_name="GM",
        source="encounter",
        reason=req.summary,
        payload=details,
    )
    payload = _encounter_dict(updated)
    payload["sheet_sync"] = synced_participants
    payload["generated_summary"] = generate_encounter_summary(updated)
    payload["treasure"] = treasure_bundle
    payload["player_sheet"] = player_sheet_payload
    return payload


@router.post("/{campaign_id}/encounters/{encounter_id}/movement")
def spend_campaign_encounter_movement(campaign_id: str, encounter_id: str, req: SpendEncounterMovementRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")
    if not encounter.participants or not (0 <= encounter.current_turn_index < len(encounter.participants)):
        raise HTTPException(400, "Encounter has no active participant")

    try:
        distance = validate_non_negative_int(req.distance, "distance")
        current = encounter.participants[encounter.current_turn_index]
        updated, participant = spend_participant_movement(
            encounter,
            participant_id=current.id,
            distance=distance,
            note=req.note or f"{current.name} moves {distance} feet.",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    _encounters().save(updated)
    summary = f"{participant.name} moves {distance} feet and has {participant.movement_remaining} feet remaining."
    scene_id = updated.scene_id
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene_id,
        actor_name=participant.name,
        action_type="movement",
        source="encounter",
        summary=summary,
        details={
            "distance": distance,
            "movement_remaining": participant.movement_remaining,
            "encounter": _encounter_dict(updated),
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type="movement",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={
            "distance": distance,
            "movement_remaining": participant.movement_remaining,
            "encounter": _encounter_dict(updated),
        },
    )
    return {
        "summary": summary,
        "participant": participant.model_dump(),
        "encounter": _encounter_dict(updated),
    }


@router.post("/{campaign_id}/encounters/{encounter_id}/reaction")
def use_campaign_encounter_reaction(campaign_id: str, encounter_id: str, req: UseEncounterReactionRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")
    if not encounter.participants:
        raise HTTPException(400, "Encounter has no participants")

    target_participant = None
    if req.participant_id:
        target_participant = next((p for p in encounter.participants if p.id == req.participant_id), None)
    else:
        target_participant = next((p for p in encounter.participants if p.owner_type == "player"), None)
    if not target_participant:
        raise HTTPException(404, "Encounter participant not found")

    try:
        updated, participant = consume_participant_action(
            encounter,
            participant_id=target_participant.id,
            cost="reaction",
            note=req.note or f"{target_participant.name} uses their reaction.",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    _encounters().save(updated)
    summary = f"{participant.name} uses their reaction."
    scene_id = updated.scene_id
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene_id,
        actor_name=participant.name,
        action_type="reaction",
        source="encounter",
        summary=summary,
        details={
            "participant_id": participant.id,
            "reaction_available": participant.reaction_available,
            "encounter": _encounter_dict(updated),
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type="reaction",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={
            "participant_id": participant.id,
            "reaction_available": participant.reaction_available,
            "encounter": _encounter_dict(updated),
        },
    )
    return {
        "summary": summary,
        "participant": participant.model_dump(),
        "encounter": _encounter_dict(updated),
    }


@router.post("/{campaign_id}/encounters/{encounter_id}/conditions")
def apply_campaign_encounter_condition(campaign_id: str, encounter_id: str, req: ApplyEncounterConditionRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")

    try:
        duration_rounds = (
            validate_positive_int(req.duration_rounds, "duration_rounds")
            if req.duration_rounds is not None
            else None
        )
        updated, participant = apply_condition_to_participant(
            encounter,
            participant_id=req.participant_id,
            condition=req.condition,
            duration_rounds=duration_rounds,
            note=req.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    _encounters().save(updated)
    summary = f"{participant.name} gains {req.condition.strip().lower()}."
    if duration_rounds is not None:
        summary = f"{summary[:-1]} for {duration_rounds} rounds."
    scene_id = updated.scene_id
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene_id,
        actor_name=participant.name,
        action_type="condition",
        source="encounter",
        summary=summary,
        details={
            "condition": req.condition.strip().lower(),
            "duration_rounds": duration_rounds,
            "conditions": participant.conditions,
            "condition_durations": participant.condition_durations,
            "encounter": _encounter_dict(updated),
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type="condition",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={
            "condition": req.condition.strip().lower(),
            "duration_rounds": duration_rounds,
            "conditions": participant.conditions,
            "condition_durations": participant.condition_durations,
            "encounter": _encounter_dict(updated),
        },
    )
    return {
        "summary": summary,
        "participant": participant.model_dump(),
        "encounter": _encounter_dict(updated),
    }


@router.post("/{campaign_id}/encounters/{encounter_id}/stabilize")
def stabilize_campaign_encounter_participant(campaign_id: str, encounter_id: str, req: StabilizeEncounterParticipantRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")

    try:
        updated, participant = stabilize_participant(
            encounter,
            participant_id=req.participant_id,
            note=req.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    _encounters().save(updated)
    scene_id = updated.scene_id
    summary = f"{participant.name} is stabilized."
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=scene_id,
        actor_name=participant.name,
        action_type="stabilize",
        source="encounter",
        summary=summary,
        details={
            "participant_id": participant.id,
            "life_state": participant.life_state,
            "conditions": participant.conditions,
            "encounter": _encounter_dict(updated),
        },
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type="stabilize",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={
            "participant_id": participant.id,
            "life_state": participant.life_state,
            "conditions": participant.conditions,
            "encounter": _encounter_dict(updated),
        },
    )
    return {
        "summary": summary,
        "participant": participant.model_dump(),
        "encounter": _encounter_dict(updated),
    }


@router.post("/{campaign_id}/encounters/{encounter_id}/concentration")
def set_campaign_encounter_concentration(campaign_id: str, encounter_id: str, req: SetEncounterConcentrationRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")
    try:
        updated, participant = set_participant_concentration(
            encounter,
            participant_id=req.participant_id,
            label=req.label,
            active=req.active,
            note=req.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _encounters().save(updated)
    summary = (
        f"{participant.name} begins concentrating on {participant.concentration_label}."
        if req.active else
        f"{participant.name} stops concentrating."
    )
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        actor_name=participant.name,
        action_type="concentration",
        source="encounter",
        summary=summary,
        details={"participant_id": participant.id, "concentration_label": participant.concentration_label, "encounter": _encounter_dict(updated)},
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        event_type="concentration",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={"participant_id": participant.id, "concentration_label": participant.concentration_label, "encounter": _encounter_dict(updated)},
    )
    return {"summary": summary, "participant": participant.model_dump(), "encounter": _encounter_dict(updated)}


@router.post("/{campaign_id}/encounters/{encounter_id}/concentration-check")
def resolve_campaign_encounter_concentration_check(campaign_id: str, encounter_id: str, req: ResolveEncounterConcentrationCheckRequest):
    _require_campaign(campaign_id)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")
    try:
        updated, participant = resolve_participant_concentration_check(
            encounter,
            participant_id=req.participant_id,
            success=req.success,
            note=req.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _encounters().save(updated)
    summary = (
        f"{participant.name} maintains concentration."
        if req.success else
        f"{participant.name} loses concentration."
    )
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        actor_name=participant.name,
        action_type="concentration_check",
        source="encounter",
        summary=summary,
        details={"participant_id": participant.id, "success": req.success, "concentration_label": participant.concentration_label, "encounter": _encounter_dict(updated)},
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=updated.scene_id,
        event_type="concentration_check",
        actor_name=participant.name,
        source="encounter",
        reason=req.note,
        payload={"participant_id": participant.id, "success": req.success, "concentration_label": participant.concentration_label, "encounter": _encounter_dict(updated)},
    )
    return {"summary": summary, "participant": participant.model_dump(), "encounter": _encounter_dict(updated)}


@router.post("/{campaign_id}/encounters/{encounter_id}/use-compendium")
def use_campaign_encounter_compendium_entry(campaign_id: str, encounter_id: str, req: UseEncounterCompendiumEntryRequest):
    campaign = _require_campaign(campaign_id)
    _require_d20_rules_mode(campaign)
    encounter = _encounters().get(encounter_id)
    if not encounter or encounter.campaign_id != campaign_id:
        raise HTTPException(404, "Encounter not found")
    if encounter.status != "active":
        raise HTTPException(400, "Encounter is not active")

    entry = _compendium_store().get(req.slug, system_pack=campaign.system_pack)
    if not entry:
        raise HTTPException(404, "Compendium entry not found")

    actor = None
    if req.actor_participant_id:
        actor = next((participant for participant in encounter.participants if participant.id == req.actor_participant_id), None)
    elif 0 <= encounter.current_turn_index < len(encounter.participants):
        actor = encounter.participants[encounter.current_turn_index]
    if not actor:
        raise HTTPException(404, "Encounter actor not found")

    encounter_after = encounter
    if entry.action_cost:
        try:
            encounter_after, actor = consume_participant_action(
                encounter_after,
                participant_id=actor.id,
                cost=entry.action_cost,
                note=req.note or f"{actor.name} uses {entry.name}.",
            )
        except ValueError as e:
            raise HTTPException(400, str(e))

    actor_sheet = _sheets().get_for_owner(campaign_id, actor.owner_type, actor.owner_id or ("player" if actor.owner_type == "player" else actor.owner_id))
    if entry.category == "spell" and entry.resource_costs:
        prepared_spells = [str(spell).strip().lower() for spell in (actor_sheet.prepared_spells if actor_sheet else [])]
        if entry.slug not in prepared_spells:
            raise HTTPException(400, f"{actor.name} has not prepared {entry.name}")
    actor_sheet, consumed_resources = _apply_resource_costs(campaign_id, actor_sheet, entry.resource_costs)

    summary = f"{actor.name} uses {entry.name}."
    targets: list[dict] = []

    if entry.slug == "dash":
        encounter_after, actor = grant_participant_movement(
            encounter_after,
            participant_id=actor.id,
            distance=int(actor.speed or 0),
            note=req.note or f"{actor.name} takes the Dash action.",
        )
        summary = f"{actor.name} dashes and now has {actor.movement_remaining} feet of movement available."
    elif entry.slug == "disengage":
        encounter_after, actor = apply_condition_to_participant(
            encounter_after,
            participant_id=actor.id,
            condition="disengaging",
            duration_rounds=1,
            note=req.note or f"{actor.name} takes the Disengage action.",
        )
        summary = f"{actor.name} disengages and can reposition more safely this turn."
        _sync_encounter_participant_to_sheet(campaign_id, actor.model_dump())
    elif entry.slug == "dodge":
        encounter_after, actor = apply_condition_to_participant(
            encounter_after,
            participant_id=actor.id,
            condition="dodging",
            duration_rounds=1,
            note=req.note or f"{actor.name} takes the Dodge action.",
        )
        summary = f"{actor.name} is dodging until their next turn."
        _sync_encounter_participant_to_sheet(campaign_id, actor.model_dump())
    elif entry.slug == "bless":
        bless_targets = req.target_participant_ids or [actor.id]
        encounter_after, actor = set_participant_concentration(
            encounter_after,
            participant_id=actor.id,
            label=entry.name,
            active=True,
            note=req.note or f"{actor.name} begins concentrating on {entry.name}.",
        )
        for target_id in bless_targets[:3]:
            encounter_after, target = apply_condition_to_participant(
                encounter_after,
                participant_id=target_id,
                condition="blessed",
                duration_rounds=10,
                note=f"{entry.name} blesses {next((p.name for p in encounter_after.participants if p.id == target_id), 'a target')}.",
            )
            target_payload = target.model_dump()
            _sync_encounter_participant_to_sheet(campaign_id, target_payload)
            targets.append(target_payload)
        summary = f"{actor.name} casts {entry.name} on {', '.join(target['name'] for target in targets) or actor.name}."
    elif entry.slug == "help":
        helped_targets = req.target_participant_ids or [actor.id]
        for target_id in helped_targets[:1]:
            encounter_after, target = apply_condition_to_participant(
                encounter_after,
                participant_id=target_id,
                condition="helped",
                duration_rounds=1,
                note=f"{actor.name} uses {entry.name} to assist {next((p.name for p in encounter_after.participants if p.id == target_id), 'a target')}.",
            )
            target_payload = target.model_dump()
            _sync_encounter_participant_to_sheet(campaign_id, target_payload)
            targets.append(target_payload)
        target_name = targets[0]["name"] if targets else actor.name
        summary = f"{actor.name} uses {entry.name} to aid {target_name}."
    elif entry.slug == "second-wind":
        healing_result = resolve_healing_roll(
            source=entry.name,
            roll_expression=entry.roll_expression or "1d10",
            modifier=entry.modifier,
            reason=req.note or f"{actor.name} uses {entry.name}.",
        )
        encounter_after, actor = apply_healing_to_participant(
            encounter_after,
            participant_id=actor.id,
            healing_total=healing_result.total,
            note=req.note or f"{actor.name} uses {entry.name}.",
        )
        actor_payload = actor.model_dump()
        _sync_encounter_participant_to_sheet(campaign_id, actor_payload)
        targets.append(actor_payload)
        summary = f"{actor.name} uses {entry.name} and regains {healing_result.total} HP."
    elif entry.slug == "healing-word":
        target_ids = req.target_participant_ids or [actor.id]
        healing_target = next((participant for participant in encounter_after.participants if participant.id == target_ids[0]), None)
        if not healing_target:
            raise HTTPException(404, "Healing target not found")
        healing_result = resolve_healing_roll(
            source=entry.name,
            roll_expression=entry.roll_expression or "1d4",
            modifier=entry.modifier,
            reason=req.note or f"{actor.name} casts {entry.name}.",
        )
        encounter_after, target = apply_healing_to_participant(
            encounter_after,
            participant_id=healing_target.id,
            healing_total=healing_result.total,
            note=req.note or f"{actor.name} casts {entry.name}.",
        )
        target_payload = target.model_dump()
        _sync_encounter_participant_to_sheet(campaign_id, target_payload)
        targets.append(target_payload)
        summary = f"{actor.name} casts {entry.name} on {target.name}, restoring {healing_result.total} HP."
    elif entry.slug == "cure-wounds":
        target_ids = req.target_participant_ids or [actor.id]
        healing_target = next((participant for participant in encounter_after.participants if participant.id == target_ids[0]), None)
        if not healing_target:
            raise HTTPException(404, "Healing target not found")
        healing_result = resolve_healing_roll(
            source=entry.name,
            roll_expression=entry.roll_expression or "1d8",
            modifier=entry.modifier,
            reason=req.note or f"{actor.name} casts {entry.name}.",
        )
        encounter_after, target = apply_healing_to_participant(
            encounter_after,
            participant_id=healing_target.id,
            healing_total=healing_result.total,
            note=req.note or f"{actor.name} casts {entry.name}.",
        )
        target_payload = target.model_dump()
        _sync_encounter_participant_to_sheet(campaign_id, target_payload)
        targets.append(target_payload)
        summary = f"{actor.name} casts {entry.name} on {target.name}, restoring {healing_result.total} HP."
    elif entry.slug == "magic-missile":
        target_ids = req.target_participant_ids or []
        resolved_targets = [
            participant for participant in encounter_after.participants
            if participant.id in target_ids
        ]
        if not resolved_targets:
            resolved_targets = [
                participant for participant in encounter_after.participants
                if participant.team != actor.team
            ][:1]
        if not resolved_targets:
            raise HTTPException(400, "Magic Missile requires at least one hostile encounter target")
        missile_damage_events: list[dict] = []
        for missile_index in range(3):
            target = resolved_targets[missile_index % len(resolved_targets)]
            damage_result = resolve_damage_roll(
                source=f"{entry.name} dart {missile_index + 1}",
                roll_expression="1d4",
                modifier=1,
                damage_type="force",
                critical_hit=False,
            )
            encounter_after, updated_target = apply_damage_to_participant(
                encounter_after,
                participant_id=target.id,
                damage_total=damage_result.total,
                note=req.note or f"{actor.name} casts {entry.name}.",
            )
            target = updated_target
            target_payload = target.model_dump()
            _sync_encounter_participant_to_sheet(campaign_id, target_payload)
            missile_damage_events.append({
                "target_id": target.id,
                "target_name": target.name,
                "damage": damage_result.model_dump(),
            })
        deduped_targets: dict[str, dict] = {}
        for participant in encounter_after.participants:
            if participant.id in {event["target_id"] for event in missile_damage_events}:
                deduped_targets[participant.id] = participant.model_dump()
        targets.extend(deduped_targets.values())
        total_damage = sum(event["damage"]["total"] for event in missile_damage_events)
        damage_result = {"missiles": missile_damage_events, "total": total_damage, "damage_type": "force"}
        summary = f"{actor.name} casts {entry.name}, dealing {total_damage} force damage across {len(deduped_targets)} target(s)."
    elif entry.slug == "healing-wand":
        if not actor_sheet:
            raise HTTPException(400, f"{actor.name} does not have a character sheet to track item charges")
        equipped_values = list((actor_sheet.equipped_items or {}).values())
        if entry.slug not in equipped_values:
            raise HTTPException(400, f"{actor.name} does not have {entry.name} equipped")
        item_charges = dict(actor_sheet.item_charges or {})
        charge_state = dict(item_charges.get(entry.slug) or {})
        current_charges = int(charge_state.get("current", entry.charges_max or 0) or 0)
        max_charges = int(charge_state.get("max", entry.charges_max or 0) or 0)
        if current_charges <= 0:
            raise HTTPException(400, f"{entry.name} has no charges remaining")
        charge_state["current"] = current_charges - 1
        charge_state["max"] = max_charges
        charge_state["restores_on"] = str(charge_state.get("restores_on", entry.restores_on or "") or "")
        item_charges[entry.slug] = charge_state
        actor_sheet = _sheets().save_for_owner(
            campaign_id,
            actor.owner_type,
            actor.owner_id or ("player" if actor.owner_type == "player" else actor.owner_id),
            item_charges=item_charges,
        )
        target_ids = req.target_participant_ids or [actor.id]
        healing_target = next((participant for participant in encounter_after.participants if participant.id == target_ids[0]), None)
        if not healing_target:
            raise HTTPException(404, "Healing target not found")
        healing_result = resolve_healing_roll(
            source=entry.name,
            roll_expression=entry.roll_expression or "2d4",
            modifier=entry.modifier,
            reason=req.note or f"{actor.name} uses {entry.name}.",
        )
        encounter_after, target = apply_healing_to_participant(
            encounter_after,
            participant_id=healing_target.id,
            healing_total=healing_result.total,
            note=req.note or f"{actor.name} uses {entry.name}.",
        )
        target_payload = target.model_dump()
        _sync_encounter_participant_to_sheet(campaign_id, target_payload)
        targets.append(target_payload)
        consumed_resources.append({
            "resource": f"{entry.slug}_charge",
            "amount": 1,
            "remaining": charge_state["current"],
            "max": charge_state["max"],
        })
        summary = f"{actor.name} uses {entry.name} on {target.name}, restoring {healing_result.total} HP."
    else:
        raise HTTPException(400, f"No encounter execution mapping exists yet for compendium entry '{entry.slug}'")

    _encounters().save(encounter_after)
    details = {
        "entry": _compendium_entry_dict(entry),
        "actor": actor.model_dump(),
        "targets": targets,
        "resources_consumed": consumed_resources,
        "damage": damage_result if 'damage_result' in locals() else None,
        "healing": healing_result.model_dump() if 'healing_result' in locals() else None,
        "encounter": _encounter_dict(encounter_after),
    }
    _action_logs().save(ActionLogEntry(
        campaign_id=campaign_id,
        scene_id=encounter_after.scene_id,
        actor_name=actor.name,
        action_type="compendium_action",
        source=entry.slug,
        summary=summary,
        details=details,
    ))
    _record_rule_audit(
        campaign_id=campaign_id,
        scene_id=encounter_after.scene_id,
        event_type="compendium_action",
        actor_name=actor.name,
        source=entry.slug,
        reason=req.note,
        payload=details,
    )
    return {
        "summary": summary,
        "entry": _compendium_entry_dict(entry),
        "actor": actor.model_dump(),
        "targets": targets,
        "resources_consumed": consumed_resources,
        "damage": damage_result if 'damage_result' in locals() else None,
        "healing": healing_result.model_dump() if 'healing_result' in locals() else None,
        "encounter": _encounter_dict(encounter_after),
    }


@router.get("/{campaign_id}/action-logs")
def get_action_logs(campaign_id: str, n: int = 20):
    _require_campaign(campaign_id)
    return [_action_log_dict(a) for a in _action_logs().get_recent(campaign_id, n=n)]


@router.get("/{campaign_id}/rule-audits")
def get_rule_audits(campaign_id: str, n: int = 50):
    _require_campaign(campaign_id)
    return [_rule_audit_dict(event) for event in _rule_audits().get_recent(campaign_id, n=n)]


@router.get("/{campaign_id}/scenes/{scene_id}/gm-decisions")
def get_scene_gm_decisions(campaign_id: str, scene_id: str, n: int = 20):
    _require_campaign(campaign_id)
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    events = _rule_audits().get_recent_filtered(
        campaign_id,
        scene_id=scene_id,
        event_type="gm_decision",
        n=n,
    )
    return [_rule_audit_dict(event) for event in events]


# ── Scene chat (streaming) ────────────────────────────────────────────────────

class SceneChatRequest(BaseModel):
    message: str
    user_name: str = "Player"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class SceneOpenRequest(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class SceneRegenerateRequest(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None


class SceneMechanicsFollowupRequest(BaseModel):
    prompt: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class ReplaceLastAssistantRequest(BaseModel):
    content: str


class GMProcedurePreviewRequest(BaseModel):
    message: str


@router.post("/{campaign_id}/scenes/{scene_id}/gm-procedure-preview")
def get_scene_gm_procedure_preview(campaign_id: str, scene_id: str, req: GMProcedurePreviewRequest):
    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    plan = build_gm_procedure_plan(req.message)
    decision = build_gm_decision_preview(req.message)
    suggested_actions = build_gm_suggested_actions(
        decision,
        user_message=req.message,
        system_pack=campaign.system_pack,
    )
    recent_decisions = _rule_audits().get_recent_filtered(
        campaign_id,
        scene_id=scene_id,
        event_type="gm_decision",
        n=5,
    )
    return {
        "scene_id": scene_id,
        "campaign_id": campaign_id,
        "play_mode": campaign.play_mode.value if hasattr(campaign.play_mode, "value") else str(campaign.play_mode),
        "plan": plan.model_dump(),
        "suggested_decision": decision.model_dump(),
        "suggested_actions": [action.model_dump() for action in suggested_actions],
        "recent_gm_decisions": [_rule_audit_dict(event) for event in recent_decisions],
    }


@router.post("/{campaign_id}/scenes/{scene_id}/mechanics-followup")
def scene_mechanics_followup_stream(campaign_id: str, scene_id: str, req: SceneMechanicsFollowupRequest):
    """
    Stream a hidden follow-up narration pass after a mechanic has been resolved.
    Does not create a user turn; persists only the assistant narration.
    """
    import json as _json
    import httpx

    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")

    pc = _pcs().get(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    objectives_list = _objectives().get_active(campaign_id)
    quests_list = _quests().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids) if scene.npc_ids else []
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []
    recent_action_logs = _action_logs().get_recent_for_scene(campaign_id, scene.id, n=6)

    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        character_sheet=sheet,
        recent_action_logs=recent_action_logs,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        objectives=objectives_list,
        quests=quests_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=(
            "[A mechanic has just been resolved. Continue the narration from that established outcome. "
            "Treat the following result as already true in the fiction and describe its immediate consequences "
            "without restating hidden process or asking for the same roll again.]\n\n"
            f"{req.prompt}"
        ),
        user_name="",
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature = req.temperature if req.temperature is not None else gs.temperature
    top_p = req.top_p if req.top_p is not None else gs.top_p
    top_k = req.top_k if req.top_k is not None else gs.top_k
    min_p = req.min_p if req.min_p is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens = req.max_tokens if req.max_tokens is not None else gs.max_tokens
    seed = req.seed if req.seed is not None else gs.seed

    def _stream():
        full_response: list[str] = []
        visible_buffer = ""
        saw_contract = False
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        emit, visible_buffer, saw_contract = _consume_visible_stream_delta(visible_buffer, delta, saw_contract)
                        if emit:
                            yield emit
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        if not saw_contract and visible_buffer:
            yield visible_buffer
        envelope = parse_gm_response_envelope("".join(full_response))
        scene.turns.append(SceneTurn(role="assistant", content=envelope.visible_text))
        scene_store.save(scene)
        _record_rule_audit(
            campaign_id=campaign_id,
            scene_id=scene.id,
            event_type="mechanics_followup",
            actor_name="GM",
            source="narration",
            reason=req.prompt,
            payload={"visible_text": envelope.visible_text},
        )
        _record_gm_envelope_audits(
            campaign_id=campaign_id,
            scene_id=scene.id,
            reason=req.prompt,
            envelope=envelope,
        )

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/{campaign_id}/scenes/{scene_id}/open")
def scene_open_stream(campaign_id: str, scene_id: str, req: SceneOpenRequest):
    """
    Stream the AI narrator's opening narration for a newly started scene.
    Uses a hidden system-level prompt — no user turn is stored.
    Only the assistant response is persisted to the scene.
    """
    import json as _json
    import httpx

    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    pc = _pcs().get(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    objectives_list = _objectives().get_active(campaign_id)
    quests_list = _quests().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    npc_rels_list = (
        _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
        if scene.npc_ids else []
    )
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []
    recent_action_logs = _action_logs().get_recent_for_scene(campaign_id, scene.id, n=6)

    # Build messages with a hidden opening prompt (not stored as a user turn)
    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        character_sheet=sheet,
        recent_action_logs=recent_action_logs,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        objectives=objectives_list,
        quests=quests_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=(
            "[Scene begins. Narrate the opening of this scene. Set the mood, "
            "describe the environment, and establish the situation. Do not wait "
            "for the player — begin the story now.]"
        ),
        user_name="",  # suppresses name prefix so it reads as a system cue
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    def _stream():
        full_response: list[str] = []
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        emit, visible_buffer, saw_contract = _consume_visible_stream_delta(visible_buffer, delta, saw_contract)
                        if emit:
                            yield emit
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        if not saw_contract and visible_buffer:
            yield visible_buffer
        envelope = parse_gm_response_envelope("".join(full_response))
        # Persist only the visible assistant turn
        scene.turns.append(SceneTurn(role="assistant", content=envelope.visible_text))
        scene_store.save(scene)
        _record_gm_envelope_audits(
            campaign_id=campaign_id,
            scene_id=scene.id,
            reason="scene_open",
            envelope=envelope,
        )

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/{campaign_id}/scenes/{scene_id}/chat")
def scene_chat_stream(campaign_id: str, scene_id: str, req: SceneChatRequest):
    """
    Stream the AI narrator response for one turn of scene play.
    Stores the user turn and AI response in the scene's turn list.
    """
    import json as _json
    import httpx

    # Load all context
    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")

    pc = _pcs().get(campaign_id)
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    objectives_list = _objectives().get_active(campaign_id)
    quests_list = _quests().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)

    # Resolve NPC cards present in this scene
    npc_list = []
    npc_rels_list = []
    if scene.npc_ids:
        npc_list = _npcs().get_many(scene.npc_ids)
        npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []
    recent_action_logs = _action_logs().get_recent_for_scene(campaign_id, scene.id, n=6)

    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        character_sheet=sheet,
        recent_action_logs=recent_action_logs,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        objectives=objectives_list,
        quests=quests_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=req.message,
        user_name=req.user_name,
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    # Store user turn first (before streaming)
    scene.turns.append(SceneTurn(role="user", content=req.message))

    def _stream():
        full_response: list[str] = []
        visible_buffer = ""
        saw_contract = False
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        emit, visible_buffer, saw_contract = _consume_visible_stream_delta(visible_buffer, delta, saw_contract)
                        if emit:
                            yield emit
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        if not saw_contract and visible_buffer:
            yield visible_buffer
        envelope = parse_gm_response_envelope("".join(full_response))
        # Persist both turns to the scene, using only the visible assistant text
        scene.turns.append(SceneTurn(role="assistant", content=envelope.visible_text))
        scene_store.save(scene)
        _record_gm_envelope_audits(
            campaign_id=campaign_id,
            scene_id=scene.id,
            reason=req.message,
            envelope=envelope,
        )

    return StreamingResponse(_stream(), media_type="text/plain")


# ── Post-scene AI tools ───────────────────────────────────────────────────────

_SUGGEST_SUMMARY_SYSTEM = """You are a transcript indexer. Your only job is to extract events from a numbered roleplay transcript and list them, one per line, with the turn number they came from.

CRITICAL RULES:
- You are NOT a storyteller. Do NOT write fiction, narration, or creative prose.
- You are NOT a narrator or character. The scene is FINISHED — do not continue it.
- Every line you write MUST cite the exact turn number it came from using [Turn N].
- If you cannot point to a specific turn that supports a claim, you MUST NOT include it.
- Do NOT infer, speculate, or add ANY detail not explicitly present in the cited turn.
- Do NOT merge or paraphrase multiple turns into one statement — cite only one turn per line.
- Do NOT embellish, add atmosphere, or use creative language.

Output format — one line per event, strictly:
- [Turn N] Past-tense statement of exactly what happened in that turn.

Work chronologically from Turn 1 to the last turn. Include every significant action, statement, decision, and outcome. Omit only trivial filler with no story consequence.
Output ONLY the list — no title, no preamble, no closing sentence."""

_SUGGEST_UPDATES_SYSTEM = """Extract world-document entries from a completed roleplay scene.

TASK: Read the transcript and summary, then output a JSON object cataloguing every character, place, fact, transformation, and relationship development worth recording. The player reviews every entry and approves or rejects — err heavily toward including MORE, not less.

CRITICAL OUTPUT RULE: Your response must be ONLY the JSON object below. No thinking prose outside the JSON. No markdown. No explanation. Begin your response with { and end with }.

REQUIRED JSON FORMAT (all seven keys must be present, use [] if nothing qualifies):
{
  "new_npcs": [
    {"name":"...", "role":"...", "gender":"...", "age":"...", "appearance":"(hair colour, eye colour, build, clothing, distinguishing features)", "personality":"...", "relationship_to_player":"...", "current_location":"...", "current_state":"...", "short_term_goal":"...", "long_term_goal":"...", "secrets":"(hidden backstory, concealed motives, or unknown truths about them)", "significance":"..."}
  ],
  "new_locations": [
    {"name":"...", "description":"...", "current_state":"...", "significance":"..."}
  ],
  "new_facts": [
    {"content":"...", "reason":"..."}
  ],
  "npc_updates": [
    {"npc_id":"exact-uuid", "npc_name":"...", "field":"current_state", "current_value":"...", "suggested_value":"...", "reason":"..."}
  ],
  "thread_updates": [
    {"thread_id":"exact-uuid", "thread_title":"...", "new_status":"resolved", "reason":"..."}
  ],
  "history_updates": [
    {"npc_id":"exact-uuid", "npc_name":"...", "addition":"one-sentence summary of what happened between this NPC and the player in this scene", "reason":"..."}
  ],
  "form_transitions": [
    {"npc_id":"exact-uuid", "npc_name":"...", "new_form_label":"...", "new_appearance":"...", "new_personality":"...", "new_current_state":"...", "reason":"..."}
  ]
}

WHAT TO EXTRACT:

new_npcs: Every character who appears in the scene AND is not in the CURRENT NPCs list. Fill every field as completely as possible — infer appearance and personality from descriptions and dialogue; put concealed backstory in "secrets".

new_locations: Every named or described place visited or mentioned in the scene that is not in the CURRENT LOCATIONS list.

new_facts: Every revelation, secret, lore detail, rule of the world, plot twist, or piece of backstory established in this scene.

npc_updates: Changes to characters already in the CURRENT NPCs list. Valid fields: current_state, is_alive, current_location. Match by the exact uuid shown.

thread_updates: Narrative threads already in the list that were resolved or went dormant. Match by exact uuid.

history_updates: For any NPC in the CURRENT NPCs list who had a meaningful interaction with the player in this scene — add a brief note to their history. One entry per NPC, one sentence. Only include if something significant happened (trust gained/lost, secret shared, conflict, alliance, etc.).

form_transitions: If any NPC in the CURRENT NPCs list visibly changed their physical form, appearance, or fundamental personality during this scene (transformation, shapeshifting, corruption, revealed disguise, possession, etc.) — record the new form. Leave new_form_label short and descriptive (e.g. "Wolf Form", "Corrupted", "True Form").

EXAMPLE — given a scene where Oren (already in the NPC list) revealed a dragon collar secret to the player, then transformed into a wolf at scene's end, the correct output includes:
{"new_npcs":[],"new_locations":[],"new_facts":[{"content":"Dragons are controlled by magical collars; removing the collar frees them.","reason":"Oren revealed this to the player"}],"npc_updates":[],"thread_updates":[],"history_updates":[{"npc_id":"oren-uuid","npc_name":"Oren","addition":"Shared the secret of dragon collars with the player, revealing his true nature as a shapeshifter.","reason":"Major trust moment and revelation"}],"form_transitions":[{"npc_id":"oren-uuid","npc_name":"Oren","new_form_label":"Wolf Form","new_appearance":"massive grey wolf, amber eyes, a scar across the left flank","new_personality":"primal, protective, still recognises the player","new_current_state":"transformed, guarding the forge entrance","reason":"Transformed at scene end when threatened"}]}"""


class SuggestSummaryRequest(BaseModel):
    model_name: Optional[str] = None


class GodPromptRequest(BaseModel):
    instruction: str
    model_name: Optional[str] = None


class SuggestSceneRequest(BaseModel):
    hint: str = ""
    model_name: Optional[str] = None


_SUMMARY_CHUNK_SIZE = 12  # turns per extraction call


@router.post("/{campaign_id}/scenes/{scene_id}/suggest-summary")
def suggest_scene_summary(campaign_id: str, scene_id: str, req: SuggestSummaryRequest = None):
    """
    Generate a suggested summary by chunking the transcript into batches of
    _SUMMARY_CHUNK_SIZE turns and extracting events from each chunk separately.
    This prevents early turns being ignored due to attention degradation on long transcripts.
    """
    import httpx
    import re as _re

    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if not scene.turns:
        return {"summary": ""}

    # Exclude silent continue nudges
    visible_turns = [t for t in scene.turns if t.content != "(Continue the story.)"]

    campaign = _campaigns().get(campaign_id)
    model = (req.model_name if req and req.model_name else None) \
            or (getattr(campaign, "summary_model_name", None) if campaign else None) \
            or (campaign.model_name if campaign else None) \
            or config.ollama_model

    def _call(prompt: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUGGEST_SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1024,
                "num_ctx": config.context_window,
            },
        }
        r = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        r.raise_for_status()
        raw = r.json()["message"]["content"]
        return _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()

    # Split into chunks and extract events from each independently
    all_lines: list[str] = []
    total = len(visible_turns)
    try:
        for chunk_start in range(0, total, _SUMMARY_CHUNK_SIZE):
            chunk = visible_turns[chunk_start:chunk_start + _SUMMARY_CHUNK_SIZE]
            chunk_text = "\n\n".join(
                f"[Turn {chunk_start + i + 1} — {'Player' if t.role == 'user' else 'Narrator'}]: {t.content}"
                for i, t in enumerate(chunk)
            )
            first_turn = chunk_start + 1
            last_turn = chunk_start + len(chunk)
            prompt = (
                f"Scene title: {scene.title or 'Untitled'}\n"
                f"Location: {scene.location or 'Unknown'}\n"
                f"This is turns {first_turn}–{last_turn} of {total} total.\n\n"
                f"TRANSCRIPT EXCERPT:\n\n{chunk_text}\n\n"
                f"--- END OF EXCERPT ---\n\n"
                f"List every significant event from ONLY these turns, one per line with its turn number. "
                f"Only include what is explicitly stated above. Begin:"
            )
            chunk_result = _call(prompt)
            # Collect non-empty lines that look like bullet entries
            for line in chunk_result.splitlines():
                line = line.strip()
                if line and (line.startswith("-") or line.startswith("[")):
                    all_lines.append(line)
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "Summary generation timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"Summary generation failed: {e}")

    return {"summary": "\n".join(all_lines)}


@router.post("/{campaign_id}/scenes/{scene_id}/suggest-updates")
def suggest_world_updates(campaign_id: str, scene_id: str):
    """
    After a scene is confirmed, suggest world document updates based on what happened.
    Returns structured suggestions the player can approve/reject.
    """
    import json as _json
    import httpx
    from app.campaigns.world_builder import _extract_json

    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    npcs = _npcs().get_all(campaign_id)
    threads = _threads().get_all(campaign_id)
    places = _places().get_all(campaign_id)

    # Build world state snapshot for context
    npc_lines = [
        f"• {n.name} (id={n.id}) — role: {n.role or 'unknown'}, "
        f"current_state: \"{n.current_state}\", is_alive: {n.is_alive}, "
        f"location: \"{n.current_location}\""
        for n in npcs
    ]
    thread_lines = [
        f"• {t.title} (id={t.id}) [{t.status.value}]: {t.description}"
        for t in threads
    ]
    place_lines = [
        f"• {p.name}: {p.description}"
        for p in places
    ]
    # Exclude silent continue nudges from transcript
    visible_turns = [t for t in scene.turns if t.content != "(Continue the story.)"]
    transcript_lines = [
        f"[{'Player' if t.role == 'user' else 'Narrator'}]: {t.content}"
        for t in visible_turns
    ]

    # Build prompt — put the content FIRST so the model reads scene before exclusion lists
    parts = []
    if scene.confirmed_summary:
        parts.append(f"[CONFIRMED SCENE SUMMARY]\n{scene.confirmed_summary}")
    if transcript_lines:
        parts.append("[SCENE TRANSCRIPT]\n" + "\n\n".join(transcript_lines))
    if thread_lines:
        parts.append("[ACTIVE NARRATIVE THREADS — update status if resolved/dormant]\n" + "\n".join(thread_lines))
    if npc_lines:
        parts.append("[ALREADY RECORDED NPCs — do NOT add these again]\n" + "\n".join(npc_lines))
    if place_lines:
        parts.append("[ALREADY RECORDED LOCATIONS — do NOT add these again]\n" + "\n".join(place_lines))

    prompt = "\n\n".join(parts) + (
        "\n\nFirst, mentally list every character name (or title/role if unnamed) that appears anywhere in the transcript above. "
        "Then, for each one NOT in the ALREADY RECORDED NPCs list, add a new_npc entry. "
        "Also extract every new location and every plot fact or revelation. "
        "Output ONLY the JSON object starting with {."
    )

    campaign = _campaigns().get(campaign_id)
    model = (getattr(campaign, "summary_model_name", None) if campaign else None) \
            or (campaign.model_name if campaign else None) \
            or config.ollama_model

    log.info("suggest_world_updates: using model=%s for scene=%s", model, scene_id)

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUGGEST_UPDATES_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.5, "num_predict": 8192, "num_ctx": config.context_window},
        }
        r = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "World updates generation timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"World updates generation failed: {e}")

    # Strip <think> blocks before parsing (Qwen3, DeepSeek-R1, etc.)
    import re as _re
    raw = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()

    data = _extract_json(raw)
    has_any = any([data.get("npc_updates"), data.get("new_facts"), data.get("thread_updates"),
                   data.get("new_npcs"), data.get("new_locations"),
                   data.get("history_updates"), data.get("form_transitions")])
    parse_ok = bool(data)

    log.info(
        "suggest_world_updates: model=%s raw_len=%d parse_ok=%s has_any=%s "
        "new_npcs=%d new_locations=%d new_facts=%d npc_updates=%d thread_updates=%d "
        "history_updates=%d form_transitions=%d",
        model, len(raw), parse_ok, has_any,
        len(data.get("new_npcs", [])), len(data.get("new_locations", [])),
        len(data.get("new_facts", [])), len(data.get("npc_updates", [])),
        len(data.get("thread_updates", [])),
        len(data.get("history_updates", [])), len(data.get("form_transitions", [])),
    )
    if not parse_ok:
        log.warning("suggest_world_updates: JSON parse FAILED. Raw (first 3000 chars):\n%s", raw[:3000])
    elif not has_any:
        log.warning("suggest_world_updates: model returned all-empty arrays. Raw (first 3000 chars):\n%s", raw[:3000])

    return {
        "npc_updates": data.get("npc_updates", []),
        "new_facts": data.get("new_facts", []),
        "thread_updates": data.get("thread_updates", []),
        "new_npcs": data.get("new_npcs", []),
        "new_locations": data.get("new_locations", []),
        "history_updates": data.get("history_updates", []),
        "form_transitions": data.get("form_transitions", []),
        "_model": model,
        "_parse_ok": parse_ok,
        "_raw": raw[:2000],   # first 2000 chars for client-side debug panel
    }


# ── God Prompt ─────────────────────────────────────────────────────────────────

_GOD_PROMPT_SYSTEM = """You are a world-state editor for a tabletop roleplaying game campaign. The GM gives you a natural-language instruction and you output a JSON object describing exactly what to change in the world document.

RULES:
- Match existing entities by their exact UUID shown in the context lists below.
- For npc field updates, valid fields: current_state, current_location, relationship_to_player, personality, secrets, is_alive, status, status_reason, short_term_goal, long_term_goal.
- Make only the changes that are clearly requested or logically implied. Do not over-reach.
- If an entity doesn't exist yet, use the create_ arrays. If it exists, use update_. Use delete_ only if explicitly requested.
- Every entry must include a brief "reason" explaining the change.

OUTPUT: A single JSON object with exactly these keys (use [] or "" for anything not needed):
{
  "update_npcs": [
    {"npc_id": "exact-uuid", "npc_name": "...", "field": "current_state", "new_value": "...", "reason": "..."}
  ],
  "create_npcs": [
    {"name": "...", "role": "...", "appearance": "...", "personality": "...", "relationship_to_player": "...", "current_state": "...", "short_term_goal": "...", "secrets": "...", "reason": "..."}
  ],
  "delete_npcs": [
    {"npc_id": "exact-uuid", "npc_name": "...", "reason": "..."}
  ],
  "create_facts": [
    {"content": "...", "reason": "..."}
  ],
  "update_facts": [
    {"fact_id": "exact-uuid", "old_content": "...", "new_content": "...", "reason": "..."}
  ],
  "delete_facts": [
    {"fact_id": "exact-uuid", "content": "...", "reason": "..."}
  ],
  "create_threads": [
    {"title": "...", "description": "...", "reason": "..."}
  ],
  "update_threads": [
    {"thread_id": "exact-uuid", "title": "...", "new_status": "active|dormant|resolved", "description": "...", "resolution": "...", "reason": "..."}
  ],
  "delete_threads": [
    {"thread_id": "exact-uuid", "title": "...", "reason": "..."}
  ],
  "create_quests": [
    {"title": "...", "description": "...", "giver_npc_name": "...", "importance": "low|medium|high", "reason": "..."}
  ],
  "update_quests": [
    {"quest_id": "exact-uuid", "title": "...", "new_status": "active|completed|abandoned", "reason": "..."}
  ],
  "create_places": [
    {"name": "...", "description": "...", "current_state": "...", "reason": "..."}
  ],
  "update_places": [
    {"place_id": "exact-uuid", "name": "...", "field": "description|current_state", "new_value": "...", "reason": "..."}
  ],
  "create_factions": [
    {"name": "...", "description": "...", "goals": "...", "standing_with_player": "...", "reason": "..."}
  ],
  "update_factions": [
    {"faction_id": "exact-uuid", "name": "...", "field": "description|goals|standing_with_player|relationship_notes", "new_value": "...", "reason": "..."}
  ],
  "narrative_note": "One sentence summarising what was changed and why."
}

Output ONLY the JSON object. No preamble, no explanation outside the JSON."""

_SUGGEST_SCENE_SYSTEM = """You are a creative director for a tabletop roleplaying game. Your job is to design a compelling next scene that naturally continues the story.

You will receive:
- Current world state (NPCs, narrative threads, world facts, places)
- Recent story history (chronicle entries, last scene summary)
- A hint from the player about what they want next (may be vague or "surprise me")

OUTPUT: A single JSON object with exactly these keys:
{
  "title": "Evocative scene title",
  "location": "Specific location name or description",
  "npc_ids": ["exact-uuid", "exact-uuid"],
  "intent": "1-2 sentences: what this scene should accomplish narratively",
  "tone": "mood/atmosphere keywords (e.g. tense, melancholy, hopeful)",
  "reasoning": "Brief explanation of why this scene fits the story now"
}

Rules:
- Only use NPC IDs from the provided list. Match by name if the hint references one.
- The scene must respect established world facts and active threads.
- Prefer locations from the established places list, but may invent new ones.
- If hint is "surprise me" or blank, pick the most dramatically appropriate next moment.
- Keep intent focused — one clear goal per scene.

Output ONLY the JSON object. No preamble."""


@router.post("/{campaign_id}/god-prompt")
def run_god_prompt(campaign_id: str, req: GodPromptRequest):
    """
    Natural-language GM command that proposes structured world changes.
    Returns suggestions for the player to review — does NOT auto-apply.
    """
    import json as _json
    import httpx
    import re as _re
    from app.campaigns.world_builder import _extract_json

    _require_campaign(campaign_id)
    campaign = _campaigns().get(campaign_id)

    # Gather world context
    npcs = _npcs().get_all(campaign_id)
    facts = _facts().get_all(campaign_id)
    threads = _threads().get_all(campaign_id)
    quests = _quests().get_all(campaign_id)
    objectives = _objectives().get_all(campaign_id)
    places = _places().get_all(campaign_id)
    factions = _factions().get_all(campaign_id)

    def _lines(items, fmt):
        return [fmt(i) for i in items] if items else []

    npc_lines = _lines(npcs, lambda n: (
        f"• {n.name} (id={n.id}) — role: {n.role or 'unknown'}, "
        f"state: \"{n.current_state}\", alive: {n.is_alive}, "
        f"location: \"{n.current_location}\""
    ))
    fact_lines = _lines(facts, lambda f: f"• (id={f.id}) {f.content}")
    thread_lines = _lines(threads, lambda t:
        f"• {t.title} (id={t.id}) [{t.status.value}]: {t.description}"
    )
    quest_lines = _lines(quests, lambda q:
        f"• {q.title} (id={q.id}) [{q.status.value}]: {q.description}"
    )
    objective_lines = _lines(objectives, lambda o:
        f"• {o.title} (id={o.id}) [{o.status.value}]"
    )
    place_lines = _lines(places, lambda p:
        f"• {p.name} (id={p.id}): {p.description}"
    )
    faction_lines = _lines(factions, lambda f:
        f"• {f.name} (id={f.id}): {f.description}"
    )

    parts = [f"[GM INSTRUCTION]\n{req.instruction.strip()}"]
    if npc_lines:
        parts.append("[CURRENT NPCs]\n" + "\n".join(npc_lines))
    if fact_lines:
        parts.append("[WORLD FACTS]\n" + "\n".join(fact_lines))
    if thread_lines:
        parts.append("[NARRATIVE THREADS]\n" + "\n".join(thread_lines))
    if quest_lines:
        parts.append("[QUESTS]\n" + "\n".join(quest_lines))
    if objective_lines:
        parts.append("[OBJECTIVES]\n" + "\n".join(objective_lines))
    if place_lines:
        parts.append("[PLACES]\n" + "\n".join(place_lines))
    if faction_lines:
        parts.append("[FACTIONS]\n" + "\n".join(faction_lines))

    prompt = "\n\n".join(parts) + "\n\nOutput ONLY the JSON object."

    model = req.model_name \
        or (getattr(campaign, "summary_model_name", None) if campaign else None) \
        or (campaign.model_name if campaign else None) \
        or config.ollama_model

    log.info("god_prompt: model=%s campaign=%s", model, campaign_id)

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _GOD_PROMPT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.4, "num_predict": 4096, "num_ctx": config.context_window},
        }
        r = httpx.post(
            f"{config.active_base_url().rstrip('/')}/api/chat"
            if config.provider == "ollama"
            else f"{config.active_base_url().rstrip('/')}/v1/chat/completions",
            json=payload if config.provider == "ollama" else {
                "model": model,
                "messages": payload["messages"],
                "temperature": 0.4,
                "max_tokens": 4096,
                "stream": False,
            },
            timeout=httpx.Timeout(10.0, read=240.0),
        )
        r.raise_for_status()
        if config.provider == "ollama":
            raw = r.json()["message"]["content"].strip()
        else:
            raw = r.json()["choices"][0]["message"]["content"].strip()
    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot reach {config.provider}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "God Prompt timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"God Prompt failed: {e}")

    raw = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()
    data = _extract_json(raw)
    parse_ok = bool(data)
    if not parse_ok:
        log.warning("god_prompt: JSON parse failed. Raw:\n%s", raw[:2000])

    return {
        "update_npcs":      data.get("update_npcs", []),
        "create_npcs":      data.get("create_npcs", []),
        "delete_npcs":      data.get("delete_npcs", []),
        "create_facts":     data.get("create_facts", []),
        "update_facts":     data.get("update_facts", []),
        "delete_facts":     data.get("delete_facts", []),
        "create_threads":   data.get("create_threads", []),
        "update_threads":   data.get("update_threads", []),
        "delete_threads":   data.get("delete_threads", []),
        "create_quests":    data.get("create_quests", []),
        "update_quests":    data.get("update_quests", []),
        "create_places":    data.get("create_places", []),
        "update_places":    data.get("update_places", []),
        "create_factions":  data.get("create_factions", []),
        "update_factions":  data.get("update_factions", []),
        "narrative_note":   data.get("narrative_note", ""),
        "_model": model,
        "_parse_ok": parse_ok,
        "_raw": raw[:2000],
    }


@router.post("/{campaign_id}/suggest-scene")
def suggest_scene(campaign_id: str, req: SuggestSceneRequest):
    """
    Given a player hint (or 'surprise me'), suggest a complete scene setup
    that continues the story naturally from the established world state.
    Returns {title, location, npc_ids, intent, tone, reasoning}.
    """
    import httpx
    import re as _re
    from app.campaigns.world_builder import _extract_json

    _require_campaign(campaign_id)
    campaign = _campaigns().get(campaign_id)

    npcs = _npcs().get_all(campaign_id)
    threads_all = _threads().get_all(campaign_id)
    facts_all = _facts().get_all(campaign_id)
    places_all = _places().get_all(campaign_id)
    chronicle_all = sorted(_chronicle().get_all(campaign_id), key=lambda e: e.scene_range_start)
    scenes_all = _scenes().get_all(campaign_id)

    # Keep only confirmed facts (critical + normal; skip background unless few facts)
    key_facts = [f for f in facts_all if f.priority in ("critical", "normal")]
    if not key_facts:
        key_facts = facts_all
    key_facts = key_facts[:30]  # cap to avoid prompt bloat

    # Most recent confirmed scene
    confirmed_scenes = [s for s in scenes_all if s.confirmed]
    last_scene = confirmed_scenes[-1] if confirmed_scenes else None

    # Recent chronicle (last 5 entries)
    recent_chronicle = chronicle_all[-5:] if chronicle_all else []

    active_threads = [t for t in threads_all if t.status.value == "active"]
    alive_npcs = [n for n in npcs if n.is_alive]

    parts = []
    hint_text = req.hint.strip() if req.hint else "surprise me"
    parts.append(f"[PLAYER HINT]\n{hint_text}")

    if last_scene:
        summary = last_scene.confirmed_summary or last_scene.intent or ""
        parts.append(
            f"[LAST SCENE — Scene {last_scene.scene_number}: {last_scene.title}]\n"
            f"Location: {last_scene.location}\n"
            + (f"Summary: {summary}" if summary else "")
        )

    if recent_chronicle:
        chron_lines = [
            f"• Scene {e.scene_range_start}: {e.content[:200]}" + ("…" if len(e.content) > 200 else "")
            for e in recent_chronicle
        ]
        parts.append("[STORY SO FAR]\n" + "\n".join(chron_lines))

    if active_threads:
        thread_lines = [
            f"• {t.title} (id={t.id}): {t.description}"
            for t in active_threads
        ]
        parts.append("[ACTIVE NARRATIVE THREADS]\n" + "\n".join(thread_lines))

    if alive_npcs:
        npc_lines = [
            f"• {n.name} (id={n.id}) — {n.role or 'unknown role'}, "
            f"state: {n.current_state or 'normal'}, location: {n.current_location or 'unknown'}"
            for n in alive_npcs
        ]
        parts.append("[AVAILABLE NPCs]\n" + "\n".join(npc_lines))

    if places_all:
        place_lines = [f"• {p.name} (id={p.id}): {p.description}" for p in places_all[:20]]
        parts.append("[KNOWN PLACES]\n" + "\n".join(place_lines))

    if key_facts:
        fact_lines = [f"• {f.content}" for f in key_facts]
        parts.append("[KEY WORLD FACTS]\n" + "\n".join(fact_lines))

    prompt = "\n\n".join(parts) + "\n\nOutput ONLY the JSON object."

    model = req.model_name \
        or (getattr(campaign, "summary_model_name", None) if campaign else None) \
        or (campaign.model_name if campaign else None) \
        or config.ollama_model

    log.info("suggest_scene: model=%s campaign=%s hint='%s'", model, campaign_id, hint_text[:60])

    try:
        payload_messages = [
            {"role": "system", "content": _SUGGEST_SCENE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        if config.provider == "ollama":
            r = httpx.post(
                f"{config.active_base_url().rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": payload_messages,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.7, "num_predict": 1024, "num_ctx": config.context_window},
                },
                timeout=httpx.Timeout(10.0, read=180.0),
            )
            r.raise_for_status()
            raw = r.json()["message"]["content"].strip()
        else:
            r = httpx.post(
                f"{config.active_base_url().rstrip('/')}/v1/chat/completions",
                json={"model": model, "messages": payload_messages, "temperature": 0.7, "max_tokens": 1024, "stream": False},
                timeout=httpx.Timeout(10.0, read=180.0),
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()
    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot reach {config.provider}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "Scene suggestion timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"Scene suggestion failed: {e}")

    raw = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()
    data = _extract_json(raw)
    parse_ok = bool(data)
    if not parse_ok:
        log.warning("suggest_scene: JSON parse failed. Raw:\n%s", raw[:1000])

    # Build NPC name list for the suggested IDs so the UI can display them
    npc_map = {n.id: n.name for n in npcs}
    suggested_ids = [i for i in (data.get("npc_ids") or []) if i in npc_map]

    return {
        "title":     data.get("title", ""),
        "location":  data.get("location", ""),
        "npc_ids":   suggested_ids,
        "npc_names": [npc_map[i] for i in suggested_ids],
        "intent":    data.get("intent", ""),
        "tone":      data.get("tone", ""),
        "reasoning": data.get("reasoning", ""),
        "_model":    model,
        "_parse_ok": parse_ok,
        "_raw":      raw[:500],
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _upsert_chronicle(campaign_id: str, scene_number: int, content: str) -> None:
    """Create or update the chronicle entry for a specific scene number."""
    store = _chronicle()
    existing = next(
        (e for e in store.get_all(campaign_id)
         if e.scene_range_start == scene_number and e.scene_range_end == scene_number),
        None,
    )
    if existing:
        store.update_content(existing.id, content)
    else:
        store.save(ChronicleEntry(
            campaign_id=campaign_id,
            scene_range_start=scene_number,
            scene_range_end=scene_number,
            content=content,
            confirmed=True,
        ))


def _require_campaign(campaign_id: str):
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


def _require_d20_rules_mode(campaign) -> None:
    if campaign.play_mode != PlayMode.RULES:
        raise HTTPException(400, "Campaign is not in rules mode")
    if campaign.system_pack != "d20-fantasy-core":
        raise HTTPException(400, "Only d20-fantasy-core resolution is implemented so far")


def _apply_resource_costs(campaign_id: str, sheet: CharacterSheet | None, resource_costs: dict[str, int] | None) -> tuple[CharacterSheet | None, list[dict]]:
    if not resource_costs:
        return sheet, []
    if not sheet:
        raise HTTPException(404, "Character sheet not found")

    updated_pools = dict(sheet.resource_pools or {})
    consumed: list[dict] = []
    for resource_name, amount in resource_costs.items():
        amount_int = int(amount or 0)
        if amount_int <= 0:
            continue
        updated_pools, pool = consume_resource(updated_pools, resource_name, amount_int)
        consumed.append({
            "resource": resource_name.strip().lower(),
            "amount": amount_int,
            "remaining": pool["current"],
            "max": pool["max"],
        })

    if not consumed:
        return sheet, []

    saved = _sheets().save_for_owner(
        campaign_id,
        sheet.owner_type,
        sheet.owner_id,
        resource_pools=updated_pools,
    )
    return saved, consumed


def _record_rule_audit(
    *,
    campaign_id: str,
    scene_id: str | None,
    event_type: str,
    actor_name: str,
    source: str,
    reason: str,
    payload: dict,
) -> None:
    _rule_audits().save(RuleAuditEvent(
        campaign_id=campaign_id,
        scene_id=scene_id,
        event_type=event_type,
        actor_name=actor_name,
        source=source,
        reason=reason,
        payload=payload,
    ))


def _record_gm_envelope_audits(
    *,
    campaign_id: str,
    scene_id: str | None,
    reason: str,
    envelope,
) -> None:
    if getattr(envelope, "contract_parse_error", ""):
        _record_rule_audit(
            campaign_id=campaign_id,
            scene_id=scene_id,
            event_type="gm_decision_error",
            actor_name="GM",
            source="contract_parse",
            reason=reason,
            payload={
                "raw_contract": envelope.raw_contract,
                "visible_text": envelope.visible_text,
                "contract_parse_error": envelope.contract_parse_error,
                "used_fallback_preview": envelope.used_fallback_preview,
                "fallback_decision": envelope.gm_decision.model_dump() if envelope.gm_decision else None,
            },
        )
    if envelope.gm_decision:
        payload = envelope.gm_decision.model_dump()
        if getattr(envelope, "used_fallback_preview", False):
            payload["_fallback_preview"] = True
        if getattr(envelope, "contract_parse_error", ""):
            payload["_contract_parse_error"] = envelope.contract_parse_error
        _record_rule_audit(
            campaign_id=campaign_id,
            scene_id=scene_id,
            event_type="gm_decision",
            actor_name="GM",
            source=envelope.gm_decision.resolution_kind,
            reason=reason,
            payload=payload,
        )


def _apply_rest_to_sheet(campaign_id: str, owner_type: str, owner_id: str, *, rest_type: str) -> tuple[CharacterSheet, list[dict], list[dict]]:
    sheet = _sheets().get_for_owner(campaign_id, owner_type, owner_id)
    if not sheet:
        raise HTTPException(404, "Character sheet not found")
    restored_resource_pools, restored_resources = restore_resource_pools(
        sheet.resource_pools,
        rest_type=rest_type,
    )
    restored_item_charges, restored_items = restore_resource_pools(
        sheet.item_charges,
        rest_type=rest_type,
    )
    updated = _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        resource_pools=restored_resource_pools,
        item_charges=restored_item_charges,
    )
    return updated, restored_resources, restored_items


def _apply_treasure_bundle_to_player(campaign_id: str, bundle: dict) -> dict | None:
    sheet = _sheets().get_for_owner(campaign_id, "player", "player")
    if not sheet:
        raise HTTPException(404, "Character sheet not found")
    updated_wallet = dict(sheet.currencies or {})
    for denomination, amount in (bundle.get("currencies") or {}).items():
        updated_wallet = adjust_currency(updated_wallet, denomination, int(amount or 0))
    updated_sheet = _sheets().save_for_owner(campaign_id, "player", "player", currencies=updated_wallet)
    return _sheet_dict(updated_sheet)


def _apply_matured_event_consequences(campaign_id: str, event, *, time_snapshot: dict) -> tuple[dict | None, list[dict], list[dict], dict]:
    hook_type = str((event.details or {}).get("hook_type", "")).strip().lower()
    player_sheet_payload = None
    faction_updates: list[dict] = []
    quest_updates: list[dict] = []
    consequence: dict = {}

    if hook_type == "resource_pressure":
        sheet = _sheets().get_for_owner(campaign_id, "player", "player")
        if sheet:
            cost_sp = max(1, int((event.details or {}).get("supply_cost_sp", 2) or 2))
            before = int((sheet.currencies or {}).get("sp", 0) or 0)
            updated_wallet = adjust_currency(sheet.currencies, "sp", -cost_sp)
            updated_sheet = _sheets().save_for_owner(campaign_id, "player", "player", currencies=updated_wallet)
            after = int((updated_sheet.currencies or {}).get("sp", 0) or 0)
            player_sheet_payload = _sheet_dict(updated_sheet)
            consequence = {
                "kind": "resource_strain",
                "currency": "sp",
                "from": before,
                "to": after,
                "attempted_loss": cost_sp,
            }
    elif hook_type == "social":
        target_faction = None
        faction_id = str((event.details or {}).get("faction_id", "") or "").strip()
        if faction_id:
            target_faction = _factions().get(faction_id)
        if not target_faction:
            factions = _factions().get_all(campaign_id)
            target_faction = factions[0] if factions else None
        if target_faction and target_faction.campaign_id == campaign_id:
            old_standing = target_faction.standing_with_player or "neutral"
            target_faction.standing_with_player = shift_faction_standing(old_standing, -1)
            note = f"[{time_snapshot['label']}] Pressure escalates from event: {event.title}."
            target_faction.relationship_notes = (target_faction.relationship_notes + "\n" if target_faction.relationship_notes else "") + note
            target_faction.updated_at = datetime.now(UTC).replace(tzinfo=None)
            _factions().save(target_faction)
            update = {
                "id": target_faction.id,
                "name": target_faction.name,
                "from": old_standing,
                "to": target_faction.standing_with_player,
                "delta": -1,
            }
            faction_updates.append(update)
            consequence = {
                "kind": "faction_pressure",
                "faction": update,
            }
    elif hook_type == "time_pressure":
        quest_id = str((event.details or {}).get("quest_id", "") or "").strip()
        quest = _quests().get(quest_id) if quest_id else None
        if quest and quest.campaign_id == campaign_id and quest.status == QuestStatus.ACTIVE:
            pressure_note = f"Pressure increased on {time_snapshot['label']}."
            if pressure_note not in (quest.description or ""):
                quest.description = f"{quest.description} {pressure_note}".strip()
            quest.updated_at = datetime.now(UTC).replace(tzinfo=None)
            _quests().save(quest)
            update = {
                "id": quest.id,
                "title": quest.title,
                "description": quest.description,
                "status": quest.status.value if hasattr(quest.status, "value") else str(quest.status),
            }
            quest_updates.append(update)
            consequence = {
                "kind": "quest_pressure",
                "quest": update,
            }

    if consequence:
        event.details = dict(event.details or {})
        event.details["last_consequence"] = consequence
        event.updated_at = datetime.now(UTC).replace(tzinfo=None)
        _events().save(event)
    return player_sheet_payload, faction_updates, quest_updates, consequence


def _save_sheet_request(campaign_id: str, owner_type: str, owner_id: str, req: SaveCharacterSheetRequest, existing) -> CharacterSheet:
    return _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        name=req.name,
        ancestry=req.ancestry,
        character_class=req.character_class,
        background=req.background,
        level=req.level,
        proficiency_bonus=req.proficiency_bonus,
        abilities=req.abilities or (existing.abilities if existing else None),
        skill_modifiers=req.skill_modifiers or (existing.skill_modifiers if existing else None),
        save_modifiers=req.save_modifiers or (existing.save_modifiers if existing else None),
        max_hp=req.max_hp,
        current_hp=req.current_hp,
        temp_hp=req.temp_hp,
        armor_class=req.armor_class,
        speed=req.speed,
        currencies=req.currencies or (existing.currencies if existing else None),
        resource_pools=req.resource_pools or (existing.resource_pools if existing else None),
        prepared_spells=req.prepared_spells or (existing.prepared_spells if existing else None),
        equipped_items=req.equipped_items or (existing.equipped_items if existing else None),
        item_charges=req.item_charges or (existing.item_charges if existing else None),
        conditions=req.conditions,
        notes=req.notes,
    )


def _consume_visible_stream_delta(buffer: str, delta: str, saw_contract: bool) -> tuple[str, str, bool]:
    combined = buffer + (delta or "")
    if saw_contract:
        return "", combined, True

    marker_index = combined.find(GM_DECISION_START)
    if marker_index != -1:
        return combined[:marker_index], combined[marker_index:], True

    keep_tail = max(0, len(GM_DECISION_START) - 1)
    if len(combined) <= keep_tail:
        return "", combined, False
    return combined[:-keep_tail], combined[-keep_tail:], False


def _build_encounter_participant_request(campaign_id: str, req: EncounterParticipantRequest):
    owner_type = (req.owner_type or "npc").strip().lower()
    owner_id = (req.owner_id or "").strip()
    if owner_type not in {"player", "npc"}:
        raise HTTPException(400, "Encounter participant owner_type must be 'player' or 'npc'")

    sheet = None
    name = req.name.strip()
    if owner_type == "player":
        sheet = _sheets().get_for_owner(campaign_id, "player", owner_id or "player")
        pc = _pcs().get(campaign_id)
        name = name or (sheet.name if sheet else (pc.name if pc else "Player"))
        owner_id = owner_id or "player"
    else:
        if owner_id:
            sheet = _sheets().get_for_owner(campaign_id, "npc", owner_id)
            npc = _npcs().get(owner_id)
            if npc:
                name = name or npc.name
        name = name or "NPC"

    return build_encounter_participant(
        owner_type=owner_type,
        owner_id=owner_id,
        name=name,
        team=req.team,
        sheet=sheet,
        initiative_roll=req.initiative_roll,
        initiative_modifier=req.initiative_modifier,
    )


def _sync_encounter_participant_to_sheet(campaign_id: str, participant_payload: dict | None) -> None:
    if not participant_payload:
        return
    owner_type = (participant_payload.get("owner_type") or "").strip().lower()
    owner_id = (participant_payload.get("owner_id") or "").strip()
    if owner_type not in {"player", "npc"}:
        return
    if owner_type == "player":
        owner_id = owner_id or "player"
    if not owner_id:
        return
    _sheets().save_for_owner(
        campaign_id,
        owner_type,
        owner_id,
        current_hp=participant_payload.get("current_hp"),
        max_hp=participant_payload.get("max_hp"),
        conditions=participant_payload.get("conditions"),
    )


def _sync_all_encounter_participants_to_sheets(campaign_id: str, encounter: Encounter) -> list[dict]:
    synced: list[dict] = []
    for participant in encounter.participants or []:
        payload = participant.model_dump()
        owner_type = (payload.get("owner_type") or "").strip().lower()
        owner_id = (payload.get("owner_id") or "").strip()
        if owner_type not in {"player", "npc"}:
            continue
        if owner_type == "player":
            owner_id = owner_id or "player"
        if not owner_id:
            continue
        _sync_encounter_participant_to_sheet(campaign_id, payload)
        synced.append({
            "participant_id": participant.id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "current_hp": participant.current_hp,
            "max_hp": participant.max_hp,
            "conditions": participant.conditions,
            "life_state": getattr(participant, "life_state", "active"),
        })
    return synced


def _validate_target_range(*, range_feet: int | None, target_distance_feet: int | None) -> None:
    if range_feet is None and target_distance_feet is None:
        return
    if range_feet is None or target_distance_feet is None:
        raise HTTPException(400, "range_feet and target_distance_feet must be provided together")
    if int(target_distance_feet) > int(range_feet):
        raise HTTPException(400, f"Target is out of range ({target_distance_feet} ft > {range_feet} ft)")


def _require_player_turn_for_scene_encounter(campaign_id: str, scene_id: str | None):
    if not scene_id:
        return None
    encounter = _encounters().get_active(campaign_id, scene_id=scene_id)
    if not encounter or not encounter.participants:
        return None
    if not (0 <= encounter.current_turn_index < len(encounter.participants)):
        return encounter
    current = encounter.participants[encounter.current_turn_index]
    if current.owner_type != "player":
        raise HTTPException(400, f"It is currently {current.name}'s turn.")
    return encounter


def _consume_player_action_if_needed(
    encounter,
    campaign_id: str,
    scene_id: str | None,
    *,
    cost: str = "action",
    note: str = "",
):
    if not encounter or not encounter.participants:
        return None, None
    current = encounter.participants[encounter.current_turn_index]
    try:
        updated, participant = consume_participant_action(
            encounter,
            participant_id=current.id,
            cost=cost,
            note=note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _encounters().save(updated)
    return updated, participant


def _campaign_dict(c) -> dict:
    time_snapshot = world_time_snapshot(getattr(c, "world_time_hours", 0))
    return {
        "id": c.id,
        "name": c.name,
        "model_name": c.model_name,
        "summary_model_name": c.summary_model_name if hasattr(c, "summary_model_name") else None,
        "play_mode": c.play_mode.value if hasattr(c.play_mode, "value") else c.play_mode,
        "system_pack": c.system_pack,
        "feature_flags": c.feature_flags,
        "style_guide": c.style_guide.model_dump(),
        "gen_settings": c.gen_settings.model_dump(),
        "world_time_hours": getattr(c, "world_time_hours", 0),
        "world_time": time_snapshot,
        "notes": c.notes,
        "cover_image": c.cover_image,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _pc_dict(pc) -> dict:
    if pc is None:
        return {}
    return {
        "id": pc.id,
        "campaign_id": pc.campaign_id,
        "name": pc.name,
        "appearance": pc.appearance,
        "personality": pc.personality,
        "background": pc.background,
        "wants": pc.wants,
        "fears": pc.fears,
        "how_seen": pc.how_seen,
        "dev_log": [{"scene_number": e.scene_number, "note": e.note} for e in (pc.dev_log or [])],
        "portrait_image": pc.portrait_image,
        "created_at": pc.created_at.isoformat(),
        "updated_at": pc.updated_at.isoformat(),
    }


def _rulebook_dict(rulebook) -> dict:
    return {
        "id": rulebook.id,
        "name": rulebook.name,
        "slug": rulebook.slug,
        "description": rulebook.description,
        "system_pack": rulebook.system_pack,
        "author": rulebook.author,
        "version": rulebook.version,
        "is_builtin": rulebook.is_builtin,
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "content": s.content,
                "tags": s.tags,
                "priority": s.priority,
            }
            for s in rulebook.sections
        ],
    }


def _sheet_dict(sheet) -> dict:
    sheet = normalize_sheet(sheet)
    return {
        "id": sheet.id,
        "campaign_id": sheet.campaign_id,
        "owner_type": sheet.owner_type,
        "owner_id": sheet.owner_id,
        "name": sheet.name,
        "ancestry": sheet.ancestry,
        "character_class": sheet.character_class,
        "background": sheet.background,
        "level": sheet.level,
        "proficiency_bonus": sheet.proficiency_bonus,
        "abilities": sheet.abilities,
        "skill_modifiers": sheet.skill_modifiers,
        "save_modifiers": sheet.save_modifiers,
        "max_hp": sheet.max_hp,
        "current_hp": sheet.current_hp,
        "temp_hp": sheet.temp_hp,
        "armor_class": sheet.armor_class,
        "speed": sheet.speed,
        "currencies": sheet.currencies,
        "resource_pools": sheet.resource_pools,
        "prepared_spells": sheet.prepared_spells,
        "equipped_items": sheet.equipped_items,
        "item_charges": sheet.item_charges,
        "conditions": sheet.conditions,
        "notes": sheet.notes,
        "derived": derive_sheet_state(sheet),
        "created_at": sheet.created_at.isoformat(),
        "updated_at": sheet.updated_at.isoformat(),
    }


def _compendium_entry_dict(entry) -> dict:
    return {
        "id": entry.id,
        "slug": entry.slug,
        "name": entry.name,
        "category": entry.category,
        "system_pack": entry.system_pack,
        "description": entry.description,
        "rules_text": entry.rules_text,
        "tags": entry.tags,
        "action_cost": entry.action_cost,
        "range_feet": entry.range_feet,
        "roll_expression": entry.roll_expression,
        "modifier": entry.modifier,
        "equipment_slot": entry.equipment_slot,
        "armor_class_bonus": entry.armor_class_bonus,
        "charges_max": entry.charges_max,
        "restores_on": entry.restores_on,
        "resource_costs": entry.resource_costs,
        "applies_conditions": entry.applies_conditions,
        "is_builtin": entry.is_builtin,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _action_log_dict(entry) -> dict:
    return {
        "id": entry.id,
        "campaign_id": entry.campaign_id,
        "scene_id": entry.scene_id,
        "actor_name": entry.actor_name,
        "action_type": entry.action_type,
        "source": entry.source,
        "summary": entry.summary,
        "details": entry.details,
        "created_at": entry.created_at.isoformat(),
    }


def _encounter_dict(encounter: Encounter) -> dict:
    current_participant = None
    if encounter.participants and 0 <= encounter.current_turn_index < len(encounter.participants):
        current_participant = encounter.participants[encounter.current_turn_index]
    return {
        "id": encounter.id,
        "campaign_id": encounter.campaign_id,
        "scene_id": encounter.scene_id,
        "name": encounter.name,
        "status": encounter.status,
        "round_number": encounter.round_number,
        "current_turn_index": encounter.current_turn_index,
        "current_participant": current_participant.model_dump() if current_participant else None,
        "participants": [participant.model_dump() for participant in encounter.participants],
        "encounter_log": encounter.encounter_log,
        "summary": encounter.summary,
        "created_at": encounter.created_at.isoformat(),
        "updated_at": encounter.updated_at.isoformat(),
    }


def _rule_audit_dict(event) -> dict:
    return {
        "id": event.id,
        "campaign_id": event.campaign_id,
        "scene_id": event.scene_id,
        "event_type": event.event_type,
        "actor_name": event.actor_name,
        "source": event.source,
        "reason": event.reason,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


def _fact_dict(f) -> dict:
    return {
        "id": f.id,
        "campaign_id": f.campaign_id,
        "content": f.content,
        "category": f.category,
        "priority": f.priority if hasattr(f, "priority") else "normal",
        "trigger_keywords": f.trigger_keywords if hasattr(f, "trigger_keywords") else [],
        "fact_order": f.fact_order,
        "created_at": f.created_at.isoformat(),
    }


def _place_dict(p) -> dict:
    return {
        "id": p.id,
        "campaign_id": p.campaign_id,
        "name": p.name,
        "description": p.description,
        "current_state": p.current_state,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _npc_dict(n) -> dict:
    return {
        "id": n.id,
        "campaign_id": n.campaign_id,
        "name": n.name,
        "appearance": n.appearance,
        "personality": n.personality,
        "role": n.role,
        "gender": n.gender,
        "age": n.age,
        "relationship_to_player": n.relationship_to_player,
        "current_location": n.current_location,
        "current_state": n.current_state,
        "is_alive": n.is_alive,
        "status": n.status.value if hasattr(n.status, "value") else n.status,
        "status_reason": n.status_reason,
        "secrets": n.secrets,
        "short_term_goal": n.short_term_goal,
        "long_term_goal": n.long_term_goal,
        "history_with_player": n.history_with_player if hasattr(n, "history_with_player") else "",
        "forms": [f.model_dump() for f in n.forms] if hasattr(n, "forms") else [],
        "active_form": n.active_form if hasattr(n, "active_form") else None,
        "dev_log": [{"scene_number": e.scene_number, "note": e.note} for e in (n.dev_log or [])],
        "portrait_image": n.portrait_image,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _thread_dict(t) -> dict:
    return {
        "id": t.id,
        "campaign_id": t.campaign_id,
        "title": t.title,
        "description": t.description,
        "status": t.status.value if hasattr(t.status, "value") else t.status,
        "resolution": t.resolution,
        "last_mentioned_scene": getattr(t, "last_mentioned_scene", 0),
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _faction_dict(f) -> dict:
    return {
        "id": f.id,
        "campaign_id": f.campaign_id,
        "name": f.name,
        "description": f.description,
        "goals": f.goals,
        "methods": f.methods,
        "standing_with_player": f.standing_with_player,
        "relationship_notes": f.relationship_notes,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }


def _objective_dict(objective) -> dict:
    return {
        "id": objective.id,
        "campaign_id": objective.campaign_id,
        "title": objective.title,
        "description": objective.description,
        "status": objective.status.value if hasattr(objective.status, "value") else str(objective.status),
        "created_at": objective.created_at.isoformat(),
        "updated_at": objective.updated_at.isoformat(),
    }


def _quest_dict(quest) -> dict:
    return {
        "id": quest.id,
        "campaign_id": quest.campaign_id,
        "title": quest.title,
        "description": quest.description,
        "status": quest.status.value if hasattr(quest.status, "value") else str(quest.status),
        "giver_npc_name": quest.giver_npc_name,
        "location_name": quest.location_name,
        "reward_notes": quest.reward_notes,
        "importance": quest.importance.value if hasattr(quest.importance, "value") else str(quest.importance),
        "progress_label": quest.progress_label,
        "tags": quest.tags,
        "stages": [
            {
                "id": stage.id,
                "description": stage.description,
                "completed": stage.completed,
                "order": stage.order,
            }
            for stage in quest.stages
        ],
        "created_at": quest.created_at.isoformat(),
        "updated_at": quest.updated_at.isoformat(),
    }


def _campaign_event_dict(event) -> dict:
    return {
        "id": event.id,
        "campaign_id": event.campaign_id,
        "event_type": event.event_type,
        "title": event.title,
        "content": event.content,
        "details": event.details,
        "world_time_hours": event.world_time_hours,
        "world_time": world_time_snapshot(event.world_time_hours),
        "status": event.status.value if hasattr(event.status, "value") else str(event.status),
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
    }


def _build_campaign_recap_items(*, chronicle_entries: list, action_logs: list, events: list, limit: int = 12, kind: str = "all") -> list[dict]:
    merged: list[dict] = []

    for entry in chronicle_entries:
        merged.append({
            "kind": "chronicle",
            "title": f"Scene {entry.scene_range_start}" if entry.scene_range_start == entry.scene_range_end else f"Scenes {entry.scene_range_start}-{entry.scene_range_end}",
            "summary": entry.content,
            "world_time": None,
            "created_at": entry.created_at.isoformat(),
            "sort_value": entry.created_at.isoformat(),
        })

    for event in events:
        snapshot = world_time_snapshot(event.world_time_hours)
        details = event.details or {}
        escalation_level = int(details.get("escalation_level", 0) or 0)
        consequence = details.get("last_consequence") if isinstance(details.get("last_consequence"), dict) else None
        merged.append({
            "kind": "event",
            "title": event.title,
            "summary": event.content,
            "world_time": snapshot["label"],
            "hook_type": details.get("hook_type", ""),
            "escalation_level": escalation_level,
            "consequence_kind": consequence.get("kind", "") if consequence else "",
            "created_at": event.created_at.isoformat(),
            "sort_value": f"{event.world_time_hours:08d}-{event.created_at.isoformat()}",
        })

    for log_entry in action_logs:
        details = log_entry.details or {}
        world_time = details.get("world_time", {}).get("label") if isinstance(details.get("world_time"), dict) else None
        merged.append({
            "kind": "mechanic",
            "title": str(log_entry.action_type or "log").replace("_", " ").title(),
            "summary": log_entry.summary,
            "world_time": world_time,
            "created_at": log_entry.created_at.isoformat(),
            "sort_value": log_entry.created_at.isoformat(),
        })

    kind_key = str(kind or "all").strip().lower()
    if kind_key != "all":
        merged = [item for item in merged if item.get("kind") == kind_key]

    merged.sort(key=lambda item: item["sort_value"], reverse=True)
    return [
        {key: value for key, value in item.items() if key != "sort_value"}
        for item in merged[:limit]
    ]


def _summarize_campaign_recap(items: list[dict]) -> str:
    if not items:
        return "No recap entries yet."
    snippets = []
    for item in items[:3]:
        label = str(item.get("title") or item.get("kind") or "Entry")
        summary = str(item.get("summary") or "").strip()
        snippets.append(f"{label}: {summary}")
    return " | ".join(snippets)


def _rel_dict(r) -> dict:
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "npc_id_a": r.npc_id_a,
        "npc_id_b": r.npc_id_b,
        "dynamic": r.dynamic,
        "trust": r.trust,
        "hostility": r.hostility,
        "history": r.history,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _scene_dict(s) -> dict:
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "scene_number": s.scene_number,
        "title": s.title,
        "location": s.location,
        "npc_ids": s.npc_ids,
        "intent": s.intent,
        "tone": s.tone,
        "turns": [
            {"role": t.role, "content": t.content}
            for t in s.turns
        ],
        "proposed_summary": s.proposed_summary,
        "confirmed_summary": s.confirmed_summary,
        "confirmed": s.confirmed,
        "allow_unselected_npcs": s.allow_unselected_npcs,
        "scene_image": s.scene_image,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _chronicle_dict(e) -> dict:
    return {
        "id": e.id,
        "campaign_id": e.campaign_id,
        "scene_range_start": e.scene_range_start,
        "scene_range_end": e.scene_range_end,
        "content": e.content,
        "confirmed": e.confirmed,
        "created_at": e.created_at.isoformat(),
    }
