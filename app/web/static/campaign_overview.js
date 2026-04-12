/**
 * Campaign overview page JS.
 * Loads the full world document and allows editing all entities.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

let _campaign = null;
let _pc = null;
let _sheet = null;
let _facts = [];
let _npcs = [];
let _places = [];
let _threads = [];
let _factions = [];
let _relationships = [];
let _scenes = [];
let _chronicle = [];
let _actionLogs = [];

let _fieldKey = null;   // which field is being edited in the field modal
let _editingNpcId = null;  // NPC whose dev-log modal is open

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadWorld();
  checkStatus();
  initCollapsibles();
});

async function loadWorld() {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _campaign       = data.campaign;
    _pc             = data.player_character;
    _sheet          = data.character_sheet;
    _actionLogs     = data.action_logs || [];
    _facts          = data.world_facts || [];
    _npcs           = data.npcs || [];
    _places         = data.places || [];
    _threads        = data.threads || [];
    _factions       = data.factions || [];
    _relationships  = data.npc_relationships || [];
    _scenes         = data.scenes || [];
    _chronicle      = data.chronicle || [];
    renderAll();
  } catch (e) {
    showBanner(`Failed to load campaign: ${e.message}`, "error");
  }
}

async function checkStatus() {
  try {
    const res = await fetch("/api/provider");
    const data = await res.json();
    const dot = document.getElementById("status-dot");
    const lbl = document.getElementById("status-label");
    if (data.available) {
      dot.className = "status-dot online";
      lbl.textContent = `${data.provider} · ${data.default_model}`;
    } else {
      dot.className = "status-dot offline";
      lbl.textContent = `${data.provider} offline`;
    }
  } catch {/* ignore */}
}

function renderAll() {
  // Header
  document.getElementById("campaign-title").textContent = _campaign?.name || "Campaign";
  if (_campaign?.model_name)
    document.getElementById("campaign-model").textContent = `Model: ${_campaign.model_name}`;
  document.title = `${_campaign?.name || "Campaign"} — RP Utility`;

  // Campaign cover image
  const coverImg = document.getElementById("campaign-cover-img");
  const coverPlaceholder = document.getElementById("campaign-cover-placeholder");
  if (_campaign?.cover_image && coverImg) {
    coverImg.src = _campaign.cover_image;
    coverImg.classList.remove("hidden");
    if (coverPlaceholder) coverPlaceholder.classList.add("hidden");
  }

  // World doc
  const facts = _facts.filter(f => f.content);
  const premise = facts.length && facts[0].content.length > 80 ? facts[0].content : null;

  document.getElementById("world-premise").textContent =
    premise || "(no premise — edit to add one)";

  // World facts — grouped by category (skip the premise if it's in position 0)
  const factsList = document.getElementById("world-facts-list");
  factsList.innerHTML = "";
  const displayFacts = premise ? _facts.slice(1) : _facts;
  // Group by category
  const catGroups = {};
  displayFacts.forEach(f => {
    if (!f.content) return;
    const cat = (f.category || "").trim();
    if (!catGroups[cat]) catGroups[cat] = [];
    catGroups[cat].push(f);
  });
  const catKeys = Object.keys(catGroups).sort((a, b) => {
    if (!a) return -1; if (!b) return 1;
    return a.localeCompare(b);
  });
  catKeys.forEach(cat => {
    if (cat) {
      const header = document.createElement("li");
      header.className = "world-fact-category-header";
      header.textContent = cat.toUpperCase();
      factsList.appendChild(header);
    }
    catGroups[cat].forEach(f => {
      const li = document.createElement("li");
      li.className = "world-fact-item";
      li.innerHTML = `<span>${escHtml(f.content)}</span>
        <button class="btn-icon fact-edit-btn" onclick="openEditFact(${escHtml(JSON.stringify(f))})" title="Edit">✎</button>
        <button class="btn-icon fact-delete-btn" onclick="deleteFact('${f.id}')" title="Delete">✕</button>`;
      factsList.appendChild(li);
    });
  });

  // Magic / technology
  const magicEl = document.getElementById("world-magic");
  const sg = _campaign?.style_guide || {};
  magicEl.textContent = sg.magic_system || "(none — click Edit to add)";

  // PC card
  renderPcCard();

  // NPCs
  renderNpcList();

  // Places
  renderEntityList("places-list", _places, openEditPlace, "place");

  // Threads
  renderEntityList("threads-list", _threads, openEditThread, "thread");

  // Factions
  renderEntityList("factions-list", _factions, openEditFaction, "faction");

  // NPC Relationships
  renderRelationshipsList();

  // Scenes tab
  renderScenesList();

  // Chronicle tab
  renderChronicle();
}

function renderPcCard() {
  const el = document.getElementById("pc-card");
  const sheetEl = document.getElementById("pc-sheet-card");

  // Portrait display
  const portraitImg         = document.getElementById("pc-portrait-img");
  const portraitPlaceholder = document.getElementById("pc-portrait-placeholder");
  if (portraitImg && portraitPlaceholder) {
    if (_pc?.portrait_image) {
      portraitImg.src = _pc.portrait_image;
      portraitImg.classList.remove("hidden");
      portraitPlaceholder.style.display = "none";
    } else {
      portraitImg.classList.add("hidden");
      portraitPlaceholder.style.display = "";
    }
  }

  if (!_pc || !_pc.name) {
    el.innerHTML = '<span class="muted">No player character yet. Click Edit to add one.</span>';
  } else {
    el.innerHTML = `
      <div class="pc-card-name">${escHtml(_pc.name)}</div>
      ${_pc.personality ? `<div class="pc-card-field"><span class="pc-field-label">Personality:</span> ${escHtml(_pc.personality)}</div>` : ""}
      ${_pc.background  ? `<div class="pc-card-field"><span class="pc-field-label">Background:</span> ${escHtml(_pc.background)}</div>` : ""}
      ${_pc.wants       ? `<div class="pc-card-field"><span class="pc-field-label">Wants:</span> ${escHtml(_pc.wants)}</div>` : ""}
      ${_pc.fears       ? `<div class="pc-card-field"><span class="pc-field-label">Fears:</span> ${escHtml(_pc.fears)}</div>` : ""}
    `;
  }

  if (!sheetEl) return;
  if (!_sheet || !_sheet.name) {
    sheetEl.innerHTML = '<span class="muted">No character sheet yet. Rules mode will work better once one is added.</span>';
    return;
  }
  const abilities = _sheet.abilities || {};
  const abilityLine = ["strength","dexterity","constitution","intelligence","wisdom","charisma"]
    .map(k => `${k.slice(0,3).toUpperCase()} ${abilities[k] ?? 10}`)
    .join(" · ");
  const topSkills = Object.entries(_sheet.skill_modifiers || {}).slice(0, 4)
    .map(([k,v]) => `${k} ${v >= 0 ? "+" : ""}${v}`).join(" · ");
  sheetEl.innerHTML = `
    <div class="pc-card-name">Rules Sheet</div>
    <div class="pc-card-field"><span class="pc-field-label">Class:</span> ${escHtml(_sheet.character_class || "Adventurer")} ${_sheet.level ? `(Level ${_sheet.level})` : ""}</div>
    <div class="pc-card-field"><span class="pc-field-label">Ancestry:</span> ${escHtml(_sheet.ancestry || "Unspecified")}</div>
    <div class="pc-card-field"><span class="pc-field-label">HP / AC:</span> ${_sheet.current_hp}/${_sheet.max_hp} HP · AC ${_sheet.armor_class}</div>
    <div class="pc-card-field"><span class="pc-field-label">Abilities:</span> ${escHtml(abilityLine)}</div>
    ${topSkills ? `<div class="pc-card-field"><span class="pc-field-label">Top Skills:</span> ${escHtml(topSkills)}</div>` : ""}
  `;
}

function _threadStalenessBadge(thread) {
  if (thread.status !== "active") return "";
  const confirmedScenes = _scenes.filter(s => s.confirmed);
  if (!confirmedScenes.length) return "";
  const maxScene = Math.max(...confirmedScenes.map(s => s.scene_number));
  const mentionedAt = thread.last_mentioned_scene || 0;
  if (!mentionedAt) {
    // Never explicitly mentioned — show warning once there are 3+ confirmed scenes
    if (maxScene >= 3) return `<span class="thread-stale-badge" title="Never advanced">dormant</span>`;
    return "";
  }
  const gap = maxScene - mentionedAt;
  if (gap >= 5) return `<span class="thread-stale-badge thread-stale-critical" title="${gap} scenes since last advanced">${gap} scenes ago</span>`;
  if (gap >= 3) return `<span class="thread-stale-badge" title="${gap} scenes since last advanced">${gap} scenes ago</span>`;
  return "";
}

function renderEntityList(containerId, items, openFn, type) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">None yet.</div>';
    return;
  }
  items.forEach(item => {
    const div = document.createElement("div");
    div.className = "entity-card";
    const name = item.name || item.title || "(unnamed)";
    const sub  = item.role || item.description || item.status || "";
    const badge = type === "thread" && item.status
      ? `<span class="thread-status-badge status-${item.status}">${item.status}</span>${_threadStalenessBadge(item)}`
      : "";
    div.innerHTML = `
      <div class="entity-card-row">
        <div>
          <div class="entity-name">${escHtml(name)} ${badge}</div>
          ${sub ? `<div class="entity-sub muted">${escHtml(sub.substring(0, 80))}${sub.length > 80 ? "…" : ""}</div>` : ""}
        </div>
        <button class="btn-icon" title="Edit">✎</button>
      </div>
    `;
    // Use addEventListener to avoid JSON-in-HTML escaping problems
    div.querySelector("button").addEventListener("click", () => openFn(item));
    container.appendChild(div);
  });
}

