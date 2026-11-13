// Petite icone au trait, dessinee par Qt (pas de fichier image) : meme epaisseur et memes bouts arrondis partout,
// dans la couleur du texte, en clair comme en sombre. Chemins sur une grille de 24 x 24.
import QtQuick
import QtQuick.Shapes

Item {
    id: icone
    property string nom: ""
    property color couleur: Theme.texte2
    property real taille: 18
    implicitWidth: taille
    implicitHeight: taille

    readonly property var chemins: ({
        // Actions sur une image
        modifier: "M4 20 h4 L18.5 9.5 a2.12 2.12 0 0 0 -3 -3 L5 17 v3 z M13.5 8.5 l3 3",
        reutiliser: "M3 12 a9 9 0 1 0 9 -9 a9.75 9.75 0 0 0 -6.74 2.74 L3 8 M3 3 v5 h5",
        details: "M12 3 a9 9 0 1 1 0 18 a9 9 0 1 1 0 -18 M12 11 v5 M12 7.6 v0.01",
        agrandir: "M15 3 h6 v6 M9 21 H3 v-6 M21 3 l-7 7 M3 21 l7 -7",
        copier: "M11 9 h8 a2 2 0 0 1 2 2 v8 a2 2 0 0 1 -2 2 h-8 a2 2 0 0 1 -2 -2 v-8 a2 2 0 0 1 2 -2 z M5 15 a2 2 0 0 1 -2 -2 V5 a2 2 0 0 1 2 -2 h8 a2 2 0 0 1 2 2",
        enregistrer: "M12 4 v11 M7 10 l5 5 l5 -5 M5 20 h14",
        dossier: "M3 7 a2 2 0 0 1 2 -2 h4 l2 2 h8 a2 2 0 0 1 2 2 v8 a2 2 0 0 1 -2 2 H5 a2 2 0 0 1 -2 -2 z",
        corbeille: "M4 7 h16 M10 11 v6 M14 11 v6 M6 7 l1 12 a2 2 0 0 0 2 2 h6 a2 2 0 0 0 2 -2 l1 -12 M9 7 V4 h6 v3",
        // Zone d'ecriture
        image: "M5 4 h14 a2 2 0 0 1 2 2 v12 a2 2 0 0 1 -2 2 H5 a2 2 0 0 1 -2 -2 V6 a2 2 0 0 1 2 -2 z M9 7.5 a1.5 1.5 0 1 1 0 3 a1.5 1.5 0 1 1 0 -3 M21 15 l-5 -5 L5 20",
        ameliorer: "M11 3 l1.6 4.4 L17 9 l-4.4 1.6 L11 15 l-1.6 -4.4 L5 9 l4.4 -1.6 z M18.5 14 l0.8 2.2 l2.2 0.8 l-2.2 0.8 l-0.8 2.2 l-0.8 -2.2 l-2.2 -0.8 l2.2 -0.8 z",
        retablir: "M9 14 L4 9 l5 -5 M4 9 h10.5 a5.5 5.5 0 0 1 0 11 H11",
        lora: "M12 3 l9 4.5 l-9 4.5 l-9 -4.5 z M3 12 l9 4.5 l9 -4.5 M3 16.5 l9 4.5 l9 -4.5",
        comparer: "M5 4 h4 a1 1 0 0 1 1 1 v14 a1 1 0 0 1 -1 1 H5 a1 1 0 0 1 -1 -1 V5 a1 1 0 0 1 1 -1 z M15 4 h4 a1 1 0 0 1 1 1 v14 a1 1 0 0 1 -1 1 h-4 a1 1 0 0 1 -1 -1 V5 a1 1 0 0 1 1 -1 z",
        carre: "M7 5 h10 a2 2 0 0 1 2 2 v10 a2 2 0 0 1 -2 2 H7 a2 2 0 0 1 -2 -2 V7 a2 2 0 0 1 2 -2 z",
        paysage: "M4 7 h16 a1.5 1.5 0 0 1 1.5 1.5 v7 a1.5 1.5 0 0 1 -1.5 1.5 H4 a1.5 1.5 0 0 1 -1.5 -1.5 v-7 A1.5 1.5 0 0 1 4 7 z",
        portrait: "M8.5 2.5 h7 A1.5 1.5 0 0 1 17 4 v16 a1.5 1.5 0 0 1 -1.5 1.5 h-7 A1.5 1.5 0 0 1 7 20 V4 a1.5 1.5 0 0 1 1.5 -1.5 z",
        recadrer: "M6 2 v14 a2 2 0 0 0 2 2 h14 M18 22 V8 a2 2 0 0 0 -2 -2 H2",
        historique: "M3 12 a9 9 0 1 0 9 -9 a9.75 9.75 0 0 0 -6.74 2.74 L3 8 M3 3 v5 h5 M12 7.5 V12 l3 2",
        moins: "M6 12 h12",
        plus: "M12 6 v12 M6 12 h12",
        // En-tete et fenetres
        telephone: "M8 2.5 h8 a2 2 0 0 1 2 2 v15 a2 2 0 0 1 -2 2 H8 a2 2 0 0 1 -2 -2 v-15 a2 2 0 0 1 2 -2 z M11 18 h2",
        modeles: "M12 2.5 l8.5 4.75 v9.5 L12 21.5 l-8.5 -4.75 v-9.5 z M3.5 7.25 L12 12 l8.5 -4.75 M12 12 v9.5",
        reglages: "M4 6 h9 M17 6 h3 M4 12 h3 M11 12 h9 M4 18 h11 M19 18 h1 M15 4 a2 2 0 1 1 0 4 a2 2 0 1 1 0 -4 M9 10 a2 2 0 1 1 0 4 a2 2 0 1 1 0 -4 M17 16 a2 2 0 1 1 0 4 a2 2 0 1 1 0 -4",
        fermer: "M6 6 l12 12 M18 6 L6 18",
        chevron: "M6 9 l6 6 l6 -6",
        recherche: "M11 4 a7 7 0 1 1 0 14 a7 7 0 1 1 0 -14 M20 20 l-4 -4"
    })

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: icone.couleur
            strokeWidth: icone.taille >= 18 ? 1.7 : 1.5
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            scale: Qt.size(icone.taille / 24, icone.taille / 24)
            PathSvg { path: icone.chemins[icone.nom] || "" }
        }
    }
}
