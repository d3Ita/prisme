# Prisme MCP server · Serveur MCP de Prisme

**English** · [Français](#français)

Lets Claude (Claude Desktop or Claude Code) create and edit images with [Prisme](../README.md), on your own computer. The server talks to Prisme's local API (`http://127.0.0.1:7861`): prompts and images never leave your PC.

## Tools

| Tool | What it does |
|---|---|
| `generate_image(prompt, width, height, seed, model)` | Creates an image. Width and height: multiples of 16 between 256 and 2048 (1024 × 1024 by default). `model` is optional: a drawing model file from `list_models`, used for this image only. |
| `edit_image(image_path, instruction)` | Edits a PNG or JPEG found in `PRISME_OUTPUT_DIR`, keeping its proportions. Needs a profile with image editing (FLUX.2 klein or Qwen-Image). |
| `list_models()` | Files in Prisme's `models` folder, the ones selected, and whether editing is possible. |
| `list_profiles()` | Model profiles by hardware, what is downloaded, and the profile suggested for this computer. |
| `get_status(task_id)` | Prisme's status; with a `task_id`, the finished image or its progress. |

Each image is copied to `PRISME_OUTPUT_DIR` and shown to Claude. If a creation takes longer than `PRISME_TIMEOUT`, the tool returns a `task_id`: Claude then calls `get_status` to get the image.

## Installation

1. Start Prisme and download a model profile (**Download the models**, then **Download this profile**).
2. Install the MCP server with Python 3.10 or later, in its own environment:

   ```bash
   python3 -m venv mcp/.venv
   mcp/.venv/bin/pip install -r mcp/requirements.txt
   mcp/.venv/bin/python mcp/server.py --check
   ```

   On Windows: `py -3 -m venv mcp\.venv`, then `mcp\.venv\Scripts\pip install -r mcp\requirements.txt` and `mcp\.venv\Scripts\python mcp\server.py --check`. The check prints the address, the timeout, the image folder and the five tools.

Optional: `pip install Pillow` in the same environment shows large images to Claude as a lighter JPEG preview; without it, an image over 900 KB is only given as a file path.

## Configuration

| Variable | Default | Role |
|---|---|---|
| `PRISME_URL` | `http://127.0.0.1:7861` | Prisme's address. Only this computer is accepted (`127.0.0.1`, `localhost`). |
| `PRISME_TIMEOUT` | `120` | Seconds to wait for an image before returning a `task_id`. |
| `PRISME_OUTPUT_DIR` | `~/Prisme-MCP` | Where images are copied. It is also the only folder `edit_image` can read. |

### Claude Desktop

Add this to `claude_desktop_config.json` (**Settings → Developer → Edit Config**), with the full paths of your copy, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "prisme": {
      "command": "C:\\path\\to\\prisme\\mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\prisme\\mcp\\server.py"],
      "env": {
        "PRISME_TIMEOUT": "300",
        "PRISME_OUTPUT_DIR": "C:\\Users\\you\\Pictures\\Prisme-MCP"
      }
    }
  }
}
```

On macOS and Linux, use `/path/to/prisme/mcp/.venv/bin/python` and `/path/to/prisme/mcp/server.py`.

### Claude Code

```bash
claude mcp add prisme -e PRISME_TIMEOUT=300 -- /path/to/prisme/mcp/.venv/bin/python /path/to/prisme/mcp/server.py
```

Check with `claude mcp list`.

## Example

> Create a 1024 × 768 image of a fox in the snow at sunset with Prisme, then add a red scarf to the fox.

Claude calls `generate_image`, gets the saved file (for example `~/Prisme-MCP/image_20261108_120000.png`), then calls `edit_image` with that file and the instruction.

## Troubleshooting

- **"Prisme is not running"**: start Prisme. If you changed its port with `PRISME_PORT`, set `PRISME_URL` to match.
- **"Prisme is not ready"**: the message lists what is missing and the profile suggested for your computer. Install the engine and download that profile in Prisme's models window, or ask Claude to call `list_profiles`.
- **"Prisme is busy"**: Prisme makes one image at a time, including the ones started from its own window. Wait, or follow it with `get_status`.
- **A `task_id` instead of an image**: the creation took longer than `PRISME_TIMEOUT`. Ask Claude to call `get_status` with it, or raise `PRISME_TIMEOUT` (some MCP clients stop waiting after about a minute, so keep it lower than their limit).
- **"only images inside … can be edited"**: copy the image into `PRISME_OUTPUT_DIR` first. The server reads no other file.
- **"cannot edit images"**: the selected models cannot edit (Z-Image, or Qwen-Image without its vision file). Choose a FLUX.2 klein or Qwen-Image profile.
- **Nothing in Claude**: run `server.py --check` with the same Python as in the config, and look at Claude Desktop's MCP logs.

---

## Français

Permet à Claude (Claude Desktop ou Claude Code) de créer et de modifier des images avec [Prisme](../README.fr.md), sur ton ordinateur. Le serveur parle à l'API locale de Prisme (`http://127.0.0.1:7861`) : les descriptions et les images ne quittent pas ton PC.

