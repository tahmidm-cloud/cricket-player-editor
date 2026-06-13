const FORMATS = ["test", "odi", "t20"];
const EDITABLE_FIELDS = [
  "name",
  "fullName",
  "role",
  "battingHand",
  "bowlingHand",
  "bowlingType",
  "bowlingStyle"
];

const LOCAL_SAVE_KEY = "cricketPlayerEditor.localSave.v1";

let originalWrapper = null;
let originalText = "";
let outputMode = "object";
let players = [];
let deletedPlayers = 0;
let loadedFileName = "players.json";
let autoSaveTimer = null;

const el = {
  file: document.getElementById("jsonFile"),
  download: document.getElementById("downloadBtn"),
  saveLocal: document.getElementById("saveLocalBtn"),
  inferBowling: document.getElementById("inferBowlingBtn"),
  loadLocal: document.getElementById("loadLocalBtn"),
  clearLocal: document.getElementById("clearLocalBtn"),
  reset: document.getElementById("resetBtn"),
  status: document.getElementById("fileStatus"),
  localStatus: document.getElementById("localStatus"),
  search: document.getElementById("searchInput"),
  nation: document.getElementById("nationFilter"),
  role: document.getElementById("roleFilter"),
  total: document.getElementById("totalCount"),
  shown: document.getElementById("shownCount"),
  deleted: document.getElementById("deletedCount"),
  list: document.getElementById("playersList"),
  template: document.getElementById("playerCardTemplate")
};

el.file.addEventListener("change", handleFileLoad);
el.download.addEventListener("click", downloadUpdatedJson);
el.saveLocal.addEventListener("click", () => saveLocalCopy(true));
el.inferBowling.addEventListener("click", autoFillAllBowlingFromStyle);
el.loadLocal.addEventListener("click", loadLocalSave);
el.clearLocal.addEventListener("click", clearLocalSave);
el.reset.addEventListener("click", resetLoadedFile);
el.search.addEventListener("input", renderPlayers);
el.nation.addEventListener("change", renderPlayers);
el.role.addEventListener("change", renderPlayers);

updateLocalSaveStatus();

async function handleFileLoad(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  loadedFileName = file.name || "players.json";
  originalText = await file.text();

  try {
    const parsed = JSON.parse(originalText);
    loadDatabase(parsed);
    el.status.textContent = `Loaded ${players.length} players from ${loadedFileName}.`;
    scheduleAutoSave();
  } catch (error) {
    console.error(error);
    el.status.textContent = "That file is not valid JSON. Load a valid players file.";
  }
}

function loadDatabase(parsed) {
  originalWrapper = structuredClone(parsed);
  deletedPlayers = 0;

  if (Array.isArray(parsed)) {
    outputMode = "array";
    players = parsed;
  } else if (parsed && Array.isArray(parsed.players)) {
    outputMode = "object";
    players = parsed.players;
  } else {
    throw new Error("Expected either a player array or an object with players array.");
  }

  players = players.map(normalizePlayerForEditor);

  enableControls();
  rebuildFilters();
  renderPlayers();
}

function enableControls() {
  el.download.disabled = false;
  el.saveLocal.disabled = false;
  el.inferBowling.disabled = false;
  el.reset.disabled = false;
  el.search.disabled = false;
  el.nation.disabled = false;
  el.role.disabled = false;
}

function normalizePlayerForEditor(player) {
  const p = player;

  if (!p.nationalFormats || typeof p.nationalFormats !== "object") {
    p.nationalFormats = {};
  }

  if (!p.formatStatus || typeof p.formatStatus !== "object") {
    p.formatStatus = {};
  }

  for (const format of FORMATS) {
    const oldStatus = p.formatStatus?.[format];

    if (oldStatus === "eligible" || oldStatus === "retired" || oldStatus === "unavailable") {
      p.formatStatus[format] = oldStatus;
    } else {
      p.formatStatus[format] = p.nationalFormats?.[format] === true ? "eligible" : "unavailable";
    }

    p.nationalFormats[format] = p.formatStatus[format] === "eligible";
  }

  for (const field of EDITABLE_FIELDS) {
    if (!(field in p)) p[field] = "";
  }

  applyBowlingInferenceIfUseful(p, false);

  return p;
}

