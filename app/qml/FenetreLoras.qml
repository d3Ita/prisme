// Bibliotheque de LoRA : ceux de Hugging Face faits pour le modele de dessin choisi, avec un apercu, la licence et un
// telechargement verifie (SHA-256) dans models/loras
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Bibliothèque de LoRA", "LoRA library")
    sousTitre: Theme.tx("Des styles et des effets partagés sur Hugging Face pour ton modèle de dessin. Ils ne sont pas vérifiés par Prisme : regarde l'exemple et la licence avant de télécharger.",
                        "Styles and effects shared on Hugging Face for your drawing model. Prisme does not check them: look at the example and the license before downloading.")
    width: Math.min(parent ? parent.width - 48 : 900, 900)
    height: Math.min(parent ? parent.height - 48 : 820, 820)
    property var loras: []
    property bool chargement: false
    property string erreur: ""
    property bool modelePersonnel: false
    // Telechargements lances ici : { depot: { ident, fichier, phase, fait, total } }
    property var suivis: ({})
    signal installe()

    onOpened: if (!loras.length) chercher()

    function chercher() {
        chargement = true
        erreur = ""
        Theme.api("/api/loras/bibliotheque" + (recherche.text.trim() ? "?q=" + encodeURIComponent(recherche.text.trim()) : ""), undefined,
                  function (r) {
                      chargement = false
                      modelePersonnel = !r.famille
                      loras = r.loras
                  }, function (message) {
                      chargement = false
                      erreur = message
                  })
    }

    function telecharger(l, fichier) {
        Theme.api("/api/loras/telecharger", { id: l.id, fichier: fichier, nombre: l.fichiers.length }, function (r) {
            const s = Object.assign({}, suivis)
            s[l.id] = { ident: r.id, phase: "attente", fait: 0, total: r.taille }
            suivis = s
        }, function (message) { Theme.note(message, true) })
    }

    // Avancement des telechargements lances ici, lu dans l'etat de Prisme
    Timer {
        interval: 1000
        repeat: true
        running: fenetre.opened && Object.keys(fenetre.suivis).some(d => ["attente", "telechargement", "verification"].indexOf(fenetre.suivis[d].phase) >= 0)
        onTriggered: Theme.api("/api/etat", undefined, function (e) {
            const s = Object.assign({}, fenetre.suivis)
            let fini = false
            for (const depot of Object.keys(s)) {
                const t = (e.telechargements || []).find(x => x.id === s[depot].ident)
                if (!t) continue
                if (t.phase === "termine" && s[depot].phase !== "termine") fini = true
                if (t.phase === "erreur") Theme.note(t.erreur || Theme.tx("Le téléchargement a échoué.", "The download failed."), true)
                s[depot] = Object.assign({}, s[depot], { phase: t.phase, fait: t.fait, total: t.total || s[depot].total })
            }
            fenetre.suivis = s
            if (fini) {
                Theme.note(Theme.tx("LoRA téléchargé : choisis-le avec le bouton LoRA.", "LoRA downloaded: pick it with the LoRA button."))
                fenetre.installe()
            }
        })
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Champ {
            id: recherche
            Layout.fillWidth: true
            implicitHeight: 34
            leftPadding: 34
            placeholderText: Theme.tx("Chercher un style : pixel, aquarelle, anime…", "Search a style: pixel, watercolor, anime…")
            onAccepted: fenetre.chercher()
            Icone { x: 11; anchors.verticalCenter: parent.verticalCenter; nom: "recherche"; taille: 16; couleur: Theme.texte3 }
        }
        BoutonPrincipal { secondaire: true; text: Theme.tx("Chercher", "Search"); onClicked: fenetre.chercher() }
    }

    Text {
        visible: text !== ""
        text: fenetre.chargement ? Theme.tx("Recherche sur Hugging Face…", "Searching Hugging Face…")
              : fenetre.erreur !== "" ? fenetre.erreur
              : fenetre.modelePersonnel ? Theme.tx("La bibliothèque connaît les LoRA des modèles du catalogue (FLUX.2 klein, Z-Image, Qwen-Image). Pour ton propre modèle, place ses LoRA dans le dossier models/loras.",
                                                   "The library knows the LoRA of the catalog models (FLUX.2 klein, Z-Image, Qwen-Image). For your own model, put its LoRA in the models/loras folder.")
              : !fenetre.loras.length ? Theme.tx("Aucun LoRA trouvé.", "No LoRA found.") : ""
        color: fenetre.erreur !== "" ? Theme.danger : Theme.texte2
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    GridLayout {
        id: grille
        Layout.fillWidth: true
        columns: Math.max(1, Math.floor((width + columnSpacing) / (210 + columnSpacing)))
        columnSpacing: 14
        rowSpacing: 14
        Repeater {
            model: fenetre.chargement ? [] : fenetre.loras
            delegate: Rectangle {
                id: carte
                required property var modelData
                readonly property var suivi: fenetre.suivis[modelData.id] || null
                readonly property bool fini: modelData.installe || (!!suivi && suivi.phase === "termine")
                readonly property bool enCours: !!suivi && ["attente", "telechargement", "verification"].indexOf(suivi.phase) >= 0
                // Largeur d'une colonne, meme quand la recherche ne trouve qu'un ou deux LoRA
                Layout.preferredWidth: (grille.width - (grille.columns - 1) * grille.columnSpacing) / grille.columns
                Layout.alignment: Qt.AlignTop
                implicitHeight: colonne.implicitHeight + 24
                radius: 14
                color: Theme.surface2
                border.color: Theme.bordure
                ColumnLayout {
                    id: colonne
                    x: 12
                    y: 12
                    width: parent.width - 24
                    spacing: 6
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 140
                        radius: 10
                        color: Theme.fondImage
                        clip: true
                        Image {
                            id: apercu
                            anchors.fill: parent
                            // Servie par Prisme, qui la telecharge une fois et la garde : rapide a la reouverture
                            source: carte.modelData.apercu ? Theme.adresse + "/api/loras/apercu?id=" + encodeURIComponent(carte.modelData.id) : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            sourceSize.width: 420
                        }
                        Icone {
                            anchors.centerIn: parent
                            visible: apercu.status !== Image.Ready
                            nom: "lora"
                            taille: 34
                            couleur: Theme.texte3
                        }
                    }
                    Text {
                        text: carte.modelData.nom
                        color: Theme.texte
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: carte.modelData.auteur + " · " + carte.modelData.telechargements.toLocaleString(Qt.locale(), "f", 0)
                              + Theme.tx(" téléchargements", " downloads")
                        color: Theme.texte3
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: Theme.tx("Licence : ", "License: ") + (carte.modelData.licence || Theme.tx("non indiquée", "not stated"))
                        color: carte.modelData.licence ? Theme.texte2 : Theme.danger
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        visible: !!carte.modelData.declencheur
                        text: Theme.tx("Mot à mettre dans la description : ", "Word to put in the description: ") + (carte.modelData.declencheur || "")
                        color: Theme.texte2
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                    }
                    ListeDeroulante {
                        id: fichier
                        visible: carte.modelData.fichiers.length > 1 && !carte.fini
                        Layout.fillWidth: true
                        implicitHeight: 30
                        model: carte.modelData.fichiers.map(f => ({ valeur: f, texte: f }))
                        valeur: carte.modelData.fichiers[0]
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        BoutonPrincipal {
                            Layout.fillWidth: true
                            secondaire: carte.fini
                            enabled: !carte.fini && !carte.enCours
                            text: carte.fini ? Theme.tx("Téléchargé", "Downloaded")
                                  : carte.enCours ? (carte.suivi.total ? Math.round(100 * carte.suivi.fait / carte.suivi.total) + " %" : "…")
                                  : Theme.tx("Télécharger", "Download")
                            onClicked: fenetre.telecharger(carte.modelData, fichier.valeur || carte.modelData.fichiers[0])
                        }
                        BoutonDiscret {
                            icone: "details"
                            aide: Theme.tx("Voir sur Hugging Face", "View on Hugging Face")
                            onClicked: Qt.openUrlExternally(carte.modelData.page)
                        }
                    }
                }
            }
        }
    }
}
