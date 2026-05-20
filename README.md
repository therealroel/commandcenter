# ⚡ COMMANDCENTER

Web-based mission control dashboard for managing multiple AI coding agents (Claude, OpenCode, Codex) across projects.

## Features

- **Multi-panel terminals** - Run 1-3 AI agents side by side
- **Tmux session persistence** - Sessions survive browser refresh, instant resume
- **Real-time metrics** - CPU, RAM, disk, network monitoring
- **Project management** - Add/remove projects, switch agents per panel
- **Git status** - Live branch and dirty state indicators
- **Weather** - Current conditions with emoji
- **Event log** - Track agent activity (tools, errors, thinking)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python server.py

# Open http://localhost:5050
```

## Architecture

- **Flask + Socket.IO** - Real-time web server
- **xterm.js** - Terminal emulation in browser
- **PTY bridge** - Connects browser to tmux sessions
- **Gevent** - Async I/O for concurrent connections

## Project Structure

```
server.py           # Main Flask app + Socket.IO handlers
templates/
  index.html        # Single-page app (HTML + CSS + JS)
services/
  pty_bridge.py     # PTY ↔ WebSocket bridge
  system.py         # System metrics (psutil)
  weather.py        # Weather API (wttr.in)
  git.py            # Git status polling
  tokens.py         # Token usage tracking
agents/
  switcher.py       # Agent cycling (opencode/claude/codex)
launcher/
  tmux.py           # Tmux session management
config/
  projects.json     # Project configuration
```

## Keyboard Shortcuts

- `Ctrl+Alt+Tab` - Cycle focus between panels
- `1/2/3` buttons - Switch panel layout

## Environment Variables

- `CC_PORT` - Server port (default: 5050)
