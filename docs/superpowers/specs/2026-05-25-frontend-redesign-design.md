# Frontend Redesign — Design Spec

**Date**: 2026-05-25  
**Status**: Draft  
**Author**: micha

## 1. Overview

Complete frontend rebuild for the TRPG investigator assistant. The current vanilla HTML/CSS/JS + `http.server` prototype is replaced with a FastAPI + HTMX + Tailwind CSS stack, serving four pages through a unified launcher.

### 1.1 Goals

- Single unified server (replace two conflicting `server.py` / `game_server.py`)
- Non-blocking async request handling
- Declarative frontend (HTMX) — minimize hand-written JS
- Consistent COC 1920s dark aesthetic via Tailwind CSS
- File browser for dynamic module/character/library selection
- WebSocket step-progress feedback during LLM calls
- Contextual user guides on every page
- PyInstaller-packable with no external runtime dependencies

### 1.2 Non-Goals

- Multi-user support (single-user local tool)
- Mobile-first responsive design (desktop primary)
- Real-time streaming of narrative text (step-level granularity only)

## 2. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Server framework | **FastAPI** | Async, built-in WebSocket, Jinja2, auto-docs, one `pip` dep |
| Frontend interactivity | **HTMX** (~14KB) | Declarative AJAX, zero hand-written DOM code, works without build step |
| CSS | **Tailwind CSS v4** | Utility-first, CDN in dev → standalone CSS in PyInstaller bundle |
| Templates | **Jinja2** (FastAPI built-in) | `base.html` layout inheritance, partial fragments for HTMX swaps |
| Real-time | **WebSocket** (FastAPI built-in) | Step-progress push during LLM processing |
| Packaging | **PyInstaller** | `--add-data` templates + static, `--hidden-import fastapi/uvicorn` |

### 2.1 Why Not...

- **React/Vue**: Adds Node.js toolchain, build step, and JS bundle. Overkill for a 4-page local app.
- **Flask**: Works but lacks async/WebSocket. FastAPI matches the async LLM-call pattern better.
- **Full CSS framework (Pico/Bulma)**: Would fight against COC custom aesthetic. Tailwind gives control.
- **Electron**: ~100MB+ overhead vs. zero with localhost + browser.

## 3. Code Separation

```
frontend/
├── server.py                  # FastAPI app entry point (NEW)
├── routers/
│   ├── __init__.py
│   ├── launcher.py            # Launcher page + pipeline API
│   ├── character.py           # Character creation API
│   ├── game.py                # Game loop API + WebSocket
│   ├── editor.py              # JSON editor API
│   └── files.py               # File browser API (shared)
├── templates/
│   ├── base.html              # Root layout (Tailwind CDN, nav, help toggle)
│   ├── launcher.html          # Launcher page
│   ├── character.html         # Character wizard (3 steps)
│   ├── game.html              # Game loop main interface
│   ├── editor.html            # JSON lightweight editor
│   └── partials/
│       ├── help-*.html        # Contextual help panels
│       ├── file-browser.html  # Reusable file/directory picker
│       └── step-indicator.html# Processing step progress bar
├── static/
│   ├── tailwind.css           # Localized Tailwind build (for prod)
│   └── images/                # Bundled placeholder images
└── (old files deleted after migration: character.html/css/js, game.html, json-editor.html, server.py, game_server.py)

src/                            # Game engine (UNCHANGED)
├── game_loop.py
├── llm.py
├── prompts.py
├── scenario_core.py
├── game/
├── library/
├── module_designer/
├── investigator/
├── config.py
└── ...
```

**Import direction**: `frontend/` imports from `src/`. `src/` never imports from `frontend/`. This keeps the game engine fully decoupled from the presentation layer.

## 4. Page Architecture

### 4.1 Launcher (`/`)

Three functional zones:

**A. Module Generation Wizard**
- Upload source document (.docx / .txt / .pdf) via file picker
- Select output module name and directory under `data/modules/`
- Checkbox-select pipeline steps (all or resume from step N)
- "Start Generation" button → `POST /api/pipeline/start` → WS pushes 18-step progress
- Download L1/L2/L3 JSON when complete
- Wraps existing `run_pipeline.py` CLI logic as web API

