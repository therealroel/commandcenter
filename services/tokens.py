from collections import deque


class TokenTracker:
    def __init__(self, max_tokens: int = 200000):
        self.max_tokens = max_tokens
        self.used = 0
        self._history = deque(maxlen=20)

    def update(self, used: int):
        self.used = used
        self._history.append(used)

    def get_status(self) -> dict:
        return {
            "used": self.used,
            "max": self.max_tokens,
            "percent": round((self.used / self.max_tokens) * 100, 1) if self.max_tokens else 0,
            "history": list(self._history),
        }
