#!/usr/bin/env python3
# labchat-lan — a tiny LAN desktop chat between two of your own machines
# (e.g. your Mac and your Kubuntu PC). No ssh, no cloud, no daemon to babysit.
# Run the same app on both, tell each the other's LAN IP, and only trusted IPs
# on your list can connect.
#
#   Live text both ways · IP allowlist · pure Python stdlib.
#
# FILES: labchat does NOT transfer files itself — it hands them to MichiBox, a
# Syncthing folder that already syncs both machines. The 📎 button copies the
# file into ~/Desktop/MichiBox and it appears on the other side on its own.
#
# Run it:
#   python3 labchat-lan.py
#
# Needs Tkinter (stdlib, but a separate package on some systems):
#   • macOS:  use the system Python — /usr/bin/python3 (Homebrew python often
#             lacks Tk). Run:  /usr/bin/python3 labchat-lan.py
#   • Kubuntu/Debian:  sudo apt install python3-tk
#
# Config lives in ~/.labchat-lan.json (name, listen port, peer IP, allowlist).
# You can edit it in the app under "Settings".

import json
import os
import queue
import socket
import threading
from pathlib import Path

APP_NAME = "labchat-lan"
CONFIG_PATH = Path.home() / ".labchat-lan.json"
DEFAULT_PORT = 8765
RECV_TIMEOUT = 30.0                 # seconds a stalled peer socket may block


def find_michibox():
    """Locate the MichiBox Syncthing folder (env override wins). Returns a Path
    even if it doesn't exist yet, so the UI can point at where it should be."""
    env = os.environ.get("LABCHAT_MICHIBOX")
    if env:
        return Path(env).expanduser()
    for cand in (Path.home() / "Desktop" / "MichiBox",
                 Path.home() / "MichiBox"):
        if cand.exists():
            return cand
    return Path.home() / "Desktop" / "MichiBox"  # default location


MICHIBOX_DIR = find_michibox()


# ── config ──────────────────────────────────────────────────────────────────
def default_config():
    return {
        "name": socket.gethostname().split(".")[0] or "me",
        "listen_port": DEFAULT_PORT,
        "peer_host": "",          # the OTHER machine's LAN IP, e.g. 192.168.1.42
        "peer_port": DEFAULT_PORT,
        # Only inbound connections from these IPs are accepted. "127.0.0.1" is
        # always allowed so you can test against yourself.
        "allowlist": ["127.0.0.1"],
    }


