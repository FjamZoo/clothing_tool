<script>
  import { processing } from "./stores.svelte.js";

  let logContainer = $state(null);
  let autoScroll = $state(true);

  let percent = $derived(
    processing.total > 0
      ? Math.round((processing.current / processing.total) * 100)
      : 0
  );

  let rate = $derived(
    processing.elapsed > 0 && processing.processed > 0
      ? (processing.processed / processing.elapsed).toFixed(1)
      : "0.0"
  );

  $effect(() => {
    // Auto-scroll log to bottom when new entries arrive
    processing.log; // subscribe
    if (autoScroll && logContainer) {
      requestAnimationFrame(() => {
        logContainer.scrollTop = logContainer.scrollHeight;
      });
    }
  });

  function handleScroll() {
    if (!logContainer) return;
    const atBottom =
      logContainer.scrollHeight - logContainer.scrollTop - logContainer.clientHeight < 30;
    autoScroll = atBottom;
  }
</script>

<div class="progress-panel">
  {#if processing.running || processing.current > 0}
    <div class="bar-section">
      <div class="bar-track">
        <div class="bar-fill" style="width: {percent}%"></div>
      </div>
      <span class="bar-pct">{percent}%</span>
    </div>

    <div class="status-line">
      {#if processing.running}
        <span class="file">{processing.currentFile || "Starting..."}</span>
      {:else}
        <span class="file">Done</span>
      {/if}
      <span class="stats">
        {processing.processed} ok
        {#if processing.failed > 0}
          &middot; <span class="fail">{processing.failed} failed</span>
        {/if}
        &middot; {rate} img/s
      </span>
    </div>
  {/if}

  <div
    class="log"
    bind:this={logContainer}
    onscroll={handleScroll}
  >
    {#each processing.log as line}
      <div class="log-line" class:error={line.startsWith("ERR") || line.startsWith("FAIL")}>{line}</div>
    {/each}
    {#if processing.log.length === 0}
      <div class="log-empty">Output will appear here...</div>
    {/if}
  </div>
</div>

<style>
  .progress-panel {
    display: flex;
    flex-direction: column;
    gap: 6px;
    flex: 1;
    min-height: 0;
  }
  .bar-section {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
  .bar-track {
    flex: 1;
    height: 6px;
    background: var(--bg-input);
    border-radius: 3px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 3px;
    transition: width 0.3s ease;
  }
  .bar-pct {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    min-width: 36px;
    text-align: right;
  }
  .status-line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
  }
  .file {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stats {
    flex-shrink: 0;
    margin-left: 12px;
  }
  .fail {
    color: var(--error);
  }
  .log {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 8px;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    line-height: 1.5;
  }
  .log-line {
    color: var(--text-secondary);
    white-space: pre-wrap;
    word-break: break-all;
  }
  .log-line.error {
    color: var(--error);
  }
  .log-empty {
    color: var(--text-muted);
    font-style: italic;
  }
</style>
