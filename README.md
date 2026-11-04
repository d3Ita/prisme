<p align="center">
  <img src="docs/logo.png" alt="Prisme logo" width="128">
</p>

<h1 align="center">Prisme</h1>

<p align="center">
  <strong>Local AI image generation and editing for Windows. One exe, no Python, nothing sent to the cloud.</strong>
</p>

<p align="center">
  <a href="https://github.com/d3Ita/prisme/releases/latest"><img src="https://img.shields.io/github/v/release/d3Ita/prisme?label=version&color=6d5dfc" alt="Latest version"></a>
  <a href="https://github.com/d3Ita/prisme/actions/workflows/tests.yml"><img src="https://github.com/d3Ita/prisme/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a855f7" alt="MIT license"></a>
  <br>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?logo=nvidia&logoColor=white" alt="NVIDIA GPU">
  <a href="https://github.com/leejet/stable-diffusion.cpp"><img src="https://img.shields.io/badge/engine-stable--diffusion.cpp-555" alt="stable-diffusion.cpp engine"></a>
  <img src="https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white" alt="Python 3.12 and 3.13">
  <img src="https://img.shields.io/badge/UI-French-0055A4" alt="French interface">
</p>

<p align="center">
  <strong>English</strong> · <a href="README.fr.md">Français</a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#phone-access">Phone access</a> ·
  <a href="#security">Security</a> ·
  <a href="#build-from-source">Build</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

![Prisme demo: a short idea, enhanced, generated, then edited](docs/demo.gif)

## Why Prisme?

Most local image tools ask you to install Python, manage dependencies, or wire nodes together. Prisme is a single 9 MB exe: download it, add your models, click **Install engine**, and start creating. Everything runs on your own GPU through [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp). No account, no subscription, and your images never leave your PC.

| | Prisme | Node-based tools (ComfyUI…) |
|---|---|---|
| Install | One exe, engines installed in one click | Python, dependencies, custom nodes |
| Learning curve | A text box and a Generate button | Graphs of nodes |
| Phone access | Built in | Extra setup |
| Advanced workflows | Settings, LoRA, samplers | Virtually unlimited |

Prisme aims to be the simplest way to run image models locally, not the most powerful one.

## Features

- **Create** images from a description, 1 to 4 per run
- **Enhance prompts** with a local language model: a short idea becomes a detailed description, and an edit request becomes a precise instruction that keeps the rest of the image intact
- **Edit** an existing image: drag, paste or pick a starting image
- **Formats**: square, landscape, portrait, or the starting image's proportions
- **History** with search, full-screen viewer, reuse of prompt and seed, and delete to the Recycle Bin
- **Settings**: models, LoRA, steps, CFG, sampler, sigmas, memory options
- **Phone access** on the same Wi-Fi: type the address, approve the device on the PC
- **Automatic engine install** on first launch, from pinned official releases verified by SHA-256

## Requirements

- Windows 10 or 11 with an NVIDIA GPU (8 GB of VRAM or more recommended)
- Models compatible with stable-diffusion.cpp, in GGUF or safetensors format
- An internet connection on first launch, to install the engines

Prisme drives models that use a diffusion model, an LLM text encoder (`--llm`), a VAE and, for editing, an image encoder (`--llm_vision`). The interface is in French.

## Quick start

1. Download `Prisme.exe` from the [Releases](../../releases) page.
2. Put your models in a `models` folder next to the exe (LoRA go in `models/loras`).
3. Run `Prisme.exe` and click **Installer le moteur** (Install engine): Prisme downloads stable-diffusion.cpp once, about 925 MB.
4. Click **Choisir les modèles** (Choose models) and pick a file for each role.

```
Prisme.exe
models/    your .gguf / .safetensors models
  loras/   your LoRA (optional)
sd/        image engine, installed by Prisme
llama/     text engine, installed by Prisme if you enable it
images/    your images
```

### Windows or antivirus warnings

`Prisme.exe` is not code-signed (a signing certificate costs money) and is built with PyInstaller, which antivirus software sometimes flags by mistake. If **Windows SmartScreen** appears, click **More info**, then **Run anyway**. To check that your file is the published one, compare its SHA-256 with the one in the release notes:

```powershell
Get-FileHash .\Prisme.exe -Algorithm SHA256
```

You can also build the exe yourself or run `app\serveur.py` directly.

## Prompt enhancement

A short prompt ("a cat on a roof at night") usually gives a weaker image than a detailed one. Prisme can rewrite it with a language model running on your PC:

1. Put a GGUF language model in `models` (and its `mmproj` vision file so it can see images).
2. In **Réglages → Amélioration de la description**, keep the **Intégré** engine, click **Installer le moteur** (llama.cpp, about 290 MB, once), then choose the model and vision file.
3. Click **Améliorer** above the prompt. **Rétablir** brings your text back.

With a starting image, the model looks at the picture and writes an edit instruction that only describes what changes. The language model runs only for the time of the request, then frees the GPU for generation. If you already use [Ollama](https://ollama.com), you can select it instead.

## Phone access

Network access is **off by default**. Turn it on in **Réglages → Application → Accès depuis le téléphone**, restart Prisme and allow it through the Windows firewall. The **Téléphone** button then shows the address to type, for example `192.168.1.22:7861`.

On the phone, open that address: it shows a 4-digit code, and Prisme asks you on the PC to **Autoriser** (approve) the device after checking the code matches. The phone then stays connected. A QR code is also available for a direct connection. Don't enable network access on public Wi-Fi: the connection is not encrypted.

To stop Prisme, click **Quitter** or close its window: the server shuts down a few seconds later.

## Security

- The server only listens on your PC unless phone access is enabled.
- Other devices need a random 128-bit access code, received through the QR code or after you approve them on the PC. After 10 wrong codes or refused requests, a device is blocked for 15 minutes.
- Websites open in your browser can neither control Prisme nor read its data: requests from another origin or host name are rejected.
- Settings, models and folders are only reachable from the PC.

## Build from source

With Python 3 installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\construire.ps1
```

The script creates an environment in `.construction/`, installs PyInstaller and Pillow, runs the tests, then builds `Prisme.exe`. If a test fails, no exe is built. To run without building: `py -3 app\serveur.py`.

```powershell
py -3 -m unittest discover -s tests -v
```

The tests cover settings validation, image metadata, engine installation and access protections. They run in a temporary folder and also run on GitHub for every push.

| File | Role |
|---|---|
| `app/serveur.py` | Local server, Python standard library only: API, engines, network access |
| `app/index.html` | The whole interface: HTML, CSS and JavaScript with no dependency |
| `app/icone.py` | Exe icon and splash screen, made from the logo |
| `construire.ps1` | Builds `Prisme.exe` |
| `tests/test_serveur.py` | Server tests |

## Responsible use

Prisme is designed for legal and ethical use. Each user is solely responsible for the images they create, edit or share with Prisme, and must respect the law of their country and the rights and image of other people.

The author of Prisme accepts no liability for any abusive, illegal or unethical use of the software. As stated in the [MIT license](LICENSE), Prisme is provided "as is", without warranty of any kind.

## License

Prisme is released under the [MIT license](LICENSE).
