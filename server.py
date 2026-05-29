import os
import re
import shlex
import shutil
import gevent.subprocess as subprocess
import sys
import time
import json
import threading
import logging
from datetime import datetime
from pathlib import Path

import gevent.monkey
gevent.monkey.patch_all()
import gevent

import psutil
from flask import Flask, render_template, request, jsonify, make_response, g
from flask_socketio import SocketIO

from version import __version__
from services.pty_bridge import PtyBridge
from agents.switcher import AgentSwitcher, AGENT_CYCLE
from launcher.tmux import TmuxManager
from services.system import SystemService
from services.weather import WeatherService
from services.git import GitService

# ============================================================================
# LOGGING SETUP - Structured logging instead of print() statements
# ============================================================================
LOG_DIR = Path.home() / ".claude" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "commandcenter.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("cc")

# Rate limiting storage
RATE_LIMIT_STORAGE = {}  # ip -> [(timestamp, count), ...]
RATE_LIMIT_MAX = 100  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds

def check_rate_limit(ip):
    """Check if IP is rate limited. Returns True if allowed, False if limited."""
    now = time.time()
    if ip not in RATE_LIMIT_STORAGE:
        RATE_LIMIT_STORAGE[ip] = []
    
    # Clean old entries
    RATE_LIMIT_STORAGE[ip] = [
        (ts, count) for ts, count in RATE_LIMIT_STORAGE[ip]
        if now - ts < RATE_LIMIT_WINDOW
    ]
    
    # Remove empty entries to prevent memory leak
    if not RATE_LIMIT_STORAGE[ip]:
        del RATE_LIMIT_STORAGE[ip]
        return True
    
    # Sum counts
    total = sum(count for ts, count in RATE_LIMIT_STORAGE[ip])
    
    if total >= RATE_LIMIT_MAX:
        return False
    
    # Add this request
    RATE_LIMIT_STORAGE[ip].append((now, 1))
    return True

# ============================================================================
# PERSISTENT SECRET KEY - Don't regenerate on every start
# ============================================================================
def get_secret_key():
    """Get or create persistent secret key."""
    key_file = Path.home() / ".claude" / "cc_secret_key"
    try:
        if key_file.exists():
            return key_file.read_bytes()
    except Exception:
        pass
    # Generate new key
    key = os.urandom(24)
    try:
        key_file.write_bytes(key)
        key_file.chmod(0o600)
    except Exception:
        pass
    return key

app = Flask(__name__)
app.config["SECRET_KEY"] = get_secret_key()
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# CORS - Allow localhost and 127.0.0.1 for Socket.IO
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*", logger=False, engineio_logger=False)

switcher = AgentSwitcher()
tmux = TmuxManager()
system_service = SystemService()
weather_service = WeatherService(os.environ.get("CC_WEATHER_CITY", "Copenhagen"))
git_service = GitService()

# Per-panel state -----------------------------------------------------------
# sid -> { panel_id: {bridge, project, agent} }
ptys = {}
# Most recent active project per panel, for git polling
# Fixed: was only tracking 2 panels (0,1), now tracks all 3
active_projects = {0: None, 1: None, 2: None}

# Lock for thread-safe access to ptys dict (scan_pty_signals can fire concurrently)
ptys_lock = threading.Lock()

# Graceful shutdown flag
shutdown_requested = False

# ============================================================================
# ACCESS LOGGING & ERROR HANDLERS
# ============================================================================
@app.before_request
def log_access():
    """Log all HTTP requests for security/audit."""
    if request.path in ['/favicon.ico']:
        return
    ip = request.remote_addr or 'unknown'
    request._start_time = time.time()
    logger.info(f"ACCESS {request.method} {request.path} from {ip} [{request.headers.get('User-Agent', 'unknown')[:50]}]")

@app.after_request
def log_response(response):
    """Log all HTTP responses."""
    if request.path in ['/favicon.ico']:
        return response
    ip = request.remote_addr or 'unknown'
    elapsed = time.time() - getattr(request, '_start_time', time.time())
    logger.info(f"RESPONSE {request.method} {request.path} -> {response.status_code} from {ip} ({elapsed:.3f}s)")
    return response

