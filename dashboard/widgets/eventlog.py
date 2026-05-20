class EventLogWidget:
    COLORS = {
        "tool_use": "#00d9ff",
        "thinking": "#ff00aa",
        "error": "#ff4444",
        "info": "#e6edf3",
    }
    LABELS = {
        "tool_use": "TOOL",
        "thinking": "THINK",
        "error": "ERROR",
        "info": "INFO",
    }
    EMOJIS = {
        "tool_use": "🔵",
        "thinking": "🟣",
        "error": "🔴",
        "info": "⚪",
    }
    MAX_EVENTS = 50

    def __init__(self, term, events: list[dict]):
        self.term = term
        self.events = events[-self.MAX_EVENTS:]

    def _fgcolor(self, hex_color):
        return self.term.white

    def render(self):
        lines = [f"EVENT LOG ({len(self.events)} events)", ""]
        for event in self.events:
            event_type = event.get("type", "info")
            timestamp = event.get("timestamp", "")
            message = event.get("message", "")
            color = self.COLORS.get(event_type, self.COLORS["info"])
            label = self.LABELS.get(event_type, "INFO")
            emoji = self.EMOJIS.get(event_type, "⚪")
            lines.append(f"[{timestamp}] {emoji} [{label}] {message}")
        return "\n".join(lines)
