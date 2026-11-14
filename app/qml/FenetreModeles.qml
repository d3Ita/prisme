// Fenetre des modeles : moteurs, profils par machine, et mode avance (chaque modele, a telecharger ou supprimer).
// Meme API et memes regles que la version web.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Modèles", "Models")
    sousTitre: descriptionMachine()

    property var infos: null
    property string profilChoisi: ""
    property bool avance: false
    // Profils dont la licence non commerciale a ete acceptee pendant cette visite
    property var licencesAcceptees: ({})
    readonly property var actifs: ["attente", "telechargement", "verification"]
    readonly property var profil: profilActuel()
    signal changement()

    onOpened: lire()

    function lire() {
        Theme.api("/api/modeles-conseilles", undefined, function (i) {
            const termines = infos ? i.modeles.filter(m => m.present && !infos.modeles.find(x => x.id === m.id).present) : []
            infos = i
            if (termines.length) {
                Theme.note(termines.length > 1 ? Theme.tx("Modèles installés et choisis dans les réglages", "Models installed and selected in the settings")
                                               : termines[0].titre + Theme.tx(" est installé", " is installed"))
                changement()
            }
        })
    }

    Timer {
        // Suivi des telechargements tant que la fenetre est ouverte
        interval: 1000
        repeat: true
        running: fenetre.opened && fenetre.enCours()
        onTriggered: fenetre.lire()
    }

    function enCours() {
        if (!infos) return false
        const moteurs = infos.moteurs || {}
        return infos.modeles.some(m => m.telechargement && actifs.indexOf(m.telechargement.phase) >= 0)
            || Object.keys(moteurs).some(n => moteurs[n].installation && ["telechargement", "extraction"].indexOf(moteurs[n].installation.phase) >= 0)
    }

    function descriptionMachine() {
        if (!infos || !infos.machine) return ""
        const m = infos.machine, go = o => Math.round(o / Math.pow(2, 30))
        const vive = m.memoire ? Theme.tx(go(m.memoire) + " Go de mémoire vive", go(m.memoire) + " GB of RAM") : ""
        const description = m.mac ? Theme.tx("Mac avec " + go(m.memoire) + " Go de mémoire unifiée", "Mac with " + go(m.memoire) + " GB of unified memory")
            : m.carte && m.carte.nom ? [m.carte.nom + (m.video ? " (" + go(m.video) + Theme.tx(" Go)", " GB)") : ""), vive].filter(Boolean).join(", ")
            : [Theme.tx("Pas de carte graphique dédiée détectée", "No dedicated graphics card found"), vive].filter(Boolean).join(", ")
        const suggere = infos.profils.find(p => p.id === infos.suggestion)
        return suggere ? description + Theme.tx(". Profil recommandé : ", ". Recommended profile: ") + Theme.enLangue(suggere.nom) + "."
                       : description + Theme.tx(". Prisme n'a pas pu tout lire : choisis le profil de ta machine.", ". Prisme couldn't read everything: choose your machine's profile.")
    }

    function profilsVisibles(categorie) {
        if (!infos) return []
        const mac = !!(infos.machine && infos.machine.mac)
        return infos.profils.filter(p => (p.cible.type === "tous" || (p.cible.type === "mac") === mac)
                                         && (categorie === "option" ? p.categorie === "option" : p.categorie !== "option"))
    }

    function profilActuel() {
        if (!infos) return null
        return infos.profils.find(p => p.id === profilChoisi) || infos.profils.find(p => p.id === infos.profil_actif)
            || infos.profils.find(p => p.id === infos.conseille) || infos.profils[0]
    }

    // --- Configuration libre : un fichier du dossier models pour chaque role, avec ou sans profil
    readonly property var roles: [
        { id: "image", nom: Theme.tx("Modèle de dessin", "Drawing model"), aide: Theme.tx("Fait l'image", "Makes the image") },
        { id: "texte", nom: Theme.tx("Modèle de texte", "Text model"), aide: Theme.tx("Comprend la description", "Understands the description") },
        { id: "edition", nom: Theme.tx("Vision", "Vision"), aide: Theme.tx("Lit l'image de départ (Qwen-Image)", "Reads the starting image (Qwen-Image)") },
        { id: "vae", nom: "VAE", aide: Theme.tx("Produit l'image finale", "Produces the final image") }
    ]

    function nomRole(id) {
        const role = roles.find(x => x.id === id)
        return role ? role.nom : id
    }

    // Fichiers installes dans models/ (catalogue et ajouts a la main), plus le fichier actuel s'il a disparu
    function fichiersInstalles(role) {
        if (!infos) return []
        const noms = infos.modeles.filter(m => m.present).map(m => m.fichier).concat(infos.autres.map(m => m.nom))
            .filter((n, i, t) => t.indexOf(n) === i).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))
        const actuel = infos.configuration ? infos.configuration[role] : ""
        const liste = noms.map(n => ({ valeur: n, texte: n }))
        if (actuel && noms.indexOf(actuel) < 0) liste.unshift({ valeur: actuel, texte: actuel + Theme.tx(" (introuvable)", " (missing)") })
        if (role === "edition" || !actuel) liste.unshift({ valeur: "", texte: role === "edition" ? Theme.tx("Aucune", "None") : "" })
        return liste
    }

    function choisir(role, nom) {
        Theme.api("/api/utiliser-modele", { nom: nom, role: role }, function () {
            Theme.note(nom ? nom + Theme.tx(" choisi : ", " selected: ") + nomRole(role).toLowerCase()
                           : Theme.tx("Vision retirée", "Vision removed"))
            lire()
            changement()
        }, function () { lire() })
    }

    function licenceManquante(p) {
        return p && p.licence_a_accepter && !licencesAcceptees[p.id] && p.modeles.some(m => !m.present && !m.licence.commercial)
    }

    function moteurTexteAInstaller() {
        const m = infos ? infos.moteurs : null, t = m ? m.texte : null
        return !!t && !t.installe && !(t.requiert && !m[t.requiert].installe)
            && !(t.installation && ["telechargement", "extraction"].indexOf(t.installation.phase) >= 0)
    }

    function suivi(id) {
        const m = infos ? infos.modeles.find(x => x.id === id) : null
        return m ? m.telechargement : null
    }

    function restant() {
        return profil ? profil.taille_restante + (moteurTexteAInstaller() ? infos.moteurs.texte.taille : 0) : 0
    }

    function telecharger(ids, licence) {
        let reste = ids.slice()
        const suivant = function () {
            if (!reste.length) { lire(); return }
            Theme.api("/api/telecharger-modele", { id: reste.shift(), licence_acceptee: !!licence }, suivant)
        }
        suivant()
    }

    function telechargerProfil() {
        if (moteurTexteAInstaller()) installerMoteur("texte")
        if (licenceManquante(profil)) return
        telecharger(profil.modeles.map(m => m.id), !!licencesAcceptees[profil.id])
    }

    function installerMoteur(nom) {
        Theme.api("/api/installer-moteur", { moteur: nom }, lire)
    }

    // --- Confirmation avant une suppression definitive
    Popup {
        id: confirmation
        property string fichier: ""
        property string nom: ""
        property real octets: 0
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(420, parent ? parent.width - 40 : 420)
        modal: true
        padding: 22
        background: Rectangle { radius: 18; color: Theme.surface; border.color: Theme.bordure }
        contentItem: ColumnLayout {
            spacing: 14
            Text {
                text: Theme.tx("Supprimer définitivement " + confirmation.nom + " (" + Theme.taille(confirmation.octets) + ") ?",
                               "Permanently delete " + confirmation.nom + " (" + Theme.taille(confirmation.octets) + ")?")
                color: Theme.texte
                font.pixelSize: 15
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Text {
                text: Theme.tx("Le fichier ne passe pas par la corbeille : il faudra le retélécharger pour s'en resservir.",
                               "The file does not go to the trash: you will need to download it again to use it.")
                color: Theme.texte2
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                BoutonPrincipal { secondaire: true; text: Theme.tx("Annuler", "Cancel"); onClicked: confirmation.close() }
                BoutonPrincipal {
                    text: Theme.tx("Supprimer", "Delete")
                    onClicked: {
                        const nom = confirmation.nom
                        confirmation.close()
                        Theme.api("/api/supprimer-modele", { nom: confirmation.fichier }, function (r) {
                            Theme.note(nom + Theme.tx(" supprimé : ", " deleted: ") + Theme.taille(r.libere) + Theme.tx(" libérés", " freed"))
                            fenetre.lire()
                            fenetre.changement()
                        })
                    }
                }
            }
        }
    }

    function supprimer(fichier, nom, octets) {
        confirmation.fichier = fichier
        confirmation.nom = nom
        confirmation.octets = octets
        confirmation.open()
    }

    // --- Moteurs
    Section {
        titre: Theme.tx("Moteurs", "Engines")
        description: Theme.tx("Programmes officiels qui font les calculs, téléchargés une seule fois", "Official programs that do the work, downloaded once")
        Repeater {
            model: fenetre.infos ? ["image", "texte"].filter(n => fenetre.infos.moteurs[n]) : []
            delegate: ColumnLayout {
                id: moteur
                required property string modelData
                readonly property var info: fenetre.infos.moteurs[modelData]
                readonly property var installation: info.installation
                readonly property bool actif: !!installation && ["telechargement", "extraction"].indexOf(installation.phase) >= 0
                Layout.fillWidth: true
                spacing: 6
                Ligne {
                    nom: (moteur.modelData === "image" ? Theme.tx("Moteur d'images", "Image engine") : Theme.tx("Moteur de texte (Améliorer)", "Text engine (Improve)"))
                         + " · " + moteur.info.nom + " " + moteur.info.version
                    aide: Theme.tx("Version officielle ", "Official version ") + moteur.info.acceleration + " · " + Theme.taille(moteur.info.taille)
                    Text {
                        visible: moteur.info.installe
                        text: "✓ " + Theme.tx("Installé", "Installed")
                        color: Theme.succes
                        font.pixelSize: 13
                    }
                    BoutonPrincipal {
                        visible: !moteur.info.installe && !moteur.actif
                        enabled: !(moteur.info.requiert && !fenetre.infos.moteurs[moteur.info.requiert].installe)
                        text: Theme.tx("Installer", "Install")
                        onClicked: fenetre.installerMoteur(moteur.modelData)
                    }
                }
                BarreProgression {
                    visible: moteur.actif
                    Layout.fillWidth: true
                    part: moteur.installation && moteur.installation.total ? moteur.installation.fait / moteur.installation.total : 0
                }
                Text {
                    visible: moteur.actif || (!!moteur.installation && moteur.installation.phase === "erreur")
                    text: !moteur.installation ? "" : moteur.installation.phase === "erreur" ? moteur.installation.erreur
                          : moteur.installation.phase === "extraction" ? Theme.tx("Installation…", "Installing…")
                          : Theme.taille(moteur.installation.fait) + Theme.tx(" sur ", " of ") + Theme.taille(moteur.installation.total)
                    color: moteur.installation && moteur.installation.phase === "erreur" ? Theme.danger : Theme.texte2
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    // --- Configuration utilisee maintenant : celle d'un profil, ou choisie fichier par fichier
    Section {
        id: configuration
        readonly property var actif: fenetre.infos ? fenetre.infos.profils.find(p => p.id === fenetre.infos.profil_actif) || null : null
        visible: !!fenetre.infos && !!fenetre.infos.configuration
        titre: Theme.tx("Ta configuration", "Your setup")
        description: configuration.actif ? Theme.tx("Celle du profil ", "The one from the ") + Theme.enLangue(configuration.actif.nom)
                                           + Theme.tx(". Change un modèle ici, ou choisis un autre profil plus bas.", " profile. Change a model here, or pick another profile below.")
                     : Theme.tx("Choisie modèle par modèle. Change un modèle ici, ou choisis un profil plus bas.", "Chosen model by model. Change a model here, or pick a profile below.")
        liens: [
            Rectangle {
                radius: 999
                height: 22
                width: etiquette.implicitWidth + 16
                color: configuration.actif ? Theme.surface3 : Theme.accentDoux
                Text {
                    id: etiquette
                    anchors.centerIn: parent
                    text: configuration.actif ? Theme.tx("Profil", "Profile") : Theme.tx("Personnalisée", "Custom")
                    font.pixelSize: 11
                    color: configuration.actif ? Theme.texte2 : Theme.accent
                }
            }
        ]
        Repeater {
            model: fenetre.roles
            delegate: Ligne {
                id: ligneRole
                required property var modelData
                nom: modelData.nom
                aide: modelData.aide
                ListeDeroulante {
                    id: liste
                    objectName: "configuration-" + ligneRole.modelData.id
                    model: fenetre.fichiersInstalles(ligneRole.modelData.id)
                    valeur: fenetre.infos && fenetre.infos.configuration ? fenetre.infos.configuration[ligneRole.modelData.id] : ""
                    onActivated: {
                        const choix = currentValue
                        if (fenetre.infos && choix !== fenetre.infos.configuration[ligneRole.modelData.id]) fenetre.choisir(ligneRole.modelData.id, choix)
                        // La liste suit toujours la configuration lue sur le serveur, meme si le choix est refuse
                        Qt.callLater(function () { liste.valeur = Qt.binding(function () { return fenetre.infos && fenetre.infos.configuration ? fenetre.infos.configuration[ligneRole.modelData.id] : "" }) })
                    }
                }
            }
        }
    }

    // --- Profils
    component CarteProfil: Rectangle {
        id: carte
        required property var modelData
        required property var panneau
        readonly property bool choisi: !!carte.panneau.profil && carte.panneau.profil.id === modelData.id
        width: 214
        height: contenuCarte.implicitHeight + 24
        radius: 14
        color: choisi ? Theme.accentDoux : Theme.surface2
        border.color: choisi ? Theme.accent : Theme.bordure
        border.width: choisi ? 2 : 1
        Column {
            id: contenuCarte
            x: 12
            y: 12
            width: parent.width - 24
            spacing: 4
            Text { text: Theme.enLangue(carte.modelData.nom); color: Theme.texte; font.pixelSize: 14; font.weight: Font.DemiBold; width: parent.width; wrapMode: Text.WordWrap }
            Text { text: Theme.enLangue(carte.modelData.materiel); color: Theme.texte2; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap }
            Text {
                text: carte.modelData.installe ? Theme.tx("Déjà téléchargé", "Already downloaded") : Theme.taille(carte.modelData.taille_totale)
                color: Theme.texte3
                font.pixelSize: 12
            }
            Flow {
                width: parent.width
                spacing: 4
                topPadding: 2
                Repeater {
                    model: [
                        [carte.modelData.id === carte.panneau.infos.suggestion, Theme.tx("Recommandé pour ta machine", "Recommended for your machine"), "accent"],
                        [carte.modelData.actif, Theme.tx("Utilisé", "In use"), "succes"],
                        [carte.modelData.statut === "experimental", Theme.tx("Expérimental", "Experimental"), ""],
                        [!carte.modelData.edition, Theme.tx("Sans modification d'image", "No image editing"), ""],
                        [carte.modelData.licence_a_accepter, Theme.tx("Non commercial", "Non-commercial"), ""]
                    ].filter(p => p[0])
                    delegate: Rectangle {
                        required property var modelData
                        radius: 999
                        height: 20
                        width: pastille.implicitWidth + 14
                        color: modelData[2] === "accent" ? Theme.accentDoux : Theme.surface3
                        Text {
                            id: pastille
                            anchors.centerIn: parent
                            text: parent.modelData[1]
                            font.pixelSize: 11
                            color: parent.modelData[2] === "accent" ? Theme.accent : parent.modelData[2] === "succes" ? Theme.succes : Theme.texte2
                        }
                    }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: carte.panneau.profilChoisi = carte.modelData.id
        }
    }

    Section {
        titre: Theme.tx("Choisis ta machine", "Choose your machine")
        Flow {
            Layout.fillWidth: true
            spacing: 10
            Repeater { model: fenetre.profilsVisibles("principal"); delegate: CarteProfil { panneau: fenetre } }
        }
    }

    Section {
        titre: Theme.tx("Autres choix", "Other choices")
        visible: fenetre.profilsVisibles("option").length > 0
        Flow {
            Layout.fillWidth: true
            spacing: 10
            Repeater { model: fenetre.profilsVisibles("option"); delegate: CarteProfil { panneau: fenetre } }
        }
    }

    // --- Resume du profil choisi
    Rectangle {
        visible: !!fenetre.profil
        Layout.fillWidth: true
        implicitHeight: resume.implicitHeight + 28
        radius: 14
        color: Theme.surface2
        border.color: Theme.bordure
        ColumnLayout {
            id: resume
            x: 14
            y: 14
            width: parent.width - 28
            spacing: 6
            readonly property var p: fenetre.profil
            Text {
                text: resume.p ? "<b>" + Theme.enLangue(resume.p.nom) + "</b> · " + Theme.enLangue(resume.p.description) : ""
                textFormat: Text.StyledText
                color: Theme.texte
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Text {
                text: resume.p ? Theme.tx("Modèles : ", "Models: ") + resume.p.modeles.map(m => m.quantification ? m.nom + " " + m.quantification : m.nom).join(", ") : ""
                color: Theme.texte2; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Text {
                text: resume.p ? Theme.tx("Vitesse : ", "Speed: ") + Theme.enLangue(resume.p.vitesse) : ""
                color: Theme.texte2; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Text {
                readonly property var licences: resume.p ? resume.p.modeles.map(m => m.licence).filter((l, i, t) => t.findIndex(x => x.nom === l.nom) === i) : []
                text: Theme.tx("Licences : ", "Licenses: ") + licences.map(l => "<a href=\"" + l.url + "\">" + l.nom + "</a>"
                      + (l.commercial ? "" : Theme.tx(" (usage non commercial)", " (non-commercial use)"))).join(", ")
                textFormat: Text.StyledText
                linkColor: Theme.accent
                onLinkActivated: lien => Qt.openUrlExternally(lien)
                color: Theme.texte2; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Text {
                readonly property real reste: fenetre.restant()
                visible: reste > 0
                text: Theme.tx("À télécharger : ", "To download: ") + Theme.taille(reste)
                      + (fenetre.moteurTexteAInstaller() ? Theme.tx(" (moteur de texte compris)", " (text engine included)") : "")
                      + (fenetre.infos ? " · " + Theme.taille(fenetre.infos.libre) + Theme.tx(" libres sur le disque", " free on disk") : "")
                color: Theme.texte2; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Text {
                readonly property real manque: fenetre.infos ? fenetre.restant() + 200 * Math.pow(2, 20) - fenetre.infos.libre : 0
                visible: fenetre.restant() > 0 && manque > 0
                text: Theme.tx("Pas assez de place : libère au moins ", "Not enough space: free at least ") + Theme.taille(manque) + Theme.tx(" sur le disque.", " on the disk.")
                color: Theme.danger; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            // Licence non commerciale : l'utilisateur l'accepte lui-meme avant le telechargement
            RowLayout {
                visible: !!resume.p && resume.p.licence_a_accepter && resume.p.modeles.some(m => !m.present && !m.licence.commercial)
                Layout.fillWidth: true
                CheckBox {
                    id: coche
                    checked: !!resume.p && !!fenetre.licencesAcceptees[resume.p.id]
                    onToggled: {
                        const acceptees = Object.assign({}, fenetre.licencesAcceptees)
                        acceptees[resume.p.id] = checked
                        fenetre.licencesAcceptees = acceptees
                    }
                }
                Text {
                    readonly property var licence: resume.p ? (resume.p.modeles.find(m => !m.licence.commercial) || {}).licence : null
                    text: licence ? Theme.tx("J'accepte la ", "I accept the ") + "<a href=\"" + licence.url + "\">" + licence.nom + "</a> : " + Theme.enLangue(licence.resume) : ""
                    textFormat: Text.StyledText
                    linkColor: Theme.accent
                    onLinkActivated: lien => Qt.openUrlExternally(lien)
                    color: Theme.texte; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
                }
            }
            // Avancement de l'ensemble du profil
            ColumnLayout {
                readonly property var suivis: resume.p ? resume.p.modeles.filter(m => !m.present).map(m => fenetre.suivi(m.id)).filter(t => t && fenetre.actifs.indexOf(t.phase) >= 0) : []
                readonly property real fait: suivis.reduce((total, t) => total + t.fait, 0)
                visible: suivis.length > 0
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: Theme.tx("Téléchargement : ", "Downloading: ") + Theme.taille(parent.fait) + Theme.tx(" sur ", " of ") + Theme.taille(resume.p ? resume.p.taille_restante : 0)
                    color: Theme.texte2; font.pixelSize: 13
                }
                BarreProgression { Layout.fillWidth: true; part: resume.p ? parent.fait / Math.max(1, resume.p.taille_restante) : 0 }
            }
            Text {
                visible: !!resume.p && fenetre.restant() === 0
                text: resume.p && resume.p.actif ? Theme.tx("Ce profil est utilisé dans les réglages.", "This profile is used in the settings.")
                      : Theme.tx("Tout est téléchargé : « Utiliser ce profil » le choisit dans les réglages.", "Everything is downloaded: \"Use this profile\" selects it in the settings.")
                color: Theme.texte2; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            // Une configuration choisie a la main n'est pas remplacee sans le dire
            Text {
                visible: !!resume.p && !resume.p.actif && !!fenetre.infos && !fenetre.infos.profil_actif
                text: Theme.tx("Ta configuration personnalisée sera remplacée par celle de ce profil. Tes fichiers restent dans le dossier models.",
                               "Your custom setup will be replaced by this profile's. Your files stay in the models folder.")
                color: Theme.texte; font.pixelSize: 13; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
        }
    }

    // --- Mode avance : chaque modele du catalogue, puis les fichiers ajoutes a la main
    BoutonDiscret {
        text: fenetre.avance ? Theme.tx("Masquer le mode avancé", "Hide advanced mode")
                             : Theme.tx("Choisir ou supprimer les modèles un par un (mode avancé)", "Choose or delete models one by one (advanced mode)")
        onClicked: fenetre.avance = !fenetre.avance
    }

    Repeater {
        model: fenetre.avance && fenetre.infos ? fenetre.infos.modeles.map(m => m.role).filter((r, i, t) => t.indexOf(r) === i) : []
        delegate: Section {
            id: role
            required property string modelData
            titre: modelData
            Repeater {
                model: fenetre.infos.modeles.filter(m => m.role === role.modelData)
                delegate: ColumnLayout {
                    id: ligneModele
                    required property var modelData
                    readonly property var t: modelData.telechargement
                    readonly property bool actif: !!t && fenetre.actifs.indexOf(t.phase) >= 0
                    Layout.fillWidth: true
                    spacing: 4
                    Ligne {
                        nom: ligneModele.modelData.titre
                        aide: (Theme.francais ? ligneModele.modelData.detail : ligneModele.modelData.detail_en) + " · " + Theme.taille(ligneModele.modelData.taille)
                        Row {
                            spacing: 6
                            Text {
                                visible: ligneModele.modelData.present
                                anchors.verticalCenter: parent.verticalCenter
                                text: "✓ " + (ligneModele.modelData.utilise ? Theme.tx("Utilisé", "In use") : Theme.tx("Installé", "Installed"))
                                color: Theme.succes
                                font.pixelSize: 13
                            }
                            BoutonPrincipal {
                                visible: ligneModele.modelData.present && !ligneModele.modelData.utilise
                                secondaire: true
                                text: Theme.tx("Utiliser", "Use")
                                onClicked: fenetre.choisir(ligneModele.modelData.role_id, ligneModele.modelData.fichier)
                            }
                            BoutonDiscret {
                                visible: ligneModele.modelData.present
                                danger: true
                                text: Theme.tx("Supprimer", "Delete")
                                onClicked: fenetre.supprimer(ligneModele.modelData.fichier, ligneModele.modelData.titre, ligneModele.modelData.taille)
                            }
                            BoutonPrincipal {
                                visible: !ligneModele.modelData.present && ligneModele.actif
                                secondaire: true
                                text: Theme.tx("Arrêter", "Stop")
                                onClicked: Theme.api("/api/annuler-modele", { id: ligneModele.modelData.id }, fenetre.lire)
                            }
                            BoutonPrincipal {
                                visible: !ligneModele.modelData.present && !ligneModele.actif
                                secondaire: !ligneModele.modelData.conseille
                                text: ligneModele.modelData.reprise ? Theme.tx("Reprendre", "Resume") : Theme.tx("Télécharger", "Download")
                                onClicked: fenetre.telecharger([ligneModele.modelData.id], ligneModele.modelData.licence && ligneModele.modelData.licence.commercial === false)
                            }
                        }
                    }
                    BarreProgression {
                        visible: !!ligneModele.t && ligneModele.t.phase === "telechargement"
                        Layout.fillWidth: true
                        part: ligneModele.t && ligneModele.t.total ? ligneModele.t.fait / ligneModele.t.total : 0
                    }
                    Text {
                        visible: !ligneModele.modelData.present && !!ligneModele.t && ligneModele.t.phase !== "termine"
                        text: !ligneModele.t ? "" : ligneModele.t.phase === "attente" ? Theme.tx("En attente…", "Waiting…")
                              : ligneModele.t.phase === "verification" ? Theme.tx("Vérification du fichier…", "Checking the file…")
                              : ligneModele.t.phase === "telechargement" ? Theme.taille(ligneModele.t.fait) + Theme.tx(" sur ", " of ") + Theme.taille(ligneModele.t.total)
                              : ligneModele.t.phase === "annule" ? Theme.tx("Arrêté : tu peux reprendre où le téléchargement s'était arrêté.", "Stopped: you can resume where the download stopped.")
                              : (ligneModele.t.erreur || "")
                        color: ligneModele.t && ligneModele.t.phase === "erreur" ? Theme.danger : Theme.texte2
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    Section {
        visible: fenetre.avance && !!fenetre.infos && fenetre.infos.autres.length > 0
        titre: Theme.tx("Autres fichiers du dossier models", "Other files in the models folder")
        description: Theme.tx("Ajoutés à la main ou hors du catalogue de Prisme", "Added by hand or outside Prisme's catalog")
        Repeater {
            model: fenetre.infos ? fenetre.infos.autres : []
            delegate: Ligne {
                id: autre
                required property var modelData
                nom: modelData.nom
                aide: Theme.taille(modelData.taille)
                      + (modelData.roles.length ? " · " + Theme.tx("Utilisé : ", "In use: ") + modelData.roles.map(r => fenetre.nomRole(r).toLowerCase()).join(", ") : "")
                Row {
                    spacing: 6
                    ListeDeroulante {
                        id: roleChoisi
                        objectName: "utiliser-comme"
                        implicitWidth: 190
                        model: [{ valeur: "", texte: Theme.tx("Utiliser comme…", "Use as…") }]
                               .concat(fenetre.roles.filter(r => autre.modelData.roles.indexOf(r.id) < 0).map(r => ({ valeur: r.id, texte: r.nom })))
                        onActivated: {
                            const role = currentValue
                            Qt.callLater(function () { roleChoisi.valeur = ""; roleChoisi.currentIndex = 0 })
                            if (role) fenetre.choisir(role, autre.modelData.nom)
                        }
                    }
                    BoutonDiscret {
                        anchors.verticalCenter: parent.verticalCenter
                        danger: true
                        text: Theme.tx("Supprimer", "Delete")
                        onClicked: fenetre.supprimer(autre.modelData.nom, autre.modelData.nom, autre.modelData.taille)
                    }
                }
            }
        }
    }

    Item { implicitHeight: 4 }

    boutons: [
        BoutonDiscret {
            text: Theme.tx("Ouvrir le dossier", "Open the folder")
            onClicked: Theme.api("/api/dossier-modeles", {})
        },
        Item { Layout.fillWidth: true },
        BoutonPrincipal {
            readonly property real reste: fenetre.restant()
            visible: !!fenetre.profil && (reste > 0 || !fenetre.profil.actif)
            text: reste > 0 ? Theme.tx("Télécharger ce profil · ", "Download this profile · ") + Theme.taille(reste) : Theme.tx("Utiliser ce profil", "Use this profile")
            enabled: !!fenetre.profil && !fenetre.licenceManquante(fenetre.profil)
                     && !(reste > 0 && fenetre.infos && fenetre.infos.libre < reste + 200 * Math.pow(2, 20))
            onClicked: fenetre.telechargerProfil()
        }
    ]
}
