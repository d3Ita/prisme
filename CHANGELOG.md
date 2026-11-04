# Changelog

All notable changes to Prisme. Downloads are on the [Releases](https://github.com/d3Ita/prisme/releases) page.

## Not released yet

- **English interface**: Prisme follows the device's language (English, or French on French devices) and the language can be chosen in **Settings → Application → Language**. The phone connection page follows the phone's language.
- Sizes, dates and times are shown in the chosen language.

## 1.7.0 · 2026-11-05

- **AMD and Intel graphics cards on Windows**: without the NVIDIA driver, Prisme installs the Vulkan engines (about 70 MB). `PRISME_ACCELERATION=cuda` or `vulkan` forces a choice.
- **Model downloads in the app**: **Télécharger les modèles** fetches official, general-purpose models from Hugging Face, resumes interrupted downloads, checks each file's SHA-256, picks the models in the settings and applies the right generation settings.
- **New version notice**: once per launch, Prisme asks GitHub for the latest version number. It can be turned off in the settings.
- The writing area resizes with the window.

## 1.6.0 · 2026-11-05

- **Conversation layout**: the writing area is at the bottom and your creations appear above it, like a chat. Enter creates, Shift + Enter adds a line.
- Image tools (edit, reuse, copy, save, delete) appear when hovering an image.
- Welcome screen with example prompts, and plainer wording.
- **Light and dark themes**, chosen in the settings or following the system.
- **Phone layout**: one-line writing area, format and number of images in the options panel, swipe in the viewer, no more horizontal overflow on small screens.
- The phone connection page matches the new look.

## 1.5.0 · 2026-11-04

- **macOS (Apple Silicon) and Linux versions**, with their official Metal and Vulkan engines.
- Links to recommended official models in the settings and the README.
- Missing Linux libraries are reported with the command to install them.
- Tests on Windows, macOS and Linux; GitHub builds every version.

## 1.4.0 · 2026-11-04

- Connect a phone by typing only the address: the phone shows a 4-digit code, approved on the PC.
- **Quitter** button, and Prisme stops a few seconds after its window closes.

## 1.3.0 – 1.3.1 · 2026-11-04

- Engines installed automatically from pinned official releases, verified by SHA-256: only the program and the models need downloading.
- Built-in prompt enhancement with llama.cpp, without Ollama.
- Logo on the splash and loading screens.

## 1.2.0 – 1.2.3 · 2026-11-04

- Prompt enhancement adapted to image edits.
- Security hardening, MIT license, automated tests and documentation.
- New logo.

## 1.1.0 · 2026-11-04

- Prompt enhancement with a local language model.

## 1.0.0 · 2026-11-04

- First version: create and edit images locally with stable-diffusion.cpp, history, settings, LoRA and phone access.
