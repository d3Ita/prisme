# Changelog

All notable changes to Prisme are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). Downloads are on the [Releases](https://github.com/d3Ita/prisme/releases) page.

## [Unreleased]

### Added

- **Model profiles by hardware**: the models window offers eight profiles (CPU only, 4 to 6 GB, 8 GB, 12 GB and 16 GB cards, 8 GB, 16 GB and 32 GB Macs), each with its size, indicative speed, licenses and a **Recommended for your machine** badge. **Download this profile** fetches the whole set; files already present are only selected, not downloaded again. The catalog lives in `app/modeles.json`.
- Experimental **Z-Image Turbo** profiles for computers without a dedicated graphics card, 4 to 6 GB cards and 8 GB Macs (creation only, not tested with Prisme yet).
- `GET /api/profils` (PC only, read-only): the profiles, what is already downloaded and the suggested profile.
- **MCP server for Claude** (`mcp/`): Claude Desktop or Claude Code can create and edit images with Prisme on this computer, with `generate_image`, `edit_image`, `list_models`, `list_profiles` and `get_status`. Long creations return a task id to follow with `get_status`. It only talks to Prisme on `127.0.0.1` and only edits images from its own folder.
- `POST /api/generer` accepts an optional `modele`: a drawing model file from `models/`, used for that creation only (for the MCP server's `model` parameter).
- Hardware detection reads AMD and Intel cards too (`rocm-smi`, `/sys` on Linux, the Windows registry, `vulkaninfo`). It only suggests a profile; nothing is sent.

### Changed

- The per-file list moves to **Choose models one by one (advanced mode)**.
- Generation settings follow the chosen drawing model (8 steps and its own sigmas), unless you changed them yourself.

### Fixed

- Editing an image with models that cannot edit now explains what to do instead of naming a missing setting.

## [1.8.5] - 2026-11-08

### Added

- The **text engine** (llama.cpp) needed by **Enhance** can be installed from the models window, and **Download all** installs it too. Before, it was only offered in Settings.

### Changed

- **Models window**: the text encoder is now called **Text model**, and each role says what it is for (the text model also powers **Enhance**).

## [1.8.4] - 2026-11-08

### Added

- Each engine file keeps its GitHub API backup link, so no extra request is needed when github.com fails; a `GITHUB_TOKEN` variable, if present, is used for api.github.com only.

### Fixed

- **Sturdier downloads**: when GitHub or Hugging Face answer with a temporary error (504, 503, timeout…) or the connection drops, Prisme tries again by itself, and model downloads resume where they stopped. If GitHub's direct release link keeps failing, the engine is downloaded through the GitHub API instead; the SHA-256 check guarantees it is the same file.
- Clearer message when a download still fails: which server, which error, and to try again later.
- Phone access: a request refused by the PC now always receives its answer, instead of the connection being cut abruptly on Windows.

## [1.8.3] - 2026-11-05

### Added

- **One-click updates**: the new-version notice has an **Update** button. Prisme downloads the new version from its GitHub releases only, checks the SHA-256 published by GitHub, replaces the program and restarts by itself; the open window reloads on the new version. Available from this version on, in the built programs (not when running the Python script).

### Fixed

- Linux and macOS: Prisme can restart right away on the port it just used.

## [1.8.2] - 2026-11-05

### Added

- **Recommended models adapted to the machine**: Prisme reads the memory (graphics card, RAM, or a Mac's shared memory) and recommends light versions when it's tight (about 10.7 GB instead of 14.7 GB). This avoids freezes and slowdowns, for example on an 18 GB Mac. A light vision file (Q8_0) joins the catalog.

### Changed

- A downloaded model is now selected right away in the settings.

### Fixed

- **The computer stays usable during a creation**: the engines run at a lower priority and leave one processor core free. Creation speed is unchanged when nothing else is running.

## [1.8.1] - 2026-11-05

### Changed

- GitHub builds now install the image engine over https on each system, to catch this kind of problem before a release.

### Fixed

- **macOS (and some Linux systems)**: downloads of the engine, the models and the version check failed with `CERTIFICATE_VERIFY_FAILED`. Prisme now loads the system's certificates when its bundled Python finds none.
- English interface: no space before punctuation anymore.

## [1.8.0] - 2026-11-05

### Added

- **English interface**: Prisme follows the device's language (English, or French on French devices) and the language can be chosen in **Settings → Application → Language**. The phone connection page follows the phone's language.
- Sizes, dates and times are shown in the chosen language.

## [1.7.0] - 2026-11-05

### Added

- **AMD and Intel graphics cards on Windows**: without the NVIDIA driver, Prisme installs the Vulkan engines (about 70 MB). `PRISME_ACCELERATION=cuda` or `vulkan` forces a choice.
- **Model downloads in the app**: **Download the models** fetches official, general-purpose models from Hugging Face, resumes interrupted downloads, checks each file's SHA-256, picks the models in the settings and applies the right generation settings.
- **New version notice**: once per launch, Prisme asks GitHub for the latest version number. It can be turned off in the settings.

### Changed

- The writing area resizes with the window.

## [1.6.0] - 2026-11-05

### Added

- **Light and dark themes**, chosen in the settings or following the system.
- Welcome screen with example prompts.

### Changed

- **Conversation layout**: the writing area is at the bottom and your creations appear above it, like a chat. Enter creates, Shift + Enter adds a line.
- Image tools (edit, reuse, copy, save, delete) appear when hovering an image.
- Plainer wording.
- **Phone layout**: one-line writing area, format and number of images in the options panel, swipe in the viewer, no more horizontal overflow on small screens.
- The phone connection page matches the new look.

## [1.5.0] - 2026-11-04

### Added

- **macOS (Apple Silicon) and Linux versions**, with their official Metal and Vulkan engines.
- Links to recommended official models in the settings and the README.
- Missing Linux libraries are reported with the command to install them.
- Tests on Windows, macOS and Linux; GitHub builds every version.

## [1.4.0] - 2026-11-04

### Added

- Connect a phone by typing only the address: the phone shows a 4-digit code, approved on the PC.
- **Quit** button, and Prisme stops a few seconds after its window closes.

## [1.3.1] - 2026-11-04

### Added

- Logo on the splash and loading screens.

## [1.3.0] - 2026-11-04

### Added

- Engines installed automatically from pinned official releases, verified by SHA-256: only the program and the models need downloading.
- Built-in prompt enhancement with llama.cpp, without Ollama.

## [1.2.3] - 2026-11-04

### Changed

- New logo.

## [1.2.2] - 2026-11-04

### Added

- Automated tests and documentation.

## [1.2.1] - 2026-11-04

### Added

- MIT license.

### Security

- Security hardening.

## [1.2.0] - 2026-11-04

### Changed

- Prompt enhancement adapted to image edits.

## [1.1.0] - 2026-11-04

### Added

- Prompt enhancement with a local language model.

## [1.0.0] - 2026-11-04

### Added

- First version: create and edit images locally with stable-diffusion.cpp, history, settings, LoRA and phone access.

[Unreleased]: https://github.com/d3Ita/prisme/compare/v1.8.5...HEAD
[1.8.5]: https://github.com/d3Ita/prisme/releases/tag/v1.8.5
[1.8.4]: https://github.com/d3Ita/prisme/releases/tag/v1.8.4
[1.8.3]: https://github.com/d3Ita/prisme/releases/tag/v1.8.3
[1.8.2]: https://github.com/d3Ita/prisme/releases/tag/v1.8.2
[1.8.1]: https://github.com/d3Ita/prisme/releases/tag/v1.8.1
[1.8.0]: https://github.com/d3Ita/prisme/releases/tag/v1.8.0
[1.7.0]: https://github.com/d3Ita/prisme/releases/tag/v1.7.0
[1.5.0]: https://github.com/d3Ita/prisme/releases/tag/v1.5.0
[1.4.0]: https://github.com/d3Ita/prisme/releases/tag/v1.4.0
[1.3.1]: https://github.com/d3Ita/prisme/releases/tag/v1.3.1
[1.3.0]: https://github.com/d3Ita/prisme/releases/tag/v1.3.0
[1.2.3]: https://github.com/d3Ita/prisme/releases/tag/v1.2.3
[1.2.2]: https://github.com/d3Ita/prisme/releases/tag/v1.2.2
[1.2.1]: https://github.com/d3Ita/prisme/releases/tag/v1.2.1