function renderScenesList() {
  const container = document.getElementById("scenes-list");
  container.innerHTML = "";
  if (!_scenes.length) {
    container.innerHTML = '<div class="muted">No scenes yet. Click ▶ Play to start your first scene.</div>';
    return;
  }
  // Active (unconfirmed) scenes first, then confirmed by scene number descending
  const sorted = [..._scenes].sort((a, b) => {
    if (!a.confirmed && b.confirmed) return -1;
    if (a.confirmed && !b.confirmed) return 1;
    return b.scene_number - a.scene_number;
  });
  sorted.forEach(s => {
    const div = document.createElement("div");
    div.className = "scene-card";
    const badge = s.confirmed
      ? '<span class="scene-badge confirmed">Confirmed</span>'
      : '<span class="scene-badge active">In Progress</span>';
    const turnCount = s.turns?.length || 0;
    const sid = escHtml(s.id);
    const summaryEsc = (s.confirmed_summary || "").replace(/\\/g, "\\\\").replace(/`/g, "\\`");
    div.innerHTML = `
      <div class="scene-card-header">
        <div>
          <span class="scene-number">Scene ${s.scene_number}</span>
          ${s.title ? `— <span class="scene-title">${escHtml(s.title)}</span>` : ""}
          ${badge}
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${turnCount > 0 ? `<button class="btn btn-sm btn-ghost" onclick="viewSceneTranscript(${JSON.stringify(s).replace(/"/g, '&quot;')})">📜 Read</button>` : ""}
          ${s.confirmed ? `<button class="btn btn-sm btn-ghost" onclick="editSceneSummary('${sid}', \`${summaryEsc}\`, ${s.scene_number})">✏ Summary</button>` : ""}
          ${s.confirmed ? `<button class="btn btn-sm btn-ghost" onclick="reopenScene('${sid}')">↩ Reopen</button>` : ""}
          ${!s.confirmed ? `<a href="/campaigns/${CAMPAIGN_ID}/play" class="btn btn-sm">▶ Continue</a>` : ""}
        </div>
      </div>
      ${s.location ? `<div class="muted scene-meta">📍 ${escHtml(s.location)}</div>` : ""}
      ${s.confirmed_summary ? `<div class="scene-summary">${escHtml(s.confirmed_summary)}</div>` : ""}
    `;
    container.appendChild(div);
  });
}

function reopenScene(sceneId) {
  showConfirm("Reopen this scene? It will become active again and you can continue playing or editing it.", async () => {
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${sceneId}/reopen`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      const idx = _scenes.findIndex(s => s.id === sceneId);
      if (idx >= 0) _scenes[idx] = updated;
      renderScenesList();
      showBanner("Scene reopened. Click ▶ Continue to resume.", "success");
    } catch (e) { showBanner(`Reopen failed: ${e.message}`, "error"); }
  });
}

let _editSummarySceneId = null;

function editSceneSummary(sceneId, currentSummary, sceneNum) {
  _editSummarySceneId = sceneId;
  document.getElementById("es-title").textContent = `Edit Summary — Scene ${sceneNum}`;
  document.getElementById("es-textarea").value = currentSummary;
  document.getElementById("es-status").textContent = "";

  // Populate model select
  const sel = document.getElementById("es-model");
  if (sel.options.length <= 1) {
    fetch("/api/models").then(r => r.json()).then(data => {
      const models = Array.isArray(data) ? data : (data.models || []);
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.name; opt.textContent = m.name;
        sel.appendChild(opt);
      });
      // Pre-select campaign summary model if set
      sel.value = _campaign?.summary_model_name || _campaign?.model_name || "";
    }).catch(() => {});
  } else {
    sel.value = _campaign?.summary_model_name || _campaign?.model_name || "";
  }

  openModal("edit-summary-modal");
}

async function resuggestSceneSummary() {
  const sceneId = _editSummarySceneId;
  if (!sceneId) return;
  const statusEl = document.getElementById("es-status");
  const btn = document.getElementById("es-regen-btn");
  const modelName = document.getElementById("es-model").value || null;
  statusEl.textContent = "Generating…";
  btn.disabled = true;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${sceneId}/suggest-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    document.getElementById("es-textarea").value = data.summary || "";
    statusEl.textContent = "Summary generated — review and save.";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function saveSceneSummary() {
  const sceneId = _editSummarySceneId;
  if (!sceneId) return;
  const summary = document.getElementById("es-textarea").value.trim();
  const statusEl = document.getElementById("es-status");
  statusEl.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${sceneId}/summary`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    const idx = _scenes.findIndex(s => s.id === sceneId);
    if (idx >= 0) _scenes[idx] = updated;
    renderScenesList();
    closeModal("edit-summary-modal");
    showBanner("Summary saved.", "success");
  } catch (e) {
    statusEl.textContent = `Save failed: ${e.message}`;
  }
}

function renderChronicle() {
  const container = document.getElementById("chronicle-list");
  container.innerHTML = "";

  // Show/hide compress button
  const compressBtn = document.getElementById("compress-btn");
  if (compressBtn) compressBtn.style.display = _chronicle.length >= 2 ? "" : "none";

  if (!_chronicle.length) {
    container.innerHTML = '<div class="muted">The chronicle is empty. It fills as scenes are completed and confirmed.</div>';
    return;
  }
  _chronicle.forEach(e => {
    const div = document.createElement("div");
    div.className = "chronicle-entry";
    const rangeLabel = e.scene_range_start === e.scene_range_end
      ? `Scene ${e.scene_range_start}`
      : `Scenes ${e.scene_range_start}–${e.scene_range_end}`;
    div.innerHTML = `
      <div class="chronicle-entry-header">
        <div class="chronicle-range">${rangeLabel}</div>
        <div class="chronicle-entry-actions">
          <button class="btn-icon" onclick="openChronicleEdit('${e.id}', ${escHtml(JSON.stringify(e.content))})" title="Edit">✎</button>
          <button class="btn-icon btn-icon-danger" onclick="deleteChronicleEntry('${e.id}')" title="Delete">✕</button>
        </div>
      </div>
      <div class="chronicle-content">${escHtml(e.content)}</div>
    `;
    container.appendChild(div);
  });
}

// ── Collapsible sections ──────────────────────────────────────────────────────

function _sectionKey(name) {
  return `rpu-collapsed-${CAMPAIGN_ID}-${name}`;
}

function initCollapsibles() {
  document.querySelectorAll(".world-section[data-section]").forEach(section => {
    const name = section.dataset.section;
    const header = section.querySelector(".world-section-header");
    if (!header) return;

    // Wrap the h3 and a new toggle button in a left-side group so the
    // existing "+ Add" / "✎ Edit" button stays flush-right via space-between.
    const h3 = header.querySelector("h3");
    if (!h3) return;

    const btn = document.createElement("button");
    btn.className = "collapse-toggle";
    btn.title = "Collapse / expand";
    btn.setAttribute("aria-label", "Toggle section");

    const titleGroup = document.createElement("span");
    titleGroup.className = "section-title-group";
    h3.replaceWith(titleGroup);
    titleGroup.appendChild(btn);
    titleGroup.appendChild(h3);

    // Restore saved state
    const collapsed = localStorage.getItem(_sectionKey(name)) === "1";
    _applyCollapse(section, btn, collapsed);

    btn.addEventListener("click", () => {
      const isNowCollapsed = !section.classList.contains("section-collapsed");
      localStorage.setItem(_sectionKey(name), isNowCollapsed ? "1" : "0");
      _applyCollapse(section, btn, isNowCollapsed);
    });
  });
}

function _applyCollapse(section, btn, collapsed) {
  section.classList.toggle("section-collapsed", collapsed);
  btn.textContent = collapsed ? "▸" : "▾";
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll(".campaign-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".campaign-tab-content").forEach(el =>
    el.classList.toggle("hidden", el.id !== `tab-${name}`));
}

// ── Field editor (premise, magic) ─────────────────────────────────────────────

function editField(key) {
  _fieldKey = key;
  const titles = { premise: "Edit Premise", magic_system: "Edit Magic / Technology" };
  document.getElementById("field-modal-title").textContent = titles[key] || "Edit";

  let current = "";
  if (key === "premise") {
    const facts = _facts.filter(f => f.content);
    current = facts.length && facts[0].content.length > 80 ? facts[0].content : "";
  } else if (key === "magic_system") {
    current = _campaign?.style_guide?.magic_system || "";
  }
  document.getElementById("field-modal-textarea").value = current;
  openModal("field-modal");
}

async function saveField() {
  const value = document.getElementById("field-modal-textarea").value.trim();
  closeModal("field-modal");

  if (_fieldKey === "premise") {
    // Store as the first world fact
    const restFacts = _facts.filter((_, i) => {
      const isPremise = _facts[0]?.content?.length > 80;
      return !(isPremise && i === 0);
    }).map(f => f.content);
    const newFacts = value ? [value, ...restFacts] : restFacts;
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facts: newFacts }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _facts = await res.json();
      renderAll();
    } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }

  } else if (_fieldKey === "magic_system") {
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ magic_system: value }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _campaign = await res.json();
      renderAll();
    } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
  }
}

// ── World facts ───────────────────────────────────────────────────────────────

function openEditFact(fact) {
  document.getElementById("fact-edit-id").value = fact?.id || "";
  document.getElementById("fact-edit-content").value = fact?.content || "";
  document.getElementById("fact-edit-category").value = fact?.category || "";
  document.getElementById("fact-edit-priority").value = fact?.priority || "normal";
  document.getElementById("fact-edit-keywords").value = (fact?.trigger_keywords || []).join(", ");
  document.getElementById("fact-edit-title").textContent = fact ? "Edit World Fact" : "Add World Fact";
  openModal("fact-edit-modal");
}

async function saveFactEdit() {
  const id = document.getElementById("fact-edit-id").value;
  const content = document.getElementById("fact-edit-content").value.trim();
  const category = document.getElementById("fact-edit-category").value.trim();
  const priority = document.getElementById("fact-edit-priority").value;
  const keywordsRaw = document.getElementById("fact-edit-keywords").value;
  const trigger_keywords = keywordsRaw.split(",").map(k => k.trim()).filter(Boolean);
  if (!content) { showBanner("Fact text is required.", "warning"); return; }
  closeModal("fact-edit-modal");

  try {
    if (id) {
      // Update existing fact via PATCH
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, category, priority, trigger_keywords }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const saved = await res.json();
      _facts = _facts.map(f => f.id === id ? saved : f);
    } else {
      // Add new fact by appending to the bulk list (priority/keywords applied via PATCH after)
      const all = _facts.map(f => f.content).concat([content]);
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facts: all }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _facts = await res.json();
      // Apply category, priority, keywords to the new fact (last one)
      if (_facts.length) {
        const newFact = _facts[_facts.length - 1];
        const pRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts/${newFact.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, priority, trigger_keywords }),
        });
        if (pRes.ok) {
          const patched = await pRes.json();
          _facts = _facts.map(f => f.id === patched.id ? patched : f);
        }
      }
    }
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteFact(factId) {
  showConfirm("Delete this world fact?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts/${factId}`, { method: "DELETE" });
    _facts = _facts.filter(f => f.id !== factId);
    renderAll();
  });
}

// ── Scene transcript viewer ───────────────────────────────────────────────────

