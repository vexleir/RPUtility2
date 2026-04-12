/**
 * Campaign scene play interface.
 * Manages scene setup, AI streaming chat, and scene confirmation.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

let _campaign = null;
let _scene = null;       // active scene or null
let _pc = null;
let _sheet = null;
let _npcs = [];
let _threads = [];
let _facts = [];
let _objectives = [];
let _quests = [];
let _events = [];
let _actionLogs = [];
let _ruleAudits = [];
let _campaignRecap = { items: [], summary: "" };
let _streaming = false;
let _userName = "Player";
let _gmProcedurePreview = null;
let _gmPreviewTimer = null;
let _recentGMDecisions = [];
let _lastHandledGMDecisionId = null;
let _activeEncounter = null;
let _compendiumEntries = [];
let _compendiumTimer = null;

// ── Regenerate state ──────────────────────────────────────────────────────────
let _alternatives = [];      // all generated responses for the current exchange
let _altIdx = 0;             // index of the currently shown / DB-committed response
let _lastAiDiv = null;       // DOM node of the last AI bubble
let _regenControlsDiv = null; // sibling DOM node holding nav + regen button

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadWorld();
  loadSummaryModels();
  setupInput();
});

async function loadSummaryModels() {
  try {
    const res = await fetch("/api/models");
    if (!res.ok) return;
    const data = await res.json();
    const models = Array.isArray(data) ? data : (data.models || []);
    const sel = document.getElementById("summary-model-select");
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.name;
      opt.textContent = m.name;
      sel.appendChild(opt);
    });
  } catch { /* ignore — dropdown stays at default */ }
}

async function loadWorld() {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _campaign = data.campaign;
    _pc = data.player_character;
    _sheet = data.character_sheet || null;
    _npcs = data.npcs || [];
    _threads = (data.threads || []).filter(t => t.status === "active");
    _facts = (data.world_facts || []).filter(f => f.content);
    _objectives = data.objectives || [];
    _quests = data.quests || [];
    _events = data.events || [];
    _actionLogs = data.action_logs || [];
    _ruleAudits = data.rule_audits || [];
    _activeEncounter = data.active_encounter || null;
    _scene = data.scenes?.find(s => !s.confirmed) || null;

    document.getElementById("back-link").href = `/campaigns/${CAMPAIGN_ID}`;
    document.getElementById("cancel-setup-link").href = `/campaigns/${CAMPAIGN_ID}`;
    document.getElementById("campaign-name-badge").textContent = _campaign?.name || "";

    // Initialise gen-settings sliders from campaign defaults
    gsInitFromCampaign();

    // Pre-select summary model dropdown from campaign settings
    // Use a small delay so loadSummaryModels() has time to populate the options
    const summaryModel = _campaign?.summary_model_name || "";
    if (summaryModel) {
      const trySet = () => {
        const sel = document.getElementById("summary-model-select");
        if (!sel) return;
        if ([...sel.options].some(o => o.value === summaryModel)) {
          sel.value = summaryModel;
        } else {
          // Options not yet loaded — retry once they arrive
          setTimeout(trySet, 200);
        }
      };
      trySet();
    }

    // Populate setup datalist with known locations
    const dl = document.getElementById("location-suggestions");
    (data.places || []).forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.name;
      dl.appendChild(opt);
    });

    // Populate NPC checkboxes
    renderNpcCheckboxes();

    const forceNew = new URLSearchParams(window.location.search).get("new") === "1";

    if (_scene && !forceNew) {
      // Resume existing active scene
      showChatMode();
      renderExistingTurns();
      await refreshCampaignRecap();
      await refreshCompendiumSidebar();
      renderSidebar();
      refreshSceneGMDecisions({ autoHandle: false });
    } else {
      // Show setup panel for new scene
      _scene = null;
      document.getElementById("scene-setup-panel").classList.remove("hidden");
      await refreshCampaignRecap();
    }

    // Load player scratchpad
    loadScratchpad();
  } catch (e) {
    showError(`Failed to load campaign: ${e.message}`);
  }
}

function renderNpcCheckboxes() {
  const container = document.getElementById("npc-checkboxes");
  container.innerHTML = "";
  if (!_npcs.length) {
    container.innerHTML = '<span class="muted">No NPCs yet — add them on the campaign overview page.</span>';
    return;
  }
  _npcs.filter(n => n.is_alive).forEach(n => {
    const label = document.createElement("label");
    label.className = "npc-checkbox-label";
    label.innerHTML = `<input type="checkbox" value="${n.id}"> ${escHtml(n.name)}${n.role ? ` <span class="muted">(${escHtml(n.role)})</span>` : ""}`;
    container.appendChild(label);
  });
}

// ── Scene Suggester ───────────────────────────────────────────────────────────

let _suggestedScene = null;

async function runSuggestScene() {
  const hint = document.getElementById("suggest-scene-hint").value.trim();
  const btn = document.getElementById("suggest-scene-btn");
  const status = document.getElementById("suggest-scene-status");
  const result = document.getElementById("suggest-scene-result");

  btn.disabled = true;
  status.textContent = "Thinking…";
  result.classList.add("hidden");

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/suggest-scene`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hint }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (!data._parse_ok || !data.title) {
      status.textContent = "⚠ Could not parse a suggestion. Try again or add more world context.";
      btn.disabled = false;
      return;
    }

    _suggestedScene = data;
    // Show reasoning
    document.getElementById("ss-reasoning").textContent = data.reasoning || "";
    result.classList.remove("hidden");
    status.textContent = `Suggested: "${data.title}"`;
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

function applySuggestedScene() {
  if (!_suggestedScene) return;
  const d = _suggestedScene;

  // Fill in the scene setup form
  if (d.title)    document.getElementById("setup-title").value = d.title;
  if (d.location) document.getElementById("setup-location").value = d.location;
  if (d.intent)   document.getElementById("setup-intent").value = d.intent;
  if (d.tone)     document.getElementById("setup-tone").value = d.tone;

  // Check suggested NPCs in the checkbox list
  if (d.npc_ids && d.npc_ids.length) {
    // Uncheck all first, then check suggested
    document.querySelectorAll("#npc-checkboxes input[type=checkbox]").forEach(cb => {
      cb.checked = d.npc_ids.includes(cb.value);
    });
  }

  // Close the suggester panel and scroll to form
  const suggestDetails = document.getElementById("qa-suggest-scene");
  if (suggestDetails) suggestDetails.removeAttribute("open");
  document.getElementById("setup-title").scrollIntoView({ behavior: "smooth", block: "nearest" });
  document.getElementById("suggest-scene-result").classList.add("hidden");
  document.getElementById("suggest-scene-status").textContent = "✓ Applied to form. Review and begin when ready.";
}

// ── Scene setup quick-add helpers ────────────────────────────────────────────

async function qaGenerateNpc() {
  const desc = document.getElementById("qa-npc-desc").value.trim();
  if (!desc) return;
  const statusEl = document.getElementById("qa-npc-gen-status");
  const btn = document.getElementById("qa-npc-gen-btn");
  statusEl.textContent = "Generating…";
  statusEl.style.color = "";
  btn.disabled = true;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: desc }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const npc = await res.json();
    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    fill("qa-npc-name", npc.name);
    fill("qa-npc-role", npc.role);
    fill("qa-npc-gender", npc.gender);
    fill("qa-npc-age", npc.age);
    fill("qa-npc-appearance", npc.appearance);
    fill("qa-npc-personality", npc.personality);
    statusEl.textContent = "✓ Done";
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  } finally {
    btn.disabled = false;
  }
}

async function qaAddNpc() {
  const name = document.getElementById("qa-npc-name").value.trim();
  if (!name) { document.getElementById("qa-npc-status").textContent = "Name is required."; return; }
  const statusEl = document.getElementById("qa-npc-status");
  statusEl.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        role: document.getElementById("qa-npc-role").value.trim(),
        gender: document.getElementById("qa-npc-gender").value.trim(),
        age: document.getElementById("qa-npc-age").value.trim(),
        appearance: document.getElementById("qa-npc-appearance").value.trim(),
        personality: document.getElementById("qa-npc-personality").value.trim(),
      }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const saved = await res.json();
    // Add to local NPC list and re-render checkboxes
    _npcs.push(saved);
    renderNpcCheckboxes();
    // Auto-check the new NPC
    const checkbox = document.querySelector(`#npc-checkboxes input[value="${saved.id}"]`);
    if (checkbox) checkbox.checked = true;
    // Clear form and collapse
    ["qa-npc-desc","qa-npc-name","qa-npc-role","qa-npc-gender","qa-npc-age","qa-npc-appearance","qa-npc-personality"].forEach(id => {
      document.getElementById(id).value = "";
    });
    document.getElementById("qa-npc-gen-status").textContent = "";
    document.getElementById("qa-npc").removeAttribute("open");
    statusEl.textContent = `✓ ${name} added and selected.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

async function qaAddLocation() {
  const name = document.getElementById("qa-loc-name").value.trim();
  if (!name) { document.getElementById("qa-loc-status").textContent = "Name is required."; return; }
  const statusEl = document.getElementById("qa-loc-status");
  statusEl.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        description: document.getElementById("qa-loc-desc").value.trim(),
        current_state: document.getElementById("qa-loc-state").value.trim(),
      }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const saved = await res.json();
    // Add to datalist and set as selected location
    const dl = document.getElementById("location-suggestions");
    const opt = document.createElement("option");
    opt.value = saved.name;
    dl.appendChild(opt);
    document.getElementById("setup-location").value = saved.name;
    // Clear form and collapse
    ["qa-loc-name","qa-loc-desc","qa-loc-state"].forEach(id => document.getElementById(id).value = "");
    document.getElementById("qa-location").removeAttribute("open");
    statusEl.textContent = `✓ "${name}" added and set as location.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

async function qaAddFacts() {
  const raw = document.getElementById("qa-facts-input").value.trim();
  if (!raw) return;
  const newFacts = raw.split("\n").map(l => l.trim()).filter(Boolean);
  if (!newFacts.length) return;
  const statusEl = document.getElementById("qa-facts-status");
  statusEl.textContent = "Saving…";
  try {
    // Fetch existing facts, append new ones, replace all
    const existing = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`).then(r => r.json());
    const allFacts = [...existing.map(f => f.content), ...newFacts];
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts: allFacts }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    document.getElementById("qa-facts-input").value = "";
    document.getElementById("qa-facts").removeAttribute("open");
    statusEl.textContent = `✓ ${newFacts.length} fact${newFacts.length > 1 ? "s" : ""} added.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

// ── Scene setup ───────────────────────────────────────────────────────────────

async function _doBeginScene(title, location, intent, tone, npcIds, allowUnselectedNpcs) {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, location, npc_ids: npcIds, intent, tone, allow_unselected_npcs: allowUnselectedNpcs }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _scene = await res.json();
    showChatMode();
    renderSidebar();
    await streamOpeningNarration();
  } catch (e) {
    showError(`Could not start scene: ${e.message}`);
  }
}

function beginScene() {
  const title = document.getElementById("setup-title").value.trim();
  const location = document.getElementById("setup-location").value.trim();
  const intent = document.getElementById("setup-intent").value.trim();
  const tone = document.getElementById("setup-tone").value.trim();
  const npcIds = [...document.querySelectorAll("#npc-checkboxes input:checked")].map(c => c.value);
  const allowUnselectedNpcs = document.getElementById("setup-allow-unselected-npcs").checked;

  // Feature 3: conflict detection — warn about dead NPCs
  const deadNames = npcIds
    .map(id => _npcs.find(n => n.id === id))
    .filter(n => n && !n.is_alive)
    .map(n => n.name);
  if (deadNames.length) {
    showConfirm(
      `Warning: the following NPCs are marked as deceased:\n${deadNames.join(", ")}\n\nAdd them to this scene anyway?`,
      () => _doBeginScene(title, location, intent, tone, npcIds, allowUnselectedNpcs)
    );
    return;
  }
  _doBeginScene(title, location, intent, tone, npcIds, allowUnselectedNpcs);
}

async function streamOpeningNarration() {
  _streaming = true;
  setSendEnabled(false);
  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/open`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(gsGetParams()),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "assistant", content: buffer });
    await refreshSceneGMDecisions();

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
    document.getElementById("user-input").focus();
  }
}

function showChatMode() {
  document.getElementById("scene-setup-panel").classList.add("hidden");
  document.getElementById("chat-body").style.display = "";
  document.getElementById("end-scene-btn").style.display = "";
  if (!_scene?.confirmed) {
    document.getElementById("delete-scene-btn").style.display = "";
  }

  // Update header
  const title = _scene?.title || `Scene ${_scene?.scene_number ?? ""}`;
  document.getElementById("scene-title").textContent = title;
  document.title = `${title} — RP Utility`;
  if (_scene?.location)
    document.getElementById("scene-location-badge").textContent = `📍 ${_scene.location}`;
  if (_scene?.scene_number)
    document.getElementById("scene-num-badge").textContent = `Scene ${_scene.scene_number}`;

  // Tone badge
  const toneBadge = document.getElementById("scene-tone-badge");
  if (_scene?.tone) {
    toneBadge.textContent = _scene.tone;
    toneBadge.classList.remove("hidden");
  } else {
    toneBadge.classList.add("hidden");
  }

  // Scene header image
  const sceneImgWrap = document.getElementById("scene-header-img-wrap");
  const sceneImg     = document.getElementById("scene-header-img");
  if (sceneImg && sceneImgWrap) {
    if (_scene?.scene_image) {
      sceneImg.src = _scene.scene_image;
      sceneImgWrap.classList.remove("hidden");
    } else {
      sceneImgWrap.classList.add("hidden");
    }
  }

  updateUndoButton();
  document.getElementById("user-input").focus();
  refreshCompendiumSidebar();
}

function updateUndoButton() {
  const btn = document.getElementById("undo-btn");
  if (!btn) return;
  const hasTurns = (_scene?.turns?.length || 0) > 0;
  btn.style.display = (hasTurns && !_scene?.confirmed) ? "" : "none";
}

// ── Render existing scene turns ───────────────────────────────────────────────

function renderExistingTurns() {
  if (!_scene?.turns?.length) return;
  const area = document.getElementById("messages-area");
  area.innerHTML = "";
  _scene.turns.forEach((t, i) => {
    // Skip the silent continue nudge — it's not a real user message
    if (t.role === "user" && t.content === "(Continue the story.)") return;
    const div = appendMessage(t.role, t.content);
    _addEditButton(div, t.role, i);
  });
  scrollToBottom();
  updateUndoButton();
}

// ── Chat ──────────────────────────────────────────────────────────────────────

async function sendMessage() {
  if (_streaming) return;
  const input = document.getElementById("user-input");
  let text = input.value.trim();
  if (!text) return;
  input.value = "";
  input.style.height = "";
  _gmProcedurePreview = null;
  renderGMProcedureSidebar();

  // ── Dice roll command (/roll XdY or /roll XdY+Z) ─────────────────────────
  const diceMatch = text.match(/^\/roll\s+(\d*)d(\d+)([+-]\d+)?(.*)$/i);
  if (diceMatch) {
    const count  = parseInt(diceMatch[1] || "1");
    const sides  = parseInt(diceMatch[2]);
    const mod    = parseInt(diceMatch[3] || "0");
    const extra  = (diceMatch[4] || "").trim();
    if (count >= 1 && count <= 100 && sides >= 2 && sides <= 1000) {
      const rolls  = Array.from({ length: count }, () => Math.ceil(Math.random() * sides));
      const total  = rolls.reduce((a, b) => a + b, 0) + mod;
      const modStr = mod > 0 ? `+${mod}` : mod < 0 ? `${mod}` : "";
      const label  = `${count}d${sides}${modStr}`;
      const rollStr = rolls.length > 1 ? `[${rolls.join(", ")}]` : `${rolls[0]}`;
      const resultLine = `🎲 Roll ${label}: ${rollStr}${mod !== 0 ? ` ${mod > 0 ? "+" : ""}${mod}` : ""} = **${total}**`;
      appendDiceRoll(label, rolls, mod, total);
      // Build the message sent to AI — include roll result as context
      text = extra
        ? `${extra}\n\n*(${resultLine})*`
        : `*(${resultLine})*`;
    }
  }

  // Reset regenerate state — new exchange begins
  _clearRegenState();

  const userDiv = appendMessage("user", text);
  scrollToBottom();
  _streaming = true;
  setSendEnabled(false);

  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, user_name: _userName, ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    // Finalize and update local scene turns
    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "user", content: text });
    _scene.turns.push({ role: "assistant", content: buffer });

    // Attach edit buttons now that indices are known
    _addEditButton(userDiv, "user", _scene.turns.length - 2);
    _trackAiResponse(aiDiv, buffer, _scene.turns.length - 1);
    await refreshSceneGMDecisions();

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

async function continueStory() {
  if (_streaming) return;

  // Inject a silent system nudge — no user bubble shown in the chat
  const continueMsg = "(Continue the story.)";
  _gmProcedurePreview = null;
  renderGMProcedureSidebar();

  // Reset regenerate state — new exchange begins
  _clearRegenState();

  _streaming = true;
  setSendEnabled(false);

  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: continueMsg, user_name: "__continue__", ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "user", content: continueMsg });
    _scene.turns.push({ role: "assistant", content: buffer });

    _trackAiResponse(aiDiv, buffer, _scene.turns.length - 1);
    await refreshSceneGMDecisions();

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

// ── Regenerate helpers ────────────────────────────────────────────────────────

function _clearRegenState() {
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }
  _alternatives = [];
  _altIdx = 0;
  _lastAiDiv = null;
}

function _trackAiResponse(aiDiv, buffer, turnIndex = -1) {
  _lastAiDiv = aiDiv;
  _alternatives = [buffer];
  _altIdx = 0;
  if (turnIndex >= 0) _addEditButton(aiDiv, "assistant", turnIndex);
  _renderRegenControls();
}

// ── Inline turn editing ───────────────────────────────────────────────────────

function _addEditButton(bubbleDiv, role, turnIndex) {
  bubbleDiv.querySelector(".turn-edit-btn")?.remove();
  const btn = document.createElement("button");
  btn.className = "turn-edit-btn";
  btn.title = "Edit this message";
  btn.textContent = "✎";
  btn.onclick = (e) => { e.stopPropagation(); startTurnEdit(bubbleDiv, turnIndex, role); };
  bubbleDiv.appendChild(btn);
}

function startTurnEdit(bubbleDiv, turnIndex, role) {
  const originalContent = _scene?.turns?.[turnIndex]?.content ?? "";

  bubbleDiv.classList.add("bubble-edit-mode");
  bubbleDiv.innerHTML = "";

  const ta = document.createElement("textarea");
  ta.className = "turn-edit-textarea";
  ta.value = originalContent;
  // Auto-grow
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; });

  const btnRow = document.createElement("div");
  btnRow.className = "turn-edit-actions";

  const saveBtn = document.createElement("button");
  saveBtn.className = "btn btn-sm btn-primary";
  saveBtn.textContent = "Save";
  saveBtn.onclick = async () => {
    const newContent = ta.value.trim();
    if (!newContent) return;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    await saveTurnEdit(bubbleDiv, turnIndex, role, newContent, originalContent);
  };

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn btn-sm";
  cancelBtn.textContent = "Cancel";
  cancelBtn.onclick = () => _restoreBubble(bubbleDiv, role, originalContent, turnIndex);

  btnRow.append(saveBtn, cancelBtn);
  bubbleDiv.append(ta, btnRow);

  // Size textarea to content, focus
  requestAnimationFrame(() => {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  });
}

function _restoreBubble(bubbleDiv, role, content, turnIndex) {
  bubbleDiv.classList.remove("bubble-edit-mode");
  if (role === "assistant") {
    bubbleDiv.innerHTML = marked.parse(content);
    colorizeAiProse(bubbleDiv);
  } else {
    bubbleDiv.textContent = content;
  }
  _addEditButton(bubbleDiv, role, turnIndex);
}

async function saveTurnEdit(bubbleDiv, turnIndex, role, newContent, originalContent) {
  try {
    const res = await fetch(
      `/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/${turnIndex}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: newContent }) }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // Update local state
    if (_scene.turns?.[turnIndex]) _scene.turns[turnIndex].content = newContent;

    _restoreBubble(bubbleDiv, role, newContent, turnIndex);

    // Keep regen alternatives in sync if this is the tracked AI div
    if (role === "assistant" && bubbleDiv === _lastAiDiv) {
      _alternatives[_altIdx] = newContent;
    }
  } catch (e) {
    showError(`Could not save edit: ${e.message}`);
    _restoreBubble(bubbleDiv, role, originalContent, turnIndex);
  }
}

