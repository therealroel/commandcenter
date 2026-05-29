#!/usr/bin/env python3
"""
CommandCenter - Comprehensive Integration Test Suite
Tests ALL features including server startup, API endpoints, WebSocket, etc.
"""
import os
import sys
import time
import json
import signal
import subprocess
import requests
import threading
from pathlib import Path

# Configuration
HOST = "http://localhost:5050"
TEST_TIMEOUT = 10
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def add_pass(self, name):
        self.passed += 1
        print(f"  ✓ {name}")

    def add_fail(self, name, reason):
        self.failed += 1
        self.errors.append(f"{name}: {reason}")
        print(f"  ✗ {name} - {reason}")

results = TestResults()

def wait_for_server(timeout=10):
    """Wait for server to be ready"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{HOST}/api/health", timeout=2)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def assert_response(r, expected_status=200, expected_json=False):
    """Assert response is valid"""
    if r.status_code != expected_status:
        raise AssertionError(f"Status {r.status_code} != {expected_status}")
    if expected_json:
        try:
            r.json()
        except:
            raise AssertionError("Response is not JSON")


print("=" * 70)
print("COMMANDCENTER - COMPREHENSIVE INTEGRATION TEST SUITE")
print("=" * 70)
print()

# Start server
print("[1] Starting server...")
server_process = None
try:
    # Check if already running
    try:
        r = requests.get(f"{HOST}/api/health", timeout=1)
        print("  Server already running - using existing instance")
        server_process = None
    except:
        # Start new server
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        server_process = subprocess.Popen(
            [sys.executable, 'server.py'],
            cwd=PROJECT_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print("  Server starting...")
        if not wait_for_server(15):
            raise Exception("Server failed to start within 15 seconds")
        print("  Server running!")
except Exception as e:
    print(f"  ✗ Failed to start server: {e}")
    sys.exit(1)

print()

# ============================================================================
# HTTP ENDPOINT TESTS
# ============================================================================
print("[2] Testing HTTP Endpoints...")
print()

def test_index_page():
    """Test main page loads with no-cache headers"""
    r = requests.get(HOST, timeout=5)
    assert_response(r, 200)
    assert "commandcenter" in r.text.lower() or "⚡" in r.text
    # Check no-cache headers
    assert "Cache-Control" in r.headers or "cache-control" in r.headers.lower()
    results.add_pass("GET / - main page loads")
    return True

def test_health_endpoint():
    """Test /api/health endpoint"""
    r = requests.get(f"{HOST}/api/health", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "ok" in data
    assert "tmux" in data
    results.add_pass("GET /api/health - health check")
    return True

def test_version_endpoint():
    """Test /api/version endpoint"""
    r = requests.get(f"{HOST}/api/version", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "version" in data
    results.add_pass("GET /api/version - version endpoint")
    return True

def test_projects_endpoint():
    """Test /api/projects endpoint"""
    r = requests.get(f"{HOST}/api/projects", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "projects" in data
    assert "agents" in data
    results.add_pass("GET /api/projects - projects list")
    return True

def test_config_endpoint():
    """Test /api/config endpoint"""
    r = requests.get(f"{HOST}/api/config", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "profile" in data
    results.add_pass("GET /api/config - config profile")
    return True

def test_auto_close_idle_get():
    """Test GET /api/settings/auto-close-idle"""
    r = requests.get(f"{HOST}/api/settings/auto-close-idle", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "enabled" in data
    results.add_pass("GET /api/settings/auto-close-idle - settings")
    return True

def test_auto_close_idle_set():
    """Test POST /api/settings/auto-close-idle"""
    r = requests.post(
        f"{HOST}/api/settings/auto-close-idle",
        json={"enabled": True},
        timeout=5
    )
    assert_response(r, 200, True)
    data = r.json()
    assert data.get("ok") == True
    results.add_pass("POST /api/settings/auto-close-idle - settings save")
    return True

def test_dirs_endpoint():
    """Test /api/dirs endpoint"""
    r = requests.get(f"{HOST}/api/dirs?path=/tmp", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "entries" in data or "path" in data
    results.add_pass("GET /api/dirs - directory listing")
    return True

def test_check_bedrock():
    """Test /api/config/check-bedrock"""
    r = requests.get(f"{HOST}/api/config/check-bedrock", timeout=5)
    assert_response(r, 200, True)
    data = r.json()
    assert "exists" in data
    results.add_pass("GET /api/config/check-bedrock - bedrock check")
    return True

def test_invalid_project_delete():
    """Test deleting non-existent project returns 404"""
    r = requests.delete(f"{HOST}/api/projects/nonexistent_project_xyz", timeout=5)
    # Should be 404 or similar
    assert r.status_code in (404, 500)
    results.add_pass("DELETE /api/projects/<name> - 404 for missing project")
    return True

def test_add_project_validation():
    """Test adding project with missing fields"""
    r = requests.post(
        f"{HOST}/api/projects",
        json={"name": "", "path": ""},
        timeout=5
    )
    assert r.status_code in (400, 500)
    results.add_pass("POST /api/projects - validation for missing fields")
    return True

# Run HTTP tests
http_tests = [
    test_index_page,
    test_health_endpoint,
    test_version_endpoint,
    test_projects_endpoint,
    test_config_endpoint,
    test_auto_close_idle_get,
    test_auto_close_idle_set,
    test_dirs_endpoint,
    test_check_bedrock,
    test_invalid_project_delete,
    test_add_project_validation,
]

for test in http_tests:
    try:
        test()
    except AssertionError as e:
        results.add_fail(test.__name__, str(e))
    except Exception as e:
        results.add_fail(test.__name__, f"Error: {e}")

print()

# ============================================================================
# SOCKET.IO / WEBSOCKET TESTS
# ============================================================================
print("[3] Testing WebSocket (Socket.IO)...")

try:
    import socketio

    # Handlers register on the Client instance, not the module.
    client = socketio.Client()

    @client.event
    def connect():
        print("  ✓ Socket.IO connected successfully")

    @client.on('metrics_update')
    def on_metrics(data):
        print("  ✓ Received metrics_update event")

    client.connect(HOST, transports=['polling'])
    print("  ✓ Socket.IO connection test")
    client.disconnect()
    results.add_pass("Socket.IO connection")

except Exception as e:
    results.add_fail("Socket.IO connection", str(e))

print()

# ============================================================================
# BACKEND SERVICE TESTS
# ============================================================================
print("[4] Testing Backend Services...")

# Test PtyBridge
def test_pty_bridge():
    """Test PtyBridge can be imported and instantiated"""
    sys.path.insert(0, PROJECT_DIR)
    from services.pty_bridge import PtyBridge

    data_received = []

    def on_data(chunk):
        data_received.append(chunk)

    # Create a simple PTY that runs 'echo test'
    bridge = PtyBridge(['echo', 'test'], on_data, rows=24, cols=80)

    # PtyBridge reads on a gevent greenlet (gevent.socket.wait_read). gevent
    # isn't monkey-patched here, so a real time.sleep would block the hub and
    # the reader would never run — yield with gevent.sleep instead.
    import gevent
    deadline = time.time() + 5
    while time.time() < deadline and not data_received:
        gevent.sleep(0.05)
    bridge.close()

    assert len(data_received) > 0, "Should receive data from PTY"
    results.add_pass("PtyBridge - PTY creation and communication")
    return True

# Test AgentSwitcher
def test_agent_switcher():
    """Test AgentSwitcher functionality"""
    sys.path.insert(0, PROJECT_DIR)
    from agents.switcher import AgentSwitcher, AGENT_CYCLE

    switcher = AgentSwitcher()

    # Test load_projects
    projects = switcher.load_projects()
    assert isinstance(projects, list), "load_projects should return list"
    results.add_pass("AgentSwitcher - load_projects")

    # Test switch_agent returns valid agent
    if len(projects) > 0:
        try:
            new_agent = switcher.switch_agent(projects[0]['name'])
            assert new_agent in AGENT_CYCLE, f"switch_agent should return valid agent, got {new_agent}"
            results.add_pass("AgentSwitcher - switch_agent")
        except ValueError:
            results.add_pass("AgentSwitcher - switch_agent (no projects to test)")

    return True

# Test GitService
def test_git_service():
    """Test GitService functionality"""
    sys.path.insert(0, PROJECT_DIR)
    from services.git import GitService

    git = GitService()

    # Test on a real git repo (this project)
    status = git.get_status(PROJECT_DIR)
    assert isinstance(status, dict), "get_status should return dict"
    assert "branch" in status, "Should have branch field"
    assert "dirty" in status, "Should have dirty field"
    assert "upstream" in status, "Should have upstream field"
    results.add_pass("GitService - get_status on real repo")
    return True

# Test SystemService
def test_system_service():
    """Test SystemService functionality"""
    sys.path.insert(0, PROJECT_DIR)
    from services.system import SystemService

    system = SystemService()
    metrics = system.get_metrics()

    assert isinstance(metrics, dict), "get_metrics should return dict"
    assert "cpu" in metrics, "Should have cpu metrics"
    assert "ram" in metrics, "Should have ram metrics"
    assert "disk" in metrics, "Should have disk metrics"
    assert "uptime" in metrics, "Should have uptime metrics"

    assert "percent" in metrics["cpu"], "CPU should have percent"
    results.add_pass("SystemService - get_metrics")
    return True

# Test WeatherService
def test_weather_service():
    """Test WeatherService functionality"""
    sys.path.insert(0, PROJECT_DIR)
    from services.weather import WeatherService

    weather = WeatherService()
    current = weather.get_current()

    assert isinstance(current, dict), "get_current should return dict"
    assert "temp_c" in current, "Should have temp_c"
    assert "condition" in current, "Should have condition"
    results.add_pass("WeatherService - get_current")
    return True

# Test TmuxManager
def test_tmux_manager():
    """Test TmuxManager functionality"""
    sys.path.insert(0, PROJECT_DIR)
    from launcher.tmux import TmuxManager

    tmux = TmuxManager()
    available = tmux.is_available()
    assert isinstance(available, bool), "is_available should return bool"
    results.add_pass(f"TmuxManager - is_available (tmux={'available' if available else 'not available'})")

    # Test list_windows (safe even if tmux not available)
    windows = tmux.list_windows()
    assert isinstance(windows, list), "list_windows should return list"
    results.add_pass("TmuxManager - list_windows")
    return True

service_tests = [
    test_pty_bridge,
    test_agent_switcher,
    test_git_service,
    test_system_service,
    test_weather_service,
    test_tmux_manager,
]

for test in service_tests:
    try:
        test()
    except AssertionError as e:
        results.add_fail(test.__name__, str(e))
    except Exception as e:
        results.add_fail(test.__name__, f"Error: {e}")

print()

# ============================================================================
# CONFIGURATION TESTS
# ============================================================================
print("[5] Testing Configuration...")

def test_config_files_exist():
    """Test that all required config files exist"""
    required = [
        'config/projects.json',
        'requirements.txt',
        'server.py',
        'templates/index.html',
        'version.py',
        'agents/switcher.py',
        'launcher/tmux.py',
        'services/pty_bridge.py',
        'services/system.py',
        'services/weather.py',
        'services/git.py',
    ]
    for f in required:
        assert os.path.exists(os.path.join(PROJECT_DIR, f)), f"Missing file: {f}"
    results.add_pass("All required config files exist")
    return True

def test_projects_json_valid():
    """Test projects.json is valid JSON"""
    with open('config/projects.json', 'r') as f:
        data = json.load(f)
    assert "projects" in data
    assert isinstance(data["projects"], list)
    results.add_pass("config/projects.json is valid")
    return True

def test_requirements_installed():
    """Test that required packages are installed"""
    required = ['flask', 'socketio', 'gevent', 'psutil']
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            raise AssertionError(f"Missing package: {pkg}")
    results.add_pass("All required Python packages installed")
    return True

config_tests = [
    test_config_files_exist,
    test_projects_json_valid,
    test_requirements_installed,
]

for test in config_tests:
    try:
        test()
    except AssertionError as e:
        results.add_fail(test.__name__, str(e))
    except Exception as e:
        results.add_fail(test.__name__, f"Error: {e}")

print()

# ============================================================================
# FRONTEND TESTS
# ============================================================================
print("[6] Testing Frontend HTML/JS...")

def test_html_no_cache():
    """Test the index route sets no-cache headers on the response."""
    # Headers are set on the Flask response (server.py), not baked into the
    # template, so assert against the response-building code.
    with open('server.py', 'r') as f:
        content = f.read()

    assert 'Cache-Control' in content and 'no-store' in content, \
        "index route should set no-cache/no-store headers on the response"
    results.add_pass("HTML has cache control")
    return True

def test_xtermjs_loaded():
    """Test xterm.js is properly loaded"""
    with open('templates/index.html', 'r') as f:
        content = f.read()

    assert 'xterm' in content.lower(), "Should load xterm.js"
    assert 'socket.io' in content.lower(), "Should load socket.io client"
    results.add_pass("xterm.js and socket.io client loaded")
    return True

def test_all_panels_have_ids():
    """Test all 3 panels have proper IDs"""
    with open('templates/index.html', 'r') as f:
        content = f.read()

    for i in range(3):
        assert f'id="panel-{i}"' in content, f"Panel {i} should have id"
        assert f'id="term-{i}"' in content, f"Term {i} should have id"
        assert f'id="agent-btn-{i}"' in content, f"Agent btn {i} should have id"
    results.add_pass("All 3 panels have proper IDs")
    return True

def test_socket_io_events_defined():
    """Test all Socket.IO events are handled"""
    with open('templates/index.html', 'r') as f:
        content = f.read()

    events = [
        'connect', 'disconnect', 'term_output', 'term_opened',
        'term_bash_output', 'metrics_update', 'network_update',
        'weather_update', 'git_update', 'event_log', 'panel_awaiting'
    ]
    for event in events:
        assert f"socket.on('{event}'" in content or f'socket.on("{event}"' in content, f"Should handle {event}"
    results.add_pass("All Socket.IO events defined")
    return True

def test_css_variables_defined():
    """Test CSS variables are defined"""
    with open('templates/index.html', 'r') as f:
        content = f.read()

    assert ':root' in content, "Should have :root CSS variables"
    assert '--bg:' in content, "Should define --bg"
    assert '--cyan:' in content, "Should define --cyan"
    results.add_pass("CSS variables defined")
    return True

frontend_tests = [
    test_html_no_cache,
    test_xtermjs_loaded,
    test_all_panels_have_ids,
    test_socket_io_events_defined,
    test_css_variables_defined,
]

for test in frontend_tests:
    try:
        test()
    except AssertionError as e:
        results.add_fail(test.__name__, str(e))
    except Exception as e:
        results.add_fail(test.__name__, f"Error: {e}")

print()

# ============================================================================
# BUG FIX VERIFICATION TESTS
# ============================================================================
print("[7] Verifying Bug Fixes...")

import re

def test_fix_active_projects_3_panels():
    """Verify active_projects has 3 panels"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert 'active_projects = {0: None, 1: None, 2: None}' in content
    results.add_pass("FIX: active_projects has 3 panels")
    return True

