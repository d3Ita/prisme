// Prisme 2 : ecran principal en Qt Quick. Il parle au serveur de Prisme par son API locale (adresse), comme le
// telephone et Claude. Les modeles et les reglages restent pour l'instant dans la version web (bouton en haut).
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
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

    // Apparence : "auto" (celle du systeme), "clair" ou "sombre", comme dans la version web
    property string apparence: "auto"
    readonly property bool sombre: apparence === "sombre" || (apparence === "auto" && Qt.styleHints.colorScheme === Qt.ColorScheme.Dark)
    readonly property bool francais: Qt.locale().name.startsWith("fr")
    function tx(fr, en) { return francais ? fr : en }

    // Memes couleurs que la version web
    QtObject {
        id: c
        readonly property color fond: sombre ? "#1b1a18" : "#f6f4ef"
        readonly property color surface: sombre ? "#242320" : "#ffffff"
        readonly property color surface2: sombre ? "#2a2926" : "#fbfaf7"
        readonly property color surface3: sombre ? "#34322e" : "#efece5"
        readonly property color bordure: sombre ? "#383632" : "#e7e3da"
        readonly property color texte: sombre ? "#f1eee8" : "#1f2430"
        readonly property color texte2: sombre ? "#bdb8ae" : "#575d6b"
        readonly property color texte3: sombre ? "#8d887f" : "#858a95"
        readonly property color accent: sombre ? "#f07a5a" : "#2f5bea"
        readonly property color surAccent: sombre ? "#2a140d" : "#ffffff"
        readonly property color bulle: sombre ? "#3a2d27" : "#e8edfb"
        readonly property color danger: sombre ? "#f26b6b" : "#d64545"
        readonly property color fondImage: sombre ? "#1f1e1b" : "#ebe8e1"
    }

    // --- Etat de Prisme
    property var etat: ({})
    property bool occupe: etat.occupe === true
    property bool etaitOccupe: false
    property bool enLigne: true
    property string format: "carre"
    property int nombre: 1
    readonly property var formats: ({ carre: [1024, 1024], paysage: [1280, 720], portrait: [720, 1280] })

    function api(chemin, corps, reussite, echec) {
        const requete = new XMLHttpRequest()
        requete.onreadystatechange = function () {
            if (requete.readyState !== XMLHttpRequest.DONE)
                return
            let donnees = {}
            try { donnees = JSON.parse(requete.responseText || "{}") } catch (e) {}
            if (requete.status >= 200 && requete.status < 300) {
                enLigne = true
                if (reussite) reussite(donnees)
                return
            }
            if (!requete.status) enLigne = false
            const message = donnees.erreur || (requete.status ? tx("Erreur ", "Error ") + requete.status
                                                               : tx("Prisme ne répond pas.", "Prisme is not responding."))
            if (echec) echec(message)
        }
        requete.open(corps === undefined ? "GET" : "POST", adresse + chemin)
        if (corps === undefined) {
            requete.send()
        } else {
            requete.setRequestHeader("Content-Type", "application/json")
            requete.send(JSON.stringify(corps))
        }
    }

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
            // Le serveur donne les plus recentes d'abord ; le fil se lit de haut en bas, comme une conversation
            for (let i = liste.length - 1; i >= 0; i--) {
                const image = liste[i]
                images.append({ nom: image.nom, prompt: image.prompt || "", largeur: image.largeur || 0, hauteur: image.hauteur || 0 })
            }
            if (descendre) Qt.callLater(fil.positionViewAtEnd)
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

    function creer() {
        const texte = saisie.text.trim()
        if (occupe || !texte)
            return
        const taille = formats[format]
        api("/api/generer", { prompt: texte, largeur: taille[0], hauteur: taille[1], nombre: nombre }, function () {
            etat = Object.assign({}, etat, { occupe: true, phase: "chargement", etape: 0, prompt: texte,
                                             largeur: taille[0], hauteur: taille[1], nombre: nombre, index: 1 })
            etaitOccupe = true
            saisie.text = ""
            Qt.callLater(fil.positionViewAtEnd)
        }, function (message) { note(message, true) })
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
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: lireEtat()
    }

    Component.onCompleted: chargerImages(true)

    // --- Image aux coins arrondis
    component ImageArrondie: Item {
        id: cadre
        required property QtObject theme
        property alias source: image.source
        property real rayon: 14
        Rectangle { anchors.fill: parent; radius: cadre.rayon; color: cadre.theme.fondImage }
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

    component BoutonDiscret: Button {
        id: bouton
        required property QtObject theme
        flat: true
        implicitHeight: 30
        leftPadding: 10
        rightPadding: 10
        font.pixelSize: 13
        contentItem: Text {
            text: bouton.text
            font: bouton.font
            color: bouton.enabled ? (bouton.hovered ? bouton.theme.texte : bouton.theme.texte2) : bouton.theme.texte3
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: bouton.hovered ? bouton.theme.surface3 : "transparent"
        }
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
            BoutonDiscret {
                theme: c
                text: tx("Modèles et réglages", "Models and settings")
                ToolTip.visible: hovered
                ToolTip.text: tx("S'ouvrent dans la version web pour l'instant", "Open in the web version for now")
                onClicked: Qt.openUrlExternally(adresse)
            }
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
            Text {
                id: probleme
                anchors.fill: parent
                anchors.margins: 10
                wrapMode: Text.WordWrap
                color: c.texte
                font.pixelSize: 13
                text: tx("Prisme n'est pas encore prêt : ", "Prisme is not ready yet: ") + (etat.problemes || []).join(" · ")
                      + tx(". Ouvre « Modèles et réglages » en haut à droite.", ". Open “Models and settings” at the top right.")
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
            // Colle en bas comme une messagerie (nouvelle image, creation en cours), sauf si l'on est remonte lire le fil
            property bool collerEnBas: true
            onMovementEnded: collerEnBas = atYEnd
            onContentHeightChanged: if (collerEnBas) Qt.callLater(positionViewAtEnd)

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
                    theme: c
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
                        theme: c
                        text: tx("Réutiliser", "Reuse")
                        onClicked: { saisie.text = message.model.prompt; saisie.forceActiveFocus() }
                    }
                    BoutonDiscret {
                        theme: c
                        text: tx("Agrandir ×4", "Enlarge ×4")
                        enabled: !occupe
                        onClicked: api("/api/agrandir", { nom: message.model.nom }, function () {
                            etaitOccupe = true
                            lireEtat()
                            Qt.callLater(fil.positionViewAtEnd)
                        }, function (m) { note(m, true) })
                    }
                    BoutonDiscret {
                        theme: c
                        text: tx("Dans le dossier", "Show in folder")
                        onClicked: api("/api/dossier", { nom: message.model.nom }, null, function (m) { note(m, true) })
                    }
                    BoutonDiscret {
                        theme: c
                        text: tx("Corbeille", "Trash")
                        onClicked: api("/api/supprimer", { nom: message.model.nom }, function () {
                            images.remove(message.index)
                            note(tx("Image mise à la corbeille", "Image moved to the trash"))
                        }, function (m) { note(m, true) })
                    }
                }
            }

            // Creation en cours, a la suite du fil
            footer: Column {
                width: fil.width
                visible: occupe
                height: occupe ? implicitHeight + 26 : 0
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

                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(Math.max(saisie.implicitHeight, 44), 160)
                    TextArea {
                        id: saisie
                        placeholderText: tx("Décris ton image…", "Describe your image…")
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
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model: [["carre", tx("Carré", "Square")], ["paysage", tx("Paysage", "Landscape")], ["portrait", tx("Portrait", "Portrait")]]
                        delegate: Button {
                            id: choixFormat
                            required property var modelData
                            readonly property bool actif: format === modelData[0]
                            text: modelData[1]
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

                    BoutonDiscret { theme: c; text: "−"; enabled: nombre > 1; onClicked: nombre-- }
                    Text {
                        text: nombre + " " + (nombre > 1 ? tx("images", "images") : tx("image", "image"))
                        color: c.texte2
                        font.pixelSize: 13
                    }
                    BoutonDiscret { theme: c; text: "+"; enabled: nombre < 4; onClicked: nombre++ }

                    Item { Layout.fillWidth: true }

                    Button {
                        id: boutonCreer
                        text: occupe ? tx("Arrêter", "Stop") : (nombre > 1 ? tx("Créer " + nombre + " images", "Create " + nombre + " images") : tx("Créer", "Create"))
                        enabled: occupe || saisie.text.trim().length > 0
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
}
