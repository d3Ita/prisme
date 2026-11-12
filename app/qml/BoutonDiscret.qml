// Bouton sans fond, pour les actions secondaires
import QtQuick
import QtQuick.Controls.Basic

Button {
    id: bouton
    property bool danger: false
    flat: true
    implicitHeight: 30
    leftPadding: 10
    rightPadding: 10
    font.pixelSize: 13
    contentItem: Text {
        text: bouton.text
        font: bouton.font
        color: !bouton.enabled ? Theme.texte3 : bouton.danger && bouton.hovered ? Theme.danger : bouton.hovered ? Theme.texte : Theme.texte2
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 8
        color: bouton.hovered && bouton.enabled ? Theme.surface3 : "transparent"
    }
}
