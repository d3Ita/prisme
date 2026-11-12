// Bouton de l'action principale (accent) ; secondaire = contour seulement
import QtQuick
import QtQuick.Controls.Basic

Button {
    id: bouton
    property bool secondaire: false
    implicitHeight: 36
    leftPadding: 18
    rightPadding: 18
    font.pixelSize: 13.5
    font.weight: Font.DemiBold
    contentItem: Text {
        text: bouton.text
        font: bouton.font
        color: bouton.secondaire ? Theme.texte : Theme.surAccent
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 999
        color: bouton.secondaire ? (bouton.hovered ? Theme.surface3 : Theme.surface) : Theme.accent
        border.color: bouton.secondaire ? Theme.bordureForte : "transparent"
        opacity: bouton.enabled ? (bouton.down ? 0.85 : 1) : 0.45
    }
}