function _renderRegenControls() {
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }
  if (!_lastAiDiv) return;

  const div = document.createElement("div");
  div.className = "regen-controls";

  if (_alternatives.length > 1) {
    const prev = document.createElement("button");
    prev.className = "btn btn-ghost btn-xs";
    prev.textContent = "←";
    prev.title = "Previous response";
    prev.disabled = _altIdx === 0;
    prev.onclick = () => showAlternative(_altIdx - 1);

    const counter = document.createElement("span");
    counter.className = "regen-counter";
    counter.textContent = `${_altIdx + 1} / ${_alternatives.length}`;

    const next = document.createElement("button");
    next.className = "btn btn-ghost btn-xs";
    next.textContent = "→";
    next.title = "Next response";
    next.disabled = _altIdx === _alternatives.length - 1;
    next.onclick = () => showAlternative(_altIdx + 1);

    div.appendChild(prev);
    div.appendChild(counter);
    div.appendChild(next);
  }

  const regenBtn = document.createElement("button");
  regenBtn.className = "btn btn-ghost btn-xs";
  regenBtn.textContent = "↺ Regenerate";
  regenBtn.title = "Generate a new response for this message";
  regenBtn.onclick = regenerate;
  div.appendChild(regenBtn);

  _lastAiDiv.after(div);
  _regenControlsDiv = div;
}

