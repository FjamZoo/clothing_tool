<script>
  import { settings, applyProfile } from "./stores.svelte.js";

  const profiles = [
    { key: "speed", label: "Speed" },
    { key: "balance", label: "Balance" },
    { key: "quality", label: "Quality" },
  ];
</script>

<div class="profile-bar">
  <span class="profile-label">Profile</span>
  <div class="profile-buttons">
    {#each profiles as p}
      <button
        class="profile-btn"
        class:active={settings.profile === p.key}
        onclick={() => applyProfile(p.key)}
      >
        {p.label}
      </button>
    {/each}
    {#if settings.profile === "custom"}
      <button class="profile-btn custom active" disabled>Custom</button>
    {/if}
  </div>
</div>

<style>
  .profile-bar {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .profile-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .profile-buttons {
    display: flex;
    gap: 2px;
    background: var(--bg-input);
    border-radius: var(--radius);
    padding: 2px;
    border: 1px solid var(--border);
  }
  .profile-btn {
    padding: 5px 16px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    background: transparent;
    transition: all 0.15s;
  }
  .profile-btn:hover:not(.active):not(:disabled) {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-primary);
  }
  .profile-btn.active {
    background: var(--accent);
    color: white;
  }
  .profile-btn.custom {
    font-style: italic;
    cursor: default;
  }
</style>
