# UniFi Network for Omarchy

A bar widget for a UniFi OS console — Dream Machine, Cloud Gateway, UDM Pro,
UDR, or UniFi OS Server. It shows what your network is doing without opening
the UniFi app, and handles the three things you usually open the app for:
restarting a device, blocking a client, and running a speed test.

```
 24  ↓12M ↑1.1M
```

Client count, live WAN throughput, and — when something is wrong — the label
turns your theme's urgent colour. A healthy network stays visually quiet.

## Install

```bash
git clone https://github.com/keenan/omarchy-plugin-unifi
cd omarchy-plugin-unifi
./install.sh
omarchy-unifi setup
```

`setup` asks for your console's address and an API key. Create the key in the
UniFi Network app under **Settings → Control Plane → Integrations → Create API
Key**. It is shown once, so copy it before closing the dialog.

Setup verifies the connection before saving anything, then enables the
background poller. If it cannot connect, nothing is written.

## What you get

**In the bar.** Client count and WAN throughput, refreshed by a background
service. The label turns urgent when the internet drops, a device goes
offline, or firmware updates are pending. A small dot marks a stale reading —
the console became unreachable — so a frozen number never reads as a live one.

- **Left click** — open the panel
- **Middle click** — refresh now
- **Right click** — open the console's web UI

**In the panel.** Internet status with IP, latency, uptime, and throughput;
every adopted device with its kind, address, client count and firmware state;
the busiest clients with signal quality and current throughput; and anything
you have blocked.

Hovering a row reveals its actions. Devices can be restarted. Clients can be
reconnected or blocked, and blocked clients unblocked. Restarting and blocking
ask for confirmation first; reconnecting does not, because a client normally
comes straight back.

## Configuration

Widget settings live in `~/.config/omarchy/shell.json` and hot-reload on save:

| Key | Default | Meaning |
|-----|---------|---------|
| `showClients` | `true` | Show the client count in the bar |
| `showThroughput` | `true` | Show WAN throughput in the bar |
| `refreshIntervalSec` | `10` | Poll rate while the panel is open |
| `maxClients` | `12` | Clients listed in the panel |

```json
{ "id": "keenan.unifi-network", "maxClients": 20, "showThroughput": false }
```

Console settings live in `~/.config/omarchy-unifi/config.json` (mode `0600`):
`host`, `apiKey`, `site`, `verifySsl`, `pollIntervalSec`, `timeoutSec`.

Set `verifySsl` to `true` only if you have given the console a certificate
your machine trusts. It is off by default because consoles ship a self-signed
certificate for their LAN address, which no CA will vouch for.

## Command line

```bash
omarchy-unifi status          # what the bar is showing, as text
omarchy-unifi status --json   # the full state file
omarchy-unifi doctor          # check the address, key, and endpoints
omarchy-unifi poll            # refresh once
omarchy-unifi speedtest --wait
omarchy-unifi restart <mac>
omarchy-unifi block <mac> | unblock <mac> | kick <mac>
```

`doctor` is the place to start when the panel looks wrong. It reports the
config path and its permissions, and probes both API surfaces separately so
you can tell a bad key from an unreachable host.

## How it works

The QML never speaks HTTP. `omarchy-unifi daemon` polls the console and writes
`~/.local/state/omarchy-unifi/state.json`; the panel watches that file and
shells back out to the same CLI for actions.

That split matters for three reasons: the API key never enters the shell
process, a hung or unreachable console can never stall the bar, and every
behaviour in the panel is reproducible from a terminal.

Reads and writes both use the console's `/proxy/network/api` surface, which on
UniFi OS accepts the same API key as the newer Integration API and is the only
one that exposes health rollups, client blocking, and speed tests. `doctor`
probes the Integration API too, so a key that only works there produces a
clear diagnosis rather than an empty panel.

The poller is a stdlib-only Python script — no pip, no node, nothing to keep
updated — and its systemd unit is confined to reading your home directory and
writing its own state file.

## Privacy

The state file lists every client on your network by name, MAC, and IP. It is
written `0600`, as is the config file holding your API key. Both live under
your home directory and are never sent anywhere.

An API key grants full access to the console until you revoke it, which you
can do at any time in the same Integrations screen that issued it.

## Requirements

- A UniFi OS console (Network 9.0 or newer for API keys)
- Omarchy with the Quickshell-based shell
- Python 3.9+ (already present on Omarchy)

A self-hosted UniFi Network Application that is *not* running on UniFi OS does
not support API keys and will not work with this plugin.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers state shaping against realistic payloads and drives the
client end to end against a stub console with a self-signed certificate,
including auth failures, unreachable hosts, and every action payload.

## License

MIT