function viewSceneTranscript(scene) {
  const title = scene.title
    ? `Scene ${scene.scene_number} — ${scene.title}`
    : `Scene ${scene.scene_number}`;
  document.getElementById("transcript-modal-title").textContent = title;

  const body = document.getElementById("transcript-body");
  body.innerHTML = "";

  if (!scene.turns || !scene.turns.length) {
    body.innerHTML = '<p class="muted">No turns recorded for this scene.</p>';
  } else {
    scene.turns.forEach(t => {
      const div = document.createElement("div");
      div.className = `transcript-turn transcript-${t.role}`;
      const label = t.role === "user" ? "Player" : "Narrator";
      div.innerHTML = `<div class="transcript-role">${label}</div><div class="transcript-content">${escHtml(t.content)}</div>`;
      body.appendChild(div);
    });
  }

  if (scene.confirmed_summary) {
    const sum = document.createElement("div");
    sum.className = "transcript-summary";
    sum.innerHTML = `<div class="transcript-role">Scene Summary</div><div class="transcript-content">${escHtml(scene.confirmed_summary)}</div>`;
    body.appendChild(sum);
  }

  openModal("transcript-modal");
}

// ── Chronicle editing ─────────────────────────────────────────────────────────

function openChronicleEdit(entryId, content) {
  document.getElementById("chronicle-edit-id").value = entryId;
  document.getElementById("chronicle-edit-textarea").value = content;
  openModal("chronicle-edit-modal");
}

async function saveChronicleEdit() {
  const id = document.getElementById("chronicle-edit-id").value;
  const content = document.getElementById("chronicle-edit-textarea").value.trim();
  if (!content) { showBanner("Chronicle content cannot be empty.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/chronicle/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    _chronicle = _chronicle.map(e => e.id === id ? updated : e);
    closeModal("chronicle-edit-modal");
    renderChronicle();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteChronicleEntry(entryId) {
  showConfirm("Delete this chronicle entry? This cannot be undone.", async () => {
    try {
      const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/chronicle/${entryId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _chronicle = _chronicle.filter(e => e.id !== entryId);
      renderChronicle();
    } catch (e) { showBanner(`Delete failed: ${e.message}`, "error"); }
  });
}

// ── Chronicle compression ──────────────────────────────────────────────────────

function openCompressChronicle() {
  const list = document.getElementById("compress-entry-list");
  list.innerHTML = "";
  _chronicle.forEach(e => {
    const rangeLabel = e.scene_range_start === e.scene_range_end
      ? `Scene ${e.scene_range_start}`
      : `Scenes ${e.scene_range_start}–${e.scene_range_end}`;
    const label = document.createElement("label");
    label.className = "compress-entry-label";
    label.innerHTML = `
      <input type="checkbox" class="compress-chk" value="${e.id}">
      <span class="compress-range">${rangeLabel}</span>
      <span class="muted compress-preview">${escHtml((e.content || "").substring(0, 80))}${e.content?.length > 80 ? "…" : ""}</span>
    `;
    list.appendChild(label);
  });
  document.getElementById("compress-loading").style.display = "none";
  openModal("compress-modal");
}

async function runCompress() {
  const checked = [...document.querySelectorAll(".compress-chk:checked")].map(c => c.value);
  if (checked.length < 2) { showBanner("Select at least 2 entries to compress.", "warning"); return; }

  document.getElementById("compress-loading").style.display = "";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/chronicle/compress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: checked.join("\n") }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const merged = await res.json();
    // Replace selected entries with the merged one in local state
    _chronicle = _chronicle.filter(e => !checked.includes(e.id));
    _chronicle.push(merged);
    _chronicle.sort((a, b) => a.scene_range_start - b.scene_range_start);
    closeModal("compress-modal");
    renderChronicle();
    showBanner("Chronicle entries compressed.", "success");
  } catch (e) { showBanner(`Compression failed: ${e.message}`, "error"); }
  finally { document.getElementById("compress-loading").style.display = "none"; }
}

// ── NPC list renderer ─────────────────────────────────────────────────────────

const NPC_STATUS_LABELS = {
  active: "", fled: "Fled", imprisoned: "Imprisoned", transformed: "Transformed", dead: "Dead"
};

function renderNpcList() {
  const container = document.getElementById("npcs-list");
  container.innerHTML = "";
  if (!_npcs.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">None yet.</div>';
    return;
  }
  _npcs.forEach(npc => {
    const div = document.createElement("div");
    div.className = "entity-card";
    const status = npc.status || "active";
    const statusLabel = NPC_STATUS_LABELS[status] || status;
    const statusBadge = status !== "active"
      ? `<span class="npc-status-badge npc-status-${status}">${statusLabel}</span>` : "";
    const sub = npc.role || "";
    div.innerHTML = `
      <div class="entity-card-row">
        <div style="display:flex;align-items:center;gap:10px">
          <img class="npc-portrait-avatar${npc.portrait_image ? "" : " hidden"}"
               src="${npc.portrait_image ? escHtml(npc.portrait_image) : ""}"
               data-npc-avatar="${npc.id}"
               alt="${escHtml(npc.name)}">
          <div>
            <div class="entity-name">${escHtml(npc.name)} ${statusBadge}</div>
            ${sub ? `<div class="entity-sub muted">${escHtml(sub.substring(0, 80))}${sub.length > 80 ? "…" : ""}</div>` : ""}
          </div>
        </div>
        <div style="display:flex;gap:4px">
          <button class="btn-icon" title="Generate portrait" data-action="img">🎨</button>
          <button class="btn-icon" title="Edit" data-action="edit">✎</button>
        </div>
      </div>
    `;
    div.querySelector('[data-action="edit"]').addEventListener("click", () => openEditNpc(npc));
    div.querySelector('[data-action="img"]').addEventListener("click", () =>
      openImgGen("npc", { npcId: npc.id, npcName: npc.name }));
    const avatarImg = div.querySelector("[data-npc-avatar]");
    if (avatarImg && npc.portrait_image) {
      avatarImg.addEventListener("click", () => openPortraitLightbox(npc.portrait_image, npc.name));
    }
    container.appendChild(div);
  });
}

// ── NPC Relationship list renderer ────────────────────────────────────────────

function renderRelationshipsList() {
  const container = document.getElementById("relationships-list");
  container.innerHTML = "";
  if (!_relationships.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">None yet.</div>';
    return;
  }
  const npcMap = Object.fromEntries(_npcs.map(n => [n.id, n.name]));
  _relationships.forEach(r => {
    const div = document.createElement("div");
    div.className = "entity-card";
    const nameA = npcMap[r.npc_id_a] || r.npc_id_a;
    const nameB = npcMap[r.npc_id_b] || r.npc_id_b;
    const sub = r.dynamic || "";
    div.innerHTML = `
      <div class="entity-card-row">
        <div>
          <div class="entity-name">${escHtml(nameA)} ↔ ${escHtml(nameB)}</div>
          ${sub ? `<div class="entity-sub muted">${escHtml(sub.substring(0, 80))}</div>` : ""}
        </div>
        <button class="btn-icon" title="Edit">✎</button>
      </div>
    `;
    div.querySelector("button").addEventListener("click", () => openEditRelationship(r));
    container.appendChild(div);
  });
}

// ── NPC editor ────────────────────────────────────────────────────────────────

// prefill: optional data to pre-populate fields (from card import)
// portrait: optional data URL to set as portrait after save
function openEditNpc(npc, prefill, portrait) {
  const data = prefill || npc || {};
  document.getElementById("npc-modal-title").textContent = npc ? "Edit NPC" : (prefill ? "Import NPC" : "New NPC");
  // Reset generate strip
  document.getElementById("npc-generate-desc").value = "";
  const genStatus = document.getElementById("npc-generate-status");
  genStatus.textContent = "";
  genStatus.style.color = "";
  document.getElementById("npc-id").value = npc?.id || "";
  document.getElementById("npc-name").value = data.name || "";
  document.getElementById("npc-role").value = data.role || "";
  document.getElementById("npc-gender").value = data.gender || "";
  document.getElementById("npc-age").value = data.age || "";
  document.getElementById("npc-appearance").value = data.appearance || "";
  document.getElementById("npc-personality").value = data.personality || "";
  document.getElementById("npc-rel").value = data.relationship_to_player || "";
  document.getElementById("npc-loc").value = data.current_location || "";
  document.getElementById("npc-state").value = data.current_state || "";
  document.getElementById("npc-status").value = npc?.status || "active";
  document.getElementById("npc-status-reason").value = npc?.status_reason || "";
  document.getElementById("npc-short-goal").value = data.short_term_goal || "";
  document.getElementById("npc-long-goal").value = data.long_term_goal || "";
  document.getElementById("npc-secrets").value = npc?.secrets || "";
  document.getElementById("npc-history").value = npc?.history_with_player || "";
  document.getElementById("npc-delete-btn").style.display = npc ? "" : "none";
  // Store pending portrait for post-save application
  document.getElementById("npc-modal").__pendingPortrait = portrait || null;

  // Render forms section
  _renderNpcForms(npc?.forms || [], npc?.active_form || "");

  // Render dev log
  const logList = document.getElementById("npc-dev-log-list");
  logList.innerHTML = "";
  (npc?.dev_log || []).forEach(entry => {
    const row = document.createElement("div");
    row.className = "dev-log-entry";
    const label = entry.scene_number ? `Scene ${entry.scene_number}: ` : "";
    row.textContent = `${label}${entry.note}`;
    logList.appendChild(row);
  });

  openModal("npc-modal");
}

async function generateNpc() {
  const desc = document.getElementById("npc-generate-desc").value.trim();
  if (!desc) {
    showBanner("Enter a description first.", "warning");
    document.getElementById("npc-generate-desc").focus();
    return;
  }
  const status = document.getElementById("npc-generate-status");
  const btn = document.querySelector("#npc-generate-strip .btn-primary");
  status.textContent = "Generating…";
  btn.disabled = true;

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: desc }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const npc = await res.json();

    // Populate fields — only overwrite fields that are currently empty
    const fill = (id, val) => {
      const el = document.getElementById(id);
      if (el && !el.value.trim() && val) el.value = val;
    };
    // Name and role: always fill if AI returned them and field is blank
    fill("npc-name", npc.name);
    fill("npc-role", npc.role);
    fill("npc-gender", npc.gender);
    fill("npc-age", npc.age);
    fill("npc-appearance", npc.appearance);
    fill("npc-personality", npc.personality);
    fill("npc-rel", npc.relationship_to_player);
    fill("npc-loc", npc.current_location);
    fill("npc-state", npc.current_state);
    fill("npc-short-goal", npc.short_term_goal);
    fill("npc-long-goal", npc.long_term_goal);
    fill("npc-secrets", npc.secrets);

    status.textContent = "✓ Fields filled — review and save.";
    status.style.color = "var(--green)";
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    status.style.color = "var(--red)";
  } finally {
    btn.disabled = false;
  }
}

function openNpcDevLogAdd() {
  _editingNpcId = document.getElementById("npc-id").value;
  if (!_editingNpcId) { showBanner("Save the NPC first before adding log entries.", "warning"); return; }
  document.getElementById("npc-devlog-note").value = "";
  document.getElementById("npc-devlog-scene").value = "0";
  openModal("npc-devlog-modal");
}

