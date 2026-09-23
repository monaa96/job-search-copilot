#!/bin/bash
# Schedules the job scan to run every day on macOS, using launchd.
#
#   ./schedule_daily_scan.sh           # run daily at 8:00
#   ./schedule_daily_scan.sh 7 30      # run daily at 7:30
#   ./schedule_daily_scan.sh remove    # stop the daily scan
#
# If the Mac is asleep at the scheduled time, the scan runs when it wakes.
# Output is logged to data/scan.log.

set -euo pipefail

LABEL="com.jobsearchcopilot.dailyscan"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT="$(cd "$(dirname "$0")" && pwd)"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "remove" ]; then
  rm -f "$PLIST"
  echo "Daily scan removed."
  exit 0
fi

HOUR="${1:-8}"
MINUTE="${2:-0}"
mkdir -p "$PROJECT/data" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT/.venv/bin/python</string>
    <string>$PROJECT/scout.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key><string>$PROJECT/data/scan.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/scan.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"
printf "Daily scan scheduled for %d:%02d. Log: %s\n" "$HOUR" "$MINUTE" "$PROJECT/data/scan.log"
