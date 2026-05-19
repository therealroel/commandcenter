# CommandCenter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A terminal dashboard that greets Thomas by name, shows real-time system info + weather, and launches opencode sessions for robostock and router-control in tmux panes.

**Architecture:** Python 3.10+ TUI with blessed library for rendering, psutil for system metrics, wttr.in (HTTP) for weather, tmux for terminal multiplexing of project sessions. Single `commandcenter.py` entry point orchestrates the asyncio refresh loop and keyboard handling.

**Tech Stack:** Python 3.10+, blessed, psutil, requests, tmux

**Color Scheme (from spec):**
- Background: #0d1117
- Primary text: #e6edf3
- Secondary text: #7d8590
- Accent cyan: #00d9ff
- Accent magenta: #ff00aa
- Accent green: #00ff88
- Warning: #ffaa00
- Error: #ff4444

---

## File Map

| File | Purpose | Lines/Complexity |
|------|---------|-----------------|
| `requirements.txt` | Dependencies | 3 lines |
| `commandcenter.py` | Entry point, main loop, keyboard | ~150 |
| `dashboard/__init__.py` | Package marker | empty |
| `dashboard/tui.py` | Layout regions, blessed Terminal init, render orchestration | ~120 |
| `dashboard/refresh.py` | RefreshManager with asyncio, interval management | ~80 |
| `dashboard/widgets/__init__.py` | Package marker | empty |
| `dashboard/widgets/header.py` | ASCII banner, greeting "Welcome back, THOMAS!", current time | ~60 |
| `dashboard/widgets/system.py` | CPU (%, freq, temp, cores), RAM (used/total GB), disk, uptime, hostname | ~100 |
| `dashboard/widgets/weather.py` | wttr.in/Copenhagen?format=j1, parse JSON, cache result | ~80 |
| `dashboard/widgets/projects.py` | Load projects.json, display scrollable list, show launch status | ~90 |
| `dashboard/widgets/sessions.py` | Query tmux for cc-* windows, show running projects | ~70 |
| `launcher/__init__.py` | Package marker | empty |
| `launcher/tmux.py` | TmuxManager: create window (`cc-{name}`), list windows, check exists | ~100 |
| `launcher/opencode.py` | OpencodeLauncher: spawn opencode in tmux window at project path | ~60 |
| `config/__init__.py` | Package marker | empty |
| `config/projects.json` | Project list: robostock, routercontrol with paths | ~20 |

---

## Task 1: Project scaffold and dependencies

**Context:** This creates the directory structure, all `__init__.py` files, requirements.txt, projects.json with robostock and routercontrol pre-defined, and a stub commandcenter.py that prints the greeting.

**Files:**
- Create: `requirements.txt`
- Create: `config/__init__.py`
- Create: `config/projects.json` — must contain robostock (path: `/home/thjo/projects/robostock`) and routercontrol (path: `/home/thjo/projects/router-control`), both with `launch_on_start: true`
- Create: `dashboard/__init__.py`
- Create: `dashboard/widgets/__init__.py`
- Create: `launcher/__init__.py`
- Create: `commandcenter.py` — prints "CommandCenter starting..." then "Welcome back, Thomas!"

- [ ] **Step 1: Create requirements.txt**
```txt
blessed>=21.0.0
psutil>=5.9.0
requests>=2.28.0
```

- [ ] **Step 2: Create config/projects.json**
```json
{
  "projects": [
    {
      "name": "robostock",
      "path": "/home/thjo/projects/robostock",
      "launch_on_start": true
    },
    {
      "name": "routercontrol",
      "path": "/home/thjo/projects/router-control",
      "launch_on_start": true
    }
  ],
  "settings": {
    "weather_location": "Copenhagen",
    "weather_units": "metric"
  }
}
```

- [ ] **Step 3: Create all __init__.py files** (empty)

