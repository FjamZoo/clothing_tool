# Clothing Tool GUI — Design Plan

## Overview

Electron + Svelte desktop app (1024×768) that wraps the existing `cli.py` as a subprocess. Dark theme, minimal UI. User double-clicks to launch, picks folders/DLCs, tweaks settings, hits Process.

## Architecture

```
┌─────────────────────────────┐
│   Svelte UI (renderer)      │  ← User interacts here
├─────────────────────────────┤
│   Electron Main Process     │  ← File dialogs, spawns Python
├─────────────────────────────┤
│   cli.py (subprocess)       │  ← Existing pipeline, unchanged
└─────────────────────────────┘
```

- UI sends config to Electron main via IPC (`ipcRenderer` → `ipcMain`)
- Main process spawns `python cli.py` with assembled flags
- Python stdout (JSON lines via `--json-progress`) streamed back to UI
- Electron handles native file dialogs for folder selection

## UI Layout

Single window, three vertical sections:

### 1. Top Bar — Paths & Mode

| Control | Type | Notes |
|---------|------|-------|
| Input folder | Browse button + path | Required |
| Base game folder | Browse button + path | Optional |
| Output folder | Browse button + path | Required |
| Blender path | Browse button + path | Auto-detected, override |
| Mode toggle | "3D Render" / "Texture Extractor" | 3D Render default. Texture Extractor greys out render settings |

### 2. Middle — DLC Picker

- After input folder is set, app runs `cli.py --scan-only` to discover DLCs
- Multi-select list with ctrl+click / shift+click
- "Select All" / "Deselect All" buttons
- Shows item counts per DLC: `rhclothing (342 items)`
- Groups: Stream DLCs vs Base Game (if base game folder set)

### 3. Bottom — Settings, Actions & Progress

**Profile selector:** Three buttons — `Speed | Balance | Quality`

| Setting | Speed | Balance | Quality |
|---------|-------|---------|---------|
| Render size | 512px | 1024px | 2048px |
| Supersampling | None (1x) | 2x | 4x |
| TAA samples | 0 | 1 | 8 |
| WebP quality | 80 | 100 | 100 |

Output size is independent of profiles — user sets it once (default 512px).

**Advanced settings** (collapsible panel, collapsed by default):

| Setting | Control | Default |
|---------|---------|---------|
| TAA samples | Number input | 1 |
| Render size | Number input (px) | 1024 |
| Supersampling | Dropdown (1x, 2x, 4x) | 2x |
| Output size | Number input (px) | 512 |
| WebP quality | Slider 1–100 | 100 |
| Workers | Number input (0=auto) | 0 |
| Green hair fix | Toggle | On |
| Force reprocess | Toggle | Off |

Selecting a profile fills in settings. Tweaking any setting after changes profile label to "Custom".

**Action buttons:** `Dry Run` and `Process`

**Progress area:**
- Progress bar with percentage
- Live scrolling log (stdout from Python)
- Status line: "Processing rhclothing/female/accs/003..." + elapsed time + throughput

## CLI Additions

### New arguments to `cli.py`

```
--json-progress     Emit JSON lines to stdout for GUI progress tracking
--scan-only         Output JSON list of discovered DLCs + item counts, then exit
--dlcs              Comma-separated DLC folder names to process (default: all)
--taa-samples       TAA render samples (default: 1)
--render-size       Blender render resolution in px (default: 1024)
--supersampling     Supersampling multiplier: 1, 2, or 4 (default: 2)
--output-size       Final output image size in px (default: 512)
--webp-quality      WebP compression quality 1-100 (default: 100)
--no-green-fix      Disable green hair tint replacement
```

### `--json-progress` output format

One JSON object per line to stdout:

```json
{"type":"scan","dlcs":[{"name":"rhclothing","count":342},{"name":"rhpeds","count":89}]}
{"type":"start","total":431}
{"type":"progress","current":1,"total":431,"file":"rhclothing/female/accs/000","status":"ok"}
{"type":"progress","current":2,"total":431,"file":"rhclothing/female/accs/001","status":"ok"}
{"type":"progress","current":3,"total":431,"file":"rhclothing/female/jbib/000","status":"failed","error":"Empty render"}
{"type":"done","processed":430,"failed":1,"skipped":0,"elapsed":86.2}
```

### `--scan-only` output format

```json
{
  "stream": [
    {"name": "rhclothing", "path": "stream/rhclothing", "items": 342},
    {"name": "rhpeds", "path": "stream/rhpeds", "items": 89}
  ],
  "base_game": [
    {"name": "base_game", "path": "base_game", "items": 204}
  ]
}
```

## Hardcoded Values to Parameterize

These are currently hardcoded and need to become configurable via CLI args:

| Setting | File | Line | Current |
|---------|------|------|---------|
| Render size | `src/blender_script.py` | 52 | `RENDER_SIZE = 1024` |
| TAA samples | `src/blender_script.py` | 139 | `taa_render_samples = 1` |
| Output size | `src/image_processor.py` | 22 | `CANVAS_SIZE = 512` |
| WebP quality | `src/image_processor.py` | 25 | `WEBP_QUALITY = 100` |
| WebP method | `src/image_processor.py` | 29 | `WEBP_METHOD = 4` |
| Green hair fix | `src/blender_script.py` | 316–387 | Always on |

Supersampling is implicit (render_size / output_size ratio). With explicit controls, supersampling multiplier × output_size = render_size. User sets output_size and supersampling; render_size is computed. Or user overrides render_size directly in advanced.

## Project Structure

```
gui/
├── package.json              # Electron + Svelte deps
├── svelte.config.js
├── vite.config.js
├── electron/
│   ├── main.js               # Electron main process
│   ├── preload.js             # IPC bridge
│   └── python-bridge.js      # Spawn & communicate with cli.py
├── src/
│   ├── App.svelte             # Root layout
│   ├── lib/
│   │   ├── PathPicker.svelte  # Folder browse component
│   │   ├── DlcList.svelte     # Multi-select DLC picker
│   │   ├── ProfileBar.svelte  # Speed/Balance/Quality buttons
│   │   ├── Settings.svelte    # Advanced settings panel
│   │   ├── ProgressLog.svelte # Progress bar + log
│   │   └── stores.js          # Svelte stores for state
│   └── styles/
│       └── global.css         # Dark theme
└── build/                     # electron-builder output
```

## Implementation Order

### Phase 1: CLI additions (Python side)
1. Parameterize hardcoded values — make them function args passed from scanner
2. Add new CLI arguments to `cli.py`
3. Add `--json-progress` output mode to scanner
4. Add `--scan-only` mode
5. Add `--dlcs` filter
6. Test that existing behavior is unchanged with defaults

### Phase 2: Electron + Svelte scaffold
1. Initialize Electron + Svelte project in `gui/`
2. Set up electron main process with IPC
3. Create Python bridge module (spawn, stream stdout, kill)
4. Basic window: 1024×768, dark theme, no frame decorations

### Phase 3: UI components
1. PathPicker — folder browse with native dialogs
2. DlcList — multi-select with scan-only integration
3. ProfileBar — Speed/Balance/Quality with Custom state
4. Settings — collapsible advanced panel
5. ProgressLog — progress bar + scrolling log
6. Wire everything together in App.svelte

### Phase 4: Integration & polish
1. End-to-end test: pick folders → scan → select DLCs → process → see results
2. Error handling: Python not found, Blender not found, process crash
3. Remember last-used paths (electron-store)
4. App icon + title