async function saveNpcDevLog() {
  const note = document.getElementById("npc-devlog-note").value.trim();
  const scene_number = parseInt(document.getElementById("npc-devlog-scene").value) || 0;
  if (!note) { showBanner("Note is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/${_editingNpcId}/dev-log`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, scene_number }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    _npcs = _npcs.map(n => n.id === updated.id ? updated : n);
    closeModal("npc-devlog-modal");
    // Refresh the dev log display inside the still-open NPC modal
    const logList = document.getElementById("npc-dev-log-list");
    logList.innerHTML = "";
    (updated.dev_log || []).forEach(entry => {
      const row = document.createElement("div");
      row.className = "dev-log-entry";
      const label = entry.scene_number ? `Scene ${entry.scene_number}: ` : "";
      row.textContent = `${label}${entry.note}`;
      logList.appendChild(row);
    });
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

async function saveNpc() {
  const id = document.getElementById("npc-id").value;
  const body = {
    id: id || null,
    name: document.getElementById("npc-name").value.trim(),
    role: document.getElementById("npc-role").value.trim(),
    gender: document.getElementById("npc-gender").value.trim(),
    age: document.getElementById("npc-age").value.trim(),
    appearance: document.getElementById("npc-appearance").value.trim(),
    personality: document.getElementById("npc-personality").value.trim(),
    relationship_to_player: document.getElementById("npc-rel").value.trim(),
    current_location: document.getElementById("npc-loc").value.trim(),
    current_state: document.getElementById("npc-state").value.trim(),
    status: document.getElementById("npc-status").value,
    status_reason: document.getElementById("npc-status-reason").value.trim(),
    short_term_goal: document.getElementById("npc-short-goal").value.trim(),
    long_term_goal: document.getElementById("npc-long-goal").value.trim(),
    secrets: document.getElementById("npc-secrets").value.trim(),
    history_with_player: document.getElementById("npc-history").value.trim(),
    forms: _getNpcFormsFromModal(),
    active_form: document.getElementById("npc-active-form").value || null,
    is_alive: document.getElementById("npc-status").value !== "dead",
  };
  if (!body.name) { showBanner("NPC name is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const saved = await res.json();
    // Apply pending portrait from card import if present
    const pendingPortrait = document.getElementById("npc-modal").__pendingPortrait;
    if (pendingPortrait) {
      document.getElementById("npc-modal").__pendingPortrait = null;
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/${saved.id}/portrait`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_url: pendingPortrait }),
      });
      saved.portrait_image = pendingPortrait;
    }
    _npcs = _npcs.filter(n => n.id !== saved.id).concat([saved]);
    _npcs.sort((a, b) => a.name.localeCompare(b.name));
    closeModal("npc-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteNpc() {
  const id = document.getElementById("npc-id").value;
  if (!id) return;
  showConfirm("Delete this NPC?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/${id}`, { method: "DELETE" });
    _npcs = _npcs.filter(n => n.id !== id);
    _relationships = _relationships.filter(r => r.npc_id_a !== id && r.npc_id_b !== id);
    closeModal("npc-modal");
    renderAll();
  });
}

// ── NPC Forms management ─────────────────────────────────────────────────────

// Internal state: array of form objects being edited in the NPC modal
let _modalForms = [];

function _renderNpcForms(forms, activeForm) {
  _modalForms = forms ? forms.map(f => ({ ...f })) : [];

  // Rebuild active-form dropdown
  const sel = document.getElementById("npc-active-form");
  sel.innerHTML = '<option value="">(base form)</option>';
  _modalForms.forEach(f => {
    const opt = document.createElement("option");
    opt.value = f.label;
    opt.textContent = f.label;
    sel.appendChild(opt);
  });
  sel.value = activeForm || "";

  // Rebuild forms list
  const list = document.getElementById("npc-forms-list");
  list.innerHTML = "";
  _modalForms.forEach((f, i) => {
    const row = document.createElement("div");
    row.className = "npc-form-entry";
    row.innerHTML = `
      <span class="npc-form-label">${f.label}</span>
      <span class="npc-form-meta">${f.appearance ? f.appearance.slice(0, 60) + (f.appearance.length > 60 ? "…" : "") : ""}</span>
      <div class="npc-form-actions">
        <button type="button" class="btn-sm" onclick="openEditNpcForm(${i})">Edit</button>
        <button type="button" class="btn-sm btn-danger" onclick="deleteNpcForm(${i})">Delete</button>
      </div>`;
    list.appendChild(row);
  });
}

function _getNpcFormsFromModal() {
  return _modalForms.map(f => ({ ...f }));
}

function openAddNpcForm() {
  _openNpcFormModal(null);
}

function openEditNpcForm(index) {
  _openNpcFormModal(index);
}

function _openNpcFormModal(index) {
  const f = index !== null ? _modalForms[index] : null;
  document.getElementById("npc-form-modal-title").textContent = f ? "Edit Form" : "Add Form";
  document.getElementById("npc-form-index").value = index !== null ? index : "";
  document.getElementById("npc-form-label").value = f?.label || "";
  document.getElementById("npc-form-appearance").value = f?.appearance || "";
  document.getElementById("npc-form-personality").value = f?.personality || "";
  document.getElementById("npc-form-state").value = f?.current_state || "";
  document.getElementById("npc-form-scene").value = f?.scene_introduced ?? "";
  openModal("npc-form-modal");
}

function saveNpcForm() {
  const label = document.getElementById("npc-form-label").value.trim();
  if (!label) { showBanner("Form label is required.", "warning"); return; }
  const indexRaw = document.getElementById("npc-form-index").value;
  const form = {
    label,
    appearance: document.getElementById("npc-form-appearance").value.trim(),
    personality: document.getElementById("npc-form-personality").value.trim(),
    current_state: document.getElementById("npc-form-state").value.trim(),
    scene_introduced: document.getElementById("npc-form-scene").value ? parseInt(document.getElementById("npc-form-scene").value) : null,
  };
  if (indexRaw !== "") {
    _modalForms[parseInt(indexRaw)] = form;
  } else {
    _modalForms.push(form);
  }
  const currentActive = document.getElementById("npc-active-form").value;
  _renderNpcForms(_modalForms, currentActive);
  closeModal("npc-form-modal");
}

function deleteNpcForm(index) {
  showConfirm("Delete this form?", () => {
    _modalForms.splice(index, 1);
    const currentActive = document.getElementById("npc-active-form").value;
    _renderNpcForms(_modalForms, currentActive);
  });
}

// ── NPC Relationship editor ───────────────────────────────────────────────────

function openEditRelationship(rel) {
  document.getElementById("rel-modal-title").textContent = rel ? "Edit Relationship" : "New Relationship";
  document.getElementById("rel-id").value = rel?.id || "";
  document.getElementById("rel-dynamic").value = rel?.dynamic || "";
  document.getElementById("rel-trust").value = rel?.trust || "";
  document.getElementById("rel-hostility").value = rel?.hostility || "";
  document.getElementById("rel-history").value = rel?.history || "";
  document.getElementById("rel-delete-btn").style.display = rel ? "" : "none";

  // Populate NPC selects
  const selA = document.getElementById("rel-npc-a");
  const selB = document.getElementById("rel-npc-b");
  selA.innerHTML = "";
  selB.innerHTML = "";
  _npcs.forEach(n => {
    selA.appendChild(new Option(n.name, n.id));
    selB.appendChild(new Option(n.name, n.id));
  });
  if (rel) {
    selA.value = rel.npc_id_a;
    selB.value = rel.npc_id_b;
  }

  openModal("rel-modal");
}

async function saveRelationship() {
  const id = document.getElementById("rel-id").value;
  const npc_id_a = document.getElementById("rel-npc-a").value;
  const npc_id_b = document.getElementById("rel-npc-b").value;
  if (!npc_id_a || !npc_id_b) { showBanner("Select both NPCs.", "warning"); return; }
  if (npc_id_a === npc_id_b) { showBanner("A relationship must be between two different NPCs.", "warning"); return; }
  const body = {
    id: id || null,
    npc_id_a, npc_id_b,
    dynamic: document.getElementById("rel-dynamic").value.trim(),
    trust: document.getElementById("rel-trust").value.trim(),
    hostility: document.getElementById("rel-hostility").value.trim(),
    history: document.getElementById("rel-history").value.trim(),
  };
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npc-relationships`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const saved = await res.json();
    _relationships = _relationships.filter(r => r.id !== saved.id).concat([saved]);
    closeModal("rel-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteRelationship() {
  const id = document.getElementById("rel-id").value;
  if (!id) return;
  showConfirm("Delete this relationship?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npc-relationships/${id}`, { method: "DELETE" });
    _relationships = _relationships.filter(r => r.id !== id);
    closeModal("rel-modal");
    renderAll();
  });
}

// ── Place editor ──────────────────────────────────────────────────────────────

function openEditPlace(place) {
  document.getElementById("place-modal-title").textContent = place ? "Edit Place" : "New Place";
  document.getElementById("place-id").value = place?.id || "";
  document.getElementById("place-name").value = place?.name || "";
  document.getElementById("place-desc").value = place?.description || "";
  document.getElementById("place-state").value = place?.current_state || "";
  document.getElementById("place-delete-btn").style.display = place ? "" : "none";
  openModal("place-modal");
}

