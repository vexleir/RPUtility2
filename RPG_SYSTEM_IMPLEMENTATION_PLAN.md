# RP Utility — Rules-Native RPG System Implementation Plan

## Purpose

This document defines the implementation plan for evolving RP Utility from a narrative-first AI roleplay tool into a rules-native RPG engine.

Target outcome:

- A modular tabletop-style engine where the AI can act as GM/DM
- Deterministic mechanics for rules resolution
- Structured support for rulebooks, settings, character sheets, combat, items, and progression
- Strong recall of story, world, and mechanical state
- A repeatable QA process proving the system behaves correctly

This plan is intended to be executable by the development team as a working roadmap.

---

## Product Vision

RP Utility should become:

"A local-first AI tabletop engine with modular rulesets, where the AI narrates and improvises inside a deterministic game framework that tracks campaign state, enforces mechanics, and supports long-form play."

This changes the product from:

- AI remembers the story

To:

- AI runs the story inside a formal game system

---

## Guiding Design Principles

1. Rules are first-class, not prompt garnish.
2. Mechanical state must be explicit, not inferred from memory.
3. The AI should narrate, adjudicate intent, and improvise fiction.
4. Deterministic code should resolve math, legality, and state transitions.
5. Narrative memory, world canon, and mechanical state must remain separate.
6. The system must support multiple game systems through modular content packs.
7. Every major subsystem must have automated tests and clear acceptance criteria.

---

## Current State Summary

The existing codebase already provides strong foundations:

- Session and campaign persistence in SQLite
- Character cards and lorebooks
- Prompt assembly with memory and world context
- Scene tracking, relationships, NPC registry, objectives, quests, factions
- Generic stats, skill checks, inventory, status effects, narrative arc
- Web-based campaign and chat UI
- Local model abstraction for Ollama and LM Studio

What is missing for full RPG support:

- Rulebook ingestion and retrieval
- Deterministic rules engine
- Real character sheets
- Formal game modes
- Combat and encounter procedures
- Rule-aware GM procedures
- Mechanical audit logs
- Modular system-pack architecture

---

## Target Architecture

The upgraded architecture should be organized into seven layers.

### 1. Content Layer

New modules:

- `app/rules/`
- `app/system_packs/`
- `app/compendium/`

Responsibilities:

- Rulebook import and storage
- System pack registration
- Compendium entities: classes, species, spells, items, monsters, conditions, actions
- Setting packs and campaign defaults

### 2. Rules Layer

New modules:

- `app/rules/engine.py`
- `app/rules/resolution.py`
- `app/rules/validators.py`
- `app/rules/procedures/`

Responsibilities:

- Resolve checks, saves, attacks, damage, initiative, rests, leveling
- Validate legal actions
- Enforce combat turn economy
- Apply conditions and durations
- Produce structured rule outcomes and audit events

### 3. Character Layer

New modules:

- `app/characters/sheets.py`
- `app/characters/progression.py`
- `app/characters/resources.py`

Responsibilities:

- Player and NPC mechanical sheets
- HP, AC, proficiencies, spell slots, equipment, currencies
- Leveling and progression state
- Derived stat calculations

### 4. Encounter Layer

New modules:

- `app/encounters/store.py`
- `app/encounters/engine.py`
- `app/encounters/turn_order.py`

Responsibilities:

- Initiative
- Encounter participants
- Combat turns
- Action logs
- Damage and condition application
- End-of-encounter cleanup

### 5. Narrative Layer

Existing modules expanded:

- `app/prompting/builder.py`
- `app/core/engine.py`
- `app/campaigns/scene_prompter.py`

Responsibilities:

- AI narration and GM framing
- Rule-aware prompt building
- Fictional summaries and recap generation
- Story memory and canon retrieval

### 6. UI Layer

Expanded web UI:

- Character sheet editor/viewer
- Combat view
- Action/roll controls
- Rule audit panel
- Mode-specific panels
- Rulebook and compendium management

### 7. QA Layer

Expanded tests:

- Unit tests for deterministic rules
- Integration tests for rules + narrative flow
- Fixture-based content pack tests
- End-to-end campaign flow tests

---

## Data Model Additions

