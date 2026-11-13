// Comparer des modeles : la meme description et la meme variante avec 2 a 4 profils installes
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Comparer des modèles", "Compare models")
    sousTitre: Theme.tx("Une image par profil, avec la même description et la même variante, et les réglages conseillés de chaque modèle. Le temps de chacune s'affiche sous l'image.",
                        "One image per profile, with the same description and variant, and each model's recommended settings. The time of each shows under the image.")
    width: Math.min(parent ? parent.width - 48 : 560, 560)
    height: Math.min(parent ? parent.height - 48 : 600, 600)
    property var profils: []
    property var choisis: []
    signal comparer(var profils)

    onOpened: {
        choisis = []
        Theme.api("/api/profils", undefined, function (p) { profils = p.profils.filter(x => x.installe) })
    }

    Text {
        visible: fenetre.profils.length < 2
        text: Theme.tx("Télécharge au moins deux profils dans la fenêtre Modèles pour les comparer.",
                       "Download at least two profiles in the Models window to compare them.")
        color: Theme.texte2
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    Repeater {
        model: fenetre.profils
        delegate: Ligne {
            required property var modelData
            nom: Theme.enLangue(modelData.nom)
            aide: modelData.modeles.map(m => m.nom).filter((n, i, t) => t.indexOf(n) === i).join(" · ")
            Interrupteur {
                checked: fenetre.choisis.indexOf(modelData.id) >= 0
                enabled: checked || fenetre.choisis.length < 4
                onToggled: fenetre.choisis = checked ? fenetre.choisis.concat([modelData.id]) : fenetre.choisis.filter(i => i !== modelData.id)
            }
        }
    }

    boutons: [
        Item { Layout.fillWidth: true },
        BoutonPrincipal {
            text: Theme.tx("Comparer", "Compare") + (fenetre.choisis.length ? " (" + fenetre.choisis.length + ")" : "")
            enabled: fenetre.choisis.length >= 2
            onClicked: { fenetre.comparer(fenetre.choisis); fenetre.close() }
        }
    ]
}
