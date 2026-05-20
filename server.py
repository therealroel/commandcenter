import os
import subprocess
import time
from datetime import datetime
from threading import Lock

import gevent.monkey
gevent.monkey.patch_all()
import gevent

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

from services.pty_bridge import PtyBridge

from agents.switcher import AgentSwitcher
from launcher.tmux import TmuxManager
from launcher.opencode import OpencodeLauncher
from launcher.claude import ClaudeLauncher
from launcher.codex import CodexLauncher
from services.system import SystemService
from services.weather import WeatherService
from services.git import GitService

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*")

switcher = AgentSwitcher()
tmux = TmuxManager()
system_service = SystemService()
weather_service = WeatherService()
git_service = GitService()

launchers = {
    "opencode": OpencodeLauncher(tmux),
    "claude": ClaudeLauncher(tmux),
    "codex": CodexLauncher(tmux),
}

capture_lock = Lock()


@app.route("/")
def index():
    return render_template("index.html")


def emit_event_log(event_type, message):
    socketio.emit("event_log", {
        "type": event_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })


def capture_pane_output(project_name):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"cc-{project_name}", "-p", "-S", "-50"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def metrics_thread():
    while True:
        m = system_service.get_metrics()
        up = m["uptime"]
        if up["days"]:
            uptime_str = f"{up['days']}d {up['hours']}h"
        elif up["hours"]:
            uptime_str = f"{up['hours']}h {up['minutes']}m"
        else:
            uptime_str = f"{up['minutes']}m"
        payload = {
            "cpu": round(m["cpu"]["percent"]),
            "ram": round(m["ram"]["percent"]),
            "disk": round(m["disk"]["percent"]),
            "uptime": uptime_str,
            "disk_used": f"{m['disk']['used_gb']}G",
            "disk_total": f"{m['disk']['total_gb']}G",
            "cpu_temp": m["cpu"]["temp_c"],
            "cpu_cores": m["cpu"]["cores"],
            "ram_used": f"{m['ram']['used_gb']}G",
            "ram_total": f"{m['ram']['total_gb']}G",
            "raw": m,
        }
        socketio.emit("metrics_update", payload)
        gevent.sleep(1)


def weather_thread():
    while True:
        data = weather_service.get_current()
        socketio.emit("weather_update", data)
        gevent.sleep(300)


# sid -> { panel_id: PtyBridge }
ptys = {}


@socketio.on("connect")
def handle_connect():
    ptys[request.sid] = {}
    emit_event_log("connection", f"Client connected ({request.sid[:6]})")


@socketio.on("disconnect")
def handle_disconnect():
    sid_ptys = ptys.pop(request.sid, {})
    for bridge in sid_ptys.values():
        try:
            bridge.close()
        except Exception:
            pass
    emit_event_log("connection", f"Client disconnected ({request.sid[:6]})")


@socketio.on("term_open")
def handle_term_open(data):
    sid = request.sid
    panel = int(data.get("panel", 0))
    project = data.get("project") or f"panel{panel}"
    agent = data.get("agent", "claude")
    rows = int(data.get("rows", 40))
    cols = int(data.get("cols", 120))

    cwd = data.get("cwd") or os.path.expanduser(f"~/projects/{project}")
    if not os.path.isdir(cwd):
        cwd = os.getcwd()

    agent_cmd = {
        "claude": "claude",
        "opencode": "opencode",
        "codex": "codex",
    }.get(agent, "claude")

    # Run the agent directly under the PTY in the project directory.
    # Falls back to an interactive bash if the agent binary is missing.
    shell_cmd = f"cd {cwd!r} && (command -v {agent_cmd} >/dev/null && exec {agent_cmd} || exec bash -i)"
    argv = ["/bin/bash", "-lc", shell_cmd]

    # Close any prior pty for this panel on this sid
    sid_ptys = ptys.setdefault(sid, {})
    if panel in sid_ptys:
        try:
            sid_ptys[panel].close()
        except Exception:
            pass

    def on_data(chunk, _sid=sid, _panel=panel):
        socketio.emit(
            "term_output",
            {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
            to=_sid,
        )

    bridge = PtyBridge(argv, on_data, rows=rows, cols=cols)
    sid_ptys[panel] = bridge
    emit_event_log("term", f"opened {session} ({agent}) on panel {panel}")


@socketio.on("term_input")
def handle_term_input(data):
    panel = int(data.get("panel", 0))
    bridge = ptys.get(request.sid, {}).get(panel)
    if bridge:
        bridge.write(data.get("data", ""))


@socketio.on("term_resize")
def handle_term_resize(data):
    panel = int(data.get("panel", 0))
    bridge = ptys.get(request.sid, {}).get(panel)
    if bridge:
        bridge.resize(int(data.get("rows", 40)), int(data.get("cols", 120)))


@socketio.on("term_close")
def handle_term_close(data):
    panel = int(data.get("panel", 0))
    bridge = ptys.get(request.sid, {}).pop(panel, None)
    if bridge:
        bridge.close()


@socketio.on("agent_switch")
def handle_agent_switch(data):
    project = data.get("project")
    if not project:
        return

    try:
        new_agent = switcher.switch_agent(project)
        emit_event_log("agent_switch", f"{project} switched to {new_agent}")

        if tmux.window_exists(project):
            tmux.close_window(project)
            projects = switcher.load_projects()
            proj_data = next((p for p in projects if p["name"] == project), None)
            if proj_data:
                launcher = launchers.get(new_agent)
                if launcher:
                    launcher.launch(project, proj_data["path"])
    except ValueError as e:
        emit_event_log("error", str(e))


if __name__ == "__main__":
    socketio.start_background_task(metrics_thread)
    socketio.start_background_task(weather_thread)
    port = int(os.environ.get("CC_PORT", 5050))
    socketio.run(app, host="0.0.0.0", port=port)