These models should be introduced before advanced features.

### Rulebook and System Models

- `Rulebook`
- `RuleSection`
- `RuleProcedure`
- `SystemPack`
- `SettingPack`
- `CompendiumSource`

### Mechanical Character Models

- `CharacterSheet`
- `AbilityScore`
- `SkillProficiency`
- `SaveProficiency`
- `ClassLevel`
- `FeatureGrant`
- `ResourcePool`
- `SpellcastingProfile`
- `SpellSlotState`
- `CurrencyWallet`
- `EquipmentLoadout`
- `ConditionInstance`

### Combat Models

- `Encounter`
- `EncounterParticipant`
- `InitiativeEntry`
- `CombatTurnState`
- `ActionResolution`
- `DamageEvent`
- `HealingEvent`

### Audit and Procedure Models

- `RuleAuditEvent`
- `TriggeredProcedure`
- `GMDecisionPoint`

### Migration Notes

Existing generic stats and status systems can be retained for backward compatibility, but the new rules-native sheet models should become primary in system-pack mode.

---

## Separation of State

The implementation must explicitly separate these concerns.

### Narrative Memory

Stored facts about what happened in the fiction.

Examples:

- "The bridge at Dunmere collapsed."
- "Serah revealed she once served the duke."

### Canon / Lore / Setting Knowledge

Reference material that defines the world or rulebook.

Examples:

- "Tieflings are distrusted in this region."
- "A long rest restores all hit points in this system."

### Mechanical State

Structured live game state.

Examples:

- HP 12/27
- AC 16
- initiative 14
- poisoned for 3 rounds
- spell slots 2/4 remaining

Mechanical state must never rely on soft memory extraction.

---

## Phased Roadmap

## Phase 0 — Foundation Alignment

### Goals

- Establish architecture for a rules-native engine
- Avoid destabilizing existing campaign and quick-play systems
- Create migration-safe boundaries

### Work

- Add `RPG mode` feature flag concept
- Add `system_pack` field to campaigns and sessions
- Add top-level `app/rules/`, `app/characters/`, and `app/encounters/` packages
- Refactor `app/core/engine.py` to reduce orchestration coupling
- Define service boundaries between narrative, rules, and UI concerns

### Deliverables

- New architecture skeleton
- New DB tables for system pack selection and rules metadata
- Internal interfaces documented in code

### Tests

- Schema migration tests
- Existing campaign/session regression tests
- Smoke tests proving legacy mode still runs unchanged

### Exit Criteria

- The app can load a campaign with or without a system pack
- No regression in current session chat or campaign scene play

---

## Phase 1 — Rulebook and System Pack Support

### Goals

- Make rulesets importable and queryable
- Introduce structured rule retrieval distinct from lorebooks

### Work

- Create `Rulebook`, `RuleSection`, and `SystemPack` models
- Add rulebook import pipeline for JSON-first structured content
- Add optional plain-text import path with parser helpers
- Create a rules retrieval service separate from lore retrieval
- Add campaign-level system selection UI
- Add system-pack registry

### Initial Pack Strategy

Start with a generic internal format and one MVP pack:

- `d20-fantasy-core`

Do not begin with direct hard-coded full 5e text dependence.
Build the engine to be 5e-compatible through structured pack data.

### Deliverables

- `app/rules/store.py`
- `app/rules/retriever.py`
- `app/system_packs/registry.py`
- Rulebook management UI

### Tests

- Rulebook import tests
- Rule retrieval ranking tests
- Regression tests ensuring lorebooks and rulebooks do not conflict
- Fixtures for rules lookup under prompt assembly

### Exit Criteria

- Campaigns can attach a system pack
- Prompts can retrieve rules separately from lore
- Rules appear in GM context only when relevant

---

## Phase 2 — Character Sheets and Derived Mechanics

### Goals

- Replace generic stat tracking with full RPG sheets
- Support player and NPC mechanical data

### Work

- Add `CharacterSheet` domain
- Implement abilities, skills, saves, proficiencies, AC, HP, speed, senses
- Add equipment and currency support
- Add spellcasting profile and resource pools
- Add sheet derivation logic
- Add player sheet editor UI
- Add NPC mechanical sheets for rule-driven encounters

