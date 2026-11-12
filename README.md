<p align="center">
  <img src="docs/logo.png" alt="Prisme logo" width="128">
</p>

<h1 align="center">Prisme</h1>

<p align="center">
  <strong>A free, open-source local AI image generator for Windows, macOS and Linux.</strong><br>
  Create and edit images on your own computer: no cloud, no subscription, no complicated setup.
</p>

<p align="center">
  <a href="https://github.com/d3Ita/prisme/releases/latest"><img src="https://img.shields.io/github/v/release/d3Ita/prisme?label=version&color=6d5dfc" alt="Latest version"></a>
  <a href="https://github.com/d3Ita/prisme/actions/workflows/tests.yml"><img src="https://github.com/d3Ita/prisme/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a855f7" alt="MIT license"></a>
  <br>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="macOS on Apple Silicon">
  <img src="https://img.shields.io/badge/Linux-x64-FCC624?logo=linux&logoColor=black" alt="Linux x64">
  <img src="https://img.shields.io/badge/GPU-CUDA%20%7C%20Metal%20%7C%20Vulkan-76B900" alt="CUDA, Metal and Vulkan">
  <a href="https://github.com/leejet/stable-diffusion.cpp"><img src="https://img.shields.io/badge/engine-stable--diffusion.cpp-555" alt="stable-diffusion.cpp engine"></a>
  <img src="https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white" alt="Python 3.12 and 3.13">
  <img src="https://img.shields.io/badge/UI-English%20%7C%20French-0055A4" alt="English and French interface">
</p>

<p align="center">
  <strong>English</strong> · <a href="README.fr.md">Français</a>
</p>

<p align="center">
  <a href="https://d3ita.github.io/prisme/"><strong>Website</strong></a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#choosing-models-for-your-machine">Models</a> ·
  <a href="#phone-access">Phone access</a> ·
  <a href="#using-prisme-with-claude-via-mcp">Claude (MCP)</a> ·
  <a href="#security">Security</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="#build-from-source">Build</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="CHANGELOG.md">Changelog</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

![Prisme demo: a short idea, enhanced, generated, then edited](docs/demo.gif)

## Why Prisme?

Most local image tools ask you to install Python, manage dependencies, or wire nodes together. Prisme is a single 11 MB desktop app for Windows, macOS and Linux: download it, let it fetch the engine and the recommended models in a few clicks, and start creating. An internet connection is needed only once, for those downloads: after that, Prisme works offline. Everything runs on your own GPU through [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp). No account, no subscription, and your images never leave your PC.

| | Prisme | Node-based tools (ComfyUI…) |
|---|---|---|
| Install | One program, engines installed in one click | Python, dependencies, custom nodes |
| Learning curve | A conversation: type, press Enter, get your image | Graphs of nodes |
| Phone access | Built in | Extra setup |
| Advanced workflows | Settings, LoRA, samplers | Virtually unlimited |

Prisme aims to be the simplest way to run image models locally, not the most powerful one: an easy alternative to ComfyUI and to cloud image generators.

![How Prisme works: your browser, phone or Claude talk to Prisme, which drives the engines and models on your computer](docs/schemas/fonctionnement-en.svg)

### Who is Prisme for?

- **People discovering local AI image generation**, who want results without learning a node editor
- **Creators** who want to keep their prompts and images private, on their own machine
- **Anyone tired of subscriptions and credits** on cloud image generators
- **Families and small teams** who want to use one PC's graphics card from their phones at home

## Features

- **Create** images from a description, 1 to 4 per run
- **Enhance prompts** with a local language model: a short idea becomes a detailed description, and an edit request becomes a precise instruction that keeps the rest of the image intact
- **Edit** an existing image: click **Edit** (Modifier) under a result, or drag, paste or attach any picture
- **Enlarge** a finished image 4 times with Real-ESRGAN: one click under the image, details stay sharp
- **Formats**: square, landscape, portrait, or the starting image's proportions
- **Conversation layout**: your requests and Prisme's images follow each other like a chat, with search, a full-screen viewer, reuse of a prompt and delete to the Recycle Bin or Trash
- **Light and dark themes**, or follow the system
- **English and French interface**, following the device's language or chosen in the settings
- **Settings**: models, LoRA, steps, CFG, sampler, sigmas, memory options
- **Phone access** on the same Wi-Fi: type the address, approve the device on the PC
- **Automatic engine install** on first launch, from pinned official releases verified by SHA-256: CUDA for NVIDIA cards, Vulkan for AMD and Intel
- **Model downloads in the app**: one click fetches the recommended official models, resumes if interrupted and checks each file
- **Remove models in the app**: free disk space from the models window, without opening the `models` folder

