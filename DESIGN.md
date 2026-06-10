# CommandCenter Design Rules

Rules derived from bugs found and fixed in production. Every rule has a **Why** — a real regression that motivated it. When editing the UI, verify each rule still holds.

---

## Layout

### Grid body rows: `52px auto auto 1fr 34px`
- Row 1: stats bar (fixed 52px)
- Row 2: `#top-dock-row` (auto — collapses to header-only)
- Row 3: reserved
- Row 4: workspace (`1fr` — always fills remaining height)
- Row 5: footer (fixed 34px)

### Dock heads must NOT have `height: 100%`
**Why:** `height: 100%` on `.gmail-head`, `.docker-head`, or `.subs-head` inside a flex-column dock consumes the full dock height, leaving `0px` for the body. The terminal/email content becomes invisible.
**Rule:** Dock heads use natural height (content-driven). Only `min-height` is allowed.

### Collapsed docks share one flex row — use `flex: 1 1 0%`, no `max-width`
Collapsed state: `flex: 1 1 0%; order: -1` inside `#top-dock-row`.
**Why:** `flex: 1 1 0%` (basis=0) forces equal distribution: 2 collapsed→50% each, 3 collapsed→33% each, all on one row. `max-width: 50%` looks correct for 2 docks but breaks with 3 — the third item can't fit and wraps to its own row.
**Why `order: -1`:** Without it, collapsed docks sort by DOM order — if an expanded dock comes first, collapsed ones wrap to a new row instead of sharing the top row.

### Panel project names must truncate, not wrap
`.panel-project { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0 }`
`.panel-header { overflow: hidden; min-width: 0 }`
**Why:** In 3-panel layout, `aws-cloud-architecture` wrapped to two lines, expanding the header and compressing terminal height.

### Gmail summary floats left when collapsed
`#top-dock-row .gmail-dock.collapsed .gmail-summary { margin-left: 0 }`
**Why:** `margin-left: auto` on `.gmail-summary` pushes it right when the tabs (the flex siblings) are hidden on collapse. Visually inconsistent with CONTAINERS and CLAUDE SUBS which show status text left-aligned.

---

## Terminals

### Terminal auto-refit via ResizeObserver
A `ResizeObserver` on each `.term-host` calls `fit.fit()` on size change.
**Why:** `window.resize` only fires on viewport resize. Dock expand/collapse changes panel height without firing window resize — tmux stays at the old row count, leaving dead space below the status bar.

### tmux inner shell must be a login shell
`exec tmux new-session ... bash -lc '...'`
**Why:** Non-login shells inside tmux don't source `~/.bash_profile`, so `~/.opencode/bin` is missing from `$PATH`. `command -v opencode` returns false, the while-loop exits immediately, and the session drops to nothing.

### fnm + opencode PATH in outer shell
`fnm_setup = 'export PATH="$HOME/.opencode/bin:$HOME/.local/share/fnm:$PATH"; ...'`
**Why:** The outer PTY bash needs the PATH too for the `command -v` pre-check before spawning tmux.

### Project agent must be applied on rebind
When `rebindPanel(panelId, projectName)` is called, look up `proj.agent` and set `panels[panelId].agentIdx` BEFORE calling `applyProjectToPanel`.
**Why:** `applyProjectToPanel` used the saved panel agent (whatever was last used), ignoring the project's configured agent. Switching to `robostock` (agent=opencode) kept launching claude.

---

## Gmail Dock

### Loading bar — animation only during loading state
```css
.gmail-loading-bar { display: none; }
.gmail-dock.loading .gmail-loading-bar { display: block; animation: gmailLoadSlide 1.2s linear infinite; }
```
**Why:** Defining the animation on the base class (even with `opacity: 0`) keeps the GPU animating forever. Using `display: none → block` stops the animation when not loading.

### Loading class only on first connect
```js
if (!socketEverConnected) { dock.classList.add('loading'); }
socketEverConnected = true;
```
**Why:** Adding `.loading` in every `socket.on('connect')` re-triggered the spinner on every reconnect, even after data had loaded.

### Section IDs must match `activateTab()` lookup
`activateTab('invite')` looks for `#gmail-invite`. The section must be `id="gmail-invite"`, not `id="gmail-section-invite"`.
**Why:** Mismatched ID means `activateTab` silently finds nothing — clicking INVITE shows blank.

### GCP/AWS rule detection runs before LLM batch
`_classify_rules()` is the fallback AND the pre-filter — GCP/AWS rules run in `_classify_batch()` via early return. Senders routed to these tiers skip LLM classification entirely.
**Why:** LLM might route `devops@bonniernews.se` (Google Cloud PAM notifications) to ACTION or HIGH rather than GCP.

---

## Calendar

### Two-slot cache for instant TODAY/TMR switching
`_calendar_cache = { "0": today_data, "1": tmr_data }` — both days fetched at startup and stored.
Frontend holds `calCache = {0: null, 1: null}` — tab click uses cache instantly, no HTTP round-trip.
**Why:** Single-day fetch on tab click caused noticeable delay and a loading flash.

### Calendar refresh triggered by invite emails
`gmail_thread` detects `data.get("invite")` and spawns `gevent.spawn(_refresh_calendar)`.
**Why:** New meeting invites arrive in Gmail before they appear in calendar; polling alone creates a stale-calendar UX.

---

### Overlays and dropdowns must escape `overflow:hidden` and xterm stacking
Any popup (dropdown, tooltip, context menu) that can appear inside a panel must:
- Append to `document.body`, NOT to the trigger element
- Use `position: fixed` with `z-index: 9999`
- Position via `trigger.getBoundingClientRect()` at open time
**Why:** `.panel-header { overflow: hidden }` clips children that extend below the header. xterm.js canvas elements create their own stacking context that defeats `z-index < 1000` even on `position: absolute` siblings.

## Subagent Safety Rules

When dispatching implementation subagents, the brief must explicitly state:
1. **Do not add `height: 100%` to flex children** — destroys parent height calculation
2. **Do not replace `addEventListener` with `onclick` attributes** — strips event listeners on re-render
3. **Do not move animation declarations to base classes** — animates elements perpetually even when hidden
4. **Test with the HTML scraper (Chrome DevTools MCP) after making changes**
5. **Run `fit.fit()` after any layout change**, not just on `window.resize`
