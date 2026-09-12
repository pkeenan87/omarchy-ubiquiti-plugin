#!/bin/bash
# Install the UniFi Network plugin into the Omarchy shell.

set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_id="keenan.unifi-network"
plugin_dir="$HOME/.config/omarchy/plugins/$plugin_id"

mkdir -p "$plugin_dir"

for file in manifest.json BarWidget.qml Panel.qml LICENSE README.md; do
  if [[ $source_dir/$file != "$plugin_dir/$file" ]]; then
    install -m 644 "$source_dir/$file" "$plugin_dir/$file"
  fi
done

for directory in bin systemd; do
  if [[ $source_dir/$directory != "$plugin_dir/$directory" ]]; then
    mkdir -p "$plugin_dir/$directory"
    cp -R "$source_dir/$directory/." "$plugin_dir/$directory/"
  fi
done

chmod 755 "$plugin_dir/bin/omarchy-unifi"

# Put the CLI on PATH so `omarchy-unifi doctor` works from any terminal.
mkdir -p "$HOME/.local/bin"
ln -sf "$plugin_dir/bin/omarchy-unifi" "$HOME/.local/bin/omarchy-unifi"

# Install the background poller, but leave it stopped until there is a
# console to poll. `omarchy-unifi setup` enables it once that succeeds.
# ReadWritePaths requires this to exist before the unit starts.
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-unifi"
chmod 700 "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-unifi"

unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
install -m 644 "$source_dir/systemd/omarchy-unifi.service" "$unit_dir/omarchy-unifi.service"
systemctl --user daemon-reload

omarchy plugin validate "$plugin_dir"
omarchy-shell shell rescanPlugins
omarchy plugin enable "$plugin_id" --section right

if [[ -r "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-unifi/config.json" ]]; then
  # Restart rather than just enable: a running daemon holds the old script in
  # memory, so copying a new one over it changes nothing until it respawns.
  systemctl --user enable omarchy-unifi.service
  systemctl --user restart omarchy-unifi.service
  printf '\n%s\n' "UniFi Network is in the bar and polling."
else
  printf '\n%s\n' "UniFi Network is in the bar. Click it and choose Run setup,"
  printf '%s\n' "or run: omarchy-unifi setup"
fi
