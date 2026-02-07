<script>
  /** Custom frameless title bar with window controls. */
</script>

<header class="titlebar">
  <div class="titlebar-drag">
    <span class="title">Clothing Tool</span>
  </div>
  <div class="controls">
    <button class="ctrl-btn" onclick={() => window.api.minimize()} title="Minimize">
      <svg width="10" height="1" viewBox="0 0 10 1"><rect width="10" height="1" fill="currentColor"/></svg>
    </button>
    <button class="ctrl-btn" onclick={() => window.api.maximize()} title="Maximize">
      <svg width="10" height="10" viewBox="0 0 10 10"><rect width="10" height="10" fill="none" stroke="currentColor" stroke-width="1"/></svg>
    </button>
    <button class="ctrl-btn close" onclick={() => window.api.close()} title="Close">
      <svg width="10" height="10" viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" stroke-width="1.2"/><line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" stroke-width="1.2"/></svg>
    </button>
  </div>
</header>

<style>
  .titlebar {
    display: flex;
    align-items: center;
    height: 32px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .titlebar-drag {
    flex: 1;
    -webkit-app-region: drag;
    height: 100%;
    display: flex;
    align-items: center;
    padding-left: 12px;
  }
  .title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .controls {
    display: flex;
    height: 100%;
  }
  .ctrl-btn {
    width: 46px;
    height: 100%;
    background: none;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.1s;
  }
  .ctrl-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-primary);
  }
  .ctrl-btn.close:hover {
    background: var(--error);
    color: white;
  }
</style>