### Deliverables

- `app/characters/store.py`
- `app/characters/derivation.py`
- `app/web/` endpoints for sheet CRUD
- Character sheet panels in campaign UI

### Tests

- Derived modifier calculation tests
- Proficiency and skill total tests
- HP/resource state persistence tests
- Sheet serialization round-trip tests

### Exit Criteria

- Player and NPCs can exist as mechanical entities
- Derived numbers are deterministic and verifiable

---

## Phase 3 — Deterministic Resolution Engine

### Goals

- Move core mechanics out of the model and into code
- Make the AI ask for resolution rather than inventing outcomes

### Work

- Implement deterministic resolution procedures:
  - ability checks
  - skill checks
  - saving throws
  - attack rolls
  - damage rolls
  - healing
  - contested checks
  - advantage/disadvantage
  - critical success/failure policy per system pack
- Add dice parser and roller service
- Add resource consumption hooks
- Add structured rule audit events

### Deliverables

- `app/rules/resolution.py`
- `app/rules/dice.py`
- `app/rules/audit.py`
- API endpoints for rule resolution

### Tests

- Deterministic dice parser tests
- Check and save resolution tests
- Advantage/disadvantage tests
- Attack and damage tests
- Resource consumption tests
- Property-style tests for bounded outputs where useful

### Exit Criteria

- All common mechanical resolutions can happen without model math
- Every resolved action produces an audit trail

---

## Phase 4 — GM Procedure Engine

### Goals

- Teach the AI to act as a system-aware GM instead of a freeform narrator

### Work

- Introduce explicit GM procedures:
  - frame situation
  - gather intent
  - determine if a rule triggers
  - resolve mechanically
  - apply consequences
  - narrate outcome
  - present next decision point
- Add prompt contracts for rule-aware GM behavior
- Add hidden GM context vs player-facing output separation
- Add passive perception / passive knowledge procedure support
- Add fail-forward and consequence policies as system-pack config

### Deliverables

- `app/rules/procedures/gm_flow.py`
- Prompt builder extensions for GM procedures
- UI hooks for GM choice points and player decision prompts

### Tests

- Procedure flow tests with mocked provider responses
- Integration tests proving rules are consulted when appropriate
- Regression tests preventing the AI from skipping required procedures

### Exit Criteria

- The AI can consistently run a turn through a formal GM loop
- Required rule procedures happen before state is finalized

---

## Phase 5 — Encounter and Combat System

### Goals

- Support full tactical combat play

### Work

- Add `Encounter` state and participant tracking
- Implement initiative and turn order
- Implement actions, bonus actions, reactions, movement
- Add targeting and range validation
- Add condition timing and duration decrement rules
- Add concentration support
- Add encounter log and summary generation
- Add combat UI with turn order and action controls

### Deliverables

- `app/encounters/`
- Combat UI in web client
- Condition and turn log services

### Tests

- Initiative ordering tests
- Turn progression tests
- Action economy tests
- Condition duration tests
- Death and stabilization tests
- Full encounter integration tests with canned fixtures

### Exit Criteria

- A full multi-round encounter can be run and resumed reliably
- All key combat state survives persistence and reloads correctly

---

## Phase 6 — Items, Spells, Conditions, and Compendium

### Goals

- Add the content density needed for an actual tabletop system

### Work

- Create compendium models for:
  - items
  - weapons
  - armor
  - spells
  - conditions
  - monsters
  - actions
- Add equipment slot logic
- Add spell preparation and slot usage
- Add item use and charges
- Add compendium lookup retrieval in prompts and resolution

### Deliverables

- `app/compendium/store.py`
- `app/compendium/models.py`
- Import tooling for structured content packs
- UI for compendium browsing

### Tests

- Item equip/unequip tests
- Spell slot consumption tests
- Condition application/removal tests
- Compendium retrieval tests
- Import validation tests

### Exit Criteria

- The engine can drive actual gameplay content from structured compendium data

---

## Phase 7 — Campaign Procedures and Adventure Play

### Goals

- Make the game playable across long-form sessions

### Work