**B. Parameter Configuration**
- API Key input (persisted to `.env`)
- Model selection: `deepseek-v4-pro` / `deepseek-v4-flash` / custom
- Thinking toggle + reasoning effort dropdown
- Pipeline thresholds: `LLM_SLOW_THRESHOLD_MS`, `LLM_TIMEOUT_MS`
- Degradation policy: `DEGRADE_POLICY` dict editable
- Feature flags: `COMBAT_LLM_ENHANCEMENT`, debug mode
- Save/Load config to `config.json` (auto-restore on startup)

**C. Quick Navigation**
- Launch character creation → `/character`
- Launch game → `/game`
- Open JSON editor → `/editor`

### 4.2 Character Creation (`/character`)

3-step wizard (compressed from 5):

| Step | Content | HTMX Behavior |
|------|---------|---------------|
| 1 | Name, age, gender, appearance/description (LLM-assisted via `/llm` trigger), stat rolling (3D6*5) | `hx-post` roll returns new stat cards; `/llm` triggers LLM description generation |
| 2 | Occupation picker, skill list with +/- adjust, occupation/interest point tracking | `hx-get` loads occupation data; skill adjustments update point counters inline |
| 3 | Weapon/equipment management, backstory, preview summary, export JSON | `hx-post` export returns downloadable JSON blob |

LLM description trigger: textarea input ending in `/llm` → POST `/api/character/generate-description` → returns 150-char description.

### 4.3 Game Loop (`/game`)

Visual-novel-style immersive layout with two modes: **compact** (default) and **expanded**.

#### Compact Mode (Default)

- **Full-screen atmospheric image** (~70% viewport) — generic mood/ambiance illustration, not scene-bound. Comes from a curated `data/images/` pool. Crossfade transition on scene change.
- **HUD overlay** (top-left): Scene name + player HP/SAN/MIN stats. Minimal, semi-transparent.
- **Step indicator** (top-right): Monospace micro-text showing pipeline progress.
- **Compact narrative bar** (bottom): 2-3 lines of latest narrative text. Below it, a subtle input field + action button. The whole bar is clickable.

#### Expanded Mode

Triggered by clicking the narrative bar or ▲ button:
- **Slide-up panel** covers bottom 60-65% of viewport. Background image dims.
- Panel contains: **full scrollable chat history** (narrative + brief + skill results + timestamps), **expanded input area**, and **HUD info** (scene details, NPCs, exits).
- **Close**: ▼ button or clicking the dimmed image area above the panel.

#### Interaction Behaviors

| Trigger | Behavior |
|---------|----------|
| New narrative arrives | Compact bar text updates with brief highlight flash |
| Click narrative bar / ▲ | Slide-up panel (60% height) with full history |
| ▼ button / click image area | Slide-down panel, back to compact |
| Scene change | Image crossfade (CSS transition opacity 0.5s) |
| Step progress WS message | Top-right indicator updates step dots |
| "?" help icon | HUD top-right, hover tooltip with command reference |
| Debug commands | Result shown as special message type in panel |

#### HTMX Partial Updates (after turn completes)
- `#narrative-bar` ← latest narrative text (compact mode)
- `#chat-history` ← `hx-swap="beforeend"` append new messages (expanded mode, if panel open)
- `#hud-stats` ← player HP/SAN
- `#hud-scene` ← scene name
- `#scene-image` ← new image src with CSS transition (on scene change)
- `#step-indicator` ← WebSocket real-time (no HTMX)

#### Image System

Images are generic atmospheric art, NOT bound to specific scenes. Stored in `data/images/` with optional module-specific subdirectory. The backend selects an image based on tags/keywords (e.g., "train", "dark", "outdoor") from the current scene description, or rotates through a default pool. Falls back to a dark gradient placeholder if no images available.

### 4.4 JSON Editor (`/editor`)

Lightweight view/edit tool for module authors:

- **Left**: file tree (browse `data/modules/` for L1/L2/L3 JSON files)
- **Center**: tree view of JSON structure (collapsible nodes)
- **Right**: selected node form editor (key → value input)
- **Bottom bar**: validation status (schema check, dependency graph integrity, entity ID collisions)

