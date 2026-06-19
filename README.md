# labchat

> A live two-way text chat between two machines on a LAN — riding the ssh
> connection you already have. Same command on both ends. No email, no cloud,
> no extra daemon to babysit.

You ssh into a box. You want to paste a snippet to it, or have it send a line
back, without opening a mail client or a third-party service. `labchat` gives
you a tiny live chat: type a line on either end, it appears on the other.

It's two small shell scripts. The traffic never touches the open LAN in the
clear — the listener binds to the **box's loopback**, and the client forwards
that port through ssh. So it's as private as your ssh session, and there's no
new port exposed to the network.

## Two ends, one command

```sh
# on your laptop — connects to the box over an ssh tunnel:
labchat

# on the box itself — joins the same chat locally, no ssh/tunnel:
labchat here
```

Both see the same conversation:

```
[mac] deploy done?
[box] yep, restarting now
```

Install labchat on both machines (it's just two files). The laptop drives the
box over ssh; the box joins its own local listener directly.

## How it works

```
your machine                         remote box (e.g. a server you ssh into)
────────────                         ──────────────────────────────────────
  nc ──► 127.0.0.1:9999  ══ssh -L══►  127.0.0.1:9999  ──► socat (fork)
                                                            │  per connection:
                                                            ├─ tail -f ~/.labchat-wall  (you SEE this)
                                                            └─ append stdin ►► ~/.labchat-wall  (you SEND this)
```

- A shared **wall** file (`~/.labchat-wall` on the remote) is the conversation.
- Each connection streams the tail of the wall to you (history + anything
  anyone types) and appends what you type back into it.
- Because it's append-only to one file, **multiple people/sessions** can join
  the same wall and all see each other.

## Requirements

- `ssh` access from the client to the box (a `~/.ssh/config` entry is easiest).
- `socat` on the **box** (`sudo apt install socat` on Debian/Ubuntu).
- `nc` on both ends (preinstalled on macOS and most Linux).
- `bash` on both ends.

## Install

Install on **both** machines (it's two small files):

```sh
git clone git@github.com:andycufari/labchat.git
cd labchat
chmod +x labchat labchatd.sh
ln -s "$PWD/labchat" /usr/local/bin/labchat     # put it on PATH
```

When you connect as a client, `labchatd.sh` (the per-connection handler) is also
copied to the box automatically — but having labchat on the box lets you run
`labchat here` for the nice local chat UX.

## Usage

**From the client (laptop)** — point at the box and connect over ssh:

```sh
export LABCHAT_HOST=myserver        # ssh alias, or user@1.2.3.4
labchat                             # starts the box listener, opens the chat
```

**On the box** — join the same chat locally (no ssh, no tunnel):

```sh
labchat here
```

Now type on either side. Lines are tagged with each host's name; `/quit` or
Ctrl-C leaves. The listener keeps running for the next session — stop it
explicitly with `labchat stop` (run that on the box, or from the client to stop
the remote one).

### One-shot, no session

```sh
labchat say "deploy finished, logs in /var/log/app"   # push one line to the wall
labchat tail                                          # print the last 30 lines and exit
```

(`say`/`tail`/`status`/`stop` act on the box from the client, or locally when
run on the box.)

### Just run a listener

```sh
labchat serve     # on the box: start the listener and exit (no interactive chat)
labchat status    # up on :9999  /  down
labchat stop      # kill the listener
```

## Configuration

All via environment variables:

| Var            | Default                | Meaning                                   |
|----------------|------------------------|-------------------------------------------|
| `LABCHAT_HOST` | `cm64labs`             | ssh alias or `user@host` of the remote    |
| `LABCHAT_PORT` | `9999`                 | loopback port on the remote (+ local fwd) |
| `LABCHAT_NAME` | your short hostname    | tag prefixed to your outgoing lines       |

## Notes & caveats

- **Privacy:** the chat rides ssh; the listener is loopback-only on the remote.
  Nothing is exposed on the LAN. It's as private as your ssh connection.
- **Persistence:** the listener does not survive a remote reboot. Just run
  `labchat` again — it relinks and re-installs the handler if needed.
- **Not encrypted at rest:** the wall is a plain file in the remote's home dir.
  Don't paste secrets you wouldn't leave in a file there. `rm ~/.labchat-wall`
  to wipe the history.
- **One wall per remote:** everyone who connects to the same remote shares one
  conversation. Use `LABCHAT_PORT` + a separate wall if you want isolated rooms
  (currently the wall path is fixed; PRs welcome).

## License

MIT
