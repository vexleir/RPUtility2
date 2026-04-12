"use strict";

const _THEME_KEY = "rp_theme";
const _THEMES = [
  { id: "dark",     label: "Dark (default)" },
  { id: "midnight", label: "Midnight" },
  { id: "sepia",    label: "Parchment" },
  { id: "forest",   label: "Forest" },
  { id: "light",    label: "Light" },
];

function setTheme(name) {
  document.documentElement.setAttribute("data-theme", name || "dark");
  try { localStorage.setItem(_THEME_KEY, name); } catch(_) {}
  // keep any select in sync
  const sel = document.getElementById("theme-select");
  if (sel) sel.value = name;
}

function _initTheme() {
  let saved = "dark";
  try { saved = localStorage.getItem(_THEME_KEY) || "dark"; } catch(_) {}
  document.documentElement.setAttribute("data-theme", saved);
}

// Apply immediately before any paint
_initTheme();

// ── Shared confirm dialog ──────────────────────────────────────────────────────
// showConfirm(message, onConfirm) — replaces native confirm() with a modal.
// The modal element is created lazily on first use and reused thereafter.
function showConfirm(message, onConfirm) {
  let backdrop = document.getElementById("_shared-confirm-modal");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "_shared-confirm-modal";
    backdrop.className = "modal-backdrop hidden";
    backdrop.innerHTML = `
      <div class="modal" style="max-width:400px">
        <div class="modal-body" style="padding:24px 20px 8px">
          <p id="_confirm-msg" style="margin:0;line-height:1.5"></p>
        </div>
        <div class="modal-footer">
          <button id="_confirm-ok" class="btn btn-danger">Delete</button>
          <button id="_confirm-cancel" class="btn">Cancel</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.addEventListener("click", e => { if (e.target === backdrop) _closeConfirm(); });
  }
  document.getElementById("_confirm-msg").textContent = message;
  const okBtn = document.getElementById("_confirm-ok");
  // Label the confirm button based on message content
  okBtn.textContent = message.toLowerCase().includes("delete") ? "Delete"
    : message.toLowerCase().includes("reopen") ? "Reopen"
    : "Confirm";
  const newOk = okBtn.cloneNode(true); // remove old listeners
  okBtn.replaceWith(newOk);
  newOk.addEventListener("click", () => { _closeConfirm(); onConfirm(); });
  document.getElementById("_confirm-cancel").onclick = _closeConfirm;
  backdrop.classList.remove("hidden");
}

function _closeConfirm() {
  const el = document.getElementById("_shared-confirm-modal");
  if (el) el.classList.add("hidden");
}

// After DOM ready: populate select and sync its value
document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("theme-select");
  if (!sel) return;
  let saved = "dark";
  try { saved = localStorage.getItem(_THEME_KEY) || "dark"; } catch(_) {}
  _THEMES.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.label;
    sel.appendChild(opt);
  });
  sel.value = saved;
});
