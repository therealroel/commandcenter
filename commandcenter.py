#!/usr/bin/env python3
import sys
import os
import threading
import time
from blessed import Terminal
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from launcher.tmux import TmuxManager
from launcher.opencode import OpencodeLauncher
from launcher.claude import ClaudeLauncher
from launcher.codex import CodexLauncher
from dashboard.widgets.weather import WeatherService
from dashboard.widgets.system import SystemGatherer
from dashboard.widgets.projects import ProjectsWidget
from dashboard.widgets.header import HeaderWidget
from agents.switcher import AgentSwitcher


LAUNCHERS = {
    'opencode': OpencodeLauncher,
    'claude': ClaudeLauncher,
    'codex': CodexLauncher,
}


class RefreshManager:
    def __init__(self, weather_service, system_gatherer):
        self.weather_service = weather_service
        self.system_gatherer = system_gatherer
        self._running = False
        self._thread = None
        self._refresh_callback = None
        self._last_refresh = None

    def start(self, refresh_callback):
        self._refresh_callback = refresh_callback
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _refresh_loop(self):
        while self._running:
            if self._refresh_callback:
                self._last_refresh = datetime.now()
                self._refresh_callback()
            time.sleep(1)

    @property
    def last_refresh(self):
        return self._last_refresh


class Dashboard:
    def __init__(self, term, tmux_manager, projects):
        self.term = term
        self.tmux_manager = tmux_manager
        self.projects = projects
        self.selected_index = 0
        self.weather_service = WeatherService()
        self.system_gatherer = SystemGatherer()
        self.header = HeaderWidget(term)
        self.projects_widget = ProjectsWidget(term)
        self.refresh_manager = RefreshManager(self.weather_service, self.system_gatherer)

    def render(self):
        lines = []
        lines.append(self.header.render())
        lines.append("")

        statuses = self._get_project_statuses()
        projects_output = self.projects_widget.render(self.selected_index, statuses)
        lines.append(projects_output)
        lines.append("")

        cpu = self.system_gatherer.get_cpu()
        ram = self.system_gatherer.get_ram()
        if cpu["percent"] < 70:
            cpu_color = "#00ff88"
        elif cpu["percent"] < 90:
            cpu_color = "#ffaa00"
        else:
            cpu_color = "#ff4444"
        lines.append(self.term.color(f"CPU: {cpu['percent']:.0f}% @ {cpu['freq_mhz']:.0f}MHz | {cpu['temp_c']:.0f}°C", cpu_color))
        lines.append(f"RAM: {ram['used_gb']:.1f} / {ram['total_gb']:.1f} GB | {ram['percent']:.0f}%")

        weather = self.weather_service.get_current()
        lines.append(f"Weather: {weather['temp_c']}°C | {weather['condition']} | Feels {weather['feels_like_c']}°C")

        lines.append("")
        lines.append(f"{self.term.cyan('q')}uit  {self.term.cyan('r')}efresh  {self.term.cyan('s')}witch agent  {self.term.cyan('1-9')} launch project  arrows navigate")

        if self.refresh_manager.last_refresh:
            lines.append(f"Last refresh: {self.refresh_manager.last_refresh.strftime('%H:%M:%S')}")

        return "\n".join(lines)

    def _get_project_statuses(self):
        statuses = {}
        for project in self.projects:
            name = project["name"]
            statuses[name] = "running" if self.tmux_manager.window_exists(name) else "stopped"
        return statuses

    def handle_input(self, key):
        if key in ('q', 'Q', 'KEY_ESCAPE'):
            return 'quit'
        elif key in ('r', 'R'):
            return 'refresh'
        elif key in ('s', 'S'):
            self._switch_selected_agent()
            return 'refresh'
        elif key in ('KEY_UP',):
            self.selected_index = max(0, self.selected_index - 1)
            return 'refresh'
        elif key in ('KEY_DOWN',):
            self.selected_index = min(len(self.projects) - 1, self.selected_index + 1)
            return 'refresh'
        elif key in ('1', '2', '3', '4', '5', '6', '7', '8', '9'):
            idx = int(key) - 1
            if 0 <= idx < len(self.projects):
                self._launch_project(idx)
            return 'refresh'
        return None

    def _switch_selected_agent(self):
        if 0 <= self.selected_index < len(self.projects):
            project = self.projects[self.selected_index]
            switcher = AgentSwitcher()
            new_agent = switcher.switch_agent(project["name"])
            project["agent"] = new_agent

    def _launch_project(self, index):
        if 0 <= index < len(self.projects):
            project = self.projects[index]
            agent = project.get("agent", "opencode")
            launcher_class = LAUNCHERS.get(agent, OpencodeLauncher)
            launcher = launcher_class(self.tmux_manager)
            launcher.launch(project["name"], project["path"])


def main():
    term = Terminal()

    tmux_manager = TmuxManager()
    if not tmux_manager.is_available():
        print("Warning: tmux not available, running in limited mode")

    weather_service = WeatherService()
    system_gatherer = SystemGatherer()

    projects_widget = ProjectsWidget(term)
    try:
        projects = projects_widget.load_projects()
    except FileNotFoundError:
        print("Warning: projects.json not found, starting with empty project list")
        projects = []

    switcher = AgentSwitcher()
    for project in projects:
        if project.get("launch_on_start", False):
            agent = project.get("agent", "opencode")
            launcher_class = LAUNCHERS.get(agent, OpencodeLauncher)
            launcher = launcher_class(tmux_manager)
            launcher.launch(project["name"], project["path"])

    dashboard = Dashboard(term, tmux_manager, projects)
    dashboard.refresh_manager.start(lambda: None)

    try:
        with term.cbreak():
            dashboard.render()
            key = ''
            while True:
                key = term.inkey(timeout=0.1)
                if key:
                    action = dashboard.handle_input(str(key))
                    if action == 'quit':
                        break
    except Exception as e:
        print(f"Error: {e}")
    finally:
        dashboard.refresh_manager.stop()
        windows = tmux_manager.list_windows("cc-")
        for window in windows:
            project_name = window.replace("cc-", "")
            tmux_manager.close_window(project_name)


if __name__ == "__main__":
    main()