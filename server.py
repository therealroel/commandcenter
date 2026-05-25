import os
import re
import shutil
import subprocess
import time
import json
from datetime import datetime
from pathlib import Path

import gevent.monkey
gevent.monkey.patch_all()
import gevent

import psutil
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

from version import __version__
from services.pty_bridge import PtyBridge
from agents.switcher import AgentSwitcher, AGENT_CYCLE
from launcher.tmux import TmuxManager
from services.system import SystemService
from services.weather import WeatherService
from services.git import GitService

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
# Re-read templates from disk on every request so editing index.html only
# needs a browser refresh, not a server restart.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*", logger=False, engineio_logger=False)

switcher = AgentSwitcher()
tmux = TmuxManager()
system_service = SystemService()
weather_service = WeatherService()
git_service = GitService()

# Per-panel state -----------------------------------------------------------
# sid -> { panel_id: {bridge, project, agent} }
ptys = {}
# Most recent active project per panel, for git polling
active_projects = {0: None, 1: None}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    import getpass
    username = getpass.getuser().upper()
    return render_template("index.html", version=__version__, username=username)


BACKUP_NAMES = {
    "bedrock": "settings.bedrock-backup.json",
    "subscription": "settings.anthropic-backup.json",
}

_config_info_cache = {"profile": "subscription", "user": "subscription", "time": 0}

