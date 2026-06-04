# CommandCenter - Development Roadmap

## Project Scope

CommandCenter is a **single-user, local mission-control dashboard for running
multiple AI coding agents (Claude, OpenCode, Codex) side-by-side** in real
terminals from one browser window.

**In scope:**
- Up to 3 live agent terminals (real PTYs, not a fake chat UI) in one view.
- Per-panel project + agent selection, persisted server-side and across refresh.
- tmux-backed session persistence so agents keep running when the tab closes.
- At-a-glance situational awareness: system metrics, git status, weather, events.
- Local Claude config switching (subscription ⇄ bedrock).

**Out of scope (by design):**
- Authentication / multi-user / remote hosting — it's for a trusted local machine.
- Native Windows (WSL only) — depends on Unix PTYs.
- Replacing each agent's own TUI — CommandCenter *hosts* the real terminal, it
  does not reimplement the agent experience.

## How CommandCenter Works (Intended Behavior)

1. **Launch** — `python server.py` starts Flask + Socket.IO (gevent) on
   `CC_PORT` (default 5050); open the dashboard in a browser.
2. **Panels** — Pick 1–3 panels. Each panel = one project + one agent =
   one tmux session named `cc-<project>-<panel>-<agent>`.
3. **Terminals are real** — Each panel streams a real PTY over WebSocket to
   xterm.js. Keystrokes, colors, and the agent's own TUI behave natively.
4. **Switching** — Clicking the agent button cycles **OpenCode → Claude →
   Codex**; switching project/agent kills that panel's old session and spawns
   the chosen one. The previous session stays alive in the background.
5. **Persistence** — Panel layout/state is saved to
   `config/settings.json` and is the source of truth on
   refresh; running agents survive tab close via their tmux sessions.
6. **Self-cleaning** — The idle janitor reaps never-used `cc-*` sessions after
   10 min (toggle with `auto_close_idle`) so stale sessions don't accumulate.
7. **Awareness rail** — The header continuously shows CPU/MEM/DISK/NET/uptime,
   per-project git branch + dirty state, weather, the active-config indicator
   (S/B), and an event log of agent activity.
8. **Shutdown** — Closing the browser does NOT stop agents; stop the server via
   its PID file or `pkill -f "python server.py"`.

## Completed Features

- Multi-panel agent terminals (1-3 panels)
- Agent cycling (OpenCode → Claude → Codex)
- Tmux session persistence
- Git status per panel
- System metrics with sparklines
- Project management via GUI
- Config switching (Subscription/Bedrock)
- Panel state persistence on refresh
- xclip integration for copy mode
- Desktop launcher installer
- Signal handlers for graceful shutdown
- Idle session auto-cleanup (tmux janitor)
- Integration test suite (`test_integration.py`, `test_fixes.py`, `test_panel_api.py`)

## Known Limitations

- **No authentication** — designed for trusted local networks
- **Windows not supported** — requires WSL
- **Session names are not private** — `cc-<project>-<panel>-<agent>` is visible in `tmux ls`/`ps`

## Potential Future Enhancements

- Authentication layer
- Expand automated test coverage (Socket.IO + PTY paths)
- Multiple config profiles (beyond just bedrock/subscription)
- Session recording/playback
- Team collaboration features
- Webhook integrations

## Architecture Notes

### Key Files

| File | Purpose |
|------|---------|
| `server.py` | Main entry — Flask + Socket.IO + agent spawning + tmux session lifecycle + idle janitor |
| `agents/switcher.py` | Project and agent configuration |
| `launcher/tmux.py` | Thin tmux probe — availability check + `cc-*` session listing only |
| `services/pty_bridge.py` | PTY to WebSocket bridge |
| `services/git.py` | Git status polling |
| `services/system.py` | System metrics collection |

### Panel State Persistence

Panel state (which project/agent per panel, plus the channel count) is:
1. Saved on every agent/layout change to `config/settings.json`
2. Loaded on page refresh from server (source of truth)
3. Synced with tmux session names for persistence

### Tmux Session Lifecycle

`launcher/tmux.py` is only a probe (is-available + list `cc-*` sessions). The
lifecycle is driven directly from `server.py`:
1. On `term_open`, the existing `cc-<project>-<panel>-<agent>` session is killed,
   then a fresh `tmux new-session` is spawned (window named after the agent).
2. Sessions persist across browser refresh; reattaching resumes the conversation.

### Idle Session Auto-Cleanup (`tmux_janitor`)

A background greenlet runs every 60s (gated on `auto_close_idle`). It kills a
`cc-*` session only when **all** hold:
1. Not bound to any open panel on a connected client (`_sessions_in_use()`).
2. Session age > 10 minutes (uses `session_started`, not activity time).
3. Pane still matches a `NEVER_USED_FINGERPRINTS` prompt (sign-in/welcome/etc).

### Config Switching

Switching between Subscription and Bedrock:
1. Copies `~/.claude/settings.json.bak-{timestamp}` (backup)
2. Replaces `settings.json` with the selected profile's backup
3. Invalidates config cache for immediate effect

## Contributing

1. Fork the repo
2. Create a feature branch
3. Test locally
4. Submit a pull request

## License

MIT