// Demande a valider par l'utilisateur (un appareil veut acceder a Prisme, ou Claude demande un telechargement)
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: demande
    property string titre: ""
    property string accepter: Theme.tx("Autoriser", "Approve")
    property string refuser: Theme.tx("Refuser", "Refuse")
    default property alias contenu: zone.data
    signal reponse(bool accepte)
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(460, parent ? parent.width - 40 : 460)
    modal: true
    closePolicy: Popup.NoAutoClose
    padding: 26
    Overlay.modal: Rectangle { color: Theme.voile }
    background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.bordure }
    contentItem: ColumnLayout {
        spacing: 12
        Image {
            source: "../logo.png"
            sourceSize: Qt.size(56, 56)
            Layout.alignment: Qt.AlignHCenter
        }
        Text {
            text: demande.titre
            color: Theme.texte
            font.pixelSize: 18
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        ColumnLayout {
            id: zone
            Layout.fillWidth: true
            spacing: 10
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 6
            spacing: 10
            BoutonPrincipal { secondaire: true; text: demande.refuser; onClicked: demande.reponse(false) }
            BoutonPrincipal { text: demande.accepter; onClicked: demande.reponse(true) }
        }
    }
}