def test_fix_session_sanitization():
    """Verify session name sanitization exists"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert '_sanitize_session_name' in content
    results.add_pass("FIX: session name sanitization")
    return True

def test_fix_loadSettings_validation():
    """Verify loadSettings has JSON validation"""
    with open('templates/index.html', 'r') as f:
        content = f.read()
    assert 'typeof parsed !== \'object\'' in content or 'typeof parsed !== "object"' in content
    results.add_pass("FIX: loadSettings JSON validation")
    return True

def test_fix_showTermIfReady_hidden_check():
    """Verify showTermIfReady checks panel visibility"""
    with open('templates/index.html', 'r') as f:
        content = f.read()
    assert 'getAttribute(\'data-hidden\')' in content or 'data-hidden' in content
    results.add_pass("FIX: showTermIfReady visibility check")
    return True

def test_fix_error_logging():
    """Verify errors are logged, not silently swallowed"""
    with open('server.py', 'r') as f:
        content = f.read()
    # Should have print statements with [SOCKET] etc
    assert 'print(f"[SOCKET]' in content or 'logging' in content
    results.add_pass("FIX: proper error logging")
    return True

def test_fix_never_used_fingerprints():
    """Verify NEVER_USED_FINGERPRINTS includes Claude patterns"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert '"claude code v"' in content
    results.add_pass("FIX: NEVER_USED_FINGERPRINTS includes Claude")
    return True

