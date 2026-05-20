import shutil
import subprocess


class TmuxManager:
    def is_available(self) -> bool:
        return shutil.which("tmux") is not None

    def create_window(self, project_name: str, project_path: str) -> bool:
        if not self.is_available():
            return False
        try:
            subprocess.run(
                ["tmux", "new-window", "-t", f"cc-{project_name}", "-c", project_path, "-d"],
                check=False,
                capture_output=True,
            )
            return True
        except Exception:
            return False

    def window_exists(self, project_name: str) -> bool:
        if not self.is_available():
            return False
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-a"],
                check=False,
                capture_output=True,
                text=True,
            )
            return f"cc-{project_name}:" in result.stdout
        except Exception:
            return False

    def list_windows(self, prefix: str = "cc-") -> list[str]:
        if not self.is_available():
            return []
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-a"],
                check=False,
                capture_output=True,
                text=True,
            )
            windows = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 2 and prefix in parts[0]:
                    windows.append(parts[0])
            return windows
        except Exception:
            return []

    def close_window(self, project_name: str) -> bool:
        if not self.is_available():
            return False
        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", f"cc-{project_name}"],
                check=False,
                capture_output=True,
            )
            return True
        except Exception:
            return False