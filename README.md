# ⚡ COMMANDCENTER

A mission-control dashboard for managing multiple AI coding agents side-by-side. Run Claude, OpenCode, and Codex in real terminal panels with live system metrics, git status, and session persistence.

![Dashboard Screenshot](screenshots/dashboard.png)

## Features

- **Multi-Panel Terminals** — Run 1-3 AI agents simultaneously in real xterm.js terminals
- **Agent Switching** — Cycle between Claude, OpenCode, and Codex per panel with one click
- **Tmux Persistence** — Sessions survive browser refresh; instant resume when you return
- **Live System Metrics** — CPU, RAM, disk, and network monitoring with sparkline graphs
- **Git Status** — Real-time branch name and dirty state indicators per project
- **Project Management** — Add/remove projects via file browser, switch projects per panel
- **Config Switching** — Hover on `S` (subscription) or `B` (bedrock) indicator to see logged-in user
- **Panel State Persistence** — Server saves panel state; reload page without losing layout
- **Idle Session Auto-Cleanup** — Never-used agent sessions are reaped after 10 min so stale tmux sessions don't pile up (toggleable)
- **Weather Display** — Current conditions in the header
- **Event Log** — Track agent activity (tool use, errors, thinking states)
- **Channel Badges** — See which projects are assigned to which panels (CH1, CH2, CH3)

## Requirements

- **Linux** or **macOS** (Windows requires WSL)
- Python 3.10+
- tmux (recommended for session persistence)
- **xclip** (for clipboard copy in tmux copy mode)
- Default browser (Firefox, Chrome, Edge, etc.)
- At least one AI coding agent installed

### Install Dependencies

```bash
# Ubuntu/Debian
sudo apt install tmux xclip

# macOS
brew install tmux xclip

# Python packages
pip install -r requirements.txt
```

### Supported Agents

