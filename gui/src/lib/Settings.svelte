<script>
  import { settings, markCustom } from "./stores.svelte.js";

  let expanded = $state(false);

  function set(key, value) {
    settings[key] = value;
    markCustom();
  }
</script>

<div class="settings-panel">
  <button class="toggle" onclick={() => (expanded = !expanded)}>
    <svg
      class="chevron"
      class:open={expanded}
      width="10"
      height="6"
      viewBox="0 0 10 6"
    >
      <polyline
        points="1,1 5,5 9,1"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
      />
    </svg>
    Advanced Settings
  </button>

  {#if expanded}
    <div class="grid">
      <div class="field">
        <label>Render Size (px)</label>
        <input
          type="number"
          value={settings.renderSize}
          oninput={(e) => set("renderSize", +e.target.value)}
          min="256"
          max="4096"
          step="256"
        />
      </div>

      <div class="field">
        <label>TAA Samples</label>
        <input
          type="number"
          value={settings.taaSamples}
          oninput={(e) => set("taaSamples", +e.target.value)}
          min="0"
          max="64"
        />
      </div>

      <div class="field">
        <label>Supersampling</label>
        <select
          value={settings.supersampling}
          onchange={(e) => set("supersampling", +e.target.value)}
        >
          <option value={1}>1x (None)</option>
          <option value={2}>2x</option>
          <option value={4}>4x</option>
        </select>
      </div>

      <div class="field">
        <label>Output Size (px)</label>
        <input
          type="number"
          value={settings.outputSize}
          oninput={(e) => set("outputSize", +e.target.value)}
          min="64"
          max="2048"
          step="64"
        />
      </div>

      <div class="field">
        <label>WebP Quality</label>
        <div class="slider-row">
          <input
            type="range"
            value={settings.webpQuality}
            oninput={(e) => set("webpQuality", +e.target.value)}
            min="1"
            max="100"
          />
          <span class="slider-val">{settings.webpQuality}</span>
        </div>
      </div>

      <div class="field">
        <label>Workers (0 = auto)</label>
        <input
          type="number"
          value={settings.workers}
          oninput={(e) => (settings.workers = +e.target.value)}
          min="0"
          max="64"
        />
      </div>

      <div class="field toggle-field">
        <label>Green Hair Fix</label>
        <button
          class="toggle-btn"
          class:on={settings.greenHairFix}
          onclick={() => (settings.greenHairFix = !settings.greenHairFix)}
        >
          {settings.greenHairFix ? "On" : "Off"}
        </button>
      </div>

      <div class="field toggle-field">
        <label>Force Reprocess</label>
        <button
          class="toggle-btn"
          class:on={settings.forceReprocess}
          onclick={() => (settings.forceReprocess = !settings.forceReprocess)}
        >
          {settings.forceReprocess ? "On" : "Off"}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .settings-panel {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .toggle {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    text-align: left;
  }
  .toggle:hover {
    color: var(--text-primary);
  }
  .chevron {
    transition: transform 0.2s;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    padding: 12px;
    background: var(--bg-primary);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .field label {
    font-size: 11px;
    color: var(--text-muted);
  }
  .field input[type="number"],
  .field select {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: 5px 8px;
  }
  .field input[type="number"]:focus,
  .field select:focus {
    border-color: var(--border-focus);
  }
  .slider-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .slider-row input[type="range"] {
    flex: 1;
    accent-color: var(--accent);
    height: 4px;
  }
  .slider-val {
    font-size: 12px;
    color: var(--text-secondary);
    min-width: 24px;
    text-align: right;
  }
  .toggle-field {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  .toggle-btn {
    padding: 4px 12px;
    border-radius: var(--radius);
    font-size: 11px;
    font-weight: 600;
    background: var(--bg-input);
    color: var(--text-muted);
    border: 1px solid var(--border);
    transition: all 0.15s;
  }
  .toggle-btn.on {
    background: var(--success);
    color: #111;
    border-color: var(--success);
  }
</style>