async function showAlternative(idx) {
  if (idx < 0 || idx >= _alternatives.length || idx === _altIdx || !_lastAiDiv) return;
  _altIdx = idx;
  _lastAiDiv.innerHTML = marked.parse(_alternatives[idx]);
  colorizeAiProse(_lastAiDiv);
  _renderRegenControls();

  // Update the last assistant turn in the DB to match selection
  try {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/last-assistant`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: _alternatives[idx] }),
    });
  } catch (e) {
    showError(`Could not save selection: ${e.message}`);
  }

  // Keep local turns in sync
  if (_scene.turns && _scene.turns.length > 0) {
    const last = _scene.turns[_scene.turns.length - 1];
    if (last.role === "assistant") {
      _scene.turns[_scene.turns.length - 1] = { role: "assistant", content: _alternatives[idx] };
    }
  }
}

async function regenerate() {
  if (_streaming || !_lastAiDiv || !_scene) return;

  // Remove controls while streaming
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }

  _lastAiDiv.classList.add("streaming");
  _lastAiDiv.innerHTML = '<span class="typing-dot"></span>';

  _streaming = true;
  setSendEnabled(false);

  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      _lastAiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(_lastAiDiv, buffer);

    // Add to alternatives and update local turns
    _alternatives.push(buffer);
    _altIdx = _alternatives.length - 1;

    if (_scene.turns && _scene.turns.length > 0 &&
        _scene.turns[_scene.turns.length - 1].role === "assistant") {
      _scene.turns[_scene.turns.length - 1] = { role: "assistant", content: buffer };
    }

    _renderRegenControls();
    await refreshSceneGMDecisions();

  } catch (e) {
    _lastAiDiv.classList.remove("streaming");
    _lastAiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
    _renderRegenControls(); // restore the controls even on error
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

function deleteScene() {
  if (!_scene) return;
  if (_scene.confirmed) {
    showError("Cannot delete a confirmed scene.");
    return;
  }
  showConfirm("Delete this scene? This cannot be undone.", async () => {
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      window.location.href = `/campaigns/${CAMPAIGN_ID}`;
    } catch (e) {
      showError(`Delete failed: ${e.message}`);
    }
  });
}

// ── Message rendering ─────────────────────────────────────────────────────────

function appendMessage(role, content) {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = `message-bubble ${role === "user" ? "user-bubble" : "ai-bubble"}`;
  div.style.animation = "fadeIn 0.2s ease";

  if (role === "assistant") {
    div.innerHTML = marked.parse(content);
  } else {
    // Use textContent first to safely escape HTML, then colorize in-place
    div.textContent = content;
    // Re-set as a single text node so the walker can process it
  }
  colorizeAiProse(div);
  area.appendChild(div);
  return div;
}

function appendStreamingMessage() {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = "message-bubble ai-bubble streaming";
  div.style.animation = "fadeIn 0.2s ease";
  div.innerHTML = '<span class="typing-dot"></span>';
  area.appendChild(div);
  return div;
}

async function streamMechanicsFollowup(prompt) {
  if (_streaming || !_scene || !prompt.trim()) return;

  _clearRegenState();
  _streaming = true;
  setSendEnabled(false);

  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/mechanics-followup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, ...gsGetParams() }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "assistant", content: buffer });
    _trackAiResponse(aiDiv, buffer, _scene.turns.length - 1);
    await refreshSceneGMDecisions();
  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

function finalizeStreamingMessage(div, content) {
  div.classList.remove("streaming");
  div.innerHTML = marked.parse(content);
  colorizeAiProse(div);
}

/**
 * Walk all text nodes inside an AI bubble and wrap:
 *   "quoted speech"   → <span class="prose-dialogue">
 *   *emote text*      → <span class="prose-emote">  (if not already inside an <em>)
 * Normal narration stays unstyled (white).
 */
function colorizeAiProse(container) {
  // Process every text-bearing leaf node (skip <code>, <pre>)
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const tag = node.parentElement?.tagName?.toUpperCase();
      if (["CODE", "PRE", "SCRIPT", "STYLE"].includes(tag)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });

  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  nodes.forEach(textNode => {
    const raw = textNode.nodeValue;
    // Only process nodes that contain a quote or asterisk
    if (!raw.includes('"') && !raw.includes("*") && !raw.includes("\u2018") && !raw.includes("\u201C")) return;

    // Build a fragment replacing matches with coloured spans
    // Pattern: "quoted" → dialogue, *emote* → emote (avoid double-wrapping <em>)
    const frag = document.createDocumentFragment();
    // Combined regex: "..." or *...*
    const re = /("(?:[^"\\]|\\.)*"|\u201C[^\u201D]*\u201D|\*[^*\n]+\*)/g;
    let last = 0, m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) frag.appendChild(document.createTextNode(raw.slice(last, m.index)));
      const span = document.createElement("span");
      const isEmote = m[0].startsWith("*");
      span.className = isEmote ? "prose-emote" : "prose-dialogue";
      // Strip the surrounding * for emote (marked already handles <em> in block elements;
      // this handles inline *text* that wasn't wrapped)
      span.textContent = isEmote ? m[0].slice(1, -1) : m[0];
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    if (last < raw.length) frag.appendChild(document.createTextNode(raw.slice(last)));
    if (last > 0) textNode.replaceWith(frag);
  });
}

// ── End scene ─────────────────────────────────────────────────────────────────

function openEndScene() {
  document.getElementById("scene-summary-input").value = _scene?.proposed_summary || "";
  openModal("end-scene-modal");
}

async function suggestSummary() {
  document.getElementById("suggest-loading").style.display = "";
  document.querySelector("#end-scene-suggest-row .btn").disabled = true;
  const modelName = document.getElementById("summary-model-select").value || null;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/suggest-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.summary) document.getElementById("scene-summary-input").value = data.summary;
  } catch (e) {
    showError(`Could not generate summary: ${e.message}`);
  } finally {
    document.getElementById("suggest-loading").style.display = "none";
    document.querySelector("#end-scene-suggest-row .btn").disabled = false;
  }
}

async function confirmEndScene() {
  const summary = document.getElementById("scene-summary-input").value.trim();
  if (!summary) {
    alert("Please write a summary before confirming.");
    return;
  }
  const confirmBtn = document.querySelector("#end-scene-modal .btn-primary");
  confirmBtn.disabled = true;
  confirmBtn.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposed_summary: summary }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    closeModal("end-scene-modal");
    await loadWorldUpdateSuggestions();
  } catch (e) {
    showError(`Could not confirm scene: ${e.message}`);
    confirmBtn.disabled = false;
    confirmBtn.textContent = "✓ Confirm & Close Scene";
  }
}

// ── World update suggestions (Feature 2) ──────────────────────────────────────

let _pendingSuggestions = null;

async function loadWorldUpdateSuggestions() {
  const footer = document.getElementById("world-updates-footer");
  const body = document.getElementById("world-updates-body");
  openModal("world-updates-modal");
  body.querySelector("p").textContent = "Analysing story impact…";
  document.getElementById("wu-npc-section").classList.add("hidden");
  document.getElementById("wu-facts-section").classList.add("hidden");
  document.getElementById("wu-threads-section").classList.add("hidden");
  document.getElementById("wu-new-npcs-section").classList.add("hidden");
  document.getElementById("wu-new-locations-section").classList.add("hidden");
  document.getElementById("wu-history-section").classList.add("hidden");
  document.getElementById("wu-forms-section").classList.add("hidden");
  document.getElementById("wu-none-msg").classList.add("hidden");
  footer.style.display = "none";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/suggest-updates`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _pendingSuggestions = await res.json();
  } catch (e) {
    body.querySelector("p").textContent = `Could not generate suggestions: ${e.message}`;
    footer.style.display = "";
    document.getElementById("wu-none-msg").classList.remove("hidden");
    _pendingSuggestions = null;
    return;
  }

  body.querySelector("p").textContent =
    "Based on what happened in this scene, the following world document updates are suggested. Uncheck any you want to skip, then click Apply.";
  footer.style.display = "";

  const { npc_updates = [], new_facts = [], thread_updates = [], new_npcs = [], new_locations = [],
          history_updates = [], form_transitions = [],
          _model, _parse_ok, _raw } = _pendingSuggestions;
  const hasAny = npc_updates.length || new_facts.length || thread_updates.length || new_npcs.length
    || new_locations.length || history_updates.length || form_transitions.length;

  if (!hasAny) {
    const noneEl = document.getElementById("wu-none-msg");
    noneEl.classList.remove("hidden");
    const modelLabel = _model ? `<strong>${escHtml(_model)}</strong>` : "the model";
    const rawHtml = _raw
      ? `<details style="margin-top:10px;text-align:left"><summary style="cursor:pointer;color:var(--text-muted);font-size:0.8rem">▶ Show raw model output (debug)</summary>` +
        `<pre style="font-size:0.75rem;white-space:pre-wrap;max-height:200px;overflow-y:auto;margin-top:6px;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px">${escHtml(_raw)}</pre></details>`
      : "";
    if (_parse_ok === false) {
      noneEl.innerHTML = `${modelLabel} did not return valid JSON. Try a different Summary Model in Campaign Settings.${rawHtml}`;
    } else {
      noneEl.innerHTML = `No updates detected by ${modelLabel}. If this is wrong, check the raw output below — the model may be incorrectly deciding nothing qualifies.${rawHtml}`;
    }
    return;
  }

  if (npc_updates.length) {
    document.getElementById("wu-npc-section").classList.remove("hidden");
    document.getElementById("wu-npc-list").innerHTML = npc_updates.map((u, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-npc-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(u.npc_name)}</strong> —
          <span class="muted">${escHtml(u.field)}</span>:
          <span class="wu-old">${escHtml(String(u.current_value))}</span> →
          <span class="wu-new">${escHtml(String(u.suggested_value))}</span>
          <div class="wu-reason muted">${escHtml(u.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (new_facts.length) {
    document.getElementById("wu-facts-section").classList.remove("hidden");
    document.getElementById("wu-facts-list").innerHTML = new_facts.map((f, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-fact-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          ${escHtml(f.content)}
          <div class="wu-reason muted">${escHtml(f.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (thread_updates.length) {
    document.getElementById("wu-threads-section").classList.remove("hidden");
    document.getElementById("wu-threads-list").innerHTML = thread_updates.map((t, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-thread-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(t.thread_title)}</strong> → mark as
          <span class="wu-new">${escHtml(t.new_status)}</span>
          <div class="wu-reason muted">${escHtml(t.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (new_npcs.length) {
    document.getElementById("wu-new-npcs-section").classList.remove("hidden");
    const list = document.getElementById("wu-new-npcs-list");
    list.innerHTML = "";
    new_npcs.forEach((n, i) => list.appendChild(_buildNpcProposalCard(n, i)));
  }

  if (new_locations.length) {
    document.getElementById("wu-new-locations-section").classList.remove("hidden");
    document.getElementById("wu-new-locations-list").innerHTML = new_locations.map((l, i) => `
      <label class="wu-item wu-new-entity">
        <input type="checkbox" class="wu-new-loc-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(l.name)}</strong>
          ${l.description ? `<div class="wu-entity-detail">${escHtml(l.description)}</div>` : ""}
          <div class="wu-reason muted">${escHtml(l.significance || "")}</div>
        </div>
      </label>`).join("");
  }

  if (history_updates.length) {
    document.getElementById("wu-history-section").classList.remove("hidden");
    document.getElementById("wu-history-list").innerHTML = history_updates.map((h, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-history-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(h.npc_name)}</strong> — history update
          <div class="wu-entity-detail">${escHtml(h.new_history)}</div>
          <div class="wu-reason muted">${escHtml(h.reason || "")}</div>
        </div>
      </label>`).join("");
  }

  if (form_transitions.length) {
    document.getElementById("wu-forms-section").classList.remove("hidden");
    document.getElementById("wu-forms-list").innerHTML = form_transitions.map((t, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-form-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(t.npc_name)}</strong> — active form →
          <span class="wu-new">${escHtml(t.new_active_form || "(base)")}</span>
          <div class="wu-reason muted">${escHtml(t.reason || "")}</div>
        </div>
      </label>`).join("");
  }
}

function _buildNpcProposalCard(n, i) {
  const card = document.createElement("div");
  card.className = "wu-npc-proposal-card";
  card.dataset.index = i;

  // Field helper: renders a label + input or textarea
  const field = (label, key, value, multiline = false) => {
    const row = document.createElement("div");
    row.className = "wu-npc-field-row";
    const lbl = document.createElement("label");
    lbl.className = "wu-npc-field-label";
    lbl.textContent = label;
    let input;
    if (multiline) {
      input = document.createElement("textarea");
      input.rows = 2;
    } else {
      input = document.createElement("input");
      input.type = "text";
    }
    input.className = "wu-npc-field-input wb-field";
    input.dataset.field = key;
    input.value = value || "";
    row.append(lbl, input);
    return row;
  };

  // Header: name + accept/reject buttons
  const header = document.createElement("div");
  header.className = "wu-npc-proposal-header";
  const titleEl = document.createElement("div");
  titleEl.className = "wu-npc-proposal-title";
  titleEl.innerHTML = `<strong>${escHtml(n.name)}</strong>${n.role ? ` <span class="muted">— ${escHtml(n.role)}</span>` : ""}`;

  const actions = document.createElement("div");
  actions.className = "wu-npc-proposal-actions";
  const acceptBtn = document.createElement("button");
  acceptBtn.className = "btn btn-sm btn-primary";
  acceptBtn.textContent = "✓ Accept";
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "btn btn-sm btn-ghost";
  rejectBtn.textContent = "✕ Reject";
  acceptBtn.onclick = () => { card.classList.remove("rejected"); acceptBtn.classList.add("active-accept"); };
  rejectBtn.onclick = () => { card.classList.toggle("rejected"); };
  actions.append(acceptBtn, rejectBtn);
  header.append(titleEl, actions);

  // Significance note
  const sig = document.createElement("div");
  sig.className = "wu-npc-significance muted";
  sig.textContent = n.significance || "";

  // Fields grid
  const grid = document.createElement("div");
  grid.className = "wu-npc-fields-grid";
  grid.append(
    field("Name",                   "name",                   n.name),
    field("Role / Occupation",      "role",                   n.role),
    field("Gender",                 "gender",                 n.gender),
    field("Age",                    "age",                    n.age),
    field("Appearance",             "appearance",             n.appearance,             true),
    field("Personality",            "personality",            n.personality,            true),
    field("Relationship to Player", "relationship_to_player", n.relationship_to_player),
    field("Current Location",       "current_location",       n.current_location),
    field("Current State",          "current_state",          n.current_state),
    field("Short-term Goal",        "short_term_goal",        n.short_term_goal),
    field("Long-term Goal",         "long_term_goal",         n.long_term_goal),
    field("Secrets / Hidden Info",  "secrets",                n.secrets,                true),
  );

  card.append(header, sig, grid);
  return card;
}

async function applyWorldUpdates() {
  if (!_pendingSuggestions) { skipWorldUpdates(); return; }
  const applyBtn = document.querySelector("#world-updates-modal .btn-primary");
  applyBtn.disabled = true;
  applyBtn.textContent = "Applying…";

  const { npc_updates = [], new_facts = [], thread_updates = [], new_npcs = [], new_locations = [],
          history_updates = [], form_transitions = [] } = _pendingSuggestions;

  // Apply checked NPC updates
  const checkedNpcs = [...document.querySelectorAll(".wu-npc-cb:checked")].map(cb => npc_updates[+cb.dataset.index]);
  for (const u of checkedNpcs) {
    const npc = _npcs.find(n => n.id === u.npc_id);
    if (!npc) continue;
    const updated = { ...npc, [u.field]: u.suggested_value };
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }).catch(() => {});
  }

  // Apply checked new facts — append to existing facts
  const checkedFacts = [...document.querySelectorAll(".wu-fact-cb:checked")].map(cb => new_facts[+cb.dataset.index]);
  if (checkedFacts.length) {
    const existingContents = _facts.map(f => f.content);
    const allFacts = [...existingContents, ...checkedFacts.map(f => f.content)];
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts: allFacts }),
    }).catch(() => {});
  }

  // Apply checked thread status updates
  const checkedThreads = [...document.querySelectorAll(".wu-thread-cb:checked")].map(cb => thread_updates[+cb.dataset.index]);
  for (const u of checkedThreads) {
    const thread = _threads.find(t => t.id === u.thread_id)
      || (await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`).then(r => r.json()).catch(() => []))
          .find(t => t.id === u.thread_id);
    if (!thread) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...thread,
        status: u.new_status,
        last_mentioned_scene: _scene?.scene_number || thread.last_mentioned_scene || 0,
      }),
    }).catch(() => {});
  }

  // Create approved new NPCs — read values from editable card inputs
  const acceptedNpcCards = [...document.querySelectorAll(".wu-npc-proposal-card:not(.rejected)")];
  for (const card of acceptedNpcCards) {
    const f = (id) => card.querySelector(`[data-field="${id}"]`)?.value?.trim() || "";
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:                   f("name"),
        role:                   f("role"),
        gender:                 f("gender"),
        age:                    f("age"),
        appearance:             f("appearance"),
        personality:            f("personality"),
        relationship_to_player: f("relationship_to_player"),
        current_location:       f("current_location"),
        current_state:          f("current_state"),
        short_term_goal:        f("short_term_goal"),
        long_term_goal:         f("long_term_goal"),
        secrets:                f("secrets"),
      }),
    }).catch(() => {});
  }

  // Create approved new locations
  const checkedNewLocs = [...document.querySelectorAll(".wu-new-loc-cb:checked")].map(cb => new_locations[+cb.dataset.index]);
  for (const l of checkedNewLocs) {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: l.name,
        description: l.description || "",
        current_state: l.current_state || "",
      }),
    }).catch(() => {});
  }

  // Apply checked history updates
  const checkedHistory = [...document.querySelectorAll(".wu-history-cb:checked")].map(cb => history_updates[+cb.dataset.index]);
  for (const h of checkedHistory) {
    const npc = _npcs.find(n => n.id === h.npc_id);
    if (!npc) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...npc, history_with_player: h.new_history }),
    }).catch(() => {});
  }

  // Apply checked form transitions
  const checkedForms = [...document.querySelectorAll(".wu-form-cb:checked")].map(cb => form_transitions[+cb.dataset.index]);
  for (const t of checkedForms) {
    const npc = _npcs.find(n => n.id === t.npc_id);
    if (!npc) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...npc, active_form: t.new_active_form || null }),
    }).catch(() => {});
  }

  skipWorldUpdates();
}

function skipWorldUpdates() {
  closeModal("world-updates-modal");
  window.location.href = `/campaigns/${CAMPAIGN_ID}`;
}

// ── Sidebar rendering ─────────────────────────────────────────────────────────

function renderSidebar() {
  // NPCs in scene
  const npcContainer = document.getElementById("sidebar-npcs");
  const sceneNpcIds = new Set(_scene?.npc_ids || []);
  const sceneNpcs = _npcs.filter(n => sceneNpcIds.has(n.id));
  if (sceneNpcs.length) {
    npcContainer.innerHTML = "";
    sceneNpcs.forEach(n => {
      const portraitHtml = n.portrait_image
        ? `<img src="${escHtml(n.portrait_image)}" class="sidebar-npc-portrait" alt="${escHtml(n.name)}" onclick="openPortraitLightbox('${escHtml(n.portrait_image)}','${escHtml(n.name)}')" title="Click to enlarge">`
        : `<div class="sidebar-npc-portrait sidebar-npc-portrait-placeholder">👤</div>`;

      // Quick-reference detail rows
      const detailRows = [
        n.personality       ? `<div class="npc-qr-row"><span class="npc-qr-label">Personality</span> ${escHtml(n.personality.substring(0, 80))}${n.personality.length > 80 ? "…" : ""}</div>` : "",
        n.relationship_to_player ? `<div class="npc-qr-row"><span class="npc-qr-label">To Player</span> ${escHtml(n.relationship_to_player.substring(0, 80))}${n.relationship_to_player.length > 80 ? "…" : ""}</div>` : "",
        n.current_location  ? `<div class="npc-qr-row"><span class="npc-qr-label">Location</span> ${escHtml(n.current_location)}</div>` : "",
        n.short_term_goal   ? `<div class="npc-qr-row"><span class="npc-qr-label">Goal</span> ${escHtml(n.short_term_goal.substring(0, 80))}${n.short_term_goal.length > 80 ? "…" : ""}</div>` : "",
        n.secrets           ? `<div class="npc-qr-row npc-qr-secret"><span class="npc-qr-label">Secret</span> ${escHtml(n.secrets.substring(0, 100))}${n.secrets.length > 100 ? "…" : ""}</div>` : "",
      ].filter(Boolean).join("");

      const cardId = `npc-qr-${n.id.replace(/[^a-z0-9]/gi, "")}`;
      const card = document.createElement("div");
      card.className = "sidebar-item sidebar-npc-item npc-quick-ref";
      card.innerHTML = `
        <div class="npc-qr-header" data-target="${cardId}">
          ${portraitHtml}
          <div style="min-width:0;flex:1">
            <div class="sidebar-item-name">${escHtml(n.name)}</div>
            ${n.role ? `<div class="sidebar-item-sub muted">${escHtml(n.role)}</div>` : ""}
            ${n.current_state ? `<div class="sidebar-item-sub">${escHtml(n.current_state)}</div>` : ""}
          </div>
          <span class="npc-qr-chevron">▾</span>
        </div>
        ${detailRows ? `<div id="${cardId}" class="npc-qr-details hidden">${detailRows}</div>` : ""}`;

      // Toggle expand on header click
      card.querySelector(".npc-qr-header").addEventListener("click", () => {
        const details = document.getElementById(cardId);
        if (!details) return;
        const open = !details.classList.contains("hidden");
        details.classList.toggle("hidden", open);
        card.querySelector(".npc-qr-chevron").textContent = open ? "▾" : "▴";
      });

      npcContainer.appendChild(card);
    });
  } else {
    npcContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No NPCs in this scene.</div>';
  }

  // Threads
  const threadContainer = document.getElementById("sidebar-threads");
  if (_threads.length) {
    threadContainer.innerHTML = _threads.map(t => {
      const sceneNum = _scene?.scene_number || 0;
      const mentionedAt = t.last_mentioned_scene || 0;
      const gap = mentionedAt && sceneNum > mentionedAt ? sceneNum - mentionedAt : 0;
      const staleBadge = gap >= 5
        ? `<span class="thread-stale-badge thread-stale-critical" title="${gap} scenes since last advanced">${gap} scenes ago</span>`
        : gap >= 3
        ? `<span class="thread-stale-badge" title="${gap} scenes since last advanced">${gap} scenes ago</span>`
        : "";
      return `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(t.title)}${staleBadge}</div>
        ${t.description ? `<div class="sidebar-item-sub muted">${escHtml(t.description.substring(0, 80))}${t.description.length > 80 ? "…" : ""}</div>` : ""}
      </div>`;
    }).join("");
  } else {
    threadContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No active threads.</div>';
  }

  renderRulesSidebar();
  renderAdventureSidebar();
  renderRecapSidebar();
  renderCompendiumSidebar();
  renderGMProcedureSidebar();
  renderEncounterSidebar();
  renderRuleAuditSidebar();
  renderActionLogSidebar();

  // World facts (first 5)
  const factsContainer = document.getElementById("sidebar-facts");
  const displayFacts = _facts.slice(0, 5);
  if (displayFacts.length) {
    factsContainer.innerHTML = displayFacts.map(f => `
      <div class="sidebar-item sidebar-fact">• ${escHtml(f.content.substring(0, 100))}${f.content.length > 100 ? "…" : ""}</div>
    `).join("");
  } else {
    factsContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No world facts.</div>';
  }

  // Scene context modal
  buildContextModal();
}

function isD20RulesMode() {
  return _campaign?.play_mode === "rules" && _campaign?.system_pack === "d20-fantasy-core";
}

function renderAdventureSidebar() {
  const section = document.getElementById("adventure-section");
  const container = document.getElementById("sidebar-adventure");
  const addObjectiveButton = document.getElementById("add-objective-btn");
  const addQuestButton = document.getElementById("add-quest-btn");
  const addEventButton = document.getElementById("add-event-btn");
  const downtimeButton = document.getElementById("run-downtime-btn");
  const advanceQuestButton = document.getElementById("advance-quest-btn");
  const generateTreasureButton = document.getElementById("generate-treasure-btn");
  if (!section || !container || !addObjectiveButton || !addQuestButton || !addEventButton || !downtimeButton || !advanceQuestButton || !generateTreasureButton) return;

  const isRulesMode = isD20RulesMode();
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const activeObjectives = (_objectives || []).filter(objective => objective.status === "active");
  const activeQuests = (_quests || []).filter(quest => quest.status === "active");
  const recentEvents = (_events || []).slice(0, 3);
  advanceQuestButton.disabled = !activeQuests.length;
  generateTreasureButton.disabled = !_sheet?.name;

  const objectiveHtml = activeObjectives.length
    ? activeObjectives.slice(0, 4).map(objective => `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(objective.title)}</div>
        ${objective.description ? `<div class="sidebar-item-sub muted">${escHtml(objective.description)}</div>` : ""}
      </div>
    `).join("")
    : '<div class="gm-empty">No active objectives.</div>';

  const questHtml = activeQuests.length
    ? activeQuests.slice(0, 4).map(quest => {
      const nextStage = (quest.stages || []).find(stage => !stage.completed);
      return `
        <div class="sidebar-item">
          <div class="sidebar-item-name">${escHtml(quest.title)}</div>
          <div class="sidebar-item-sub muted">${escHtml(quest.progress_label || quest.status)}</div>
          ${quest.description ? `<div class="sidebar-item-sub">${escHtml(quest.description)}</div>` : ""}
          ${nextStage ? `<div class="sidebar-item-sub muted">Next: ${escHtml(nextStage.description)}</div>` : ""}
        </div>
      `;
    }).join("")
    : '<div class="gm-empty">No active quests.</div>';

  const eventHtml = recentEvents.length
    ? recentEvents.map(event => {
      const escalationLevel = Number(event.details?.escalation_level || 0);
      const hookType = String(event.details?.hook_type || "").replaceAll("_", " ");
      const consequenceKind = String(event.details?.last_consequence?.kind || "").replaceAll("_", " ");
      const severity = escalationLevel > 0 ? `Severity ${escalationLevel}` : "";
      const targetHint = event.details?.faction_id
        ? `Target faction: ${escHtml(event.details.faction_id)}`
        : event.details?.quest_id
          ? `Target quest: ${escHtml(event.details.quest_id)}`
          : "";
      return `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(event.title)}</div>
        <div class="sidebar-item-sub muted">${escHtml((event.event_type || "world").replaceAll("_", " "))} · ${escHtml(event.world_time?.label || "")}</div>
        ${(hookType || severity) ? `<div class="sidebar-item-sub muted">${escHtml([hookType, severity].filter(Boolean).join(" · "))}</div>` : ""}
        ${event.content ? `<div class="sidebar-item-sub">${escHtml(event.content)}</div>` : ""}
        ${consequenceKind ? `<div class="sidebar-item-sub muted">Fallout: ${escHtml(consequenceKind)}</div>` : ""}
        ${targetHint ? `<div class="sidebar-item-sub muted">${targetHint}</div>` : ""}
        <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" onclick="editCampaignEvent('${escHtml(event.id)}')">Edit</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleCampaignEventStatus('${escHtml(event.id)}')">${event.status === "pending" ? "Resolve" : "Reopen"}</button>
          ${event.status === "pending" && event.details?.hook_type === "encounter" ? `<button class="btn btn-ghost btn-sm" onclick="generateEncounterFromEvent('${escHtml(event.id)}')">Trigger Encounter</button>` : ""}
        </div>
      </div>
    `;
    }).join("")
    : '<div class="gm-empty">No scheduled campaign events yet.</div>';

  container.innerHTML = `
    <div class="sidebar-item">
      <div class="sidebar-item-sub muted">Objectives</div>
    </div>
    ${objectiveHtml}
    <div class="sidebar-item" style="margin-top:8px">
      <div class="sidebar-item-sub muted">Quests</div>
    </div>
    ${questHtml}
    <div class="sidebar-item" style="margin-top:8px">
      <div class="sidebar-item-sub muted">Recent Events</div>
    </div>
    ${eventHtml}
  `;
}

function renderRecapSidebar() {
  const section = document.getElementById("recap-section");
  const container = document.getElementById("sidebar-recap");
  if (!section || !container) return;

  const isRulesMode = isD20RulesMode();
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const items = Array.isArray(_campaignRecap?.items) ? _campaignRecap.items : [];
  if (!items.length) {
    container.innerHTML = '<div class="gm-empty">No merged recap entries yet.</div>';
    return;
  }

  container.innerHTML = items.slice(0, 6).map(item => `
    <div class="sidebar-item">
      <div class="sidebar-item-name">${escHtml(item.title || item.kind || "Entry")}</div>
      <div class="sidebar-item-sub muted">${escHtml(item.kind || "")}${item.world_time ? ` · ${escHtml(item.world_time)}` : ""}</div>
      <div class="sidebar-item-sub">${escHtml(item.summary || "")}</div>
    </div>
  `).join("");
}

function renderRulesSidebar() {
  const section = document.getElementById("rules-sheet-section");
  const button = document.getElementById("resolve-check-btn");
  const stateButton = document.getElementById("sheet-state-btn");
  const timeButton = document.getElementById("advance-time-btn");
  const shortRestButton = document.getElementById("short-rest-btn");
  const longRestButton = document.getElementById("long-rest-btn");
  const container = document.getElementById("sidebar-sheet");
  if (!container || !section || !button || !stateButton || !timeButton || !shortRestButton || !longRestButton) return;

  const isRulesMode = isD20RulesMode();
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  if (!_sheet || !_sheet.name) {
    container.innerHTML = '<div class="muted" style="font-size:0.8rem">No character sheet yet. Add one from the campaign overview to get deterministic checks.</div>';
    button.disabled = true;
    stateButton.disabled = true;
    timeButton.disabled = true;
    shortRestButton.disabled = true;
    longRestButton.disabled = true;
    return;
  }

  const playerCanAct = !_activeEncounter || _activeEncounter.current_participant?.owner_type === "player";
  const canRest = !_activeEncounter;
  timeButton.disabled = false;
  button.disabled = !playerCanAct;
  stateButton.disabled = !playerCanAct;
  shortRestButton.disabled = !canRest;
  longRestButton.disabled = !canRest;
  const abilities = _sheet.abilities || {};
  const abilityLine = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    .map(key => `${key.slice(0, 3).toUpperCase()} ${abilities[key] ?? 10}`)
    .join(" · ");
  const conditions = (_sheet.conditions || []).length
    ? (_sheet.conditions || []).join(", ")
    : "None";
  const topSkills = Object.entries(_sheet.skill_modifiers || {})
    .slice(0, 6)
    .map(([key, value]) => `${key} ${value >= 0 ? "+" : ""}${value}`)
    .join(" · ");
  const resourcePools = Object.entries(_sheet.resource_pools || {})
    .slice(0, 4)
    .map(([key, value]) => {
      const current = value?.current ?? 0;
      const maximum = value?.maximum ?? current;
      return `${key} ${current}/${maximum}`;
    })
    .join(" · ");
  const preparedSpells = (_sheet.prepared_spells || []).slice(0, 4).join(", ");
  const equippedItems = Object.entries(_sheet.equipped_items || {})
    .slice(0, 4)
    .map(([slot, slug]) => `${slot}: ${slug}`)
    .join(" · ");
  const itemCharges = Object.entries(_sheet.item_charges || {})
    .slice(0, 4)
    .map(([slug, value]) => `${slug} ${value?.current ?? 0}/${value?.max ?? 0}`)
    .join(" · ");
  const worldTimeLabel = _campaign?.world_time?.label || "Day 1, 00:00";

  container.innerHTML = `
    <div class="sidebar-item">
      <div class="sidebar-item-name">${escHtml(_sheet.name)}</div>
      <div class="sidebar-item-sub muted">${escHtml(_sheet.character_class || "Adventurer")} · Level ${_sheet.level || 1}${_sheet.ancestry ? ` · ${escHtml(_sheet.ancestry)}` : ""}</div>
    </div>
    <div class="sidebar-item">
      <div class="sidebar-item-sub muted">World Time: ${escHtml(worldTimeLabel)}</div>
    </div>
    <div class="sidebar-item">
      <div class="sidebar-item-sub">HP ${_sheet.current_hp}/${_sheet.max_hp}${_sheet.temp_hp ? ` (+${_sheet.temp_hp} temp)` : ""} · AC ${_sheet.armor_class} · Speed ${_sheet.speed}</div>
    </div>
    <div class="sidebar-item">
      <div class="sidebar-item-sub">${escHtml(abilityLine)}</div>
    </div>
    ${topSkills ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Skills: ${escHtml(topSkills)}</div></div>` : ""}
    ${resourcePools ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Resources: ${escHtml(resourcePools)}</div></div>` : ""}
    ${preparedSpells ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Prepared: ${escHtml(preparedSpells)}</div></div>` : ""}
    ${equippedItems ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Equipped: ${escHtml(equippedItems)}</div></div>` : ""}
    ${itemCharges ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Item Charges: ${escHtml(itemCharges)}</div></div>` : ""}
    <div class="sidebar-item">
      <div class="sidebar-item-sub muted">Conditions: ${escHtml(conditions)}</div>
    </div>
    ${!playerCanAct && _activeEncounter?.current_participant ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Action gating: waiting for ${escHtml(_activeEncounter.current_participant.name)}'s turn.</div></div>` : ""}
    ${!canRest && _activeEncounter ? `<div class="sidebar-item"><div class="sidebar-item-sub muted">Resting is disabled while an encounter is active.</div></div>` : ""}
  `;
}

function renderCompendiumSidebar() {
  const section = document.getElementById("compendium-section");
  const container = document.getElementById("sidebar-compendium");
  const searchInput = document.getElementById("compendium-search");
  const categorySelect = document.getElementById("compendium-category");
  if (!section || !container || !searchInput || !categorySelect) return;

  const isRulesMode = isD20RulesMode();
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const query = searchInput.value.trim().toLowerCase();
  const category = categorySelect.value || "";
  const filtered = (_compendiumEntries || []).filter(entry => {
    if (category && entry.category !== category) return false;
    if (!query) return true;
    const haystack = [
      entry.name,
      entry.slug,
      entry.description,
      entry.rules_text,
      ...(entry.tags || []),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  }).slice(0, 10);

  if (!_compendiumEntries.length) {
    container.innerHTML = '<div class="gm-empty">No compendium entries loaded yet.</div>';
    return;
  }
  if (!filtered.length) {
    container.innerHTML = '<div class="gm-empty">No matching compendium entries.</div>';
    return;
  }

  container.innerHTML = filtered.map((entry, index) => `
    <div class="sidebar-item">
      <div class="sidebar-item-name">${escHtml(entry.name)}</div>
      <div class="sidebar-item-sub muted">${escHtml(entry.category)}${entry.action_cost ? ` · ${escHtml(entry.action_cost.replaceAll("_", " "))}` : ""}${entry.range_feet !== null && entry.range_feet !== undefined ? ` · ${entry.range_feet} ft` : ""}</div>
      ${entry.description ? `<div class="sidebar-item-sub">${escHtml(entry.description)}</div>` : ""}
      ${entry.category === "spell" && isSpellPrepared(entry.slug) ? `<div class="sidebar-item-sub muted">Prepared</div>` : ""}
      ${entry.equipment_slot ? `<div class="sidebar-item-sub muted">${escHtml(entry.equipment_slot)}${entry.armor_class_bonus ? ` · AC ${entry.armor_class_bonus >= 0 ? "+" : ""}${entry.armor_class_bonus}` : ""}${entry.charges_max ? ` · ${entry.charges_max} charges` : ""}${isItemEquipped(entry.slug) ? " · Equipped" : ""}</div>` : ""}
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" onclick="useCompendiumEntry('${escHtml(entry.slug)}')">Use</button>
        <button class="btn btn-ghost btn-sm" onclick="previewCompendiumEntry('${escHtml(entry.slug)}')">Details</button>
        ${entry.category === "spell" ? `<button class="btn btn-ghost btn-sm" onclick="togglePreparedSpell('${escHtml(entry.slug)}', ${isSpellPrepared(entry.slug) ? "false" : "true"})">${isSpellPrepared(entry.slug) ? "Unprepare" : "Prepare"}</button>` : ""}
        ${entry.equipment_slot ? `<button class="btn btn-ghost btn-sm" onclick="toggleEquipmentEntry('${escHtml(entry.slug)}', ${isItemEquipped(entry.slug) ? "false" : "true"})">${isItemEquipped(entry.slug) ? "Unequip" : "Equip"}</button>` : ""}
      </div>
    </div>
  `).join("");
}

function scheduleCompendiumRefresh() {
  clearTimeout(_compendiumTimer);
  _compendiumTimer = setTimeout(() => {
    renderCompendiumSidebar();
  }, 150);
}

async function refreshCompendiumSidebar() {
  if (!isD20RulesMode()) return;
  try {
    const category = document.getElementById("compendium-category")?.value || "";
    const query = document.getElementById("compendium-search")?.value?.trim() || "";
    const params = new URLSearchParams();
    params.set("system_pack", _campaign?.system_pack || "d20-fantasy-core");
    if (category) params.set("category", category);
    if (query) params.set("query", query);
    const res = await fetch(`/api/campaigns/compendium?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _compendiumEntries = await res.json();
  } catch (e) {
    _compendiumEntries = [];
    showError(`Could not load compendium: ${e.message}`);
  }
  renderCompendiumSidebar();
}

function useCompendiumEntry(slug) {
  const entry = (_compendiumEntries || []).find(item => item.slug === slug);
  if (!entry) {
    showToast("Compendium entry not found.", "info");
    return;
  }
  if (entry.category === "spell" && !isSpellPrepared(entry.slug)) {
    showToast(`Prepare ${entry.name} on the rules sheet before using it.`, "info", 5000);
    return;
  }
  if (_activeEncounter && ["dash", "dodge", "disengage", "bless", "help", "second-wind", "healing-word", "cure-wounds", "magic-missile", "healing-wand"].includes(entry.slug)) {
    useEncounterCompendiumEntry(entry);
    return;
  }
  if (entry.category === "armor" || (entry.category === "item" && entry.equipment_slot)) {
    showToast(`Use the ${isItemEquipped(entry.slug) ? "Unequip" : "Equip"} button for ${entry.name}.`, "info", 5000);
    return;
  }
  const baseReason = document.getElementById("user-input")?.value?.trim() || "";
  if (entry.category === "action" || entry.category === "weapon") {
    openResolveAttackModal({
      source: entry.name,
      range_feet: entry.range_feet,
      action_cost: entry.action_cost || "action",
      resource_costs: entry.resource_costs || {},
      reason: baseReason,
    });
    return;
  }
  if (entry.category === "spell") {
    const nameLower = String(entry.name || "").toLowerCase();
    if (nameLower.includes("heal") || nameLower.includes("cure") || nameLower.includes("word")) {
      openResolveHealingModal({
        source: entry.name,
        range_feet: entry.range_feet,
        action_cost: entry.action_cost || "action",
        resource_costs: entry.resource_costs || {},
        reason: baseReason,
      });
      return;
    }
    openResolveAttackModal({
      source: entry.name,
      range_feet: entry.range_feet,
      action_cost: entry.action_cost || "action",
      resource_costs: entry.resource_costs || {},
      reason: baseReason,
    });
    return;
  }
  if (entry.category === "condition") {
    showToast(`Condition reference: ${entry.name}. Use the encounter Condition control to apply it.`, "info", 5000);
    return;
  }
  showToast(`No direct resolver mapping for ${entry.category} yet.`, "info");
}

async function useEncounterCompendiumEntry(entry) {
  if (!_activeEncounter?.id) {
    showToast("No active encounter for direct compendium execution.", "info");
    return;
  }
  const currentParticipant = _activeEncounter.current_participant;
  const actorId = currentParticipant?.id || null;
  const payload = {
    slug: entry.slug,
    actor_participant_id: actorId,
    target_participant_ids: [],
  };
  payload.target_participant_ids = promptCompendiumTargets(entry, actorId);
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/use-compendium`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    if (data.actor?.owner_type === "player" || (data.targets || []).some(target => target.owner_type === "player")) {
      await loadWorld();
      return;
    }
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || `${entry.name} used.`, "success");
  } catch (e) {
    showError(`Could not use compendium entry: ${e.message}`);
  }
}

function promptCompendiumTargets(entry, actorId) {
  const participants = _activeEncounter?.participants || [];
  const actor = participants.find(participant => participant.id === actorId) || null;
  if (entry.slug === "bless") {
    return participants
      .filter(participant => participant.team === actor?.team || participant.owner_type === "player")
      .slice(0, 3)
      .map(participant => participant.id);
  }
  if (["second-wind", "dash", "dodge", "disengage"].includes(entry.slug)) {
    return [];
  }
  const wantsFriendlyTarget = ["help", "healing-word", "cure-wounds", "healing-wand"].includes(entry.slug);
  const wantsHostileTarget = ["magic-missile"].includes(entry.slug);
  const eligible = participants.filter(participant => {
    if (!actor) return true;
    if (wantsFriendlyTarget) return participant.team === actor.team;
    if (wantsHostileTarget) return participant.team !== actor.team;
    return true;
  });
  if (!eligible.length) return [];
  if (entry.slug === "magic-missile") {
    return eligible.slice(0, 3).map(participant => participant.id);
  }
  const defaultTarget = eligible[0];
  const promptText = eligible.map(participant => `${participant.id}: ${participant.name}`).join("\n");
  const selected = window.prompt(`Target ${entry.name} at which participant id?\n${promptText}`, defaultTarget.id);
  if (selected === null) return [];
  const target = eligible.find(participant => participant.id === selected.trim());
  return target ? [target.id] : [];
}

function previewCompendiumEntry(slug) {
  const entry = (_compendiumEntries || []).find(item => item.slug === slug);
  if (!entry) return;
  const lines = [
    entry.name,
    `${entry.category}${entry.action_cost ? ` · ${entry.action_cost.replaceAll("_", " ")}` : ""}${entry.range_feet !== null && entry.range_feet !== undefined ? ` · ${entry.range_feet} ft` : ""}`,
    entry.description || "",
    entry.rules_text || "",
    (entry.applies_conditions || []).length ? `Applies: ${(entry.applies_conditions || []).join(", ")}` : "",
    Object.keys(entry.resource_costs || {}).length ? `Costs: ${formatResourceCosts(entry.resource_costs || {})}` : "",
  ].filter(Boolean);
  showToast(lines.join(" | "), "info", 8000);
}

function isSpellPrepared(slug) {
  const normalized = String(slug || "").trim().toLowerCase();
  return (_sheet?.prepared_spells || []).includes(normalized);
}

function isItemEquipped(slug) {
  const normalized = String(slug || "").trim().toLowerCase();
  return Object.values(_sheet?.equipped_items || {}).includes(normalized);
}

async function togglePreparedSpell(slug, prepared) {
  if (!_sheet?.name) {
    showToast("Create a character sheet first.", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/player/player/prepared-spells`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, prepared }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.sheet) _sheet = data.sheet;
    renderSidebar();
    renderCompendiumSidebar();
    showToast(data.summary || "Prepared spells updated.", "success");
  } catch (e) {
    showError(`Could not update prepared spells: ${e.message}`);
  }
}

async function toggleEquipmentEntry(slug, equipped) {
  if (!_sheet?.name) {
    showToast("Create a character sheet first.", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/player/player/equipment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, equipped }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.sheet) _sheet = data.sheet;
    renderSidebar();
    renderCompendiumSidebar();
    showToast(data.summary || "Equipment updated.", "success");
  } catch (e) {
    showError(`Could not update equipment: ${e.message}`);
  }
}

function renderGMProcedureSidebar() {
  const section = document.getElementById("gm-procedure-section");
  const button = document.getElementById("gm-procedure-preview-btn");
  const container = document.getElementById("sidebar-gm-procedure");
  if (!section || !button || !container) return;

  const isRulesMode = isD20RulesMode() && !!_scene;
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const currentInput = document.getElementById("user-input")?.value?.trim() || "";
  button.disabled = !currentInput;

  if (!_gmProcedurePreview) {
    container.innerHTML = `
      <div class="gm-empty">
        Start typing in the scene input box, then preview the likely rules procedure for that intent.
      </div>
    `;
    return;
  }

  const plan = _gmProcedurePreview.plan || {};
  const decision = _gmProcedurePreview.suggested_decision || {};
  const actions = Array.isArray(_gmProcedurePreview.suggested_actions) ? _gmProcedurePreview.suggested_actions : [];
  const recent = Array.isArray(_gmProcedurePreview.recent_gm_decisions) && _gmProcedurePreview.recent_gm_decisions.length
    ? _gmProcedurePreview.recent_gm_decisions
    : _recentGMDecisions;
  const planHeadline = (plan.resolution_kind || "none").replaceAll("_", " ");
  const consultBadge = decision.consult_rules
    ? '<span class="badge yellow">Rules Triggered</span>'
    : '<span class="badge">Narration</span>';
  const rollBadge = decision.ask_for_roll
    ? '<span class="badge green">Roll Likely</span>'
    : "";
  const actionMarkup = actions.map((action, index) => `
    <button class="gm-action-chip" onclick="applySuggestedAction(${index})" title="${escHtml(action.summary || "")}">
      ${escHtml((action.action_type || "action").replaceAll("_", " "))}
    </button>
  `).join("");
  const recentMarkup = recent.length
    ? recent.map(entry => {
        const payload = entry.payload || {};
        const gmDecision = payload.gm_decision || {};
        const label = (gmDecision.resolution_kind || entry.source || "decision").replaceAll("_", " ");
        const mode = gmDecision.player_facing_mode || "narration";
        return `
          <div class="gm-decision-item">
            <div class="gm-decision-head">
              <div class="sidebar-item-name">${escHtml(label)}</div>
              <div class="gm-decision-time">${escHtml(formatRelativeAuditTime(entry.created_at || ""))}</div>
            </div>
            <div class="sidebar-item-sub muted">${escHtml(mode.replaceAll("_", " "))}</div>
          </div>
        `;
      }).join("")
    : '<div class="gm-empty">No scene decisions have been captured yet.</div>';

  container.innerHTML = `
    <div class="gm-procedure-card">
      <div class="gm-procedure-kicker">Current Intent</div>
      <div class="gm-procedure-headline">${escHtml(planHeadline === "none" ? "No deterministic procedure strongly indicated yet." : `Likely ${planHeadline} flow`)}</div>
      <div class="gm-procedure-meta">
        ${consultBadge}
        ${rollBadge}
      </div>
      <div class="gm-procedure-note">
        ${escHtml(actions[0]?.summary || "Continue with narration or gather clarification before resolving mechanics.")}
      </div>
      ${actionMarkup ? `<div class="gm-procedure-actions">${actionMarkup}</div>` : ""}
    </div>
    <div style="margin-top:12px">
      <div class="sidebar-item-name" style="margin-bottom:6px">Recent GM Decisions</div>
      ${recentMarkup}
    </div>
  `;
}

function renderActionLogSidebar() {
  const section = document.getElementById("action-log-section");
  const container = document.getElementById("sidebar-action-log");
  if (!container || !section) return;

  const isRulesMode = _campaign?.play_mode === "rules";
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const logs = (_actionLogs || []).slice(0, 8);
  if (!logs.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.8rem">No logged actions yet.</div>';
    return;
  }

  container.innerHTML = logs.map(log => {
    const details = log.details || {};
    const attack = details.attack || null;
    const damage = details.damage || null;
    const healing = details.healing || null;
    const resolution = details.resolution || null;
    let headline = log.summary;
    let meta = "";
    if (attack) {
      headline = `${log.source || "attack"} ${attack.total} vs AC ${attack.target_armor_class}`;
      meta = `${String(attack.outcome || "").replaceAll("_", " ")}${damage ? ` · ${damage.total} ${damage.damage_type || "damage"}` : ""}`;
    } else if (healing) {
      headline = `${log.source || "healing"} restored ${healing.total}`;
      meta = healing.roll_expression || "";
    } else if (log.action_type === "campaign_procedure") {
      headline = `${String(log.source || "procedure").replaceAll("_", " ")}`;
      const worldTime = details.world_time?.label || "";
      const subject = details.subject || "";
      const destination = details.destination || "";
      const rewards = Object.entries(details.reward_currencies || {})
        .filter(([, amount]) => Number(amount) > 0)
        .map(([denomination, amount]) => `${amount} ${denomination}`)
        .join(", ");
      const maturedEvents = (details.matured_events || []).map(event => event.title).join(", ");
      const maturedConsequences = (details.matured_event_consequences || []).map(entry => entry.consequence?.kind || "").filter(Boolean).join(", ");
      const generatedEvents = (details.generated_events || []).map(event => event.title).join(", ");
      meta = [
        worldTime,
        subject,
        destination,
        rewards ? `reward: ${rewards}` : "",
        maturedEvents ? `escalated: ${maturedEvents}` : "",
        maturedConsequences ? `fallout: ${maturedConsequences.replaceAll("_", " ")}` : "",
        generatedEvents ? `events: ${generatedEvents}` : "",
      ].filter(Boolean).join(" · ");
    } else if (log.action_type === "rest") {
      headline = `${String(log.source || "rest").replaceAll("_", " ")}`;
      const restoredResources = (details.restored_resources || []).map(entry => entry.resource).join(", ");
      const restoredItems = (details.restored_item_charges || []).map(entry => entry.resource).join(", ");
      meta = [restoredResources ? `resources: ${restoredResources}` : "", restoredItems ? `items: ${restoredItems}` : ""]
        .filter(Boolean)
        .join(" · ");
    } else if (log.action_type === "quest_progress") {
      headline = `${details.quest?.title || log.source || "quest progress"}`;
      const stageId = details.completed_stage_id || "";
      const stage = (details.quest?.stages || []).find(entry => entry.id === stageId);
      const worldTime = details.world_time?.label || "";
      meta = [stage ? `stage: ${stage.description}` : "", worldTime].filter(Boolean).join(" · ");
    } else if (log.action_type === "treasure") {
      headline = `${String(log.source || "treasure").replaceAll("_", " ")} reward`;
      const currencies = details.treasure?.currencies || {};
      meta = Object.entries(currencies)
        .filter(([, amount]) => Number(amount) > 0)
        .map(([denomination, amount]) => `${amount} ${denomination}`)
        .join(" · ");
    } else if (resolution && resolution.actor && resolution.opponent) {
      headline = `${resolution.actor.name} ${resolution.actor.total} vs ${resolution.opponent.name} ${resolution.opponent.total}`;
      meta = `${String(resolution.winner || "tie").replaceAll("_", " ")}${resolution.margin ? ` · margin ${resolution.margin}` : ""}`;
    } else if (resolution && resolution.total !== undefined) {
      headline = `${resolution.source || log.source || "check"} ${resolution.total} vs DC ${resolution.difficulty}`;
      meta = `${String(resolution.outcome || "").replaceAll("_", " ")}${resolution.advantage_state && resolution.advantage_state !== "normal" ? ` · ${resolution.advantage_state}` : ""}`;
    }
    return `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(log.actor_name || "Player")}</div>
        <div class="sidebar-item-sub">${escHtml(headline)}</div>
        ${meta ? `<div class="sidebar-item-sub muted">${escHtml(meta)}</div>` : ""}
      </div>
    `;
  }).join("");
}

async function takeCharacterRest(restType) {
  if (!_sheet?.name) {
    showToast("Create a character sheet first.", "warning");
    return;
  }
  if (_activeEncounter) {
    showToast("Complete the active encounter before taking a rest.", "info");
    return;
  }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/player/player/rest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rest_type: restType }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.sheet) _sheet = data.sheet;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Rest completed.", "success", 5000);
  } catch (e) {
    showError(`Could not take rest: ${e.message}`);
  }
}