- [ ] **Step 4: Create commandcenter.py stub**
```python
#!/usr/bin/env python3
import sys

def main():
    print("CommandCenter starting...")
    print("Welcome back, Thomas!")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Install dependencies and test stub**
```bash
pip install -r requirements.txt
python commandcenter.py
```
Expected: prints greeting, exits cleanly

- [ ] **Step 6: Commit**
```bash
git add requirements.txt config/projects.json commandcenter.py dashboard/ launcher/ config/__init__.py
git commit -m "feat: project scaffold with dependencies"
```

---

## Task 2: Header widget with ASCII art and Thomas greeting

**Context:** The header is the first thing Thomas sees. It shows a cyberpunk ASCII art "COMMANDCENTER" banner using box-drawing characters, followed by "Welcome back, THOMAS!" and the current time. The color scheme uses cyan (#00d9ff) for the banner text. This widget is used by the Dashboard class in tui.py.

**Files:**
- Create: `dashboard/widgets/header.py`

**Class/Function signatures (do not change):**
```python
class HeaderWidget:
    def __init__(self, term): ...
    def render(self): -> str: ...
    @property
    def height(self) -> int: ...
```

- [ ] **Step 1: Write dashboard/widgets/header.py**
- ASCII art banner (use Unicode box-drawing: `╔ ╗ ╚ ╝ ═ ║`, and fill chars `█ ▓ ▒ ░` for style)
- Banner text: "COMMANDCENTER" in a box
- Below banner: "▶ Welcome back, THOMAS!" in accent cyan
- Below that: "  System: {hostname} {kernel} | Uptime: {uptime}" in primary text
- Current time displayed as "  {HH:MM:SS}" in secondary text, updated each render call
- `height` property returns total lines rendered

- [ ] **Step 2: Test header renders without errors**
```bash
python -c "from dashboard.widgets.header import HeaderWidget; from blessed import Terminal; h = HeaderWidget(Terminal()); print(h.render())"
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/widgets/header.py && git commit -m "feat: ASCII header widget with Thomas greeting"
```

---

## Task 3: System metrics widget

**Context:** Displays real-time system information using psutil. Refresh rate is every 1 second (managed by RefreshManager in Task 8). Shows CPU usage %, frequency, temperature, core count; RAM used/total GB and %; disk usage for root mount; system hostname, OS, kernel version, and uptime. Color coding: values in accent green when normal, amber when elevated (>70%), red when critical (>90%).

**Files:**
- Create: `dashboard/widgets/system.py`

**Class/Function signatures (do not change):**
```python
class SystemGatherer:
    def __init__(self): ...
    def get_cpu(self) -> dict: ...  # keys: percent, freq_mhz, temp_c, cores
    def get_ram(self) -> dict: ...  # keys: used_gb, total_gb, percent
    def get_disk(self) -> dict: ...  # keys: used_gb, total_gb, percent, mount
    def get_system(self) -> dict: ...  # keys: hostname, os, kernel, uptime_str

class SystemWidget:
    def __init__(self, term, gatherer: SystemGatherer): ...
    def render(self) -> str: ...
```

- [ ] **Step 1: Write dashboard/widgets/system.py with SystemGatherer and SystemWidget classes**

- [ ] **Step 2: Test metrics are returned correctly**
```bash
python -c "
from dashboard.widgets.system import SystemGatherer
g = SystemGatherer()
print('CPU:', g.get_cpu())
print('RAM:', g.get_ram())
print('Disk:', g.get_disk())
print('System:', g.get_system())
"
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/widgets/system.py && git commit -m "feat: system metrics widget with psutil"
```

---

## Task 4: Weather widget

**Context:** Fetches current weather from wttr.in for Copenhagen using the J1 JSON format endpoint: `https://wttr.in/Copenhagen?format=j1`. Cache the result for 5 minutes to avoid excessive API calls. If fetch fails, return a cached dict with `error: True` and show "Weather unavailable" in the UI.

**Files:**
- Create: `dashboard/widgets/weather.py`

**Class/Function signatures (do not change):**
```python
class WeatherService:
    def __init__(self, location: str = "Copenhagen", units: str = "metric"): ...
    def get_current(self) -> dict: ...  # keys: temp_c, feels_like_c, condition, humidity, wind_kph, icon

class WeatherWidget:
    def __init__(self, term, service: WeatherService): ...
    def render(self) -> str: ...
```

- [ ] **Step 1: Write dashboard/widgets/weather.py with WeatherService and WeatherWidget**

- [ ] **Step 2: Test weather fetch works**
```bash
python -c "
from dashboard.widgets.weather import WeatherService
s = WeatherService()
w = s.get_current()
print(w)
"
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/widgets/weather.py && git commit -m "feat: weather widget with wttr.in integration"
```

---

## Task 5: Projects list widget

