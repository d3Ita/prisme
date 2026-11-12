// Fenetre des reglages : memes sections et meme API que la version web. L'enregistrement renvoie la version lue,
// pour ne pas ecraser un modele choisi par un telechargement pendant que la fenetre etait ouverte.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Panneau {
    id: fenetre
    titre: Theme.tx("Réglages", "Settings")
    sousTitre: Theme.tx("Modèles et paramètres utilisés pour les prochaines générations.", "Models and parameters used for the next generations.")

    property var infos: null
    property var claude: null
    property var moteurTexte: null
    property var ollama: []
    property string noteOllama: ""
    property var loras: []
    readonly property string sigmasRapide: "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"
    signal ouvrirModeles()
    signal enregistre()
    signal apparenceChoisie(string apparence)
    signal langueChoisie(string langue)

    onOpened: lire()

    function lire() {
        Theme.api("/api/reglages", undefined, function (i) {
            infos = i
            remplir(i.reglages)
        })
        Theme.api("/api/claude", undefined, function (c) { claude = c }, function () { claude = null })
        Theme.api("/api/etat", undefined, function (e) { moteurTexte = (e.moteurs || {}).texte || null })
    }

    function fichiers(extensions, vide) {
        const liste = infos ? infos.modeles.filter(m => !extensions || extensions.some(x => m.nom.toLowerCase().endsWith(x))) : []
        return (vide ? [{ valeur: "", texte: vide }] : []).concat(liste.map(m => ({ valeur: m.nom, texte: m.nom })))
    }

    function remplir(r) {
        diffusion.valeur = r.modele_diffusion
        texte.valeur = r.modele_texte
        vision.valeur = r.modele_vision
        vae.valeur = r.vae
        moteurAmelioration.valeur = r.amelioration_moteur
        llmLocal.valeur = r.amelioration_modele_local
        llmVision.valeur = r.amelioration_vision_locale
        modeleOllama.valeur = r.amelioration_modele
        adresseOllama.text = r.ollama_adresse
        amelioAuto.checked = r.amelioration_auto
        consigne.text = r.amelioration_consigne
        consigneModif.text = r.amelioration_consigne_modif
        etapes.text = String(r.etapes)
        cfg.text = String(r.cfg)
        methode.valeur = r.methode
        sigmas.text = r.sigmas
        cpu.checked = r.dechargement_cpu
        tuiles.checked = r.vae_tuiles
        ecran.checked = r.memoire_ecran
        flash.checked = r.flash_attention
        reseau.checked = r.acces_reseau
        maj.checked = r.verifier_mises_a_jour
        arretFermeture.checked = r.arret_fermeture
        arretAuto.text = String(r.arret_auto_minutes)
        // LoRA du dossier, avec leur force et leur etat enregistres
        loras = (infos ? infos.loras : []).map(function (l) {
            const connu = (r.loras || []).find(x => x.nom === l.nom)
            return { nom: l.nom, force: connu ? connu.force : 1.0, actif: connu ? connu.actif : false }
        })
    }

    function lireOllama() {
        Theme.api("/api/ollama-modeles", undefined, function (o) {
            ollama = o.modeles.map(m => ({ valeur: m.nom, texte: m.nom + " · " + Theme.taille(m.taille) }))
            noteOllama = o.erreur || ""
        })
    }

    function lireFormulaire() {
        return {
            modele_diffusion: diffusion.valeur, modele_texte: texte.valeur, modele_vision: vision.valeur, vae: vae.valeur,
            amelioration_moteur: moteurAmelioration.valeur, amelioration_modele_local: llmLocal.valeur,
            amelioration_vision_locale: llmVision.valeur, amelioration_modele: modeleOllama.valeur,
            ollama_adresse: adresseOllama.text, amelioration_auto: amelioAuto.checked,
            amelioration_consigne: consigne.text, amelioration_consigne_modif: consigneModif.text,
            etapes: Number(etapes.text), cfg: Number(cfg.text.replace(",", ".")), methode: methode.valeur, sigmas: sigmas.text,
            dechargement_cpu: cpu.checked, vae_tuiles: tuiles.checked, memoire_ecran: ecran.checked, flash_attention: flash.checked,
            acces_reseau: reseau.checked, verifier_mises_a_jour: maj.checked, arret_fermeture: arretFermeture.checked,
            arret_auto_minutes: Number(arretAuto.text), loras: loras.filter(l => l.actif || l.force !== 1.0)
        }
    }

    function enregistrer() {
        Theme.api("/api/reglages", Object.assign(lireFormulaire(), { version: infos ? infos.version : null }), function () {
            Theme.note(Theme.tx("Réglages enregistrés", "Settings saved"))
            fenetre.enregistre()
            fenetre.close()
        })
    }

    component Consigne: TextArea {
        Layout.fillWidth: true
        Layout.preferredHeight: 92
        wrapMode: TextArea.Wrap
        font.pixelSize: 13
        color: Theme.texte
        selectByMouse: true
        background: Rectangle { radius: 10; color: Theme.surface2; border.color: parent.activeFocus ? Theme.accent : Theme.bordure }
    }

    // --- Modeles
    Section {
        titre: Theme.tx("Modèles", "Models")
        description: fenetre.infos ? (fenetre.infos.modeles.length ? fenetre.infos.modeles.length + Theme.tx(" fichiers trouvés dans ", " files found in ") + fenetre.infos.dossier
                                                                   : Theme.tx("Aucun modèle trouvé dans ", "No model found in ") + fenetre.infos.dossier) : ""
        liens: [
            BoutonDiscret { text: Theme.tx("Télécharger", "Download"); onClicked: fenetre.ouvrirModeles() },
            BoutonDiscret { text: Theme.tx("Actualiser", "Refresh"); onClicked: { const r = fenetre.lireFormulaire(); Theme.api("/api/reglages", undefined, function (i) { fenetre.infos = i; fenetre.remplir(Object.assign({}, i.reglages, r)) }) } },
            BoutonDiscret { text: Theme.tx("Ouvrir le dossier", "Open the folder"); onClicked: Theme.api("/api/dossier-modeles", {}) }
        ]
        Ligne { nom: Theme.tx("Modèle de dessin", "Drawing model"); aide: Theme.tx("Fait l'image", "Makes the image"); ListeDeroulante { id: diffusion; model: fenetre.fichiers(null, "") } }
        Ligne { nom: Theme.tx("Modèle de texte", "Text model"); aide: Theme.tx("Comprend la description", "Understands the description"); ListeDeroulante { id: texte; model: fenetre.fichiers(null, "") } }
        Ligne { nom: Theme.tx("Vision", "Vision"); aide: Theme.tx("Lit l'image de départ (Qwen-Image)", "Reads the starting image (Qwen-Image)"); ListeDeroulante { id: vision; model: fenetre.fichiers(null, Theme.tx("Aucune", "None")) } }
        Ligne { nom: "VAE"; aide: Theme.tx("Produit l'image finale", "Produces the final image"); ListeDeroulante { id: vae; model: fenetre.fichiers(null, "") } }
    }

    // --- LoRA
    Section {
        titre: "LoRA"
        description: fenetre.loras.length ? "" : Theme.tx("Aucun LoRA : place des fichiers .safetensors dans models/loras.", "No LoRA: put .safetensors files in models/loras.")
        liens: [BoutonDiscret { text: Theme.tx("Ouvrir le dossier", "Open the folder"); onClicked: Theme.api("/api/dossier-loras", {}) }]
        Repeater {
            model: fenetre.loras
            delegate: Ligne {
                id: lora
                required property var modelData
                required property int index
                nom: modelData.nom
                Row {
                    spacing: 10
                    Champ {
                        width: 70
                        text: String(lora.modelData.force)
                        validator: DoubleValidator { bottom: -2; top: 2; decimals: 2 }
                        onEditingFinished: { const l = fenetre.loras.slice(); l[lora.index] = Object.assign({}, l[lora.index], { force: Number(text.replace(",", ".")) }); fenetre.loras = l }
                    }
                    Interrupteur {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: lora.modelData.actif
                        onToggled: { const l = fenetre.loras.slice(); l[lora.index] = Object.assign({}, l[lora.index], { actif: checked }); fenetre.loras = l }
                    }
                }
            }
        }
    }

    // --- Amelioration de la description
    Section {
        titre: Theme.tx("Amélioration de la description", "Prompt enhancement")
        Ligne {
            nom: Theme.tx("Moteur", "Engine")
            aide: Theme.tx("Intégré : rien d'autre à installer", "Built-in: nothing else to install")
            ListeDeroulante {
                id: moteurAmelioration
                model: [{ valeur: "integre", texte: Theme.tx("Intégré (llama.cpp)", "Built-in (llama.cpp)") }, { valeur: "ollama", texte: "Ollama" }]
                onValeurChanged: if (valeur === "ollama") fenetre.lireOllama()
            }
        }
        Ligne {
            visible: moteurAmelioration.valeur !== "ollama"
            nom: Theme.tx("Modèle de langage", "Language model")
            aide: Theme.tx("Fichier GGUF du dossier models", "GGUF file from the models folder")
            ListeDeroulante { id: llmLocal; model: fenetre.fichiers([".gguf"], Theme.tx("Aucun", "None")) }
        }
        Ligne {
            visible: moteurAmelioration.valeur !== "ollama"
            nom: Theme.tx("Vision", "Vision")
            aide: Theme.tx("Facultatif : lit l'image de départ", "Optional: reads the starting image")
            ListeDeroulante { id: llmVision; model: fenetre.fichiers([".gguf"], Theme.tx("Aucune", "None")) }
        }
        Ligne {
            visible: moteurAmelioration.valeur !== "ollama" && !!fenetre.moteurTexte
            nom: Theme.tx("Moteur de texte", "Text engine")
            aide: fenetre.moteurTexte && fenetre.moteurTexte.installe ? Theme.tx("Installé", "Installed") : Theme.tx("Téléchargé une seule fois", "Downloaded once")
            BoutonPrincipal {
                visible: !!fenetre.moteurTexte && !fenetre.moteurTexte.installe
                secondaire: true
                text: Theme.tx("Installer le moteur", "Install the engine")
                onClicked: Theme.api("/api/installer-moteur", { moteur: "texte" }, function () { Theme.note(Theme.tx("Installation du moteur de texte…", "Installing the text engine…")) })
            }
        }
        Ligne {
            visible: moteurAmelioration.valeur === "ollama"
            nom: Theme.tx("Modèle de langage", "Language model")
            aide: fenetre.noteOllama || Theme.tx("Servi par Ollama", "Served by Ollama")
            ListeDeroulante { id: modeleOllama; model: fenetre.ollama }
        }
        Ligne {
            visible: moteurAmelioration.valeur === "ollama"
            nom: Theme.tx("Adresse d'Ollama", "Ollama address")
            Champ { id: adresseOllama }
        }
        Ligne {
            nom: Theme.tx("Améliorer automatiquement", "Enhance automatically")
            aide: Theme.tx("Avant chaque génération", "Before each generation")
            Interrupteur { id: amelioAuto }
        }
        Text { text: Theme.tx("Consigne de création", "Creation instruction"); color: Theme.texte; font.pixelSize: 14 }
        Consigne { id: consigne }
        Text { text: Theme.tx("Consigne de modification", "Edit instruction"); color: Theme.texte; font.pixelSize: 14 }
        Consigne { id: consigneModif }
    }

    // --- Generation
    Section {
        titre: Theme.tx("Génération", "Generation")
        liens: [BoutonDiscret {
            text: Theme.tx("Profil rapide", "Fast profile")
            ToolTip.visible: hovered
            ToolTip.text: Theme.tx("Pour les modèles distillés en 8 étapes", "For models distilled to 8 steps")
            onClicked: { etapes.text = "8"; cfg.text = "1"; methode.valeur = "euler"; sigmas.text = fenetre.sigmasRapide }
        }]
        Ligne { nom: Theme.tx("Étapes", "Steps"); aide: Theme.tx("Selon le modèle, souvent 20 à 30", "Depends on the model, often 20 to 30"); Champ { id: etapes; width: 90; validator: IntValidator { bottom: 1; top: 150 } } }
        Ligne { nom: "CFG"; aide: Theme.tx("Selon le modèle, souvent 1 à 5", "Depends on the model, often 1 to 5"); Champ { id: cfg; width: 90 } }
        Ligne {
            nom: Theme.tx("Méthode", "Method")
            aide: Theme.tx("Échantillonneur", "Sampler")
            ListeDeroulante { id: methode; model: fenetre.infos ? fenetre.infos.methodes.map(m => ({ valeur: m, texte: m })) : [] }
        }
        Ligne {
            nom: "Sigmas"
            readonly property int valeurs: sigmas.text.split(",").filter(x => x.trim()).length
            readonly property int voulu: Number(etapes.text) + 1
            aide: !sigmas.text.trim() ? Theme.tx("Vide = automatique", "Empty = automatic")
                  : valeurs === voulu ? valeurs + Theme.tx(" valeurs, correct.", " values, correct.")
                  : valeurs + Theme.tx(" valeurs : il en faut ", " values: ") + voulu + Theme.tx(" pour ", " are needed for ") + (voulu - 1) + Theme.tx(" étapes.", " steps.")
            Champ { id: sigmas; width: 300 }
        }
    }

    // --- Performances
    Section {
        titre: Theme.tx("Performances", "Performance")
        Ligne { nom: Theme.tx("Décharger sur le processeur", "Offload to the CPU"); aide: Theme.tx("Économise la mémoire de la carte graphique", "Saves graphics card memory"); Interrupteur { id: cpu } }
        Ligne { nom: Theme.tx("VAE par tuiles", "Tiled VAE"); aide: Theme.tx("Évite les manques de mémoire", "Avoids running out of memory"); Interrupteur { id: tuiles } }
        Ligne {
            nom: Theme.tx("Garder le PC utilisable", "Keep the PC usable")
            aide: Theme.tx("Laisse 1,5 Go de la carte graphique à l'affichage pendant les calculs : un peu plus lent, mais l'écran ne gèle plus",
                           "Leaves 1.5 GB of the graphics card to the display during calculations: a little slower, but the screen no longer freezes")
            Interrupteur { id: ecran }
        }
        Ligne { nom: "Flash attention"; aide: Theme.tx("Plus rapide sur carte NVIDIA", "Faster on NVIDIA cards"); Interrupteur { id: flash } }
    }

    // --- Application
    Section {
        titre: Theme.tx("Application", "Application")
        Ligne {
            nom: Theme.tx("Langue", "Language")
            aide: Theme.tx("Pour cet ordinateur · Language", "For this computer")
            Row {
                spacing: 4
                Repeater {
                    model: [["fr", "Français"], ["en", "English"], ["auto", Theme.tx("Automatique", "Automatic")]]
                    delegate: BoutonPrincipal {
                        required property var modelData
                        secondaire: Theme.langue !== modelData[0]
                        text: modelData[1]
                        implicitHeight: 32
                        onClicked: fenetre.langueChoisie(modelData[0])
                    }
                }
            }
        }
        Ligne {
            nom: Theme.tx("Apparence", "Appearance")
            aide: Theme.tx("Pour cet ordinateur, appliquée tout de suite", "For this computer, applied right away")
            Row {
                spacing: 4
                Repeater {
                    model: [["clair", Theme.tx("Clair", "Light")], ["sombre", Theme.tx("Sombre", "Dark")], ["auto", Theme.tx("Automatique", "Automatic")]]
                    delegate: BoutonPrincipal {
                        required property var modelData
                        secondaire: Theme.apparence !== modelData[0]
                        text: modelData[1]
                        implicitHeight: 32
                        onClicked: fenetre.apparenceChoisie(modelData[0])
                    }
                }
            }
        }
        Ligne { nom: Theme.tx("Accès depuis le téléphone", "Phone access"); aide: Theme.tx("Pris en compte au prochain lancement", "Applied at next launch"); Interrupteur { id: reseau } }
        Ligne { nom: Theme.tx("Chercher les nouvelles versions", "Check for new versions"); aide: Theme.tx("Une fois au lancement, sur GitHub", "Once at launch, on GitHub"); Interrupteur { id: maj } }
        Ligne {
            id: ligneMaj
            property string etat: Theme.tx("Chercher une nouvelle version tout de suite", "Look for a new version right now")
            nom: Theme.tx("Mise à jour", "Update")
            aide: etat
            BoutonPrincipal {
                secondaire: true
                text: Theme.tx("Vérifier", "Check")
                onClicked: {
                    ligneMaj.etat = Theme.tx("Vérification…", "Checking…")
                    Theme.api("/api/verifier-mise-a-jour", {}, function (r) {
                        ligneMaj.etat = r.mise_a_jour ? "Prisme " + r.mise_a_jour.version + Theme.tx(" est disponible.", " is available.")
                                                      : Theme.tx("Prisme est à jour (v", "Prisme is up to date (v") + r.version + ")."
                    }, function (m) { ligneMaj.etat = m })
                }
            }
        }
        Ligne {
            id: ligneClaude
            readonly property bool connecte: !!fenetre.claude && (fenetre.claude.desktop_connecte || fenetre.claude.code_connecte)
            nom: "Claude"
            aide: !fenetre.claude || !(fenetre.claude.desktop || fenetre.claude.code) ? Theme.tx("Claude n'est pas installé sur cet ordinateur", "Claude is not installed on this computer")
                  : connecte ? Theme.tx("Connecté : Claude peut créer des images avec Prisme", "Connected: Claude can create images with Prisme")
                  : Theme.tx("Créer des images en le demandant à Claude", "Create images by asking Claude")
            BoutonPrincipal {
                visible: !!fenetre.claude && (fenetre.claude.desktop || fenetre.claude.code)
                secondaire: true
                text: ligneClaude.connecte ? Theme.tx("Déconnecter", "Disconnect") : Theme.tx("Connecter", "Connect")
                onClicked: Theme.api("/api/connecter-claude", { retirer: ligneClaude.connecte }, function (r) {
                    fenetre.claude = r.claude
                    Theme.note(r.erreurs.length ? r.erreurs.join("\n") : Theme.tx("Fait : relance Claude pour qu'il voie le changement.", "Done: restart Claude so it sees the change."), r.erreurs.length > 0)
                })
            }
        }
        Ligne {
            nom: Theme.tx("Quitter Prisme", "Quit Prisme")
            aide: Theme.tx("Arrête Prisme et ses moteurs ; le téléphone et Claude n'y ont plus accès", "Stops Prisme and its engines; the phone and Claude lose access")
            BoutonPrincipal { secondaire: true; text: Theme.tx("Quitter Prisme", "Quit Prisme"); onClicked: Theme.api("/api/quitter", {}, function () { Qt.quit() }) }
        }
        Ligne { nom: Theme.tx("Arrêter à la fermeture", "Stop when closed"); aide: Theme.tx("Quand la fenêtre de Prisme se ferme", "When the Prisme window closes"); Interrupteur { id: arretFermeture } }
        Ligne { nom: Theme.tx("Arrêt automatique", "Automatic stop"); aide: Theme.tx("Minutes sans fenêtre ouverte", "Minutes without an open window"); Champ { id: arretAuto; width: 90; validator: IntValidator { bottom: 1; top: 1440 } } }
    }

    Item { implicitHeight: 4 }

    boutons: [
        BoutonDiscret { text: Theme.tx("Valeurs par défaut", "Defaults"); onClicked: if (fenetre.infos) { fenetre.remplir(fenetre.infos.defauts); Theme.note(Theme.tx("Valeurs par défaut chargées : clique sur Enregistrer pour les garder", "Defaults loaded: click Save to keep them")) } },
        Item { Layout.fillWidth: true },
        BoutonPrincipal { secondaire: true; text: Theme.tx("Annuler", "Cancel"); onClicked: fenetre.close() },
        BoutonPrincipal { text: Theme.tx("Enregistrer", "Save"); onClicked: fenetre.enregistrer() }
    ]
}
