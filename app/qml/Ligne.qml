// Une ligne de reglage : nom et explication a gauche, controle a droite
import QtQuick
import QtQuick.Layouts

RowLayout {
    id: ligne
    property string nom: ""
    property string aide: ""
    default property alias controle: zone.data
    Layout.fillWidth: true
    spacing: 16
    ColumnLayout {
        spacing: 2
        Layout.fillWidth: true
        Layout.preferredWidth: 260
        Text {
            text: ligne.nom
            color: Theme.texte
            font.pixelSize: 14
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
        Text {
            visible: ligne.aide !== ""
            text: ligne.aide
            color: Theme.texte3
            font.pixelSize: 12
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
    }
    Item {
        id: zone
        implicitWidth: childrenRect.width
        implicitHeight: childrenRect.height
        Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
    }
}