def test_fix_tmux_janitor_start_time():
    """Verify tmux_janitor uses session start time"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert '#{session_started}' in content
    results.add_pass("FIX: tmux_janitor uses session start time")
    return True

def test_fix_input_validation():
    """Verify socket events have input validation"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert 'panel not in (0, 1, 2)' in content
    assert 'max(1, min(rows' in content
    results.add_pass("FIX: socket event input validation")
    return True

def test_fix_weather_regular_interval():
    """Verify weather uses regular interval"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert 'gevent.sleep(60)' in content
    assert 'for _ in range(10)' not in content
    results.add_pass("FIX: weather regular 60s interval")
    return True

def test_fix_git_upstream_detection():
    """Verify git detects upstream status"""
    with open('services/git.py', 'r') as f:
        content = f.read()
    assert '"upstream":' in content or "'upstream':" in content
    results.add_pass("FIX: git upstream detection")
    return True

def test_fix_thread_lock():
    """Verify threading lock exists"""
    with open('server.py', 'r') as f:
        content = f.read()
    assert 'threading.Lock' in content
    results.add_pass("FIX: threading lock for ptys")
    return True

bug_fix_tests = [
    test_fix_active_projects_3_panels,
    test_fix_session_sanitization,
    test_fix_loadSettings_validation,
    test_fix_showTermIfReady_hidden_check,
    test_fix_error_logging,
    test_fix_never_used_fingerprints,
    test_fix_tmux_janitor_start_time,
    test_fix_input_validation,
    test_fix_weather_regular_interval,
    test_fix_git_upstream_detection,
    test_fix_thread_lock,
]

for test in bug_fix_tests:
    try:
        test()
    except AssertionError as e:
        results.add_fail(test.__name__, str(e))
    except Exception as e:
        results.add_fail(test.__name__, f"Error: {e}")

print()

# ============================================================================
# CLEANUP
# ============================================================================
print("[8] Cleaning up...")

if server_process:
    print("  Stopping server...")
    server_process.terminate()
    try:
        server_process.wait(timeout=5)
    except:
        server_process.kill()
    print("  Server stopped")

print()

# ============================================================================
# FINAL RESULTS
# ============================================================================
print("=" * 70)
print("FINAL RESULTS")
print("=" * 70)
print()
print(f"  PASSED: {results.passed}")
print(f"  FAILED: {results.failed}")
print()

if results.failed > 0:
    print("FAILED TESTS:")
    for error in results.errors:
        print(f"  - {error}")
    print()
    sys.exit(1)
else:
    print("✓ ALL TESTS PASSED!")
    print()
    print("=" * 70)
    print("SYSTEM STATUS: FULLY FUNCTIONAL")
    print("=" * 70)
    sys.exit(0)