async function savePlace() {
  const id = document.getElementById("place-id").value;
  const body = {
    id: id || null,
    name: document.getElementById("place-name").value.trim(),
    description: document.getElementById("place-desc").value.trim(),
    current_state: document.getElementById("place-state").value.trim(),
  };
  if (!body.name) { showBanner("Place name is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const saved = await res.json();
    _places = _places.filter(p => p.id !== saved.id).concat([saved]);
    _places.sort((a, b) => a.name.localeCompare(b.name));
    closeModal("place-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deletePlace() {
  const id = document.getElementById("place-id").value;
  if (!id) return;
  showConfirm("Delete this place?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/places/${id}`, { method: "DELETE" });
    _places = _places.filter(p => p.id !== id);
    closeModal("place-modal");
    renderAll();
  });
}

// ── Thread editor ─────────────────────────────────────────────────────────────

function openEditThread(thread) {
  document.getElementById("thread-modal-title").textContent = thread ? "Edit Thread" : "New Thread";
  document.getElementById("thread-id").value = thread?.id || "";
  document.getElementById("thread-title").value = thread?.title || "";
  document.getElementById("thread-desc").value = thread?.description || "";
  document.getElementById("thread-status").value = thread?.status || "active";
  document.getElementById("thread-resolution").value = thread?.resolution || "";
  document.getElementById("thread-delete-btn").style.display = thread ? "" : "none";
  openModal("thread-modal");
}

async function saveThread() {
  const id = document.getElementById("thread-id").value;
  const body = {
    id: id || null,
    title: document.getElementById("thread-title").value.trim(),
    description: document.getElementById("thread-desc").value.trim(),
    status: document.getElementById("thread-status").value,
    resolution: document.getElementById("thread-resolution").value.trim(),
  };
  if (!body.title) { showBanner("Thread title is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const saved = await res.json();
    _threads = _threads.filter(t => t.id !== saved.id).concat([saved]);
    closeModal("thread-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteThread() {
  const id = document.getElementById("thread-id").value;
  if (!id) return;
  showConfirm("Delete this thread?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads/${id}`, { method: "DELETE" });
    _threads = _threads.filter(t => t.id !== id);
    closeModal("thread-modal");
    renderAll();
  });
}

// ── Faction editor ────────────────────────────────────────────────────────────

function openEditFaction(faction) {
  document.getElementById("faction-modal-title").textContent = faction ? "Edit Faction" : "New Faction";
  document.getElementById("faction-id").value = faction?.id || "";
  document.getElementById("faction-name").value = faction?.name || "";
  document.getElementById("faction-desc").value = faction?.description || "";
  document.getElementById("faction-goals").value = faction?.goals || "";
  document.getElementById("faction-methods").value = faction?.methods || "";
  document.getElementById("faction-standing").value = faction?.standing_with_player || "";
  document.getElementById("faction-rel-notes").value = faction?.relationship_notes || "";
  document.getElementById("faction-delete-btn").style.display = faction ? "" : "none";
  openModal("faction-modal");
}

async function saveFaction() {
  const id = document.getElementById("faction-id").value;
  const body = {
    id: id || null,
    name: document.getElementById("faction-name").value.trim(),
    description: document.getElementById("faction-desc").value.trim(),
    goals: document.getElementById("faction-goals").value.trim(),
    methods: document.getElementById("faction-methods").value.trim(),
    standing_with_player: document.getElementById("faction-standing").value.trim(),
    relationship_notes: document.getElementById("faction-rel-notes").value.trim(),
  };
  if (!body.name) { showBanner("Faction name is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/factions`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const saved = await res.json();
    _factions = _factions.filter(f => f.id !== saved.id).concat([saved]);
    closeModal("faction-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function deleteFaction() {
  const id = document.getElementById("faction-id").value;
  if (!id) return;
  showConfirm("Delete this faction?", async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/factions/${id}`, { method: "DELETE" });
    _factions = _factions.filter(f => f.id !== id);
    closeModal("faction-modal");
    renderAll();
  });
}

// ── PC editor ─────────────────────────────────────────────────────────────────

function openEditPc() {
  document.getElementById("edit-pc-name").value = _pc?.name || "";
  document.getElementById("edit-pc-role").value = _pc?.how_seen || "";
  document.getElementById("edit-pc-appearance").value = _pc?.appearance || "";
  document.getElementById("edit-pc-personality").value = _pc?.personality || "";
  document.getElementById("edit-pc-background").value = _pc?.background || "";
  document.getElementById("edit-pc-wants").value = _pc?.wants || "";
  document.getElementById("edit-pc-fears").value = _pc?.fears || "";
  document.getElementById("edit-pc-how-seen").value = _pc?.how_seen || "";
  document.getElementById("sheet-ancestry").value = _sheet?.ancestry || "";
  document.getElementById("sheet-class").value = _sheet?.character_class || "";
  document.getElementById("sheet-level").value = _sheet?.level || 1;
  document.getElementById("sheet-prof").value = _sheet?.proficiency_bonus || 2;
  document.getElementById("sheet-current-hp").value = _sheet?.current_hp || 10;
  document.getElementById("sheet-max-hp").value = _sheet?.max_hp || 10;
  document.getElementById("sheet-temp-hp").value = _sheet?.temp_hp || 0;
  document.getElementById("sheet-ac").value = _sheet?.armor_class || 10;
  document.getElementById("sheet-speed").value = _sheet?.speed || 30;
  const abilities = _sheet?.abilities || {};
  document.getElementById("sheet-str").value = abilities.strength ?? 10;
  document.getElementById("sheet-dex").value = abilities.dexterity ?? 10;
  document.getElementById("sheet-con").value = abilities.constitution ?? 10;
  document.getElementById("sheet-int").value = abilities.intelligence ?? 10;
  document.getElementById("sheet-wis").value = abilities.wisdom ?? 10;
  document.getElementById("sheet-cha").value = abilities.charisma ?? 10;
  document.getElementById("sheet-skills").value = JSON.stringify(_sheet?.skill_modifiers || {}, null, 2);
  document.getElementById("sheet-saves").value = JSON.stringify(_sheet?.save_modifiers || {}, null, 2);
  document.getElementById("sheet-notes").value = _sheet?.notes || "";

  // Render dev log
  const logList = document.getElementById("pc-dev-log-list");
  logList.innerHTML = "";
  (_pc?.dev_log || []).forEach(entry => {
    const row = document.createElement("div");
    row.className = "dev-log-entry";
    const label = entry.scene_number ? `Scene ${entry.scene_number}: ` : "";
    row.textContent = `${label}${entry.note}`;
    logList.appendChild(row);
  });

  openModal("pc-modal");
}

function openPcDevLogAdd() {
  document.getElementById("pc-devlog-note").value = "";
  document.getElementById("pc-devlog-scene").value = "0";
  openModal("pc-devlog-modal");
}

async function savePcDevLog() {
  const note = document.getElementById("pc-devlog-note").value.trim();
  const scene_number = parseInt(document.getElementById("pc-devlog-scene").value) || 0;
  if (!note) { showBanner("Note is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/player-character/dev-log`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, scene_number }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _pc = await res.json();
    closeModal("pc-devlog-modal");
    // Refresh log in still-open PC modal
    const logList = document.getElementById("pc-dev-log-list");
    logList.innerHTML = "";
    (_pc.dev_log || []).forEach(entry => {
      const row = document.createElement("div");
      row.className = "dev-log-entry";
      const label = entry.scene_number ? `Scene ${entry.scene_number}: ` : "";
      row.textContent = `${label}${entry.note}`;
      logList.appendChild(row);
    });
    renderPcCard();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

async function savePc() {
  const body = {
    name: document.getElementById("edit-pc-name").value.trim() || "The Protagonist",
    appearance: document.getElementById("edit-pc-appearance").value.trim(),
    personality: document.getElementById("edit-pc-personality").value.trim(),
    background: document.getElementById("edit-pc-background").value.trim(),
    wants: document.getElementById("edit-pc-wants").value.trim(),
    fears: document.getElementById("edit-pc-fears").value.trim(),
    how_seen: document.getElementById("edit-pc-how-seen").value.trim(),
  };
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/player-character`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    _pc = await res.json();
    let skillModifiers = {};
    let saveModifiers = {};
    try { skillModifiers = JSON.parse(document.getElementById("sheet-skills").value.trim() || "{}"); }
    catch { throw new Error("Skill modifiers must be valid JSON"); }
    try { saveModifiers = JSON.parse(document.getElementById("sheet-saves").value.trim() || "{}"); }
    catch { throw new Error("Save modifiers must be valid JSON"); }
    const sheetRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheet`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: body.name || "Adventurer",
        ancestry: document.getElementById("sheet-ancestry").value.trim(),
        character_class: document.getElementById("sheet-class").value.trim(),
        background: body.background,
        level: parseInt(document.getElementById("sheet-level").value) || 1,
        proficiency_bonus: parseInt(document.getElementById("sheet-prof").value) || 2,
        abilities: {
          strength: parseInt(document.getElementById("sheet-str").value) || 10,
          dexterity: parseInt(document.getElementById("sheet-dex").value) || 10,
          constitution: parseInt(document.getElementById("sheet-con").value) || 10,
          intelligence: parseInt(document.getElementById("sheet-int").value) || 10,
          wisdom: parseInt(document.getElementById("sheet-wis").value) || 10,
          charisma: parseInt(document.getElementById("sheet-cha").value) || 10
        },
        skill_modifiers: skillModifiers,
        save_modifiers: saveModifiers,
        current_hp: parseInt(document.getElementById("sheet-current-hp").value) || 10,
        max_hp: parseInt(document.getElementById("sheet-max-hp").value) || 10,
        temp_hp: parseInt(document.getElementById("sheet-temp-hp").value) || 0,
        armor_class: parseInt(document.getElementById("sheet-ac").value) || 10,
        speed: parseInt(document.getElementById("sheet-speed").value) || 30,
        notes: document.getElementById("sheet-notes").value.trim()
      }),
    });
    if (!sheetRes.ok) throw new Error(`Character sheet save failed: HTTP ${sheetRes.status}`);
    _sheet = await sheetRes.json();
    closeModal("pc-modal");
    renderAll();
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function levelUpPc() {
  if (!_sheet) {
    showBanner("Create the rules sheet first.", "warning");
    return;
  }
  const nextLevel = (_sheet.level || 1) + 1;
  document.getElementById("levelup-target").value = nextLevel;
  document.getElementById("levelup-hp").value = "0";
  document.getElementById("levelup-abilities").value = "{}";
  document.getElementById("levelup-resources").value = "{}";
  document.getElementById("levelup-feature").value = "";
  openModal("levelup-modal");
  setTimeout(() => document.getElementById("levelup-target").focus(), 50);
}

async function applyLevelUp() {
  const targetLevel = parseInt(document.getElementById("levelup-target").value, 10);
  const hitPointGain = parseInt(document.getElementById("levelup-hp").value, 10);
  if (!Number.isFinite(targetLevel) || targetLevel <= (_sheet?.level || 1)) {
    showBanner("Enter a level higher than the current level.", "warning");
    return;
  }
  if (!Number.isFinite(hitPointGain) || hitPointGain < 0) {
    showBanner("HP gain must be zero or greater.", "warning");
    return;
  }
  let abilityIncreases = {}, resourcePoolIncreases = {};
  try {
    abilityIncreases = JSON.parse(document.getElementById("levelup-abilities").value || "{}");
    resourcePoolIncreases = JSON.parse(document.getElementById("levelup-resources").value || "{}");
  } catch {
    showBanner("Ability/resource fields must be valid JSON objects.", "warning");
    return;
  }
  const featureNote = document.getElementById("levelup-feature").value.trim();
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/player/player/level-up`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_level: targetLevel,
        hit_point_gain: hitPointGain,
        ability_increases: abilityIncreases,
        resource_pool_increases: resourcePoolIncreases,
        feature_note: featureNote,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _sheet = data.sheet;
    closeModal("levelup-modal");
    openEditPc();
    renderAll();
    showBanner(data.summary || `Leveled to ${targetLevel}.`, "success");
  } catch (e) {
    showBanner(`Level up failed: ${e.message}`, "error");
  }
}

async function quickBuildPc() {
  try {
    const optionsRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/quick-build/options`);
    const options = await optionsRes.json().catch(() => ({}));
    if (!optionsRes.ok) throw new Error(options.detail || `HTTP ${optionsRes.status}`);

    // Pre-fill and show modal
    document.getElementById("qb-name").value = _pc?.name || _sheet?.name || "Adventurer";
    document.getElementById("qb-class").value = _sheet?.character_class?.toLowerCase() || "fighter";
    document.getElementById("qb-ancestry").value = _sheet?.ancestry?.toLowerCase() || "human";
    document.getElementById("qb-background").value = _sheet?.background?.toLowerCase() || "wanderer";
    document.getElementById("qb-class-hint").textContent = (options.classes || []).join(" / ");
    document.getElementById("qb-ancestry-hint").textContent = (options.ancestries || []).join(" / ");
    document.getElementById("qb-background-hint").textContent = (options.backgrounds || []).join(" / ");

    openModal("quickbuild-modal");
    setTimeout(() => document.getElementById("qb-name").focus(), 50);
  } catch (e) {
    showBanner(`Quick build failed: ${e.message}`, "error");
  }
}

async function applyQuickBuild() {
  const name = document.getElementById("qb-name").value.trim();
  const characterClass = document.getElementById("qb-class").value.trim().toLowerCase();
  const ancestry = document.getElementById("qb-ancestry").value.trim().toLowerCase();
  const background = document.getElementById("qb-background").value.trim().toLowerCase();
  if (!name) { showBanner("Character name is required.", "warning"); return; }
  if (!characterClass) { showBanner("Class is required.", "warning"); return; }
  if (!ancestry) { showBanner("Ancestry is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/character-sheets/player/player/quick-build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, character_class: characterClass, ancestry, background, level: 1 }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    _sheet = data.sheet;
    if (data.player_character) _pc = data.player_character;
    closeModal("quickbuild-modal");
    openEditPc();
    renderAll();
    showBanner(data.summary || "Quick build complete.", "success");
  } catch (e) {
    showBanner(`Quick build failed: ${e.message}`, "error");
  }
}

// ── God Prompt ────────────────────────────────────────────────────────────────

let _gpSuggestions = null;

function openGodPrompt() {
  resetGodPrompt();
  openModal("god-prompt-modal");
  setTimeout(() => document.getElementById("god-prompt-instruction").focus(), 50);
}

function resetGodPrompt() {
  _gpSuggestions = null;
  document.getElementById("god-prompt-instruction").value = "";
  document.getElementById("god-prompt-status").textContent = "";
  document.getElementById("god-prompt-run-btn").disabled = false;
  document.getElementById("god-prompt-input-area").classList.remove("hidden");
  document.getElementById("god-prompt-suggestions").classList.add("hidden");
  document.getElementById("god-prompt-footer").classList.add("hidden");
  document.getElementById("god-prompt-note").classList.add("hidden");
}

async function runGodPrompt() {
  const instruction = document.getElementById("god-prompt-instruction").value.trim();
  if (!instruction) { showBanner("Enter an instruction first.", "warning"); return; }

  const btn = document.getElementById("god-prompt-run-btn");
  const status = document.getElementById("god-prompt-status");
  btn.disabled = true;
  status.textContent = "Thinking…";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/god-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    if (!data._parse_ok) {
      status.textContent = "⚠ AI response could not be parsed. Try rephrasing.";
      btn.disabled = false;
      return;
    }

    _gpSuggestions = data;
    _renderGodPromptSuggestions(data);
    document.getElementById("god-prompt-input-area").classList.add("hidden");
    document.getElementById("god-prompt-suggestions").classList.remove("hidden");
    document.getElementById("god-prompt-footer").classList.remove("hidden");
    status.textContent = "";
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    btn.disabled = false;
  }
}

function _gpItem(label, sub, cbClass, idx) {
  return `<label class="wu-item">
    <input type="checkbox" class="${cbClass}" data-index="${idx}" checked>
    <div class="wu-item-text">
      <strong>${escHtml(label)}</strong>
      ${sub ? `<div class="wu-reason muted">${escHtml(sub)}</div>` : ""}
    </div>
  </label>`;
}

function _renderGodPromptSuggestions(d) {
  // Narrative note
  const noteEl = document.getElementById("god-prompt-note");
  if (d.narrative_note) {
    noteEl.textContent = d.narrative_note;
    noteEl.classList.remove("hidden");
  }

  function _populateSection(sectionId, listId, items, renderFn) {
    const section = document.getElementById(sectionId);
    const list = document.getElementById(listId);
    if (items && items.length) {
      list.innerHTML = items.map((item, i) => renderFn(item, i)).join("");
      section.classList.remove("hidden");
    } else {
      section.classList.add("hidden");
    }
  }

  _populateSection("gp-update-npcs-section", "gp-update-npcs-list", d.update_npcs, (u, i) =>
    _gpItem(`${u.npc_name}: set ${u.field} → "${u.new_value}"`, u.reason, "gp-update-npc-cb", i));

  _populateSection("gp-create-npcs-section", "gp-create-npcs-list", d.create_npcs, (u, i) =>
    _gpItem(`Create NPC: ${u.name}${u.role ? ` (${u.role})` : ""}`, u.reason, "gp-create-npc-cb", i));

  _populateSection("gp-delete-npcs-section", "gp-delete-npcs-list", d.delete_npcs, (u, i) =>
    _gpItem(`Delete NPC: ${u.npc_name}`, u.reason, "gp-delete-npc-cb", i));

  _populateSection("gp-create-facts-section", "gp-create-facts-list", d.create_facts, (u, i) =>
    _gpItem(u.content, u.reason, "gp-create-fact-cb", i));

  _populateSection("gp-update-facts-section", "gp-update-facts-list", d.update_facts, (u, i) =>
    _gpItem(`"${u.old_content}" → "${u.new_content}"`, u.reason, "gp-update-fact-cb", i));

  _populateSection("gp-delete-facts-section", "gp-delete-facts-list", d.delete_facts, (u, i) =>
    _gpItem(`Delete fact: "${u.content}"`, u.reason, "gp-delete-fact-cb", i));

  // Threads: combine create + update + delete
  const allThreadItems = [];
  (d.create_threads || []).forEach((u, i) =>
    allThreadItems.push(_gpItem(`Create thread: "${u.title}"`, u.reason, "gp-create-thread-cb", i)));
  (d.update_threads || []).forEach((u, i) =>
    allThreadItems.push(_gpItem(
      `Update "${u.title}"${u.new_status ? ` → ${u.new_status}` : ""}`,
      u.reason, "gp-update-thread-cb", i)));
  (d.delete_threads || []).forEach((u, i) =>
    allThreadItems.push(_gpItem(`Delete thread: "${u.title}"`, u.reason, "gp-delete-thread-cb", i)));

  const threadSection = document.getElementById("gp-threads-section");
  const threadList = document.getElementById("gp-threads-list");
  if (allThreadItems.length) {
    threadList.innerHTML = allThreadItems.join("");
    threadSection.classList.remove("hidden");
  } else {
    threadSection.classList.add("hidden");
  }

  // Quests
  const questItems = [
    ...(d.create_quests || []).map((u, i) =>
      _gpItem(`Create quest: "${u.title}"`, u.reason, "gp-create-quest-cb", i)),
    ...(d.update_quests || []).map((u, i) =>
      _gpItem(`"${u.title}" → ${u.new_status}`, u.reason, "gp-update-quest-cb", i)),
  ];
  const questSection = document.getElementById("gp-quests-section");
  const questList = document.getElementById("gp-quests-list");
  if (questItems.length) {
    questList.innerHTML = questItems.join("");
    questSection.classList.remove("hidden");
  } else {
    questSection.classList.add("hidden");
  }

  // Places
  const placeItems = [
    ...(d.create_places || []).map((u, i) =>
      _gpItem(`Create place: "${u.name}"`, u.reason, "gp-create-place-cb", i)),
    ...(d.update_places || []).map((u, i) =>
      _gpItem(`Update "${u.name}": set ${u.field} → "${u.new_value}"`, u.reason, "gp-update-place-cb", i)),
  ];
  const placeSection = document.getElementById("gp-places-section");
  const placeList = document.getElementById("gp-places-list");
  if (placeItems.length) {
    placeList.innerHTML = placeItems.join("");
    placeSection.classList.remove("hidden");
  } else {
    placeSection.classList.add("hidden");
  }

  // Factions
  const factionItems = [
    ...(d.create_factions || []).map((u, i) =>
      _gpItem(`Create faction: "${u.name}"`, u.reason, "gp-create-faction-cb", i)),
    ...(d.update_factions || []).map((u, i) =>
      _gpItem(`Update "${u.name}": set ${u.field} → "${u.new_value}"`, u.reason, "gp-update-faction-cb", i)),
  ];
  const factionSection = document.getElementById("gp-factions-section");
  const factionList = document.getElementById("gp-factions-list");
  if (factionItems.length) {
    factionList.innerHTML = factionItems.join("");
    factionSection.classList.remove("hidden");
  } else {
    factionSection.classList.add("hidden");
  }
}

async function applyGodPrompt() {
  if (!_gpSuggestions) return;
  const d = _gpSuggestions;
  const applyBtn = document.querySelector("#god-prompt-footer .btn-primary");
  applyBtn.disabled = true;
  applyBtn.textContent = "Applying…";

  const checked = (cls) =>
    [...document.querySelectorAll(`.${cls}:checked`)].map(cb => parseInt(cb.dataset.index));

  try {
    // Update NPCs
    for (const i of checked("gp-update-npc-cb")) {
      const u = d.update_npcs[i];
      const npc = _npcs.find(n => n.id === u.npc_id);
      if (!npc) continue;
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...npc, [u.field]: u.new_value }),
      }).catch(() => {});
    }

    // Create NPCs
    for (const i of checked("gp-create-npc-cb")) {
      const u = d.create_npcs[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(u),
      }).catch(() => {});
    }

    // Delete NPCs
    for (const i of checked("gp-delete-npc-cb")) {
      const u = d.delete_npcs[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/${u.npc_id}`, { method: "DELETE" }).catch(() => {});
    }

    // Create facts
    const newFactContents = checked("gp-create-fact-cb").map(i => d.create_facts[i].content);
    if (newFactContents.length) {
      const existingContents = _facts.map(f => f.content);
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facts: [...existingContents, ...newFactContents] }),
      }).catch(() => {});
    }

    // Update facts (PATCH individual fact)
    for (const i of checked("gp-update-fact-cb")) {
      const u = d.update_facts[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts/${u.fact_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: u.new_content }),
      }).catch(() => {});
    }

    // Delete facts
    for (const i of checked("gp-delete-fact-cb")) {
      const u = d.delete_facts[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts/${u.fact_id}`, { method: "DELETE" }).catch(() => {});
    }

    // Create threads
    for (const i of checked("gp-create-thread-cb")) {
      const u = d.create_threads[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: u.title, description: u.description, status: "active" }),
      }).catch(() => {});
    }

    // Update threads
    for (const i of checked("gp-update-thread-cb")) {
      const u = d.update_threads[i];
      const thread = _threads.find(t => t.id === u.thread_id);
      if (!thread) continue;
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...thread,
          description: u.description || thread.description,
          status: u.new_status || thread.status,
          resolution: u.resolution || thread.resolution,
        }),
      }).catch(() => {});
    }

    // Delete threads
    for (const i of checked("gp-delete-thread-cb")) {
      const u = d.delete_threads[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads/${u.thread_id}`, { method: "DELETE" }).catch(() => {});
    }

    // Create quests
    for (const i of checked("gp-create-quest-cb")) {
      const u = d.create_quests[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/quests`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: u.title, description: u.description, giver_npc_name: u.giver_npc_name || "", importance: u.importance || "medium", status: "active" }),
      }).catch(() => {});
    }

    // Update quests (fetch current quest state to merge)
    const questsToUpdate = checked("gp-update-quest-cb").map(i => d.update_quests[i]);
    if (questsToUpdate.length) {
      const allQuests = await fetch(`/api/campaigns/${CAMPAIGN_ID}/quests`).then(r => r.json()).catch(() => []);
      for (const u of questsToUpdate) {
        const quest = allQuests.find(q => q.id === u.quest_id);
        if (!quest) continue;
        await fetch(`/api/campaigns/${CAMPAIGN_ID}/quests`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...quest, status: u.new_status }),
        }).catch(() => {});
      }
    }

    // Create places
    for (const i of checked("gp-create-place-cb")) {
      const u = d.create_places[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: u.name, description: u.description, current_state: u.current_state || "" }),
      }).catch(() => {});
    }

    // Update places
    for (const i of checked("gp-update-place-cb")) {
      const u = d.update_places[i];
      const place = _places.find(p => p.id === u.place_id);
      if (!place) continue;
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...place, [u.field]: u.new_value }),
      }).catch(() => {});
    }

    // Create factions
    for (const i of checked("gp-create-faction-cb")) {
      const u = d.create_factions[i];
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/factions`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: u.name, description: u.description, goals: u.goals || "", standing_with_player: u.standing_with_player || "" }),
      }).catch(() => {});
    }

    // Update factions
    for (const i of checked("gp-update-faction-cb")) {
      const u = d.update_factions[i];
      const faction = _factions.find(f => f.id === u.faction_id);
      if (!faction) continue;
      await fetch(`/api/campaigns/${CAMPAIGN_ID}/factions`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...faction, [u.field]: u.new_value }),
      }).catch(() => {});
    }

    closeModal("god-prompt-modal");
    await loadWorld();
    showBanner("God Prompt applied successfully.", "success");
  } catch (e) {
    showBanner(`Apply failed: ${e.message}`, "error");
    applyBtn.disabled = false;
    applyBtn.textContent = "Apply Selected";
  }
}

// ── Search ────────────────────────────────────────────────────────────────────

let _searchTimer = null;

function openSearchModal() {
  document.getElementById("search-input").value = "";
  document.getElementById("search-results").innerHTML =
    '<div class="muted" style="font-size:0.85rem">Type to search across all scene turns.</div>';
  openModal("search-modal");
  setTimeout(() => document.getElementById("search-input").focus(), 50);
}

function runSearch() {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(_doSearch, 250);
}

async function _doSearch() {
  const q = document.getElementById("search-input").value.trim();
  const container = document.getElementById("search-results");
  if (q.length < 2) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">Type at least 2 characters.</div>';
    return;
  }
  container.innerHTML = '<div class="muted" style="font-size:0.85rem">Searching…</div>';
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const results = await res.json();
    if (!results.length) {
      container.innerHTML = '<div class="muted" style="font-size:0.85rem">No matches found.</div>';
      return;
    }
    container.innerHTML = "";
    results.forEach(r => {
      const div = document.createElement("div");
      div.className = "search-result";
      const scene = r.scene_title ? `Scene ${r.scene_number}: ${r.scene_title}` : `Scene ${r.scene_number}`;
      const role = r.role === "user" ? "Player" : "Narrator";
      // Highlight the match within the excerpt
      const before = escHtml(r.excerpt.slice(0, r.match_pos));
      const match  = escHtml(r.excerpt.slice(r.match_pos, r.match_pos + r.match_len));
      const after  = escHtml(r.excerpt.slice(r.match_pos + r.match_len));
      div.innerHTML = `
        <div class="search-result-meta"><span class="search-scene">${escHtml(scene)}</span> · <span class="muted">${role}</span></div>
        <div class="search-result-excerpt">${before}<mark class="search-highlight">${match}</mark>${after}</div>
      `;
      div.style.cursor = "pointer";
      div.addEventListener("click", () => {
        closeModal("search-modal");
        const sceneObj = _scenes.find(s => s.id === r.scene_id);
        if (sceneObj && !sceneObj.confirmed) {
          window.location.href = `/campaigns/${CAMPAIGN_ID}/play`;
        } else {
          showBanner("That scene is completed — its summary appears in the Chronicle section.", "info");
        }
      });
      container.appendChild(div);
    });
  } catch (e) { container.innerHTML = `<div class="muted">Error: ${escHtml(e.message)}</div>`; }
}

// ── Stats ─────────────────────────────────────────────────────────────────────

async function openStatsModal() {
  document.getElementById("stats-body").innerHTML = '<div class="muted">Loading…</div>';
  openModal("stats-modal");
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/stats`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const s = await res.json();
    document.getElementById("stats-body").innerHTML = `
      <div class="stats-grid">
        <div class="stats-card"><div class="stats-value">${s.scenes_total}</div><div class="stats-label">Scenes Total</div></div>
        <div class="stats-card"><div class="stats-value">${s.scenes_confirmed}</div><div class="stats-label">Confirmed</div></div>
        <div class="stats-card"><div class="stats-value">${s.total_turns}</div><div class="stats-label">Total Turns</div></div>
        <div class="stats-card"><div class="stats-value">${s.total_words.toLocaleString()}</div><div class="stats-label">Words Written</div></div>
        <div class="stats-card"><div class="stats-value">${s.player_words.toLocaleString()}</div><div class="stats-label">Player Words</div></div>
        <div class="stats-card"><div class="stats-value">${s.narrator_words.toLocaleString()}</div><div class="stats-label">Narrator Words</div></div>
        <div class="stats-card"><div class="stats-value">${s.thread_resolution_rate}%</div><div class="stats-label">Thread Resolution</div></div>
        <div class="stats-card"><div class="stats-value">${s.world_fact_count}</div><div class="stats-label">World Facts</div></div>
      </div>
      ${s.top_npcs.length ? `
        <div style="margin-top:16px">
          <div style="font-weight:600;margin-bottom:8px;font-size:0.85rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.05em">Most Active NPCs</div>
          ${s.top_npcs.map(n => `
            <div class="stats-npc-row">
              <span>${escHtml(n.name)}</span>
              <span class="muted">${n.scene_count} scene${n.scene_count !== 1 ? "s" : ""}</span>
            </div>`).join("")}
        </div>` : ""}
    `;
  } catch (e) {
    document.getElementById("stats-body").innerHTML = `<div class="muted">Error: ${escHtml(e.message)}</div>`;
  }
}