Not a full JSON IDE. For complex edits, users export and use VS Code.

### 4.5 User Guide System

Each page includes a collapsible help panel (right sidebar or slide-out drawer):

- **Toggle**: `?` icon in top bar. State persisted in `localStorage`.
- **Content**: Context-sensitive — changes with current step on character wizard, shows command reference on game page.
- **Implementation**: Jinja2 partials (`partials/help-*.html`) loaded via `hx-get` on panel open.

## 5. File Selection System

Reusable file/directory browser component used across all pages.

### 5.1 API

```
GET /api/files?dir=data/modules
  → { files: [{name, path, ext}], dirs: [{name, path}], parent: "data" }
```

- Root-locked to project directory
- Whitelist extensions: `.json`, `.docx`, `.txt`, `.pdf`
- Path sanitization: reject `..` traversal

### 5.2 Usage Contexts

| Context | Selects | Mode | API Consumer |
|---------|---------|------|-------------|
| Pipeline source | `.docx` / `.txt` file | single file | `POST /api/pipeline/start` |
| Game module | `l1_test.json` / `l2_test.json` / `l3_test.json` | 3 files | `POST /api/game/init` |
| Investigator | `.json` character sheet | single file | `POST /api/game/init` |
| Libraries | weapons/enemies/bosses JSON | multi-select (core + extensions) | `POST /api/game/library` |

### 5.3 Frontend Component

HTMX-powered: click directory → `hx-get /api/files?dir=...` → swap listing. Breadcrumb path display. Selected files shown as tags/chips.

## 6. API Routes

### 6.1 Launcher & Pipeline

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Launcher page |
| `POST` | `/api/pipeline/start` | Start module generation (body: `{source, module_name, output_dir, steps[]}`) |
| `WS` | `/api/pipeline/progress` | Stream 18-step status updates |
| `POST` | `/api/config/save` | Save current config to `config.json` |
| `GET` | `/api/config/load` | Load saved config |

### 6.2 Character

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/character` | Character creation page |
| `GET` | `/character/step/{n}` | Render step N HTML fragment |
| `POST` | `/character/roll` | Roll stats, return stat card HTML |
| `POST` | `/character/generate-description` | LLM description generation |
| `POST` | `/character/export` | Export character JSON, return download |

### 6.3 Game

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/game` | Game loop page |
| `POST` | `/api/game/init` | Initialize game with selected module + character + libraries |
| `POST` | `/api/game/turn` | Process player turn, return narrative HTML |
| `GET` | `/api/game/state` | Full game state (player, scene, NPCs, exits) |
| `GET` | `/api/game/player-status` | Player HP/SAN/MP fragment |
| `GET` | `/api/game/scene` | Scene info fragment |
| `GET` | `/api/game/npcs` | NPC list fragment |
| `GET` | `/api/game/current-image` | Current scene image path/URL |
| `WS` | `/api/game/progress` | Turn processing step stream |
| `POST` | `/api/game/reset` | Reset game |

### 6.4 Editor

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/editor` | JSON editor page |
| `GET` | `/api/editor/load?path=...` | Load JSON file as tree |
| `POST` | `/api/editor/save` | Save edited JSON back to file |
| `POST` | `/api/editor/validate` | Validate JSON against schema |

### 6.5 Files (shared)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/files?dir=...` | List directory contents |

## 7. Server Architecture

Single `frontend/server.py` entry point:

```python
# Pseudocode structure
app = FastAPI()
app.mount("/static", StaticFiles(directory="frontend/static"))

# Routers
app.include_router(launcher.router)
app.include_router(character.router)
app.include_router(game.router)
app.include_router(editor.router)
app.include_router(files.router)

# Startup
@app.on_event("startup")
def init():
    load_config()
    # Libraries loaded lazily on first use
```

Dev server: `uvicorn frontend.server:app --reload --port 8080`  
Prod (PyInstaller): `uvicorn.run(app, host="127.0.0.1", port=8080)` then `webbrowser.open(url)`

