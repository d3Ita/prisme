# Prisme MCP server · Serveur MCP de Prisme

**English** · [Français](#français)

Lets Claude (Claude Desktop or Claude Code) create and edit images with [Prisme](../README.md), and set Prisme up, on your own computer. The server is **built into Prisme**: nothing to install, no Python needed. It talks to Prisme's local API (`http://127.0.0.1:7861`), so prompts and images never leave your PC.

## Connect in one click

Start Prisme. If Claude Desktop or Claude Code is on the computer, a banner offers **Connect to Claude** (also in **Settings → Application → Claude**). Prisme adds itself to Claude's configuration, keeping a copy of the original (`claude_desktop_config.avant-prisme.json`); for Claude Code it uses `claude mcp add --scope user`. Restart Claude, then ask for an image. **Disconnect** in the same setting removes it. If you move Prisme, the setting offers to connect it again.

Claude starts Prisme by itself when it is not open, and Prisme stays open when Claude closes.

## Tools

| Tool | What it does |
|---|---|
| `generate_image(prompt, width, height, seed, model)` | Creates an image. Width and height: multiples of 16 between 256 and 2048 (1024 × 1024 by default). `model` is optional: a drawing model file from `list_models`, used for this image only. |
| `edit_image(image_path, instruction)` | Edits a PNG or JPEG found in `PRISME_OUTPUT_DIR`, keeping its proportions. Needs a profile with image editing (FLUX.2 klein or Qwen-Image). |
| `get_status(task_id)` | Prisme's status: progress, engines, downloads, problems; with a `task_id`, the finished image. |
| `list_models()` | Files in Prisme's `models` folder, the ones selected, and whether editing is possible. |
| `list_profiles()` | Model profiles by hardware and other choices, with size and license, and the profile suggested for this computer. |
| `install_engine(engine)` | Installs the `image` engine (stable-diffusion.cpp) or the `text` engine (llama.cpp) from their pinned official releases. |
| `download_profile(profile_id)` | Downloads a profile and the missing engines. |
| `download_model(url, use_as)` | Downloads a model outside Prisme's catalog (`.gguf` or `.safetensors` over https), optionally selected as `image`, `text`, `vision`, `vae` or `lora`. |

Each image is copied to `PRISME_OUTPUT_DIR` and shown to Claude as a small preview. If a creation takes longer than `PRISME_TIMEOUT`, the tool returns a `task_id`: Claude then calls `get_status` to get the image.

## Your approval for licenses and other models

Profiles under an open license (Apache-2.0) are downloaded directly when you agree with Claude. Two cases need **your click in Prisme's window**, which Claude cannot give for you:

- a profile under a **non-commercial license** (Qwen-Image 2.1 Turbo): Prisme shows the license and what it allows;
- a model **outside Prisme's catalog**: Prisme warns that neither its license nor its content is checked, links to its page, and says whether the file can be checked by a checksum or only by its size.

Prisme opens its window if needed. If you refuse, or nobody answers within 10 minutes, nothing is downloaded.

## Manual setup

Use the full path of your Prisme program:

| System | Command |
|---|---|
| Windows | `C:\path\to\Prisme.exe` |
| macOS | `/Applications/Prisme.app/Contents/MacOS/Prisme` |
| Linux | `/path/to/prisme` |

Claude Desktop, in `claude_desktop_config.json` (**Settings → Developer → Edit Config**):

```json
{
  "mcpServers": {
    "prisme": {
      "command": "C:\\path\\to\\Prisme.exe",
      "args": ["--mcp"],
      "env": { "PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "1" }
    }
  }
}
```

Claude Code:

```bash
claude mcp add --scope user -e PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1 prisme -- /path/to/Prisme --mcp
```

From the source code, use `python3 app/serveur.py --mcp` (or `python3 mcp/server.py`). `--mcp --check` prints the settings and the tools, then stops.

| Variable | Default | Role |
|---|---|---|
| `PRISME_URL` | `http://127.0.0.1:7861` | Prisme's address. Only this computer is accepted. |
| `PRISME_TIMEOUT` | `50` | Seconds to wait for an image (or an approval, up to 3 minutes) before returning. |
| `PRISME_OUTPUT_DIR` | `~/Prisme-MCP` | Where images are copied. It is also the only folder `edit_image` can read. |

## Troubleshooting

- **Prisme doesn't appear in Claude**: restart Claude after connecting. In Claude Code, check with `claude mcp list`.
- **"Prisme is not ready"**: the message lists what is missing. Ask Claude to call `list_profiles`, then `download_profile` with the suggested profile.
- **"Prisme is busy"**: Prisme makes one image at a time, including the ones started from its window. Wait, or follow it with `get_status`.
- **A `task_id` instead of an image**: the creation took longer than `PRISME_TIMEOUT`. Ask Claude to call `get_status`, or raise `PRISME_TIMEOUT` (some clients stop waiting after about a minute: stay below their limit).
- **"waiting_for_user_approval"**: answer the request in Prisme's window.
- **"only images inside … can be edited"**: copy the image into `PRISME_OUTPUT_DIR` first. The server reads no other file.
- **"cannot edit images"**: the selected models cannot edit (Z-Image, or Qwen-Image without its vision file). Choose a FLUX.2 klein or Qwen-Image profile.

---

## Français

Permet à Claude (Claude Desktop ou Claude Code) de créer et de modifier des images avec [Prisme](../README.fr.md), et d'installer Prisme, sur ton ordinateur. Le serveur est **intégré à Prisme** : rien à installer, pas besoin de Python. Il parle à l'API locale de Prisme (`http://127.0.0.1:7861`) : les descriptions et les images ne quittent pas ton PC.

### Connecter en un clic

Lance Prisme. Si Claude Desktop ou Claude Code est sur l'ordinateur, un bandeau propose **Connecter à Claude** (aussi dans **Réglages → Application → Claude**). Prisme s'ajoute à la configuration de Claude en gardant une copie de l'original (`claude_desktop_config.avant-prisme.json`) ; pour Claude Code, il utilise `claude mcp add --scope user`. Relance Claude, puis demande une image. **Déconnecter**, au même endroit, le retire. Si tu déplaces Prisme, le réglage propose de le reconnecter.

Claude lance Prisme tout seul s'il n'est pas ouvert, et Prisme reste ouvert quand Claude se ferme.

### Outils

| Outil | Rôle |
|---|---|
| `generate_image(prompt, width, height, seed, model)` | Crée une image. Largeur et hauteur : multiples de 16 entre 256 et 2048 (1024 × 1024 par défaut). `model` est facultatif : un fichier de modèle de dessin donné par `list_models`, pour cette image seulement. |
| `edit_image(image_path, instruction)` | Modifie un PNG ou un JPEG du dossier `PRISME_OUTPUT_DIR`, en gardant ses proportions. Demande un profil qui sait modifier (FLUX.2 klein ou Qwen-Image). |
| `get_status(task_id)` | L'état de Prisme : avancement, moteurs, téléchargements, problèmes ; avec un `task_id`, l'image terminée. |
| `list_models()` | Les fichiers du dossier `models`, ceux qui sont choisis, et si la modification est possible. |
| `list_profiles()` | Les profils par machine et les autres choix, avec taille et licence, et le profil suggéré pour cet ordinateur. |
| `install_engine(engine)` | Installe le moteur `image` (stable-diffusion.cpp) ou `text` (llama.cpp) depuis leurs versions officielles épinglées. |
| `download_profile(profile_id)` | Télécharge un profil et les moteurs qui manquent. |
| `download_model(url, use_as)` | Télécharge un modèle hors du catalogue de Prisme (`.gguf` ou `.safetensors` en https), éventuellement choisi comme `image`, `text`, `vision`, `vae` ou `lora`. |

Chaque image est copiée dans `PRISME_OUTPUT_DIR` et montrée à Claude en petit aperçu. Si une création dure plus que `PRISME_TIMEOUT`, l'outil renvoie un `task_id` : Claude appelle ensuite `get_status` pour récupérer l'image.

### Ton accord pour les licences et les autres modèles

Les profils sous licence ouverte (Apache-2.0) se téléchargent directement quand tu es d'accord avec Claude. Deux cas demandent **ton clic dans la fenêtre de Prisme**, que Claude ne peut pas donner à ta place :

- un profil sous **licence non commerciale** (Qwen-Image 2.1 Turbo) : Prisme affiche la licence et ce qu'elle permet ;
- un modèle **hors du catalogue de Prisme** : Prisme prévient que ni sa licence ni son contenu ne sont vérifiés, donne le lien vers sa page, et indique si le fichier pourra être vérifié par une empreinte ou seulement par sa taille.

Prisme ouvre sa fenêtre si besoin. Si tu refuses, ou si personne ne répond dans les 10 minutes, rien n'est téléchargé.

### Installation à la main

Utilise le chemin complet de ton programme Prisme (voir le tableau en anglais ci-dessus) avec l'argument `--mcp`, et la variable `PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1` pour éviter l'écran de démarrage à chaque lancement de Claude. Les blocs de configuration de Claude Desktop et la commande de Claude Code sont plus haut. Depuis le code source : `python3 app/serveur.py --mcp` (ou `python3 mcp/server.py`) ; `--mcp --check` affiche les réglages et les outils, puis s'arrête.

| Variable | Par défaut | Rôle |
|---|---|---|
| `PRISME_URL` | `http://127.0.0.1:7861` | Adresse de Prisme. Seul cet ordinateur est accepté. |
| `PRISME_TIMEOUT` | `50` | Secondes d'attente d'une image (ou d'un accord, 3 minutes au plus) avant de répondre. |
| `PRISME_OUTPUT_DIR` | `~/Prisme-MCP` | Dossier où les images sont copiées. C'est aussi le seul dossier que `edit_image` peut lire. |

### Dépannage

- **Prisme n'apparaît pas dans Claude** : relance Claude après la connexion. Dans Claude Code, vérifie avec `claude mcp list`.
- **« Prisme is not ready »** : le message liste ce qui manque. Demande à Claude d'appeler `list_profiles`, puis `download_profile` avec le profil suggéré.
- **« Prisme is busy »** : Prisme fait une image à la fois, y compris celles lancées depuis sa fenêtre. Attends, ou suis-la avec `get_status`.
- **Un `task_id` au lieu d'une image** : la création a duré plus que `PRISME_TIMEOUT`. Demande à Claude d'appeler `get_status`, ou augmente `PRISME_TIMEOUT` (certains clients arrêtent d'attendre après environ une minute : reste en dessous).
- **« waiting_for_user_approval »** : réponds à la demande dans la fenêtre de Prisme.
- **« only images inside … can be edited »** : copie d'abord l'image dans `PRISME_OUTPUT_DIR`. Le serveur ne lit aucun autre fichier.
- **« cannot edit images »** : les modèles choisis ne savent pas modifier (Z-Image, ou Qwen-Image sans son fichier de vision). Choisis un profil FLUX.2 klein ou Qwen-Image.
