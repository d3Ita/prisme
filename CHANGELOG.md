# Changelog

All notable changes to Prisme are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). Downloads are on the [Releases](https://github.com/d3Ita/prisme/releases) page.

## [Unreleased]

## [2.0.0-rc.1] - 2026-11-12

Pre-release of Prisme 2, to try before it is offered as an update.

### Added

- **A real desktop app on Windows and Mac**, in Qt Quick (PySide6) instead of a browser window: its own window and Dock or taskbar icon, light or dark following the system, native file dialogs. The same screens as before: the feed (newest image at the bottom), creating and editing images (choose, drag, paste or **Edit** an image of the feed), **Enhance**, **Enlarge ×4**, the **Models** and **Settings** windows, **Phone** with a QR code made on the computer (no Internet needed), device access requests, Claude's download approvals, and the update and Claude banners.
- Closing the window hides it: Prisme keeps serving the phone, Claude and downloads, then stops according to its settings. Opening Prisme again, or clicking its Dock icon, brings the window back.

### Changed

- The phone still uses the web page, and Claude still uses the same local server: the three share one logic.
- `--web` keeps the browser window; on Linux, the Qt window is opt-in with `--qt` (it needs system libraries that may be missing).
- After a one-click update, the Qt app restarts with its window.
- The Windows program is larger (about 150 MB instead of 12 MB), since it carries Qt.

## [1.10.1] - 2026-11-12

### Fixed

- **Closing the window no longer stops a download.** Prisme used to stop a few seconds after its window closed, or 10 minutes after Claude's last request, even in the middle of a model, engine or update download. It now stays open until the download ends.
- **Saving the Settings no longer undoes a model choice.** If a download chose a model while the Settings window was open, **Save** put the old one back; Prisme now asks to reopen the Settings. The settings file is also written in one go, so a power cut can no longer reset it.
- **An unexpected error no longer looks like a crash.** It used to cut the connection, and the window showed "The server is not responding"; it now shows the error.
- **Improve** and **Create** started at the same moment (from Claude or the phone) can no longer run together and overload the graphics card.
- Two requests for the same model at the same moment no longer download it twice.

## [1.10.0] - 2026-11-12

### Added

- **Enlarge**: a finished image ×4 with Real-ESRGAN x4plus (BSD-3-Clause, 67 MB, downloaded at the first click), in a new image that keeps the description and variant. 1280 × 704 to 5120 × 2816 in 14 s on an RTX 4070 SUPER. Refused from Claude, which keeps no access to Prisme's images.
- **Remove models from the app**: a delete button for each installed model in the models window (advanced mode), including files added by hand. Deleted for good, after a confirmation, to really free the space. Refused from the phone and from Claude, during a creation, and while that file downloads.

## [1.9.6] - 2026-11-11

### Fixed

- **The PC no longer freezes during a creation or Improve.** The image engine and the text engine now leave 1.5 GB of the graphics card to the display, which they used to fill up to 0.5 GB. It costs a few seconds at most (Improve with Qwen-Image 2.1's text model: 3.1 s instead of 1.6 s). **Settings → Performance → Keep the PC usable** turns it off.
- The **Connect to Claude** and update banners no longer cover the first message of the feed.

## [1.9.5] - 2026-11-10

### Fixed

- On a phone, the **Connect to Claude** and update banners take the full width again, instead of a narrow circle with one word per line.

### Changed

- Version numbers with a pre-release suffix (such as `2.0.0-beta.1`) are now compared correctly: a beta comes before its final version, so a beta tester is offered the final release.

## [1.9.4] - 2026-11-10

### Added

- **Quit Prisme** in **Settings → Application**, next to **Quit** at the top of the window: it stops Prisme and its engines.
- When an update could not be installed, the next launch says so at the top of the window, with a link to the releases page. The details are in `app/mise-a-jour.log`.

### Fixed

- **Updates never fall back silently to the old version.** Prisme waits for itself and its engines to stop (up to 2 minutes), renames the old program first (allowed even while Claude's MCP server still uses it) and retries for 2 minutes (antivirus, SmartScreen). If it still fails, the leftover `.prisme-maj-*` files are removed and the old version starts again with the error message.
- **One Prisme at a time**: a second launch no longer opens a second window or server. It reopens the existing window, and does nothing when started by an update (`--sans-fenetre`).
- **No more engines left running in the background**: on Windows, `sd-cli` and `llama-server` now stop with Prisme even if it crashes or is ended from the Task Manager (Job object); on Linux and macOS they get their own process group, and on Linux they also stop when Prisme dies. Engines left by a previous session are stopped at the next launch, only if they run from Prisme's own `sd/` or `llama/` folder.
- Closing the window is noticed even when the browser could not tell Prisme (sudden close, crash): after 5 minutes without news from the window, Prisme stops as if it had been closed.
- Mac started from a temporary copy (App Translocation): the update banner explains right away how to move Prisme to Applications, instead of failing on click. The one-click update keeps using the `.zip`.

## [1.9.3] - 2026-11-09

### Added

- **Mac disk image**: `Prisme-macOS-arm64.dmg` opens with Prisme next to a shortcut to Applications: drag one onto the other, like other Mac apps. The `.zip` stays for the one-click update.

### Changed

- **Claude's images apart**: images Claude asks for go to the `images-claude` folder (next to `images`) and no longer appear in Prisme's gallery. Claude can no longer read the images created in Prisme's window, follow a creation started there, or see its description. The MCP server's default `PRISME_OUTPUT_DIR` is now that folder instead of `~/Prisme-MCP`.

### Fixed

- **Mac, Prisme opened from Downloads**: macOS then runs it from a temporary read-only copy (App Translocation), whose path changes after a restart. Prisme no longer writes that path into Claude's configuration and no longer tries to update itself there; it asks you to move Prisme.app to Applications instead.

## [1.9.2] - 2026-11-09

### Added

- **Check for updates now**: Settings → Application has a **Check** button that asks GitHub right away. A new version brings back the update notice, even if you had dismissed it; otherwise Prisme says it is up to date, or that GitHub is not answering.
- `POST /api/verifier-mise-a-jour` (PC only): the same check, with an error when GitHub cannot be reached instead of silence.

## [1.9.1] - 2026-11-09

### Fixed

- **Long creations from Claude**: `PRISME_TIMEOUT` now defaults to 50 s instead of 120 s. Claude stops waiting for a tool after 60 s, so a creation longer than that ended in "Request timed out" with no image and no task id; Prisme now answers in time with a `task_id` that `get_status` turns into the image.

## [1.9.0] - 2026-11-08

### Added

- **Model profiles by hardware**: the models window offers eight profiles (CPU only, 4 to 6 GB, 8 GB, 12 GB and 16 GB cards, 8 GB, 16 GB and 32 GB Macs), each with its size, indicative speed, licenses and a **Recommended for your machine** badge. **Download this profile** fetches the whole set; files already present are only selected, not downloaded again. The catalog lives in `app/modeles.json`.
- **Profiles under permissive licenses only**: the profiles suggested for your machine use FLUX.2 klein 4B, Qwen3 4B and the FLUX.2 small decoder, all Apache-2.0 (commercial use allowed). FLUX.2 klein creates and edits images with a single model, without a vision file. The 12 GB card profile is tested (8 to 10 s per image on an RTX 4070 SUPER); the others stay experimental until tested on their hardware.
- **Other choices**: Z-Image Turbo (Apache-2.0, creation only) and Qwen-Image 2.1 Turbo (8, 12 and 16 GB). Qwen-Image is under a research license (non-commercial): Prisme asks you to accept it before downloading, and the server refuses the download otherwise.
- `GET /api/profils` (PC only, read-only): the profiles, what is already downloaded and the suggested profile.
- **Claude can use Prisme** (MCP): **Connect to Claude** adds Prisme to Claude Desktop and Claude Code in one click, with a copy of their configuration kept. The MCP server is built into the program (`Prisme --mcp`, standard library only, nothing to install) and starts Prisme if it isn't open; Prisme stays open when Claude closes.
- MCP tools: `generate_image`, `edit_image`, `get_status` (long creations return a task id), `list_models`, `list_profiles`, `install_engine`, `download_profile` and `download_model`. It only talks to Prisme on `127.0.0.1` and only edits images from its own folder. Previews for Claude are made without Pillow.
- **Your approval in Prisme's window**: when Claude asks for a profile under a non-commercial license (Qwen-Image) or a model outside the catalog (any `.gguf` or `.safetensors` link), Prisme shows the license or a warning; only your click there starts the download. Models outside the catalog are checked against the checksum given by the site when there is one, otherwise by size.
- `POST /api/generer` accepts an optional `modele`: a drawing model file from `models/`, used for that creation only (for the MCP server's `model` parameter).
- Hardware detection reads AMD and Intel cards too (`rocm-smi`, `/sys` on Linux, the Windows registry, `vulkaninfo`). It only suggests a profile; nothing is sent.

### Changed

- The per-file list moves to **Choose models one by one (advanced mode)**.
- Generation settings follow the chosen drawing model (8 steps and its own sigmas), unless you changed them yourself.
- **Enhance** asks the built-in text engine to answer without a thinking phase, which keeps Qwen3 4B fast.

### Fixed

- Editing an image with models that cannot edit now explains what to do instead of naming a missing setting.
- **Connect to Claude** with the Microsoft Store version of Claude Desktop: Prisme now writes to the configuration that recent versions read (`AppData\Local\Claude-Data`), instead of the older `AppData\Roaming\Claude`.
- The MCP server answers Claude Desktop's `prompts/list` and `resources/list` requests (empty lists) instead of an error.

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

[Unreleased]: https://github.com/d3Ita/prisme/compare/v2.0.0-rc.1...HEAD
[2.0.0-rc.1]: https://github.com/d3Ita/prisme/releases/tag/v2.0.0-rc.1
[1.10.1]: https://github.com/d3Ita/prisme/releases/tag/v1.10.1
[1.10.0]: https://github.com/d3Ita/prisme/releases/tag/v1.10.0
[1.9.6]: https://github.com/d3Ita/prisme/releases/tag/v1.9.6
[1.9.5]: https://github.com/d3Ita/prisme/releases/tag/v1.9.5
[1.9.4]: https://github.com/d3Ita/prisme/releases/tag/v1.9.4
[1.9.3]: https://github.com/d3Ita/prisme/releases/tag/v1.9.3
[1.9.2]: https://github.com/d3Ita/prisme/releases/tag/v1.9.2
[1.9.1]: https://github.com/d3Ita/prisme/releases/tag/v1.9.1
[1.9.0]: https://github.com/d3Ita/prisme/releases/tag/v1.9.0
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
