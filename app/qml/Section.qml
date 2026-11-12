// Bloc d'une fenetre : titre, liens a droite, puis le contenu
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: section
    property string titre: ""
    property string description: ""
    default property alias contenu: zone.data
    property alias liens: liens.data
    Layout.fillWidth: true
    spacing: 10
    RowLayout {
        Layout.fillWidth: true
        Text {
            text: section.titre
            color: Theme.texte
            font.pixelSize: 15
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }
        Row { id: liens; spacing: 2 }
    }
    Text {
        visible: section.description !== ""
        text: section.description
        color: Theme.texte2
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    ColumnLayout {
        id: zone
        Layout.fillWidth: true
        spacing: 12
    }
}