function rebuildFilters() {
  const nations = uniqueSorted(players.map(p => p.nationality).filter(Boolean));
  const roles = uniqueSorted(players.map(p => p.role).filter(Boolean));

  fillSelect(el.nation, "All nations", nations);
  fillSelect(el.role, "All roles", roles);
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((a, b) => String(a).localeCompare(String(b)));
}

function fillSelect(select, firstLabel, values) {
  const current = select.value;
  select.innerHTML = "";

  const first = document.createElement("option");
  first.value = "";
  first.textContent = firstLabel;
  select.appendChild(first);

  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }

  select.value = values.includes(current) ? current : "";
}

function getFilteredPlayers() {
  const query = el.search.value.trim().toLowerCase();
  const nation = el.nation.value;
  const role = el.role.value;

  return players.filter(player => {
    const blob = [
      player.id,
      player.name,
      player.fullName,
      player.nationality,
      player.role,
      player.battingHand,
      player.bowlingHand,
      player.bowlingType,
      player.bowlingStyle
    ].join(" ").toLowerCase();

    if (query && !blob.includes(query)) return false;
    if (nation && player.nationality !== nation) return false;
    if (role && player.role !== role) return false;

    return true;
  });
}

function renderPlayers() {
  const visible = getFilteredPlayers();

  el.total.textContent = players.length;
  el.shown.textContent = visible.length;
  el.deleted.textContent = deletedPlayers;

  el.list.innerHTML = "";

  if (!players.length) {
    el.list.innerHTML = `
      <div class="empty-state">
        <h2>Load your JSON to begin</h2>
        <p>Your data stays in this browser. Nothing is uploaded anywhere.</p>
      </div>
    `;
    return;
  }

  if (!visible.length) {
    el.list.innerHTML = `
      <div class="empty-state">
        <h2>No matching players</h2>
        <p>Clear your search or filters.</p>
      </div>
    `;
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const player of visible) {
    fragment.appendChild(createPlayerCard(player));
  }
  el.list.appendChild(fragment);
}

function createPlayerCard(player) {
  const node = el.template.content.firstElementChild.cloneNode(true);

  node.dataset.id = player.id;
  node.querySelector(".id-pill").textContent = `ID ${player.id ?? "—"}`;
  node.querySelector(".card-title").textContent = player.name || player.fullName || "Unnamed Player";
  node.querySelector(".card-meta").textContent = [
    player.nationality || "No nation",
    player.role || "No role"
  ].join(" • ");

  node.querySelector(".delete-btn").addEventListener("click", () => deletePlayer(player.id));

  for (const input of node.querySelectorAll("[data-field]")) {
    const field = input.dataset.field;
    input.value = player[field] ?? "";

    input.addEventListener("input", () => {
      player[field] = cleanValue(input.value);

      if (field === "bowlingStyle") {
        applyBowlingInferenceIfUseful(player, true);
        refreshBowlingControls(node, player);
      }

      markDirty(node);
      updateCardHeader(node, player);

      if (field === "role") rebuildFilters();
      scheduleAutoSave();
    });
  }

  for (const select of node.querySelectorAll("[data-format]")) {
    const format = select.dataset.format;
    select.value = player.formatStatus?.[format] || "unavailable";

    select.addEventListener("change", () => {
      setFormatStatus(player, format, select.value);
      markDirty(node);
      scheduleAutoSave();
    });
  }

  return node;
}

function cleanValue(value) {
  const trimmed = String(value ?? "").trim();
  return trimmed === "" ? null : trimmed;
}

function markDirty(card) {
  card.classList.add("dirty");
}

function updateCardHeader(card, player) {
  card.querySelector(".card-title").textContent = player.name || player.fullName || "Unnamed Player";
  card.querySelector(".card-meta").textContent = [
    player.nationality || "No nation",
    player.role || "No role"
  ].join(" • ");
}

function setFormatStatus(player, format, status) {
  if (!player.formatStatus) player.formatStatus = {};
  if (!player.nationalFormats) player.nationalFormats = {};

  player.formatStatus[format] = status;
  player.nationalFormats[format] = status === "eligible";
}