async function openAdvanceTimePrompt() {
  const hoursRaw = window.prompt("Advance how many in-world hours?", "1");
  if (hoursRaw === null) return;
  const hours = parseInt(hoursRaw, 10);
  if (!Number.isFinite(hours) || hours <= 0) {
    showToast("Enter a positive number of hours.", "warning");
    return;
  }
  const procedureType = (window.prompt("Procedure type? travel / downtime / rest / custom", "travel") || "travel").trim().toLowerCase();
  const destination = procedureType === "travel"
    ? (window.prompt("Destination (optional)", _scene?.location || "") || "").trim()
    : "";
  const restType = procedureType === "rest"
    ? ((window.prompt("Rest type? short_rest / long_rest", "long_rest") || "").trim().toLowerCase() || null)
    : null;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/procedures/advance-time`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hours,
        procedure_type: procedureType || "custom",
        destination,
        rest_type: restType,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.campaign) _campaign = data.campaign;
    if (data.player_sheet) _sheet = data.player_sheet;
    if (Array.isArray(data.events) && data.events.length) {
      _events = [...data.events, ...(_events || [])];
    }
    if (destination && _scene && procedureType === "travel") _scene.location = destination;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Time advanced.", "success", 5000);
  } catch (e) {
    showError(`Could not advance time: ${e.message}`);
  }
}

async function openDowntimePrompt() {
  const activityType = (window.prompt("Downtime activity? work / training / research / carouse / craft", "work") || "work").trim().toLowerCase();
  if (!activityType) return;
  const daysRaw = window.prompt("How many downtime days?", "1");
  if (daysRaw === null) return;
  const days = parseInt(daysRaw, 10);
  if (!Number.isFinite(days) || days <= 0) {
    showToast("Enter a positive number of downtime days.", "warning");
    return;
  }
  const subjectPrompt = activityType === "craft"
    ? "What compendium slug are you crafting? (example: shield, healing-wand)"
    : "Subject or focus (optional)";
  const subject = (window.prompt(subjectPrompt, "") || "").trim();
  const reason = (window.prompt("Why is this downtime happening? (optional)", "") || "").trim();
  const factionId = activityType === "carouse"
    ? (window.prompt("Target faction id (optional)", "") || "").trim()
    : "";
  const questId = ["research", "training"].includes(activityType)
    ? (window.prompt("Target quest id (optional)", "") || "").trim()
    : "";
  const objectiveId = activityType === "training"
    ? (window.prompt("Target objective id (optional)", "") || "").trim()
    : "";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/procedures/downtime`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        activity_type: activityType,
        days,
        subject,
        reason,
        faction_id: factionId || null,
        quest_id: questId || null,
        objective_id: objectiveId || null,
        apply_rewards_to_player: true,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.campaign) _campaign = data.campaign;
    if (data.player_sheet) _sheet = data.player_sheet;
    if (Array.isArray(data.events) && data.events.length) {
      _events = [...data.events, ...(_events || [])];
    }
    if (Array.isArray(data.quest_updates) && data.quest_updates.length) {
      data.quest_updates.forEach(updated => {
        const index = (_quests || []).findIndex(quest => quest.id === updated.id);
        if (index >= 0) _quests[index] = updated;
      });
      _quests = [..._quests];
    }
    if (Array.isArray(data.objective_updates) && data.objective_updates.length) {
      data.objective_updates.forEach(updated => {
        const index = (_objectives || []).findIndex(objective => objective.id === updated.id);
        if (index >= 0) _objectives[index] = updated;
      });
      _objectives = [..._objectives];
    }
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Downtime completed.", "success", 5000);
  } catch (e) {
    showError(`Could not run downtime: ${e.message}`);
  }
}

