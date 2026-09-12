import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar entry for the UniFi console.
//
// Three things are readable without opening anything: how many clients are
// on the network, what the WAN is currently pushing, and whether any of the
// gear is unhappy. The first two are the label; the third is the colour,
// because a count that is fine most of the time should not cost bar width.
BarWidget {
  id: root
  moduleName: "keenan.unifi-network"

  // The bar is a status light, not a readout: the figures change constantly,
  // cost width permanently, and are a click away in the panel (and in the
  // tooltip without one). Both are opt-in.
  readonly property bool showThroughput: setting("showThroughput", false)
  readonly property bool showClients: setting("showClients", false)

  readonly property var state: panelLoader.item ? panelLoader.item.state : ({})
  readonly property bool configured: panelLoader.item ? panelLoader.item.configured : false
  readonly property bool healthy: panelLoader.item ? panelLoader.item.healthy : true
  readonly property bool stale: panelLoader.item ? panelLoader.item.stale : false

  readonly property string clientText: {
    var clients = state && state.clients ? state.clients : null
    return clients && clients.total !== undefined ? String(clients.total) : "–"
  }

  readonly property string throughputText: {
    if (!panelLoader.item) return ""
    var wan = state && state.wan ? state.wan : null
    if (!wan) return ""
    return "↓" + panelLoader.item.humanBps(wan.downBps)
         + " ↑" + panelLoader.item.humanBps(wan.upBps)
  }

  // nf-fa-signal: three plain bars. The neighbouring network widget already
  // owns the wifi arcs and the ethernet plug, so this stays legible beside
  // them instead of reading as a second wifi indicator.
  readonly property string icon: ""

  readonly property string displayText: {
    if (!configured) return icon + "  setup"
    var parts = []
    if (showClients) parts.push(clientText)
    if (showThroughput && throughputText !== "") parts.push(throughputText)
    // The glyph's advance leaves almost no gap of its own, so the icon gets a
    // wider separator than the figures get between themselves.
    return parts.length ? icon + "  " + parts.join(" ") : icon
  }


  // Shape contract for Bar.findPanelWidget popout routing.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }
  function refresh() { if (panelLoader.item) panelLoader.item.reloadState() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "keenan.unifi-network"

    function refresh(): void { root.refresh() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.vertical ? root.icon : root.displayText
    labelVisible: true
    hasVisualContent: text !== ""
    // Tuned against a screenshot: 26px between this glyph and the icon beside
    // it, against 24-32px for the bar's other pairs. On a 2x display the gap
    // only lands on even numbers, so 26 is as close to mid-range as it gets;
    // the next step down is 24. The stock 8.75 leaves this glyph crowded, as
    // it is wider than most. (WidgetButton ignores this if fixedWidth is set.)
    horizontalMargin: 9.625
    verticalPadding: 8.75

    // Trouble is worth a colour change; everything else stays in the theme's
    // normal foreground so a healthy network is visually quiet. `active`
    // drives the label to the bar's urgent colour.
    active: !root.healthy && root.configured
    useActiveColor: true

    tooltipText: panelLoader.item ? panelLoader.item.barTooltip : "UniFi Network"

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.togglePanel()
      else if (buttonCode === Qt.MiddleButton) root.refresh()
      else if (buttonCode === Qt.RightButton && panelLoader.item)
        panelLoader.item.openConsole()
    }

    // A stale reading is not the same as a broken network; mark it quietly
    // rather than turning the whole label red.
    Rectangle {
      visible: root.stale && root.configured
      width: Style.space(5)
      height: width
      radius: width / 2
      color: root.bar ? root.bar.urgent : Color.urgent
      opacity: 0.8
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.rightMargin: Style.space(2)
      anchors.topMargin: Style.space(2)
    }
  }
}