function deletePlayer(playerId) {
  const player = players.find(p => String(p.id) === String(playerId));
  const label = player?.name || player?.fullName || playerId || "this player";

  if (!confirm(`Delete ${label}?`)) return;

  players = players.filter(p => String(p.id) !== String(playerId));
  deletedPlayers += 1;

  rebuildFilters();
  renderPlayers();
  scheduleAutoSave();
}

function inferBowlingFromStyle(style) {
  const text = String(style || "").toLowerCase().trim();

  if (!text || text === "does not bowl" || text === "none" || text === "null") {
    return {
      bowlingHand: null,
      bowlingType: null
    };
  }

  let bowlingHand = null;
  let bowlingType = null;

  if (
    text.includes("left-arm") ||
    text.includes("left arm") ||
    text.includes("slow left") ||
    text.includes("sla")
  ) {
    bowlingHand = "left";
  } else if (
    text.includes("right-arm") ||
    text.includes("right arm") ||
    text.includes("off break") ||
    text.includes("offbreak") ||
    text.includes("leg break") ||
    text.includes("legbreak") ||
    text.includes("googly")
  ) {
    bowlingHand = "right";
  }

  if (
    text.includes("fast") ||
    text.includes("medium") ||
    text.includes("seam") ||
    text.includes("swing") ||
    text.includes("pace")
  ) {
    bowlingType = "pace";
  }

  if (
    text.includes("spin") ||
    text.includes("spinner") ||
    text.includes("orthodox") ||
    text.includes("off break") ||
    text.includes("offbreak") ||
    text.includes("leg break") ||
    text.includes("legbreak") ||
    text.includes("googly") ||
    text.includes("wrist") ||
    text.includes("chinaman")
  ) {
    bowlingType = "spin";
  }

  return { bowlingHand, bowlingType };
}

function applyBowlingInferenceIfUseful(player, overwrite = false) {
  const inferred = inferBowlingFromStyle(player.bowlingStyle);

  if (overwrite || !player.bowlingHand) {
    player.bowlingHand = inferred.bowlingHand;
  }

  if (overwrite || !player.bowlingType) {
    player.bowlingType = inferred.bowlingType;
  }
}

function refreshBowlingControls(card, player) {
  const handControl = card.querySelector('[data-field="bowlingHand"]');
  const typeControl = card.querySelector('[data-field="bowlingType"]');

  if (handControl) handControl.value = player.bowlingHand || "";
  if (typeControl) typeControl.value = player.bowlingType || "";
}

function autoFillAllBowlingFromStyle() {
  if (!players.length) {
    el.status.textContent = "Load a JSON file first.";
    return;
  }

  let changed = 0;

  for (const player of players) {
    const beforeHand = player.bowlingHand ?? null;
    const beforeType = player.bowlingType ?? null;

    applyBowlingInferenceIfUseful(player, true);

    if ((player.bowlingHand ?? null) !== beforeHand || (player.bowlingType ?? null) !== beforeType) {
      changed += 1;
    }
  }

  renderPlayers();
  scheduleAutoSave();
  el.status.textContent = `Auto-filled bowling hand/type from bowling style for ${changed} players.`;
}

function buildOutputJson() {
  const cleanedPlayers = players.map(player => {
    const p = structuredClone(player);

    applyBowlingInferenceIfUseful(p, false);

    if (!p.nationalFormats || typeof p.nationalFormats !== "object") {
      p.nationalFormats = {};
    }

    if (!p.formatStatus || typeof p.formatStatus !== "object") {
      p.formatStatus = {};
    }

    for (const format of FORMATS) {
      const status = p.formatStatus[format] || "unavailable";
      p.formatStatus[format] = status;
      p.nationalFormats[format] = status === "eligible";
    }

    return p;
  });

  if (outputMode === "array") {
    return cleanedPlayers;
  }

  const wrapper = structuredClone(originalWrapper);
  wrapper.players = cleanedPlayers;

  if (wrapper.metadata && typeof wrapper.metadata === "object") {
    wrapper.metadata.playerCount = cleanedPlayers.length;
    wrapper.metadata.modifiedAt = new Date().toISOString();
    wrapper.metadata.formatRule = "nationalFormats means selectable; formatStatus retired blocks selection.";
    wrapper.metadata.bowlingInference = "bowlingHand and bowlingType can be inferred from bowlingStyle.";
  }

  return wrapper;
}