// ── Export ────────────────────────────────────────────────────────────────────

function exportMarkdown() {
  window.location.href = `/api/campaigns/${CAMPAIGN_ID}/export/markdown`;
}

function exportJson() {
  window.location.href = `/api/campaigns/${CAMPAIGN_ID}/export/json`;
}

function exportTemplate() {
  window.location.href = `/api/campaigns/${CAMPAIGN_ID}/export/template`;
}

// ── Restore ───────────────────────────────────────────────────────────────────

function openRestoreModal() {
  document.getElementById("restore-file").value = "";
  document.getElementById("restore-status").textContent = "";
  openModal("restore-modal");
}

async function runRestore() {
  const file = document.getElementById("restore-file").files[0];
  const statusEl = document.getElementById("restore-status");
  if (!file) { statusEl.textContent = "Please select a JSON file."; return; }
  statusEl.textContent = "Importing…";
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const res = await fetch("/api/campaigns/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const result = await res.json();
    closeModal("restore-modal");
    showBanner(`Campaign restored as "${result.name}". Redirecting…`, "success");
    setTimeout(() => { window.location.href = `/campaigns/${result.campaign_id}`; }, 1500);
  } catch (e) { statusEl.textContent = `Import failed: ${e.message}`; }
}

// ── Save as template ──────────────────────────────────────────────────────────