async function addCampaignObjective() {
  const title = (window.prompt("Objective title", "") || "").trim();
  if (!title) return;
  const description = (window.prompt("Objective description (optional)", "") || "").trim();
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/objectives`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description, status: "active" }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _objectives = [...(_objectives || []), data];
    renderSidebar();
    showToast(`Objective added: ${title}`, "success", 4000);
  } catch (e) {
    showError(`Could not add objective: ${e.message}`);
  }
}

async function addCampaignQuest() {
  const title = (window.prompt("Quest title", "") || "").trim();
  if (!title) return;
  const description = (window.prompt("Quest description (optional)", "") || "").trim();
  const stageText = (window.prompt("Stages (separate with |)", "") || "").trim();
  const stages = stageText
    ? stageText.split("|").map((text, index) => ({ description: text.trim(), completed: false, order: index })).filter(stage => stage.description)
    : [];
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/quests`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description, stages, status: "active" }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _quests = [...(_quests || []), data];
    renderSidebar();
    showToast(`Quest added: ${title}`, "success", 4000);
  } catch (e) {
    showError(`Could not add quest: ${e.message}`);
  }
}

function findCampaignEvent(eventId) {
  return (_events || []).find(event => event.id === eventId) || null;
}

function buildEventDetailsFromPrompts(existing = {}) {
  const hookType = (window.prompt("Event hook type? encounter / discovery / resource_pressure / social / time_pressure / blank", existing.hook_type || "") || "").trim().toLowerCase();
  if (hookType === null) return null;
  const escalationRaw = window.prompt("Escalation hours?", String(existing.escalation_hours ?? 12));
  if (escalationRaw === null) return null;
  const escalationHours = parseInt(escalationRaw, 10);
  const details = { ...existing };
  if (hookType) details.hook_type = hookType;
  else delete details.hook_type;
  if (Number.isFinite(escalationHours) && escalationHours > 0) details.escalation_hours = escalationHours;
  else delete details.escalation_hours;

  const enemyCountRaw = window.prompt("Enemy count for encounter hooks? Leave blank to keep/remove.", existing.enemy_count ?? "");
  if (enemyCountRaw === null) return null;
  const enemyCount = parseInt(enemyCountRaw, 10);
  if (enemyCountRaw.trim() && Number.isFinite(enemyCount) && enemyCount > 0) details.enemy_count = enemyCount;
  else delete details.enemy_count;

  const supplyCostRaw = window.prompt("Supply cost in sp for resource pressure? Leave blank to keep/remove.", existing.supply_cost_sp ?? "");
  if (supplyCostRaw === null) return null;
  const supplyCost = parseInt(supplyCostRaw, 10);
  if (supplyCostRaw.trim() && Number.isFinite(supplyCost) && supplyCost >= 0) details.supply_cost_sp = supplyCost;
  else delete details.supply_cost_sp;

  const factionId = window.prompt("Target faction id (optional)", existing.faction_id || "");
  if (factionId === null) return null;
  if (factionId.trim()) details.faction_id = factionId.trim();
  else delete details.faction_id;

  const questId = window.prompt("Target quest id (optional)", existing.quest_id || "");
  if (questId === null) return null;
  if (questId.trim()) details.quest_id = questId.trim();
  else delete details.quest_id;

  return details;
}

function upsertCampaignEvent(eventPayload) {
  if (!eventPayload?.id) return;
  const current = _events || [];
  const existingIndex = current.findIndex(event => event.id === eventPayload.id);
  if (existingIndex >= 0) {
    current[existingIndex] = eventPayload;
    _events = [...current];
  } else {
    _events = [eventPayload, ...current];
  }
}

async function persistCampaignEvent(payload, { refreshLogs = false, successMessage = "Event saved." } = {}) {
  const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/events`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  if (data.player_sheet) _sheet = data.player_sheet;
  upsertCampaignEvent(data);
  if (refreshLogs || data.treasure) {
    await refreshActionLogs();
  } else {
    await refreshCampaignRecap();
  }
  renderSidebar();
  showToast(successMessage, "success", 4000);
  return data;
}

async function addCampaignEvent() {
  const title = (window.prompt("Event title", "") || "").trim();
  if (!title) return;
  const content = (window.prompt("Event summary", "") || "").trim();
  const details = buildEventDetailsFromPrompts({});
  if (details === null) return;
  try {
    await persistCampaignEvent({
      title,
      content,
      event_type: "world",
      status: "pending",
      details,
    }, { successMessage: `Event added: ${title}` });
  } catch (e) {
    showError(`Could not add event: ${e.message}`);
  }
}

async function editCampaignEvent(eventId) {
  const event = findCampaignEvent(eventId);
  if (!event) {
    showToast("Event not found.", "warning");
    return;
  }
  const title = window.prompt("Event title", event.title || "");
  if (title === null || !title.trim()) return;
  const content = window.prompt("Event summary", event.content || "");
  if (content === null) return;
  const details = buildEventDetailsFromPrompts(event.details || {});
  if (details === null) return;
  try {
    await persistCampaignEvent({
      id: event.id,
      title: title.trim(),
      content: content.trim(),
      event_type: event.event_type || "world",
      status: event.status || "pending",
      world_time_hours: event.world_time_hours,
      details,
    }, { successMessage: `Event updated: ${title.trim()}` });
  } catch (e) {
    showError(`Could not update event: ${e.message}`);
  }
}

async function toggleCampaignEventStatus(eventId) {
  const event = findCampaignEvent(eventId);
  if (!event) {
    showToast("Event not found.", "warning");
    return;
  }
  const nextStatus = event.status === "pending" ? "resolved" : "pending";
  let generateTreasure = false;
  let treasureChallengeRating = null;
  if (nextStatus === "resolved") {
    const rewardAnswer = (window.prompt("Generate treasure while resolving this event? yes / no", "no") || "no").trim().toLowerCase();
    generateTreasure = rewardAnswer === "yes" || rewardAnswer === "y";
    if (generateTreasure) {
      const crRaw = window.prompt("Treasure challenge rating / reward tier?", "1");
      if (crRaw === null) return;
      const parsed = parseInt(crRaw, 10);
      treasureChallengeRating = Number.isFinite(parsed) && parsed >= 0 ? parsed : 1;
    }
  }
  try {
    await persistCampaignEvent({
      id: event.id,
      title: event.title,
      content: event.content || "",
      event_type: event.event_type || "world",
      status: nextStatus,
      world_time_hours: event.world_time_hours,
      details: event.details || {},
      generate_treasure: generateTreasure,
      treasure_challenge_rating: treasureChallengeRating,
      apply_treasure_to_player: true,
    }, {
      refreshLogs: nextStatus === "resolved",
      successMessage: `Event ${nextStatus === "resolved" ? "resolved" : "reopened"}: ${event.title}`,
    });
  } catch (e) {
    showError(`Could not update event status: ${e.message}`);
  }
}

async function advanceCampaignQuest() {
  const activeQuests = (_quests || []).filter(quest => quest.status === "active");
  if (!activeQuests.length) {
    showToast("No active quests to advance.", "info");
    return;
  }
  const questList = activeQuests.map((quest, index) => `${index + 1}. ${quest.title}`).join("\n");
  const questRaw = window.prompt(`Advance which quest?\n${questList}`, "1");
  if (questRaw === null) return;
  const questIndex = parseInt(questRaw, 10) - 1;
  const quest = activeQuests[questIndex];
  if (!quest) {
    showToast("Choose a valid quest number.", "warning");
    return;
  }
  const openStages = (quest.stages || []).filter(stage => !stage.completed);
  const stageList = openStages.map((stage, index) => `${index + 1}. ${stage.description}`).join("\n");
  const stageRaw = openStages.length ? window.prompt(`Complete which stage for "${quest.title}"?\n${stageList}`, "1") : null;
  if (openStages.length && stageRaw === null) return;
  const stageIndex = openStages.length ? parseInt(stageRaw, 10) - 1 : -1;
  const stage = openStages.length ? openStages[stageIndex] : null;
  if (openStages.length && !stage) {
    showToast("Choose a valid stage number.", "warning");
    return;
  }
  const note = (window.prompt("Progress note (optional)", "") || "").trim();
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/procedures/advance-quest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        quest_id: quest.id,
        stage_id: stage?.id || null,
        note,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.campaign) _campaign = data.campaign;
    if (data.quest) {
      _quests = (_quests || []).map(existing => existing.id === data.quest.id ? data.quest : existing);
    }
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || `Quest advanced: ${quest.title}`, "success", 5000);
  } catch (e) {
    showError(`Could not advance quest: ${e.message}`);
  }
}

async function generateEncounterFromEvent(eventId) {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/events/${eventId}/generate-encounter`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.event) {
      _events = (_events || []).map(event => event.id === data.event.id ? data.event : event);
    }
    if (data.encounter) {
      _activeEncounter = data.encounter;
    }
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Encounter generated.", "success", 5000);
  } catch (e) {
    showError(`Could not generate encounter: ${e.message}`);
  }
}

async function generateTreasureReward() {
  if (!_sheet?.name) {
    showToast("Create a character sheet first.", "warning");
    return;
  }
  const crRaw = window.prompt("Treasure challenge rating / reward tier?", "1");
  if (crRaw === null) return;
  const challengeRating = parseInt(crRaw, 10);
  if (!Number.isFinite(challengeRating) || challengeRating < 0) {
    showToast("Enter a non-negative challenge rating.", "warning");
    return;
  }
  const sourceType = (window.prompt("Treasure source? loot / quest / event / encounter", "loot") || "loot").trim().toLowerCase();
  const sourceName = (window.prompt("Source name (optional)", _activeEncounter?.name || "") || "").trim();
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/procedures/generate-treasure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        challenge_rating: challengeRating,
        source_type: sourceType || "loot",
        source_name: sourceName,
        apply_to_player: true,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.player_sheet) _sheet = data.player_sheet;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Treasure generated.", "success", 5000);
  } catch (e) {
    showError(`Could not generate treasure: ${e.message}`);
  }
}

