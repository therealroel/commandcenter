import os
import re
import shutil
import time
from datetime import datetime

import gevent.monkey
gevent.monkey.patch_all()
import gevent

import psutil
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

from services.pty_bridge import PtyBridge
from agents.switcher import AgentSwitcher, AGENT_CYCLE
from launcher.tmux import TmuxManager
from services.system import SystemService
from services.weather import WeatherService
from services.git import GitService
from services.tokens import TokenTracker

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*")

switcher = AgentSwitcher()
tmux = TmuxManager()
system_service = SystemService()
weather_service = WeatherService()
git_service = GitService()

# Per-panel state -----------------------------------------------------------
# sid -> { panel_id: {bridge, project, agent, tokens: TokenTracker} }
ptys = {}
# Most recent active project per panel, for git polling
active_projects = {0: None, 1: None}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/projects")
def api_projects():
    try:
        projects = switcher.load_projects()
    except Exception as exc:
        return jsonify({"error": str(exc), "projects": []}), 500
    return jsonify({
        "projects": projects,
        "agents": AGENT_CYCLE,
        "tmux": tmux.is_available(),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def emit_event(event_type, message):
    socketio.emit("event_log", {
        "type": event_type,
        "message": message[:200],
        "timestamp": datetime.now().isoformat(),
    })


ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*[\x07\x1b]")


def scan_pty_signals(panel, chunk):
    """Look for human-meaningful events inside raw PTY bytes."""
    text = ANSI_RE.sub(b"", chunk).decode("utf-8", errors="replace")
    lowered = text.lower()
    if "error" in lowered or "traceback" in lowered:
        line = next((l for l in text.splitlines() if "error" in l.lower() or "Traceback" in l), "")
        if line.strip():
            emit_event("ERROR", f"[p{panel}] {line.strip()[:120]}")
    if "running tool" in lowered or "tool_use" in lowered or "● " in text:
        for l in text.splitlines():
            if "tool" in l.lower() or l.startswith("● "):
                emit_event("TOOL", f"[p{panel}] {l.strip()[:120]}")
                break
    if "thinking" in lowered:
        emit_event("THINK", f"[p{panel}] thinking…")


# ---------------------------------------------------------------------------
# Background telemetry threads
# ---------------------------------------------------------------------------
def metrics_thread():
    while True:
        try:
            m = system_service.get_metrics()
            up = m["uptime"]
            if up["days"]:
                uptime_str = f"{up['days']}d {up['hours']}h"
            elif up["hours"]:
                uptime_str = f"{up['hours']}h {up['minutes']}m"
            else:
                uptime_str = f"{up['minutes']}m"
            socketio.emit("metrics_update", {
                "cpu": round(m["cpu"]["percent"]),
                "ram": round(m["ram"]["percent"]),
                "disk": round(m["disk"]["percent"]),
                "uptime": uptime_str,
                "disk_used": f"{m['disk']['used_gb']}G",
                "disk_total": f"{m['disk']['total_gb']}G",
                "ram_used": f"{m['ram']['used_gb']}G",
                "ram_total": f"{m['ram']['total_gb']}G",
                "cpu_temp": m["cpu"]["temp_c"],
                "cpu_cores": m["cpu"]["cores"],
            })
        except Exception as exc:
            print("metrics_thread err:", exc)
        gevent.sleep(1)


def network_thread():
    prev = psutil.net_io_counters()
    prev_t = time.time()
    while True:
        gevent.sleep(1)
        try:
            cur = psutil.net_io_counters()
            now = time.time()
            dt = max(0.1, now - prev_t)
            rx_bps = (cur.bytes_recv - prev.bytes_recv) / dt
            tx_bps = (cur.bytes_sent - prev.bytes_sent) / dt
            prev, prev_t = cur, now
            socketio.emit("network_update", {
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
                "rx_total": cur.bytes_recv,
                "tx_total": cur.bytes_sent,
            })
        except Exception as exc:
            print("network_thread err:", exc)


def weather_thread():
    while True:
        try:
            data = weather_service.get_current()
            socketio.emit("weather_update", data)
        except Exception as exc:
            print("weather_thread err:", exc)
        gevent.sleep(300)


def git_thread():
    """Poll git status of whatever project is currently bound to each panel."""
    while True:
        try:
            projects = {p["name"]: p for p in switcher.load_projects()}
            for panel_id, project_name in active_projects.items():
                if not project_name:
                    continue
                proj = projects.get(project_name)
                if not proj:
                    continue
                path = proj.get("path")
                if not path or not os.path.isdir(os.path.join(path, ".git")):
                    socketio.emit("git_update", {"panel": panel_id, "project": project_name, "git": None})
                    continue
                try:
                    status = git_service.get_status(path)
                    socketio.emit("git_update", {
                        "panel": panel_id,
                        "project": project_name,
                        "git": status,
                    })
                except Exception:
                    socketio.emit("git_update", {"panel": panel_id, "project": project_name, "git": None})
        except Exception as exc:
            print("git_thread err:", exc)
        gevent.sleep(5)


# ---------------------------------------------------------------------------
# Socket: terminals
# ---------------------------------------------------------------------------
@socketio.on("connect")
def handle_connect():
    ptys[request.sid] = {}
    emit_event("INFO", f"client connected · {request.sid[:6]}")


@socketio.on("disconnect")
def handle_disconnect():
    sid_ptys = ptys.pop(request.sid, {})
    for slot in sid_ptys.values():
        try:
            slot["bridge"].close()
        except Exception:
            pass
    emit_event("INFO", f"client disconnected · {request.sid[:6]}")


def _resolve_project(name):
    for p in switcher.load_projects():
        if p["name"] == name:
            return p
    return None


@socketio.on("term_open")
def handle_term_open(data):
    sid = request.sid
    panel = int(data.get("panel", 0))
    project_name = data.get("project")
    rows = int(data.get("rows", 40))
    cols = int(data.get("cols", 120))

    proj = _resolve_project(project_name) if project_name else None
    if proj:
        cwd = proj.get("path") or os.getcwd()
        agent = data.get("agent") or proj.get("agent") or "claude"
    else:
        cwd = os.getcwd()
        agent = data.get("agent", "claude")

    if not os.path.isdir(cwd):
        cwd = os.getcwd()

    agent_cmd = agent if agent in AGENT_CYCLE else "claude"
    session = f"cc-{project_name or 'panel'+str(panel)}"

    if tmux.is_available():
        shell_cmd = (
            f"cd {cwd!r} && "
            f"(command -v {agent_cmd} >/dev/null && "
            f"exec tmux new-session -A -s {session!r} {agent_cmd} || "
            f"exec bash -i)"
        )
    else:
        shell_cmd = (
            f"cd {cwd!r} && "
            f"(command -v {agent_cmd} >/dev/null && exec {agent_cmd} || exec bash -i)"
        )
    argv = ["/bin/bash", "-lc", shell_cmd]

    sid_ptys = ptys.setdefault(sid, {})
    if panel in sid_ptys:
        try:
            sid_ptys[panel]["bridge"].close()
        except Exception:
            pass

    tokens = TokenTracker(max_tokens=200_000)

    def on_data(chunk, _sid=sid, _panel=panel, _tokens=tokens):
        socketio.emit(
            "term_output",
            {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
            to=_sid,
        )
        # Use streamed bytes as a fuel proxy. Rough but visible.
        _tokens.update(_tokens.used + len(chunk))
        status = _tokens.get_status()
        socketio.emit("token_update", {
            "panel": _panel,
            "percent": min(100, status["percent"]),
            "used": status["used"],
            "max": status["max"],
        }, to=_sid)
        try:
            scan_pty_signals(_panel, chunk)
        except Exception:
            pass

    bridge = PtyBridge(argv, on_data, rows=rows, cols=cols)
    sid_ptys[panel] = {"bridge": bridge, "project": project_name, "agent": agent, "tokens": tokens}
    active_projects[panel] = project_name
    emit_event("INFO", f"opened {project_name or '?'} ({agent}) on panel {panel}")


@socketio.on("term_input")
def handle_term_input(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot:
        slot["bridge"].write(data.get("data", ""))


@socketio.on("term_resize")
def handle_term_resize(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot:
        slot["bridge"].resize(int(data.get("rows", 40)), int(data.get("cols", 120)))


@socketio.on("term_close")
def handle_term_close(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).pop(panel, None)
    if slot:
        slot["bridge"].close()


@socketio.on("agent_switch")
def handle_agent_switch(data):
    """Cycle and persist the agent for a project, then re-open its PTY."""
    project_name = data.get("project")
    panel = int(data.get("panel", 0))
    if not project_name:
        return
    try:
        new_agent = switcher.switch_agent(project_name)
        emit_event("INFO", f"{project_name} → {new_agent}")
        socketio.emit("agent_switched", {"project": project_name, "agent": new_agent, "panel": panel})
    except ValueError as e:
        emit_event("ERROR", str(e))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    socketio.start_background_task(metrics_thread)
    socketio.start_background_task(network_thread)
    socketio.start_background_task(weather_thread)
    socketio.start_background_task(git_thread)
    port = int(os.environ.get("CC_PORT", 5050))
    print(f"⚡ commandcenter on http://0.0.0.0:{port} (tmux={'on' if tmux.is_available() else 'off'})")
    socketio.run(app, host="0.0.0.0", port=port)