## Screenshots

<table>
  <tr>
    <td><img src="docs/captures/ordinateur-sombre.png" alt="Prisme in dark mode: a request and its image, like a chat"></td>
    <td><img src="docs/captures/modeles.png" alt="Recommended models window, with one-click downloads"></td>
  </tr>
  <tr>
    <td align="center">Dark theme on a computer</td>
    <td align="center">Recommended models, downloaded in one click</td>
  </tr>
</table>
<table>
  <tr>
    <td><img src="docs/captures/telephone.png" alt="Prisme on a phone" width="260"></td>
    <td><img src="docs/captures/telephone-options.png" alt="Phone options panel: format, number of images, variant" width="260"></td>
  </tr>
  <tr>
    <td align="center">On a phone, over the home Wi-Fi</td>
    <td align="center">Format and number of images in the options panel</td>
  </tr>
</table>

## Requirements

| System | Download | GPU | Status |
|---|---|---|---|
| Windows 10 or 11 | `Prisme.exe` | NVIDIA (CUDA), or AMD and Intel (Vulkan); 8 GB of VRAM or more recommended | Tested |
| macOS 13 or later | `Prisme-macOS-arm64.dmg` | Apple Silicon (M1 or later, Metal), 16 GB of memory or more recommended | Tested on M3 |
| Linux x64 (Ubuntu 24.04 or similar) | `Prisme-Linux-x64.tar.gz` | Any GPU with a Vulkan driver | Experimental |

