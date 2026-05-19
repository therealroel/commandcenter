from blessed import Terminal


class QuickActionsWidget:
    def __init__(self, term, projects: list[dict], selected: int):
        self.term = term
        self.projects = projects
        self.selected = selected

    def render(self) -> str:
        parts = []
        primary_color = self.term.color_rgb(0xe6, 0xed, 0xf3)
        for i, project in enumerate(self.projects):
            idx = i + 1
            if i == self.selected:
                parts.append(f"{self.term.cyan(f'[{idx}]')} {self.term.cyan(project['name'])}")
            else:
                parts.append(f"{primary_color}[{idx}]{self.term.normal} {primary_color}{project['name']}{self.term.normal}")
        return " ".join(parts)
