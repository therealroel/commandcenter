from blessed import Terminal


class Dashboard:
    def __init__(self, term):
        self.term = term
        self._selected_index = 0
        self._system_metrics = None
        self._weather_data = None
        self._project_statuses = {}

        from dashboard.widgets.header import HeaderWidget
        from dashboard.widgets.system import SystemWidget, SystemGatherer
        from dashboard.widgets.weather import WeatherWidget, WeatherService
        from dashboard.widgets.projects import ProjectsWidget
        from dashboard.widgets.sessions import SessionsWidget
        from dashboard.widgets.quickactions import QuickActionsWidget
        from dashboard.widgets.tokens import TokenWidget

        self.header = HeaderWidget(term)
        gatherer = SystemGatherer()
        self.system = SystemWidget(term, gatherer)
        self.weather_widget = WeatherWidget(term, WeatherService())
        self.projects = ProjectsWidget(term)
        self.tmux_manager = TmuxManager() if hasattr(TmuxManager, 'is_available') else None
        self.sessions = SessionsWidget(term, self.tmux_manager or DummyTmuxManager())
        self.quickactions = QuickActionsWidget(term, [], 0)
        self.tokens = TokenWidget(term, [])

    def update_system_metrics(self, cpu=None, ram=None, disk=None, system=None):
        if cpu:
            self._system_metrics = {'cpu': cpu, 'ram': ram, 'disk': disk, 'system': system}
            self.system.gatherer._cpu_cache = cpu
            self.system.gatherer._ram_cache = ram
            self.system.gatherer._disk_cache = disk
            self.system.gatherer._system_cache = system

    def update_weather(self, weather_data):
        self._weather_data = weather_data

    def render(self) -> None:
        self.term.clear()
        output = []
        output.append(self.header.render())
        output.append("")

        system_output = self.system.render()
        if isinstance(system_output, list):
            output.extend(system_output)
        else:
            output.append(system_output)

        weather_output = self.weather_widget.render()
        output.append(f"Weather: {weather_output}")
        output.append("")

        projects_output = self.projects.render(self._selected_index, self._project_statuses)
        output.append(f"Projects:\n{projects_output}")
        output.append("")

        sessions_output = self.sessions.render()
        output.append(f"Sessions: {sessions_output}")
        output.append("")

        quickactions_output = self.quickactions.render()
        output.append(f"Actions: {quickactions_output}")

        print("\n".join(output))

    def handle_input(self, key) -> str | None:
        if key in ('q', 'KEY_ESCAPE'):
            return "quit"
        elif key == 'r':
            return "refresh"
        elif key == 'KEY_DOWN':
            return "select_next"
        elif key == 'KEY_UP':
            return "select_prev"
        return None


class TmuxManager:
    def is_available(self):
        import subprocess
        try:
            subprocess.run(["tmux", "list-windows"], capture_output=True, timeout=1)
            return True
        except Exception:
            return False

    def list_windows(self, prefix=""):
        import subprocess
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-F", "#{window_name}"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                windows = [w for w in result.stdout.strip().split("\n") if w.startswith(prefix)]
                return windows
        except Exception:
            pass
        return []


class DummyTmuxManager:
    def is_available(self):
        return False

    def list_windows(self, prefix=""):
        return []