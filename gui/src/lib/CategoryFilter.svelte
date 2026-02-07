<script>
  import {
    categoryState,
    selectAllCategories,
    deselectAllCategories,
    toggleCategory,
  } from "./stores.svelte.js";

  let totalItems = $derived(
    categoryState.categories
      .filter((c) => categoryState.selected.has(c.key))
      .reduce((sum, c) => sum + c.items, 0)
  );

  let allSelected = $derived(
    categoryState.categories.length > 0 &&
      categoryState.categories.every((c) => categoryState.selected.has(c.key))
  );
</script>

<div class="cat-filter">
  <div class="cat-header">
    <span class="cat-title">Categories</span>
    {#if categoryState.categories.length > 0}
      <span class="cat-count"
        >{categoryState.selected.size}/{categoryState.categories.length} selected
        &middot; {totalItems} items</span
      >
    {/if}
  </div>

  {#if categoryState.categories.length === 0}
    <div class="cat-body empty">Scan to discover categories</div>
  {:else}
    <div class="cat-body">
      <button
        class="pill select-all"
        class:active={allSelected}
        onclick={() => allSelected ? deselectAllCategories() : selectAllCategories()}
      >
        <span class="pill-label">{allSelected ? "Deselect All" : "Select All"}</span>
      </button>
      {#each categoryState.categories as cat (cat.key)}
        <button
          class="pill"
          class:active={categoryState.selected.has(cat.key)}
          onclick={() => toggleCategory(cat.key)}
        >
          <span class="pill-label">{cat.label}</span>
          <span class="pill-count">{cat.items}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .cat-filter {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    flex-shrink: 0;
  }
  .cat-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
  }
  .cat-title {
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
  }
  .cat-count {
    font-size: 11px;
    color: var(--text-muted);
    margin-left: auto;
  }
  .cat-body {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 10px 12px;
    background: var(--bg-primary);
  }
  .cat-body.empty {
    justify-content: center;
    padding: 16px;
    color: var(--text-muted);
    font-size: 12px;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    border: 1px solid var(--border);
    cursor: pointer;
    transition: all 0.15s;
    user-select: none;
  }
  .pill:hover {
    border-color: var(--accent);
  }
  .pill.active {
    background: rgba(233, 69, 96, 0.15);
    border-color: var(--accent);
    color: var(--text-primary);
  }
  .pill.select-all {
    border-style: dashed;
    font-style: italic;
  }
  .pill.select-all.active {
    border-style: dashed;
  }
  .pill-label {
    font-weight: 500;
  }
  .pill-count {
    font-size: 10px;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    padding: 0 5px;
    border-radius: 8px;
    min-width: 20px;
    text-align: center;
  }
  .pill.active .pill-count {
    background: rgba(233, 69, 96, 0.25);
  }
</style>
