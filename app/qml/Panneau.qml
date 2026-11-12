// Fenetre par-dessus Prisme (Modeles, Reglages) : titre, contenu qui defile, boutons en bas
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: panneau
    property string titre: ""
    property string sousTitre: ""
    default property alias contenu: colonne.data
    property alias boutons: boutons.data
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent ? parent.width - 48 : 760, 760)
    height: Math.min(parent ? parent.height - 48 : 720, 820)
    modal: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    Overlay.modal: Rectangle { color: Theme.voile }
    background: Rectangle {
        radius: 20
        color: Theme.surface
        border.color: Theme.bordure
    }
    contentItem: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 22
            Layout.bottomMargin: 10
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                Text { text: panneau.titre; color: Theme.texte; font.pixelSize: 20; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Text {
                    visible: panneau.sousTitre !== ""
                    text: panneau.sousTitre
                    color: Theme.texte2
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
            BoutonDiscret { text: "✕"; font.pixelSize: 16; onClicked: panneau.close() }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.bordure }
        ScrollView {
            id: defilement
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                id: colonne
                width: defilement.availableWidth - 44
                x: 22
                spacing: 26
                Item { implicitHeight: 2 }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.bordure; visible: boutons.children.length > 0 }
        RowLayout {
            id: boutons
            visible: children.length > 0
            Layout.fillWidth: true
            Layout.margins: 16
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            spacing: 8
        }
    }
}
