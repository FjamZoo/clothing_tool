<script>
  import TitleBar from "./lib/TitleBar.svelte";
  import PathPicker from "./lib/PathPicker.svelte";
  import DlcList from "./lib/DlcList.svelte";
  import CategoryFilter from "./lib/CategoryFilter.svelte";
  import ProfileBar from "./lib/ProfileBar.svelte";
  import Settings from "./lib/Settings.svelte";
  import ProgressLog from "./lib/ProgressLog.svelte";
  import {
    paths,
    dlcState,
    categoryState,
    settings,
    processing,
    addLog,
    resetProcessing,
    selectAllDlcs,
    selectAllCategories,
  } from "./lib/stores.svelte.js";

  let unsubProgress = $state(null);
  let loaded = $state(false);

  // Restore all saved state on mount
  $effect(() => {
    loadSavedState();
    return () => {
      if (unsubProgress) unsubProgress();
    };
  });

  // Auto-save settings whenever they change (after initial load)
  $effect(() => {
    if (!loaded || !window.api) return;
    // Read all reactive values to subscribe
    const snap = {
      profile: settings.profile,
      mode: settings.mode,
      taaSamples: settings.taaSamples,
      renderSize: settings.renderSize,
      supersampling: settings.supersampling,
      outputSize: settings.outputSize,
      webpQuality: settings.webpQuality,
      workers: settings.workers,
      greenHairFix: settings.greenHairFix,
      forceReprocess: settings.forceReprocess,
    };
    window.api.setSetting("settings", snap);
  });

  // Auto-save DLC selection whenever it changes (after initial load)
  $effect(() => {
    if (!loaded || !window.api) return;
    const sel = [...dlcState.selected];
    window.api.setSetting("selectedDlcs", sel);
  });

  // Auto-save category selection whenever it changes (after initial load)
  $effect(() => {
    if (!loaded || !window.api) return;
    const sel = [...categoryState.selected];
    window.api.setSetting("selectedCategories", sel);
  });

  async function loadSavedState() {
    if (!window.api) { loaded = true; return; }
    try {
      const saved = await window.api.getAllSettings();

      // Restore paths
      if (saved?.inputDir) paths.inputDir = saved.inputDir;
      if (saved?.baseGameDir) paths.baseGameDir = saved.baseGameDir;
      if (saved?.outputDir) paths.outputDir = saved.outputDir;
      if (saved?.blenderPath) paths.blenderPath = saved.blenderPath;

      // Restore settings
      if (saved?.settings) {
        const s = saved.settings;
        if (s.profile) settings.profile = s.profile;
        if (s.mode) settings.mode = s.mode;
        if (s.taaSamples != null) settings.taaSamples = s.taaSamples;
        if (s.renderSize) settings.renderSize = s.renderSize;
        if (s.supersampling) settings.supersampling = s.supersampling;
        if (s.outputSize) settings.outputSize = s.outputSize;
        if (s.webpQuality) settings.webpQuality = s.webpQuality;
        if (s.workers != null) settings.workers = s.workers;
        if (s.greenHairFix != null) settings.greenHairFix = s.greenHairFix;
        if (s.forceReprocess != null) settings.forceReprocess = s.forceReprocess;
      }

      // Auto-scan if input dir was saved, then restore DLC + category selection
      if (paths.inputDir) {
        await triggerScan();
        // Restore DLC selection after scan populates the list
        if (saved?.selectedDlcs && Array.isArray(saved.selectedDlcs)) {
          dlcState.selected = new Set(saved.selectedDlcs);
        }
        // Restore category selection after scan populates the list
        if (saved?.selectedCategories && Array.isArray(saved.selectedCategories)) {
          categoryState.selected = new Set(saved.selectedCategories);
        }
      }
    } catch {
      // electron-store not available (dev mode in browser)
    }
    loaded = true;
  }

  function savePath(key, value) {
    paths[key] = value;
    window.api?.setSetting(key, value);
    // Auto-scan when input dir changes
    if (key === "inputDir" && value) triggerScan();
    if (key === "baseGameDir") triggerScan();
  }

  async function triggerScan() {
    if (!paths.inputDir) return;
    dlcState.scanning = true;
    dlcState.scanError = "";

    try {
      const config = {
        inputDir: paths.inputDir,
        baseGameDir: paths.baseGameDir || undefined,
      };
      const result = await window.api.scan(config);
      dlcState.streamDlcs = result.stream || [];
      dlcState.baseGameDlcs = result.base_game || [];
      categoryState.categories = result.categories || [];
      // Auto-select all
      selectAllDlcs();
      selectAllCategories();
    } catch (err) {
      dlcState.scanError = err.message || "Scan failed";
      dlcState.streamDlcs = [];
      dlcState.baseGameDlcs = [];
      categoryState.categories = [];
    } finally {
      dlcState.scanning = false;
    }
  }

  function buildConfig(dryRun = false) {
    return {
      inputDir: paths.inputDir,
      outputDir: paths.outputDir,
      baseGameDir: paths.baseGameDir || undefined,
      blenderPath: paths.blenderPath || undefined,
      dlcs: [...dlcState.selected],
      categories: [...categoryState.selected],
      render3d: settings.mode === "3d",
      taaSamples: settings.taaSamples,
      renderSize: settings.renderSize,
      supersampling: settings.supersampling,
      outputSize: settings.outputSize,
      webpQuality: settings.webpQuality,
      workers: settings.workers,
      noGreenFix: !settings.greenHairFix,
      force: settings.forceReprocess,
      dryRun,
    };
  }

  let startTime = 0;
  let elapsedInterval = null;

  function startElapsedTimer() {
    startTime = Date.now();
    elapsedInterval = setInterval(() => {
      processing.elapsed = (Date.now() - startTime) / 1000;
    }, 500);
  }

  function stopElapsedTimer() {
    if (elapsedInterval) {
      clearInterval(elapsedInterval);
      elapsedInterval = null;
    }
  }

  function handleProgressLine(data) {
    if (data.type === "start") {
      processing.total = data.total;
      addLog(`Starting: ${data.total} items to process`);
    } else if (data.type === "progress") {
      processing.current = data.current;
      processing.currentFile = data.file || "";
      if (data.status === "ok") {
        processing.processed++;
      } else {
        processing.failed++;
        addLog(`FAIL: ${data.file} -- ${data.error || "unknown"}`);
      }
    } else if (data.type === "scan") {
      const names = data.dlcs.map((d) => `${d.name}(${d.count})`).join(", ");
      addLog(`DLCs: ${names}`);
    } else if (data.type === "done") {
      processing.running = false;
      processing.elapsed = data.elapsed || processing.elapsed;
      stopElapsedTimer();
      addLog(
        `Done: ${data.processed} processed, ${data.failed} failed, ${data.skipped} skipped in ${data.elapsed}s`
      );
    } else if (data.type === "error") {
      processing.running = false;
      stopElapsedTimer();
      addLog(`ERROR: ${data.message}`);
    } else if (data.type === "log") {
      addLog(data.message);
    }
  }

  async function startProcessing(dryRun = false) {
    if (!paths.inputDir || !paths.outputDir) return;
    if (dlcState.selected.size === 0) return;

    resetProcessing();
    processing.running = true;
    startElapsedTimer();
    addLog(dryRun ? "Starting dry run..." : "Starting processing...");

    // Subscribe to progress events
    if (unsubProgress) unsubProgress();
    unsubProgress = window.api.onProgress(handleProgressLine);

    const config = buildConfig(dryRun);
    try {
      await window.api.process(config);
    } catch (err) {
      addLog(`ERROR: ${err.message}`);
      processing.running = false;
      stopElapsedTimer();
    }
  }

  function stopProcessing() {
    window.api.kill();
    processing.running = false;
    stopElapsedTimer();
    addLog("Process cancelled by user");
  }

  let canStart = $derived(
    paths.inputDir && paths.outputDir && dlcState.selected.size > 0 && categoryState.selected.size > 0 && !processing.running
  );
