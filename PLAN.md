# CommandCenter - Development Roadmap

## Completed Features

- Multi-panel agent terminals (1-3 panels)
- Agent cycling (Claude → OpenCode → Codex)
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

Panel state (which project/agent per panel) is:
1. Saved on every agent switch to `~/.claude/commandcenter_settings.json`
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