async function refreshCampaignRecap() {
  try {
    const filterValue = document.getElementById("recap-filter")?.value || "all";
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/recap?limit=12&kind=${encodeURIComponent(filterValue)}`);
    const data = await res.json().catch(() => ({ items: [], summary: "" }));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _campaignRecap = {
      items: Array.isArray(data.items) ? data.items : [],
      summary: data.summary || "",
    };
  } catch {
    _campaignRecap = { items: [], summary: "" };
  }
}

function renderEncounterSidebar() {
  const section = document.getElementById("encounter-section");
  const container = document.getElementById("sidebar-encounter");
  const startBtn = document.getElementById("encounter-start-btn");
  const moveBtn = document.getElementById("encounter-move-btn");
  const reactBtn = document.getElementById("encounter-react-btn");
  const conditionBtn = document.getElementById("encounter-condition-btn");
  const concentrationBtn = document.getElementById("encounter-concentration-btn");
  const stabilizeBtn = document.getElementById("encounter-stabilize-btn");
  const advanceBtn = document.getElementById("encounter-advance-btn");
  const completeBtn = document.getElementById("encounter-complete-btn");
  if (!section || !container || !startBtn || !moveBtn || !reactBtn || !conditionBtn || !concentrationBtn || !stabilizeBtn || !advanceBtn || !completeBtn) return;

  const isRulesMode = isD20RulesMode() && !!_scene;
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const encounter = _activeEncounter;
  startBtn.disabled = !!encounter;
  advanceBtn.disabled = !encounter;
  completeBtn.disabled = !encounter;
  moveBtn.disabled = !encounter;
  reactBtn.disabled = !encounter;
  conditionBtn.disabled = !encounter;
  concentrationBtn.disabled = !encounter;
  stabilizeBtn.disabled = !encounter;

  if (!encounter) {
    container.innerHTML = '<div class="gm-empty">No active encounter. Start one to track initiative and turn order for this scene.</div>';
    return;
  }

  const playerParticipant = (encounter.participants || []).find(participant => participant.owner_type === "player");
  const currentParticipant = encounter.current_participant;
  moveBtn.disabled = !currentParticipant || currentParticipant.owner_type !== "player";
  reactBtn.disabled = !playerParticipant || !playerParticipant.reaction_available;
  stabilizeBtn.disabled = !(encounter.participants || []).some(participant => participant.life_state === "down");

  const participants = encounter.participants || [];
  const participantMarkup = participants.map((participant, index) => `
    <div class="sidebar-item">
      <div class="sidebar-item-name">${index === encounter.current_turn_index ? "▶ " : ""}${escHtml(participant.name)}</div>
      <div class="sidebar-item-sub muted">
        Init ${participant.initiative_total}${participant.current_hp !== null && participant.current_hp !== undefined ? ` · HP ${participant.current_hp}/${participant.max_hp}` : ""}${participant.life_state && participant.life_state !== "active" ? ` · ${escHtml(participant.life_state)}` : ""}
      </div>
      ${participant.concentration_label ? `<div class="sidebar-item-sub muted">Concentration: ${escHtml(participant.concentration_label)}${participant.pending_concentration_dc ? ` · DC ${participant.pending_concentration_dc}` : ""}</div>` : ""}
      ${(participant.conditions || []).length ? `<div class="sidebar-item-sub muted">Conditions: ${escHtml((participant.conditions || []).map(condition => {
        const duration = participant.condition_durations?.[condition];
        return duration ? `${condition} (${duration})` : condition;
      }).join(", "))}</div>` : ""}
    </div>
  `).join("");

  container.innerHTML = `
    <div class="sidebar-item">
      <div class="sidebar-item-name">${escHtml(encounter.name)}</div>
      <div class="sidebar-item-sub muted">Round ${encounter.round_number} · ${escHtml(encounter.status)}</div>
    </div>
    ${encounter.current_participant ? `
      <div class="sidebar-item">
        <div class="sidebar-item-sub">Current turn: ${escHtml(encounter.current_participant.name)}</div>
        <div class="sidebar-item-sub muted">Action ${encounter.current_participant.action_available ? "available" : "spent"} · Bonus ${encounter.current_participant.bonus_action_available ? "available" : "spent"} · Move ${encounter.current_participant.movement_remaining ?? 0}</div>
      </div>
    ` : ""}
    ${playerParticipant ? `
      <div class="sidebar-item">
        <div class="sidebar-item-sub">Player reaction: ${playerParticipant.reaction_available ? "available" : "spent"}</div>
        <div class="sidebar-item-sub muted">${escHtml(playerParticipant.name)}${currentParticipant && currentParticipant.id !== playerParticipant.id ? " can still react off-turn." : " is the current actor."}</div>
      </div>
    ` : ""}
    ${participantMarkup || '<div class="gm-empty">No participants.</div>'}
  `;
}

function populateEncounterTargetOptions(selectId, emptyLabel, filterFn = null) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const currentValue = select.value;
  const participants = (_activeEncounter?.participants || []).filter(participant => participant.is_active !== false);
  const filtered = filterFn ? participants.filter(filterFn) : participants;
  select.innerHTML = `<option value="">${escHtml(emptyLabel)}</option>` + filtered.map(participant => (
    `<option value="${escHtml(participant.id)}">${escHtml(participant.name)}${participant.team ? ` (${escHtml(participant.team)})` : ""}</option>`
  )).join("");
  if ([...select.options].some(option => option.value === currentValue)) {
    select.value = currentValue;
  }
}

function updateAttackTargetPreview() {
  const select = document.getElementById("attack-target-participant");
  const preview = document.getElementById("attack-target-preview");
  const acInput = document.getElementById("attack-target-ac");
  if (!select || !preview || !acInput) return;
  const participant = (_activeEncounter?.participants || []).find(entry => entry.id === select.value);
  if (!participant) {
    preview.textContent = "Manual target AC entry.";
    return;
  }
  if (participant.armor_class !== null && participant.armor_class !== undefined) {
    acInput.value = String(participant.armor_class);
  }
  preview.textContent = `Targeting ${participant.name}${participant.current_hp !== null && participant.current_hp !== undefined ? ` · HP ${participant.current_hp}/${participant.max_hp}` : ""}`;
}

function updateHealingTargetPreview() {
  const select = document.getElementById("healing-target-participant");
  const preview = document.getElementById("healing-target-preview");
  const applyCheckbox = document.getElementById("healing-apply-to-sheet");
  if (!select || !preview || !applyCheckbox) return;
  const participant = (_activeEncounter?.participants || []).find(entry => entry.id === select.value);
  if (!participant) {
    applyCheckbox.disabled = false;
    preview.textContent = `Current sheet: HP ${_sheet.current_hp}/${_sheet.max_hp}${_sheet.temp_hp ? ` (+${_sheet.temp_hp} temp)` : ""}.`;
    return;
  }
  applyCheckbox.checked = false;
  applyCheckbox.disabled = true;
  preview.textContent = `Targeting ${participant.name}${participant.current_hp !== null && participant.current_hp !== undefined ? ` · HP ${participant.current_hp}/${participant.max_hp}` : ""}`;
}

async function startSceneEncounter() {
  if (!isD20RulesMode() || !_scene) {
    showToast("An encounter can only be started in an active rules-mode scene.", "info");
    return;
  }
  if (_activeEncounter) {
    showToast("There is already an active encounter in this scene.", "info");
    return;
  }

  const participants = [
    { owner_type: "player", owner_id: "player", team: "player", name: _sheet?.name || _pc?.name || "Player" },
    ...((_scene.npc_ids || []).map(id => {
      const npc = (_npcs || []).find(entry => entry.id === id);
      return {
        owner_type: "npc",
        owner_id: id,
        team: "enemy",
        name: npc?.name || "NPC",
      };
    })),
  ];

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: _scene?.title ? `${_scene.title} Encounter` : "Scene Encounter",
        scene_id: _scene.id,
        participants,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _activeEncounter = data;
    await refreshActionLogs();
    renderSidebar();
    showToast(`Encounter started. ${data.current_participant?.name || "First participant"} is up.`, "success");
  } catch (e) {
    showError(`Could not start encounter: ${e.message}`);
  }
}

async function advanceEncounterTurn() {
  if (!_activeEncounter) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: "" }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _activeEncounter = data;
    await refreshActionLogs();
    renderSidebar();
    showToast(`Round ${data.round_number}: ${data.current_participant?.name || "Next participant"} is up.`, "info");
  } catch (e) {
    showError(`Could not advance encounter: ${e.message}`);
  }
}

async function spendEncounterMovement() {
  if (!_activeEncounter?.id || !_activeEncounter?.current_participant) {
    showToast("No active encounter turn to move in.", "info");
    return;
  }
  const current = _activeEncounter.current_participant;
  const promptLabel = `${current.name} has ${current.movement_remaining ?? 0} feet remaining. How many feet should be spent?`;
  const raw = window.prompt(promptLabel, "5");
  if (raw === null) return;
  const distance = parseInt(raw, 10);
  if (!Number.isFinite(distance) || distance < 0) {
    showError("Enter a non-negative number of feet.");
    return;
  }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/movement`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ distance }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Movement spent.", "info");
  } catch (e) {
    showError(`Could not spend movement: ${e.message}`);
  }
}

async function useEncounterReaction() {
  if (!_activeEncounter?.id) {
    showToast("No active encounter to react in.", "info");
    return;
  }
  const playerParticipant = (_activeEncounter.participants || []).find(participant => participant.owner_type === "player");
  if (!playerParticipant) {
    showError("No player participant is tracked in the active encounter.");
    return;
  }
  if (!playerParticipant.reaction_available) {
    showToast("Your reaction is already spent.", "info");
    return;
  }
  const note = window.prompt(`Use ${playerParticipant.name}'s reaction for what?`, "Opportunity attack / defensive maneuver");
  if (note === null) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/reaction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_id: playerParticipant.id, note }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Reaction used.", "info");
  } catch (e) {
    showError(`Could not use reaction: ${e.message}`);
  }
}

async function applyEncounterCondition() {
  if (!_activeEncounter?.id) {
    showToast("No active encounter to modify.", "info");
    return;
  }
  const participants = _activeEncounter.participants || [];
  if (!participants.length) {
    showToast("No encounter participants available.", "info");
    return;
  }
  const targetName = window.prompt(`Apply a condition to whom?\n${participants.map(participant => participant.name).join(", ")}`, participants[0].name || "");
  if (targetName === null) return;
  const participant = participants.find(entry => String(entry.name).toLowerCase() === String(targetName).trim().toLowerCase()) || participants[0];
  const condition = window.prompt(`What condition should ${participant.name} gain?`, "poisoned");
  if (condition === null || !condition.trim()) return;
  const durationRaw = window.prompt("How many rounds should it last? Leave blank for indefinite.", "2");
  if (durationRaw === null) return;
  const duration_rounds = durationRaw.trim() ? parseInt(durationRaw, 10) : null;
  if (durationRaw.trim() && (!Number.isFinite(duration_rounds) || duration_rounds <= 0)) {
    showError("Enter a positive number of rounds, or leave it blank.");
    return;
  }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/conditions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        participant_id: participant.id,
        condition,
        duration_rounds,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Condition applied.", "info");
  } catch (e) {
    showError(`Could not apply condition: ${e.message}`);
  }
}

async function stabilizeEncounterParticipant() {
  if (!_activeEncounter?.id) {
    showToast("No active encounter to stabilize in.", "info");
    return;
  }
  const downed = (_activeEncounter.participants || []).filter(participant => participant.life_state === "down");
  if (!downed.length) {
    showToast("No downed participants need stabilization.", "info");
    return;
  }
  const targetName = window.prompt(`Stabilize whom?\n${downed.map(participant => participant.name).join(", ")}`, downed[0].name || "");
  if (targetName === null) return;
  const participant = downed.find(entry => String(entry.name).toLowerCase() === String(targetName).trim().toLowerCase()) || downed[0];
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/stabilize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_id: participant.id }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Participant stabilized.", "success");
  } catch (e) {
    showError(`Could not stabilize participant: ${e.message}`);
  }
}

async function toggleEncounterConcentration() {
  if (!_activeEncounter?.id) {
    showToast("No active encounter to update.", "info");
    return;
  }
  const participants = _activeEncounter.participants || [];
  if (!participants.length) {
    showToast("No encounter participants available.", "info");
    return;
  }
  const targetName = window.prompt(`Set concentration for whom?\n${participants.map(participant => participant.name).join(", ")}`, participants[0].name || "");
  if (targetName === null) return;
  const participant = participants.find(entry => String(entry.name).toLowerCase() === String(targetName).trim().toLowerCase()) || participants[0];
  const currentlyActive = !!participant.concentration_label;
  if (currentlyActive && participant.pending_concentration_dc) {
    const keep = window.confirm(`${participant.name} has a pending concentration DC ${participant.pending_concentration_dc}. Did they maintain concentration?`);
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/concentration-check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ participant_id: participant.id, success: keep }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      if (data.encounter) _activeEncounter = data.encounter;
      await refreshActionLogs();
      renderSidebar();
      showToast(data.summary || "Concentration resolved.", keep ? "success" : "info");
    } catch (e) {
      showError(`Could not resolve concentration: ${e.message}`);
    }
    return;
  }
  if (currentlyActive) {
    const shouldEnd = window.confirm(`${participant.name} is concentrating on "${participant.concentration_label}". End concentration?`);
    if (!shouldEnd) return;
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/concentration`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ participant_id: participant.id, active: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      if (data.encounter) _activeEncounter = data.encounter;
      await refreshActionLogs();
      renderSidebar();
      showToast(data.summary || "Concentration ended.", "info");
    } catch (e) {
      showError(`Could not update concentration: ${e.message}`);
    }
    return;
  }
  const label = window.prompt(`What is ${participant.name} concentrating on?`, "Bless, Hunter's Mark, etc.");
  if (label === null || !label.trim()) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/concentration`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_id: participant.id, active: true, label }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Concentration started.", "success");
  } catch (e) {
    showError(`Could not update concentration: ${e.message}`);
  }
}

async function completeActiveEncounter() {
  if (!_activeEncounter) return;
  const summary = prompt("Encounter summary (optional):", "") || "";
  const treasureAnswer = (window.prompt("Generate treasure from this encounter? yes / no", "no") || "no").trim().toLowerCase();
  const generateTreasure = treasureAnswer === "yes" || treasureAnswer === "y";
  const treasureChallengeRating = generateTreasure
    ? parseInt(window.prompt("Treasure challenge rating / reward tier?", String(Math.max(1, (_activeEncounter.participants || []).filter(p => p.team === "enemy").length))) || "1", 10)
    : null;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/encounters/${_activeEncounter.id}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        summary,
        generate_treasure: generateTreasure,
        treasure_challenge_rating: Number.isFinite(treasureChallengeRating) ? treasureChallengeRating : null,
        apply_treasure_to_player: true,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (data.player_sheet) _sheet = data.player_sheet;
    _activeEncounter = null;
    await refreshActionLogs();
    renderSidebar();
    showToast(data.summary || "Encounter completed.", "success");
  } catch (e) {
    showError(`Could not complete encounter: ${e.message}`);
  }
}

function scheduleGMProcedurePreview() {
  if (!isD20RulesMode() || !_scene) return;
  clearTimeout(_gmPreviewTimer);
  _gmPreviewTimer = setTimeout(() => {
    previewCurrentIntent({ quiet: true });
  }, 350);
}

async function previewCurrentIntent(options = {}) {
  const quiet = options.quiet === true;
  const input = document.getElementById("user-input");
  const message = input?.value?.trim() || "";
  if (!message) {
    _gmProcedurePreview = null;
    renderGMProcedureSidebar();
    return;
  }

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/gm-procedure-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _gmProcedurePreview = data;
    _recentGMDecisions = Array.isArray(data.recent_gm_decisions) ? data.recent_gm_decisions : _recentGMDecisions;
    renderGMProcedureSidebar();
  } catch (e) {
    if (!quiet) showError(`Could not preview GM procedure: ${e.message}`);
  }
}

function applySuggestedAction(index) {
  const actions = _gmProcedurePreview?.suggested_actions || [];
  const action = actions[index];
  if (!action) return;

  if (action.action_type === "check") {
    openResolveCheckModal(action.payload_template || {});
    return;
  }
  if (action.action_type === "attack") {
    openResolveAttackModal(action.payload_template || {});
    return;
  }
  if (action.action_type === "healing") {
    openResolveHealingModal(action.payload_template || {});
    return;
  }
  if (action.action_type === "contested_check") {
    openResolveContestedModal(action.payload_template || {});
    return;
  }
  if (action.action_type === "compendium_action") {
    const slug = action.payload_template?.slug || "";
    if (slug) {
      useCompendiumEntry(slug);
      return;
    }
    showToast(action.summary || "A compendium action likely applies here.", "info");
    return;
  }
  if (action.action_type === "passive_check") {
    const sources = (action.payload_template?.passive_sources || []).join(", ");
    showToast(action.summary || `Consult passive ${sources || "awareness"} before asking for a roll.`, "info", 5000);
    return;
  }

  showToast(action.summary || "Continue with narration.", "info");
}

