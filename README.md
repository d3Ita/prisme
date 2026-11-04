# Prisme

Application locale pour créer et modifier des images par intelligence artificielle sur Windows. Tout tourne sur ton PC : pas de compte, pas d'abonnement, pas d'envoi de tes images sur Internet. Le calcul est fait par la carte graphique grâce à [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp).

![Aperçu de Prisme](docs/apercu.png)

## Fonctions

- **Création** d'images à partir d'une description, de 1 à 4 images par lancement
- **Modification** d'une image existante : glisser, coller ou choisir une image de départ
- **Formats** carré, paysage, portrait, ou proportions de l'image de départ
- **Historique** avec recherche, visionneuse plein écran, réutilisation de la description et du seed, mise à la corbeille
- **Réglages** : choix des modèles, LoRA, étapes, CFG, échantillonneur, sigmas, options mémoire
- **Téléphone** : utilisation depuis un téléphone sur le même Wi-Fi, protégée par un code d'accès (QR code)
- **Exécutable** Windows unique, sans Python à installer

## Prérequis

- Windows 10 ou 11 avec une carte graphique NVIDIA (8 Go de mémoire vidéo ou plus conseillés)
- [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp/releases), version CUDA pour Windows
- Des modèles compatibles avec stable-diffusion.cpp, au format GGUF ou safetensors

Prisme pilote les modèles qui fonctionnent avec un modèle de diffusion, un encodeur de texte de type LLM (`--llm`), un VAE et, pour la modification d'image, un encodeur d'image (`--llm_vision`).

## Installation

1. Télécharge `Prisme.exe` depuis la page [Releases](../../releases), ou construis-le (voir plus bas).
2. Crée cette structure à côté de l'exe :

   ```
   Prisme.exe
   sd/        sd-cli.exe et ses DLL (archive de stable-diffusion.cpp)
   models/    tes modèles .gguf / .safetensors
     loras/   tes LoRA (facultatif)
   ```

3. Lance `Prisme.exe`. Au premier lancement, l'application indique ce qui manque : clique sur **Choisir les modèles** et sélectionne un fichier pour chaque rôle.

Au premier lancement, Windows peut demander d'autoriser l'accès au réseau. Accepte si tu veux utiliser Prisme depuis ton téléphone.

## Utilisation

| Action | Comment |
|---|---|
| Générer | Écrire une description puis **Générer**, ou `Ctrl` + `Entrée` |
| Modifier une image | **Modifier** sous une image, ou glisser une image dans « Image de départ » |
| Changer de modèle | **Réglages → Modèles**, puis **Enregistrer** |
| Ajouter un LoRA | Le placer dans `models/loras`, puis **Réglages → LoRA → Actualiser** |
| Utiliser le téléphone | **Téléphone** en haut à droite, puis scanner le QR code |
| Parcourir l'historique | Clic sur une vignette, ou flèches ← → |

Les réglages sont enregistrés dans `app/reglages.json`, les images dans `images/`. L'application s'arrête seule après 30 minutes sans fenêtre ouverte (modifiable dans les Réglages).

### Téléphone

Le téléphone doit être sur le même réseau que le PC. Le lien du QR code contient un code d'accès enregistré dans `app/code-acces.txt` : supprimer ce fichier puis relancer Prisme en crée un nouveau et déconnecte les appareils déjà reliés.

## Construire depuis les sources

Avec Python 3 installé :

```powershell
powershell -ExecutionPolicy Bypass -File .\construire.ps1
```

Le script crée un environnement dans `.construction/`, y installe PyInstaller et Pillow, puis produit `Prisme.exe` à la racine.

Pour lancer sans construire :

```powershell
py -3 app\serveur.py
```

## Structure du code

| Fichier | Rôle |
|---|---|
| `app/serveur.py` | Serveur local (bibliothèque standard Python uniquement) : API, lancement de sd-cli, accès réseau |
| `app/index.html` | Interface complète : HTML, CSS et JavaScript sans dépendance |
| `app/icone.py` | Dessin de l'icône de l'exécutable |
| `construire.ps1` | Construction de `Prisme.exe` |
