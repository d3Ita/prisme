// Liste deroulante ; model = [{ valeur, texte }], valeur = la valeur choisie
import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: liste
    property string valeur: ""
    textRole: "texte"
    valueRole: "valeur"
    implicitHeight: 34
    implicitWidth: 300
    font.pixelSize: 13
    onActivated: valeur = currentValue
    onValeurChanged: currentIndex = indexOfValue(valeur)
    onModelChanged: currentIndex = indexOfValue(valeur)
    contentItem: Text {
        leftPadding: 12
        rightPadding: 28
        text: liste.displayText
        font: liste.font
        color: Theme.texte
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }
    indicator: Text {
        x: liste.width - width - 12
        anchors.verticalCenter: parent.verticalCenter
        text: "⌄"
        color: Theme.texte2
        font.pixelSize: 14
    }
    background: Rectangle {
        radius: 10
        color: Theme.surface2
        border.color: liste.activeFocus ? Theme.accent : Theme.bordure
    }
    delegate: ItemDelegate {
        id: choix
        required property var modelData
        required property int index
        width: liste.width
        highlighted: liste.highlightedIndex === index
        contentItem: Text {
            text: choix.modelData.texte
            color: Theme.texte
            font: liste.font
            elide: Text.ElideMiddle
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle { color: choix.highlighted ? Theme.surface3 : Theme.surface }
    }
    popup.background: Rectangle {
        radius: 10
        color: Theme.surface
        border.color: Theme.bordure
    }
}
