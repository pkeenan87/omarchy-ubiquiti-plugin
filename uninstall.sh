#!/bin/bash
# Remove the UniFi Network plugin and everything it installed.
#
# `omarchy plugin remove` deletes the plugin directory only. This plugin also
# installs a systemd user service, a CLI symlink, a config file holding an API
# key, and a state file that inventories the network - none of which the
# plugin manager knows about.
#
#   ./uninstall.sh                 remove the plugin, ask about credentials
#   ./uninstall.sh --purge         remove everything, no questions
#   ./uninstall.sh --keep-config   remove the plugin, keep credentials

set -euo pipefail

plugin_id="io.github.pkeenan87.unifi-network"
plugin_dir="$HOME/.config/omarchy/plugins/$plugin_id"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-unifi"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-unifi"
unit="omarchy-unifi.service"

purge=ask
for arg in "$@"; do
  case "$arg" in
  --purge) purge=yes ;;
  --keep-config) purge=no ;;
  *)
    echo "unknown option: $arg" >&2
    exit 1
    ;;
  esac
done

# Stop the poller before its binary disappears, or it lingers on a deleted
# inode and fails at next login instead of now.
if systemctl --user list-unit-files "$unit" >/dev/null 2>&1; then
  systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
fi
rm -f "$HOME/.config/systemd/user/$unit"
systemctl --user daemon-reload || true
echo "Stopped and removed the background poller."

rm -f "$HOME/.local/bin/omarchy-unifi"

if [[ -d $plugin_dir ]]; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
  rm -rf "$plugin_dir"
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
  echo "Removed the plugin from the bar."
fi

if [[ $purge == ask ]]; then
  if [[ -e $config_dir || -e $state_dir ]]; then
    printf '\n%s\n' "Your API key and pinned certificate are in $config_dir,"
    printf '%s\n' "and $state_dir lists every client on your network."
    read -r -p "Delete them too? [y/N]: " answer
    [[ ${answer,,} == y || ${answer,,} == yes ]] && purge=yes || purge=no
  else
    purge=no
  fi
fi

if [[ $purge == yes ]]; then
  rm -rf "$config_dir" "$state_dir"
  printf '\n%s\n' "Deleted the API key, the pinned certificate, and the state file."
  printf '%s\n' "The key still exists on the console - revoke it under Integrations."
else
  printf '\n%s\n' "Kept $config_dir and $state_dir."
fi

printf '%s\n' "Done."