function openTemplateModal() {
  document.getElementById("template-name").value = (_campaign?.name || "") + " — Template";
  openModal("template-modal");
  setTimeout(() => document.getElementById("template-name").focus(), 50);
}

async function runSaveTemplate() {
  const name = document.getElementById("template-name").value.trim();
  if (!name) { showBanner("Template name is required.", "warning"); return; }
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/save-as-template`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const result = await res.json();
    closeModal("template-modal");
    showBanner(`Template "${result.name}" created. Open it from the home screen.`, "success");
  } catch (e) { showBanner(`Failed: ${e.message}`, "error"); }
}

// ── Campaign settings / delete ─────────────────────────────────────────────────

function csSync(key, value, decimals) {
  const lbl = document.getElementById(`cs-lbl-${key}`);
  if (lbl) lbl.textContent = decimals > 0 ? parseFloat(value).toFixed(decimals) : value;
}

function csResetDefaults() {
  const defaults = { temperature:0.80, top_p:0.95, top_k:0, min_p:0.05, repeat_penalty:1.10, max_tokens:1024, seed:-1, context_window:32768 };
  for (const [k, v] of Object.entries(defaults)) {
    const el = document.getElementById(`cs-${k}`);
    if (el) { el.value = v; csSync(k, v, ["temperature","top_p","min_p","repeat_penalty"].includes(k) ? 2 : 0); }
  }
}

async function openEditCampaign() {
  // Populate name & model
  document.getElementById("cs-name").value = _campaign?.name || "";

  // Populate model selects (load models if not yet populated)
  const sel = document.getElementById("cs-model");
  const sumSel = document.getElementById("cs-summary-model");
  if (sel.options.length <= 1) {
    try {
      const res = await fetch("/api/models");
      const data = await res.json();
      const models = Array.isArray(data) ? data : (data.models || []);
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.name; opt.textContent = m.name;
        sel.appendChild(opt);
        const opt2 = opt.cloneNode(true);
        sumSel.appendChild(opt2);
      });
    } catch {/* ignore */}
  }
  sel.value = _campaign?.model_name || "";
  sumSel.value = _campaign?.summary_model_name || "";

  // Populate gen settings sliders
  const gs = _campaign?.gen_settings || {};
  const defaults = { temperature:0.80, top_p:0.95, top_k:0, min_p:0.05, repeat_penalty:1.10, max_tokens:1024, seed:-1, context_window:32768 };
  for (const [k, def] of Object.entries(defaults)) {
    const v = gs[k] ?? def;
    const el = document.getElementById(`cs-${k}`);
    if (el) { el.value = v; csSync(k, v, ["temperature","top_p","min_p","repeat_penalty"].includes(k) ? 2 : 0); }
  }

  openModal("campaign-settings-modal");
}

async function saveEditCampaign() {
  const gs = _campaign?.gen_settings || {};
  const body = {
    name:              document.getElementById("cs-name").value.trim() || _campaign?.name,
    model_name:        document.getElementById("cs-model").value || null,
    summary_model_name: document.getElementById("cs-summary-model").value || null,
    temperature:    parseFloat(document.getElementById("cs-temperature").value),
    top_p:          parseFloat(document.getElementById("cs-top_p").value),
    top_k:          parseInt(document.getElementById("cs-top_k").value),
    min_p:          parseFloat(document.getElementById("cs-min_p").value),
    repeat_penalty: parseFloat(document.getElementById("cs-repeat_penalty").value),
    max_tokens:     parseInt(document.getElementById("cs-max_tokens").value),
    seed:           parseInt(document.getElementById("cs-seed").value),
    context_window: parseInt(document.getElementById("cs-context_window").value),
  };
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _campaign = await res.json();
    closeModal("campaign-settings-modal");
    renderAll();
    showBanner("Campaign settings saved.", "success");
  } catch (e) { showBanner(`Save failed: ${e.message}`, "error"); }
}

function confirmDeleteCampaign() {
  showConfirm(`Delete campaign "${_campaign?.name}"? This cannot be undone.`, async () => {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}`, { method: "DELETE" });
    window.location.href = "/";
  });
}

