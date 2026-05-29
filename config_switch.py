#!/usr/bin/env python3
"""Switches between Claude config profiles: bedrock vs subscription."""
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path.home() / ".claude"
SETTINGS = BASE / "settings.json"
BACKUPS = {
    "bedrock": BASE / "settings.bedrock-backup.json",
    "subscription": BASE / "settings.anthropic-backup.json",
}

def get_current():
    try:
        with open(SETTINGS) as f:
            data = json.load(f)
        env = data.get("env", {})
        if env.get("CLAUDE_CODE_USE_BEDROCK") == "1":
            return "bedrock"
        return "subscription"
    except Exception:
        return "unknown"

def switch_to(profile):
    if profile not in BACKUPS:
        return f"Unknown profile: {profile}"
    backup = BACKUPS[profile]
    if not backup.exists():
        return f"Backup not found: {backup}"
    # Backup current settings first
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    current_backup = SETTINGS.with_name(f"settings.json.bak-{timestamp}")
    shutil.copy2(SETTINGS, current_backup)
    # Switch to new profile
    shutil.copy2(backup, SETTINGS)
    return "ok"

def main():
    if len(sys.argv) < 2:
        print(get_current())
    elif sys.argv[1] == "get":
        print(get_current())
    elif sys.argv[1] == "switch":
        if len(sys.argv) < 3:
            print("Usage: config_switch.py switch <bedrock|subscription>")
            sys.exit(1)
        result = switch_to(sys.argv[2])
        if result == "ok":
            print(f"Switched to {sys.argv[2]}")
        else:
            print(f"Error: {result}")
            sys.exit(1)
    else:
        print(f"Unknown command: {sys.argv[1]}")
        sys.exit(1)

if __name__ == "__main__":
    main()