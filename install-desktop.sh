#!/usr/bin/env bash
# Install CommandCenter desktop shortcut and launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

echo "Installing CommandCenter..."

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

# Create custom icon
cat > "$ICON_DIR/commandcenter.svg" << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="8" fill="#05080d"/>
  <path d="M36 8L16 36h14l-2 20 24-32H30z" fill="#00d9ff" stroke="#00d9ff" stroke-width="2"/>
</svg>
SVG

# Create launcher script
cat > "$BIN_DIR/commandcenter" << 'LAUNCHER'
#!/usr/bin/env bash
# commandcenter launcher: ensures the server is up, then opens default browser.
set -e

PROJECT_DIR="PLACEHOLDER_PROJECT_DIR"
PORT="${CC_PORT:-5050}"
URL="http://localhost:${PORT}/"
LOG="/tmp/commandcenter.log"

is_up() {
  curl -sf -o /dev/null -m 1 "$URL"
}

start_server() {
  if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    echo "venv missing" >> "$LOG"
    exit 1
  fi
  nohup env CC_PORT="$PORT" "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/server.py" >> "$LOG" 2>&1 &
  disown
  sleep 0.5
}

if ! is_up; then
  start_server
  for i in {1..40}; do
    sleep 0.25
    is_up && break
  done
fi

xdg-open "http://localhost:$PORT/"
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

# Remove old shortcuts
rm -f "$HOME/Desktop/CommandCenter.desktop" 2>/dev/null || true
rm -f "$HOME/Desktop/commandcenter.desktop" 2>/dev/null || true

echo ""
echo "Installed successfully!"
echo "   Launcher: $BIN_DIR/commandcenter"
echo "   Desktop:  $APP_DIR/commandcenter.desktop"