def load_config():
    cfg = default_config()
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except (ValueError, OSError):
            pass  # corrupt/unreadable → fall back to defaults, don't crash
    # 127.0.0.1 is always trusted (self-test); dedupe while preserving order.
    allow = cfg.get("allowlist") or []
    if "127.0.0.1" not in allow:
        allow = ["127.0.0.1", *allow]
    cfg["allowlist"] = list(dict.fromkeys(allow))
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ── wire protocol ───────────────────────────────────────────────────────────
# One JSON object per line ('\n'-terminated). Only one kind:
#   {"t":"msg", "from":"mac", "text":"hi"}
# Line framing keeps it dead simple. Files don't ride this channel — they go
# through the MichiBox synced folder instead.
def encode(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


def read_lines(sock):
    """Yield decoded JSON objects from a socket, one per newline."""
    buf = b""
    sock.settimeout(RECV_TIMEOUT)
    while True:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue  # skip a garbled line rather than kill the connection


# ── network core (GUI-agnostic) ─────────────────────────────────────────────
class Net:
    """Owns the listener + outbound sends. Pushes events onto self.events
    (a Queue) for the GUI to drain: ('msg', who, text), ('sys', text),
    ('status', bool_listening)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.events = queue.Queue()
        self._server = None
        self._stop = threading.Event()

    # -- inbound ------------------------------------------------------------
    def start_listener(self):
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", int(self.cfg["listen_port"])))
            srv.listen(8)
            srv.settimeout(1.0)
            self._server = srv
        except OSError as e:
            self.events.put(("sys", f"⚠ cannot listen on port "
                                     f"{self.cfg['listen_port']}: {e}"))
            self.events.put(("status", False))
            return
        self.events.put(("status", True))
        self.events.put(("sys", f"listening on :{self.cfg['listen_port']} — "
                                f"trusted: {', '.join(self.cfg['allowlist'])}"))
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            peer_ip = addr[0]
            if peer_ip not in self.cfg["allowlist"]:
                self.events.put(("sys", f"⛔ refused connection from {peer_ip} "
                                        f"(not on allowlist)"))
                conn.close()
                continue
            threading.Thread(target=self._serve_conn, args=(conn, peer_ip),
                             daemon=True).start()
        srv.close()

    def _serve_conn(self, conn, peer_ip):
        try:
            for obj in read_lines(conn):
                self._handle(obj, peer_ip)
        finally:
            conn.close()

    def _handle(self, obj, peer_ip):
        who = obj.get("from") or peer_ip
        if obj.get("t") == "msg":
            self.events.put(("msg", who, str(obj.get("text", ""))))

    # -- outbound -----------------------------------------------------------
    def _dial(self):
        host = self.cfg.get("peer_host", "").strip()
        if not host:
            raise OSError("no peer IP set — open Settings and add the other "
                          "machine's LAN IP")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(8.0)
        s.connect((host, int(self.cfg.get("peer_port", DEFAULT_PORT))))
        return s

    def send_text(self, text):
        obj = {"t": "msg", "from": self.cfg["name"], "text": text}
        try:
            s = self._dial()
        except OSError as e:
            self.events.put(("sys", f"⚠ can't reach peer: {e}"))
            return
        try:
            s.sendall(encode(obj))
        except OSError as e:
            self.events.put(("sys", f"⚠ send failed: {e}"))
        finally:
            s.close()

    def share_file(self, path):
        """Files don't ride the socket — copy them into MichiBox and let
        Syncthing carry them to the other machine. Also tell the peer over
        chat so they see it arriving."""
        src = Path(path)
        if not MICHIBOX_DIR.exists():
            self.events.put(("sys", f"⚠ MichiBox folder not found at "
                                    f"{MICHIBOX_DIR} — is Syncthing set up? "
                                    f"(override with LABCHAT_MICHIBOX)"))
            return
        try:
            import shutil
            dest = _unique_path(MICHIBOX_DIR / src.name)
            shutil.copy2(src, dest)
        except OSError as e:
            self.events.put(("sys", f"⚠ couldn't copy into MichiBox: {e}"))
            return
        size_kb = dest.stat().st_size // 1024 or 1
        self.events.put(("sys", f"📎 copied {dest.name} into MichiBox "
                                f"({size_kb} KB) — Syncthing will carry it over"))
        # let the other side know it's coming
        threading.Thread(
            target=self.send_text,
            args=(f"📎 shared '{dest.name}' via MichiBox "
                  f"({size_kb} KB) — check your MichiBox folder",),
            daemon=True).start()

    def stop(self):
        self._stop.set()


def _unique_path(path):
    """Never overwrite: x.png → x (1).png → x (2).png ..."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


# ── GUI ─────────────────────────────────────────────────────────────────────
# A simple, readable chat: dark window, message bubbles (you = green on the
# right, them = blue on the left), a focused input box, timestamps. Pure Tk, no
# deps. The layout uses a Text widget with per-message tags rather than a
# canvas — it's the simplest thing that gives a real "chat" look and scrolls.

# palette — hacker terminal: black bg, cyan accent, phosphor-ish text
BG      = "#05080a"   # near-black terminal background
BUBBLE_ME   = "#04343d"   # your bubble (dark teal, cyan-tinted)
BUBBLE_THEM = "#12181d"   # peer bubble (charcoal)
FG      = "#c8f2ee"   # soft cyan-white text
MUTED   = "#4d6068"   # dim slate for meta/timestamps
ACCENT  = "#22d3ee"   # bright cyan (prompt, send, status)
ME_FG   = "#7dffe6"   # your text (bright aqua)
THEM_FG = "#8fe3ff"   # peer text (light cyan-blue)


def _pick_mono(root):
    """Pick the nicest monospace font actually installed. Falls back cleanly."""
    import tkinter.font as tkfont
    have = set(tkfont.families(root))
    for name in ("JetBrains Mono", "Fira Code", "Hack", "Cascadia Code",
                 "Menlo", "DejaVu Sans Mono", "Ubuntu Mono", "Consolas",
                 "Monaco", "Courier New"):
        if name in have:
            return name
    return "TkFixedFont"


def run_gui():
    import tkinter as tk
    from tkinter import filedialog

    cfg = load_config()
    net = Net(cfg)

    root = tk.Tk()
    root.title(f"labchat · {cfg['name']}")
    root.geometry("640x620")
    root.minsize(420, 380)
    root.configure(bg=BG)

    MONO = _pick_mono(root)
    F_MSG  = (MONO, 11)
    F_META = (MONO, 9)
    F_UI   = (MONO, 10)
    F_UI_B = (MONO, 10, "bold")
    F_ART  = (MONO, 8)

    # ── header: a terminal title bar ──────────────────────────────────────
    header = tk.Frame(root, bg="#0a1013", height=42)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)
    tk.Label(header, text="  ▚ labchat", bg="#0a1013", fg=ACCENT,
             font=(MONO, 12, "bold"), anchor="w").pack(side="left", fill="y")
    status_lbl = tk.Label(header, text="○ offline", bg="#0a1013", fg=MUTED,
                          font=(MONO, 10))
    status_lbl.pack(side="right", padx=(0, 12))
    cfg_lbl = tk.Label(header, text="[cfg]", bg="#0a1013", fg=MUTED,
                       font=(MONO, 10), cursor="hand2")
    cfg_lbl.pack(side="right", padx=6)
    cfg_lbl.bind("<Button-1>",
                 lambda e: _settings_dialog(root, cfg, net, sysline))
    cfg_lbl.bind("<Enter>", lambda e: cfg_lbl.configure(fg=ACCENT))
    cfg_lbl.bind("<Leave>", lambda e: cfg_lbl.configure(fg=MUTED))

    # ── transcript (terminal log) ─────────────────────────────────────────
    # Kept in "normal" state so text is selectable/copyable (a "disabled" Text
    # blocks selection+copy on macOS). We make it read-only by swallowing key
    # input but explicitly allowing copy shortcuts + the arrows/scroll.
    wrap = tk.Frame(root, bg=BG)
    view = tk.Text(wrap, wrap="word", bg=BG, fg=FG,
                   bd=0, padx=14, pady=10, font=F_MSG, cursor="xterm",
                   spacing1=1, spacing3=3, highlightthickness=0, insertwidth=0,
                   selectbackground="#0e3a42", selectforeground="#eafffb")
    scroll = tk.Scrollbar(wrap, command=view.yview, width=10)
    view.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    view.pack(side="left", fill="both", expand=True)

    def _copy(_e=None):
        try:
            sel = view.get("sel.first", "sel.last")
            if sel:
                root.clipboard_clear(); root.clipboard_append(sel)
        except tk.TclError:
            pass
        return "break"

    def _read_only(e):
        # allow copy (Cmd/Ctrl+C or +A), navigation, and modifier chords;
        # block everything else so the log can't be edited.
        if (e.state & 0x8) or (e.state & 0x4):   # Cmd (mac) / Ctrl
            return None
        if e.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                        "Home", "End", "Shift_L", "Shift_R"):
            return None
        return "break"
    view.bind("<Key>", _read_only)
    view.bind("<Command-c>", _copy)
    view.bind("<Control-c>", _copy)
    # right-click → Copy
    menu = tk.Menu(view, tearoff=0)
    menu.add_command(label="Copy", command=_copy)
    view.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
    view.bind("<Button-2>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    # terminal tags: a colored "who>" prompt then the message text.
    view.tag_config("me_prompt",   foreground=ACCENT,  font=(MONO, 11, "bold"))
    view.tag_config("them_prompt", foreground="#ffb347", font=(MONO, 11, "bold"))
    view.tag_config("me_text",   foreground=ME_FG)
    view.tag_config("them_text", foreground=THEM_FG)
    view.tag_config("meta", foreground=MUTED, font=F_META)
    view.tag_config("sys",  foreground=MUTED, font=F_META, spacing1=2)
    view.tag_config("art",  foreground=ACCENT, font=F_ART, spacing1=0, spacing3=0)
    view.tag_config("art2", foreground="#0e7d8c", font=F_ART, spacing1=0, spacing3=0)

    def _clock():
        import time as _t
        return _t.strftime("%H:%M:%S")

    # view stays in "normal" state (for copy) — inserts just append + scroll.
    def add_msg(who, text, mine):
        view.insert("end", f"[{_clock()}] ", "meta")
        view.insert("end", f"{who}> ", "me_prompt" if mine else "them_prompt")
        view.insert("end", f"{text}\n", "me_text" if mine else "them_text")
        view.see("end")

    def sysline(text):
        view.insert("end", f"  · {text}\n", "sys")
        view.see("end")

    def banner():
        art = r"""
   __      __   __      __   __  ___
  |  |    /  \ |  |    /  \ |  |/ __|
  |  |__ |  ()||  |__ |  ()||  ||(__     l a b c h a t
  |_____| \__/ |_____| \__/ |__| \___|   lan · e2e · no cloud
"""
        for i, ln in enumerate(art.strip("\n").splitlines()):
            view.insert("end", ln + "\n", "art" if i < 3 else "art2")
        view.insert("end", "\n", ())

    # ── input bar: a bare terminal prompt line ────────────────────────────
    # Same black as the chat, no borders/background. Packed to bottom BEFORE
    # the transcript so it always reserves its height (an expand=True transcript
    # packed first can starve it to zero — that was the "no input box" bug).
    # NOTE: tk.Button renders as a chromed native pill on macOS (the "white
    # borders"), so the buttons here are Labels wired to click — zero chrome.
    bar = tk.Frame(root, bg=BG)
    bar.pack(fill="x", side="bottom")
    inner = tk.Frame(bar, bg=BG)
    inner.pack(fill="x", padx=14, pady=(4, 10))

    tk.Label(inner, text="❯", bg=BG, fg=ACCENT,
             font=(MONO, 12, "bold")).pack(side="left", padx=(0, 8))

    entry = tk.Entry(inner, font=(MONO, 12), bg=BG, fg=ME_FG,
                     insertbackground=ACCENT, insertwidth=2, relief="flat",
                     highlightthickness=0, bd=0)
    entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 10))

    def _click(lbl, fn):
        lbl.bind("<Button-1>", lambda e: fn())
        lbl.bind("<Enter>", lambda e: lbl.configure(fg="#67e8f9"))
        lbl.bind("<Leave>", lambda e: lbl.configure(fg=lbl._rest))
        lbl.configure(cursor="hand2")
        return lbl

    file_lbl = tk.Label(inner, text="[+file]", bg=BG, fg=MUTED, font=F_UI)
    file_lbl._rest = MUTED
    _click(file_lbl, lambda: do_share_file()).pack(side="left", padx=(0, 10))
    send_lbl = tk.Label(inner, text="[send]", bg=BG, fg=ACCENT, font=F_UI_B)
    send_lbl._rest = ACCENT
    _click(send_lbl, lambda: do_send()).pack(side="left")

    # full clipboard support in the entry (macOS Cmd + Linux Ctrl)
    def _entry_copy(_e=None):
        try:
            if entry.selection_present():
                root.clipboard_clear()
                root.clipboard_append(entry.selection_get())
        except tk.TclError:
            pass
        return "break"

    def _entry_paste(_e=None):
        try:
            entry.insert("insert", root.clipboard_get())
        except tk.TclError:
            pass
        return "break"

    def _entry_cut(_e=None):
        _entry_copy()
        try:
            if entry.selection_present():
                entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    for seq in ("<Command-c>", "<Control-c>"):
        entry.bind(seq, _entry_copy)
    for seq in ("<Command-v>", "<Control-v>"):
        entry.bind(seq, _entry_paste)
    for seq in ("<Command-x>", "<Control-x>"):
        entry.bind(seq, _entry_cut)
    for seq in ("<Command-a>", "<Control-a>"):
        entry.bind(seq, lambda e: (entry.select_range(0, "end"),
                                   entry.icursor("end"), "break")[-1])

    # now that the bottom bar exists, let the transcript fill the rest.
    wrap.pack(fill="both", expand=True)

    def do_send(_evt=None):
        text = entry.get().strip()
        if not text:
            return
        entry.delete(0, "end")
        add_msg(cfg["name"], text, mine=True)
        threading.Thread(target=net.send_text, args=(text,),
                         daemon=True).start()

    def do_share_file():
        path = filedialog.askopenfilename(title="Share a file via MichiBox")
        if not path:
            return
        add_msg(cfg["name"], f"[+file] {os.path.basename(path)} → MichiBox",
                mine=True)
        threading.Thread(target=net.share_file, args=(path,),
                         daemon=True).start()

    entry.bind("<Return>", do_send)

    # ── network pump ──────────────────────────────────────────────────────
    def pump():
        try:
            while True:
                kind, *rest = net.events.get_nowait()
                if kind == "msg":
                    who, text = rest
                    add_msg(who, text, mine=False)
                elif kind == "sys":
                    sysline(rest[0])
                elif kind == "status":
                    up = rest[0]
                    status_lbl.configure(
                        text="● online" if up else "○ offline",
                        fg=ACCENT if up else MUTED)
        except queue.Empty:
            pass
        root.after(120, pump)

    # ── focus: KDE/Tk often doesn't put the cursor in the entry on launch.
    # Grab it forcefully a moment after the window is mapped.
    def grab_focus():
        try:
            root.lift()
            root.focus_force()
            entry.focus_set()
        except tk.TclError:
            pass
    root.after(200, grab_focus)
    root.after(600, grab_focus)   # second nudge after the WM settles
    # clicking anywhere in the window returns focus to the entry
    root.bind("<Button-1>", lambda e: entry.focus_set()
              if e.widget not in (entry,) else None)

    banner()
    mb = "ok" if MICHIBOX_DIR.exists() else "not found!"
    sysline(f"user={cfg['name']}  peer={cfg['peer_host'] or '(unset — [cfg])'}"
            f"  michibox={mb}")
    sysline("type a message and hit enter · files ride MichiBox · [cfg] to set peer")
    net.start_listener()
    root.after(120, pump)
    root.protocol("WM_DELETE_WINDOW", lambda: (net.stop(), root.destroy()))
    root.mainloop()


