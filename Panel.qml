import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// UniFi console popup.
//
// This panel never speaks HTTP. `omarchy-unifi` polls the console and writes
// a state file; the panel watches that file and shells back out to the same
// CLI for actions. That keeps credentials and TLS handling out of the shell
// process, and means a hung console can never stall the bar.
Panel {
  id: root
  moduleName: "keenan.unifi-network"
  manageIpc: false

  property Item anchorItem: null
  property var hostWidget: null

  readonly property string home: Quickshell.env("HOME")
  readonly property string stateHome: (Quickshell.env("XDG_STATE_HOME") || home + "/.local/state")
  readonly property string statePath: stateHome + "/omarchy-unifi/state.json"
  // decodeURIComponent: resolvedUrl percent-encodes, so a home directory with
  // a space produced a path that does not exist and actions failed silently.
  readonly property string pluginDir: decodeURIComponent(
    String(Qt.resolvedUrl(".")).replace("file://", ""))
  readonly property string cli: pluginDir + "bin/omarchy-unifi"

  property var state: ({})
  property string actionError: ""
  property string busyLabel: ""

  readonly property int refreshSeconds: Math.max(3, setting("refreshIntervalSec", 10))
  readonly property int maxClients: Math.max(3, setting("maxClients", 25))

  // ---- derived state -------------------------------------------------

  readonly property var wan: state && state.wan ? state.wan : ({})
  readonly property var clients: state && state.clients ? state.clients : ({})
  readonly property var devices: state && state.devices ? state.devices : ({})
  readonly property var deviceList: devices && devices.list ? devices.list : []
  readonly property var clientList: state && state.clientList ? state.clientList : []
  readonly property var blockedList: state && state.blockedList ? state.blockedList : []
  readonly property var alerts: state && state.alerts ? state.alerts : []
  readonly property var notices: state && state.notices ? state.notices : []
  readonly property var partial: state && state.partial ? state.partial : []

  // An empty state file means the CLI has never run; that is a setup
  // problem, not a network problem, and the panel says so differently.
  // `configured` is reported by the CLI: a poll that failed purely because
  // no console is set up must show the setup card, not a fake outage.
  readonly property bool configured: state && state.updatedAt !== undefined
                                     && state.configured !== false
  readonly property bool stale: configured && state.stale === true
  readonly property bool wanUp: wan && wan.up === true
  // Deliberately excludes `stale` and `notices`: a dropped poll gets the bar's
  // quiet dot, and a deferred firmware update should not look like an outage.
  readonly property bool healthy: configured && wanUp && alerts.length === 0

  readonly property string barTooltip: {
    if (!configured) return "UniFi Network — not set up yet"
    if (stale) return "UniFi Network — " + (state.error || "cannot reach console")
    var lines = [
      (wanUp ? "Internet up" : "Internet DOWN") + (wan.ip ? " · " + wan.ip : ""),
      "↓ " + humanBps(wan.downBps) + "bps   ↑ " + humanBps(wan.upBps) + "bps",
      (clients.total || 0) + " clients · " + (clients.wireless || 0) + " wireless, "
        + (clients.wired || 0) + " wired",
      (devices.online || 0) + "/" + (devices.total || 0) + " devices online"
    ]
    for (var i = 0; i < alerts.length; i++) lines.push("! " + alerts[i])
    return lines.join("\n")
  }

  // ---- formatting ----------------------------------------------------

  function humanBps(bytesPerSecond) {
    var bits = Math.max(0, Number(bytesPerSecond) || 0) * 8
    var units = [["G", 1e9], ["M", 1e6], ["k", 1e3]]
    for (var i = 0; i < units.length; i++) {
      if (bits >= units[i][1]) {
        var value = bits / units[i][1]
        return (value < 10 ? value.toFixed(1) : Math.round(value)) + units[i][0]
      }
    }
    return "0"
  }

  function humanUptime(seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0))
    var days = Math.floor(total / 86400)
    var hours = Math.floor((total % 86400) / 3600)
    var minutes = Math.floor((total % 3600) / 60)
    if (days) return days + "d " + hours + "h"
    if (hours) return hours + "h " + minutes + "m"
    return minutes + "m"
  }

  function signalLabel(client) {
    if (client.wired) return "Wired"
    var signal = Number(client.signal) || 0
    if (signal === 0) return client.essid || "Wireless"
    // UniFi reports RSSI in dBm; -50 is excellent, -80 is barely usable.
    var quality = signal >= -55 ? "Strong" : (signal >= -70 ? "Good" : "Weak")
    return (client.essid ? client.essid + " · " : "") + quality
  }

  function relativeAge(epochSeconds) {
    var age = Date.now() / 1000 - (Number(epochSeconds) || 0)
    if (age < 0 || !isFinite(age)) return ""
    return humanUptime(age) + " ago"
  }

  // ---- state file ----------------------------------------------------

  function applyState(text) {
    if (!text || text.trim() === "") return
    try {
      root.state = JSON.parse(text)
    } catch (error) {
      // A torn read is possible in theory; the writer swaps atomically, so
      // the right response is to wait for the next change rather than show
      // an error the user cannot act on.
      root.state = root.state
    }
  }

  function reloadState() {
    if (pollProcess.running) return
    pollProcess.command = [root.cli, "poll"]
    pollProcess.running = true
  }

  // ---- actions -------------------------------------------------------

  function runAction(args, label) {
    if (actionProcess.running) return
    root.actionError = ""
    root.busyLabel = label
    actionProcess.command = [root.cli].concat(args)
    actionProcess.running = true
  }

  function restartDevice(device) {
    confirm.message = "Restart " + device.name + "?\nIt will drop off the network for a minute."
    confirm.confirmText = "Restart"
    confirm.onAccept = function() { runAction(["restart", device.mac], "Restarting " + device.name) }
    confirm.opened = true
  }

  function blockClient(client) {
    confirm.message = "Block " + client.name + "?\nIt stays blocked until you unblock it here."
    confirm.confirmText = "Block"
    confirm.onAccept = function() { runAction(["block", client.mac], "Blocking " + client.name) }
    confirm.opened = true
  }

  function kickClient(client) {
    // Reconnecting is not destructive - most clients come straight back -
    // so this one does not need a confirmation step.
    runAction(["kick", client.mac], "Reconnecting " + client.name)
  }

  function unblockClient(entry) {
    runAction(["unblock", entry.mac], "Unblocking " + entry.name)
  }

  function openConsole() {
    launchProcess.command = [root.cli, "open"]
    launchProcess.running = true
  }

  function openSetup() {
    // Setup prompts for an API key, so it needs a real terminal.
    launchProcess.command = ["xdg-terminal-exec", root.cli, "setup"]
    launchProcess.running = true
    root.close()
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyState(text())
    onLoadFailed: root.state = ({})
  }

  // If the daemon is running, its writes arrive through FileView and a second
  // loop here only doubles the request rate against the console and gives
  // state.json two concurrent writers. So poll from the panel only when the
  // daemon is not running, plus once on open so a long-shut panel is current.
  property bool daemonRunning: false

  Process {
    id: daemonCheck
    running: false
    command: ["systemctl", "--user", "is-active", "--quiet", "omarchy-unifi.service"]
    onExited: function(exitCode) { root.daemonRunning = exitCode === 0 }
  }

  onOpenedChanged: {
    if (!opened) return
    if (!daemonCheck.running) daemonCheck.running = true
    root.reloadState()
  }

  Timer {
    interval: root.refreshSeconds * 1000
    repeat: true
    running: root.opened && !root.daemonRunning
    onTriggered: root.reloadState()
  }

  Process {
    id: pollProcess
    running: false
    onExited: stateFile.reload()
  }

  Process { id: launchProcess; running: false }

  Process {
    id: actionProcess
    running: false
    stderr: StdioCollector {
      onStreamFinished: {
        var message = text.trim()
        if (message !== "") root.actionError = message
      }
    }
    onExited: function(exitCode) {
      root.busyLabel = ""
      if (exitCode === 0) root.actionError = ""
      stateFile.reload()
    }
  }

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color surface: Util.alpha(foreground, 0.05)

  // Small text button used across the header and the setup card. Wraps the
  // shared Ui/Button so hover, pressed and focus fills come from the theme's
  // control tokens rather than from alpha values hardcoded here.
  component ActionButton: Button {
    property string label: ""
    property bool outlined: false
    signal triggered()

    text: label
    bordered: outlined
    foreground: root.foreground
    accent: Color.accent
    fontFamily: root.fontFamily
    fontSize: Style.font.bodySmall
    opacity: enabled ? 1 : 0.4
    onClicked: if (enabled) triggered()
  }

  // A filled dot reads as "online" faster than any word does.
  component StatusDot: Rectangle {
    property bool ok: true
    width: Style.space(7)
    height: width
    radius: width / 2
    color: ok ? Util.alpha(root.foreground, 0.65) : root.urgent
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(460))
    contentHeight: panel.fittedContentHeight(
      headerRow.implicitHeight + Style.space(10) + content.implicitHeight,
      Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      // While the dialog is up it owns the keyboard. Without this, Enter did
      // nothing and Tab switched bar panels out from under an open
      // confirmation, leaving it armed with its callback intact.
      onCloseRequested: confirm.opened ? confirm.canceled() : root.close()
      onTabRequested: function(direction) {
        if (confirm.opened) confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0
        else root.switchPanel(direction)
      }
      onMoveRequested: function(dx, dy) {
        if (confirm.opened && dx !== 0)
          confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0
      }
      onActivateRequested: {
        if (!confirm.opened) return
        if (confirm.selectedIndex === 0) confirm.canceled()
        else confirm.confirmed()
      }

      Column {
        id: panelBody
        anchors.fill: parent
        spacing: Style.space(10)

        // ---- header (pinned above the scroll region) ----
        Row {
          id: headerRow
          width: parent.width
          spacing: Style.space(8)

          Text {
            textFormat: Text.PlainText
            width: parent.width - headerActions.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            text: "UNIFI NETWORK"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
          }

          Row {
            id: headerActions
            spacing: Style.space(6)

            ActionButton {
              label: "Refresh"
              enabled: !actionProcess.running
              onTriggered: root.reloadState()
            }

            ActionButton {
              visible: root.configured
              label: "Console"
              outlined: true
              onTriggered: root.openConsole()
            }
          }
        }

        // Everything below the header scrolls as one region. A scrollable
        // list per section would need a height budget that stays correct as
        // alerts, devices and clients all vary independently; this cannot
        // overflow the card no matter what the console reports.
        Flickable {
          id: bodyScroll
          width: parent.width
          height: parent.height - headerRow.height - panelBody.spacing
          contentHeight: content.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          // Only steals wheel events when there is somewhere to scroll.
          interactive: contentHeight > height

          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          Column {
            id: content
            width: bodyScroll.width
            spacing: Style.space(10)

            // ---- first-run ----
            Rectangle {
              visible: !root.configured
              width: parent.width
              height: visible ? setupColumn.implicitHeight + Style.space(24) : 0
              radius: Style.cornerRadius
              color: root.surface

              Column {
                id: setupColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(12)
                spacing: Style.space(8)

                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  text: "Connect your UniFi console"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }

                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: "Open your console's Integrations page, create an API "
                      + "key, then run setup — it prints the exact URL for your "
                      + "console. The key is stored in your config directory, "
                      + "readable only by you."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }

                ActionButton {
                  label: "Run setup"
                  onTriggered: root.openSetup()
                }
              }
            }

            // ---- internet ----
            PanelHero {
              visible: root.configured
              width: parent.width
              foreground: root.wanUp && !root.stale ? root.foreground : root.urgent
              fontFamily: root.fontFamily
              title: root.stale ? "Console unreachable"
                   : (root.wanUp ? "Internet up" : "Internet down")
              meta: {
                if (root.stale) return "last reading " + root.relativeAge(root.state.updatedAt)
                if (!root.wanUp) return root.state.error || "No WAN connectivity"
                var parts = []
                if (root.wan.ip) parts.push(root.wan.ip)
                if (root.wan.latencyMs >= 0) parts.push(Math.round(root.wan.latencyMs) + " ms")
                if (root.wan.uptimeSec > 0) parts.push("up " + root.humanUptime(root.wan.uptimeSec))
                return parts.join("  ·  ")
              }
            }

            // Sits directly under the hero's meta line rather than in the
            // hero's trailing pill: it is the fastest-changing number here and
            // reads better as the last line of that block than as a badge.
            Text {
              textFormat: Text.PlainText
              visible: root.configured && root.wanUp
              width: parent.width
              text: "↓ " + root.humanBps(root.wan.downBps) + "bps"
                  + "      ↑ " + root.humanBps(root.wan.upBps) + "bps"
              // PanelHero insets its labels by the icon gutter even when it
              // has no icon; match it so this reads as the block's last line.
              leftPadding: Style.space(14)
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            // ---- alerts ----
            Repeater {
              model: root.configured ? root.alerts : []

              Rectangle {
                required property string modelData
                width: content.width
                height: alertText.implicitHeight + Style.space(12)
                radius: Style.cornerRadius
                color: Util.alpha(root.urgent, 0.14)

                Text {
                  textFormat: Text.PlainText
                  id: alertText
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(10)
                  text: parent.modelData
                  color: root.urgent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }
              }
            }

                // A device or client fetch that failed used to hide its whole
            // section, leaving a hero and nothing else with no explanation.
            Text {
              textFormat: Text.PlainText
              visible: root.configured && root.partial.length > 0
              width: parent.width
              leftPadding: Style.space(14)
              text: root.partial.join(" and ") + " could not be listed this poll"
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            // ---- notices (informational; never urgent) ----
            Repeater {
              model: root.configured ? root.notices : []

              Rectangle {
                required property string modelData
                width: content.width
                height: noticeText.implicitHeight + Style.space(12)
                radius: Style.cornerRadius
                color: root.surface

                Text {
                  id: noticeText
                  textFormat: Text.PlainText
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(10)
                  text: parent.modelData
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }
              }
            }

        // ---- action feedback ----
            Text {
              textFormat: Text.PlainText
              visible: root.busyLabel !== "" || root.actionError !== ""
              width: parent.width
              text: root.actionError !== "" ? root.actionError : root.busyLabel + "…"
              color: root.actionError !== "" ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            // ---- devices ----
            PanelSeparator {
              visible: root.configured && root.deviceList.length > 0
              width: parent.width
              foreground: root.foreground
            }

            PanelSectionHeader {
              visible: root.configured && root.deviceList.length > 0
              width: parent.width
              foreground: root.foreground
              fontFamily: root.fontFamily
              text: "DEVICES  ·  " + (root.devices.online || 0) + "/" + (root.devices.total || 0) + " ONLINE"
            }

            Repeater {
              model: root.configured ? root.deviceList : []

              Rectangle {
                id: deviceRow
                required property var modelData
                width: content.width
                height: Style.space(34)
                radius: Style.cornerRadius
                color: deviceMouse.containsMouse ? root.surface : "transparent"

                MouseArea {
                  id: deviceMouse
                  anchors.fill: parent
                  hoverEnabled: true
                }

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(10)

                  StatusDot {
                    anchors.verticalCenter: parent.verticalCenter
                    ok: deviceRow.modelData.online
                  }

                  Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - Style.space(18) - deviceActions.width - parent.spacing * 2
                    spacing: Style.space(1)

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: deviceRow.modelData.name
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                    }

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: {
                        var item = deviceRow.modelData
                        var parts = [item.kind]
                        if (!item.online) parts.push("offline")
                        else if (item.clients > 0) parts.push(item.clients + " clients")
                        if (item.ip) parts.push(item.ip)
                        if (item.updatable) parts.push("update available")
                        return parts.join("  ·  ")
                      }
                      color: deviceRow.modelData.online ? root.dim : root.urgent
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }

                  Row {
                    id: deviceActions
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(4)
                    // Visible at rest so the row reads as actionable, and
                    // full strength on hover. Fully hidden meant nothing
                    // signalled that these rows do anything at all.
                    opacity: deviceMouse.containsMouse ? 1 : 0.35

                    PanelActionButton {
                      iconText: ""
                      // The console cannot restart a device that is offline.
                      visible: deviceRow.modelData.online
                      tooltipText: "Restart " + deviceRow.modelData.name
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      enabled: !actionProcess.running
                      onClicked: root.restartDevice(deviceRow.modelData)
                    }
                  }
                }
              }
            }

            // ---- clients ----
            PanelSeparator {
              visible: root.configured && root.clientList.length > 0
              width: parent.width
              foreground: root.foreground
            }

            PanelSectionHeader {
              visible: root.configured && root.clientList.length > 0
              width: parent.width
              foreground: root.foreground
              fontFamily: root.fontFamily
              text: "CLIENTS  ·  " + (root.clients.total || 0) + " CONNECTED"
            }

            Repeater {
              // Busiest clients first, capped so the panel stays a panel.
              model: root.configured ? root.clientList.slice(0, root.maxClients) : []

              Rectangle {
                id: clientRow
                required property var modelData
                width: content.width
                height: Style.space(34)
                radius: Style.cornerRadius
                color: clientMouse.containsMouse ? root.surface : "transparent"

                MouseArea {
                  id: clientMouse
                  anchors.fill: parent
                  hoverEnabled: true
                }

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(10)

                  Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - clientActions.width - parent.spacing
                    spacing: Style.space(1)

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: clientRow.modelData.name
                           + (clientRow.modelData.guest ? "  (guest)" : "")
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                    }

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: {
                        var item = clientRow.modelData
                        var parts = [root.signalLabel(item)]
                        if (item.ip) parts.push(item.ip)
                        if (item.downBps + item.upBps > 0)
                          parts.push("↓" + root.humanBps(item.downBps)
                                   + " ↑" + root.humanBps(item.upBps))
                        return parts.join("  ·  ")
                      }
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }

                  Row {
                    id: clientActions
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(4)
                    opacity: clientMouse.containsMouse ? 1 : 0.35

                    PanelActionButton {
                      iconText: ""
                      tooltipText: "Reconnect " + clientRow.modelData.name
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      enabled: !actionProcess.running
                      onClicked: root.kickClient(clientRow.modelData)
                    }

                    PanelActionButton {
                      iconText: ""
                      tooltipText: "Block " + clientRow.modelData.name
                      foreground: root.foreground
                      hoverColor: root.urgent
                      fontFamily: root.fontFamily
                      enabled: !actionProcess.running
                      onClicked: root.blockClient(clientRow.modelData)
                    }
                  }
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              // clientList is capped at 100 by the CLI, so subtracting from it
              // under-reported once a network had more clients than that.
              visible: root.configured && (root.clients.total || 0) > root.maxClients
              width: parent.width
              text: "+ " + ((root.clients.total || 0) - root.maxClients)
                  + " more · omarchy-unifi clients"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }

            // ---- blocked ----
            PanelSeparator {
              visible: root.configured && root.blockedList.length > 0
              width: parent.width
              foreground: root.foreground
            }

            PanelSectionHeader {
              visible: root.configured && root.blockedList.length > 0
              width: parent.width
              foreground: root.foreground
              fontFamily: root.fontFamily
              text: "BLOCKED"
            }

            Repeater {
              model: root.configured ? root.blockedList : []

              Rectangle {
                id: blockedRow
                required property var modelData
                width: content.width
                height: Style.space(28)
                radius: Style.cornerRadius
                color: blockedMouse.containsMouse ? root.surface : "transparent"

                MouseArea {
                  id: blockedMouse
                  anchors.fill: parent
                  hoverEnabled: true
                }

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(10)

                  Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - unblockButton.width - parent.spacing
                    text: blockedRow.modelData.name
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                  }

                  PanelActionButton {
                    id: unblockButton
                    anchors.verticalCenter: parent.verticalCenter
                    iconText: ""
                    tooltipText: "Unblock " + blockedRow.modelData.name
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    enabled: !actionProcess.running
                    onClicked: root.unblockClient(blockedRow.modelData)
                  }
                }
              }
            }

            // ---- footer ----
            Text {
              textFormat: Text.PlainText
              visible: root.configured
              width: parent.width
              text: {
                var host = root.state.host || ""
                var age = root.relativeAge(root.state.updatedAt)
                return host + (age ? "  ·  updated " + age : "")
              }
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }
          }
        }
      }

      // Inside the key catcher so it covers the card: the panel's own root
      // item has no size, so anchoring there would never paint.
      ConfirmDialog {
        id: confirm
        property var onAccept: null
        anchors.fill: parent
        z: 10
        background: Color.popups.background
        foreground: root.foreground
        fontFamily: root.fontFamily
        onConfirmed: {
          opened = false
          if (onAccept) onAccept()
        }
        onCanceled: opened = false
      }
    }
  }
}
