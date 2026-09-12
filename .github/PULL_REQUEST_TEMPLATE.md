## What this changes

<!-- And why. For anything touching the API surface, the systemd sandbox, or
     how console-supplied data is rendered, explain the constraint behind the
     decision — that context is hard to recover later. -->

## Checks

- [ ] `python3 -m unittest discover -s tests` passes
- [ ] `omarchy plugin validate .` exits 0
- [ ] `shellcheck install.sh uninstall.sh` is clean
- [ ] `omarchy restart shell`, then no plugin errors in `journalctl --user -t omarchy-shell`
- [ ] Panel opens, closes, and survives a shell restart
- [ ] `./uninstall.sh` then `./install.sh` leaves a working install

## If this touches QML

- [ ] Every `Text` that can render console-supplied data sets `textFormat: Text.PlainText`

## If this changes a setting

- [ ] `manifest.json` defaults and the README table agree (a test enforces this)
