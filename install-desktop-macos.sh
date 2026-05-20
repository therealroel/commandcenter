#!/usr/bin/env bash
# Install CommandCenter as a macOS app (Chrome in app mode)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="CommandCenter"
APP_DIR="$HOME/Applications"
APP_PATH="$APP_DIR/$APP_NAME.app"

echo "Installing CommandCenter for macOS..."

# Create Applications folder if needed
mkdir -p "$APP_DIR"

# Create app bundle structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Create launcher script
cat > "$APP_PATH/Contents/MacOS/commandcenter" << LAUNCHER
#!/usr/bin/env bash
# CommandCenter launcher for macOS
set -e

PROJECT_DIR="$SCRIPT_DIR"
PORT="\${CC_PORT:-5050}"
URL="http://localhost:\${PORT}/"
VENV_PY="\$PROJECT_DIR/.venv/bin/python"
SERVER_PY="\$PROJECT_DIR/server.py"
LOG="/tmp/commandcenter.log"

is_up() {
  curl -sf -o /dev/null -m 1 "\$URL"
}

start_server() {
  if [[ ! -x "\$VENV_PY" ]]; then
    echo "venv missing at \$VENV_PY" >> "\$LOG"
    exit 1
  fi
  cd "\$PROJECT_DIR"
  nohup env CC_PORT="\$PORT" "\$VENV_PY" "\$SERVER_PY" >> "\$LOG" 2>&1 &
  disown
}

if ! is_up; then
  start_server
  for i in {1..40}; do
    sleep 0.25
    is_up && break
  done
fi

# Try Chrome, then Chromium, then fallback to open
if [[ -d "/Applications/Google Chrome.app" ]]; then
  open -na "Google Chrome" --args --app="\$URL" --user-data-dir="\$HOME/.config/commandcenter-chrome"
elif [[ -d "/Applications/Chromium.app" ]]; then
  open -na "Chromium" --args --app="\$URL" --user-data-dir="\$HOME/.config/commandcenter-chrome"
else
  open "\$URL"
fi
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/commandcenter"

# Create Info.plist
cat > "$APP_PATH/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>commandcenter</string>
    <key>CFBundleIdentifier</key>
    <string>com.commandcenter.app</string>
    <key>CFBundleName</key>
    <string>CommandCenter</string>
    <key>CFBundleDisplayName</key>
    <string>CommandCenter</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

echo ""
echo "✅ Installed successfully!"
echo ""
echo "   App: $APP_PATH"
echo ""
echo "You can now:"
echo "  - Double-click CommandCenter in ~/Applications"
echo "  - Or run: open '$APP_PATH'"
echo "  - Add to Dock by dragging from ~/Applications"
echo ""
