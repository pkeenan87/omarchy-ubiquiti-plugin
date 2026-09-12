# Contributing

Thanks for your interest. This guide covers everything needed to land a change.

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

For **security vulnerabilities**, follow [SECURITY.md](SECURITY.md) instead of
opening a public issue.

---

## Project layout

```
omarchy-ubiquiti-plugin/
├── manifest.json        # Omarchy plugin manifest and settings schema
├── BarWidget.qml        # the bar entry; owns IPC and loads the panel
├── Panel.qml            # the popup; reads state, shells out for actions
├── bin/omarchy-unifi    # poller, CLI and UniFi API client (stdlib only)
├── systemd/             # user service for background polling
├── tests/               # unit + integration tests
├── install.sh           # install into ~/.config/omarchy/plugins/
└── uninstall.sh         # remove the plugin, service, and credentials
```

## The one architectural rule

**The QML never speaks HTTP.** `bin/omarchy-unifi` polls the console and writes
`~/.local/state/omarchy-unifi/state.json`; `Panel.qml` watches that file with
`FileView` and shells back out to the same CLI for actions.

Keep it that way. It is what keeps the API key out of the long-running shell
process, stops an unreachable console from stalling the bar, and makes every
behaviour in the panel reproducible from a terminal.

## Local setup

You need a machine running Omarchy, and a UniFi OS console to point at.

```bash
git clone https://github.com/pkeenan87/omarchy-ubiquiti-plugin
cd omarchy-ubiquiti-plugin
./install.sh
omarchy-unifi setup
```

`install.sh` copies into `~/.config/omarchy/plugins/`, so re-run it after every
change. Editing the installed copy directly works for quick experiments, but
those edits are overwritten by the next install.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

No dependencies beyond the standard library and `openssl` (used to generate a
stub certificate). The integration tests stand up a real HTTPS server with a
self-signed, `CA:FALSE` certificate — matching what a console presents — and
drive the client through it, including auth failures, unreachable hosts,
certificate mismatches, and every action payload.

Tests must never read `~/.config/omarchy-unifi`; both suites redirect every
user-owned path into a temp directory at import time. Keep that intact.

## Working on the QML

Two traps will cost you an hour each if you don't know them:

1. **A QML error makes the plugin fail to load silently.** No error appears in
   the journal; the widget just renders its fallback state. Worse, the file
   watcher then stops firing, so later fixes appear to do nothing. Run
   `omarchy restart shell` before concluding a change didn't work.

2. **`console.log` from plugin QML** shows up as `DEBUG qml:` lines in
   `journalctl --user -t omarchy-shell`. Filter by `_PID=$(pgrep -x quickshell)`
   — stale lines from previous shell instances are very misleading.

## Before opening a PR

```bash
python3 -m unittest discover -s tests   # all green
omarchy plugin validate .               # exit 0, silent on success
shellcheck install.sh uninstall.sh
omarchy restart shell                   # then confirm no QML errors
```

Also walk the plugin lifecycle once, as the Omarchy guidance asks: open and
close the panel, toggle the widget off and on (`omarchy plugin disable` /
`enable`), restart the shell, and run `./uninstall.sh` followed by
`./install.sh`.

If you change a default in `manifest.json`, update the table in the README.
A test enforces that they agree.

## Commit style

Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `style:`).

Explain *why* in the body, not just what — particularly for anything touching
the API surface, the sandbox, or how untrusted data is rendered. Several
decisions in this codebase look arbitrary until you know the constraint behind
them, and the commit message is where that gets recorded.

## Bumping the version

`manifest.json` uses semantic versioning. Update it in the same commit as the
change, add a `CHANGELOG.md` entry, and tag the release (`v1.2.0`).