def _settings_dialog(root, cfg, net, append):
    import tkinter as tk
    from tkinter import messagebox

    win = tk.Toplevel(root)
    win.title("Settings")
    win.transient(root)
    win.grab_set()

    rows = [
        ("Your name", "name", str(cfg["name"])),
        ("Listen port", "listen_port", str(cfg["listen_port"])),
        ("Peer IP (the other machine)", "peer_host", str(cfg["peer_host"])),
        ("Peer port", "peer_port", str(cfg["peer_port"])),
        ("Allowlist (comma-separated IPs)", "allowlist",
         ", ".join(cfg["allowlist"])),
    ]
    vars_ = {}
    for i, (label, key, val) in enumerate(rows):
        tk.Label(win, text=label, anchor="w").grid(row=i, column=0,
                                                    sticky="w", padx=8, pady=4)
        v = tk.StringVar(value=val)
        tk.Entry(win, textvariable=v, width=34).grid(row=i, column=1,
                                                     padx=8, pady=4)
        vars_[key] = v

    tk.Label(win, text="Tip: find a machine's LAN IP with `ipconfig getifaddr "
                       "en0` (Mac) or `hostname -I` (Linux).",
             fg="#888", wraplength=380, justify="left").grid(
        row=len(rows), column=0, columnspan=2, sticky="w", padx=8, pady=(2, 6))

    def apply_and_close():
        cfg["name"] = vars_["name"].get().strip() or cfg["name"]
        try:
            cfg["listen_port"] = int(vars_["listen_port"].get())
            cfg["peer_port"] = int(vars_["peer_port"].get())
        except ValueError:
            messagebox.showerror(APP_NAME, "Ports must be numbers.")
            return
        cfg["peer_host"] = vars_["peer_host"].get().strip()
        allow = [x.strip() for x in vars_["allowlist"].get().split(",")
                 if x.strip()]
        if "127.0.0.1" not in allow:
            allow.insert(0, "127.0.0.1")
        cfg["allowlist"] = list(dict.fromkeys(allow))
        net.cfg = cfg
        save_config(cfg)
        append("settings saved. Restart the app to re-bind the listen port.",
               "sys")
        win.destroy()

    btns = tk.Frame(win)
    btns.grid(row=len(rows) + 1, column=0, columnspan=2, pady=8)
    tk.Button(btns, text="Save", command=apply_and_close).pack(side="left", padx=4)
    tk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=4)


if __name__ == "__main__":
    try:
        run_gui()
    except ModuleNotFoundError as e:
        if "tkinter" in str(e) or "_tkinter" in str(e):
            print("labchat-lan needs Tkinter (a GUI toolkit that ships with "
                  "Python).\n"
                  "  • macOS:  run with the system Python:  "
                  "/usr/bin/python3 labchat-lan.py\n"
                  "  • Debian/Ubuntu/Kubuntu:  sudo apt install python3-tk\n"
                  f"\n(original error: {e})")
            raise SystemExit(1)
        raise