### Outils

| Outil | Rôle |
|---|---|
| `generate_image(prompt, width, height, seed, model)` | Crée une image. Largeur et hauteur : multiples de 16 entre 256 et 2048 (1024 × 1024 par défaut). `model` est facultatif : un fichier de modèle de dessin donné par `list_models`, utilisé pour cette image seulement. |
| `edit_image(image_path, instruction)` | Modifie un PNG ou un JPEG du dossier `PRISME_OUTPUT_DIR`, en gardant ses proportions. Demande un profil qui sait modifier (FLUX.2 klein ou Qwen-Image). |
| `list_models()` | Les fichiers du dossier `models` de Prisme, ceux qui sont choisis, et si la modification est possible. |
| `list_profiles()` | Les profils de modèles par machine, ce qui est téléchargé et le profil suggéré pour cet ordinateur. |
| `get_status(task_id)` | L'état de Prisme ; avec un `task_id`, l'image terminée ou son avancement. |

Chaque image est copiée dans `PRISME_OUTPUT_DIR` et montrée à Claude. Si une création dure plus que `PRISME_TIMEOUT`, l'outil renvoie un `task_id` : Claude appelle ensuite `get_status` pour récupérer l'image.

### Installation

1. Lance Prisme et télécharge un profil de modèles (**Télécharger les modèles**, puis **Télécharger ce profil**).
2. Installe le serveur MCP avec Python 3.10 ou plus récent, dans son propre environnement :

   ```bash
   python3 -m venv mcp/.venv
   mcp/.venv/bin/pip install -r mcp/requirements.txt
   mcp/.venv/bin/python mcp/server.py --check
   ```

   Sous Windows : `py -3 -m venv mcp\.venv`, puis `mcp\.venv\Scripts\pip install -r mcp\requirements.txt` et `mcp\.venv\Scripts\python mcp\server.py --check`. La vérification affiche l'adresse, le délai, le dossier des images et les cinq outils.

Facultatif : `pip install Pillow` dans le même environnement montre les grandes images à Claude sous forme d'aperçu JPEG plus léger ; sans lui, une image de plus de 900 Ko n'est donnée que par son chemin.

### Configuration

| Variable | Par défaut | Rôle |
|---|---|---|
| `PRISME_URL` | `http://127.0.0.1:7861` | Adresse de Prisme. Seul cet ordinateur est accepté (`127.0.0.1`, `localhost`). |
| `PRISME_TIMEOUT` | `120` | Secondes d'attente d'une image avant de renvoyer un `task_id`. |
| `PRISME_OUTPUT_DIR` | `~/Prisme-MCP` | Dossier où les images sont copiées. C'est aussi le seul dossier que `edit_image` peut lire. |

**Claude Desktop** : ajoute le bloc `mcpServers` ci-dessus à `claude_desktop_config.json` (**Réglages → Développeur → Modifier la configuration**), avec les chemins complets de ta copie, puis relance Claude Desktop.

**Claude Code** :

```bash
claude mcp add prisme -e PRISME_TIMEOUT=300 -- /chemin/vers/prisme/mcp/.venv/bin/python /chemin/vers/prisme/mcp/server.py
```

Vérifie avec `claude mcp list`.

### Exemple

> Crée avec Prisme une image 1024 × 768 d'un renard dans la neige au coucher du soleil, puis ajoute une écharpe rouge au renard.

Claude appelle `generate_image`, reçoit le fichier enregistré (par exemple `~/Prisme-MCP/image_20261108_120000.png`), puis appelle `edit_image` avec ce fichier et la consigne.

### Dépannage

- **« Prisme is not running »** : lance Prisme. Si tu as changé son port avec `PRISME_PORT`, mets la même adresse dans `PRISME_URL`.
- **« Prisme is not ready »** : le message liste ce qui manque et le profil suggéré pour ta machine. Installe le moteur et télécharge ce profil dans la fenêtre des modèles de Prisme, ou demande à Claude d'appeler `list_profiles`.
- **« Prisme is busy »** : Prisme fait une image à la fois, y compris celles lancées depuis sa fenêtre. Attends, ou suis-la avec `get_status`.
- **Un `task_id` au lieu d'une image** : la création a duré plus que `PRISME_TIMEOUT`. Demande à Claude d'appeler `get_status` avec, ou augmente `PRISME_TIMEOUT` (certains clients MCP arrêtent d'attendre après environ une minute : reste en dessous de leur limite).
- **« only images inside … can be edited »** : copie d'abord l'image dans `PRISME_OUTPUT_DIR`. Le serveur ne lit aucun autre fichier.
- **« cannot edit images »** : les modèles choisis ne savent pas modifier (Z-Image, ou Qwen-Image sans son fichier de vision). Choisis un profil FLUX.2 klein ou Qwen-Image.
- **Rien dans Claude** : lance `server.py --check` avec le même Python que dans la configuration, et regarde les journaux MCP de Claude Desktop.