// ── Play navigation ───────────────────────────────────────────────────────────

function startPlay() {
  window.location.href = `/campaigns/${CAMPAIGN_ID}/play?new=1`;
}

// ── Modal helpers ─────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// ── Utility ───────────────────────────────────────────────────────────────────

function showBanner(msg, type = "info") {
  const container = document.getElementById("banner-container");
  const banner = document.createElement("div");
  banner.className = `banner banner-${type}`;
  banner.textContent = msg;
  const close = document.createElement("button");
  close.className = "banner-close";
  close.textContent = "✕";
  close.onclick = () => banner.remove();
  banner.appendChild(close);
  container.innerHTML = "";
  container.appendChild(banner);
  if (type !== "error") setTimeout(() => banner.remove(), 6000);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ── Portrait lightbox ─────────────────────────────────────────────────────────

function openPortraitLightbox(src, name) {
  document.getElementById("portrait-lightbox-img").src = src;
  document.getElementById("portrait-lightbox-img").alt = name || "";
  document.getElementById("portrait-lightbox").classList.remove("hidden");
}

// ── Import NPC from character card ────────────────────────────────────────────

let _importCardData = null;   // parsed card fields
let _importCardPortrait = null; // data URL from PNG
let _importCardResult = null;  // {proposed_npc, contradictions} from backend

function openImportCardModal() {
  resetImportCard();
  // Populate model select
  fetch("/api/models").then(r => r.json()).then(models => {
    const sel = document.getElementById("import-card-model");
    sel.innerHTML = '<option value="">Default model</option>';
    (Array.isArray(models) ? models : (models.models || [])).forEach(m => {
      const o = document.createElement("option");
      o.value = m.name; o.textContent = m.name;
      sel.appendChild(o);
    });
  }).catch(() => {});
  document.getElementById("import-card-modal").classList.remove("hidden");
}

function resetImportCard() {
  _importCardData = null;
  _importCardPortrait = null;
  _importCardResult = null;
  document.getElementById("import-card-file").value = "";
  document.getElementById("import-card-file-info").textContent = "";
  document.getElementById("import-card-context").value = "";
  document.getElementById("import-card-step1").classList.remove("hidden");
  document.getElementById("import-card-step2").classList.add("hidden");
  document.getElementById("import-card-step1-footer").style.display = "";
  document.getElementById("import-card-step2-footer").classList.add("hidden");
}

// Wire up file input after DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("import-card-file")?.addEventListener("change", function () {
    const file = this.files[0];
    if (!file) return;
    const isPng = /\.png$/i.test(file.name) || file.type === "image/png";
    const infoEl = document.getElementById("import-card-file-info");
    infoEl.textContent = `Loading ${file.name}…`;

    if (isPng) {
      let dataUrl = null;
      let cardJson = null;
      const finish = () => {
        if (dataUrl === null || cardJson === null) return;
        if (!cardJson) { infoEl.textContent = `No character data found in ${file.name}.`; return; }
        _importCardData = cardJson;
        _importCardPortrait = dataUrl;
        infoEl.textContent = `Card loaded: ${cardJson.name || file.name} (PNG)`;
      };
      const ur = new FileReader();
      ur.onload = e => { dataUrl = e.target.result; finish(); };
      const br = new FileReader();
      br.onload = e => {
        const parsed = _parsePngCharaForImport(e.target.result);
        cardJson = parsed || false;
        finish();
      };
      ur.readAsDataURL(file);
      br.readAsArrayBuffer(file);
    } else {
      const r = new FileReader();
      r.onload = e => {
        try {
          const data = JSON.parse(e.target.result);
          const card = data.data || data;
          _importCardData = card;
          _importCardPortrait = null;
          infoEl.textContent = `Card loaded: ${card.name || card.char_name || file.name}`;
        } catch {
          infoEl.textContent = "Could not parse file as JSON.";
        }
      };
      r.readAsText(file);
    }
  });
});

function _parsePngCharaForImport(arrayBuffer) {
  try {
    const view = new DataView(arrayBuffer);
    if (view.getUint32(0) !== 0x89504E47) return null;
    let offset = 8;
    while (offset + 12 <= view.byteLength) {
      const length = view.getUint32(offset);
      const type = String.fromCharCode(view.getUint8(offset+4),view.getUint8(offset+5),view.getUint8(offset+6),view.getUint8(offset+7));
      if (type === "tEXt" && length > 0) {
        const data = new Uint8Array(arrayBuffer, offset + 8, length);
        let sep = -1;
        for (let i = 0; i < data.length; i++) { if (data[i] === 0) { sep = i; break; } }
        if (sep !== -1) {
          const keyword = new TextDecoder().decode(data.slice(0, sep));
          if (keyword === "chara") {
            const b64 = new TextDecoder("latin1").decode(data.slice(sep + 1));
            try { const j = JSON.parse(atob(b64)); return j.data || j; } catch { return null; }
          }
        }
      }
      offset += 12 + length;
      if (type === "IEND") break;
    }
  } catch {}
  return null;
}

async function analyseImportCard() {
  if (!_importCardData) {
    showBanner("Please select a character card file first.", "warning");
    return;
  }
  const card = _importCardData;
  const context = document.getElementById("import-card-context").value.trim();
  const model = document.getElementById("import-card-model").value;

  const step1Footer = document.getElementById("import-card-step1-footer");
  step1Footer.innerHTML = '<div class="spinner" style="display:inline-block"></div> <span class="muted">Analysing…</span>';

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/import-card`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: card.name || card.char_name || "Unknown",
        description: card.description || "",
        personality: card.personality || "",
        scenario: card.scenario || "",
        creator_notes: card.creator_notes || "",
        additional_context: context,
        model_name: model || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    _importCardResult = await res.json();
    _showImportCardStep2();
  } catch (e) {
    step1Footer.innerHTML = `
      <button class="btn btn-primary" onclick="analyseImportCard()">✨ Analyse Card</button>
      <button class="btn" onclick="closeModal('import-card-modal')">Cancel</button>`;
    showBanner(`Analysis failed: ${e.message}`, "error");
  }
}

function _showImportCardStep2() {
  const { proposed_npc: npc, contradictions } = _importCardResult;

  // Render NPC preview
  const preview = document.getElementById("import-card-npc-preview");
  const fields = [
    ["Name", npc.name], ["Gender", npc.gender], ["Age", npc.age],
    ["Role", npc.role], ["Appearance", npc.appearance], ["Personality", npc.personality],
    ["Relationship to Player", npc.relationship_to_player],
    ["Current Location", npc.current_location], ["Current State", npc.current_state],
    ["Short-term Goal", npc.short_term_goal], ["Long-term Goal", npc.long_term_goal],
  ].filter(([, v]) => v);
  preview.innerHTML = `<dl>${fields.map(([k, v]) =>
    `<dt>${escHtml(k)}</dt><dd>${escHtml(v)}</dd>`).join("")}</dl>`;

  // Render contradictions
  const cdiv = document.getElementById("import-card-contradictions");
  if (!contradictions || !contradictions.length) {
    cdiv.innerHTML = '<div class="muted" style="font-size:0.85rem">No contradictions detected. This card integrates cleanly with your world.</div>';
  } else {
    cdiv.innerHTML = contradictions.map((c, i) => `
      <div class="import-card-contradiction">
        <label>
          <input type="checkbox" data-contradiction="${i}" checked>
          <div>
            <div class="ic-field">${escHtml(c.field || "")}</div>
            <div class="ic-issue">${escHtml(c.issue || "")}</div>
            <div class="ic-suggested">→ ${escHtml(c.suggested || "")}</div>
          </div>
        </label>
      </div>`).join("");
  }

  document.getElementById("import-card-step1").classList.add("hidden");
  document.getElementById("import-card-step2").classList.remove("hidden");
  document.getElementById("import-card-step1-footer").style.display = "none";
  const s2f = document.getElementById("import-card-step2-footer");
  s2f.classList.remove("hidden");
  s2f.style.display = "flex";
}

function confirmImportCard() {
  const { proposed_npc: npc, contradictions } = _importCardResult;

  // Build the resolved NPC by applying checked adjustments
  const resolved = { ...npc };
  document.querySelectorAll("[data-contradiction]").forEach(cb => {
    if (cb.checked) {
      const i = parseInt(cb.dataset.contradiction);
      const c = contradictions[i];
      if (c && c.field && c.suggested) {
        resolved[c.field] = c.suggested;
      }
    }
  });

  // Close import modal and pre-fill the NPC editor
  closeModal("import-card-modal");
  openEditNpc(null, resolved, _importCardPortrait);
}
