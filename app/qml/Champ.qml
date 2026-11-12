// Champ de saisie d'une ligne
import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: champ
    implicitHeight: 34
    implicitWidth: 300
    font.pixelSize: 13
    color: Theme.texte
    placeholderTextColor: Theme.texte3
    leftPadding: 12
    selectByMouse: true
    background: Rectangle {
        radius: 10
        color: Theme.surface2
        border.color: champ.activeFocus ? Theme.accent : Theme.bordure
    }
}
