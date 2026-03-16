#!/bin/bash
# Install/refresh the Float Plan launchd agent for this checkout.
# Creates ~/Library/LaunchAgents/com.floatplan.plist pointing at start-service.sh,
# then unloads/loads it so the service starts automatically.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.floatplan.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$SCRIPT_DIR/data"

echo "Installing launchd agent for Float Plan..."
cat > "$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.floatplan</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_DIR}/start-service.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/data/service.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/data/service.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "Wrote: $PLIST_DEST"

echo "Reloading launchd job..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo
echo "Installed and loaded launch agent:"
echo "  $PLIST_DEST"
echo
echo "You can check status with:"
echo "  launchctl list | grep floatplan"
echo
