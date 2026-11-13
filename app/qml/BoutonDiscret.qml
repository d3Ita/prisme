// Bouton sans fond, pour les actions secondaires : texte, icone, ou les deux. Une icone seule a une infobulle (aide),
// lue aussi par les lecteurs d'ecran
import QtQuick
import QtQuick.Controls.Basic

Button {
    id: bouton
    property bool danger: false
    property string icone: ""
    property string aide: ""
    // Choix en cours (format choisi, LoRA modifies) : fond marque
    property bool actif: false
    readonly property color couleur: !bouton.enabled ? Theme.texte3 : bouton.danger && bouton.hovered ? Theme.danger
                                     : bouton.hovered || bouton.actif ? Theme.texte : Theme.texte2
    flat: true
    implicitHeight: 32
    implicitWidth: icone !== "" && text === "" ? 32 : contenu.implicitWidth + leftPadding + rightPadding
    leftPadding: icone !== "" && text === "" ? 0 : 10
    rightPadding: leftPadding
    font.pixelSize: 13
    ToolTip.visible: hovered && aide !== ""
    ToolTip.text: aide
    ToolTip.delay: 400
    Accessible.name: aide !== "" ? aide : text
    contentItem: Item {
        implicitWidth: contenu.implicitWidth
        implicitHeight: contenu.implicitHeight
        Row {
            id: contenu
            anchors.centerIn: parent
            spacing: 6
            Icone {
                visible: bouton.icone !== ""
                nom: bouton.icone
                couleur: bouton.couleur
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: bouton.text !== ""
                text: bouton.text
                font: bouton.font
                color: bouton.couleur
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
    background: Rectangle {
        radius: 8
        color: bouton.actif ? Theme.surface3 : bouton.hovered && bouton.enabled ? Theme.surface2 : "transparent"
        border.color: bouton.actif ? Theme.bordure : "transparent"
    }
}