</script>

<div class="app">
  <TitleBar />

  <div class="content">
    <!-- Top: Paths & Mode -->
    <section class="paths-section">
      <div class="paths-grid">
        <PathPicker
          label="Input Folder"
          value={paths.inputDir}
          onChange={(v) => savePath("inputDir", v)}
          placeholder="stream/ directory with DLC packs"
          required
        />
        <PathPicker
          label="Output Folder"
          value={paths.outputDir}
          onChange={(v) => savePath("outputDir", v)}
          placeholder="Where to save .webp previews"
          required
        />
        <PathPicker
          label="Base Game Folder"
          value={paths.baseGameDir}
          onChange={(v) => savePath("baseGameDir", v)}
          placeholder="Optional: base_game directory"
        />
        <PathPicker
          label="Blender Path"
          value={paths.blenderPath}
          onChange={(v) => savePath("blenderPath", v)}
          placeholder="Auto-detected"
          type="file"
          filters={[{ name: "Blender", extensions: ["exe"] }]}
        />
      </div>
      <div class="mode-row">
        <div class="mode-toggle">
          <button
            class="mode-btn"
            class:active={settings.mode === "3d"}
            onclick={() => (settings.mode = "3d")}
          >
            3D Render
          </button>
          <button
            class="mode-btn"
            class:active={settings.mode === "flat"}
            onclick={() => (settings.mode = "flat")}
          >
            Flat Texture
          </button>
        </div>
      </div>
    </section>

    <!-- Middle: DLC Picker -->
    <section class="dlc-section">
      <DlcList />
    </section>

    <!-- Category Filter -->
    <section class="category-section">
      <CategoryFilter />
    </section>

    <!-- Bottom: Settings, Actions & Progress -->
    <section class="bottom-section">
      <div class="controls-row">
        <ProfileBar />
        <div class="action-buttons">
          {#if processing.running}
            <button class="btn btn-stop" onclick={stopProcessing}>
              Stop
            </button>
          {:else}
            <button
              class="btn btn-secondary"
              onclick={() => startProcessing(true)}
              disabled={!canStart}
              title="Scan and show what would be processed, without writing any files"
            >
              Dry Run
            </button>
            <button
              class="btn btn-primary"
              onclick={() => startProcessing(false)}
              disabled={!canStart}
            >
              Process
            </button>
          {/if}
        </div>
      </div>

      {#if settings.mode === "3d"}
        <Settings />
      {/if}

      <ProgressLog />
    </section>
  </div>
</div>

<style>
  .app {
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--bg-primary);
  }
  .content {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 12px 16px;
    gap: 12px;
    min-height: 0;
    overflow: hidden;
  }

  /* --- Paths section --- */
  .paths-section {
    flex-shrink: 0;
  }
  .paths-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .mode-row {
    margin-top: 8px;
    display: flex;
    align-items: center;
  }
  .mode-toggle {
    display: flex;
    gap: 2px;
    background: var(--bg-input);
    border-radius: var(--radius);
    padding: 2px;
    border: 1px solid var(--border);
  }
  .mode-btn {
    padding: 5px 16px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    background: transparent;
    transition: all 0.15s;
  }
  .mode-btn:hover:not(.active) {
    background: rgba(255, 255, 255, 0.05);
  }
  .mode-btn.active {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }

  /* --- DLC section --- */
  .dlc-section {
    flex: 1;
    min-height: 80px;
    display: flex;
  }

  /* --- Category section --- */
  .category-section {
    flex-shrink: 0;
  }

  /* --- Bottom section --- */
  .bottom-section {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-height: 120px;
  }
  .controls-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }
  .action-buttons {
    display: flex;
    gap: 6px;
  }
  .btn {
    padding: 7px 20px;
    border-radius: var(--radius);
    font-size: 13px;
    font-weight: 600;
    transition: all 0.15s;
  }
  .btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .btn-primary {
    background: var(--accent);
    color: white;
  }
  .btn-primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .btn-secondary {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  .btn-secondary:hover:not(:disabled) {
    background: #1a4a80;
  }
  .btn-stop {
    background: var(--error);
    color: white;
  }
  .btn-stop:hover {
    background: var(--accent-hover);
  }
</style>
