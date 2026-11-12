// Interrupteur marche / arret, comme ceux de la version web
import QtQuick
import QtQuick.Controls.Basic

Switch {
    id: interrupteur
    implicitWidth: 42
    implicitHeight: 24
    padding: 0
    indicator: Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: interrupteur.checked ? Theme.accent : Theme.surface3
        border.color: interrupteur.checked ? Theme.accent : Theme.bordureForte
        Rectangle {
            width: 18
            height: 18
            radius: 9
            y: 3
            x: interrupteur.checked ? parent.width - width - 3 : 3
            color: interrupteur.checked ? Theme.surAccent : Theme.surface
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: Item {}
}
