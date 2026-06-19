#!/usr/bin/env bash
# labchatd.sh — box-side per-connection handler for labchat.
# socat runs ONE copy of this per incoming connection. It streams the shared
# wall to the peer (so they see history + live messages from anyone) and
# appends whatever the peer types back into the wall. Plain files + tail, no
# clever quoting.
WALL="$HOME/.labchat-wall"
touch "$WALL"
# Stream the tail of the wall to the peer in the background...
tail -n 20 -f "$WALL" &
TAILPID=$!
# ...and append the peer's input to the wall (so the tail echoes it to everyone).
# stdbuf keeps it line-buffered so messages appear immediately.
while IFS= read -r line; do
  printf '%s\n' "$line" >> "$WALL"
done
kill "$TAILPID" 2>/dev/null
