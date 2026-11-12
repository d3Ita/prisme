// Barre d'avancement (part de 0 a 1)
import QtQuick

Rectangle {
    property real part: 0
    implicitHeight: 6
    radius: 3
    color: Theme.surface3
    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, parent.part))
        height: parent.height
        radius: parent.radius
        color: Theme.accent
        Behavior on width { NumberAnimation { duration: 200 } }
    }
}
