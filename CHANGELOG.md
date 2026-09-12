# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-09-12

First release.

### Added

- Bar widget showing WAN state, with the label turning urgent when the
  internet drops or a device goes offline. Client count and throughput are
  opt-in via `showClients` and `showThroughput`.
- Panel with internet status, every adopted device, the busiest clients, and
  anything currently blocked. Restart a device, reconnect or block a client,
  unblock a blocked one — each with a confirmation where the action is
  destructive, and a notice afterwards for the ones that succeed invisibly.
- `omarchy-unifi` CLI: `setup`, `doctor`, `trust-cert`, `poll`, `daemon`,
  `status`, `clients`, `devices`, `restart`, `block`, `unblock`, `kick`,
  `open`. Stdlib-only Python; no pip packages.
- Background poller as a confined systemd user service.
- `install.sh` and `uninstall.sh`, the latter removing the service, the
  symlink, the plugin, and optionally the credentials and state.

### Security

- The console's TLS certificate is pinned at setup, before the API key is
  ever transmitted; a mismatch aborts during connect, so nothing is sent to
  an impostor. `trust-cert` re-pins after a legitimate change.
- Console-supplied names render as plain text and are stripped of control
  characters. Client names come from DHCP option 12, so any device on the
  network chooses its own.
- Credentials, the pinned certificate and the state file are written `0600`
  in `0700` directories. The key never appears in argv, logs, command output,
  or the state file, and there is no `UNIFI_API_KEY` environment variable.
- The poller runs with `ProtectHome=tmpfs`, bind-mounting only what it needs,
  plus a syscall filter and address-family restrictions.

[Unreleased]: https://github.com/pkeenan87/omarchy-ubiquiti-plugin/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/pkeenan87/omarchy-ubiquiti-plugin/releases/tag/v1.0.0
