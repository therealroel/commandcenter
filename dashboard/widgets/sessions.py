class SessionsWidget:
    def __init__(self, term, tmux_manager):
        self.term = term
        self.tmux_manager = tmux_manager

    def render(self):
        if not self.tmux_manager.is_available():
            return "tmux not available"

        windows = self.tmux_manager.list_windows("cc-")
        if not windows:
            return ""

        parts = []
        for i, window in enumerate(windows):
            name = window.replace("cc-", "")
            parts.append(f"[{i}] {name}")

        return " ".join(parts)