@app.errorhandler(404)
def error_404(e):
    """Don't expose stack traces for 404."""
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def error_500(e):
    """Don't expose stack traces for 500."""
    logger.error(f"INTERNAL ERROR: {request.path} - {str(e)}")
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def error_exception(e):
    """Catch-all error handler - never expose exceptions."""
    logger.error(f"UNHANDLED ERROR: {request.path} - {str(e)}")
    return jsonify({"error": "An error occurred"}), 500


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    import getpass
    username = getpass.getuser().upper()
    response = make_response(render_template("index.html", version=__version__, username=username))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


BACKUP_NAMES = {
    "bedrock": "settings.bedrock-backup.json",
    "subscription": "settings.anthropic-backup.json",
}

_config_info_cache = {"profile": "subscription", "user": "subscription", "time": 0}

def rate_limit():
    """Decorator to apply rate limiting to routes."""
    def decorator(f):
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or 'unknown'
            if not check_rate_limit(ip):
                logger.warning(f"RATE LIMIT EXCEEDED: {ip} for {request.path}")
                return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper
    return decorator

def _load_cc_settings():
    """Load commandcenter settings from disk"""
    settings_file = Path.home() / ".claude" / "commandcenter_settings.json"
    try:
        if settings_file.exists():
            with open(settings_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {"auto_close_idle": True, "panels": {}}

def _save_settings(data):
    """Save commandcenter settings to disk"""
    settings_file = Path.home() / ".claude" / "commandcenter_settings.json"
    try:
        with open(settings_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")

def get_config_info():
    """Get current config profile and user info if available - cached for 5s"""
    global _config_info_cache
    now = time.time()
    if now - _config_info_cache.get("time", 0) < 60:
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
        user = "subscription"
    except Exception:
        profile = "unknown"
        user = None

    _config_info_cache = {"profile": profile, "user": user, "time": now}
    return {"profile": profile, "user": user}

@app.route("/api/config")
@rate_limit()
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


@app.route("/api/auth/check")
def api_auth_check():
    """On-demand claude auth check - returns user email if logged in."""
    try:
        result = gevent.subprocess.check_output(
            ["claude", "auth", "status", "--json"],
            stderr=gevent.subprocess.DEVNULL,
            timeout=5
        ).decode()
        auth_data = json.loads(result)
        email = auth_data.get("email", "logged in")
        return jsonify({"ok": True, "user": email})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/api/config/switch", methods=["POST"])
@rate_limit()
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
        _config_info_cache = {"profile": profile, "user": profile, "time": 0}
        logger.info(f"Config switched to {profile}")
        return jsonify({"ok": True, "profile": profile})
    except Exception as exc:
        logger.error(f"Config switch failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/config/save", methods=["POST"])
@rate_limit()
def api_config_save():
    data = request.get_json(force=True) or {}
    action = data.get("action")
    profile = data.get("profile")
    if profile not in ("bedrock", "subscription"):
        return jsonify({"error": "invalid profile"}), 400

    base = Path.home() / ".claude"
    settings = base / "settings.json"
    backup = base / BACKUP_NAMES[profile]

    if action == "save":
        try:
            shutil.copy2(settings, backup)
            logger.info(f"Config saved as {profile}")
            return jsonify({"ok": True, "profile": profile})
        except Exception as exc:
            logger.error(f"Config save failed: {exc}")
            return jsonify({"error": str(exc)}), 500

    elif action == "apply":
        if not backup.exists():
            return jsonify({"error": f"backup not found: {backup}"}), 404
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(settings, settings.with_name(f"settings.json.bak-{ts}"))
            shutil.copy2(backup, settings)
            logger.info(f"Config applied from {profile}")
            return jsonify({"ok": True, "profile": profile})
        except Exception as exc:
            logger.error(f"Config apply failed: {exc}")
            return jsonify({"error": str(exc)}), 500

    return jsonify({"error": "invalid action"}), 400


@app.route("/api/config/check-bedrock")
@rate_limit()
def api_check_bedrock():
    base = Path.home() / ".claude"
    bedrock_backup = base / "settings.bedrock-backup.json"
    return jsonify({"exists": bedrock_backup.exists()})


@app.route("/api/config/save-bedrock", methods=["POST"])
@rate_limit()
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
        with open(settings) as f:
            current = json.load(f)

        bedrock_config = json.loads(json.dumps(current))

        if "env" not in bedrock_config:
            bedrock_config["env"] = {}
        bedrock_config["env"]["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_config["env"]["AWS_REGION"] = region
        bedrock_config["env"]["AWS_BEARER_TOKEN_BEDROCK"] = token

        if "env" in bedrock_config and "CLAUDE_API_KEY" in bedrock_config["env"]:
            del bedrock_config["env"]["CLAUDE_API_KEY"]

        with open(bedrock_backup, "w") as f:
            json.dump(bedrock_config, f, indent=2)
        os.chmod(bedrock_backup, 0o600)

        logger.info("Bedrock config saved")
        return jsonify({"ok": True})
    except Exception as exc:
        logger.error(f"Save bedrock failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/settings/auto-close-idle")
@rate_limit()
def api_get_auto_close_idle():
    """Get auto-close idle sessions setting"""
    settings = _load_cc_settings()
    return jsonify({"enabled": settings.get("auto_close_idle", True)})


@app.route("/api/settings/auto-close-idle", methods=["POST"])
@rate_limit()
def api_set_auto_close_idle():
    """Set auto-close idle sessions setting"""
    data = request.get_json(force=True) or {}
    enabled = data.get("enabled", True)
    settings = _load_cc_settings()
    settings["auto_close_idle"] = enabled
    _save_settings(settings)
    logger.info(f"Auto-close idle set to {enabled}")
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/favicon.ico")
def favicon():
    # No icon asset shipped; answer cleanly instead of 404ing the console.
    return ("", 204)


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "tmux": tmux.is_available(),
        "tmux_sessions": len(tmux.list_windows()) if tmux.is_available() else 0,
        "active_ptys": sum(len(s) for s in ptys.values()),
        "uptime": time.time(),
    })


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


@app.route("/api/panel-state")
def api_panel_state():
    settings = _load_cc_settings()
    return jsonify(settings.get("panels", {}))


@app.route("/api/panel-state", methods=["PUT"])
def api_save_panel_state():
    data = request.get_json(force=True) or {}
    # data should be { "panels": { "0": {"project": "...", "agent": "..."}, ... } }
    panels_data = data.get("panels", {})
    if not isinstance(panels_data, dict):
        return jsonify({"error": "invalid panels data"}), 400
    settings = _load_cc_settings()
    settings["panels"] = panels_data
    _save_settings(settings)
    logger.info(f"Saved panel state: {panels_data}")
    return jsonify({"ok": True})


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
    """Emit event to all connected clients and log it."""
    logger.info(f"EVENT [{event_type}] {message[:200]}")
    socketio.emit("event_log", {
        "type": event_type,
        "message": message[:200],
        "timestamp": datetime.now().isoformat(),
    })


def audit_log(action, details=None, level="info"):
    """Security audit logging for important events."""
    ip = None
    try:
        ip = request.remote_addr if request else None
    except Exception:
        pass
    entry = f"AUDIT [{action}] ip={ip or 'unknown'}"
    if details:
        entry += f" {details}"
    if level == "warning":
        logger.warning(entry)
    elif level == "error":
        logger.error(entry)
    else:
        logger.info(entry)


ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*[\x07\x1b]")

# Session names are built as cc-<project>-<panel>-<agent>. Project names are
# sanitized (not hashed), so they DO appear in `tmux ls` / `ps` — this app is
# meant for trusted local use only (see the Security section in the README).
def _sanitize_session_name(name):
    """Sanitize string for use in tmux session names - only allow safe chars."""
    if not name:
        return "panel"
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)

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
# Background telemetry threads - run independently, don't block each other
# ---------------------------------------------------------------------------
def metrics_thread():
    import random
    logger.info("THREAD_START: metrics_thread")
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
            },)
        except Exception as exc:
            logger.warning(f"metrics_thread error: {exc}")
        gevent.sleep(2 + random.random() * 0.5)


