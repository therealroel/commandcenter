# CommandCenter — Terminal Dashboard & Project Launcher

**Spec Version:** 2026-05-19
**Author:** thjo
**Status:** Draft

---

## 1. Concept & Vision

A **personal command center** that lives in the terminal — part real-time system dashboard, part project launcher, part conversation partner. When you fire it up, it greets you by name, shows you everything about your machine and world, and spins up AI agent sessions for your defined projects in split tmux panes.

It's not just a utility — it's **your cockpit**. Designed to feel alive, responsive, and a little magical. Every number updates in real-time. Every project is one command away. The kind of tool that makes you want to open a terminal just to look at it.

---

## 2. Design Language

### Aesthetic
- **Style:** Cyberpunk terminal — dark background (#0d1117), neon accents (cyan #00d9ff, magenta #ff00aa, green #00ff88), ASCII art headers
- **Font:** Monospace (system default) — use Unicode box-drawing characters for panels
- **Personality:** Greeting with name on start; subtle animated elements; warm but techy

### Color Palette
| Element | Color | Hex |
|---------|-------|-----|
| Background | Deep space | #0d1117 |
| Primary text | Ice white | #e6edf3 |
| Secondary text | Muted gray | #7d8590 |
| Accent cyan | Electric | #00d9ff |
| Accent magenta | Pulse | #ff00aa |
| Accent green | Matrix | #00ff88 |
| Warning | Amber | #ffaa00 |
| Error | Red | #ff4444 |

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│  ██████╗ ██╗     ██╗████████╗ ██████╗██╗  ██╗               │
│ ██╔════╝ ██║     ██║╚══██╔══╝██╔════╝██║  ██║               │
│ ██║  ███╗██║     ██║   ██║   ██║     ███████║               │
│ ██║   ██║██║     ██║   ██║   ██║     ██╔══██║               │
│ ╚██████╔╝███████╗██║   ██║   ╚██████╗██║  ██║               │
│  ╚═════╝ ╚══════╝╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝               │
│                                                             │
│  ▶ Welcome back, THOMAS!                                    │
│  ▶ System: Linux thjo 6.17.0 | Uptime: 3 days, 14:22        │
│  ▶ CPU: Intel i9-13900K @ 5.8GHz | 68°C | 34%              │
│  ▶ RAM: 14.2 GB / 64 GB | Disk: 892 GB / 2 TB              │
│  ▶ Weather: Copenhagen ☀️ 22°C | Feels like 24°C            │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  PROJECTS                      │  TMUX SESSIONS              │
│  ┌──────────────────────────┐  │  ┌────────────────────────┐ │
│  │ ● robostock              │  │  │ [0] robostock          │ │
│  │   /home/thjo/.../robostock│  │  │ [1] router-control    │ │
│  │   status: running         │  │  │ [2] ...               │ │
│  │ ● routercontrol          │  │  └────────────────────────┘ │
│  │   /home/thjo/.../routerctrl│                            │
│  │   status: running         │                            │
│  └──────────────────────────┘  │                            │
└─────────────────────────────────────────────────────────────┘
```

### Components
1. **Header Banner** — ASCII art "COMMANDCENTER" with neon glow effect
2. **Greeting Bar** — Personalized welcome with user name (Thomas), system uptime, current time (local + UTC + Copenhagen)
3. **System Metrics Panel** — Real-time CPU, RAM, disk, temperatures
4. **Weather Widget** — Current conditions from wttr.in
5. **Project List** — Scrollable list from projects.json with agent switcher (OpenCode ↔ Claude ↔ Codex per project)
6. **Session Manager** — Shows active tmux sessions for projects
7. **Git Status Panel** — Branch, dirty state, recent commits per project
8. **Token Tracker** — Real-time context/token usage per project with fuel gauge
9. **Live Event Log** — Stream of tool calls, decisions, agent actions
10. **Quick Actions Bar** — Hotkeys 1-9 to jump to/launch projects
11. **Status Bar** — Last refresh timestamp, connection status

---

## 3. Architecture

### Components
```
commandcenter/
├── commandcenter.py          # Main entry point
├── dashboard/
│   ├── __init__.py
│   ├── tui.py                # Blessed TUI render engine
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── header.py        # ASCII banner + greeting + multi-clock
│   │   ├── system.py        # CPU, RAM, disk metrics
│   │   ├── weather.py       # wttr.in integration
│   │   ├── projects.py      # Project list with agent switcher
│   │   ├── sessions.py      # Tmux session status
│   │   ├── gitstatus.py     # Branch, dirty, recent commits
│   │   ├── tokens.py        # Token/context usage tracker + sparkline
│   │   ├── eventlog.py      # Live event stream
│   │   └── quickactions.py  # Hotkey bar (1-9)
│   └── refresh.py            # Data refresh loop
├── launcher/
│   ├── __init__.py
│   ├── tmux.py              # Tmux session/window management
│   ├── opencode.py          # Opencode process launcher
│   ├── claude.py            # Claude Code process launcher
│   └── codex.py            # Codex process launcher (future)
├── config/
│   ├── __init__.py
│   └── projects.json        # Project definitions with agent preference
├── agents/
│   ├── __init__.py
│   └── switcher.py         # Switch agent per project, supports opencode/claude/codex
├── requirements.txt
└── README.md
```

### Data Flow
```
projects.json → ConfigLoader → Project list data
                                      ↓
System APIs (psutil) → SystemGatherer → TUI Widgets → Render (blessed)
                                      ↓
wttr.in (HTTP) → WeatherService → TUI Widgets
                                      ↓
tmux sockets → TmuxManager → Session status → Sessions widget
                                      ↓
User input → CommandHandler → TmuxManager / App controller
```

### Key Libraries
| Library | Purpose | Justification |
|---------|---------|---------------|
| `blessed` | TUI rendering | Best Python TUI lib, excellent keyboard handling |
| `psutil` | System metrics | Comprehensive system info, cross-platform |
| `requests` | HTTP client | For wttr.in weather API |

---

## 4. Features & Interactions

### Core Features

**F1: Greeting on Launch**
- On start, displays personalized ASCII art header
- Shows "Welcome back, THOMAS!" with current time
- Subtle fade-in animation for terminal warmth

**F2: Real-Time System Metrics (1s refresh)**
- CPU: usage %, clock speed, temperature, core count
- RAM: used/total GB, percentage
- Disk: used/total GB for root and key mounts
- System: hostname, OS, kernel, uptime

**F3: Weather Display (5min refresh)**
- Location: Copenhagen (hardcoded initially, extensible)
- Data: temperature, conditions, feels-like, humidity, wind
- Falls back gracefully if offline

**F4: Project Definitions (projects.json)**
```json
{
  "projects": [
    {
      "name": "robostock",
      "path": "/home/thjo/projects/robostock",
      "agent": "opencode",
      "launch_on_start": true
    },
    {
      "name": "routercontrol",
      "path": "/home/thjo/projects/router-control",
      "agent": "claude",
      "launch_on_start": true
    }
  ],
  "settings": {
    "weather_location": "Copenhagen",
    "weather_units": "metric"
  }
}
```

**F5: Tmux Project Sessions**
- Each `launch_on_start: true` project gets a tmux window
- Windows named after project: `cc-robostock`, `cc-routercontrol`
- Launched with `opencode` or `claude` command in project directory
- Sessions displayed in dashboard with running status

**F6: Agent Switcher (OpenCode ↔ Claude ↔ Codex)**
- Each project has a preferred agent: `opencode`, `claude`, or `codex`
- Switch agent per project via `s` key or menu
- Agent preference persisted in projects.json
- Visual indicator shows current agent per project (🟢 OpenCode / 🔵 Claude / 🟣 Codex)
- Codex support is extensible — add new providers by adding launcher/{provider}.py
- Our own switcher — Thomas has full control, no third-party dependency

**F7: Git Status Panel**
- Per-project: branch name, dirty state (*), recent commit (last 3)
- Updates on project selection or manual refresh
- Uses subprocess git commands

**F8: Token/Context Tracker with Sparkline**
- Per-project: context window usage %, token count
- Color-coded fuel gauge: green (<50%), yellow (50-80%), red (>80%)
- Shows per-request tokens and cumulative session total
- Sparkline history showing token usage trend over last 30 data points

**F9: Live Event Log**
- Streaming panel showing tool calls, decisions, agent actions
- Color-coded by event type (tool use, thinking, error, etc.)
- Last 50 events, scrollable
- Filter by project or event type

**F10: Quick Actions Bar**
- Hotkeys 1-9 mapped to first 9 projects
- Shows project index and name
- Press number to launch/select that project
- Current selection highlighted

### Interactions
| Action | Behavior |
|--------|----------|
| `Enter` on project | Launch agent session in new tmux window |
| `s` key on project | Switch agent (OpenCode ↔ Claude ↔ Codex) for that project |
| `1-9` keys | Quick-launch project by index |
| `r` key | Refresh all data manually |
| `g` key | Refresh git status for selected project |
| `q` or `Esc` | Quit gracefully (kill sessions? confirm) |
| `Tab` | Cycle focus between panels |
| `↑/↓` | Navigate project list |
| `Ctrl+C` | Force quit with confirmation |

### Edge Cases
- **tmux not installed:** Show error, offer to install, disable session features
- **opencode not found:** Warn but continue; show "opencode not in PATH" status
- **claude not found:** If claude selected and not found, offer to switch to opencode
- **codex not found:** If codex selected and not found, show "codex not in PATH" status
- **Weather API fails:** Show "Weather unavailable" with last-known state
- **Project path doesn't exist:** Mark as "PATH NOT FOUND" in red
- **Project already running in tmux:** Don't duplicate; show "already running"
- **Git repo not found:** Show "not a git repo" in project git panel
- **Token API unavailable:** Show "token tracking unavailable" — doesn't crash
- **No network:** All online services gracefully degrade with cached/offline state

---

## 5. File Manifest

### commandcenter.py
Main entry point. Initializes blessed Terminal, starts refresh loops, handles keyboard input, renders TUI.

### dashboard/tui.py
`Dashboard` class that manages layout regions (header, metrics, projects, sessions) and orchestrates rendering.

### dashboard/widgets/header.py
`HeaderWidget` — ASCII art rendering, greeting text, current time display (local + UTC + Copenhagen).

### dashboard/widgets/system.py
`SystemWidget` — Uses psutil to gather: CPU %, freq, temp, core count; RAM used/total; disk usage; uptime, hostname.

### dashboard/widgets/weather.py
`WeatherWidget` — Fetches from `wttr.in/Copenhagen?format=j1`, parses JSON, caches result.

### dashboard/widgets/projects.py
`ProjectsWidget` — Reads from projects.json, displays scrollable list, shows launch status, shows current agent per project (OpenCode/Claude indicator).

### dashboard/widgets/sessions.py
`SessionsWidget` — Queries tmux for active sessions matching `cc-*` prefix, shows running projects.

### dashboard/widgets/gitstatus.py
`GitStatusWidget` — Shows branch, dirty state, and last 3 commits for selected project.

### dashboard/widgets/tokens.py
`TokenWidget` — Displays context/token usage per project with color-coded fuel gauge + sparkline history.

### dashboard/widgets/eventlog.py
`EventLogWidget` — Live event stream: tool calls, decisions, errors. Last 50 events, scrollable, filterable.

### dashboard/widgets/quickactions.py
`QuickActionsWidget` — Hotkey bar showing 1-9 project indices, current selection highlighted.

### dashboard/refresh.py
`RefreshManager` — asyncio-based loop managing refresh intervals per data source.

### launcher/tmux.py
`TmuxManager` — Creates/destroys tmux windows, lists sessions, checks if session exists.

### launcher/opencode.py
`OpencodeLauncher` — Spawns opencode subprocess in specified directory within tmux window.

### launcher/claude.py
`ClaudeLauncher` — Spawns claude subprocess in specified directory within tmux window.

### launcher/codex.py
`CodexLauncher` — Spawns codex subprocess in specified directory within tmux window (future).

### agents/switcher.py
`AgentSwitcher` — Switch agent per project (opencode/claude/codex), persist preference to projects.json. Our own implementation, Thomas has full control.

### config/projects.json
Default project configuration with robostock and routercontrol pre-defined, agent field per project.

---

## 6. Technical Approach

### Language & Runtime
- **Python 3.10+** — Modern async support, excellent TUI ecosystem
- **tmux** — Terminal multiplexing for project sessions
- **blessed** — TUI rendering (successor to blessings)
- **psutil** — System metrics
- **requests** — Weather API calls

### Process Model
```
Main process (commandcenter.py)
├── TUI render loop (blessed Terminal)
├── Refresh loop (asyncio)
│   ├── System data (every 1s)
│   └── Weather data (every 5min)
└── Keyboard handler
    └── tmux window creation → opencode/claude/codex subprocess
```

### Tmux Integration
- Use `tmux new-window -t cc-{project}` to create named windows
- Launch opencode/claude with `tmux send-keys -t cc-{project} "{agent}" C-m`
- List sessions with `tmux list-windows -t cc` or `tmux list-sessions`

### Error Handling Strategy
- All external calls (tmux, opencode, HTTP) wrapped in try/except
- Graceful degradation: if tmux unavailable, disable session features
- Weather failures don't crash — show cached/unavailable state
- Logging to file for debugging: `~/.commandcenter/logs/`

---

## 7. Installation & Usage

### Prerequisites
```bash
pip install -r requirements.txt
tmux new -s commandcenter  # Test tmux is available
```

### Running
```bash
cd /home/thjo/projects/commandcenter
python commandcenter.py
```

### First-Launch Experience
1. ASCII banner animates in
2. "Welcome back, THOMAS!" greeting appears
3. System metrics start streaming in
4. Weather fetches (may show "Loading..." briefly)
5. Projects from projects.json load
6. tmux windows created for each `launch_on_start: true` project
7. AI agent sessions start in those windows (opencode or claude per project setting)

---

## 8. Success Criteria

- [ ] Launches with `python commandcenter.py` and displays TUI immediately
- [ ] Greeting shows user name (Thomas) prominently with multi-clock (local + UTC + Copenhagen)
- [ ] System metrics update every second without flicker
- [ ] Weather displays Copenhagen conditions with icon
- [ ] Projects list shows robostock and routercontrol from projects.json
- [ ] Agent switcher works per-project (OpenCode ↔ Claude ↔ Codex) with our own switcher
- [ ] `s` key toggles agent for selected project
- [ ] tmux sessions created with correct agent for each project
- [ ] Quick actions bar (1-9) launches correct project
- [ ] Git status panel shows branch, dirty state, last 3 commits
- [ ] Token tracker shows context usage with color-coded fuel gauge + sparkline
- [ ] Live event log streams tool calls and agent actions
- [ ] Keyboard navigation works (arrow keys, Enter, q to quit)
- [ ] Clean shutdown — tmux windows closed, no zombie processes
- [ ] Runs on Linux (current platform)
- [ ] Extensible: adding new AI provider just requires adding launcher/{provider}.py