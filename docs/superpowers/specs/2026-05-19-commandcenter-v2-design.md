# CommandCenter - Design Specification

## Overview
**CommandCenter** is a MEGA PRO web-based dashboard for Thomas to control AI coding agents across multiple projects simultaneously. It replaces terminal-based TUI with a modern web interface featuring real-time streaming chat, system metrics, and project management.

---

## Design System

### Visual Style: Linear + Raycast + Grafana Hybrid
- **Background**: `#0d1117` (deep dark)
- **Card/Panel**: `#161b22` (elevated surface)
- **Border**: `#30363d` (subtle separation)
- **Text Primary**: `#e6edf3` (high contrast)
- **Text Secondary**: `#7d8590` (muted)
- **Accent Cyan**: `#00d9ff` (highlights)
- **Accent Green**: `#00ff88` (success/connected)
- **Accent Yellow**: `#ffaa00` (warning)
- **Accent Red**: `#ff4444` (error)
- **Accent Magenta**: `#ff00aa` (thinking)

### Typography
- **Font**: `SF Mono, Monaco, Consolas, monospace` (code feel)
- **Headings**: 16px bold
- **Body**: 14px regular
- **Small/Metrics**: 12px

### Layout
- **Header Bar**: Fixed top, contains branding, user greeting, weather
- **Main Content**: 60/40 or 50/50 split panels for project chats
- **Bottom Bar**: System metrics as floating cards

### Components
- **Chat Panels**: Rounded corners (8px), subtle shadow
- **Input Fields**: Dark background, glowing focus border
- **Status Dots**: Pulsing animation for active states
- **Message Bubbles**: User (right-aligned, cyan), AI (left-aligned, white)
- **Thinking Indicator**: Animated gradient bar

---

## Features

### 1. Split-Screen AI Chat (PRIMARY)
- Two panels side-by-side for robostock and routercontrol
- Each panel shows:
  - Project name with agent icon (opencode🟢, claude🔵, codex🟣)
  - Connection status indicator (pulsing dot)
  - Chat message history (scrollable)
  - Input field for user messages
  - Send button + Enter key support
- Real-time streaming of AI responses (WebSocket)
- Both sessions active simultaneously

### 2. Agent Switcher (Per-Project)
- Press `S` or click agent icon to cycle: opencode → claude → codex
- Visual feedback on switch (icon changes, panel restarts)
- Persisted in config/projects.json

### 3. System Metrics (Real-Time)
- **CPU**: Usage %, frequency, temperature, core count
- **RAM**: Used/Total GB, percentage
- **Disk**: Used/Total GB, percentage
- **Uptime**: Days, hours, minutes since boot
- Refresh rate: 1 second
- Color-coded status (green < 70%, yellow 70-90%, red > 90%)

### 4. Weather Widget
- Copenhagen weather via wttr.in
- Temperature, condition (☀️/🌧️/☁️), feels like
- Humidity, wind speed
- Auto-refresh: 5 minutes

### 5. Project Management
- Projects loaded from config/projects.json
- Fields: name, path, agent, launch_on_start
- Git status per project (branch, dirty state)
- Quick launch via keyboard shortcuts 1-9

### 6. Token Tracker (Visual Fuel Gauge)
- Context window usage as progress bar
- Color-coded: green (<50%), yellow (50-80%), red (>80%)
- Sparkline showing usage history
- Token count display

### 7. Event Log
- Timestamped events with type badges
- Types: TOOL, THINK, ERROR, INFO
- Color-coded with emojis
- Scrolling list, last 50 events

### 8. Quick Actions Bar
- Keyboard shortcuts displayed
- [1-2] Switch panels, [Enter] Send, [S] Switch agent, [Q] Quit
- Visual key hints

### 9. tmux Integration
- Each project session runs in tmux window (cc-projectname)
- Graceful fallback if tmux unavailable (use direct subprocess)
- Window listing and management

---

## Architecture

### Backend (Python Flask)
```
commandcenter/
├── server.py              # Flask + WebSocket server
├── config/
│   └── projects.json      # Project configurations
├── agents/
│   ├── switcher.py        # Agent cycling logic
│   └── wrappers/
│       ├── opencode.py    # opencode subprocess wrapper
│       ├── claude.py      # claude subprocess wrapper
│       └── codex.py       # codex subprocess wrapper
├── services/
│   ├── system.py          # psutil metrics gatherer
│   ├── weather.py         # wttr.in integration
│   ├── git.py             # Git status per project
│   └── tokens.py          # Token tracking
└── templates/
    └── index.html         # Single-page app
```

### Frontend (Vanilla HTML/CSS/JS)
- No framework dependencies
- WebSocket for real-time updates
- CSS Grid for layout
- CSS animations for status indicators
- Semantic HTML for accessibility

### WebSocket Events
| Event | Direction | Payload |
|-------|-----------|---------|
| chat_message | client→server | `{project, message}` |
| ai_response | server→client | `{project, chunk, done}` |
| metrics_update | server→client | `{cpu, ram, disk, ...}` |
| weather_update | server→client | `{temp, condition, ...}` |
| event_log | server→client | `{type, message, timestamp}` |

---

## Data Flow

### Chat Session
1. User types in project panel input
2. Frontend sends via WebSocket: `{"project": "robostock", "message": "analyze this"}`
3. Backend receives, finds correct agent wrapper
4. Agent wrapper spawns subprocess (tmux or direct)
5. Subprocess output streamed back via WebSocket
6. Frontend renders message in real-time

### Metrics Collection
1. Backend timer (1s interval) calls system gatherer
2. Results broadcast to all WebSocket clients
3. Frontend updates metric displays

---

## Configuration

### config/projects.json
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
  ]
}
```

---

## Success Criteria

1. ✅ Web dashboard loads in browser at http://localhost:8080
2. ✅ Both project panels show independently
3. ✅ Can type message and receive AI response streamed in real-time
4. ✅ System metrics update every second
5. ✅ Weather displays for Copenhagen
6. ✅ Agent switcher cycles through opencode→claude→codex
7. ✅ tmux integration works when available
8. ✅ Graceful degradation without tmux
9. ✅ Token tracker shows usage
10. ✅ Event log records session activity
11. ✅ Design matches Linear/Raycast aesthetic
12. ✅ Thomas greeted by name on load

---

## Technical Notes

- **Dependencies**: flask, flask-socketio, psutil, requests, websocket-client
- **Port**: 8080 (configurable)
- **No external CSS/JS frameworks** - keeps it fast and self-contained
- **Terminal fallback**: Python TUI version still available via `--tui` flag