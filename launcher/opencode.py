import shutil
import subprocess


class OpencodeLauncher:
    def __init__(self, tmux_manager):
        self.tmux_manager = tmux_manager
        self.agent_cmd = "opencode"

    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("opencode") is not None

    def launch(self, project_name: str, project_path: str) -> bool:
        if not self.tmux_manager.create_window(project_name, project_path):
            return False
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"cc-{project_name}", self.agent_cmd, "C-m"],
                check=False,
                capture_output=True,
            )
            return True
        except Exception:
            return False