**Context:** Reads from `config/projects.json` and displays the project list. Each project shows: name with status indicator (● running in green, ○ stopped in gray), path (truncated if needed), and status text. The widget tracks launch status (running/stopped) via a status dictionary passed in. Supports selection via keyboard.

**Files:**
- Create: `dashboard/widgets/projects.py`

**Class/Function signatures (do not change):**
```python
class ProjectsWidget:
    def __init__(self, term, config_path: str = "config/projects.json"): ...
    def load_projects(self) -> list: ...  # list of dicts with name, path, launch_on_start
    def render(self, selected_index: int = 0, statuses: dict = None) -> str: ...
    # statuses: dict mapping project_name -> "running" | "stopped" | "not_found"
```

- [ ] **Step 1: Write dashboard/widgets/projects.py**

- [ ] **Step 2: Test project list loads**
```bash
python -c "
from dashboard.widgets.projects import ProjectsWidget
from blessed import Terminal
p = ProjectsWidget(Terminal())
projects = p.load_projects()
for proj in projects:
    print(proj)
"
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/widgets/projects.py && git commit -m "feat: projects list widget"
```

---

## Task 6: Tmux manager and opencode launcher

**Context:** Handles tmux session/window management for launching opencode sessions. TmuxManager creates windows named `cc-{project_name}` in the current tmux server. OpencodeLauncher spawns an opencode subprocess in that window. If tmux is not available, TmuxManager methods return False/empty gracefully without crashing.

**Files:**
- Create: `launcher/tmux.py`
- Create: `launcher/opencode.py`

**Class/Function signatures (do not change):**
```python
class TmuxManager:
    def __init__(self): ...
    def is_available(self) -> bool: ...
    def create_window(self, project_name: str, project_path: str) -> bool: ...
    def window_exists(self, project_name: str) -> bool: ...
    def list_windows(self, prefix: str = "cc-") -> list[str]: ...
    def close_window(self, project_name: str) -> bool: ...

class OpencodeLauncher:
    def __init__(self, tmux_manager: TmuxManager): ...
    def launch(self, project_name: str, project_path: str) -> bool: ...
    def is_opencode_available(self) -> bool: ...
```

- [ ] **Step 1: Write launcher/tmux.py**
- Use subprocess.run with ['tmux', 'list-windows', '-a'] to check availability
- `create_window`: `tmux new-window -t cc-{project_name} -c {project_path} -d` (detached)
- `window_exists`: `tmux list-windows -a` grep for `cc-{project_name}:`
- `list_windows`: parse `tmux list-windows -a` output for `cc-*` prefixes
- `close_window`: `tmux kill-window -t cc-{project_name}`

- [ ] **Step 2: Write launcher/opencode.py**
- `is_opencode_available`: check if opencode is in PATH via shutil.which
- `launch`: first create tmux window, then `tmux send-keys -t cc-{project_name} "opencode" C-m` to type opencode and press Enter

- [ ] **Step 3: Test tmux integration**
```bash
python -c "
from launcher.tmux import TmuxManager
tm = TmuxManager()
print('tmux available:', tm.is_available())
if tm.is_available():
    print('windows:', tm.list_windows())
"
```

- [ ] **Step 4: Commit**
```bash
git add launcher/tmux.py launcher/opencode.py && git commit -m "feat: tmux manager and opencode launcher"
```

---

## Task 7: Sessions status widget

**Context:** Shows currently active tmux sessions/windows that match the `cc-*` prefix. Displays running project names with an index number in brackets. Updates from tmux state on each render call.

**Files:**
- Create: `dashboard/widgets/sessions.py`

**Class/Function signatures (do not change):**
```python
class SessionsWidget:
    def __init__(self, term, tmux_manager: TmuxManager): ...
    def render(self) -> str: ...
```

- [ ] **Step 1: Write dashboard/widgets/sessions.py**

- [ ] **Step 2: Test sessions widget**
```bash
python -c "
from launcher.tmux import TmuxManager
from dashboard.widgets.sessions import SessionsWidget
from blessed import Terminal
tm = TmuxManager()
s = SessionsWidget(Terminal(), tm)
print(s.render())
"
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/widgets/sessions.py && git commit -m "feat: sessions status widget"
```

---

## Task 8: TUI integration and refresh loop

