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

## Known Limitations

- **No authentication** — designed for trusted local networks
- **No tests** — manual testing required
- **Windows not supported** — requires WSL

## Potential Future Enhancements

- Authentication layer
- Automated test suite
- Multiple config profiles (beyond just bedrock/subscription)
- Session recording/playback
- Team collaboration features
- Webhook integrations

## Architecture Notes

### Key Files

| File | Purpose |
|------|---------|
| `server.py` | Main entry — Flask + Socket.IO + agent spawning |
| `agents/switcher.py` | Project and agent configuration |
| `launcher/tmux.py` | Tmux session lifecycle |
| `services/pty_bridge.py` | PTY to WebSocket bridge |
| `services/git.py` | Git status polling |
| `services/system.py` | System metrics collection |

### Panel State Persistence

Panel state (which project/agent per panel) is:
1. Saved on every agent switch to `~/.claude/commandcenter_settings.json`
2. Loaded on page refresh from server (source of truth)
3. Synced with tmux session names for persistence

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