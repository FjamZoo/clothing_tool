/**
 * Application state using Svelte 5 runes.
 *
 * Profiles: Speed / Balance / Quality set render settings.
 * Any manual tweak switches to "Custom".
 */

export const PROFILES = {
  speed: {
    renderSize: 512,
    supersampling: 1,
    taaSamples: 0,
    webpQuality: 80,
  },
  balance: {
    renderSize: 1024,
    supersampling: 2,
    taaSamples: 1,
    webpQuality: 100,
  },
  quality: {
    renderSize: 2048,
    supersampling: 4,
    taaSamples: 8,
    webpQuality: 100,
  },
};

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------
export let paths = $state({
  inputDir: "",
  baseGameDir: "",
  outputDir: "",
  blenderPath: "",
});

// ---------------------------------------------------------------------------
// DLCs
// ---------------------------------------------------------------------------
export let dlcState = $state({
  /** @type {{ name: string, items: number }[]} */
  streamDlcs: [],
  /** @type {{ name: string, items: number }[]} */
  baseGameDlcs: [],
  /** @type {Set<string>} */
  selected: new Set(),
  scanning: false,
  scanError: "",
});

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------
export let categoryState = $state({
  /** @type {{ key: string, label: string, items: number }[]} */
  categories: [],
  /** @type {Set<string>} */
  selected: new Set(),
});

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
export let settings = $state({
  profile: "balance",
  mode: "3d",
  taaSamples: 1,
  renderSize: 1024,
  supersampling: 2,
  outputSize: 512,
  webpQuality: 100,
  workers: 0,
  greenHairFix: true,
  forceReprocess: false,
});

// ---------------------------------------------------------------------------
// Processing
// ---------------------------------------------------------------------------
export let processing = $state({
  running: false,
  current: 0,
  total: 0,
  currentFile: "",
  status: "",
  elapsed: 0,
  /** @type {string[]} */
  log: [],
  processed: 0,
  failed: 0,
});

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Apply a profile preset to settings.
 * @param {"speed" | "balance" | "quality"} name
 */
export function applyProfile(name) {
  const p = PROFILES[name];
  if (!p) return;
  settings.profile = name;
  settings.renderSize = p.renderSize;
  settings.supersampling = p.supersampling;
  settings.taaSamples = p.taaSamples;
  settings.webpQuality = p.webpQuality;
}

/** Mark profile as custom (called when user manually changes a setting). */
export function markCustom() {
  settings.profile = "custom";
}

/** Select all DLCs. */
export function selectAllDlcs() {
  const all = [
    ...dlcState.streamDlcs.map((d) => d.name),
    ...dlcState.baseGameDlcs.map((d) => d.name),
  ];
  dlcState.selected = new Set(all);
}

/** Deselect all DLCs. */
export function deselectAllDlcs() {
  dlcState.selected = new Set();
}

/** Toggle a single DLC selection. */
export function toggleDlc(name) {
  const next = new Set(dlcState.selected);
  if (next.has(name)) {
    next.delete(name);
  } else {
    next.add(name);
  }
  dlcState.selected = next;
}

/** Select all categories. */
export function selectAllCategories() {
  categoryState.selected = new Set(categoryState.categories.map((c) => c.key));
}

/** Deselect all categories. */
export function deselectAllCategories() {
  categoryState.selected = new Set();
}

/** Toggle a single category selection. */
export function toggleCategory(key) {
  const next = new Set(categoryState.selected);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  categoryState.selected = next;
}

/** Add a log line. */
export function addLog(message) {
  processing.log = [...processing.log, message];
}

/** Reset processing state for a new run. */
export function resetProcessing() {
  processing.running = false;
  processing.current = 0;
  processing.total = 0;
  processing.currentFile = "";
  processing.status = "";
  processing.elapsed = 0;
  processing.log = [];
  processing.processed = 0;
  processing.failed = 0;
}
