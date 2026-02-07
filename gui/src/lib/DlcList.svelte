<script>
  import { dlcState, selectAllDlcs, deselectAllDlcs, toggleDlc } from "./stores.svelte.js";

  let allDlcs = $derived([
    ...dlcState.streamDlcs.map((d) => ({ ...d, group: "Stream" })),
    ...dlcState.baseGameDlcs.map((d) => ({ ...d, group: "Base Game" })),
  ]);

  let totalItems = $derived(
    allDlcs.filter((d) => dlcState.selected.has(d.name)).reduce((sum, d) => sum + d.items, 0)
  );

  let allSelected = $derived(
    allDlcs.length > 0 && allDlcs.every((d) => dlcState.selected.has(d.name))
  );
</script>

<div class="dlc-list">
  <div class="dlc-header">
    <span class="dlc-title">DLC Packs</span>
    {#if allDlcs.length > 0}
      <span class="dlc-count">{dlcState.selected.size}/{allDlcs.length} selected &middot; {totalItems} items</span>
    {/if}
    <div class="dlc-actions">
      <button class="action-btn" onclick={selectAllDlcs} disabled={allDlcs.length === 0}>All</button>
      <button class="action-btn" onclick={deselectAllDlcs} disabled={allDlcs.length === 0}>None</button>
    </div>
  </div>

  {#if dlcState.scanning}
    <div class="dlc-body empty">
      <span class="spinner"></span> Scanning...
    </div>
  {:else if dlcState.scanError}
    <div class="dlc-body empty error">{dlcState.scanError}</div>
  {:else if allDlcs.length === 0}
    <div class="dlc-body empty">Set input folder to discover DLC packs</div>
  {:else}
    <div class="dlc-body">
      {#each allDlcs as dlc}
        <label class="dlc-item" class:selected={dlcState.selected.has(dlc.name)}>
          <input
            type="checkbox"
            checked={dlcState.selected.has(dlc.name)}
            onchange={() => toggleDlc(dlc.name)}
          />
          <span class="dlc-name">{dlc.name}</span>
          <span class="dlc-badge">{dlc.items}</span>
          <span class="dlc-group">{dlc.group}</span>
        </label>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dlc-list {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    flex: 1;
    min-height: 0;
  }
  .dlc-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .dlc-title {
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
  }
  .dlc-count {
    font-size: 11px;
    color: var(--text-muted);
    margin-left: auto;
  }
  .dlc-actions {
    display: flex;
    gap: 4px;
  }
  .action-btn {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 3px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    transition: background 0.15s;
  }
  .action-btn:hover:not(:disabled) {
    background: var(--accent);
    color: white;
  }
  .action-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .dlc-body {
    flex: 1;
    overflow-y: auto;
    background: var(--bg-primary);
  }
  .dlc-body.empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 24px;
    color: var(--text-muted);
    font-size: 12px;
    min-height: 80px;
  }
  .dlc-body.error {
    color: var(--error);
  }
  .dlc-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    cursor: pointer;
    transition: background 0.1s;
  }
  .dlc-item:hover {
    background: rgba(255, 255, 255, 0.03);
  }
  .dlc-item.selected {
    background: rgba(233, 69, 96, 0.06);
  }
  .dlc-item input[type="checkbox"] {
    accent-color: var(--accent);
  }
  .dlc-name {
    flex: 1;
    font-size: 13px;
  }
  .dlc-badge {
    font-size: 11px;
    color: var(--text-muted);
    background: var(--bg-secondary);
    padding: 1px 6px;
    border-radius: 8px;
    min-width: 28px;
    text-align: center;
  }
  .dlc-group {
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    width: 60px;
    text-align: right;
  }

  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
