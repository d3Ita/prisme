// Fiche d'une image : comment elle a ete creee (lu dans le PNG), et de quoi la refaire a l'identique
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Détails de l'image", "Image details")
    width: Math.min(parent ? parent.width - 48 : 600, 600)
    height: Math.min(parent ? parent.height - 48 : 680, 680)
    // Les infos de /api/images pour cette image
    property var image: null
    readonly property var p: image && image.parametres ? image.parametres : null
    readonly property var m: image && image.mesures ? image.mesures : null
    signal refaire(var image)
    signal range()

    function ouvrir(infos) {
        image = infos
        open()
    }
    // Le projet tape est garde meme si la fiche se ferme avant la fin de la saisie
    onClosed: ranger(projet.text)

    function valeur(v) { return v === null || v === undefined || v === "" ? "—" : String(v) }

    function duree(s) { return s < 60 ? Math.round(s) + " s" : Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" }

    function ranger(projet) {
        if (!image || projet.trim() === (image.projet || "")) return
        const nom = image.nom
        Theme.api("/api/projet", { noms: [nom], projet: projet }, function () {
            image = Object.assign({}, image, { projet: projet.trim() })
            range()
        })
    }

    component Valeur: Text {
        color: Theme.texte2
        font.pixelSize: 13
        wrapMode: Text.WrapAnywhere
        horizontalAlignment: Text.AlignRight
        width: Math.min(implicitWidth, 300)
    }

    Section {
        titre: Theme.tx("Description", "Description")
        Text {
            text: fenetre.image && fenetre.image.prompt ? fenetre.image.prompt : "—"
            color: Theme.texte
            font.pixelSize: 14
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            Layout.fillWidth: true
        }
    }

    Section {
        titre: Theme.tx("Projet", "Project")
        description: Theme.tx("Range cette image dans un projet pour la retrouver (vide : dans aucun).",
                              "Put this image in a project to find it again (empty: none).")
        Champ {
            id: projet
            Layout.fillWidth: true
            text: fenetre.image ? fenetre.image.projet || "" : ""
            placeholderText: Theme.tx("Aucun projet", "No project")
            maximumLength: 60
            onEditingFinished: fenetre.ranger(text)
        }
    }

    Section {
        titre: Theme.tx("Création", "Creation")
        Ligne { nom: Theme.tx("Variante", "Variant"); Valeur { text: fenetre.valeur(fenetre.image ? fenetre.image.seed : null) } }
        Ligne { nom: Theme.tx("Taille", "Size"); Valeur { text: fenetre.image ? fenetre.image.largeur + " × " + fenetre.image.hauteur : "—" } }
        Ligne { nom: Theme.tx("Date", "Date"); Valeur { text: fenetre.image ? fenetre.valeur(fenetre.image.date).replace("T", " ") : "—" } }
        Ligne {
            nom: Theme.tx("Durée", "Time")
            aide: Theme.tx("Sur cet ordinateur, chargement des modèles compris", "On this computer, including loading the models")
            Valeur { text: fenetre.m && fenetre.m.duree ? fenetre.duree(fenetre.m.duree) : "—" }
        }
        Ligne {
            nom: Theme.tx("Mémoire vive maximale", "Peak memory")
            aide: Theme.tx("Prise par le moteur, sans celle de la carte graphique", "Used by the engine, not counting the graphics card")
            Valeur { text: fenetre.m && fenetre.m.memoire ? (fenetre.m.memoire / 1e9).toFixed(1) + Theme.tx(" Go", " GB") : "—" }
        }
        Ligne { nom: Theme.tx("Étapes", "Steps"); Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.etapes : null) } }
        Ligne { nom: "CFG"; Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.cfg : null) } }
        Ligne { nom: Theme.tx("Méthode", "Method"); Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.methode : null) } }
        Ligne { nom: Theme.tx("Modèle de diffusion", "Diffusion model"); Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.modele_diffusion : null) } }
        Ligne { nom: Theme.tx("Modèle de texte", "Text model"); Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.modele_texte : null) } }
        Ligne { nom: "VAE"; Valeur { text: fenetre.valeur(fenetre.p ? fenetre.p.vae : null) } }
        Ligne {
            nom: "LoRA"
            Valeur { text: fenetre.image && fenetre.image.loras && fenetre.image.loras.length ? fenetre.image.loras.join("\n") : "—" }
        }
        Text {
            visible: !!fenetre.image && !fenetre.p
            text: Theme.tx("Cette image ne garde pas ses réglages (version ancienne du moteur, ou image venue d'ailleurs).",
                           "This image doesn't keep its settings (older engine version, or an image from elsewhere).")
            color: Theme.texte3
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    boutons: [
        BoutonPrincipal {
            secondaire: true
            text: Theme.tx("Copier la description", "Copy the description")
            enabled: !!fenetre.image && !!fenetre.image.prompt
            onClicked: {
                if (typeof fichiers !== "undefined") fichiers.copier(fenetre.image.prompt)
                Theme.note(Theme.tx("Description copiée", "Description copied"))
            }
        },
        Item { Layout.fillWidth: true },
        BoutonPrincipal {
            text: Theme.tx("Refaire à l'identique", "Redo identically")
            enabled: !!fenetre.image && !!fenetre.image.prompt
            onClicked: { fenetre.refaire(fenetre.image); fenetre.close() }
        }
    ]
}
