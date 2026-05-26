#!/usr/bin/env bash
# Install CommandCenter desktop shortcut and launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"
SYSTEMD_DIR="$HOME/.config/systemd/user"
LOG="/tmp/commandcenter.log"

echo "Installing CommandCenter..."

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$SYSTEMD_DIR"

# Create custom icon
cat > "$ICON_DIR/commandcenter.svg" << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="8" fill="#05080d"/>
  <path d="M36 8L16 36h14l-2 20 24-32H30z" fill="#00d9ff" stroke="#00d9ff" stroke-width="2"/>
</svg>
SVG

# Create systemd service
cat > "$SYSTEMD_DIR/commandcenter.service" << 'SYSTEMD'
[Unit]
Description=CommandCenter Server
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart=SCRIPT_DIR/.venv/bin/python SCRIPT_DIR/server.py
Restart=always
RestartSec=3
StandardOutput=append:/home/thjo/.claude/logs/commandcenter.log
StandardError=append:/home/thjo/.claude/logs/commandcenter.log
KillMode=mixed
TimeoutStopSec=10

[Install]
WantedBy=default.target
SYSTEMD

sed -i "s|SCRIPT_DIR|$SCRIPT_DIR|g" "$SYSTEMD_DIR/commandcenter.service"

# Create launcher script with proper health checking
cat > "$BIN_DIR/commandcenter" << 'LAUNCHER'
#!/usr/bin/env bash
# commandcenter launcher: ensures the server is up, then opens default browser.
set -e

PROJECT_DIR="PLACEHOLDER_PROJECT_DIR"
PORT="${CC_PORT:-5050}"
HEALTH_URL="http://localhost:${PORT}/api/health"
LOG="/tmp/commandcenter.log"
PID_FILE="/tmp/commandcenter.pid"

is_healthy() {
  response=$(curl -sf -m 2 "$HEALTH_URL" 2>/dev/null)
  [[ "$response" == *"\"ok\":true"* ]]
}

get_pid() {
  [[ -f "$PID_FILE" ]] && cat "$PID_FILE"
}

save_pid() {
  echo "$1" > "$PID_FILE"
}

is_running() {
  pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

kill_zombies() {
  for pid in $(pgrep -f "python.*server.py" 2>/dev/null || true); do
    if [[ "$pid" != "$$" ]]; then
      echo "Killing zombie server process $pid" >> "$LOG"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

start_server() {
  if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    echo "venv missing" >> "$LOG"
    exit 1
  fi

  kill_zombies
  rm -f "$PID_FILE"

  nohup env CC_PORT="$PORT" "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/server.py" >> "$LOG" 2>&1 &
  new_pid=$!
  disown
  save_pid "$new_pid"
  sleep 1
}

main() {
  if is_healthy; then
    cached_pid=$(get_pid)
    if is_running "$cached_pid"; then
      echo "Server already healthy (PID $cached_pid)"
    else
      echo "Server responding but wrong PID - restarting"
      kill_zombies
      start_server
    fi
  else
    echo "Server not healthy - starting fresh"
    kill_zombies
    start_server
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      sleep 0.5
      is_healthy && echo "Server healthy" && break
      echo "Waiting for server... ($i)"
    done
  fi

  xdg-open "http://localhost:$PORT/"
}

main "$@"
LAUNCHER

sed -i "s|PLACEHOLDER_PROJECT_DIR|$SCRIPT_DIR|g" "$BIN_DIR/commandcenter"
chmod +x "$BIN_DIR/commandcenter"

# Create desktop entry with custom icon
cat > "$APP_DIR/commandcenter.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=⚡ CommandCenter
GenericName=Agent Mission Control
Comment=Live multi-agent terminal dashboard
Exec=$BIN_DIR/commandcenter
Icon=$ICON_DIR/commandcenter.svg
Terminal=false
Categories=Development;Utility;
StartupNotify=true
StartupWMClass=CommandCenter
Keywords=claude;opencode;agents;terminal;dashboard;
DESKTOP

chmod +x "$APP_DIR/commandcenter.desktop"

# Enable linger for systemd service (allows user services to start at boot)
systemd-logind-linger on 2>/dev/null || loginctl enable-linger $USER 2>/dev/null || true

# Reload systemd and enable service
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable commandcenter 2>/dev/null || true

# Remove old shortcuts
rm -f "$HOME/Desktop/CommandCenter.desktop" 2>/dev/null || true
rm -f "$HOME/Desktop/commandcenter.desktop" 2>/dev/null || true

echo ""
echo "Installed successfully!"
echo "   Launcher: $BIN_DIR/commandcenter"
echo "   Desktop:  $APP_DIR/commandcenter.desktop"
echo "   Service:  $SYSTEMD_DIR/commandcenter.service (enabled for boot)"
echo ""
echo "To start the service:"
echo "   systemctl --user start commandcenter"