## 8. Tailwind CSS Strategy

**Development**: CDN `<script src="https://cdn.tailwindcss.com">` in `base.html`. Custom theme config inline:
```js
tailwind.config = {
  theme: {
    extend: {
      colors: {
        parchment: { DEFAULT: '#d4c5a0', dark: '#1a1410', ... },
        aged: { gold: '#c9a060', brown: '#8b5a3c', ... },
      },
      fontFamily: { serif: ['Noto Serif SC', 'SimSun', 'serif'] },
    },
  },
}
```

**Production (PyInstaller)**: Build standalone CSS with Tailwind CLI, place in `frontend/static/tailwind.css`. Replace CDN script tag with `<link>` in prod template. Font files bundled in `frontend/static/fonts/`.

## 9. WebSocket Contract

### 9.1 Game Turn Progress

```
Server → Client (JSON):
  { "step": "parse",         "status": "running" }
  { "step": "parse",         "status": "done" }
  { "step": "judge",         "status": "running" }
  { "step": "judge",         "status": "done" }
  { "step": "enrich",        "status": "running" }  // parallel
  { "step": "combat_entry",  "status": "running" }  // parallel
  { "step": "enrich",        "status": "done" }
  { "step": "combat_entry",  "status": "done" }
  { "step": "standoff",      "status": "running" }  // optional
  { "step": "standoff",      "status": "done" }
  { "step": "curate",        "status": "running" }
  { "step": "curate",        "status": "done" }
  { "step": "narrate",       "status": "running" }
  { "step": "narrate",       "status": "done" }
  { "step": "complete" }
```

Client renders as horizontal step bar, fills each step when status="done".

### 9.2 Pipeline Progress

```
Server → Client (JSON):
  { "step": "1a", "name": "结构化提取", "status": "running" }
  { "step": "1a", "name": "结构化提取", "status": "done", "preview": "{...}" }
  ...
  { "step": "complete", "outputs": ["l1.json", "l2.json", "l3.json"] }
```

Client renders as vertical progress list with checkmarks.

## 10. Migration Plan

### Phase 1: Scaffold
1. Create `frontend/templates/`, `frontend/static/`, `frontend/routers/`
2. Write `frontend/server.py` with FastAPI app skeleton + static mount
3. Add `fastapi`, `uvicorn`, `jinja2` to requirements

### Phase 2: Pages (in order)
4. Launcher page (module wizard stub + config + nav)
5. Character creation wizard (3 steps)
6. Game loop interface (visual-novel layout: full-screen image + compact narrative bar + expandable chat panel + WS progress)
7. JSON editor (tree view + form edit)

### Phase 3: Wire Up
8. Connect pipeline API to existing `run_pipeline.py` logic
9. Connect game API to existing `game_loop.py` (already has `init_game()` / `run_turn()`)
10. Connect character API to existing `src/investigator/`
11. Connect editor API to file read/write + validation

### Phase 4: Polish
12. User guide partials for all pages
13. File browser component with path safety
14. Tailwind prod build for PyInstaller
15. Remove old `server.py`, `game_server.py`, `character.html/css/js`, `game.html`, `json-editor.html`

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| FastAPI + uvicorn packaging in PyInstaller | Test early; known working pattern with `--hidden-import` |
| Tailwind prod build requires Node.js | Generate once before packaging; commit the compiled CSS |
| HTMX may need supplemental JS for complex interactions | Alpine.js as lightweight fallback (~15KB, can be added without changing architecture) |
| WebSocket connection drops during long LLM calls | Client auto-reconnect with exponential backoff; WS is advisory (turn still completes via POST) |
| File system access from browser sandbox | This is a localhost app — full filesystem access via backend API is intended |

## 12. Resolved Design Decisions

- **Font bundling**: Bundle Noto Serif SC woff2 (~5MB) in `frontend/static/fonts/`. Fallback chain: Noto Serif SC → SimSun → serif. Worth the bundle cost for the 1920s aesthetic.
- **Image system**: Generic atmospheric images from `data/images/` (not scene-bound). Backend selects by keyword match on scene description or rotates default pool. Images are decorative mood-setters, not informational.
