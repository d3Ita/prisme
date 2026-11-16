// Planche d'un webtoon : les images d'un projet les unes sous les autres, dans l'ordre choisi, avec un espace entre
// elles ; exportee en morceaux au format des plateformes (assemblee par Python, fichiers.exporterPlanche).
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Planche", "Strip") + (planche ? " · " + planche.projet : "")
    sousTitre: Theme.tx("Les images du projet les unes sous les autres, comme un épisode de webtoon. Range de nouvelles images dans le projet : elles s'ajoutent en bas.",
                        "The project's images one below the other, like a webtoon episode. Put new images in the project: they are added at the bottom.")
    width: Math.min(parent ? parent.width - 48 : 860, 860)
    property var planche: null
    // Largeur de l'apercu de la planche, a gauche
    readonly property int largeurApercu: 220
    readonly property real echelle: planche ? largeurApercu / planche.reglages.largeur : 1
    signal exportee()

    function ouvrir(projet) {
        planche = null
        open()
        Theme.api("/api/planche?projet=" + encodeURIComponent(projet), undefined, function (p) { planche = p },
                  function (m) { Theme.note(m, true); fenetre.close() })
    }

    function enregistrer(cases, retirees, reglages) {
        Theme.api("/api/planche", { projet: planche.projet, ordre: cases.map(c => c.nom), retirees: retirees, reglages: reglages },
                  function (p) { planche = p }, function (m) { Theme.note(m, true) })
    }

    function deplacer(i, sens) {
        const cases = planche.cases.slice()
        const j = i + sens
        if (j < 0 || j >= cases.length) return
        const c = cases[i]
        cases[i] = cases[j]
        cases[j] = c
        enregistrer(cases, planche.retirees, planche.reglages)
    }

    function retirer(i) {
        const cases = planche.cases.slice()
        const nom = cases.splice(i, 1)[0].nom
        enregistrer(cases, planche.retirees.concat([nom]), planche.reglages)
    }

    function remettre(nom) {
        // Remise en bas de la planche
        enregistrer(planche.cases.concat([{ nom: nom }]), planche.retirees.filter(n => n !== nom), planche.reglages)
    }

    function regler(cle, valeur) {
        const r = Object.assign({}, planche.reglages)
        r[cle] = valeur
        enregistrer(planche.cases, planche.retirees, r)
    }

    function hauteur(c) {
        return c.largeur ? Math.round(c.hauteur * planche.reglages.largeur / c.largeur) : 0
    }

    function hauteurTotale() {
        if (!planche || !planche.cases.length) return 0
        return planche.cases.reduce((t, c) => t + hauteur(c), 0) + planche.reglages.gouttiere * (planche.cases.length - 1)
    }

    function exporter(dossier) {
        if (typeof fichiers === "undefined") return
        const r = JSON.parse(fichiers.exporterPlanche(Theme.adresse, JSON.stringify(planche), dossier))
        if (r.erreur) {
            Theme.note(r.erreur, true)
            return
        }
        Theme.note((r.fichiers.length > 1 ? r.fichiers.length + Theme.tx(" images enregistrées dans ", " images saved in ")
                                          : Theme.tx("Image enregistrée dans ", "Image saved in ")) + r.dossier)
        exportee()
    }

    FolderDialog {
        id: choixDossier
        title: Theme.tx("Dossier où enregistrer la planche", "Folder to save the strip in")
        onAccepted: fenetre.exporter(selectedFolder.toString())
    }

    Text {
        visible: !fenetre.planche
        text: Theme.tx("Chargement…", "Loading…")
        color: Theme.texte2
        font.pixelSize: 13
    }

    // --- Reglages de la planche
    Section {
        visible: !!fenetre.planche
        titre: Theme.tx("Mise en page", "Layout")
        Ligne {
            nom: Theme.tx("Largeur", "Width")
            aide: Theme.tx("Celle de la plateforme où tu publies", "The one of the platform you publish on")
            ListeDeroulante {
                implicitWidth: 240
                model: [{ valeur: 800, texte: "Webtoon, Naver · 800 px" }, { valeur: 940, texte: "Tapas · 940 px" }, { valeur: 1080, texte: "1080 px" }]
                valeur: fenetre.planche ? fenetre.planche.reglages.largeur : 800
                onActivated: fenetre.regler("largeur", currentValue)
            }
        }
        Ligne {
            nom: Theme.tx("Espace entre les cases", "Space between panels")
            ListeDeroulante {
                implicitWidth: 240
                model: [{ valeur: 0, texte: Theme.tx("Aucun", "None") }, { valeur: 30, texte: Theme.tx("Petit · 30 px", "Small · 30 px") },
                        { valeur: 80, texte: Theme.tx("Moyen · 80 px", "Medium · 80 px") }, { valeur: 200, texte: Theme.tx("Grand · 200 px", "Large · 200 px") },
                        { valeur: 400, texte: Theme.tx("Très grand · 400 px", "Very large · 400 px") }]
                valeur: fenetre.planche ? fenetre.planche.reglages.gouttiere : 80
                onActivated: fenetre.regler("gouttiere", currentValue)
            }
        }
        Ligne {
            nom: Theme.tx("Fond", "Background")
            ListeDeroulante {
                implicitWidth: 240
                model: [{ valeur: "#ffffff", texte: Theme.tx("Blanc", "White") }, { valeur: "#000000", texte: Theme.tx("Noir", "Black") }]
                valeur: fenetre.planche ? fenetre.planche.reglages.fond : "#ffffff"
                onActivated: fenetre.regler("fond", currentValue)
            }
        }
        Ligne {
            nom: Theme.tx("Export", "Export")
            aide: Theme.tx("Webtoon Canvas : 1280 px de haut au plus par image. Les coupes tombent entre deux cases quand c'est possible.",
                           "Webtoon Canvas: 1280 px high at most per image. Cuts fall between two panels when possible.")
            Row {
                spacing: 6
                ListeDeroulante {
                    implicitWidth: 200
                    model: [{ valeur: 1280, texte: Theme.tx("Morceaux de 1280 px", "1280 px pieces") }, { valeur: 0, texte: Theme.tx("Une seule image", "A single image") }]
                    valeur: fenetre.planche ? fenetre.planche.reglages.decoupe : 1280
                    onActivated: fenetre.regler("decoupe", currentValue)
                }
                ListeDeroulante {
                    implicitWidth: 90
                    model: [{ valeur: "jpg", texte: "JPG" }, { valeur: "png", texte: "PNG" }]
                    valeur: fenetre.planche ? fenetre.planche.reglages.format : "jpg"
                    onActivated: fenetre.regler("format", currentValue)
                }
            }
        }
    }

    // --- Apercu (a gauche) et cases (a droite)
    Section {
        visible: !!fenetre.planche
        titre: Theme.tx("Cases", "Panels")
        description: !fenetre.planche ? "" : !fenetre.planche.cases.length
            ? Theme.tx("Aucune image dans ce projet : range des images dans « ", "No image in this project: put images in \"") + fenetre.planche.projet + Theme.tx(" » (fiche Détails, ou crée-les avec ce projet choisi).", "\" (Details, or create them with this project picked).")
            : fenetre.planche.cases.length + Theme.tx(" cases · ", " panels · ") + fenetre.hauteurTotale() + Theme.tx(" px de haut", " px high")
        RowLayout {
            Layout.fillWidth: true
            spacing: 18
            visible: !!fenetre.planche && fenetre.planche.cases.length > 0
            Rectangle {
                id: apercu
                objectName: "apercuPlanche"
                Layout.preferredWidth: fenetre.largeurApercu
                Layout.preferredHeight: colonneApercu.height
                Layout.alignment: Qt.AlignTop
                color: fenetre.planche ? fenetre.planche.reglages.fond : "#ffffff"
                border.color: Theme.bordure
                Column {
                    id: colonneApercu
                    width: parent.width
                    spacing: fenetre.planche ? fenetre.planche.reglages.gouttiere * fenetre.echelle : 0
                    Repeater {
                        model: fenetre.planche ? fenetre.planche.cases : []
                        delegate: Image {
                            required property var modelData
                            width: fenetre.largeurApercu
                            height: fenetre.hauteur(modelData) * fenetre.echelle
                            source: Theme.adresse + "/images/" + encodeURIComponent(modelData.nom)
                            sourceSize.width: fenetre.largeurApercu * 2
                            fillMode: Image.Stretch
                            asynchronous: true
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 8
                Repeater {
                    model: fenetre.planche ? fenetre.planche.cases : []
                    delegate: RowLayout {
                        id: ligneCase
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 10
                        Text {
                            text: ligneCase.index + 1
                            color: Theme.texte2
                            font.pixelSize: 13
                            Layout.preferredWidth: 22
                            horizontalAlignment: Text.AlignRight
                        }
                        ImageArrondie {
                            Layout.preferredWidth: 48
                            Layout.preferredHeight: 64
                            rayon: 8
                            source: Theme.adresse + "/images/" + encodeURIComponent(ligneCase.modelData.nom)
                        }
                        Text {
                            text: ligneCase.modelData.nom
                            color: Theme.texte2
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        BoutonDiscret {
                            icone: "monter"
                            aide: Theme.tx("Monter", "Move up")
                            enabled: ligneCase.index > 0
                            onClicked: fenetre.deplacer(ligneCase.index, -1)
                        }
                        BoutonDiscret {
                            icone: "descendre"
                            aide: Theme.tx("Descendre", "Move down")
                            enabled: !!fenetre.planche && ligneCase.index < fenetre.planche.cases.length - 1
                            onClicked: fenetre.deplacer(ligneCase.index, 1)
                        }
                        BoutonDiscret {
                            icone: "fermer"
                            aide: Theme.tx("Retirer de la planche (l'image reste dans le projet)", "Take out of the strip (the image stays in the project)")
                            onClicked: fenetre.retirer(ligneCase.index)
                        }
                    }
                }
            }
        }
    }

    Section {
        visible: !!fenetre.planche && fenetre.planche.retirees.length > 0
        titre: Theme.tx("Retirées de la planche", "Taken out of the strip")
        Flow {
            Layout.fillWidth: true
            spacing: 10
            Repeater {
                model: fenetre.planche ? fenetre.planche.retirees : []
                delegate: Column {
                    required property string modelData
                    spacing: 4
                    ImageArrondie {
                        width: 60
                        height: 80
                        rayon: 8
                        source: Theme.adresse + "/images/" + encodeURIComponent(parent.modelData)
                    }
                    BoutonDiscret { text: Theme.tx("Remettre", "Put back"); onClicked: fenetre.remettre(parent.modelData) }
                }
            }
        }
    }

    Item { implicitHeight: 4 }

    boutons: [
        Item { Layout.fillWidth: true },
        BoutonPrincipal { secondaire: true; text: Theme.tx("Fermer", "Close"); onClicked: fenetre.close() },
        BoutonPrincipal {
            objectName: "exporterPlanche"
            text: Theme.tx("Exporter…", "Export…")
            enabled: !!fenetre.planche && fenetre.planche.cases.length > 0
            onClicked: choixDossier.open()
        }
    ]
}
