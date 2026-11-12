// Prisme 2 : ecran principal en Qt Quick. Il parle au serveur de Prisme par son API locale (adresse), comme le
// telephone et Claude. Modeles et Reglages s'ouvrent dans leurs fenetres (FenetreModeles.qml, FenetreReglages.qml).
import QtCore
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Shapes

ApplicationWindow {
    id: fenetre
    required property string adresse

    width: 1180
    height: 820
    minimumWidth: 640
    minimumHeight: 520
    visible: true
    title: "Prisme"
    color: c.fond

    // Apparence choisie dans les Reglages et gardee sur cet ordinateur ; "auto" suit celle du systeme
    property string apparence: preferences.apparence
    // Couleurs, langue et appels a l'API : partages par tous les ecrans (Theme.qml)
    readonly property var c: Theme
    readonly property bool enLigne: Theme.enLigne
    function tx(fr, en) { return Theme.tx(fr, en) }
    function api(chemin, corps, reussite, echec) { Theme.api(chemin, corps, reussite, echec) }

    Settings {
        id: preferences
        category: "fenetre"
        property string apparence: "auto"
        // "fr", "en" ou "auto" (celle du systeme), comme le choix de la version web
        property string langue: "auto"
        // Bandeaux masques sur cet ordinateur : la version annoncee, et l'invitation a connecter Claude
        property string majMasquee: ""
        property bool claudeMasque: false
    }
    Binding { target: Theme; property: "apparence"; value: fenetre.apparence }
    Binding { target: Theme; property: "langue"; value: preferences.langue }
    Connections { target: Theme; function onMessage(texte, erreur) { fenetre.note(texte, erreur) } }

    // --- Etat de Prisme
    property var etat: ({})
    property bool occupe: etat.occupe === true
    property bool etaitOccupe: false
    property string format: "carre"
    property int nombre: 1
    // Image de depart : { galerie } pour une image du fil, { data } pour un fichier ou une image collee
    property var source: null
    property bool ameliorant: false
    property string texteOriginal: ""
    property string texteAmeliore: ""
    readonly property bool ameliorationPossible: !!(etat.amelioration && etat.amelioration.modele)
    readonly property var formats: ({ carre: [1024, 1024], paysage: [1280, 720], portrait: [720, 1280] })

    function note(texte, erreur) {
        bulleNote.texte = texte
        bulleNote.erreur = !!erreur
        bulleNote.visible = true
        minuteurNote.interval = erreur ? 7000 : 2600
        minuteurNote.restart()
    }

    // Toutes les images du dossier ; le fil n'en montre que celles qui correspondent a la recherche
    property var toutesImages: []
    property string recherche: ""

    function chargerImages(descendre) {
        api("/api/images", undefined, function (liste) {
            toutesImages = liste
            afficherImages()
            if (descendre) fil.positionViewAtBeginning()
        }, function (message) { note(message, true) })
    }

    function afficherImages() {
        const mots = recherche.trim().toLowerCase()
        images.clear()
        // Les plus recentes d'abord, comme le serveur les donne : le fil, range de bas en haut, les montre en bas
        for (const image of toutesImages) {
            if (mots && (image.prompt || "").toLowerCase().indexOf(mots) < 0)
                continue
            images.append({ nom: image.nom, prompt: image.prompt || "", largeur: image.largeur || 0, hauteur: image.hauteur || 0,
                            seed: image.seed === null || image.seed === undefined ? "" : String(image.seed) })
        }
    }

    // Claude Desktop ou Claude Code sur cet ordinateur, et Prisme y est-il branche ?
    property var claude: null
    readonly property var maj: etat.mise_a_jour || null
    readonly property var installationMaj: maj ? maj.installation : null
    readonly property bool majEnCours: !!installationMaj && ["telechargement", "installation", "redemarrage"].indexOf(installationMaj.phase) >= 0
    readonly property bool bandeauMaj: !!etat.maj_echec || (!!maj && (maj.version !== preferences.majMasquee || majEnCours))
    readonly property bool bandeauClaude: !!claude && (claude.desktop || claude.code) && !bandeauMaj && !preferences.claudeMasque
        && (!((!claude.desktop || claude.desktop_connecte) && (!claude.code || claude.code_connecte)) || claude.desktop_a_mettre_a_jour)
    property string erreurMajVue: ""

    function lireEtat() {
        api("/api/etat", undefined, function (e) {
            etat = e
            const installation = e.mise_a_jour ? e.mise_a_jour.installation : null
            if (installation && installation.phase === "erreur" && installation.erreur !== erreurMajVue) {
                erreurMajVue = installation.erreur
                note(installation.erreur, true)
            }
            if (etaitOccupe && !e.occupe) {
                chargerImages(true)
                if (e.phase === "erreur") note(tx("La création a échoué.\n", "The creation failed.\n") + (e.erreur || ""), true)
                else if (e.phase === "annule") note(tx("Création arrêtée", "Creation stopped"))
                else if ((e.resultats || []).length) note(tx("Image prête en ", "Image ready in ") + Math.round(e.ecoule || 0) + " s")
            }
            etaitOccupe = e.occupe === true
        })
    }

    function definirSource(s) {
        source = s
        if (s) format = "source"
        else if (format === "source") format = "carre"
        saisie.forceActiveFocus()
    }

    function lireFichier(adresse) {
        if (occupe) return
        const image = typeof fichiers !== "undefined" ? fichiers.lireImage(adresse) : null
        if (image) definirSource(image)
        else note(tx("Impossible de lire cette image.", "This image cannot be read."), true)
    }

    // Comme la version web : 1024 x 1024 pixels en tout, aux proportions de l'image de depart
    function tailleVoulue() {
        if (format === "source" && source && source.largeur && source.hauteur) {
            const e = Math.sqrt(1024 * 1024 / (source.largeur * source.hauteur))
            const arrondi = v => Math.min(2048, Math.max(256, Math.round(v * e / 16) * 16))
            return [arrondi(source.largeur), arrondi(source.hauteur)]
        }
        return formats[format] || formats.carre
    }

    function avecSource(corps) {
        if (source && source.galerie) corps.source_nom = source.galerie
        else if (source) corps.source_data = source.data
        return corps
    }

    function creer() {
        const texte = saisie.text.trim()
        if (occupe || ameliorant || !texte)
            return
        // Amelioration automatique (Reglages), sauf si le texte vient deja d'etre ameliore
        if (etat.amelioration && etat.amelioration.auto && ameliorationPossible && texte !== texteAmeliore)
            ameliorer(lancerCreation)
        else
            lancerCreation()
    }

    function lancerCreation() {
        const texte = saisie.text.trim()
        const taille = tailleVoulue()
        const corps = avecSource({ prompt: texte, largeur: taille[0], hauteur: taille[1], nombre: nombre })
        if (variante.text !== "") corps.seed = Number(variante.text)
        api("/api/generer", corps, function () {
            etat = Object.assign({}, etat, { occupe: true, phase: "chargement", etape: 0, prompt: texte,
                                             largeur: taille[0], hauteur: taille[1], nombre: nombre, index: 1 })
            etaitOccupe = true
            saisie.text = ""
            texteAmeliore = ""
            definirSource(null)
            fil.positionViewAtBeginning()
        }, function (message) { note(message, true) })
    }

    // Reecrit la description (ou, avec une image de depart, une consigne de modification) ; suite() ensuite
    function ameliorer(suite) {
        const texte = saisie.text.trim()
        if (!texte) {
            note(tx("Écris d'abord une description à améliorer.", "Write a description to enhance first."), true)
            return
        }
        ameliorant = true
        api("/api/ameliorer", avecSource({ prompt: texte }), function (r) {
            ameliorant = false
            texteOriginal = texte
            texteAmeliore = r.prompt
            saisie.text = r.prompt
            if (suite) suite()
        }, function (message) {
            ameliorant = false
            note(message, true)
            // Sans amelioration, la creation part avec la description telle quelle
            if (suite) suite()
        })
    }

    function avancement() {
        if (etat.phase === "dessin" || etat.phase === "agrandissement")
            return etat.total ? etat.etape / etat.total : 0
        return etat.phase === "finalisation" ? 1 : -1
    }

    function texteAvancement() {
        const lot = etat.nombre > 1 ? tx(" · image " + etat.index + " sur " + etat.nombre, " · image " + etat.index + " of " + etat.nombre) : ""
        if (etat.phase === "dessin")
            return tx("Étape " + etat.etape + " sur " + etat.total, "Step " + etat.etape + " of " + etat.total) + lot
        if (etat.phase === "agrandissement")
            return tx("Morceau " + etat.etape + " sur " + etat.total, "Part " + etat.etape + " of " + etat.total)
        if (etat.phase === "finalisation")
            return tx("Finalisation", "Finishing") + lot
        return tx("Chargement des modèles", "Loading the models") + lot
    }

    ListModel { id: images }

    Timer {
        interval: occupe || majEnCours ? 700 : 2500
        // Fenetre cachee : plus de nouvelles, pour que Prisme puisse s'arreter selon ses reglages
        running: Theme.adresse !== "" && fenetre.visible
        repeat: true
        triggeredOnStart: true
        onTriggered: lireEtat()
    }

    // Fermer la fenetre la cache (Prisme continue pour le telephone et Claude) et previent le serveur, comme la page web
    onClosing: api("/api/fermeture", {})

    Component.onCompleted: {
        Theme.adresse = adresse
        chargerImages(true)
        api("/api/claude", undefined, function (c) { claude = c }, function () {})
    }

    function connecterClaude() {
        api("/api/connecter-claude", { retirer: false }, function (r) {
            claude = r.claude
            const noms = r.faits.map(f => f === "desktop" ? "Claude Desktop" : "Claude Code").join(tx(" et ", " and "))
            if (r.faits.length)
                note(tx("Prisme est connecté à " + noms + ". Relance Claude, puis demande-lui de créer une image.",
                        "Prisme is connected to " + noms + ". Restart Claude, then ask it to create an image."))
            if (r.erreurs.length) note(r.erreurs.join("\n"), true)
        })
    }

    // --- En-tete
    header: Rectangle {
        height: 56
        color: c.fond
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 14
            spacing: 10
            Image {
                // Fichier local, a cote du dossier qml : le logo s'affiche meme avant que le serveur reponde
                source: "../logo.png"
                sourceSize: Qt.size(30, 30)
                Layout.preferredWidth: 30
                Layout.preferredHeight: 30
            }
            Text {
                text: "Prisme"
                color: c.texte
                font.pixelSize: 19
                font.weight: Font.DemiBold
            }
            Rectangle {
                visible: !!etat.modele
                radius: 999
                color: c.surface3
                implicitHeight: 24
                implicitWidth: badge.implicitWidth + 18
                Text {
                    id: badge
                    anchors.centerIn: parent
                    text: (etat.modele || "").split("/").pop().replace(/\.(gguf|safetensors)$/i, "")
                    color: c.texte2
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: !enLigne
                text: tx("Prisme ne répond pas", "Prisme is not responding")
                color: c.danger
                font.pixelSize: 13
            }
            Champ {
                implicitWidth: 230
                implicitHeight: 32
                placeholderText: tx("Rechercher dans mes images", "Search my images")
                onTextChanged: { recherche = text; afficherImages() }
            }
            BoutonDiscret { text: tx("Téléphone", "Phone"); onClicked: telephone.open() }
            BoutonDiscret { text: tx("Modèles", "Models"); onClicked: modeles.open() }
            BoutonDiscret { text: tx("Réglages", "Settings"); onClicked: reglages.open() }
            Text {
                text: etat.version ? "v" + etat.version : ""
                color: c.texte3
                font.pixelSize: 12
            }
        }
    }

    // --- Fil des images
    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // Nouvelle version (mise a jour en un clic, ou a telecharger), ou mise a jour echouee
        Bandeau {
            visible: bandeauMaj
            masquable: !majEnCours && !etat.maj_echec
            texte: etat.maj_echec ? etat.maj_echec.message + tx(" Télécharge la nouvelle version à la main.", " Download the new version by hand.")
                : !maj ? ""
                : installationMaj && installationMaj.phase === "telechargement"
                    ? tx("Téléchargement de Prisme ", "Downloading Prisme ") + maj.version + " : " + Math.floor(installationMaj.fait / Math.max(1, installationMaj.total) * 100) + " %"
                : installationMaj && installationMaj.phase === "installation" ? tx("Installation de la mise à jour…", "Installing the update…")
                : installationMaj && installationMaj.phase === "redemarrage" ? tx("Mise à jour vers Prisme ", "Updating to Prisme ") + maj.version + tx("… Prisme redémarre.", "… Prisme is restarting.")
                : "Prisme " + maj.version + tx(" est disponible.", " is available.") + (maj.raison ? " " + maj.raison : "")
            onMasquer: preferences.majMasquee = maj ? maj.version : ""
            BoutonPrincipal {
                visible: !!maj && maj.auto && !majEnCours && !etat.maj_echec
                text: tx("Mettre à jour", "Update")
                implicitHeight: 32
                onClicked: api("/api/mettre-a-jour", {}, lireEtat)
            }
            BoutonPrincipal {
                visible: (!!maj && !maj.auto) || !!etat.maj_echec
                secondaire: true
                text: tx("Télécharger", "Download")
                implicitHeight: 32
                onClicked: Qt.openUrlExternally(etat.maj_echec ? etat.maj_echec.url : maj.url)
            }
        }

        // Claude est sur cet ordinateur mais Prisme n'y est pas branche (ou a change de place)
        Bandeau {
            visible: bandeauClaude
            texte: claude && claude.desktop_a_mettre_a_jour ? tx("Prisme a changé de place : reconnecte-le à Claude.", "Prisme has moved: connect it to Claude again.")
                                                            : tx("Claude est installé : il peut créer des images avec Prisme.", "Claude is installed: it can create images with Prisme.")
            onMasquer: preferences.claudeMasque = true
            BoutonPrincipal { text: tx("Connecter à Claude", "Connect to Claude"); implicitHeight: 32; onClicked: connecterClaude() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 18
            Layout.rightMargin: 18
            visible: (etat.problemes || []).length > 0
            implicitHeight: probleme.implicitHeight + 20
            radius: 12
            color: c.surface
            border.color: c.bordure
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: modeles.open() }
            Text {
                id: probleme
                anchors.fill: parent
                anchors.margins: 10
                wrapMode: Text.WordWrap
                color: c.texte
                font.pixelSize: 13
                text: tx("Prisme n'est pas encore prêt : ", "Prisme is not ready yet: ") + (etat.problemes || []).join(" · ")
                      + tx(". Clique ici pour ouvrir les modèles.", ". Click here to open the models.")
            }
        }

        ListView {
            id: fil
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 26
            topMargin: 18
            bottomMargin: 18
            model: images
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            readonly property real largeurImage: Math.min(width - 72, 620)
            // Comme une messagerie : la plus recente en bas, sans calcul de defilement quand une image arrive
            verticalLayoutDirection: ListView.BottomToTop
            // La zone d'ecriture grandit (image de depart, texte long) : le bas du fil reste visible, sauf si l'on est remonte
            property bool enBas: true
            onMovementEnded: enBas = atYEnd
            onHeightChanged: if (enBas) positionViewAtBeginning()

            delegate: Column {
                id: message
                required property var model
                required property int index
                width: ListView.view.width
                spacing: 10

                // La demande, a droite comme dans une messagerie
                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 36
                    visible: !!message.model.prompt
                    width: Math.min(demande.implicitWidth + 28, fil.width * 0.62)
                    height: demande.implicitHeight + 20
                    radius: 16
                    color: c.bulle
                    Text {
                        id: demande
                        anchors.fill: parent
                        anchors.margins: 10
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        text: message.model.prompt
                        wrapMode: Text.WordWrap
                        color: c.texte
                        font.pixelSize: 14
                    }
                }

                // L'image de Prisme, a gauche
                ImageArrondie {
                    x: 36
                    // Une image en portrait ne depasse pas 560 px de haut ; une hauteur fixe (et non celle du fil) garde
                    // la taille des images stable quand la fenetre ou la zone d'ecriture change
                    readonly property real proportion: message.model.largeur ? message.model.hauteur / message.model.largeur : 1
                    width: Math.min(fil.largeurImage, 560 / proportion)
                    height: width * proportion
                    source: adresse + "/images/" + encodeURIComponent(message.model.nom)
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: visionneuse.ouvrir(message.model.nom)
                    }
                }

                Row {
                    x: 30
                    spacing: 2
                    BoutonDiscret {
                        text: tx("Modifier", "Edit")
                        enabled: !occupe
                        onClicked: definirSource({ galerie: message.model.nom, nom: message.model.nom,
                                                   url: adresse + "/images/" + encodeURIComponent(message.model.nom),
                                                   largeur: message.model.largeur, hauteur: message.model.hauteur })
                    }
                    BoutonDiscret {
                        text: tx("Réutiliser", "Reuse")
                        // La description et la variante : la meme image peut etre refaite en changeant un detail
                        onClicked: { saisie.text = message.model.prompt; variante.text = message.model.seed; saisie.forceActiveFocus() }
                    }
                    BoutonDiscret {
                        text: tx("Agrandir ×4", "Enlarge ×4")
                        enabled: !occupe
                        onClicked: api("/api/agrandir", { nom: message.model.nom }, function () {
                            etaitOccupe = true
                            lireEtat()
                            fil.positionViewAtBeginning()
                        }, function (m) { note(m, true) })
                    }
                    BoutonDiscret {
                        text: tx("Copier", "Copy")
                        onClicked: {
                            const fait = typeof fichiers !== "undefined" && fichiers.copierImage(adresse + "/images/" + encodeURIComponent(message.model.nom))
                            note(fait ? tx("Image copiée", "Image copied") : tx("Impossible de copier l'image.", "The image cannot be copied."), !fait)
                        }
                    }
                    BoutonDiscret {
                        text: tx("Enregistrer", "Save")
                        onClicked: { enregistrement.nom = message.model.nom; enregistrement.open() }
                    }
                    BoutonDiscret {
                        text: tx("Dans le dossier", "Show in folder")
                        onClicked: api("/api/dossier", { nom: message.model.nom }, null, function (m) { note(m, true) })
                    }
                    BoutonDiscret {
                        text: tx("Corbeille", "Trash")
                        onClicked: api("/api/supprimer", { nom: message.model.nom }, function () {
                            chargerImages(false)
                            note(tx("Image mise à la corbeille", "Image moved to the trash"))
                        }, function (m) { note(m, true) })
                    }
                }
            }

            // Creation en cours, en bas du fil (debut de la liste rangee de bas en haut)
            header: Column {
                width: fil.width
                visible: occupe
                height: occupe ? implicitHeight + 26 : 0
                // Une creation commence (ici, depuis le telephone ou Claude) : le fil descend pour la montrer
                onHeightChanged: if (occupe) fil.positionViewAtBeginning()
                topPadding: 26
                spacing: 10

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 36
                    visible: !!etat.prompt
                    width: Math.min(demandeEnCours.implicitWidth + 28, fil.width * 0.62)
                    height: demandeEnCours.implicitHeight + 20
                    radius: 16
                    color: c.bulle
                    Text {
                        id: demandeEnCours
                        anchors.fill: parent
                        anchors.margins: 10
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        text: etat.prompt || ""
                        wrapMode: Text.WordWrap
                        color: c.texte
                        font.pixelSize: 14
                    }
                }

                Rectangle {
                    x: 36
                    width: Math.min(fil.largeurImage, 420)
                    height: etat.largeur ? width * etat.hauteur / etat.largeur : width
                    radius: 14
                    color: c.surface
                    border.color: c.bordure

                    Item {
                        id: anneau
                        anchors.centerIn: parent
                        width: 76
                        height: 76
                        readonly property real part: avancement()
                        property real angle: 0
                        // Avancement inconnu (chargement des modeles) : l'arc tourne
                        NumberAnimation on angle { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: occupe && anneau.part < 0 }
                        Shape {
                            anchors.fill: parent
                            preferredRendererType: Shape.CurveRenderer
                            ShapePath {
                                strokeColor: c.surface3
                                strokeWidth: 6
                                fillColor: "transparent"
                                PathAngleArc { centerX: 38; centerY: 38; radiusX: 32; radiusY: 32; startAngle: 0; sweepAngle: 360 }
                            }
                            ShapePath {
                                strokeColor: c.accent
                                strokeWidth: 6
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                PathAngleArc {
                                    centerX: 38; centerY: 38; radiusX: 32; radiusY: 32
                                    startAngle: anneau.part < 0 ? anneau.angle : -90
                                    sweepAngle: anneau.part < 0 ? 90 : 360 * anneau.part
                                }
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: anneau.part >= 0
                            text: Math.round(anneau.part * 100) + "%"
                            color: c.texte
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }
                    Column {
                        anchors.top: anneau.bottom
                        anchors.topMargin: 14
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 2
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: texteAvancement()
                            color: c.texte
                            font.pixelSize: 14
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: Math.round(etat.ecoule || 0) + " s"
                            color: c.texte3
                            font.pixelSize: 12
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: images.count === 0 && !occupe
                text: recherche.trim() ? tx("Aucune image ne correspond à ta recherche.", "No image matches your search.")
                                       : tx("Décris l'image à créer, en bas.", "Describe the image to create, below.")
                color: c.texte3
                font.pixelSize: 15
            }
        }

        // --- Zone d'ecriture
        Rectangle {
            Layout.fillWidth: true
            Layout.maximumWidth: 860
            Layout.alignment: Qt.AlignHCenter
            Layout.leftMargin: 18
            Layout.rightMargin: 18
            Layout.bottomMargin: 18
            implicitHeight: zone.implicitHeight + 24
            radius: 22
            color: c.surface
            border.color: saisie.activeFocus ? c.accent : c.bordure

            ColumnLayout {
                id: zone
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    visible: !!source
                    Layout.fillWidth: true
                    spacing: 10
                    ImageArrondie {
                        Layout.preferredWidth: 52
                        Layout.preferredHeight: 52
                        rayon: 10
                        source: fenetre.source ? fenetre.source.url : ""
                    }
                    ColumnLayout {
                        spacing: 1
                        Layout.fillWidth: true
                        Text {
                            text: fenetre.source ? tx("Image de départ · ", "Starting image · ") + fenetre.source.nom : ""
                            color: c.texte
                            font.pixelSize: 13
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        Text {
                            text: fenetre.source ? fenetre.source.largeur + " × " + fenetre.source.hauteur : ""
                            color: c.texte3
                            font.pixelSize: 12
                        }
                    }
                    BoutonDiscret { text: tx("Retirer", "Remove"); onClicked: definirSource(null) }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(Math.max(saisie.implicitHeight, 44), 160)
                    TextArea {
                        id: saisie
                        placeholderText: source ? tx("Décris le changement à faire sur cette image…", "Describe the change to make to this image…")
                                                : tx("Décris ton image…", "Describe your image…")
                        enabled: !ameliorant
                        placeholderTextColor: c.texte3
                        color: c.texte
                        wrapMode: TextArea.Wrap
                        font.pixelSize: 15
                        background: null
                        focus: true
                        // Entree cree l'image ; Maj + Entree va a la ligne
                        Keys.onReturnPressed: function (evenement) {
                            if (evenement.modifiers & Qt.ShiftModifier) { evenement.accepted = false; return }
                            creer()
                        }
                        Keys.onEnterPressed: creer()
                        // Une image dans le presse-papiers devient l'image de depart ; sinon, collage du texte
                        Keys.onPressed: function (evenement) {
                            if (!evenement.matches(StandardKey.Paste) || occupe || typeof fichiers === "undefined")
                                return
                            const image = fichiers.collerImage()
                            if (image) {
                                definirSource(image)
                                note(tx("Image collée comme image de départ", "Image pasted as the starting image"))
                                evenement.accepted = true
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    BoutonDiscret {
                        text: tx("Image", "Image")
                        enabled: !occupe
                        ToolTip.visible: hovered
                        ToolTip.text: tx("Ajouter une image à modifier (tu peux aussi la glisser ou la coller ici)",
                                         "Add an image to edit (you can also drag or paste it here)")
                        onClicked: choixImage.open()
                    }
                    BoutonDiscret {
                        visible: ameliorationPossible
                        enabled: !ameliorant && !occupe && saisie.text.trim().length > 0
                        text: ameliorant ? (source ? tx("Analyse de l'image…", "Looking at the image…") : tx("Amélioration…", "Enhancing…"))
                                         : tx("Améliorer", "Enhance")
                        ToolTip.visible: hovered
                        ToolTip.text: tx("Réécrire la description en plus détaillé avec ", "Rewrite the description in more detail with ") + (etat.amelioration ? etat.amelioration.modele : "")
                        onClicked: ameliorer(null)
                    }
                    BoutonDiscret {
                        visible: texteAmeliore !== "" && saisie.text === texteAmeliore
                        text: tx("Rétablir", "Undo")
                        ToolTip.visible: hovered
                        ToolTip.text: tx("Revenir au texte que tu avais écrit", "Go back to the text you wrote")
                        onClicked: { saisie.text = texteOriginal; texteAmeliore = ""; saisie.forceActiveFocus() }
                    }

                    Rectangle { width: 1; height: 20; color: c.bordure; Layout.leftMargin: 4; Layout.rightMargin: 4 }

                    Repeater {
                        model: [["carre", tx("Carré", "Square")], ["paysage", tx("Paysage", "Landscape")], ["portrait", tx("Portrait", "Portrait")],
                                ["source", tx("Original", "Original")]]
                        delegate: Button {
                            id: choixFormat
                            required property var modelData
                            readonly property bool actif: format === modelData[0]
                            text: modelData[1]
                            // Original : les proportions de l'image de depart
                            visible: modelData[0] !== "source" || !!source
                            implicitHeight: 32
                            font.pixelSize: 13
                            onClicked: format = modelData[0]
                            contentItem: Text {
                                text: choixFormat.text
                                font: choixFormat.font
                                color: choixFormat.actif ? c.texte : c.texte2
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                radius: 999
                                color: choixFormat.actif ? c.surface3 : (choixFormat.hovered ? c.surface2 : "transparent")
                                border.color: choixFormat.actif ? c.bordure : "transparent"
                            }
                        }
                    }

                    Rectangle { width: 1; height: 20; color: c.bordure; Layout.leftMargin: 4; Layout.rightMargin: 4 }

                    BoutonDiscret { text: "−"; enabled: nombre > 1; onClicked: nombre-- }
                    Text {
                        text: nombre + " " + (nombre > 1 ? tx("images", "images") : tx("image", "image"))
                        color: c.texte2
                        font.pixelSize: 13
                    }
                    BoutonDiscret { text: "+"; enabled: nombre < 4; onClicked: nombre++ }

                    // Variante : vide = au hasard ; meme description et meme variante donnent la meme image
                    Champ {
                        id: variante
                        implicitWidth: 130
                        implicitHeight: 32
                        placeholderText: tx("Variante au hasard", "Random variant")
                        validator: RegularExpressionValidator { regularExpression: /\d{0,10}/ }
                        ToolTip.visible: hovered
                        ToolTip.text: tx("Même description et même numéro donnent la même image : pratique pour refaire une image en changeant un détail.",
                                         "The same description and number give the same image: handy to redo an image while changing a detail.")
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        id: boutonCreer
                        text: occupe ? tx("Arrêter", "Stop") : source ? tx("Modifier", "Edit")
                              : (nombre > 1 ? tx("Créer " + nombre + " images", "Create " + nombre + " images") : tx("Créer", "Create"))
                        enabled: occupe || (!ameliorant && saisie.text.trim().length > 0)
                        implicitHeight: 38
                        leftPadding: 20
                        rightPadding: 20
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        onClicked: occupe ? api("/api/annuler", {}) : creer()
                        contentItem: Text {
                            text: boutonCreer.text
                            font: boutonCreer.font
                            color: occupe ? c.danger : c.surAccent
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 999
                            color: occupe ? "transparent" : c.accent
                            border.color: occupe ? c.danger : "transparent"
                            opacity: boutonCreer.enabled ? (boutonCreer.down ? 0.85 : 1) : 0.4
                        }
                    }
                }
            }
        }
    }

    // --- Visionneuse plein ecran
    Popup {
        id: visionneuse
        property string nom: ""
        function ouvrir(n) { nom = n; open() }
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: fenetre.width
        height: fenetre.height
        modal: true
        padding: 28
        background: Rectangle { color: Qt.rgba(0, 0, 0, 0.82) }
        Image {
            anchors.fill: parent
            source: visionneuse.nom ? adresse + "/images/" + encodeURIComponent(visionneuse.nom) : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            sourceSize.width: 3000
        }
        MouseArea { anchors.fill: parent; onClicked: visionneuse.close() }
    }

    // --- Messages courts
    Rectangle {
        id: bulleNote
        property string texte: ""
        property bool erreur: false
        visible: false
        z: 10
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 12
        width: Math.min(texteNote.implicitWidth + 32, fenetre.width - 40)
        height: texteNote.implicitHeight + 18
        radius: 12
        color: c.surface
        border.color: erreur ? c.danger : c.bordure
        Text {
            id: texteNote
            anchors.centerIn: parent
            width: Math.min(implicitWidth, fenetre.width - 72)
            text: bulleNote.texte
            wrapMode: Text.WordWrap
            color: bulleNote.erreur ? c.danger : c.texte
            font.pixelSize: 13
        }
        Timer { id: minuteurNote; onTriggered: bulleNote.visible = false }
    }

    // --- Fenetres des modeles et des reglages
    FenetreModeles { id: modeles; objectName: "modeles"; onChangement: lireEtat() }
    FenetreReglages {
        id: reglages
        objectName: "reglages"
        onOuvrirModeles: { reglages.close(); modeles.open() }
        onEnregistre: lireEtat()
        onApparenceChoisie: function (choix) {
            fenetre.apparence = choix
            preferences.apparence = choix
        }
        onLangueChoisie: function (choix) { preferences.langue = choix }
    }

    // --- Image de depart : choisie ou glissee sur la fenetre
    FileDialog {
        id: choixImage
        title: tx("Image à modifier", "Image to edit")
        nameFilters: [tx("Images", "Images") + " (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff)"]
        onAccepted: lireFichier(selectedFile.toString())
    }
    DropArea {
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: function (depot) {
            if (depot.hasUrls) {
                lireFichier(depot.urls[0].toString())
                depot.accept()
            }
        }
    }

    FenetreTelephone { id: telephone; objectName: "telephone" }

    // --- Un appareil demande l'acces : le PC l'autorise en comparant le code
    property string demandeRepondue: ""
    readonly property var demandeAcces: (etat.demandes || []).find(d => d.id !== demandeRepondue) || null
    Demande {
        objectName: "demandeAcces"
        visible: !!demandeAcces
        titre: tx("Un appareil veut utiliser Prisme", "A device wants to use Prisme")
        onReponse: function (accepte) {
            const id = demandeAcces.id
            demandeRepondue = id
            api("/api/repondre-demande", { id: id, accepter: accepte }, function () {
                note(accepte ? tx("Appareil autorisé", "Device approved") : tx("Demande refusée", "Request refused"))
                lireEtat()
            })
        }
        Text {
            text: demandeAcces ? demandeAcces.appareil + " · " + demandeAcces.ip : ""
            color: Theme.texte2
            font.pixelSize: 13
            Layout.alignment: Qt.AlignHCenter
        }
        Text {
            text: demandeAcces ? demandeAcces.code : ""
            color: Theme.accent
            font.pixelSize: 40
            font.weight: Font.DemiBold
            font.letterSpacing: 10
            Layout.alignment: Qt.AlignHCenter
        }
        Text {
            text: tx("Autorise seulement si ce code est celui affiché sur ton appareil.", "Only approve if this code is the one shown on your device.")
            color: Theme.texte3
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }

    // --- Claude demande un telechargement : licence non commerciale, ou modele hors du catalogue de Prisme
    property string accordRepondu: ""
    readonly property var accord: (etat.consentements || []).find(d => d.id !== accordRepondu) || null
    Demande {
        objectName: "accordClaude"
        visible: !!accord
        titre: tx("Claude demande un téléchargement", "Claude is asking for a download")
        accepter: tx("Accepter et télécharger", "Accept and download")
        onReponse: function (accepte) {
            const id = accord.id
            accordRepondu = id
            api("/api/repondre-consentement", { id: id, accepter: accepte }, function () {
                note(accepte ? tx("Téléchargement accepté", "Download accepted") : tx("Demande refusée", "Request refused"))
                lireEtat()
                modeles.lire()
            })
        }
        Text {
            readonly property var d: accord ? accord.details : null
            text: !d ? "" : (accord.genre === "profil" ? Theme.enLangue(d.nom) : d.fichier.split("/").pop()) + " · " + Theme.taille(d.taille)
            color: Theme.texte
            font.pixelSize: 15
            font.weight: Font.DemiBold
            wrapMode: Text.WrapAnywhere
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: avertissement.implicitHeight + 20
            radius: 10
            color: Theme.surface2
            border.color: Theme.bordureForte
            Text {
                id: avertissement
                readonly property var d: accord ? accord.details : null
                x: 12
                y: 10
                width: parent.width - 24
                textFormat: Text.StyledText
                linkColor: Theme.accent
                onLinkActivated: lien => Qt.openUrlExternally(lien)
                text: !d ? "" : accord.genre === "profil"
                      ? tx("Ces modèles sont sous ", "These models are under the ") + "<a href=\"" + d.licence.url + "\">" + d.licence.nom + "</a> : "
                        + Theme.enLangue(d.licence.resume) + tx(" En acceptant, c'est toi qui acceptes cette licence.", " By accepting, you accept this license yourself.")
                      : tx("Attention : ce modèle ne fait pas partie de ceux proposés par Prisme. Ni sa licence ni son contenu ne sont vérifiés : vérifie sa page avant d'accepter, ",
                           "Warning: this model is not one of those offered by Prisme. Neither its license nor its content is checked: check its page before accepting, ")
                        + "<a href=\"" + d.url + "\">" + d.hote + "</a>."
                color: Theme.texte
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
        }
        Text {
            readonly property var d: accord ? accord.details : null
            text: !d ? "" : accord.genre === "profil" ? tx("Téléchargés depuis Hugging Face et vérifiés par leur empreinte.", "Downloaded from Hugging Face and checked against their checksum.")
                  : d.sha256 ? tx("Le fichier sera vérifié par l'empreinte annoncée par le site.", "The file will be checked against the checksum given by the site.")
                  : tx("Le site ne donne pas d'empreinte : seule la taille du fichier sera vérifiée.", "The site gives no checksum: only the file size will be checked.")
            color: Theme.texte3
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }

    // --- Enregistrer une image du fil ailleurs que dans le dossier de Prisme
    FileDialog {
        id: enregistrement
        property string nom: ""
        title: tx("Enregistrer l'image", "Save the image")
        fileMode: FileDialog.SaveFile
        // Propose le dossier Images, avec le nom de l'image
        currentFolder: StandardPaths.writableLocation(StandardPaths.PicturesLocation)
        selectedFile: currentFolder + "/" + nom
        nameFilters: ["PNG (*.png)"]
        onAccepted: {
            const fait = typeof fichiers !== "undefined" && fichiers.enregistrerImage(adresse + "/images/" + encodeURIComponent(nom), selectedFile.toString())
            note(fait ? tx("Image enregistrée", "Image saved") : tx("Impossible d'enregistrer l'image.", "The image cannot be saved."), !fait)
        }
    }
}