**Context:** This is the core rendering engine. Uses blessed Terminal to manage the full-screen TUI. The Dashboard class arranges header (top), system+weather (middle-left), projects (middle-right-top), sessions (middle-right-bottom), and a status bar (bottom). RefreshManager uses asyncio to refresh system data every 1 second and weather data every 5 minutes. All widgets receive the blessed Terminal for consistent styling.

**Files:**
- Create: `dashboard/tui.py`
- Create: `dashboard/refresh.py`

**Class/Function signatures (do not change):**
```python
class Dashboard:
    def __init__(self, term): ...
    def render(self) -> None: ...  # calls term.clear() then prints all widget outputs
    def handle_input(self, key) -> str | None: ...  # returns action: "quit" | "refresh" | "select_next" | "select_prev"

class RefreshManager:
    def __init__(self, dashboard: Dashboard, weather_service: WeatherService, system_gatherer: SystemGatherer): ...
    async def start(self) -> None: ...
    def stop(self) -> None: ...
```

- [ ] **Step 1: Write dashboard/refresh.py with RefreshManager**

- [ ] **Step 2: Write dashboard/tui.py with Dashboard**

- [ ] **Step 3: Test dashboard renders without errors (headless test)**
```bash
python -c "
from blessed import Terminal
from dashboard.tui import Dashboard
term = Terminal()
with term.fullscreen():
    d = Dashboard(term)
    # Just verify render() doesn't throw
    d.render()
print('Dashboard render OK')
"
```

- [ ] **Step 4: Commit**
```bash
git add dashboard/tui.py dashboard/refresh.py && git commit -m "feat: TUI dashboard layout and refresh loop"
```

---

## Task 9: Main entry point with keyboard handling and startup launch

**Context:** The final integration. `commandcenter.py` becomes the full application. On startup: initialize all services (TmuxManager, OpencodeLauncher, WeatherService, SystemGatherer), load projects from projects.json, launch opencode sessions for all `launch_on_start: true` projects in tmux windows (non-blocking), then start the TUI with keyboard handling. Keyboard: q/Esc quits, r refreshes, Tab cycles focus, arrows navigate.

**Files:**
- Modify: `commandcenter.py`

**Main loop structure:**
```python
async def main():
    term = Terminal()
    tmux_mgr = TmuxManager()
    opencode = OpencodeLauncher(tmux_mgr)
    weather_svc = WeatherService()
    system_gatherer = SystemGatherer()
    dashboard = Dashboard(term)
    refresh_mgr = RefreshManager(dashboard, weather_svc, system_gatherer)

    # Launch configured projects
    projects = load_projects()
    for proj in projects:
        if proj.get('launch_on_start'):
            opencode.launch(proj['name'], proj['path'])

    # Start refresh loop
    refresh_task = asyncio.create_task(refresh_mgr.start())

    # TUI input loop
    with term.cbreak():
        while True:
            key = term.inkey(timeout=0.1)
            action = dashboard.handle_input(key)
            if action == 'quit':
                break
            dashboard.render()

    refresh_mgr.stop()
    await refresh_task
```

- [ ] **Step 1: Replace commandcenter.py stub with full implementation**

- [ ] **Step 2: Run full app test (may need tmux)**
```bash
cd /home/thjo/projects/commandcenter
timeout 5 python commandcenter.py 2>&1 || true
```

- [ ] **Step 3: Commit**
```bash
git add commandcenter.py && git commit -m "feat: main entry point with keyboard handling and project launch"
```

---

## Spec Coverage Check

- [x] Greeting on launch (Task 1 stub + Task 2 header)
- [x] Real-time system metrics (Task 3)
- [x] Weather display (Task 4)
- [x] Projects list from JSON (Task 5)
- [x] Tmux project sessions (Task 6)
- [x] Session status widget (Task 7)
- [x] TUI with blessed (Task 8)
- [x] Keyboard handling: q/ESC/r/Tab/arrows (Task 9)
- [x] Startup launch of configured projects (Task 9)

## Self-Review

- [x] All class/function signatures defined and consistent across tasks
- [x] No placeholder TODOs in any step
- [x] Exact file paths in every step
- [x] Color hex codes from spec applied in widgets
- [x] Uptime, hostname, kernel from spec under SystemMetrics
- [x] Copenhagen wttr.in weather with J1 JSON format
- [x] tmux window naming: `cc-{project_name}`
- [x] Projects pre-loaded: robostock (/home/thjo/projects/robostock) and routercontrol (/home/thjo/projects/router-control)
- [x] Thomas greeting in header