- Add travel, rest, downtime, and quest progression procedures
- Add encounter generation hooks
- Add random tables support
- Add treasure generation and economy rules
- Add faction consequence propagation over time
- Add world time pressure systems
- Add player-facing recap and log views that merge fiction and mechanics

### Deliverables

- Travel/rest/downtime engines
- Expanded quest and objective procedures
- Campaign event scheduler

### Tests

- Rest recovery tests
- Travel time and event tests
- Quest progression tests
- Economy and inventory consistency tests
- Time advancement integration tests

### Exit Criteria

- A campaign can progress through exploration, social scenes, combat, and downtime coherently

---

## Phase 8 — System-Pack MVP for 5e-Style Play

### Goals

- Deliver a complete playable fantasy rules experience

### Work

- Build a `5e-compatible` structured pack using only approved content sources
- Implement:
  - d20 checks
  - six abilities
  - proficiency bonus
  - skill and save procedures
  - AC, HP, initiative
  - weapon attacks
  - damage resolution
  - core conditions
  - spell slots and core spellcasting flow
  - rests
  - level progression hooks
- Add GM templates for fantasy adventure pacing

### Content and Legal Note

Do not assume unrestricted use of proprietary 5e text.
This phase must be implemented with approved or user-imported content.

### Tests

- End-to-end "playable session" fixture tests
- Character creation tests
- Combat scenario tests
- Spellcasting scenario tests
- Long rest / recovery tests

### Exit Criteria

- A user can start a campaign, build a character, explore, fight, loot, rest, and continue play under a 5e-style rules framework

---

## Phase 9 — Polish, Explainability, and Release Hardening

### Goals

- Make the system trustworthy and approachable

### Work

- Add rule audit panel in UI
- Add "why this roll happened" explanations
- Add better GM-facing debug views
- Improve fallback behavior when the model produces invalid structured output
- Add import/export for system packs and campaigns
- Add docs and onboarding for rules-native mode

### Tests

- UI integration tests where practical
- Error recovery tests
- Import/export round-trip tests
- Regression sweep over legacy and RPG modes

### Exit Criteria

- The system feels understandable, debuggable, and production-ready

---

## Cross-Cutting Workstreams

These should run alongside the phases above.

### Workstream A — Engine Refactor

- Break up `app/core/engine.py` into focused orchestration services
- Separate narrative orchestration from rule resolution orchestration
- Reduce direct store coupling

### Workstream B — Prompt Contracts

- Convert prompt design from prose-heavy to procedure-aware
- Introduce explicit structured outputs for GM decisions
- Keep prompts narrow and role-specific

### Workstream C — Migrations and Compatibility

- Preserve legacy session mode
- Add gradual migration for campaign data
- Maintain data export safety before schema-heavy changes

### Workstream D — Content Tooling

- Build validators for compendium and rulebook imports
- Add pack versioning
- Add schema docs for custom/homebrew packs

---

## Testing Strategy

The QA plan should be formalized from the start.

## Test Pyramid

### Unit Tests

Focus:

- Dice parsing
- math and modifiers
- legality validation
- resource consumption
- state derivation
- combat turn logic

Target:

- Fast, deterministic, high coverage

### Integration Tests

Focus:

- Rules engine with persistence
- prompt builder with rules retrieval
- GM procedure execution with mocked model calls
- campaign state transitions

### Scenario Tests

Focus:

- Full playable flows
- combat encounters
- spell use
- rest cycle
- quest advancement
- long campaign continuation

These should use canned fixtures and mocked providers.

### End-to-End Manual QA

Focus:

- UI usability
- readability of audit logs
- rulebook import workflow
- campaign creation and character creation
- multi-scene continuity

---

## Required Test Suites By Subsystem

### Rules Engine

- `tests/test_rules_dice.py`
- `tests/test_rules_resolution.py`
- `tests/test_rules_validators.py`
- `tests/test_rules_audit.py`

### Character Sheets

- `tests/test_character_sheets.py`
- `tests/test_character_progression.py`
- `tests/test_character_resources.py`

### Encounters

- `tests/test_encounter_turn_order.py`
- `tests/test_encounter_actions.py`
- `tests/test_encounter_conditions.py`
- `tests/test_encounter_integration.py`