def network_thread():
    import random
    logger.info("THREAD_START: network_thread")
    prev = psutil.net_io_counters()
    prev_t = time.time()
    while True:
        gevent.sleep(1.5 + random.random() * 0.5)
        try:
            cur = psutil.net_io_counters()
            now = time.time()
            dt = max(0.5, now - prev_t)
            rx_bps = (cur.bytes_recv - prev.bytes_recv) / dt
            tx_bps = (cur.bytes_sent - prev.bytes_sent) / dt
            prev, prev_t = cur, now
            socketio.emit("network_update", {
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
                "rx_total": cur.bytes_recv,
                "tx_total": cur.bytes_sent,
            },)
        except Exception as exc:
            logger.warning(f"network_thread error: {exc}")


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
    logger.info("THREAD_START: weather_thread")
    while True:
        try:
            data = weather_service.get_current()
            emoji = get_weather_emoji(data['condition'])
            text = f"{emoji} {data['temp_c']:.0f}°C {data['condition']}"
            socketio.emit("weather_update", {"text": text, **data})
        except Exception as exc:
            logger.warning(f"weather_thread error: {exc}")
        gevent.sleep(60)


# Fingerprints that mean an agent pane is still on its first-launch / login
# screen — never typed in, never authed. Combined with idle time + the "not
# currently bound to a visible panel" check, these mark sessions safe to kill.
NEVER_USED_FINGERPRINTS = (
    "sign in with chatgpt",
    "sign in with device code",
    "sign in with anthropic",
    "claude code v",
    "welcome to claude code",
    "welcome to codex",
    "type a message",
    "press enter to start",
    "choose a template",
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
    logger.info("THREAD_START: tmux_janitor")
    # Cache tmux availability since it doesn't change during runtime
    tmux_available = tmux.is_available()

    while True:
        gevent.sleep(60)
        settings = _load_cc_settings()
        if not settings.get("auto_close_idle", True):
            continue
        if not tmux_available:
            continue
        try:
            # Use session start time instead of activity time to detect truly unused sessions
            # Activity time can be reset by ANY interaction in the session
            raw = subprocess.check_output(
                ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_started}"],
                stderr=subprocess.DEVNULL,
            ).decode().splitlines()
        except Exception as e:
            logger.warning(f"tmux_janitor list-sessions failed: {e}")
            continue
        now = time.time()
        in_use = _sessions_in_use()
        for line in raw:
            try:
                name, started = line.split("\t")
            except ValueError:
                continue
            if not name.startswith("cc-") or name in in_use:
                continue
            try:
                age = now - int(started)
            except ValueError:
                continue
            # Use session age (> 10 minutes) instead of idle time
            # This ensures we only kill sessions that have been running long enough
            # to be truly "never used" rather than just temporarily idle
            if age < 600:  # 10 minutes
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
                except Exception as e:
                    logger.warning(f"tmux_janitor kill-session failed for {name}: {e}")


