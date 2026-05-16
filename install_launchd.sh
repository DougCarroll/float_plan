#!/bin/bash
# Install/refresh the Float Plan launchd agent for this checkout.
# Creates ~/Library/LaunchAgents/com.svburnttoast.floatplan.plist pointing at start-service.sh,
# then bootstraps it so the service starts automatically.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.svburnttoast.floatplan"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$SCRIPT_DIR/data"

echo "Installing launchd agent for Float Plan (${LABEL})..."

launchctl bootout "gui/${UID_NUM}" "$HOME/Library/LaunchAgents/com.floatplan.plist" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}/com.floatplan" 2>/dev/null || true

cat > "$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
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
echo
echo "Required: $SCRIPT_DIR/.env must define SECRET_KEY=... (start-service.sh runs in production)."
echo "  echo \"SECRET_KEY=\$(python3 -c 'import secrets; print(secrets.token_hex(32))')\" >> .env"
echo

echo "Reloading launchd job..."
launchctl bootout "gui/${UID_NUM}" "$PLIST_DEST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DEST"

echo
echo "Installed and loaded launch agent:"
echo "  $PLIST_DEST"
echo
echo "You can check status with:"
echo "  launchctl list | grep svburnttoast.floatplan"
echo
echo "Restart:"
echo "  launchctl kickstart -k \"gui/\$(id -u)/${LABEL}\""
echo
