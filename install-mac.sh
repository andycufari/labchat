#!/usr/bin/env bash
# install-mac.sh — build "labchat.app" and drop it on your Desktop (macOS).
# Double-click it like any app. It runs labchat-lan.py with the SYSTEM Python
# (/usr/bin/python3), which has Tkinter — Homebrew's python usually doesn't.
#
#   ./install-mac.sh            # builds ~/Desktop/labchat.app
#   ./install-mac.sh /Applications   # build somewhere else
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SRC_DIR/labchat-lan.py"
ICNS="$SRC_DIR/labchat.icns"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/labchat.app"

[ -f "$SCRIPT" ] || { echo "missing $SCRIPT"; exit 1; }

echo "Building $APP …"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# copy the app code INTO the bundle so the app is self-contained
cp "$SCRIPT" "$APP/Contents/Resources/labchat-lan.py"
[ -f "$ICNS" ] && cp "$ICNS" "$APP/Contents/Resources/labchat.icns"

# launcher: pick a Python whose Tk can ACTUALLY open a window on this macOS.
#
# Gotcha (macOS 26 Tahoe): Apple's bundled Tk 8.5 (used by every /usr/bin and
# CommandLineTools/Xcode python3) has a version-check bug — it reads macOS "26"
# as "16" and abort()s with "macOS 26 (2602) or later required". The fix is a
# modern Tk: `brew install python-tk@3.14` pulls tcl-tk 9 which works. So we
# probe each candidate by actually creating+destroying a Tk() and use the first
# that survives.
cat > "$APP/Contents/MacOS/labchat" <<'LAUNCH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
SCRIPT="$DIR/labchat-lan.py"

# preference order: Homebrew pythons (modern Tk 9) first, Apple's last.
CANDIDATES=(
  /opt/homebrew/bin/python3.14
  /opt/homebrew/bin/python3.13
  /opt/homebrew/bin/python3.12
  /opt/homebrew/bin/python3
  /usr/local/bin/python3
  /Library/Developer/CommandLineTools/usr/bin/python3
  /usr/bin/python3
)
for py in "${CANDIDATES[@]}"; do
  [ -x "$py" ] || continue
  # a candidate qualifies only if it can create a real Tk window right now.
  if "$py" - <<'PROBE' >/dev/null 2>&1
import tkinter
r = tkinter.Tk(); r.withdraw(); r.update(); r.destroy()
PROBE
  then exec "$py" "$SCRIPT"; fi
done

# none worked — tell the user in a dialog they can actually see.
osascript -e 'display dialog "labchat could not find a Python with a working Tk on this macOS.\n\nFix: open Terminal and run\n    brew install python-tk@3.14\nthen relaunch labchat." buttons {"OK"} with title "labchat"'
exit 1
LAUNCH
chmod +x "$APP/Contents/MacOS/labchat"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>labchat</string>
  <key>CFBundleDisplayName</key><string>labchat</string>
  <key>CFBundleIdentifier</key><string>studio.cm64.labchat</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>labchat</string>
  <key>CFBundleIconFile</key><string>labchat.icns</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
PLIST

# nudge Finder/LaunchServices to pick up the icon
touch "$APP"
echo "✓ Built $APP"
echo "  Double-click it on your Desktop. First launch: right-click → Open"
echo "  (to get past Gatekeeper on an unsigned app)."
