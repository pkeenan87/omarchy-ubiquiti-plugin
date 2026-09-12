# Security policy

## Reporting a vulnerability

If you believe you've found a security vulnerability in this plugin, please
**do not** open a public issue. Instead:

- Open a private security advisory at
  <https://github.com/pkeenan87/omarchy-ubiquiti-plugin/security/advisories/new>, or
- Email the maintainer directly with details and reproduction steps.

I aim to acknowledge new reports within **5 business days** and to provide a
remediation plan within **15 business days** for High / Critical issues.

## Why this plugin warrants care

It holds a UniFi Network API key, which is a **full-admin credential for the
console** — it can block every client, restart every device, and read or
change configuration. It also writes a state file that inventories the home
network by name, MAC and IP. Both live under the user's home directory and are
never transmitted anywhere except to the console itself.

## Threat model

What the design assumes, and what it defends against:

| Threat | Control |
|--------|---------|
| API key intercepted on the LAN | The console's certificate is pinned at setup (SHA-256, checked in `connect()`); a mismatch aborts before any request is sent. Consoles ship self-signed certificates, so CA verification alone is not available. |
| Key leaking into logs, argv, or other processes | The key is never passed as an argument, printed by any command, or written to the state file. `getpass` keeps it out of shell history. There is no `UNIFI_API_KEY` env var, because an exported credential is readable in `/proc/*/environ`. `UNIFI_API_KEY_FILE` points at a file instead. |
| Key or inventory readable by other local users | `config.json`, `console.pem` and `state.json` are written `0600` via `os.open`, their directories `0700`, and the poller runs with `UMask=0077`. |
| Hostile data from the network | Client names come from DHCP option 12, so any device on the network chooses its own. All names render as `Text.PlainText` and are stripped of C0/C1 control characters and length-capped, so a name cannot impersonate another client, inject markup, or break row layout. |
| A compromised poller reading the rest of `$HOME` | The systemd unit runs with `ProtectHome=tmpfs` and bind-mounts only its config, its own code and its state directory, plus `SystemCallFilter`, `RestrictAddressFamilies`, `NoNewPrivileges` and friends. |
| Shell injection through device or client names | Every subprocess is spawned with an argv list. Nothing reaches a shell. MACs are validated against a strict pattern before being sent. |

## Scope

In scope:

- `bin/omarchy-unifi` — the poller, CLI and API client
- `BarWidget.qml` / `Panel.qml` — anything rendered from console-supplied data
- `systemd/omarchy-unifi.service` — sandbox configuration
- `install.sh` / `uninstall.sh` — file permissions and credential handling

Out of scope:

- Vulnerabilities in UniFi Network or UniFi OS themselves — report those to
  Ubiquiti.
- Vulnerabilities in Omarchy, Quickshell or Hyprland — report those upstream.
- Anything requiring an attacker who already has your user account or root on
  the machine. The credential is protected against other local users, not
  against you.
- The fact that TLS verification is disabled when nothing is pinned. That is
  the documented state of an install predating pinning; `omarchy-unifi doctor`
  reports it and `omarchy-unifi trust-cert` fixes it.

## Revoking a key

Deleting the local config does **not** revoke the key. Revoke it on the
console under Integrations, the same screen that issued it.

## Coordinated disclosure

I follow standard 90-day coordinated-disclosure practice and will work with
reporters on a public-disclosure timeline once a fix has shipped.