You also need models compatible with stable-diffusion.cpp (GGUF or safetensors, see [Choosing models for your machine](#choosing-models-for-your-machine)) and an internet connection on first launch, to install the engines.

Prisme drives models that use a diffusion model, an LLM text encoder (`--llm`), a VAE and, for editing, an image encoder (`--llm_vision`). The interface is in English and French.

### Tested configuration

| Graphics card | System memory | Models | Time per 1024 × 1024 image |
|---|---|---|---|
| NVIDIA RTX 4070 SUPER, 12 GB (CUDA, Windows 11) | 32 GB | Recommended set: drawing model Q4_K, text model Q8_0, vision F16 | Creation 25 to 50 s, edit 45 to 90 s, model loading included |
| Same card with the Vulkan engine | 32 GB | Same models | About 50 s for a creation, model loading included |
| NVIDIA RTX 4070 SUPER, 12 GB (CUDA, Windows 11) | 32 GB | FLUX.2 klein 4B Q8_0, Qwen3 4B Q8_0 (12 GB card profile) | Creation 8 to 10 s, edit 10 to 12 s at 1024 × 768 |
| Apple M3, 18 GB of unified memory (Metal, macOS) | 18 GB (shared) | Full set (before light versions were recommended on Mac) | About 5 minutes for a creation, model loading included |
| NVIDIA RTX 4070 SUPER, 12 GB (CUDA, Windows 11) | 32 GB | Real-ESRGAN x4plus | Enlarging 1280 × 704 to 5120 × 2816: 14 s |

Other cards have not been measured yet. As a guide: with 8 GB of video memory, pick the Q4_K drawing model and the Q4_K_M text model and keep **Offload to the CPU** (Décharger sur le processeur) on; 16 GB of system memory or more helps, since parts of the models wait there. Plan about 16 GB of free disk space for the engine and the recommended models. Results on other hardware are welcome in [Discussions](https://github.com/d3Ita/prisme/discussions/categories/show-and-tell).

## Quick start

![Get started in 4 steps: download, install the engine, pick your machine, describe the image](docs/schemas/demarrage-en.svg)

1. Download the file for your system from the [website](https://d3ita.github.io/prisme/#download) or the [Releases](../../releases) page. The website keeps a copy of the latest release, which still works when GitHub's download links are down (checksums in [SHA256SUMS.txt](https://d3ita.github.io/prisme/telechargements/SHA256SUMS.txt)).
2. Start Prisme and click **Install the engine** (Installer le moteur): Prisme downloads stable-diffusion.cpp once (about 925 MB on Windows with an NVIDIA card, under 40 MB otherwise). Without the NVIDIA driver, Prisme picks the Vulkan version; set `PRISME_ACCELERATION=cuda` or `vulkan` to force a choice.
3. Click **Download the models** (Télécharger les modèles), then **Download all** (Tout télécharger) to get the [models for your machine](#choosing-models-for-your-machine) and the text engine used by **Enhance** (5 to 13 GB depending on the profile). Prisme selects them in the settings by itself.
4. To use your own models instead, put them in a `models` folder (LoRA go in `models/loras`): next to the program on Windows and Linux, in `~/Prisme/models` on macOS. Then click **Choose models** (Choisir les modèles) and pick a file for each role.

```
Prisme.exe    (prisme on Linux, Prisme.app on macOS)
models/       your .gguf / .safetensors models
  loras/      your LoRA (optional)
sd/           image engine, installed by Prisme
llama/        text engine, installed by Prisme if you enable it
images/       your images
```

Engines come from pinned official releases of [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) and [llama.cpp](https://github.com/ggml-org/llama.cpp). Prisme checks the SHA-256 of each file before installing it.

### Windows

`Prisme.exe` is not code-signed (a signing certificate costs money) and is built with PyInstaller, which antivirus software sometimes flags by mistake. If **Windows SmartScreen** appears, click **More info**, then **Run anyway**. To check that your file is the published one, compare its SHA-256 with the one in the release notes:

```powershell
Get-FileHash .\Prisme.exe -Algorithm SHA256
```

### macOS

Open `Prisme-macOS-arm64.dmg` and drag **Prisme** onto the **Applications** folder next to it. Launched from Downloads, macOS would run it from a temporary copy and Prisme could neither update itself nor stay connected to Claude. The app is not notarized, so macOS blocks it on first launch: open **System Settings → Privacy & Security** and click **Open Anyway**, or run once:

```bash
xattr -dr com.apple.quarantine /Applications/Prisme.app
```

Prisme keeps its data in `~/Prisme` (models, engines, images and settings), because an app bundle cannot hold them.

### Linux

```bash
tar -xzf Prisme-Linux-x64.tar.gz
./prisme
```

The engines need OpenMP and Vulkan. If Prisme reports missing libraries, install them with `sudo apt install libgomp1 libvulkan1`, plus the Vulkan driver of your GPU (for example `mesa-vulkan-drivers`). Prisme opens as an app window in Chrome, Chromium, Edge or Brave when one is installed, otherwise in your default browser.

You can also build Prisme yourself or run `app/serveur.py` directly on any system.

## Choosing models for your machine

Open the models window (**Download the models**, or **Settings → Models → Download**) and pick the card that matches your computer. Prisme reads your graphics card and memory with the tools already on your system (`nvidia-smi`, `rocm-smi`, the Windows registry, `/sys` and `/proc/meminfo` on Linux, `vulkaninfo`, `sysctl` on macOS) and marks the profile it recommends. Nothing is sent anywhere. If it can't read everything, choose the profile yourself.

**Download this profile** shows the size and the free disk space first, then fetches the whole set, checks each file's SHA-256 and selects it in the settings. Files you already have are not downloaded again, and the text engine used by **Enhance** is added if it's missing. **Choose models one by one (advanced mode)** lists every file.

The profiles for your machine use only **Apache-2.0** models, which allow commercial use, including of the images you create: [FLUX.2 klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) creates and edits images, [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) understands the description (and powers **Enhance**), and the [FLUX.2 small decoder](https://huggingface.co/black-forest-labs/FLUX.2-small-decoder) produces the final image.

| Profile | Hardware | FLUX.2 klein 4B | Qwen3 4B | Download |
|---|---|---|---|---|
| CPU only | No dedicated graphics card (or integrated graphics), 8 GB of RAM | Q4_0 | Q4_K_M | 5.2 GB |
| 4 to 6 GB card | 4 to 6 GB of video memory | Q4_0 | Q4_K_M | 5.2 GB |
| 8 GB card | 8 GB of video memory (or more, with less than 24 GB of RAM) | Q8_0 | Q4_K_M | 7.0 GB |
| 12 GB card | 12 GB of video memory and 24 GB of RAM or more | Q8_0 | Q8_0 | 8.8 GB |
| 16 GB card or more | 16 GB of video memory or more and 24 GB of RAM or more | BF16 (original) | Q8_0 | 12.3 GB |
| 8 GB Mac | Apple Silicon, 8 GB of unified memory | Q4_0 | Q4_K_M | 5.2 GB |
| 16 GB Mac | Apple Silicon, 16 to 24 GB of unified memory | Q8_0 | Q4_K_M | 7.0 GB |
| 32 GB Mac or more | Apple Silicon, 32 GB of unified memory or more | Q8_0 | Q8_0 | 8.8 GB |

The **12 GB card** profile is tested: creation in 8 to 10 s and edit in 10 to 12 s at 1024 × 768 on an RTX 4070 SUPER, download included in the app. The other FLUX.2 klein profiles use the same model in other sizes, following the [stable-diffusion.cpp documentation](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/flux2.md); they stay marked **Experimental** until they are tested on that hardware. The CPU-only profile also depends on the engine running without a graphics card, which has not been tested yet.

**Other choices**, never suggested automatically:

| Option | What it is | Download | License |
|---|---|---|---|
| Z-Image Turbo | Another image style, creation only (no editing) | 6.7 GB | Apache-2.0 |
| Qwen-Image · 8 GB, 12 GB, 16 GB | Qwen-Image 2.1 Turbo: very good quality, tested (25 to 50 s per image on an RTX 4070 SUPER) | 10.7, 14.7 or 18.1 GB | [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE): research or evaluation only, no commercial use of the models or the images |

Before downloading a Qwen-Image profile, Prisme asks you to accept its license; the server refuses the download otherwise. The catalog, with every file's link, size, SHA-256 and license, is in [`app/modeles.json`](app/modeles.json).

**Enlarging** uses [Real-ESRGAN x4plus](https://huggingface.co/Comfy-Org/Real-ESRGAN) (67 MB, BSD-3-Clause), downloaded the first time you click **Enlarge** under an image.

**Removing a model**: in the models window, **Choose or delete models one by one (advanced mode)** shows a delete button next to each installed file, including the ones you added by hand. The file is deleted for good (not moved to the trash, so the space is really freed), after a confirmation.

### Qwen-Image 2.1 Turbo by hand

If you prefer to download Qwen-Image 2.1 Turbo yourself (after reading [its license](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/LICENSE)):

| Role in Prisme | Recommended file | Where to find it | Lighter option |
|---|---|---|---|
| Drawing model (Modèle de dessin) | `Q5_K`, `Q6_K` or `Q8_0` GGUF | [Qwen-Image-2.1-Turbo-GGUF](https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF) | `Q4_K` |
| Text model (Modèle de texte) | `Qwen3VL-8B-Instruct-Q8_0.gguf` (8.7 GB) | [Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF) | `Q4_K_M` (5 GB): edits look grainier |
| Vision (image encoder, for editing) | `mmproj-Qwen3VL-8B-Instruct-F16.gguf` (1.2 GB) | [Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF) | `mmproj` `Q8_0` |
| VAE | `vae/diffusion_pytorch_model.safetensors` (675 MB) | [Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/tree/main/vae) | |
| Language model (Modèle de langage), for **Enhance** | The same text model and vision files | [Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF) | [Qwen3-VL-4B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF) |

This Turbo model needs few steps. In **Settings → Generation** (Réglages → Génération), use 8 steps, CFG 1, the `euler` method and these sigmas:

```
1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0
```

You can rename the VAE file (for example `qwen-image-vae.safetensors`) so it is easy to spot. Attribution required by its license: "Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) 2026 Hangzhou Tongyi Laboratory Technology Co., Ltd. All Rights Reserved."

## Prompt enhancement

A short prompt ("a cat on a roof at night") usually gives a weaker image than a detailed one. Prisme can rewrite it with a language model running on your PC:

1. Put a GGUF language model in `models` (and its `mmproj` vision file so it can see images).
2. Install the text engine (llama.cpp, about 290 MB, once): **Download all** in the models window does it, or **Settings → Enhancing the description** (Réglages → Amélioration de la description), with the **Built in** (Intégré) engine, then **Install the engine** (Installer le moteur). Downloaded models are chosen for you; otherwise choose the model and vision file there.
3. Click **Enhance** (Améliorer) in the writing area. **Undo** (Rétablir) brings your text back.

With a starting image, the model looks at the picture and writes an edit instruction that only describes what changes. The language model runs only for the time of the request, then frees the GPU for generation. If you already use [Ollama](https://ollama.com), you can select it instead.

## Phone access

Network access is **off by default**. Turn it on in **Settings → Application → Phone access** (Réglages → Application → Accès depuis le téléphone), restart Prisme and allow it through your firewall if your system asks. The **Phone** (Téléphone) button then shows the address to type, for example `192.168.1.22:7861`.

On the phone, open that address: it shows a 4-digit code, and Prisme asks you on the PC to **Approve** (Autoriser) the device after checking the code matches. The phone then stays connected. A QR code is also available for a direct connection. Don't enable network access on public Wi-Fi: the connection is not encrypted.

The QR code link contains an access code stored in `app/code-acces.txt`: delete that file and restart Prisme to create a new code and disconnect the devices already linked.

To stop Prisme, click **Quit** (Quitter) at the top of the window or **Quit Prisme** in **Settings → Application**, or close its window: the server and its engines shut down a few seconds later. While Claude Desktop is open, the Task Manager may also show `Prisme.exe --mcp` processes: they are Claude's connection to Prisme, started and stopped by Claude, and they use almost no resources.

## Using Prisme with Claude via MCP

![Prisme with Claude: you ask Claude, Claude calls Prisme, the image comes back; licenses are approved in Prisme's window](docs/schemas/claude-en.svg)

If Claude Desktop or Claude Code is installed on your computer, Prisme offers **Connect to Claude** (Connecter à Claude) in a banner and in **Settings → Application**. One click adds Prisme to Claude's configuration (a copy of the original is kept); restart Claude, then just ask: *"Create an image of a fox in the snow with Prisme"*. Nothing else to install: the MCP server is built into the program (`Prisme.exe --mcp`), and Claude starts Prisme by itself if it isn't open.

Claude can then:

- **create and edit images** (`generate_image`, `edit_image`), and follow long ones (`get_status`);
- **set Prisme up**: see the profile recommended for your machine (`list_profiles`), install the engines (`install_engine`) and download a profile (`download_profile`);
- **download another model** that you name (`download_model`, a `.gguf` or `.safetensors` link).

**You stay in control of licenses.** Profiles under an open license (Apache-2.0) are downloaded directly. For a non-commercial license (Qwen-Image) or a model outside Prisme's catalog, Prisme opens a request in its own window, with the license or a warning (license and content not checked); only your click there starts the download. Claude cannot answer for you.

The server only talks to Prisme on `127.0.0.1`. Images Claude asks for go to the `images-claude` folder, next to Prisme's `images` folder (`~/Prisme/images-claude` on a Mac); Claude neither reads nor edits the images created in Prisme's window. Manual setup, settings and troubleshooting: [MCP README](mcp/README.md).

## Security

- The server only listens on your PC unless phone access is enabled.
- Other devices need a random 128-bit access code, received through the QR code or after you approve them on the PC. After 10 wrong codes or refused requests, a device is blocked for 15 minutes.
- Websites open in your browser can neither control Prisme nor read its data: requests from another origin or host name are rejected.
- Settings, models and folders are only reachable from the PC.
- Once per launch, Prisme asks GitHub for the latest version number to tell you about updates. Nothing else is sent; turn it off in **Settings → Application** (Réglages → Application).
- **Update** in that notice downloads the new version only from Prisme's GitHub releases, checks its SHA-256 published by GitHub, then replaces the program and restarts it. Settings, images, engines and models are kept. If the replacement fails (antivirus, file in use), the old version starts again and says so, with a link to download the new one; details are in `app/mise-a-jour.log`.

## Build from source

On the system you build for, with Python 3.12 or later, PyInstaller and Pillow installed:

```bash
python3 construire.py
```

On Windows, `powershell -ExecutionPolicy Bypass -File .\construire.ps1` first creates that environment in `.construction/`. The build runs the tests, then makes `Prisme.exe` (Windows), `dist/Prisme-macOS-arm64.dmg` and `.zip` (macOS) or `dist/Prisme-Linux-x64.tar.gz` (Linux). If a test fails, nothing is built. To run without building: `python3 app/serveur.py`.

How the pieces fit together (interface, server, engines, models and images) is described with a diagram in [docs/architecture.md](docs/architecture.md).

### Tests

The tests use Python's built-in `unittest`: nothing to install. From the repository folder:

```bash
python3 -m unittest discover -s tests -v
```

On Windows, type `py -3` instead of `python3`. To run a single test class, for example the model catalog tests:

```bash
python3 -m unittest tests.test_serveur.ModelesConseillesTest -v
```

The tests cover settings validation, image metadata, engine installation, archive extraction, downloads (retries, resume, checksums), model links, updates and access protections. They run in a temporary folder and never touch your settings, models or images. GitHub runs them on Windows and Linux, with Python 3.12 and 3.13, for every push, then builds both versions. The macOS version is built on demand.

| File | Role |
|---|---|
| `app/serveur.py` | Local server, Python standard library only: API, engines, network access |
| `app/index.html` | The whole interface: HTML, CSS and JavaScript with no dependency |
| `app/modeles.json` | Catalog of downloadable models and profiles by hardware |
| `app/icone.py` | Program icon and splash screen, made from the logo |
| `app/mcp_prisme.py` | MCP server built into Prisme (`--mcp`), standard library only |
| `app/agrandir.py` | Enlarging an image with Real-ESRGAN |
| `mcp/` | MCP README, and a launcher for developers |
| `construire.py` | Builds Prisme for the current system |
| `construire.ps1` | Prepares a Python environment on Windows, then runs `construire.py` |
| `tests/test_serveur.py` | Server tests |
| `tests/test_mcp.py` | MCP server tests, against a fake Prisme |
| `tests/test_protocole_mcp.py` | The MCP server with the official MCP client (run when the `mcp` package is installed) |
| `tests/test_agrandir.py`, `tests/test_supprimer_modele.py` | Enlarging and model removal, with a fake engine |
| `docs/architecture.md` | Architecture diagram and explanation |

## Roadmap

Planned, in no fixed order. Ideas and votes are welcome in [Discussions](https://github.com/d3Ita/prisme/discussions/categories/ideas).

- ~~**Model profiles by hardware**~~: done in 1.9.0 (see [Choosing models for your machine](#choosing-models-for-your-machine)).
- ~~**MCP server for Claude**~~: done in 1.9.0 (see [Using Prisme with Claude via MCP](#using-prisme-with-claude-via-mcp)).
- **Faster successive images**: keep the models loaded between two creations instead of loading them each time.
- ~~**Remove models from the app**~~: done in 1.10.0 (see [Choosing models for your machine](#choosing-models-for-your-machine)).
- ~~**Upscaling**~~: done in 1.10.0, with Real-ESRGAN x4.

## FAQ

**Is Prisme free?**
Yes. Prisme is open source under the MIT license, with no account, no subscription and no credits. The models it offers are free to download too.

**Can I use the images commercially?**
With the profiles for your machine (FLUX.2 klein 4B, Qwen3 4B, Apache-2.0), yes. With the Qwen-Image options, no: their license only allows research or evaluation. Prisme itself (MIT) adds no restriction. You remain responsible for what your images show.

**Does it work offline?**
Yes, once the engine and the models are downloaded. Image creation, editing and prompt enhancement all run on your computer. The only optional connection is a version check on GitHub at launch, which you can turn off.

**What hardware do I need?**
A graphics card with 8 GB of video memory or more: NVIDIA (CUDA) or AMD and Intel (Vulkan) on Windows, any Vulkan card on Linux, or an Apple Silicon Mac. See [Requirements](#requirements).

**Which models does it support?**
Models that stable-diffusion.cpp can run with an LLM text encoder, in GGUF or safetensors format, plus LoRA. Prisme downloads a set suited to your machine: see [Choosing models for your machine](#choosing-models-for-your-machine).

**Is it an alternative to ComfyUI?**
For creating and editing images from a description, yes, with a much simpler interface. For complex multi-step workflows, ComfyUI stays more powerful.

**Do my images leave my computer?**
No. Prompts, models and images stay on your PC. Other devices on your network can connect only if you enable phone access and approve them.

**Can I use it from my phone?**
Yes, on the same Wi-Fi: see [Phone access](#phone-access).

**Is the interface in English?**
Yes. Prisme follows your browser's language (English, or French for French browsers), and you can choose it in **Settings → Application → Language**. On a phone, it follows the phone's language.

## Responsible use

Prisme is designed for legal and ethical use. Each user is solely responsible for the images they create, edit or share with Prisme, and must respect the law of their country and the rights and image of other people.

The author of Prisme accepts no liability for any abusive, illegal or unethical use of the software. As stated in the [MIT license](LICENSE), Prisme is provided "as is", without warranty of any kind.

## License

Prisme is released under the [MIT license](LICENSE).
