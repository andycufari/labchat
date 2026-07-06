#!/usr/bin/env bash
# install-linux.sh — install labchat as a desktop app on Linux (KDE/GNOME).
# Puts the script + icon under ~/.local, and creates a .desktop launcher both
# in the app menu and on the Desktop. Ensures Tkinter is present.
#
#   ./install-linux.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SRC_DIR/labchat-lan.py"
ICON_SRC="$SRC_DIR/icon-256.png"

APP_HOME="$HOME/.local/share/labchat"
ICON_DIR="$HOME/.local/share/icons"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

[ -f "$SCRIPT" ] || { echo "missing $SCRIPT"; exit 1; }

# 1) Tkinter — required for the GUI.
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Installing python3-tk (needs sudo)…"
  sudo apt-get update -qq && sudo apt-get install -y python3-tk
fi

# 2) place code + icon
mkdir -p "$APP_HOME" "$ICON_DIR" "$APPS_DIR" "$DESKTOP_DIR"
cp "$SCRIPT" "$APP_HOME/labchat-lan.py"
chmod +x "$APP_HOME/labchat-lan.py"
[ -f "$ICON_SRC" ] && cp "$ICON_SRC" "$ICON_DIR/labchat.png"

# 3) the .desktop launcher
DESKTOP_FILE_CONTENT="[Desktop Entry]
Type=Application
Name=labchat
Comment=LAN chat with your other machine
Exec=python3 $APP_HOME/labchat-lan.py
Icon=$ICON_DIR/labchat.png
Terminal=false
Categories=Network;InstantMessaging;
StartupNotify=true"

echo "$DESKTOP_FILE_CONTENT" > "$APPS_DIR/labchat.desktop"
echo "$DESKTOP_FILE_CONTENT" > "$DESKTOP_DIR/labchat.desktop"
chmod +x "$APPS_DIR/labchat.desktop" "$DESKTOP_DIR/labchat.desktop"

# KDE (Plasma) requires the desktop file to be "trusted" to show the icon and
# run on click. gio marks it as trusted metadata; harmless on GNOME too.
gio set "$DESKTOP_DIR/labchat.desktop" "metadata::trusted" true 2>/dev/null || true
# refresh menu caches so it appears without a re-login
update-desktop-database "$APPS_DIR" 2>/dev/null || true
kbuildsycoca6 2>/dev/null || kbuildsycoca5 2>/dev/null || true

echo "✓ Installed. Look for 'labchat' on your Desktop and in the app menu."
echo "  On KDE, first click may ask to trust the launcher — allow it."
