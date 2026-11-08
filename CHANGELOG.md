# Changelog

All notable changes to Prisme. Downloads are on the [Releases](https://github.com/d3Ita/prisme/releases) page.

## Not released yet

- **Models window**: the text encoder is now called **Text model**, and each role says what it is for (the text model also powers **Enhance**).
- The **text engine** (llama.cpp) needed by **Enhance** can be installed from the models window, and **Download all** installs it too. Before, it was only offered in Settings.

## 1.8.4 · 2026-11-08

- **Sturdier downloads**: when GitHub or Hugging Face answer with a temporary error (504, 503, timeout…) or the connection drops, Prisme tries again by itself, and model downloads resume where they stopped. If GitHub's direct release link keeps failing, the engine is downloaded through the GitHub API instead; the SHA-256 check guarantees it is the same file.
- Each engine file keeps its GitHub API backup link, so no extra request is needed when github.com fails; a `GITHUB_TOKEN` variable, if present, is used for api.github.com only.
- Clearer message when a download still fails: which server, which error, and to try again later.
- Phone access: a request refused by the PC now always receives its answer, instead of the connection being cut abruptly on Windows.

## 1.8.3 · 2026-11-05

- **One-click updates**: the new-version notice has an **Update** button. Prisme downloads the new version from its GitHub releases only, checks the SHA-256 published by GitHub, replaces the program and restarts by itself; the open window reloads on the new version. Available from this version on, in the built programs (not when running the Python script).
- Linux and macOS: Prisme can restart right away on the port it just used.

## 1.8.2 · 2026-11-05

- **Recommended models adapted to the machine**: Prisme reads the memory (graphics card, RAM, or a Mac's shared memory) and recommends light versions when it's tight (about 10.7 GB instead of 14.7 GB). This avoids freezes and slowdowns, for example on an 18 GB Mac. A light vision file (Q8_0) joins the catalog.
- A downloaded model is now selected right away in the settings.
- **The computer stays usable during a creation**: the engines run at a lower priority and leave one processor core free. Creation speed is unchanged when nothing else is running.

## 1.8.1 · 2026-11-05

- **macOS (and some Linux systems)**: downloads of the engine, the models and the version check failed with `CERTIFICATE_VERIFY_FAILED`. Prisme now loads the system's certificates when its bundled Python finds none.
- English interface: no space before punctuation anymore.
- GitHub builds now install the image engine over https on each system, to catch this kind of problem before a release.

## 1.8.0 · 2026-11-05

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
