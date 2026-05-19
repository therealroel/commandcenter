import json
import os


class ProjectsWidget:
    AGENT_EMOJI = {
        "opencode": "🟢",
        "claude": "🔵",
        "codex": "🟣",
    }

    def __init__(self, term, config_path="config/projects.json"):
        self.term = term
        self.config_path = config_path

    def load_projects(self) -> list[dict]:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_file = os.path.join(base_dir, self.config_path)
        with open(config_file, "r") as f:
            data = json.load(f)
        return data.get("projects", [])

    def render(self, selected_index=0, statuses=None) -> str:
        projects = self.load_projects()
        statuses = statuses or {}
        lines = []
        max_width = self.term.width or 80

        for i, project in enumerate(projects):
            name = project["name"]
            path = project["path"]
            agent = project.get("agent", "opencode")
            emoji = self.AGENT_EMOJI.get(agent, "⚪")
            status = statuses.get(name, "stopped")

            is_selected = i == selected_index
            is_running = status == "running"

            if is_running:
                indicator = f"● {name}"
                color = "#00ff88"
            else:
                indicator = f"○ {name}"
                color = "#7d8590"

            if is_selected:
                indicator = self.term.bold(indicator)
                color = self.term.bold(color)

            agent_text = f"{emoji} {agent.capitalize()}"

            path_display = path
            available_width = max_width - 4
            if len(path_display) > available_width:
                path_display = path_display[:available_width - 3] + "..."

            lines.append(f"  {indicator}")
            lines.append(f"    {agent_text} | {path_display}")

        return "\n".join(lines)