def _load_cc_settings():
    """Load commandcenter settings from disk"""
    settings_file = Path.home() / ".claude" / "commandcenter_settings.json"
    try:
        if settings_file.exists():
            with open(settings_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {"auto_close_idle": True}

def _save_settings(data):
    """Save commandcenter settings to disk"""
    settings_file = Path.home() / ".claude" / "commandcenter_settings.json"
    try:
        with open(settings_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def get_config_info():
    """Get current config profile and user info if available - cached for 5s"""
    global _config_info_cache
    import time
    now = time.time()
    if now - _config_info_cache.get("time", 0) < 5:
        return _config_info_cache

    base = Path.home() / ".claude"
    settings = base / "settings.json"
    try:
        with open(settings) as f:
            data = json.load(f)
        env = data.get("env", {})
        if env.get("CLAUDE_CODE_USE_BEDROCK") == "1":
            profile = "bedrock"
            user = "bedrock"
        else:
            profile = "subscription"
            user = None
            try:
                result = subprocess.check_output(
                    ["claude", "auth", "status", "--json"],
                    stderr=subprocess.DEVNULL,
                    timeout=3
                ).decode()
                auth_data = json.loads(result)
                email = auth_data.get("email")
                if email:
                    user = email
                else:
                    user = "logged in"
            except Exception:
                user = "subscription"
    except Exception:
        profile = "unknown"
        user = None

    _config_info_cache = {"profile": profile, "user": user, "time": now}
    return {"profile": profile, "user": user}

@app.route("/api/config")
def api_config():
    base = Path.home() / ".claude"
    settings = base / "settings.json"
    try:
        with open(settings) as f:
            data = json.load(f)
        env = data.get("env", {})
        if env.get("CLAUDE_CODE_USE_BEDROCK") == "1":
            profile = "bedrock"
        else:
            profile = "subscription"
    except Exception:
        profile = "unknown"
    return jsonify({"profile": profile})


@app.route("/api/config/switch", methods=["POST"])
def api_config_switch():
    global _config_info_cache
    data = request.get_json(force=True) or {}
    profile = data.get("profile")
    if profile not in ("bedrock", "subscription"):
        return jsonify({"error": "invalid profile"}), 400
    base = Path.home() / ".claude"
    settings = base / "settings.json"
    backup = base / BACKUP_NAMES[profile]
    if not backup.exists():
        return jsonify({"error": f"backup not found: {backup}"}), 404
    try:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(settings, settings.with_name(f"settings.json.bak-{ts}"))
        shutil.copy2(backup, settings)
        # Invalidate cache so next request gets fresh data
        _config_info_cache = {"profile": profile, "user": profile, "time": 0}
        return jsonify({"ok": True, "profile": profile})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/config/save", methods=["POST"])
def api_config_save():
    """Save current settings as a backup profile, or save a profile to settings.json"""
    data = request.get_json(force=True) or {}
    action = data.get("action")
    profile = data.get("profile")  # "bedrock" or "subscription"
    if profile not in ("bedrock", "subscription"):
        return jsonify({"error": "invalid profile"}), 400

    base = Path.home() / ".claude"
    settings = base / "settings.json"
    backup = base / BACKUP_NAMES[profile]

    if action == "save":
        # Save current settings as the specified profile backup
        try:
            shutil.copy2(settings, backup)
            return jsonify({"ok": True, "profile": profile})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    elif action == "apply":
        # Apply the backup profile to current settings
        if not backup.exists():
            return jsonify({"error": f"backup not found: {backup}"}), 404
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(settings, settings.with_name(f"settings.json.bak-{ts}"))
            shutil.copy2(backup, settings)
            return jsonify({"ok": True, "profile": profile})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return jsonify({"error": "invalid action"}), 400


@app.route("/api/config/check-bedrock")
def api_check_bedrock():
    base = Path.home() / ".claude"
    bedrock_backup = base / "settings.bedrock-backup.json"
    return jsonify({"exists": bedrock_backup.exists()})


@app.route("/api/config/save-bedrock", methods=["POST"])
def api_save_bedrock():
    """Create bedrock config from provided credentials, preserving other settings"""
    data = request.get_json(force=True) or {}
    region = data.get("region", "").strip()
    token = data.get("token", "").strip()
    if not region or not token:
        return jsonify({"error": "region and token required"}), 400

    base = Path.home() / ".claude"
    settings = base / "settings.json"
    bedrock_backup = base / "settings.bedrock-backup.json"

    try:
        # Read current settings to get base config (preserve all other settings)
        with open(settings) as f:
            current = json.load(f)

        # Deep copy current settings for bedrock config
        bedrock_config = json.loads(json.dumps(current))

        # Update env section with bedrock credentials
        if "env" not in bedrock_config:
            bedrock_config["env"] = {}
        bedrock_config["env"]["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_config["env"]["AWS_REGION"] = region
        bedrock_config["env"]["AWS_BEARER_TOKEN_BEDROCK"] = token

        # Remove CLAUDE_API_KEY since we're using bedrock
        if "env" in bedrock_config and "CLAUDE_API_KEY" in bedrock_config["env"]:
            del bedrock_config["env"]["CLAUDE_API_KEY"]

        # Save as bedrock backup
        with open(bedrock_backup, "w") as f:
            json.dump(bedrock_config, f, indent=2)

        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/settings/auto-close-idle")
def api_get_auto_close_idle():
    """Get auto-close idle sessions setting"""
    settings = _load_cc_settings()
    return jsonify({"enabled": settings.get("auto_close_idle", True)})


@app.route("/api/settings/auto-close-idle", methods=["POST"])
def api_set_auto_close_idle():
    """Set auto-close idle sessions setting"""
    data = request.get_json(force=True) or {}
    enabled = data.get("enabled", True)
    settings = _load_cc_settings()
    settings["auto_close_idle"] = enabled
    _save_settings(settings)
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/favicon.ico")
def favicon():
    # No icon asset shipped; answer cleanly instead of 404ing the console.
    return ("", 204)


@app.route("/api/version")
def api_version():
    return jsonify({"version": __version__})


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


@app.route("/api/dirs")
def api_dirs():
    raw = request.args.get("path") or os.path.expanduser("~/projects")
    if not raw:
        raw = os.path.expanduser("~")
    path = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        path = os.path.expanduser("~")
    try:
        entries = []
        for name in sorted(os.listdir(path), key=str.lower):
            if name.startswith("."):
                continue
            full = os.path.join(path, name)
            try:
                if not os.path.isdir(full):
                    continue
                is_git = os.path.isdir(os.path.join(full, ".git"))
                entries.append({"name": name, "path": full, "git": is_git})
            except OSError:
                continue
        parent = os.path.dirname(path) if path != "/" else None
        return jsonify({
            "path": path,
            "parent": parent,
            "home": os.path.expanduser("~"),
            "entries": entries,
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "path": path, "entries": []}), 500


@app.route("/api/projects", methods=["POST"])
def api_add_project():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    path = (data.get("path") or "").strip()
    agent = data.get("agent") or "claude"
    if not name or not path:
        return jsonify({"error": "name and path are required"}), 400
    path = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return jsonify({"error": f"not a directory: {path}"}), 400
    if agent not in AGENT_CYCLE:
        return jsonify({"error": f"unknown agent: {agent}"}), 400
    projects = switcher.load_projects()
    if any(p["name"] == name for p in projects):
        return jsonify({"error": f"project '{name}' already exists"}), 409
    new_proj = {"name": name, "path": path, "agent": agent, "launch_on_start": False}
    projects.append(new_proj)
    switcher.save_projects(projects)
    emit_event("INFO", f"added project {name} → {path}")
    return jsonify({"ok": True, "project": new_proj})


@app.route("/api/projects/<name>", methods=["DELETE"])
def api_del_project(name):
    projects = switcher.load_projects()
    new = [p for p in projects if p["name"] != name]
    if len(new) == len(projects):
        return jsonify({"error": "not found"}), 404
    switcher.save_projects(new)
    emit_event("INFO", f"removed project {name}")
    return jsonify({"ok": True})


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

# Patterns that mean "this pane is sitting on a prompt waiting for the human".
# Used both for the slow border-fade alert AND for the tmux janitor heuristic
# (when combined with idle time, these fingerprints mark a never-prompted session).
AWAITING_PATTERNS = (
    "sign in with chatgpt",
    "sign in with device code",
    "press enter to continue",
    "select any you wish to enable",
    "do you want to proceed",
    "approve this tool",
    "allow this tool",
)

# Real error indicators — anchored patterns, not loose substring matches.
ERROR_RE = re.compile(
    r"(?:^|\s)(?:Traceback \(most recent call last\)"
    r"|[A-Z]\w*Error:\s"
    r"|[A-Z]\w*Exception:\s"
    r"|ERROR:\s"
    r"|FATAL:\s"
    r"|fatal:\s"
    r"|error:\s)"
)

# Lines that look like claude-mem observation listings — skip entirely.
# Examples: "#472 1:31PM 🔴 winControlsReferenceError..." or "[37/126] #466 🟣 ..."
MEM_OBS_RE = re.compile(r"#\d{2,}\s*\d*[ap]?m?\s*[🔴🟣🔵✅⚖🚨🔐🟢🟡🟠]")
MEM_PROGRESS_RE = re.compile(r"\[\d+/\d+\]")


def scan_pty_signals(sid, panel, chunk):
    """Look for human-meaningful events inside raw PTY bytes."""
    text = ANSI_RE.sub(b"", chunk).decode("utf-8", errors="replace")
    lowered = text.lower()
    ch = panel + 1  # panel 0 = CH 1, etc.

    # Awaiting-input alert — emit per-sid so only the panel's owner sees it.
    if any(p in lowered for p in AWAITING_PATTERNS):
        socketio.emit("panel_awaiting", {"panel": panel, "awaiting": True}, to=sid)

    # Skip noisy startup lines
    if "claude code v" in lowered or "───" in text:
        return

    # Real errors only — strict pattern, and skip claude-mem observation output.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if MEM_OBS_RE.search(stripped) or MEM_PROGRESS_RE.search(stripped):
            continue
        if "claude code" in stripped.lower() or "───" in stripped:
            continue
        if ERROR_RE.search(stripped):
            emit_event("ERROR", f"[CH{ch}] {stripped[:120]}")
            break

    # Tool use
    if "● " in text:
        for l in text.splitlines():
            if l.strip().startswith("● "):
                emit_event("TOOL", f"[CH{ch}] {l.strip()[:120]}")
                break

    # Thinking indicator — only match Claude's standalone status line, not
    # the substring "thinking" appearing inside other output.
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if MEM_OBS_RE.search(s) or MEM_PROGRESS_RE.search(s):
            continue
        # Claude prints lines like "✻ Thinking…" or "* Thinking" as its
        # live-status indicator. Require it to be near the start of the line.
        if re.match(r"^[*✻✱·●]?\s*Thinking[…\.\s]*$", s):
            emit_event("THINK", f"[CH{ch}] thinking…")
            break


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


def get_weather_emoji(condition):
    """Map weather condition to emoji."""
    c = condition.lower()
    if "sun" in c or "clear" in c:
        return "☀️"
    elif "cloud" in c and ("part" in c or "few" in c):
        return "⛅"
    elif "cloud" in c or "overcast" in c:
        return "☁️"
    elif "rain" in c and ("light" in c or "drizzle" in c or "patchy" in c):
        return "🌦️"
    elif "rain" in c or "shower" in c:
        return "🌧️"
    elif "thunder" in c or "storm" in c:
        return "⛈️"
    elif "snow" in c:
        return "❄️"
    elif "fog" in c or "mist" in c:
        return "🌫️"
    elif "wind" in c:
        return "💨"
    else:
        return "🌡️"

def weather_thread():
    # Emit every 3 seconds for first 30 seconds to catch connecting clients
    for _ in range(10):
        try:
            data = weather_service.get_current()
            emoji = get_weather_emoji(data['condition'])
            text = f"{emoji} {data['temp_c']:.0f}°C {data['condition']}"
            socketio.emit("weather_update", {"text": text, **data})
        except Exception as exc:
            print(f"[WEATHER] Error: {exc}")
        gevent.sleep(3)
    # Then every 5 minutes
    while True:
        try:
            data = weather_service.get_current()
            emoji = get_weather_emoji(data['condition'])
            text = f"{emoji} {data['temp_c']:.0f}°C {data['condition']}"
            socketio.emit("weather_update", {"text": text, **data})
        except Exception as exc:
            print(f"[WEATHER] Error: {exc}")
        gevent.sleep(300)


# Fingerprints that mean an agent pane is still on its first-launch / login
# screen — never typed in, never authed. Combined with idle time + the "not
# currently bound to a visible panel" check, these mark sessions safe to kill.
NEVER_USED_FINGERPRINTS = (
    "sign in with chatgpt",
    "sign in with device code",
    "welcome to codex",
)


def _sessions_in_use():
    """tmux session names bound to a visible panel on any connected client.

    The web client only displays sessions that are in `ptys`. Anything else
    in tmux is by definition a background session.
    """
    in_use = set()
    for sid_map in ptys.values():
        for panel, slot in sid_map.items():
            proj = slot.get("project") or f"panel{panel}"
            agent = slot.get("agent") or "claude"
            in_use.add(f"cc-{proj}-{panel}-{agent}")
    return in_use


def tmux_janitor():
    """Auto-close background agent sessions that were never prompted.

    Strict criteria so we never kill something the user is using:
      • Session prefix `cc-` (only sessions we spawned)
      • NOT currently bound to a visible panel on any client
      • Idle for at least 5 minutes
      • Pane content still matches a first-launch fingerprint
      • Only runs if auto_close_idle setting is enabled
    """
    while True:
        gevent.sleep(60)
        settings = _load_cc_settings()
        if not settings.get("auto_close_idle", True):
            continue
        if not tmux.is_available():
            continue
        try:
            raw = subprocess.check_output(
                ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_activity}"],
                stderr=subprocess.DEVNULL,
            ).decode().splitlines()
        except Exception:
            continue
        now = time.time()
        in_use = _sessions_in_use()
        for line in raw:
            try:
                name, act = line.split("\t")
            except ValueError:
                continue
            if not name.startswith("cc-") or name in in_use:
                continue
            try:
                idle = now - int(act)
            except ValueError:
                continue
            if idle < 300:
                continue
            try:
                pane = subprocess.check_output(
                    ["tmux", "capture-pane", "-p", "-t", name],
                    stderr=subprocess.DEVNULL,
                ).decode().lower()
            except Exception:
                continue
            if any(fp in pane for fp in NEVER_USED_FINGERPRINTS):
                try:
                    subprocess.run(
                        ["tmux", "kill-session", "-t", name],
                        check=False,
                        stderr=subprocess.DEVNULL,
                    )
                    emit_event("INFO", f"auto-closed idle agent: {name}")
                except Exception:
                    pass


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
    # Send weather immediately on connect
    try:
        data = weather_service.get_current()
        emoji = get_weather_emoji(data['condition'])
        text = f"{emoji} {data['temp_c']:.0f}°C {data['condition']}"
        socketio.emit("weather_update", {"text": text, **data}, to=request.sid)
    except Exception:
        pass


@socketio.on("disconnect")
def handle_disconnect():
    sid_ptys = ptys.pop(request.sid, {})
    for slot in sid_ptys.values():
        for key in ("bridge", "bash_bridge"):
            br = slot.get(key)
            if br:
                try:
                    br.close()
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
    # Session name includes project + panel (channel) + agent so each panel
    # gets its own tmux session. Switching agents keeps each one's session
    # alive in the background. Reattaching resumes existing conversation.
    session = f"cc-{project_name or 'panel'}-{panel}-{agent_cmd}"

    # fnm (node version manager) setup for codex
    fnm_setup = 'export PATH="$HOME/.local/share/fnm:$PATH"; eval "$(fnm env 2>/dev/null)" 2>/dev/null;'

    if tmux.is_available():
        # Check if session already exists - clear history then attach (keeps
        # AI conversation but removes scrollback replay lag). If not found,
        # create new session with agent auto-restart loop. When agent exits
        # (accidental close), it auto-restarts. User can manually exit to stop.
        shell_cmd = (
            f"{fnm_setup} cd {cwd!r} && "
            f"(tmux has-session -t {session!r} 2>/dev/null && "
            f"tmux clear-history -t {session!r} 2>/dev/null && "
            f"exec tmux attach-session -t {session!r} || "
            f"(command -v {agent_cmd} >/dev/null && "
            f"exec tmux new-session -s {session!r} 'while command -v {agent_cmd} >/dev/null 2>&1; do {agent_cmd}; sleep 1; done' || "
            f"exec bash -i))"
        )
    else:
        shell_cmd = (
            f"{fnm_setup} cd {cwd!r} && "
            f"(command -v {agent_cmd} >/dev/null && exec {agent_cmd} || exec bash -i)"
        )
    argv = ["/bin/bash", "-lc", shell_cmd]

    sid_ptys = ptys.setdefault(sid, {})
    if panel in sid_ptys:
        for key in ("bridge", "bash_bridge"):
            br = sid_ptys[panel].get(key)
            if br:
                try:
                    br.close()
                except Exception:
                    pass

    def on_data(chunk, _sid=sid, _panel=panel):
        socketio.emit(
            "term_output",
            {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
            to=_sid,
        )
        try:
            scan_pty_signals(_sid, _panel, chunk)
        except Exception:
            pass

    bridge = PtyBridge(argv, on_data, rows=rows, cols=cols)
    sid_ptys[panel] = {"bridge": bridge, "project": project_name, "agent": agent}
    active_projects[panel] = project_name
    config_info = get_config_info()
    socketio.emit("term_opened", {
        "panel": panel,
        "project": project_name,
        "agent": agent,
        "config": config_info["profile"],
        "user": config_info["user"]
    })
    emit_event("INFO", f"opened {project_name or '?'} ({agent}) on panel {panel}")


@socketio.on("term_input")
def handle_term_input(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot:
        slot["bridge"].write(data.get("data", ""))
        # User just acted on the panel — clear the awaiting-input border pulse.
        socketio.emit(
            "panel_awaiting",
            {"panel": panel, "awaiting": False},
            to=request.sid,
        )


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
        for key in ("bridge", "bash_bridge"):
            br = slot.get(key)
            if br:
                try:
                    br.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Socket: bottom-of-panel bash terminal (per-panel, rooted at project path)
# ---------------------------------------------------------------------------
@socketio.on("term_bash_open")
def handle_term_bash_open(data):
    sid = request.sid
    panel = int(data.get("panel", 0))
    rows = int(data.get("rows", 15))
    cols = int(data.get("cols", 120))

    slot = ptys.get(sid, {}).get(panel)
    if not slot:
        return  # agent terminal must exist first — that's where we get the project from

    proj = _resolve_project(slot.get("project")) if slot.get("project") else None
    cwd = (proj.get("path") if proj else None) or os.path.expanduser("~")
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")

    # Close any prior bash bridge for this panel before spawning a fresh one.
    old = slot.get("bash_bridge")
    if old:
        try:
            old.close()
        except Exception:
            pass

    shell = os.environ.get("SHELL", "/bin/bash")
    inner = f"cd {cwd!r} && exec {shell} -i"

    def on_data(chunk, _sid=sid, _panel=panel):
        socketio.emit(
            "term_bash_output",
            {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
            to=_sid,
        )

    bridge = PtyBridge(["/bin/bash", "-lc", inner], on_data, rows=rows, cols=cols)
    slot["bash_bridge"] = bridge


@socketio.on("term_bash_input")
def handle_term_bash_input(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        slot["bash_bridge"].write(data.get("data", ""))


@socketio.on("term_bash_resize")
def handle_term_bash_resize(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        slot["bash_bridge"].resize(
            int(data.get("rows", 15)), int(data.get("cols", 120))
        )


@socketio.on("term_bash_close")
def handle_term_bash_close(data):
    panel = int(data.get("panel", 0))
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        try:
            slot["bash_bridge"].close()
        except Exception:
            pass
        slot["bash_bridge"] = None


@socketio.on("agent_switch")
def handle_agent_switch(data):
    """Set the agent for a project (or cycle if no agent specified)."""
    project_name = data.get("project")
    panel = int(data.get("panel", 0))
    new_agent = data.get("agent")  # specific agent or None to cycle
    if not project_name:
        return
    try:
        if new_agent and new_agent in AGENT_CYCLE:
            switcher.set_agent(project_name, new_agent)
        else:
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
    socketio.start_background_task(tmux_janitor)
    port = int(os.environ.get("CC_PORT", 5050))
    print(f"⚡ commandcenter on http://0.0.0.0:{port} (tmux={'on' if tmux.is_available() else 'off'})")
    # Explicit gevent WSGIServer + WebSocketHandler — Flask-SocketIO's auto-
    # detection of gevent-websocket can fail silently, leaving Socket.IO stuck
    # on long-polling. Wiring the handler ourselves guarantees the upgrade.
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    pywsgi.WSGIServer(
        ("0.0.0.0", port), app, handler_class=WebSocketHandler, log=None
    ).serve_forever()
