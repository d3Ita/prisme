// Image aux coins arrondis, decodee a la taille affichee
import QtQuick
import QtQuick.Effects

Item {
    id: cadre
    property alias source: image.source
    property real rayon: 14
    Rectangle { anchors.fill: parent; radius: cadre.rayon; color: Theme.fondImage }
    Image {
        id: image
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true
        // Une image agrandie (5120 px) se decode a la taille affichee : moins de memoire
        sourceSize.width: 1400
        visible: false
        layer.enabled: true
    }
    Rectangle {
        id: masque
        anchors.fill: parent
        radius: cadre.rayon
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        anchors.fill: image
        source: image
        maskEnabled: true
        maskSource: masque
    }
}
