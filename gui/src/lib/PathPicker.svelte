<script>
  /**
   * Folder/file browse component with native dialogs.
   * @type {{ label: string, value: string, onChange: (v: string) => void, type?: "directory" | "file", placeholder?: string, required?: boolean, filters?: any[] }}
   */
  let { label, value, onChange, type = "directory", placeholder = "", required = false, filters = [] } = $props();

  async function browse() {
    let result;
    if (type === "file") {
      result = await window.api.openFile({ title: `Select ${label}`, filters });
    } else {
      result = await window.api.openDirectory({ title: `Select ${label}` });
    }
    if (result) onChange(result);
  }
</script>

<div class="path-picker">
  <label class="label">
    {label}
    {#if required}<span class="required">*</span>{/if}
  </label>
  <div class="input-row">
    <input
      type="text"
      class="path-input"
      {placeholder}
      value={value}
      oninput={(e) => onChange(e.target.value)}
      readonly
    />
    <button class="browse-btn" onclick={browse}>Browse</button>
  </div>
</div>

<style>
  .path-picker {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .required {
    color: var(--accent);
  }
  .input-row {
    display: flex;
    gap: 6px;
  }
  .path-input {
    flex: 1;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: 6px 10px;
    font-size: 12px;
    cursor: default;
  }
  .path-input:focus {
    border-color: var(--border-focus);
  }
  .browse-btn {
    background: var(--bg-tertiary);
    color: var(--text-primary);
    padding: 6px 14px;
    border-radius: var(--radius);
    font-size: 12px;
    font-weight: 500;
    transition: background 0.15s;
  }
  .browse-btn:hover {
    background: var(--accent);
  }
</style>
