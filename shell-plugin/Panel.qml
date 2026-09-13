pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "eduardo.hardware-lights"
  ipcTarget: "eduardo.hardware-lights"

  readonly property string lightsBin: Quickshell.env("HOME") + "/.local/bin/omarchy-lights"
  readonly property string statusPath: Quickshell.env("HOME") + "/.local/state/omarchy-lights/status.json"

  property var status: ({})
  readonly property var devices: status.devices || []
  readonly property var shades: status.shades || []
  readonly property string accent: status.accent || ""
  property double now: Date.now() / 1000
  readonly property bool stale: !status.updated || (now - status.updated) > 30

  readonly property int syncing: {
    var n = 0
    for (var i = 0; i < devices.length; i++) if (devices[i].enabled && devices[i].present) n++
    return n
  }
  readonly property int missing: {
    var n = 0
    for (var i = 0; i < devices.length; i++) if (devices[i].enabled && !devices[i].present) n++
    return n
  }

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string glyph: "󰌵"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function run(args) {
    Quickshell.execDetached(args)
  }

  function toggleDevice(id) {
    run([lightsBin, "toggle", id])
  }

  function summary() {
    if (stale) return "daemon not running"
    if (devices.length === 0) return "nothing detected"
    var text = syncing + " of " + devices.length + " syncing"
    if (missing > 0) text += " · " + missing + " missing"
    return text
  }

  FileView {
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.status = JSON.parse(text()) } catch (e) { root.status = ({}) }
    }
    onLoadFailed: root.status = ({})
  }

  // the file only changes when the daemon writes it, so freshness needs its own clock
  Timer {
    interval: 5000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.now = Date.now() / 1000
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    dimmed: root.syncing === 0
    active: root.missing > 0 || root.stale
    tooltipText: "Hardware lights · " + root.summary()
    onPressed: function(b) {
      if (b === Qt.RightButton) root.run([root.lightsBin, "sync"])
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "s" || t === "S") root.run([root.lightsBin, "sync"])
        else if (t === "r" || t === "R") root.run([root.lightsBin, "restart"])
      }

      Column {
        id: column
        anchors.fill: parent
        spacing: Style.space(12)

        PanelHero {
          width: parent.width
          title: root.status.theme || "Hardware lights"
          meta: root.accent !== "" ? root.accent : "no palette yet"
          detail: root.summary()
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: root.glyph
              color: root.accent !== "" ? root.accent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }
          }
        }

        Row {
          id: swatches
          width: parent.width
          height: Style.space(10)
          visible: root.shades.length > 0
          spacing: 0

          Repeater {
            model: root.shades
            Rectangle {
              required property string modelData
              width: swatches.width / Math.max(1, root.shades.length)
              height: swatches.height
              color: modelData
            }
          }
        }

        Text {
          visible: root.stale
          width: parent.width
          textFormat: Text.PlainText
          text: "The animation daemon is not reporting. Toggles are saved but only take effect once it runs: systemctl --user start omarchy-lights"
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          visible: !root.stale && root.devices.length === 0
          width: parent.width
          textFormat: Text.PlainText
          text: "No hardware detected yet"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Column {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.devices
            Toggle {
              required property var modelData
              width: parent.width
              label: modelData.name
              description: modelData.detail
              checked: modelData.enabled
              foreground: modelData.enabled && !modelData.present ? root.urgent : root.foreground
              fontFamily: root.fontFamily
              onClicked: root.toggleDevice(modelData.id)
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.space(6)

          Button {
            width: (parent.width - parent.spacing) / 2
            text: "Sync now"
            bordered: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.run([root.lightsBin, "sync"])
          }

          Button {
            width: (parent.width - parent.spacing) / 2
            text: "Restart daemon"
            bordered: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.run([root.lightsBin, "restart"])
          }
        }
      }
    }
  }
}