function formatRelativeAuditTime(value) {
  if (!value) return "";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "";
  return dt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function refreshSceneGMDecisions(options = {}) {
  if (!_scene) return null;
  const autoHandle = options.autoHandle !== false;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/gm-decisions?n=5`);
    const data = await res.json().catch(() => ([]));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _recentGMDecisions = Array.isArray(data) ? data : [];
    if (_gmProcedurePreview) {
      _gmProcedurePreview.recent_gm_decisions = _recentGMDecisions;
    }
    renderGMProcedureSidebar();
    const latest = _recentGMDecisions[0] || null;
    if (autoHandle && latest) {
      await maybeHandleLatestGMDecision(latest);
    }
    return latest;
  } catch (e) {
    return null;
  }
}

async function maybeHandleLatestGMDecision(entry) {
  if (!entry || entry.id === _lastHandledGMDecisionId) return;
  const decision = entry.payload || {};
  _lastHandledGMDecisionId = entry.id;

  if (decision.ask_follow_up && decision.follow_up_question) {
    showToast(decision.follow_up_question, "info", 6000);
    return;
  }
  if (!decision.consult_rules || decision.player_facing_mode !== "rules_handoff") {
    return;
  }
  if (hasOpenModal()) {
    showToast(`Rules handoff ready: ${String(decision.resolution_kind || "action").replaceAll("_", " ")}.`, "info");
    return;
  }

  const prefill = buildActionPrefillFromDecision(decision);
  const kind = decision.resolution_kind;
  if (kind === "check") {
    openResolveCheckModal(prefill);
  } else if (kind === "attack") {
    openResolveAttackModal(prefill);
  } else if (kind === "healing") {
    openResolveHealingModal(prefill);
  } else if (kind === "contested_check") {
    openResolveContestedModal(prefill);
  } else if (kind === "compendium_action") {
    await previewCurrentIntent({ quiet: true });
    const action = (_gmProcedurePreview?.suggested_actions || []).find(item => item.action_type === "compendium_action");
    const slug = action?.payload_template?.slug || "";
    if (slug) {
      useCompendiumEntry(slug);
    } else {
      showToast("A named action or spell likely applies here. Check the Compendium sidebar.", "info", 5000);
    }
  } else if (kind === "passive_check") {
    const sources = (decision.passive_sources || []).join(", ");
    showToast(`Consult passive ${sources || "perception"} before calling for an active roll.`, "info", 5000);
  }
}

function buildActionPrefillFromDecision(decision) {
  const reason = document.getElementById("user-input")?.value?.trim() || "";
  if (decision.resolution_kind === "attack") {
    return {
      source: "",
      target_armor_class: 10,
      roll_expression: "d20",
      advantage_state: "normal",
      damage_roll_expression: "1d6",
      damage_modifier: 0,
      damage_type: "",
      reason,
    };
  }
  if (decision.resolution_kind === "healing") {
    return {
      source: "healing",
      roll_expression: "1d4",
      modifier: 0,
      apply_to_sheet: true,
      reason,
    };
  }
  if (decision.resolution_kind === "contested_check") {
    return {
      actor_source: "",
      opponent_source: "",
      opponent_name: "Opponent",
      roll_expression: "d20",
      actor_advantage_state: "normal",
      opponent_advantage_state: "normal",
      reason,
    };
  }
  return {
    source: "",
    difficulty: 15,
    roll_expression: "d20",
    advantage_state: "normal",
    reason,
  };
}

function hasOpenModal() {
  return [...document.querySelectorAll(".modal-backdrop")].some(el => !el.classList.contains("hidden"));
}

function buildContextModal() {
  const body = document.getElementById("scene-context-body");
  const pc = _pc;
  const sceneNpcIds = new Set(_scene?.npc_ids || []);

  body.innerHTML = `
    ${pc ? `
      <div class="world-section">
        <h4>Player Character</h4>
        <div><strong>${escHtml(pc.name)}</strong></div>
        ${pc.personality ? `<div class="muted">${escHtml(pc.personality)}</div>` : ""}
      </div>` : ""}

    ${_campaign?.play_mode === "rules" && _sheet ? `
      <div class="world-section">
        <h4>Rules Context</h4>
        <div><strong>${escHtml(_campaign.system_pack || "d20-fantasy-core")}</strong></div>
        <div class="muted">${escHtml(_sheet.character_class || "Adventurer")} · Level ${_sheet.level || 1}${_sheet.ancestry ? ` · ${escHtml(_sheet.ancestry)}` : ""}</div>
        <div style="margin-top:6px">HP ${_sheet.current_hp}/${_sheet.max_hp}${_sheet.temp_hp ? ` (+${_sheet.temp_hp} temp)` : ""} · AC ${_sheet.armor_class} · Speed ${_sheet.speed}</div>
      </div>` : ""}

    ${_scene?.intent ? `
      <div class="world-section">
        <h4>Scene Intent</h4>
        <div>${escHtml(_scene.intent)}</div>
      </div>` : ""}

    <div class="world-section">
      <h4>World Facts</h4>
      <ul style="margin:0;padding-left:20px">
        ${_facts.map(f => `<li>${escHtml(f.content)}</li>`).join("")}
      </ul>
    </div>

    ${_threads.length ? `
      <div class="world-section">
        <h4>Active Narrative Threads</h4>
        ${_threads.map(t => `
          <div style="margin-bottom:8px">
            <strong>${escHtml(t.title)}</strong>
            ${t.description ? `<div class="muted">${escHtml(t.description)}</div>` : ""}
          </div>`).join("")}
      </div>` : ""}

    ${_npcs.filter(n => sceneNpcIds.has(n.id)).length ? `
      <div class="world-section">
        <h4>NPCs in Scene</h4>
        ${_npcs.filter(n => sceneNpcIds.has(n.id)).map(n => `
          <div style="margin-bottom:8px">
            <strong>${escHtml(n.name)}</strong>${n.role ? ` — ${escHtml(n.role)}` : ""}
            ${n.personality ? `<div class="muted">${escHtml(n.personality)}</div>` : ""}
          </div>`).join("")}
      </div>` : ""}
  `;
}

// ── Dice roll bubble ──────────────────────────────────────────────────────────

function appendDiceRoll(label, rolls, mod, total) {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = "message-bubble dice-bubble";
  div.style.animation = "fadeIn 0.2s ease";
  const modStr = mod > 0 ? ` + ${mod}` : mod < 0 ? ` − ${Math.abs(mod)}` : "";
  const rollStr = rolls.length > 1 ? rolls.join(" + ") : rolls[0];
  div.innerHTML = `<span class="dice-label">🎲 ${escHtml(label)}</span><span class="dice-rolls">${rollStr}${modStr}</span><span class="dice-total">${total}</span>`;
  area.appendChild(div);
  scrollToBottom();
}

function openResolveCheckModal(prefill = {}) {
  if (_campaign?.play_mode !== "rules") {
    showToast("Check resolution is only available in rules mode.", "info");
    return;
  }
  if (!_sheet || !_sheet.name) {
    showToast("Create a character sheet on the campaign overview first.", "warning");
    return;
  }
  document.getElementById("check-source").value = prefill.source || "";
  document.getElementById("check-difficulty").value = String(prefill.difficulty ?? 15);
  document.getElementById("check-advantage").value = prefill.advantage_state || "normal";
  document.getElementById("check-roll-expression").value = prefill.roll_expression || "d20";
  document.getElementById("check-reason").value = prefill.reason || (document.getElementById("user-input")?.value?.trim() || "");
  document.getElementById("check-action-cost").value = prefill.action_cost || "action";
  document.getElementById("check-narrate-outcome").checked = true;
  document.getElementById("resolve-check-preview").textContent =
    `Using ${_sheet.name}'s sheet from ${_campaign.system_pack || "d20-fantasy-core"}.`;
  openModal("resolve-check-modal");
  setTimeout(() => document.getElementById("check-source").focus(), 50);
}

function openResolveAttackModal(prefill = {}) {
  if (!isD20RulesMode()) {
    showToast("Attack resolution is only available in d20 rules mode.", "info");
    return;
  }
  if (!_sheet || !_sheet.name) {
    showToast("Create a character sheet on the campaign overview first.", "warning");
    return;
  }
  populateEncounterTargetOptions("attack-target-participant", "No encounter target", participant => participant.team !== "player");
  document.getElementById("attack-source").value = prefill.source || "";
  document.getElementById("attack-target-participant").value = prefill.target_participant_id || "";
  document.getElementById("attack-target-ac").value = String(prefill.target_armor_class ?? 10);
  document.getElementById("attack-advantage").value = prefill.advantage_state || "normal";
  document.getElementById("attack-roll-expression").value = prefill.roll_expression || "d20";
  document.getElementById("attack-damage-roll").value = prefill.damage_roll_expression || "1d6";
  document.getElementById("attack-damage-modifier").value = String(prefill.damage_modifier ?? 0);
  document.getElementById("attack-damage-type").value = prefill.damage_type || "";
  document.getElementById("attack-range-feet").value = prefill.range_feet ?? "";
  document.getElementById("attack-target-distance").value = prefill.target_distance_feet ?? "";
  document.getElementById("attack-resource-costs").value = formatResourceCosts(prefill.resource_costs || {});
  document.getElementById("attack-reason").value = prefill.reason || (document.getElementById("user-input")?.value?.trim() || "");
  document.getElementById("attack-action-cost").value = prefill.action_cost || "action";
  document.getElementById("attack-narrate-outcome").checked = true;
  document.getElementById("resolve-attack-preview").textContent = `Rolling against ${_sheet.name}'s current sheet and saving the result to the action log.`;
  updateAttackTargetPreview();
  openModal("resolve-attack-modal");
  setTimeout(() => document.getElementById("attack-source").focus(), 50);
}

function openResolveHealingModal(prefill = {}) {
  if (!isD20RulesMode()) {
    showToast("Healing resolution is only available in d20 rules mode.", "info");
    return;
  }
  if (!_sheet || !_sheet.name) {
    showToast("Create a character sheet on the campaign overview first.", "warning");
    return;
  }
  populateEncounterTargetOptions("healing-target-participant", "Active player sheet");
  document.getElementById("healing-source").value = prefill.source || "healing";
  document.getElementById("healing-target-participant").value = prefill.target_participant_id || "";
  document.getElementById("healing-roll-expression").value = prefill.roll_expression || "1d4";
  document.getElementById("healing-modifier").value = String(prefill.modifier ?? 0);
  document.getElementById("healing-range-feet").value = prefill.range_feet ?? "";
  document.getElementById("healing-target-distance").value = prefill.target_distance_feet ?? "";
  document.getElementById("healing-apply-to-sheet").checked = prefill.apply_to_sheet !== false;
  document.getElementById("healing-resource-costs").value = formatResourceCosts(prefill.resource_costs || {});
  document.getElementById("healing-reason").value = prefill.reason || (document.getElementById("user-input")?.value?.trim() || "");
  document.getElementById("healing-action-cost").value = prefill.action_cost || "action";
  document.getElementById("healing-narrate-outcome").checked = true;
  document.getElementById("resolve-healing-preview").textContent = `Resolve healing and persist the result to the action log.`;
  updateHealingTargetPreview();
  openModal("resolve-healing-modal");
  setTimeout(() => document.getElementById("healing-source").focus(), 50);
}

function populateContestedOpponentOptions() {
  const select = document.getElementById("contested-opponent-owner-id");
  if (!select) return;
  const currentValue = select.value;
  const livingNpcs = (_npcs || []).filter(n => n.is_alive);
  select.innerHTML = '<option value="">Custom opponent / no sheet</option>' + livingNpcs.map(n => (
    `<option value="${escHtml(n.id)}">${escHtml(n.name)}${n.role ? ` (${escHtml(n.role)})` : ""}</option>`
  )).join("");
  if ([...select.options].some(option => option.value === currentValue)) {
    select.value = currentValue;
  }
}

function updateContestedOpponentMode() {
  const select = document.getElementById("contested-opponent-owner-id");
  const selectedId = select?.value || "";
  const nameInput = document.getElementById("contested-opponent-name");
  const modifierInput = document.getElementById("contested-opponent-modifier");
  if (!nameInput || !modifierInput) return;
  if (!selectedId) {
    modifierInput.disabled = false;
    document.getElementById("resolve-contested-preview").textContent = "Using a custom opponent modifier.";
    return;
  }
  const npc = (_npcs || []).find(entry => entry.id === selectedId);
  if (npc) nameInput.value = npc.name || "Opponent";
  modifierInput.disabled = true;
  document.getElementById("resolve-contested-preview").textContent = npc
    ? `Using ${npc.name}'s NPC sheet if one exists.`
    : "Using selected NPC sheet.";
}

function openResolveContestedModal(prefill = {}) {
  if (!isD20RulesMode()) {
    showToast("Contested checks are only available in d20 rules mode.", "info");
    return;
  }
  if (!_sheet || !_sheet.name) {
    showToast("Create a character sheet on the campaign overview first.", "warning");
    return;
  }
  populateContestedOpponentOptions();
  document.getElementById("contested-actor-source").value = prefill.actor_source || "";
  document.getElementById("contested-opponent-source").value = prefill.opponent_source || "";
  document.getElementById("contested-opponent-owner-id").value = prefill.opponent_owner_id || "";
  document.getElementById("contested-opponent-name").value = prefill.opponent_name || "Opponent";
  document.getElementById("contested-opponent-modifier").value = String(prefill.opponent_modifier ?? 0);
  document.getElementById("contested-roll-expression").value = prefill.roll_expression || "d20";
  document.getElementById("contested-actor-advantage").value = prefill.actor_advantage_state || "normal";
  document.getElementById("contested-opponent-advantage").value = prefill.opponent_advantage_state || "normal";
  document.getElementById("contested-resource-costs").value = formatResourceCosts(prefill.resource_costs || {});
  document.getElementById("contested-reason").value = prefill.reason || (document.getElementById("user-input")?.value?.trim() || "");
  document.getElementById("contested-action-cost").value = prefill.action_cost || "action";
  document.getElementById("contested-narrate-outcome").checked = true;
  updateContestedOpponentMode();
  openModal("resolve-contested-check-modal");
  setTimeout(() => document.getElementById("contested-actor-source").focus(), 50);
}

function openSheetStateModal() {
  if (_campaign?.play_mode !== "rules") {
    showToast("Sheet state updates are only available in rules mode.", "info");
    return;
  }
  if (!_sheet || !_sheet.name) {
    showToast("Create a character sheet on the campaign overview first.", "warning");
    return;
  }
  document.getElementById("sheet-state-damage").value = "0";
  document.getElementById("sheet-state-healing").value = "0";
  document.getElementById("sheet-state-temp").value = "0";
  document.getElementById("sheet-state-add-conditions").value = "";
  document.getElementById("sheet-state-remove-conditions").value = "";
  document.getElementById("sheet-state-note").value = "";
  document.getElementById("sheet-state-current").textContent =
    `HP ${_sheet.current_hp}/${_sheet.max_hp}${_sheet.temp_hp ? ` (+${_sheet.temp_hp} temp)` : ""} · Conditions: ${(_sheet.conditions || []).join(", ") || "None"}`;
  openModal("sheet-state-modal");
  setTimeout(() => document.getElementById("sheet-state-damage").focus(), 50);
}

async function submitResolveCheck() {
  const source = document.getElementById("check-source").value.trim();
  const difficulty = parseInt(document.getElementById("check-difficulty").value, 10) || 15;
  const advantage_state = document.getElementById("check-advantage").value || "normal";
  const roll_expression = document.getElementById("check-roll-expression").value.trim() || "d20";
  const reason = document.getElementById("check-reason").value.trim();
  const action_cost = document.getElementById("check-action-cost").value || "action";
  const narrateOutcome = document.getElementById("check-narrate-outcome").checked;
  const submitBtn = document.getElementById("resolve-check-submit");

  if (!source) {
    showError("Check source is required.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Resolving...";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/checks/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, difficulty, advantage_state, roll_expression, action_cost, reason }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    appendDiceRoll(`${source} check`, data.dice_rolls || [], data.modifier || 0, data.total || 0);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    closeModal("resolve-check-modal");
    const resultText = `${source} ${data.total} vs DC ${difficulty} (${String(data.outcome || "").replaceAll("_", " ")})`;
    showToast(resultText, data.success ? "success" : "info");
    if (narrateOutcome) {
      await streamMechanicsFollowup(
        `Resolved check: ${resultText}. Narrate the immediate fictional outcome and consequence of that result.`
      );
    }
  } catch (e) {
    showError(`Could not resolve check: ${e.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Resolve";
  }
}

async function submitResolveAttack() {
  const source = document.getElementById("attack-source").value.trim();
  const target_participant_id = document.getElementById("attack-target-participant").value || null;
  const target_armor_class = parseInt(document.getElementById("attack-target-ac").value, 10) || 10;
  const advantage_state = document.getElementById("attack-advantage").value || "normal";
  const roll_expression = document.getElementById("attack-roll-expression").value.trim() || "d20";
  const damage_roll_expression = document.getElementById("attack-damage-roll").value.trim() || "1d6";
  const damage_modifier = parseInt(document.getElementById("attack-damage-modifier").value, 10) || 0;
  const damage_type = document.getElementById("attack-damage-type").value.trim();
  const range_feet_raw = document.getElementById("attack-range-feet").value.trim();
  const target_distance_raw = document.getElementById("attack-target-distance").value.trim();
  const range_feet = range_feet_raw ? parseInt(range_feet_raw, 10) : null;
  const target_distance_feet = target_distance_raw ? parseInt(target_distance_raw, 10) : null;
  const reason = document.getElementById("attack-reason").value.trim();
  const action_cost = document.getElementById("attack-action-cost").value || "action";
  const resource_costs = parseResourceCosts(document.getElementById("attack-resource-costs").value);
  const narrateOutcome = document.getElementById("attack-narrate-outcome").checked;
  const submitBtn = document.getElementById("resolve-attack-submit");

  if (!source) {
    showError("Attack source is required.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Resolving...";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/attacks/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        target_armor_class,
        target_participant_id,
        advantage_state,
        roll_expression,
        damage_roll_expression,
        damage_modifier,
        damage_type,
        range_feet,
        target_distance_feet,
        action_cost,
        reason,
        resource_costs,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    if (data.attack) {
      appendDiceRoll(`${source} attack`, data.attack.dice_rolls || [], data.attack.modifier || 0, data.attack.total || 0);
    }
    if (data.damage) {
      appendDiceRoll(`${source} damage`, data.damage.dice_rolls || [], data.damage.modifier || 0, data.damage.total || 0);
    }
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    closeModal("resolve-attack-modal");
    const resultText = data.attack?.hit
      ? `${source} hit AC ${target_armor_class}${data.damage ? ` for ${data.damage.total} ${data.damage.damage_type || "damage"}` : ""}.`
      : `${source} missed AC ${target_armor_class}.`;
    showToast(resultText, data.attack?.hit ? "success" : "info");
    if (narrateOutcome) {
      await streamMechanicsFollowup(
        `Resolved attack: ${resultText} Narrate the immediate effect in the scene, including what the target and surroundings do next.`
      );
    }
  } catch (e) {
    showError(`Could not resolve attack: ${e.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Resolve";
  }
}

async function submitResolveHealing() {
  const source = document.getElementById("healing-source").value.trim() || "healing";
  const target_participant_id = document.getElementById("healing-target-participant").value || null;
  const roll_expression = document.getElementById("healing-roll-expression").value.trim() || "1d4";
  const modifier = parseInt(document.getElementById("healing-modifier").value, 10) || 0;
  const range_feet_raw = document.getElementById("healing-range-feet").value.trim();
  const target_distance_raw = document.getElementById("healing-target-distance").value.trim();
  const range_feet = range_feet_raw ? parseInt(range_feet_raw, 10) : null;
  const target_distance_feet = target_distance_raw ? parseInt(target_distance_raw, 10) : null;
  const apply_to_sheet = document.getElementById("healing-apply-to-sheet").checked;
  const reason = document.getElementById("healing-reason").value.trim();
  const action_cost = document.getElementById("healing-action-cost").value || "action";
  const resource_costs = parseResourceCosts(document.getElementById("healing-resource-costs").value);
  const narrateOutcome = document.getElementById("healing-narrate-outcome").checked;
  const submitBtn = document.getElementById("resolve-healing-submit");

  submitBtn.disabled = true;
  submitBtn.textContent = "Resolving...";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/healing/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        roll_expression,
        modifier,
        apply_to_sheet: target_participant_id ? false : apply_to_sheet,
        target_participant_id,
        range_feet,
        target_distance_feet,
        action_cost,
        reason,
        resource_costs,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    if (data.healing) {
      appendDiceRoll(`${source} healing`, data.healing.dice_rolls || [], data.healing.modifier || 0, data.healing.total || 0);
    }
    if (data.sheet) _sheet = data.sheet;
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    closeModal("resolve-healing-modal");
    const resultText = data.summary || `${source} restored ${data.healing?.total || 0} HP.`;
    showToast(resultText, "success");
    if (narrateOutcome) {
      await streamMechanicsFollowup(
        `Resolved healing: ${resultText} Narrate the visible recovery, reactions, and the immediate shift in momentum.`
      );
    }
  } catch (e) {
    showError(`Could not resolve healing: ${e.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Resolve";
  }
}

async function submitResolveContestedCheck() {
  const actor_source = document.getElementById("contested-actor-source").value.trim();
  const opponent_source = document.getElementById("contested-opponent-source").value.trim();
  const opponent_owner_id = document.getElementById("contested-opponent-owner-id").value || "";
  const opponent_name = document.getElementById("contested-opponent-name").value.trim() || "Opponent";
  const opponent_modifier = parseInt(document.getElementById("contested-opponent-modifier").value, 10) || 0;
  const roll_expression = document.getElementById("contested-roll-expression").value.trim() || "d20";
  const actor_advantage_state = document.getElementById("contested-actor-advantage").value || "normal";
  const opponent_advantage_state = document.getElementById("contested-opponent-advantage").value || "normal";
  const reason = document.getElementById("contested-reason").value.trim();
  const action_cost = document.getElementById("contested-action-cost").value || "action";
  const resource_costs = parseResourceCosts(document.getElementById("contested-resource-costs").value);
  const narrateOutcome = document.getElementById("contested-narrate-outcome").checked;
  const submitBtn = document.getElementById("resolve-contested-submit");

  if (!actor_source || !opponent_source) {
    showError("Both player and opponent sources are required.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Resolving...";
  try {
    const payload = {
      actor_source,
      opponent_source,
      opponent_owner_type: opponent_owner_id ? "npc" : null,
      opponent_owner_id: opponent_owner_id || null,
      opponent_name,
      opponent_modifier: opponent_owner_id ? null : opponent_modifier,
      roll_expression,
      actor_advantage_state,
      opponent_advantage_state,
      action_cost,
      reason,
      resource_costs,
    };
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/contested-checks/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    appendDiceRoll(`${data.actor?.name || "Player"} ${actor_source}`, data.actor?.dice_rolls || [], data.actor?.modifier || 0, data.actor?.total || 0);
    appendDiceRoll(`${data.opponent?.name || opponent_name} ${opponent_source}`, data.opponent?.dice_rolls || [], data.opponent?.modifier || 0, data.opponent?.total || 0);
    if (data.encounter) _activeEncounter = data.encounter;
    await refreshActionLogs();
    renderSidebar();
    closeModal("resolve-contested-check-modal");
    const winnerName = data.winner === "actor"
      ? data.actor?.name || "Player"
      : data.winner === "opponent"
        ? data.opponent?.name || opponent_name
        : "No one";
    const resultText = data.winner === "tie"
      ? "Contested check tied."
      : `${winnerName} won by ${data.margin || 0}.`;
    showToast(
      resultText,
      data.winner === "actor" ? "success" : "info"
    );
    if (narrateOutcome) {
      await streamMechanicsFollowup(
        `Resolved contested check: ${data.actor?.name || "Player"} rolled ${data.actor?.total || 0} and ${data.opponent?.name || opponent_name} rolled ${data.opponent?.total || 0}. ${resultText} Narrate the immediate struggle and consequence.`
      );
    }
  } catch (e) {
    showError(`Could not resolve contested check: ${e.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Resolve";
  }
}

async function submitSheetStateUpdate() {
  const submitBtn = document.getElementById("sheet-state-submit");
  const damage = parseInt(document.getElementById("sheet-state-damage").value, 10) || 0;
  const healing = parseInt(document.getElementById("sheet-state-healing").value, 10) || 0;
  const temp_hp_delta = parseInt(document.getElementById("sheet-state-temp").value, 10) || 0;
  const add_conditions = splitCsv(document.getElementById("sheet-state-add-conditions").value);
  const remove_conditions = splitCsv(document.getElementById("sheet-state-remove-conditions").value);
  const notes_append = document.getElementById("sheet-state-note").value.trim();

  submitBtn.disabled = true;
  submitBtn.textContent = "Applying...";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheet/adjust`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ damage, healing, temp_hp_delta, add_conditions, remove_conditions, notes_append }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _sheet = data.sheet || _sheet;
    await refreshActionLogs();
    renderSidebar();
    closeModal("sheet-state-modal");
    showToast(data.summary || "Updated sheet state.", "success");
  } catch (e) {
    showError(`Could not update sheet state: ${e.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Apply";
  }
}

async function refreshActionLogs() {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/action-logs?n=20`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _actionLogs = await res.json();
    await refreshRuleAudits({ quiet: true });
    await refreshCampaignRecap();
  } catch (e) {
    showError(`Could not refresh action log: ${e.message}`);
  }
}

async function refreshRuleAudits(options = {}) {
  const quiet = options.quiet === true;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/rule-audits?n=20`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _ruleAudits = await res.json();
    renderRuleAuditSidebar();
  } catch (e) {
    if (!quiet) showError(`Could not refresh rule audits: ${e.message}`);
  }
}

function renderRuleAuditSidebar() {
  const section = document.getElementById("rule-audit-section");
  const container = document.getElementById("sidebar-rule-audit");
  if (!section || !container) return;

  const isRulesMode = isD20RulesMode();
  section.style.display = isRulesMode ? "" : "none";
  if (!isRulesMode) return;

  const audits = (_ruleAudits || []).slice(0, 8);
  if (!audits.length) {
    container.innerHTML = '<div class="gm-empty">No rule audits yet.</div>';
    return;
  }

  container.innerHTML = audits.map(audit => {
    const summary = buildRuleAuditSummary(audit);
    const why = buildRuleAuditWhy(audit);
    const time = formatRelativeAuditTime(audit.created_at);
    return `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(String(audit.event_type || "audit").replaceAll("_", " "))}</div>
        <div class="sidebar-item-sub">${escHtml(summary)}</div>
        ${why ? `<div class="sidebar-item-sub muted">${escHtml(why)}</div>` : ""}
        <div class="sidebar-item-sub muted">${escHtml([audit.actor_name || "GM", audit.source || "", time].filter(Boolean).join(" · "))}</div>
      </div>
    `;
  }).join("");
}

function buildRuleAuditSummary(audit) {
  const payload = audit.payload || {};
  if (audit.event_type === "attack") {
    const attack = payload.attack || {};
    const damage = payload.damage || {};
    const damagePart = damage.total ? ` for ${damage.total} ${damage.damage_type || "damage"}` : "";
    return `${attack.total ?? "?"} vs AC ${attack.target_armor_class ?? "?"}${damagePart}`;
  }
  if (audit.event_type === "healing") {
    const healing = payload.healing || {};
    return `Restored ${healing.total ?? "?"} HP from ${healing.source || audit.source || "healing"}.`;
  }
  if (audit.event_type === "check") {
    const resolution = payload.resolution || {};
    return `${resolution.total ?? "?"} vs DC ${resolution.difficulty ?? "?"} on ${resolution.source || audit.source || "check"}.`;
  }
  if (audit.event_type === "contested_check") {
    const resolution = payload.resolution || {};
    return `${resolution.actor?.name || "Actor"} ${resolution.actor?.total ?? "?"} vs ${resolution.opponent?.name || "Opponent"} ${resolution.opponent?.total ?? "?"}.`;
  }
  if (audit.event_type === "gm_decision") {
    const passive = (payload.passive_sources || []).join(", ");
    return passive ? `GM decided on ${payload.resolution_kind || "rules"} using passive ${passive}.` : `GM decided on ${payload.resolution_kind || "rules"} handoff.`;
  }
  if (audit.event_type === "gm_decision_error") {
    return "Hidden GM decision block was malformed; fallback guidance was used.";
  }
  if (audit.event_type === "compendium_action") {
    return `${payload.entry?.name || audit.source || "Compendium action"} resolved directly.`;
  }
  if (audit.event_type === "campaign_procedure") {
    return payload.world_time?.label ? `Procedure advanced to ${payload.world_time.label}.` : (audit.reason || "Campaign procedure resolved.");
  }
  return audit.reason || audit.source || "Rule audit recorded.";
}

function buildRuleAuditWhy(audit) {
  const payload = audit.payload || {};
  if (audit.event_type === "gm_decision") {
    const extras = [];
    if (payload._fallback_preview) extras.push("fallback preview");
    if (payload._contract_parse_error) extras.push("invalid hidden contract");
    if (payload.passive_sources?.length) extras.push(`passive ${payload.passive_sources.join("/")}`);
    return extras.join(" · ");
  }
  if (audit.event_type === "gm_decision_error") {
    return payload.contract_parse_error || "Could not parse GM contract JSON.";
  }
  if (audit.event_type === "attack") {
    const attack = payload.attack || {};
    if (attack.outcome) return String(attack.outcome).replaceAll("_", " ");
  }
  if (audit.event_type === "check") {
    const resolution = payload.resolution || {};
    const parts = [];
    if (resolution.advantage_state && resolution.advantage_state !== "normal") parts.push(resolution.advantage_state);
    if (resolution.outcome) parts.push(String(resolution.outcome).replaceAll("_", " "));
    return parts.join(" · ");
  }
  if (audit.event_type === "campaign_procedure") {
    const rewards = Object.entries(payload.reward_currencies || {})
      .filter(([, amount]) => Number(amount) > 0)
      .map(([denomination, amount]) => `${amount} ${denomination}`)
      .join(", ");
    return rewards ? `reward: ${rewards}` : "";
  }
  return "";
}

function splitCsv(raw) {
  return raw
    .split(",")
    .map(part => part.trim())
    .filter(Boolean);
}

function parseResourceCosts(raw) {
  const costs = {};
  if (!raw.trim()) return costs;
  for (const entry of raw.split(",")) {
    const part = entry.trim();
    if (!part) continue;
    const [name, amount] = part.split(":").map(value => value.trim());
    const parsed = parseInt(amount, 10);
    if (name && Number.isFinite(parsed)) {
      costs[name] = parsed;
    }
  }
  return costs;
}

function formatResourceCosts(costs) {
  return Object.entries(costs || {})
    .map(([key, value]) => `${key}:${value}`)
    .join(", ");
}

// ── Scene search ──────────────────────────────────────────────────────────────

function openSceneSearch() {
  document.getElementById("scene-search-input").value = "";
  document.getElementById("scene-search-results").innerHTML =
    '<div class="muted" style="font-size:0.85rem">Type to search within this scene\'s turns.</div>';
  openModal("scene-search-modal");
  setTimeout(() => document.getElementById("scene-search-input").focus(), 50);
}

function runSceneSearch() {
  const q = document.getElementById("scene-search-input").value.toLowerCase().trim();
  const container = document.getElementById("scene-search-results");
  if (q.length < 2) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">Type at least 2 characters.</div>';
    return;
  }
  const turns = _scene?.turns || [];
  const matches = [];
  turns.forEach((t, i) => {
    const pos = t.content.toLowerCase().indexOf(q);
    if (pos === -1) return;
    const start = Math.max(0, pos - 60);
    const end   = Math.min(t.content.length, pos + q.length + 60);
    matches.push({ turn: t, index: i, pos, start, end, excerpt: t.content.slice(start, end) });
  });

  if (!matches.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">No matches in this scene.</div>';
    return;
  }
  container.innerHTML = "";
  matches.forEach(m => {
    const div = document.createElement("div");
    div.className = "search-result";
    const role = m.turn.role === "user" ? "Player" : "Narrator";
    const localPos = m.pos - m.start;
    const before = escHtml(m.excerpt.slice(0, localPos));
    const match  = escHtml(m.excerpt.slice(localPos, localPos + q.length));
    const after  = escHtml(m.excerpt.slice(localPos + q.length));
    div.innerHTML = `
      <div class="search-result-meta"><span class="muted">${role} · Turn ${m.index + 1}</span></div>
      <div class="search-result-excerpt">${before}<mark class="search-highlight">${match}</mark>${after}</div>
    `;
    container.appendChild(div);
  });
}

// ── Undo last turn ────────────────────────────────────────────────────────────

async function undoLastTurn() {
  if (_streaming || !_scene) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/last`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    _scene = await res.json();
    _clearRegenState();
    // Re-render the messages area from the updated turn list
    const area = document.getElementById("messages-area");
    area.innerHTML = "";
    renderExistingTurns();
    updateUndoButton();
    showToast("Last exchange removed.", "info");
  } catch (e) {
    showError(`Undo failed: ${e.message}`);
  }
}

// ── Prompt preview ────────────────────────────────────────────────────────────

async function openPromptPreview() {
  if (!_scene) {
    showToast("No active scene to preview.", "info");
    return;
  }
  document.getElementById("prompt-preview-loading").style.display = "";
  document.getElementById("prompt-preview-text").style.display = "none";
  document.getElementById("prompt-preview-stats").textContent = "";
  openModal("prompt-preview-modal");
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/prompt-preview`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    document.getElementById("prompt-preview-text").textContent = data.system_prompt;
    document.getElementById("prompt-preview-text").style.display = "";
    const chars = data.system_prompt.length;
    document.getElementById("prompt-preview-stats").textContent =
      `${chars.toLocaleString()} chars · ${data.total_messages - 2} history turns`;
  } catch (e) {
    document.getElementById("prompt-preview-loading").textContent = `Error: ${e.message}`;
  } finally {
    document.getElementById("prompt-preview-loading").style.display = "none";
  }
}

// ── Toast notifications ───────────────────────────────────────────────────────

function showToast(msg, type = "info", duration = 4000) {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  // Trigger fade-in
  requestAnimationFrame(() => toast.classList.add("toast-visible"));
  setTimeout(() => {
    toast.classList.remove("toast-visible");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  }, duration);
}

// ── Input helpers ─────────────────────────────────────────────────────────────

function setupInput() {
  const input = document.getElementById("user-input");
  if (!input) return;
  input.addEventListener("keydown", e => {
    // Enter (without Shift) sends; Ctrl/Cmd+Enter also sends
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
    scheduleGMProcedurePreview();
  });

  // Global keyboard shortcuts
  document.addEventListener("keydown", e => {
    // Esc → close topmost visible modal
    if (e.key === "Escape") {
      const modals = [...document.querySelectorAll(".modal-backdrop:not(.hidden)")];
      if (modals.length) {
        e.preventDefault();
        modals[modals.length - 1].classList.add("hidden");
      }
    }
    // / → focus chat input (when not already in a text field and chat is visible)
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = document.activeElement?.tagName;
      if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
        const chatBody = document.getElementById("chat-body");
        if (chatBody && chatBody.style.display !== "none") {
          e.preventDefault();
          input.focus();
        }
      }
    }
  });
}