### Rulebook and Packs

- `tests/test_rulebook_import.py`
- `tests/test_system_pack_registry.py`
- `tests/test_compendium_import.py`

### Campaign Flow

- `tests/test_rpg_campaign_flow.py`
- `tests/test_rpg_rest_and_travel.py`
- `tests/test_rpg_quest_progression.py`

### Legacy Safety

- `tests/test_legacy_session_mode.py`
- `tests/test_legacy_campaign_mode.py`

---

## Acceptance Scenarios

These scenarios define what "working" means.

### Scenario 1 — Rulebook Retrieval

- User selects a fantasy system pack
- User asks to sneak past guards
- GM flow retrieves stealth rules and passive detection guidance
- System resolves the check using the character sheet
- Audit log shows DC, modifiers, and result

### Scenario 2 — Combat

- Player attacks an enemy
- Turn order is enforced
- Attack roll is calculated deterministically
- Damage is applied correctly
- HP updates persist
- Conditions and turn economy update correctly

### Scenario 3 — Spellcasting

- Player casts a leveled spell
- Slot is consumed
- Range and target legality are validated
- Effects are applied
- Audit log records the action

### Scenario 4 — Long-Form Continuity

- Campaign runs across several scenes
- NPC relationships and world facts remain consistent
- Mechanical resources remain accurate
- AI recalls both fiction and mechanics at the right times

### Scenario 5 — Legacy Compatibility

- Existing quick-play session mode still works without a system pack
- Existing campaign mode still loads old data safely

---

## Risks and Mitigations

### Risk 1 — Overreliance on the LLM

Issue:

- The AI may drift or ignore rules if too much remains prompt-driven

Mitigation:

- Keep math and legality deterministic
- Reduce prompt responsibility to narration and judgment

### Risk 2 — Complexity Explosion

Issue:

- Too many systems may land at once and destabilize the app

Mitigation:

- Gate work by phases
- Maintain feature flags
- Land foundation before content density

### Risk 3 — Content Licensing

Issue:

- Proprietary RPG content may not be safe to bundle

Mitigation:

- Use approved structured content
- Support user-provided imports
- Keep the pack format system-agnostic

### Risk 4 — UI Overload

Issue:

- Too much mechanical data can make the interface hostile

Mitigation:

- Add mode-specific panels
- Default to progressive disclosure

### Risk 5 — Regression Against Existing Narrative Play

Issue:

- The current user experience could degrade during the overhaul

Mitigation:

- Preserve legacy mode
- Maintain regression tests for current flows

---

## Recommended Implementation Order

If development time is constrained, use this sequence.

1. Phase 0 — foundation alignment
2. Phase 1 — rulebook and system pack support
3. Phase 2 — character sheets
4. Phase 3 — deterministic resolution
5. Phase 4 — GM procedures
6. Phase 5 — combat engine
7. Phase 6 — compendium content
8. Phase 7 — campaign procedures
9. Phase 8 — 5e-style MVP pack
10. Phase 9 — polish and release hardening

This order preserves architecture first, mechanics second, content third.

---

## Definition of Done for the Overhaul

The rules-native RPG system is complete when:

- A campaign can select a system pack
- A player can create and manage a full character sheet
- The GM can run exploration, social scenes, and combat under enforceable rules
- Mechanical state is stored explicitly and survives reloads
- The AI narrates within the rule framework instead of inventing mechanics
- Rule audits explain why outcomes happened
- Structured tests cover the critical game loops
- Legacy narrative play remains functional

---

## Immediate Next Sprint Recommendation

The first sprint should only cover foundation work.

### Sprint 1 Scope

- Add `system_pack` to campaigns/sessions
- Create `app/rules/` package skeleton
- Create `Rulebook` and `SystemPack` models
- Add DB migrations for rules metadata
- Add pack registry
- Add placeholder rulebook CRUD endpoints
- Add regression tests proving nothing existing broke

### Sprint 1 Success Condition

- The codebase can distinguish between:
  - lorebooks
  - rulebooks
  - system packs
- Existing campaign play still works
- We are ready to build the actual rules engine without reworking persistence again

