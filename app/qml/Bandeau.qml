// Bandeau en haut du fil (nouvelle version, Claude) : un texte, des boutons, et Masquer
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: bandeau
    property string texte: ""
    property bool masquable: true
    default property alias boutons: boutons.data
    signal masquer()
    Layout.fillWidth: true
    Layout.leftMargin: 18
    Layout.rightMargin: 18
    implicitHeight: ligne.implicitHeight + 16
    radius: 14
    color: Theme.surface
    border.color: Theme.bordure
    RowLayout {
        id: ligne
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 8
        spacing: 10
        Text {
            text: bandeau.texte
            color: Theme.texte
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Row { id: boutons; spacing: 6 }
        BoutonDiscret { visible: bandeau.masquable; text: "✕"; onClicked: bandeau.masquer() }
    }
}
