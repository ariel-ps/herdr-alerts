# Herdr Alerts

**Hear when an agent finishes or needs your attention. See which pane needs you.**

Herdr Alerts plays a sound and flashes the affected pane when an agent finishes or becomes blocked. Its Rust CLI previews sounds and manages settings. An included tone works immediately; optional game packs let you choose your own alert sounds.

```sh
herdr-sound play                  # Test your speakers
herdr-sound play --flash          # Also flash your terminal
herdr-sound download mario       # Get a sound pack
herdr-sound set done 1up         # Use it when an agent finishes
```

## Install

[Herdr Setup](https://github.com/ariel-ps/herdr-setup#prerequisites) installs Herdr, this plugin, and the other setup plugins with their dependencies. Supports macOS, Ubuntu/Debian, and Fedora, with bash or zsh.

```sh
curl -fsSL https://raw.githubusercontent.com/ariel-ps/herdr-setup/main/install.sh | sh
```

You need internet access, `curl`, and `tar`. macOS also needs Homebrew and its command-line build tools; Linux needs `apt-get` or `dnf`, with sudo or root access. Herdr does not need to be installed already.

Open a new terminal, then run `herdr-sound play`. You should hear a short tone; no sound-pack download is required.

<details>
<summary>Install only this plugin into an existing Herdr installation</summary>

Requires Herdr 0.9.3+, Git, a stable Rust toolchain (Cargo and rustc), Python 3, zsh, and jq. Installation compiles the Rust CLI. Audio uses `afplay` on macOS or `ffplay` (FFmpeg) on Linux. Terminal flashes use `tput`, included with macOS; Linux supplies it through `ncurses-bin` (Ubuntu/Debian) or `ncurses` (Fedora). Pane graphics use netcat and Perl with `MIME::Base64` and `JSON::PP`; optional sound-pack downloads use the existing Python fetchers through uv.

```sh
herdr plugin install ariel-ps/herdr-alerts --ref main --yes
herdr plugin action invoke play --plugin dev.ariel.herdr-alerts
```

The second command previews the included tone. In Herdr, you can also choose **Preview alert sound** from the plugin actions. Use a commit or release tag instead of `main` to pin a version.

To use `herdr-sound` in your shell, source the installed plugin's `shell.bash` from `.bashrc`, or `shell.zsh` from `.zshrc`. These add its `bin` directory to `PATH`. Bash remains your shell. The Rust CLI uses zsh to read existing shell configuration, and the automatic pane hook remains a zsh script. Herdr Setup configures shell integration automatically.

</details>

## Choose your sounds

```sh
herdr-sound list                  # Browse names, packs, and availability
herdr-sound download mario
herdr-sound play 1up              # Preview before choosing
herdr-sound set done 1up

herdr-sound download redalert
herdr-sound set blocked tesla
```

Choices apply to the next alert without restarting Herdr. Missing game sounds fall back to the included tone during automatic alerts. Automatic alerts also flash the pane and can show sprites when the corresponding assets are available.

Run `herdr-sound play --flash` or `alert8play --flash` from your terminal for sound and two flashes. Herdr does not need to be running. Named sounds work too: `herdr-sound play 1up --flash`.

Outside Herdr, flashing uses your terminal's visual-bell capability (`tput flash`) without changing its colors or contents. Inside Herdr, versions with the graphics API use a green pane overlay, which requires `experimental.kitty_graphics = true`. Versions without that API, including Herdr 0.9.3, use the pane's terminal visual bell. Explicit previews work even when automatic alerts are muted and do not show sprites. Omit `--flash` for sound only. A terminal without visual-bell support, or a background job without a terminal, reports a clear error.

## Commands

| Command | What it does |
| --- | --- |
| `herdr-sound play [NAME] [--flash]` | Preview a sound; optionally flash your terminal or Herdr pane |
| `herdr-sound list` | Browse sounds and see which are ready |
| `herdr-sound download [PACK ...]` | Download selected packs; omit PACK to download all sound packs |
| `herdr-sound set blocked NAME` | Choose the needs-attention sound |
| `herdr-sound set done NAME` | Choose the finished sound |
| `herdr-sound enable` | Enable automatic alerts |
| `herdr-sound disable` | Mute automatic alerts; manual previews still work |
| `herdr-sound status` | Show settings, sound availability, and audio backend |

Run `herdr-sound COMMAND --help` for details. The aliases `sync`, `on`, and `off`, and the older `alert8play` and `herdr-sounds-sync` commands still work. `alert8play [NAME] --flash` previews the same sound and visual effect.

## Settings

Find your configuration directory with:

```sh
herdr plugin config-dir dev.ariel.herdr-alerts
```

Edit or create `config.sh` there to adjust volume or clip duration:

```sh
HERDR_VOLUME_BLOCKED=1.8
HERDR_VOLUME_DONE=1.0
HERDR_ALERT_MAX_SECONDS=3
```

Previews use the done-volume and duration settings. The CLI saves sound choices and enabled state in a marked section at the end of this file, backing up existing settings. `set` also clears that event's custom file override.

## No sound?

Run `herdr-sound status`, then `herdr-sound play`. Status checks settings and the audio player; the preview tests playback. Read any reported error, and check whether another application can play audio. Linux requires a working audio session and output device.

If a named sound is missing, run `herdr-sound download PACK` using the pack shown by `list`. Downloads are cached under `${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit` and reused across upgrades.

## Development

The catalog is `data/packs.json`; regenerate the committed event lookup after editing it:

```sh
python3 scripts/build/gen-alert-tables.py
```

`src/` contains the Rust CLI. `bin/` contains its public launchers, `hooks/` contains the pane event adapter, and `libexec/` contains the compiled binary and private playback/download helpers. `generated/alerts.zsh` is the generated lookup. Sprite acquisition under `scripts/dev/` remains maintainer tooling.

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
python3 tests/test_plugin.py
```

The integration check compiles the Rust executable, then tests Bash/Zsh commands, settings, downloads, compatibility aliases, and playback errors with stubs. It does not play audio or download sound packs. Build locally with `sh scripts/build/install.sh`. Cargo dependencies are pinned in `Cargo.lock`.

## License

See [CHANGELOG.md](CHANGELOG.md) for release history and [SECURITY.md](SECURITY.md) for vulnerability reporting. Sprite-renderer provenance is recorded in [vendor/sprite/ORIGIN.md](vendor/sprite/ORIGIN.md).

Original project code is licensed under the [MIT License](LICENSE). Third-party code and media retain their own terms; this license does not grant rights to game assets, downloaded themes, or other third-party content.