function downloadUpdatedJson() {
  const output = buildOutputJson();
  const text = JSON.stringify(output, null, 2);

  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = makeDownloadName(loadedFileName);
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
  el.status.textContent = `Downloaded updated JSON with ${players.length} players.`;
}

function makeDownloadName(name) {
  const clean = name.replace(/\.json$/i, "");
  return `${clean}_updated.json`;
}

function resetLoadedFile() {
  if (!originalText) return;

  if (!confirm("Reset all edits back to the loaded file?")) return;

  const parsed = JSON.parse(originalText);
  loadDatabase(parsed);
  el.status.textContent = `Reset ${loadedFileName}.`;
  scheduleAutoSave();
}

function scheduleAutoSave() {
  if (!players.length) return;

  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => saveLocalCopy(false), 500);
}

function saveLocalCopy(showMessage = true) {
  if (!players.length) {
    el.status.textContent = "Load a JSON file before saving locally.";
    return;
  }

  const payload = {
    savedAt: new Date().toISOString(),
    fileName: loadedFileName,
    outputMode,
    originalWrapper: buildOutputJson(),
    deletedPlayers
  };

  try {
    localStorage.setItem(LOCAL_SAVE_KEY, JSON.stringify(payload));
    updateLocalSaveStatus();

    if (showMessage) {
      el.status.textContent = `Saved locally in this browser with ${players.length} players.`;
    }
  } catch (error) {
    console.error(error);
    el.status.textContent = "Local save failed. Your browser storage may be full or blocked.";
  }
}

function loadLocalSave() {
  const raw = localStorage.getItem(LOCAL_SAVE_KEY);

  if (!raw) {
    el.status.textContent = "No local save found in this browser.";
    updateLocalSaveStatus();
    return;
  }

  try {
    const payload = JSON.parse(raw);
    const data = payload.originalWrapper;

    loadedFileName = payload.fileName || "players.json";
    outputMode = payload.outputMode || "object";
    deletedPlayers = payload.deletedPlayers || 0;
    originalText = JSON.stringify(data, null, 2);

    loadDatabase(data);
    el.status.textContent = `Loaded local save from ${formatSavedDate(payload.savedAt)}.`;
    updateLocalSaveStatus();
  } catch (error) {
    console.error(error);
    el.status.textContent = "Local save is damaged. Clear it and load your JSON again.";
  }
}

function clearLocalSave() {
  if (!confirm("Clear the saved local copy from this browser?")) return;

  localStorage.removeItem(LOCAL_SAVE_KEY);
  updateLocalSaveStatus();
  el.status.textContent = "Local save cleared.";
}

function updateLocalSaveStatus() {
  const raw = localStorage.getItem(LOCAL_SAVE_KEY);

  el.localStatus.classList.remove("has-save", "no-save");

  if (!raw) {
    el.localStatus.textContent = "Local save: none yet.";
    el.localStatus.classList.add("no-save");
    return;
  }

  try {
    const payload = JSON.parse(raw);
    const count = Array.isArray(payload?.originalWrapper)
      ? payload.originalWrapper.length
      : payload?.originalWrapper?.players?.length;

    el.localStatus.textContent = `Local save: ${count ?? "?"} players saved on ${formatSavedDate(payload.savedAt)}.`;
    el.localStatus.classList.add("has-save");
  } catch {
    el.localStatus.textContent = "Local save: found, but it may be damaged.";
    el.localStatus.classList.add("no-save");
  }
}

function formatSavedDate(iso) {
  if (!iso) return "unknown date";

  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/*
  Use this helper in your game/team-selection code.

  Meaning:
  - eligible = selectable
  - retired = blocked
  - unavailable = not selectable unless you change it
*/
function canSelectForFormat(player, format) {
  const status = player?.formatStatus?.[format];

  if (status === "retired") return false;
  if (status === "eligible") return true;

  return player?.nationalFormats?.[format] === true;
}