def git_thread():
    logger.info("THREAD_START: git_thread")
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
                except Exception as exc:
                    logger.warning(f"git status failed for {project_name}: {exc}")
                    socketio.emit("git_update", {"panel": panel_id, "project": project_name, "git": None})
        except Exception as exc:
            logger.warning(f"git_thread error: {exc}")
        gevent.sleep(10)


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
    except Exception as e:
        logger.warning(f"socket weather on connect failed: {e}")


@socketio.on("disconnect")
def handle_disconnect():
    sid_ptys = ptys.pop(request.sid, {})
    for slot in sid_ptys.values():
        for key in ("bridge", "bash_bridge"):
            br = slot.get(key)
            if br:
                try:
                    br.close()
                except Exception as e:
                    logger.warning(f"socket bridge close error: {e}")
    emit_event("INFO", f"client disconnected · {request.sid[:6]}")


def _resolve_project(name):
    for p in switcher.load_projects():
        if p["name"] == name:
            return p
    return None


@socketio.on("term_open")
def handle_term_open(data):
    sid = request.sid
    # Input validation - ensure panel/rows/cols are within reasonable bounds
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            panel = 0
    except (ValueError, TypeError):
        panel = 0
    try:
        rows = int(data.get("rows", 40))
        rows = max(1, min(rows, 200))  # Clamp between 1 and 200
    except (ValueError, TypeError):
        rows = 40
    try:
        cols = int(data.get("cols", 120))
        cols = max(1, min(cols, 300))  # Clamp between 1 and 300
    except (ValueError, TypeError):
        cols = 120

    project_name = data.get("project")
    if project_name and not isinstance(project_name, str):
        project_name = None

    proj = _resolve_project(project_name) if project_name else None
    if proj:
        cwd = proj.get("path") or os.getcwd()
        agent = data.get("agent") or proj.get("agent") or "claude"
    else:
        cwd = os.getcwd()
        agent = data.get("agent", "claude")

    if not os.path.isdir(cwd):
        cwd = os.getcwd()

    safe_cwd = shlex.quote(cwd)
    agent_cmd = agent if agent in AGENT_CYCLE else "claude"
    # Session name includes project + panel (channel) + agent so each panel
    # gets its own tmux session. Switching agents keeps each one's session
    # alive in the background. Reattaching resumes existing conversation.
    # Sanitize project name to prevent invalid tmux session names
    safe_project = _sanitize_session_name(project_name)
    session = f"cc-{safe_project}-{panel}-{agent_cmd}"

    # fnm (node version manager) setup for codex
    fnm_setup = 'export PATH="$HOME/.local/share/fnm:$PATH"; eval "$(fnm env 2>/dev/null)" 2>/dev/null;'

    if tmux.is_available():
        # Resume the session if it already exists (page refresh / reconnect keeps
        # the agent's conversation and scrollback intact); otherwise start it
        # fresh. Switching agents targets a different session name, so that still
        # spawns a new session while the previous agent keeps running in the
        # background. The idle janitor reaps never-used sessions.
        shell_cmd = (
            f"{fnm_setup} cd {safe_cwd} && "
            f"(tmux has-session -t {session!r} 2>/dev/null && exec tmux attach-session -t {session!r} || "
            f"(command -v {agent_cmd} >/dev/null && "
            f"exec tmux new-session -s {session!r} -n {agent_cmd!r} 'while command -v {agent_cmd} >/dev/null 2>&1; do {agent_cmd}; sleep 1; done' || "
            f"exec bash -i))"
        )
    else:
        shell_cmd = (
            f"{fnm_setup} cd {safe_cwd} && "
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
        try:
            socketio.emit(
                "term_output",
                {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
                to=_sid,
            )
            scan_pty_signals(_sid, _panel, chunk)
        except Exception as e:
            logger.warning(f"PTY on_data error panel {_panel}: {e}")

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
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
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
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    slot = ptys.get(request.sid, {}).get(panel)
    if slot:
        try:
            rows = int(data.get("rows", 40))
            rows = max(1, min(rows, 200))
        except (ValueError, TypeError):
            rows = 40
        try:
            cols = int(data.get("cols", 120))
            cols = max(1, min(cols, 300))
        except (ValueError, TypeError):
            cols = 120
        slot["bridge"].resize(rows, cols)


@socketio.on("term_close")
def handle_term_close(data):
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    slot = ptys.get(request.sid, {}).pop(panel, None)
    if slot:
        for key in ("bridge", "bash_bridge"):
            br = slot.get(key)
            if br:
                try:
                    br.close()
                except Exception as e:
                    logger.warning(f"socket bridge close error: {e}")


# ---------------------------------------------------------------------------
# Socket: bottom-of-panel bash terminal (per-panel, rooted at project path)
# ---------------------------------------------------------------------------
@socketio.on("term_bash_open")
def handle_term_bash_open(data):
    sid = request.sid
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    try:
        rows = int(data.get("rows", 15))
        rows = max(1, min(rows, 100))
    except (ValueError, TypeError):
        rows = 15
    try:
        cols = int(data.get("cols", 120))
        cols = max(1, min(cols, 300))
    except (ValueError, TypeError):
        cols = 120

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
        try:
            socketio.emit(
                "term_bash_output",
                {"panel": _panel, "data": chunk.decode("utf-8", errors="replace")},
                to=_sid,
            )
        except Exception as e:
            logger.warning(f"BASH_TERM on_data error panel {_panel}: {e}")

    bridge = PtyBridge(["/bin/bash", "-lc", inner], on_data, rows=rows, cols=cols)
    slot["bash_bridge"] = bridge


@socketio.on("term_bash_input")
def handle_term_bash_input(data):
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        slot["bash_bridge"].write(data.get("data", ""))


@socketio.on("term_bash_resize")
def handle_term_bash_resize(data):
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        try:
            rows = int(data.get("rows", 15))
            rows = max(1, min(rows, 100))
        except (ValueError, TypeError):
            rows = 15
        try:
            cols = int(data.get("cols", 120))
            cols = max(1, min(cols, 300))
        except (ValueError, TypeError):
            cols = 120
        slot["bash_bridge"].resize(rows, cols)


@socketio.on("term_bash_close")
def handle_term_bash_close(data):
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
    slot = ptys.get(request.sid, {}).get(panel)
    if slot and slot.get("bash_bridge"):
        try:
            slot["bash_bridge"].close()
        except Exception as e:
            logger.warning(f"BASH_TERM close error: {e}")
        slot["bash_bridge"] = None


@socketio.on("agent_switch")
def handle_agent_switch(data):
    """Set the agent for a project (or cycle if no agent specified)."""
    project_name = data.get("project")
    try:
        panel = int(data.get("panel", 0))
        if panel not in (0, 1, 2):
            return
    except (ValueError, TypeError):
        return
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
        # Save panel state
        settings = _load_cc_settings()
        settings.setdefault("panels", {})[str(panel)] = {
            "project": project_name,
            "agent": new_agent
        }
        _save_settings(settings)
    except ValueError as e:
        emit_event("ERROR", str(e))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Starting CommandCenter v{__version__}")

    import signal
    # Handle SIGNALS for systemd - allow graceful shutdown
    def handle_signal(signum, frame):
        global shutdown_requested
        logger.info(f"Shutdown signal received ({signum})")
        shutdown_requested = True
        for sid_map in list(ptys.values()):
            for slot in sid_map.values():
                for key in ("bridge", "bash_bridge"):
                    br = slot.get(key)
                    if br:
                        try:
                            br.close()
                        except Exception:
                            pass
        logger.info("All PTY bridges closed, exiting")
        pid_file = Path("/tmp/commandcenter.pid")
        pid_file.unlink(missing_ok=True)
        os._exit(0)
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)

    port = int(os.environ.get("CC_PORT", 5050))
    logger.info(f"⚡ commandcenter on http://0.0.0.0:{port} (tmux={'on' if tmux.is_available() else 'off'})")

    # Write PID file so launchers can find us
    pid_file = Path("/tmp/commandcenter.pid")
    pid_file.write_text(str(os.getpid()))
    logger.info(f"Writing PID {os.getpid()} to {pid_file}")
    logger.info("STARTING background threads...")
    socketio.start_background_task(metrics_thread)
    logger.info("  -> metrics_thread started")
    socketio.start_background_task(network_thread)
    logger.info("  -> network_thread started")
    socketio.start_background_task(weather_thread)
    logger.info("  -> weather_thread started")
    socketio.start_background_task(git_thread)
    logger.info("  -> git_thread started")
    socketio.start_background_task(tmux_janitor)
    logger.info("  -> tmux_janitor started")
    logger.info("ALL threads launched, starting server...")
    # Explicit gevent WSGIServer + WebSocketHandler — Flask-SocketIO's auto-
    # detection of gevent-websocket can fail silently, leaving Socket.IO stuck
    # on long-polling. Wiring the handler ourselves guarantees the upgrade.
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    try:
        pywsgi.WSGIServer(
            ("0.0.0.0", port), app, handler_class=WebSocketHandler, log=None
        ).serve_forever()
    except Exception as exc:
        logger.error(f"SERVER CRASHED: {exc}")
        import traceback
        logger.error(traceback.format_exc())
        # Clean up PID file before exit
        try:
            pid_file = Path("/tmp/commandcenter.pid")
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        os._exit(1)  # sys.exit doesn't work when signals are ignored - force exit
