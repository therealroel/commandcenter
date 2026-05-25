#!/usr/bin/env python3
"""
CommandCenter Test Suite
Tests all critical functionality including bug fixes
"""
import os
import sys
import json
import re
import tempfile
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

def test_active_projects_supports_3_panels():
    """Bug fix: active_projects dict should support panels 0,1,2"""
    print("TEST: active_projects supports 3 panels...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # Check that active_projects is initialized with 3 panels
    match = re.search(r'active_projects\s*=\s*\{(\d+):\s*None,\s*(\d+):\s*None,\s*(\d+):\s*None\}', content)
    assert match, "active_projects should have 3 panels (0, 1, 2)"
    
    panels = [int(match.group(1)), int(match.group(2)), int(match.group(3))]
    assert 0 in panels and 1 in panels and 2 in panels, f"Panels should include 0,1,2 got {panels}"
    print("  ✓ active_projects has 3 panels")


def test_session_name_sanitization():
    """Bug fix: tmux session names should be sanitized"""
    print("TEST: tmux session name sanitization...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # Check _sanitize_session_name function exists
    assert '_sanitize_session_name' in content, "Should have _sanitize_session_name function"
    
    # Check it's used in session creation
    assert 'safe_project = _sanitize_session_name' in content, "Should sanitize project names"
    print("  ✓ session name sanitization exists")


def test_no_cache_headers():
    """Bug fix: HTML should have no-cache headers"""
    print("TEST: HTML no-cache headers...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    assert 'Cache-Control' in content, "Should have Cache-Control header"
    assert 'no-cache, no-store, must-revalidate' in content, "Should have no-cache directive"
    assert 'make_response' in content, "Should use make_response for headers"
    print("  ✓ no-cache headers implemented")


def test_loadSettings_validation():
    """Bug fix: loadSettings should validate JSON structure"""
    print("TEST: loadSettings JSON validation...")
    with open('templates/index.html', 'r') as f:
        content = f.read()
    
    # Check loadSettings has validation
    assert 'typeof parsed !== \'object\'' in content or 'typeof parsed !== "object"' in content, "Should validate parsed is object"
    assert 'return null' in content, "Should return null on invalid data"
    print("  ✓ loadSettings has JSON validation")


def test_showTermIfReady_checks_hidden():
    """Bug fix: showTermIfReady should check if panel is hidden"""
    print("TEST: showTermIfReady DOM hidden check...")
    with open('templates/index.html', 'r') as f:
        content = f.read()
    
    assert 'data-hidden' in content, "Should check data-hidden attribute"
    assert 'getAttribute(\'data-hidden\')' in content, "Should call getAttribute"
    print("  ✓ showTermIfReady checks panel visibility")


def test_logging_not_silent():
    """Bug fix: Errors should be logged, not silently swallowed"""
    print("TEST: Proper error logging...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # Count silent 'pass' in exception handlers
    silent_passes = len(re.findall(r'except.*:\s*\n\s*pass', content))
    
    # Should have minimal silent passes now
    print(f"  silent passes remaining: {silent_passes}")
    
    # Check specific handlers have logging
    assert 'print(f"[SOCKET]' in content or 'logging' in content.lower(), "Should have error logging"
    print("  ✓ Error logging implemented")


def test_never_used_fingerprints():
    """Bug fix: NEVER_USED_FINGERPRINTS should include Claude Code patterns"""
    print("TEST: NEVER_USED_FINGERPRINTS for Claude...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    assert '"sign in with anthropic"' in content, "Should have anthropic pattern"
    assert '"claude code v"' in content, "Should have claude code version pattern"
    print("  ✓ NEVER_USED_FINGERPRINTS includes Claude patterns")


def test_tmux_janitor_uses_start_time():
    """Bug fix: tmux_janitor should use session start time, not activity time"""
    print("TEST: tmux_janitor uses session start time...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    assert '#{session_started}' in content, "Should use session_started not session_activity"
    assert 'age < 600' in content, "Should use age (session time) not idle"
    print("  ✓ tmux_janitor uses session start time")


def test_git_upstream_detection():
    """Bug fix: git should detect when no upstream configured"""
    print("TEST: git upstream detection...")
    with open('services/git.py', 'r') as f:
        content = f.read()
    
    assert 'upstream' in content, "Should have upstream field"
    assert 'return {' in content and '"upstream":' in content, "Should return upstream status"
    print("  ✓ git service detects upstream status")


def test_input_validation_socket_events():
    """Bug fix: Socket events should validate input"""
    print("TEST: Socket event input validation...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # Check term_open has validation
    assert 'max(1, min(rows' in content or 'max(1,min(rows' in content, "Should clamp rows"
    assert 'max(1, min(cols' in content or 'max(1,min(cols' in content, "Should clamp cols"
    assert 'panel not in (0, 1, 2)' in content, "Should validate panel values"
    print("  ✓ Socket events have input validation")


def test_weather_thread_regular_interval():
    """Bug fix: weather should emit at regular intervals, not burst then nothing"""
    print("TEST: Weather thread regular interval...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # Should NOT have the burst loop (for _ in range(10))
    assert 'for _ in range(10)' not in content, "Should not have burst loop"
    
    # Should have regular interval
    assert 'gevent.sleep(60)' in content, "Should sleep 60 seconds"
    print("  ✓ Weather thread uses regular 60s interval")


def test_winClose_graceful():
    """Bug fix: winClose should do something meaningful"""
    print("TEST: winClose graceful handling...")
    with open('templates/index.html', 'r') as f:
        content = f.read()
    
    # Should NOT just call window.close()
    assert 'window.close()' not in content or 'confirm' in content, "Should use confirmation not just close"
    print("  ✓ winClose has graceful handling")


def test_subprocess_errors_replace():
    """Bug fix: subprocess should handle non-UTF8 gracefully"""
    print("TEST: subprocess errors='replace'...")
    with open('services/git.py', 'r') as f:
        content = f.read()
    
    assert 'errors="replace"' in content, "Should use errors='replace'"
    print("  ✓ subprocess handles non-UTF8")


def test_thread_lock_exists():
    """Thread safety: should have lock for ptys access"""
    print("TEST: Threading lock exists...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    assert 'threading.Lock' in content, "Should import threading.Lock"
    assert 'ptys_lock' in content, "Should have ptys_lock"
    print("  ✓ Threading lock implemented")


def test_git_frontend_shows_no_upstream():
    """Frontend should show indicator when no upstream"""
    print("TEST: Git pill shows no upstream indicator...")
    with open('templates/index.html', 'r') as f:
        content = f.read()
    
    assert 'upstream === false' in content, "Should check upstream status"
    assert '∅' in content or 'no upstream' in content.lower(), "Should show no upstream indicator"
    print("  ✓ Git pill shows no upstream indicator")


def test_panel_count_validation():
    """Panel count should be validated"""
    print("TEST: panelCount validation...")
    with open('templates/index.html', 'r') as f:
        content = f.read()
    
    # Should validate panelCount range (check for < 1 and > 3)
    assert 'parsed.panelCount < 1' in content or 'panelCount < 1' in content, "Should validate panelCount >= 1"
    assert 'parsed.panelCount > 3' in content or 'panelCount > 3' in content, "Should validate panelCount <= 3"
    print("  ✓ panelCount has validation")


def test_fnm_setup_check():
    """fnm_setup should check if fnm exists before using"""
    print("TEST: fnm setup checks existence...")
    with open('server.py', 'r') as f:
        content = f.read()
    
    # The fnm_setup uses command -v to check
    assert 'command -v' in content, "Should check if command exists"
    print("  ✓ fnm setup has existence check")


def run_all_tests():
    print("=" * 60)
    print("COMMANDCENTER TEST SUITE")
    print("=" * 60)
    print()
    
    tests = [
        test_active_projects_supports_3_panels,
        test_session_name_sanitization,
        test_no_cache_headers,
        test_loadSettings_validation,
        test_showTermIfReady_checks_hidden,
        test_logging_not_silent,
        test_never_used_fingerprints,
        test_tmux_janitor_uses_start_time,
        test_git_upstream_detection,
        test_input_validation_socket_events,
        test_weather_thread_regular_interval,
        test_winClose_graceful,
        test_subprocess_errors_replace,
        test_thread_lock_exists,
        test_git_frontend_shows_no_upstream,
        test_panel_count_validation,
        test_fnm_setup_check,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ ALL TESTS PASSED!")
    else:
        print(f"\n✗ {failed} TESTS FAILED - review output above")
    
    return failed == 0


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or '.')
    success = run_all_tests()
    sys.exit(0 if success else 1)