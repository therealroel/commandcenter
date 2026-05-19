import shutil


class CodexLauncher:
    def __init__(self, tmux_manager):
        self.tmux_manager = tmux_manager

    @classmethod
    def is_available(cls) -> bool:
        return False

    def launch(self, project_name: str, project_path: str) -> bool:
        return False