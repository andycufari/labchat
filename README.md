# labchat

> A tiny desktop chat + file transfer between two of your own machines on the
> same LAN — e.g. your Mac and your Kubuntu PC. No cloud, no accounts, no
> daemon to babysit. Run the same app on both, point each at the other's LAN
> IP, and only IPs on your allowlist can connect.

You've got two computers on your desk (or your house). You want to fire a line
of text or a file from one to the other without email, AirDrop-that-won't-see-
Linux, or a USB stick. `labchat` is a small Python desktop window that does
exactly that: **text both ways, files both ways, trusted IPs only.**

It's a single file (`labchat-lan.py`) built on the Python standard library —
nothing to `pip install`.

## What it looks like

```
┌─ labchat-lan · mac · ● listening ──────────────┐
│ · listening on :8765 — trusted: 192.168.1.42   │
│ [mac] deploy done?                             │
│ [kubuntu] yep, restarting now                  │
│ [kubuntu] 📎 received: ~/Downloads/labchat/…    │
│                                                │
│ ┌────────────────────────┐ [Send] [📎 File] [⚙]│
│ └────────────────────────┘                     │
└────────────────────────────────────────────────┘
```

## Requirements

- **Python 3** (already on macOS and Kubuntu).
- **Tkinter** — ships with Python, but is a separate package on some systems:
  - **macOS:** use the *system* Python at `/usr/bin/python3` (Homebrew's
    Python often lacks Tk). Homebrew users can also `brew install python-tk`.
  - **Kubuntu / Debian / Ubuntu:** `sudo apt install python3-tk`
- Both machines on the **same LAN**, reachable by IP.

No `pip`, no third-party libraries.

## Install

Just copy `labchat-lan.py` to **both** machines. That's it.

```sh
git clone git@github.com:andycufari/labchat.git
```

Optional — put it on your PATH so you can launch it from anywhere:

```sh
# macOS (system Python has Tk):
echo '#!/bin/sh\nexec /usr/bin/python3 /path/to/labchat/labchat-lan.py "$@"' \
  | sudo tee /usr/local/bin/labchat >/dev/null && sudo chmod +x /usr/local/bin/labchat

# Kubuntu/Linux:
echo '#!/bin/sh\nexec python3 /path/to/labchat/labchat-lan.py "$@"' \
  | sudo tee /usr/local/bin/labchat >/dev/null && sudo chmod +x /usr/local/bin/labchat
```

## Usage

1. **Find each machine's LAN IP:**
   - macOS: `ipconfig getifaddr en0`  (or `en1` on Wi-Fi)
   - Linux: `hostname -I`

2. **Launch on both machines:**
   ```sh
   # macOS:
   /usr/bin/python3 labchat-lan.py
   # Kubuntu:
   python3 labchat-lan.py
   ```

3. **First run — click ⚙ Settings on each machine and fill in:**
   - **Your name** — the tag on your outgoing lines (e.g. `mac`, `kubuntu`).
   - **Peer IP** — the *other* machine's LAN IP.
   - **Allowlist** — add the *other* machine's IP so it's allowed to connect
     in. (`127.0.0.1` is always trusted, for testing against yourself.)

   Save on both. Restart the app once so it binds the listen port.

4. **Chat.** Type + Enter (or **Send**) to send a line. Click **📎 File** to
   send a file. Received files land in `~/Downloads/labchat/` (override with
   `LABCHAT_DOWNLOADS`).

### Example setup

| | Mac (192.168.1.10) | Kubuntu (192.168.1.42) |
|---|---|---|
| Your name | `mac` | `kubuntu` |
| Peer IP | `192.168.1.42` | `192.168.1.10` |
| Allowlist | `192.168.1.42` | `192.168.1.10` |

Both listen on `:8765` by default.

## How it works

```
Mac                                  Kubuntu
───                                  ───────
labchat-lan.py                       labchat-lan.py
  ├─ listener  :8765  ◄──TCP (LAN)──   dials peer 192.168.1.10:8765
  │   accepts ONLY allowlisted IPs
  └─ dials peer 192.168.1.42:8765 ──►  listener :8765 (allowlist checked)
```

- Each app runs a **listener thread** on its port and **dials the peer** when
  you send. Fully symmetric — either side can start a message or a file.
- One **JSON object per line** over TCP is the whole protocol. Text and files
  share the same channel; a file rides as base64 with a SHA-256 checksum, so a
  truncated or corrupt transfer is dropped rather than written.
- **Every inbound connection's source IP is checked against your allowlist**
  before a single byte is read. Anything not on the list is refused and logged.

## Configuration

Stored in `~/.labchat-lan.json` (edit in-app via ⚙, or by hand):

```json
{
  "name": "mac",
  "listen_port": 8765,
  "peer_host": "192.168.1.42",
  "peer_port": 8765,
  "allowlist": ["127.0.0.1", "192.168.1.42"]
}
```

| Field | Meaning |
|-------|---------|
| `name` | tag prefixed to your outgoing lines |
| `listen_port` | port this machine listens on |
| `peer_host` / `peer_port` | the other machine's LAN IP + port |
| `allowlist` | inbound IPs allowed to connect (`127.0.0.1` always trusted) |

Env: `LABCHAT_DOWNLOADS` overrides where received files are saved.

## Notes & caveats

- **Trust model:** the allowlist is your gate. Only put IPs you control on it.
  Traffic on the LAN is **not encrypted** — this is for your own machines on
  your own network, not for sending secrets across an untrusted network. If you
  need encryption between two boxes, use the ssh-tunnel variant below.
- **Firewall:** on first run macOS may ask to allow incoming connections for
  Python — say yes. On Linux, if it can't connect, check `ufw`/firewalld.
- **File size:** capped at 200 MB per file (it's base64-in-memory; fine for the
  files you hand-move, not a bulk sync tool). Files never overwrite — a repeat
  name becomes `x (1).ext`.
- **Static IPs help:** if your router hands out new IPs, update Peer IP +
  allowlist, or reserve a DHCP lease per machine.

## The ssh-tunnel variant (original labchat)

The repo also ships the original **terminal, ssh-tunnel** version — `labchat`
(bash) + `labchatd.sh`. Use that when the two machines are *not* peers on a
trusted LAN but boxes you `ssh` into, and you want the chat encrypted over the
ssh connection with nothing exposed on the network. It's text-only. See the
header comments in `labchat` for its usage (`labchat`, `labchat here`,
`labchat say "…"`, `labchat tail`).

Rule of thumb:
- **Two of your own machines on your LAN, want a window + files** → `labchat-lan.py`.
- **A remote server you ssh into, want text over the encrypted tunnel** → `labchat`.

## License

MIT
