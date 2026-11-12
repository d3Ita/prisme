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

    Settings { id: preferences; category: "fenetre"; property string apparence: "auto" }
    Binding { target: Theme; property: "apparence"; value: fenetre.apparence }
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

    function chargerImages(descendre) {
        api("/api/images", undefined, function (liste) {
            images.clear()
            // Les plus recentes d'abord, comme le serveur les donne : le fil, range de bas en haut, les montre en bas
            for (const image of liste)
                images.append({ nom: image.nom, prompt: image.prompt || "", largeur: image.largeur || 0, hauteur: image.hauteur || 0 })
            if (descendre) fil.positionViewAtBeginning()
        }, function (message) { note(message, true) })
    }

    function lireEtat() {
        api("/api/etat", undefined, function (e) {
            etat = e
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
        api("/api/generer", avecSource({ prompt: texte, largeur: taille[0], hauteur: taille[1], nombre: nombre }), function () {
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
        interval: occupe ? 700 : 2500
        running: Theme.adresse !== ""
        repeat: true
        triggeredOnStart: true
        onTriggered: lireEtat()
    }

    Component.onCompleted: {
        Theme.adresse = adresse
        chargerImages(true)
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
        spacing: 0

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
                    // Une image en portrait tient dans les trois quarts de la hauteur du fil
                    readonly property real proportion: message.model.largeur ? message.model.hauteur / message.model.largeur : 1
                    width: Math.min(fil.largeurImage, fil.height * 0.75 / proportion)
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
                        onClicked: { saisie.text = message.model.prompt; saisie.forceActiveFocus() }
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
                        text: tx("Dans le dossier", "Show in folder")
                        onClicked: api("/api/dossier", { nom: message.model.nom }, null, function (m) { note(m, true) })
                    }
                    BoutonDiscret {
                        text: tx("Corbeille", "Trash")
                        onClicked: api("/api/supprimer", { nom: message.model.nom }, function () {
                            images.remove(message.index)
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
                text: tx("Décris l'image à créer, en bas.", "Describe the image to create, below.")
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
}
