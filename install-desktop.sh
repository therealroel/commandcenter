#!/usr/bin/env bash
# Install CommandCenter desktop shortcut and launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

echo "Installing CommandCenter..."

# Create directories
mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

# Create launcher script
cat > "$BIN_DIR/commandcenter" << 'LAUNCHER'
#!/usr/bin/env bash
# commandcenter launcher: ensures the server is up, then opens Chrome in app mode.
set -e

PROJECT_DIR="PLACEHOLDER_PROJECT_DIR"
PORT="${CC_PORT:-5050}"
URL="http://localhost:${PORT}/"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
SERVER_PY="$PROJECT_DIR/server.py"
LOG="/tmp/commandcenter.log"

is_up() {
  curl -sf -o /dev/null -m 1 "$URL"
}

start_server() {
  if [[ ! -x "$VENV_PY" ]]; then
    echo "venv missing at $VENV_PY" >> "$LOG"
    exit 1
  fi
  cd "$PROJECT_DIR"
  nohup env CC_PORT="$PORT" "$VENV_PY" "$SERVER_PY" >> "$LOG" 2>&1 &
  disown
}

if ! is_up; then
  start_server
  # wait up to 10s for it to come up
  for i in {1..40}; do
    sleep 0.25
    is_up && break
  done
fi

# --app gives a chromeless PWA-style window (no tabs, no URL bar).
# --start-maximized makes it cover the full screen but stay a normal
# window you can drag between monitors. A dedicated profile dir keeps
# its state isolated from your daily Chrome session.
exec google-chrome \
  --app="$URL" \
  --start-maximized \
  --user-data-dir="$HOME/.config/commandcenter-chrome" \
  --class=CommandCenter \
  --name=CommandCenter \
  >> "$LOG" 2>&1
LAUNCHER

# Replace placeholder with actual path
sed -i "s|PLACEHOLDER_PROJECT_DIR|$SCRIPT_DIR|g" "$BIN_DIR/commandcenter"
chmod +x "$BIN_DIR/commandcenter"

# Create desktop entry
cat > "$APP_DIR/commandcenter.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=CommandCenter
GenericName=Agent Mission Control
Comment=Live multi-agent terminal dashboard
Exec=$BIN_DIR/commandcenter
Icon=utilities-terminal
Terminal=false
Categories=Development;Utility;
StartupNotify=true
StartupWMClass=CommandCenter
Keywords=claude;opencode;agents;terminal;dashboard;
DESKTOP

chmod +x "$APP_DIR/commandcenter.desktop"

echo ""
echo "✅ Installed successfully!"
echo ""
echo "   Launcher: $BIN_DIR/commandcenter"
echo "   Desktop:  $APP_DIR/commandcenter.desktop"
echo ""
echo "You can now:"
echo "  - Run 'commandcenter' from terminal"
echo "  - Find 'CommandCenter' in your app launcher"
echo ""
echo "Make sure ~/.local/bin is in your PATH:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
