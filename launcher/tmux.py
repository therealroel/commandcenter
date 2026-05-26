import shutil
import subprocess


class TmuxManager:
    """Lightweight tmux probe used by /health and the janitor.

    Live session lifecycle (cc-<project>-<panel>-<agent>) is driven directly
    from server.py via subprocess — this class only answers "is tmux here"
    and "how many cc-* sessions are around right now".
    """

    def is_available(self) -> bool:
        return shutil.which("tmux") is not None

    def list_windows(self, prefix: str = "cc-") -> list[str]:
        if not self.is_available():
            return []
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                check=False,
                capture_output=True,
                text=True,
            )
            return [
                line
                for line in result.stdout.strip().splitlines()
                if line.startswith(prefix)
            ]
        except Exception:
            return []