| Agent | Command | Install |
|-------|---------|---------|
| Claude | `claude` | [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) |
| OpenCode | `opencode` | [opencode](https://github.com/opencode-ai/opencode) |
| Codex | `codex` | `npm install -g @openai/codex` |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/therealroel/commandcenter.git
cd commandcenter

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Run
python server.py

# Open http://localhost:5050
```

## Desktop Installation

Install as a standalone desktop application:

```bash
# Linux
./install-desktop.sh
commandcenter  # Run via launcher

# macOS
./install-desktop-macos.sh
# Open ~/Applications/CommandCenter.app or add to Dock
```

Windows requires WSL (native Windows not supported due to PTY limitations).

## Configuration

### Projects Setup

On first run, copy `config/projects.example.json` to `config/projects.json`:

```bash
cp config/projects.example.json config/projects.json
```

Or use the GUI: Press `+ ADD PROJECT` in the project palette to browse and add folders.

The `projects.json` file is gitignored — your private project settings are never pushed to the repo.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CC_PORT` | `5050` | Server port |
| `CC_WEATHER_CITY` | `Copenhagen` | City shown in the header weather widget (via wttr.in) |

### Settings File

Runtime settings (panel layout, auto-cleanup toggle) are stored in
`~/.claude/commandcenter_settings.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `auto_close_idle` | `true` | Auto-reap never-used agent sessions (see below) |
| `panels` | `{}` | Saved per-panel project/agent state |

### Idle Session Auto-Cleanup

A background janitor runs every 60s and kills `cc-*` tmux sessions that are:
1. **Not** bound to any open panel on a connected client, **and**
2. Older than **10 minutes**, **and**
3. Still sitting on a sign-in / welcome / "type a message" prompt (i.e. never
   actually used).

Sessions you're actively using are never touched. To disable, set
`auto_close_idle` to `false` in the settings file (or toggle it via the
`/api/settings/auto-close-idle` endpoint).

## Usage

### Panel Layout

Click **1**, **2**, or **3** in the projects strip to change the number of visible terminal panels.

### Switching Projects

- Click a project chip in the strip to open it in the focused panel
- Click the project name in a panel header to open the project palette
- Use **+ ADD PROJECT** to browse and add new project folders

### Switching Agents

Click the agent button in any panel header to cycle through: **OpenCode → Claude → Codex**

### Config Indicator (S/B)

Each panel shows an indicator for the active config:
- **S** = Subscription mode (Anthropic API)
- **B** = Bedrock mode (AWS)

**Hover over the indicator** to see the logged-in user email for subscription mode.

### Tmux Copy Mode

When in tmux, press `prefix` (default `Ctrl+b`) then `[` to enter copy mode:

- **Scroll** with arrow keys
- **Select text** with arrow keys + `Enter` or `v`
- **Copy** with `Enter` or `y` (sends to xclip)
- **Quit** with `q` or `Esc`

#### Recommended `~/.tmux.conf`

For mouse scrolling + drag-to-copy that **doesn't trap your keyboard**, install
the bundled config ([`config/tmux.conf`](config/tmux.conf)):

```bash
cat config/tmux.conf >> ~/.tmux.conf   # append to your existing config, OR
cp  config/tmux.conf  ~/.tmux.conf     # use it as your whole config
tmux source ~/.tmux.conf               # reload into the running server
```

It enables `mouse on`, drag-to-clipboard via xclip, and wheel bindings that pass
scrolling through to full-screen apps (Claude's TUI) instead of hijacking it.

> ⚠️ A bare `copy-mode` wheel binding drops **every** non-mouse app into copy
> mode on scroll, which swallows your keystrokes — you'd see a `[0/NNN]`
> indicator and be unable to type until you press `q`. The bundled config avoids
> this.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Alt+Tab` | Cycle focus between panels |
| `Shift+Scroll` | Scroll terminal history |

### Closing the App

Closing the browser tab does NOT stop your agents. They continue running in their tmux sessions.

To stop everything:

```bash
# Find the process
cat /tmp/commandcenter.pid

# Kill it
kill $(cat /tmp/commandcenter.pid)
```

Or use `pkill -f "python server.py"`.

## Architecture

```
commandcenter/
├── server.py              # Flask + Socket.IO server (main entry, tmux + janitor)
├── version.py             # __version__ (semantic versioning)
├── config_switch.py       # Standalone CLI to swap Claude bedrock/subscription config
├── agents/
│   └── switcher.py        # Agent cycling and project config
├── config/
│   ├── projects.json      # Your projects (gitignored)
│   ├── projects.example.json  # Template for new users
│   └── tmux.conf          # Recommended tmux config (scroll/copy, no copy-mode trap)
├── launcher/
│   └── tmux.py            # Thin tmux probe (availability + cc-* session list)
├── services/
│   ├── pty_bridge.py      # PTY ↔ WebSocket bridge (gevent reader)
│   ├── system.py          # System metrics via psutil
│   ├── weather.py         # Weather API (wttr.in)
│   └── git.py             # Git status polling
├── templates/
│   └── index.html         # Single-page app (HTML + CSS + JS)
├── test_integration.py    # End-to-end suite (boots a live server)
├── test_fixes.py          # Regression checks for past fixes
├── test_panel_api.py      # Panel-state API tests
├── install-desktop.sh     # Desktop launcher installer (Linux)
├── install-desktop-macos.sh  # Desktop launcher installer (macOS)
└── requirements.txt       # Python dependencies
```

### Tech Stack

- **Backend**: Flask + Flask-SocketIO on gevent
- **WebSocket**: gevent-websocket for real-time PTY communication
- **Frontend**: Vanilla JS, xterm.js, Socket.IO client
- **Terminal**: Real PTY via Python pty module, optional tmux wrapper

## Status Rail

The header shows real-time system metrics:

| Metric | Description |
|--------|-------------|
| **CPU** | Usage percentage with sparkline history |
| **MEM** | RAM usage with sparkline history |
| **DISK** | Disk usage and capacity |
| **NET** | Network RX/TX bandwidth |
| **UPTIME** | System uptime |
| **AGENTS** | Active panels in use, out of 3 (e.g. `2 / 3 ACTIVE`) |
| **EVENTS** | Event log count |

## Security Warning

**No authentication is built-in.** This app is designed for local use on a trusted network.

If you expose it publicly, anyone can:
- Execute commands in terminals
- Access projects and their data
- Use AI agents to perform actions on your behalf

Use behind a VPN or add your own authentication layer.

## Troubleshooting

### Agents not starting
- Check that the agent command is in your PATH
- Run `claude --version` (or `opencode --version`, `codex --version`) to verify

### Tmux sessions not persisting
- Verify tmux is installed: `tmux -V`
- Check tmux is running: `tmux list-sessions`

### An agent session disappeared on its own
- The idle janitor reaps `cc-*` sessions that are >10 min old and never used
  (still on a sign-in/welcome prompt). Sessions bound to an open panel are safe.
- To keep all sessions, set `auto_close_idle` to `false` in
  `~/.claude/commandcenter_settings.json`. See [Idle Session Auto-Cleanup](#idle-session-auto-cleanup).

### Copy mode not working
- Install xclip: `sudo apt install xclip` (or `brew install xclip` on macOS)
- Verify: `xclip --version`

### Panel state not persisting after refresh
- Server is source of truth — panel state is saved to `~/.claude/commandcenter_settings.json`
- If server restarts, state is reloaded from tmux sessions

### "subscription mode" shown instead of email
- Hover over the `S` indicator — it fetches auth status on hover
- If still shows "subscription mode", you're likely not logged in: `claude auth status`

## License

MIT