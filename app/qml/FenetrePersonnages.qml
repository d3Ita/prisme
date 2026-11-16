// Fiches personnages (webtoon, manhwa) : un nom, une description et une image de reference. Choisis dans la zone
// d'ecriture, ils gardent le meme personnage d'une image a l'autre (FLUX.2 klein ou Qwen-Image).
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Personnages", "Characters")
    sousTitre: Theme.tx("Garde le même personnage d'une image à l'autre : choisis-le avec le bouton Personnages avant de créer. Une image nette, de face et en entier, donne les meilleurs résultats.",
                        "Keep the same character from one image to the next: pick it with the Characters button before creating. A sharp, front-facing, full-body image works best.")
    width: Math.min(parent ? parent.width - 48 : 720, 720)
    property var fiches: []
    property bool possible: true
    property int nombreMax: 2
    // Personnages choisis pour les prochaines creations (identifiants), tenus par la fenetre principale
    property var choisis: []
    // Image de reference du nouveau personnage : { galerie, url, nom } ou { data, url, nom }
    property var nouvelleImage: null
    signal choix(var ids)
    signal change()

    onOpened: lire()

    function lire() {
        Theme.api("/api/personnages", undefined, function (r) {
            fiches = r.personnages
            possible = r.possible
            nombreMax = r.nombre_max
        })
    }

    function nouveau(image) {
        nouvelleImage = image
        nom.text = ""
        description.text = ""
        open()
        nom.forceActiveFocus()
    }

    function creer() {
        const corps = { nom: nom.text, description: description.text }
        if (nouvelleImage.galerie) corps.source_nom = nouvelleImage.galerie
        else corps.source_data = nouvelleImage.data
        Theme.api("/api/personnages", corps, function (fiche) {
            Theme.note(fiche.nom + Theme.tx(" est prêt : choisis-le avec le bouton Personnages.", " is ready: pick it with the Characters button."))
            nouvelleImage = null
            nom.text = ""
            description.text = ""
            // Le nouveau personnage est choisi tout de suite, s'il reste de la place
            if (fenetre.choisis.length < fenetre.nombreMax) fenetre.choix(fenetre.choisis.concat([fiche.id]))
            lire()
            change()
        }, function (message) { Theme.note(message, true) })
    }

    function basculer(id) {
        choix(choisis.indexOf(id) >= 0 ? choisis.filter(x => x !== id) : choisis.concat([id]))
    }

    FileDialog {
        id: choixFichier
        title: Theme.tx("Image du personnage", "Character image")
        nameFilters: [Theme.tx("Images", "Images") + " (*.png *.jpg *.jpeg *.webp *.bmp)"]
        onAccepted: {
            const image = typeof fichiers !== "undefined" ? fichiers.lireImage(selectedFile.toString()) : null
            if (image) fenetre.nouvelleImage = image
            else Theme.note(Theme.tx("Impossible de lire cette image.", "This image cannot be read."), true)
        }
    }

    component Description: TextArea {
        Layout.fillWidth: true
        Layout.preferredHeight: 64
        wrapMode: TextArea.Wrap
        font.pixelSize: 13
        color: Theme.texte
        placeholderTextColor: Theme.texte3
        selectByMouse: true
        background: Rectangle { radius: 10; color: Theme.surface2; border.color: parent.activeFocus ? Theme.accent : Theme.bordure }
    }

    Text {
        visible: !fenetre.possible
        text: Theme.tx("Ton modèle de dessin ne sait pas partir d'une image : choisis un profil FLUX.2 klein ou Qwen-Image dans la fenêtre des modèles pour utiliser tes personnages.",
                       "Your drawing model can't start from an image: pick a FLUX.2 klein or Qwen-Image profile in the Models window to use your characters.")
        color: Theme.danger
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    // --- Nouveau personnage
    Section {
        titre: Theme.tx("Nouveau personnage", "New character")
        description: Theme.tx("Depuis une image : le bouton Personnage sous une image du fil, ou un fichier.",
                              "From an image: the Character button under an image of the feed, or a file.")
        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Rectangle {
                Layout.preferredWidth: 96
                Layout.preferredHeight: 128
                Layout.alignment: Qt.AlignTop
                radius: 12
                color: Theme.fondImage
                clip: true
                ImageArrondie {
                    anchors.fill: parent
                    visible: !!fenetre.nouvelleImage
                    rayon: 12
                    source: fenetre.nouvelleImage ? fenetre.nouvelleImage.url : ""
                }
                Icone {
                    anchors.centerIn: parent
                    visible: !fenetre.nouvelleImage
                    nom: "personnage"
                    taille: 34
                    couleur: Theme.texte3
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Champ {
                    id: nom
                    objectName: "nomPersonnage"
                    Layout.fillWidth: true
                    maximumLength: 40
                    placeholderText: Theme.tx("Nom : Mina, Jun…", "Name: Mina, Jun…")
                }
                Description {
                    id: description
                    placeholderText: Theme.tx("Apparence : âge, cheveux, yeux, vêtements, signes distinctifs…",
                                              "Looks: age, hair, eyes, clothes, distinctive marks…")
                }
                RowLayout {
                    spacing: 6
                    BoutonDiscret {
                        icone: "image"
                        text: fenetre.nouvelleImage ? Theme.tx("Changer l'image", "Change the image") : Theme.tx("Choisir une image…", "Choose an image…")
                        onClicked: choixFichier.open()
                    }
                    Item { Layout.fillWidth: true }
                    BoutonPrincipal {
                        text: Theme.tx("Créer le personnage", "Create the character")
                        enabled: !!fenetre.nouvelleImage && nom.text.trim().length > 0
                        onClicked: fenetre.creer()
                    }
                }
            }
        }
    }

    // --- Personnages existants
    Section {
        titre: Theme.tx("Tes personnages", "Your characters")
        description: fenetre.fiches.length ? Theme.tx("Choisis-en ", "Pick up to ") + fenetre.nombreMax + Theme.tx(" au plus pour les prochaines créations.", " for the next creations.")
                                           : Theme.tx("Aucun personnage pour l'instant.", "No character yet.")
        Repeater {
            model: fenetre.fiches
            delegate: RowLayout {
                id: carte
                required property var modelData
                readonly property bool choisi: fenetre.choisis.indexOf(modelData.id) >= 0
                readonly property bool modifie: nomFiche.text.trim() !== modelData.nom || descriptionFiche.text.trim() !== modelData.description
                property bool confirmer: false
                Layout.fillWidth: true
                spacing: 14
                ImageArrondie {
                    Layout.preferredWidth: 72
                    Layout.preferredHeight: 96
                    Layout.alignment: Qt.AlignTop
                    rayon: 10
                    source: Theme.adresse + "/personnages/" + carte.modelData.image
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Champ {
                        id: nomFiche
                        Layout.fillWidth: true
                        maximumLength: 40
                        text: carte.modelData.nom
                    }
                    Description { id: descriptionFiche; text: carte.modelData.description; placeholderText: description.placeholderText }
                    RowLayout {
                        spacing: 6
                        Interrupteur {
                            checked: carte.choisi
                            enabled: carte.choisi || fenetre.choisis.length < fenetre.nombreMax
                            onToggled: fenetre.basculer(carte.modelData.id)
                        }
                        Text {
                            text: Theme.tx("Pour les prochaines créations", "For the next creations")
                            color: Theme.texte2
                            font.pixelSize: 13
                            Layout.fillWidth: true
                        }
                        BoutonDiscret {
                            visible: carte.modifie
                            text: Theme.tx("Enregistrer", "Save")
                            onClicked: Theme.api("/api/personnages", { id: carte.modelData.id, nom: nomFiche.text, description: descriptionFiche.text },
                                                 function () { Theme.note(Theme.tx("Personnage enregistré", "Character saved")); fenetre.lire(); fenetre.change() },
                                                 function (m) { Theme.note(m, true) })
                        }
                        BoutonDiscret {
                            danger: true
                            text: carte.confirmer ? Theme.tx("Supprimer vraiment ?", "Really delete?") : Theme.tx("Supprimer", "Delete")
                            onClicked: {
                                if (!carte.confirmer) { carte.confirmer = true; return }
                                Theme.api("/api/personnages/supprimer", { id: carte.modelData.id }, function () {
                                    fenetre.choix(fenetre.choisis.filter(x => x !== carte.modelData.id))
                                    fenetre.lire()
                                    fenetre.change()
                                }, function (m) { Theme.note(m, true) })
                            }
                        }
                    }
                }
            }
        }
    }

    Item { implicitHeight: 4 }

    boutons: [
        Item { Layout.fillWidth: true },
        BoutonPrincipal { secondaire: true; text: Theme.tx("Fermer", "Close"); onClicked: fenetre.close() }
    ]
}
