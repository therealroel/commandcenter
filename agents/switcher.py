import json
import os

AGENT_CYCLE = ["opencode", "claude", "codex"]
AGENT_EMOJI = {
    "opencode": "🟢",
    "claude": "🔵",
    "codex": "🟣"
}
AGENT_DISPLAY = {agent: f"{AGENT_EMOJI[agent]} {agent}" for agent in AGENT_CYCLE}


class AgentSwitcher:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config", "projects.json")
        self.config_path = os.path.abspath(config_path)
        self.example_path = os.path.join(os.path.dirname(self.config_path), "projects.example.json")

    def _ensure_config(self) -> None:
        """Create projects.json on first run so the app always has a config.

        Seeds from projects.example.json when present, otherwise writes an
        empty project list. This is what lets us keep the user's real
        projects.json out of git — it's regenerated locally on demand.
        """
        if os.path.exists(self.config_path):
            return
        seed = {"projects": []}
        try:
            if os.path.exists(self.example_path):
                with open(self.example_path, "r") as f:
                    seed = json.load(f)
        except Exception:
            seed = {"projects": []}
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(seed, f, indent=2)

    def load_projects(self) -> list:
        self._ensure_config()
        with open(self.config_path, "r") as f:
            data = json.load(f)
        return data["projects"]

    def save_projects(self, projects: list) -> None:
        with open(self.config_path, "w") as f:
            json.dump({"projects": projects}, f, indent=2)

    def switch_agent(self, project_name: str) -> str:
        """Cycle to the next agent for a project."""
        projects = self.load_projects()
        for project in projects:
            if project["name"] == project_name:
                current = project.get("agent", "opencode")
                next_index = (AGENT_CYCLE.index(current) + 1) % len(AGENT_CYCLE)
                new_agent = AGENT_CYCLE[next_index]
                project["agent"] = new_agent
                self.save_projects(projects)
                return new_agent
        raise ValueError(f"Project '{project_name}' not found")

    def set_agent(self, project_name: str, agent: str) -> str:
        """Set a specific agent for a project."""
        if agent not in AGENT_CYCLE:
            raise ValueError(f"Unknown agent: {agent}")
        projects = self.load_projects()
        for project in projects:
            if project["name"] == project_name:
                project["agent"] = agent
                self.save_projects(projects)
                return agent
        raise ValueError(f"Project '{project_name}' not found")