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

    def load_projects(self) -> list:
        with open(self.config_path, "r") as f:
            data = json.load(f)
        return data["projects"]

    def save_projects(self, projects: list) -> None:
        with open(self.config_path, "w") as f:
            json.dump({"projects": projects}, f, indent=2)

    def switch_agent(self, project_name: str) -> str:
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