function setSendEnabled(enabled) {
  document.getElementById("send-btn").disabled = !enabled;
  const continueBtn = document.getElementById("continue-btn");
  if (continueBtn) continueBtn.disabled = !enabled;
}

function scrollToBottom() {
  const area = document.getElementById("messages-area");
  area.scrollTop = area.scrollHeight;
}

function showError(msg) {
  const el = document.getElementById("error-banner");
  el.textContent = msg;
  el.style.display = "";
  setTimeout(() => { el.style.display = "none"; }, 8000);
}

// ── Modals ────────────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// ── Quick-add NPC ─────────────────────────────────────────────────────────────

function openQuickAddNpc() {
  document.getElementById("qnpc-name").value = "";
  document.getElementById("qnpc-role").value = "";
  document.getElementById("qnpc-personality").value = "";
  document.getElementById("qnpc-state").value = "";
  document.getElementById("qnpc-add-to-scene").checked = true;
  openModal("quick-npc-modal");
  setTimeout(() => document.getElementById("qnpc-name").focus(), 50);
}

async function saveQuickNpc() {
  const name = document.getElementById("qnpc-name").value.trim();
  if (!name) {
    document.getElementById("qnpc-name").focus();
    return;
  }
  const body = {
    name,
    role: document.getElementById("qnpc-role").value.trim(),
    personality: document.getElementById("qnpc-personality").value.trim(),
    current_state: document.getElementById("qnpc-state").value.trim(),
    current_location: _scene?.location || "",
    appearance: "",
    relationship_to_player: "",
    is_alive: true,
  };

  try {
    // 1. Save NPC to world document
    const npcRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!npcRes.ok) throw new Error(`HTTP ${npcRes.status}`);
    const newNpc = await npcRes.json();

    // Add to local NPC list
    _npcs = [..._npcs.filter(n => n.id !== newNpc.id), newNpc];

    // 2. Optionally add to current scene's npc_ids
    const addToScene = document.getElementById("qnpc-add-to-scene").checked;
    if (addToScene && _scene) {
      const updatedIds = [...(_scene.npc_ids || []), newNpc.id];
      const sceneRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ npc_ids: updatedIds }),
      });
      if (sceneRes.ok) {
        _scene = await sceneRes.json();
      }
    }

    closeModal("quick-npc-modal");
    renderSidebar();
  } catch (e) {
    showError(`Could not save NPC: ${e.message}`);
  }
}

// ── Player scratchpad ─────────────────────────────────────────────────────────

let _scratchpadTimer = null;

function loadScratchpad() {
  const notes = _campaign?.notes || "";
  const el = document.getElementById("scratchpad");
  if (!el) return;
  el.value = notes;
  el.addEventListener("input", () => {
    clearTimeout(_scratchpadTimer);
    document.getElementById("scratchpad-status").textContent = "Unsaved…";
    _scratchpadTimer = setTimeout(saveScratchpad, 1200);
  });
}

async function saveScratchpad() {
  const el = document.getElementById("scratchpad");
  const statusEl = document.getElementById("scratchpad-status");
  if (!el) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: el.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (_campaign) _campaign.notes = el.value;
    statusEl.textContent = "Saved";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  } catch (e) {
    statusEl.textContent = "Save failed";
  }
}

// ── Image generation bridge (used by campaign_imggen.js) ─────────────────────

// ── Gen-settings helpers ──────────────────────────────────────────────────────

function gsSync(key, value, decimals) {
  const lbl = document.getElementById(`gs-lbl-${key}`);
  if (lbl) lbl.textContent = decimals > 0 ? parseFloat(value).toFixed(decimals) : value;
}

function gsGetParams() {
  return {
    temperature:    parseFloat(document.getElementById("gs-temperature")?.value    ?? 0.8),
    top_p:          parseFloat(document.getElementById("gs-top_p")?.value          ?? 0.95),
    top_k:          parseInt(document.getElementById("gs-top_k")?.value            ?? 0),
    min_p:          parseFloat(document.getElementById("gs-min_p")?.value          ?? 0.05),
    repeat_penalty: parseFloat(document.getElementById("gs-repeat_penalty")?.value ?? 1.10),
    max_tokens:     parseInt(document.getElementById("gs-max_tokens")?.value       ?? 1024),
    seed:           parseInt(document.getElementById("gs-seed")?.value             ?? -1),
  };
}

function gsInitFromCampaign() {
  const gs = _campaign?.gen_settings || {};
  const defaults = { temperature:0.80, top_p:0.95, top_k:0, min_p:0.05, repeat_penalty:1.10, max_tokens:1024, seed:-1 };
  for (const [k, def] of Object.entries(defaults)) {
    const v = gs[k] ?? def;
    const el = document.getElementById(`gs-${k}`);
    if (el) { el.value = v; gsSync(k, v, ["temperature","top_p","min_p","repeat_penalty"].includes(k) ? 2 : 0); }
  }
}

function gsResetDefaults() {
  gsInitFromCampaign();
}

function openSceneImgGen() {
  if (!_scene) { showToast("No active scene.", 3000); return; }
  openImgGen("scene", { sceneId: _scene.id });
}

function openChatImgGen() {
  if (!_scene) { showToast("No active scene.", 3000); return; }
  // Find the last assistant turn in the local scene state
  const turns = _scene.turns || [];
  const lastAi = [...turns].reverse().find(t => t.role === "assistant");
  if (!lastAi) { showToast("No AI response yet to base the image on.", 3000); return; }
  openImgGen("chat", { sceneId: _scene.id, lastMessage: lastAi.content });
}

/** Called by campaign_imggen.js when the user clicks "Insert into Chat" */
function insertImgGenToChat_impl(dataUrl, prompt) {
  const area = document.getElementById("messages-area");
  if (!area) return;
  const div = document.createElement("div");
  div.className = "message-bubble ai-bubble imggen-inline";
  div.style.animation = "fadeIn 0.2s ease";

  const delBtn = document.createElement("button");
  delBtn.className = "imggen-del-btn";
  delBtn.textContent = "✕";
  delBtn.title = "Remove image";
  delBtn.onclick = () => div.remove();

  const caption = document.createElement("div");
  caption.className = "imggen-caption";
  caption.textContent = prompt;

  const img = document.createElement("img");
  img.src = dataUrl;
  img.alt = prompt;
  img.className = "imggen-inline-img";
  img.title = "Click to expand";
  img.onclick = () => img.classList.toggle("imggen-inline-img-full");

  const hint = document.createElement("div");
  hint.className = "muted";
  hint.style.cssText = "font-size:11px;margin-top:4px";
  hint.textContent = "Click image to expand · Generated by ComfyUI";

  div.appendChild(delBtn);
  div.appendChild(caption);
  div.appendChild(img);
  div.appendChild(hint);
  area.appendChild(div);
  scrollToBottom();
}

// ── Portrait lightbox ─────────────────────────────────────────────────────────

function openPortraitLightbox(src, name) {
  document.getElementById("portrait-lightbox-img").src = src;
  document.getElementById("portrait-lightbox-img").alt = name || "";
  document.getElementById("portrait-lightbox").classList.remove("hidden");
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
