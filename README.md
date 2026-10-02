# Herdr Alerts

**Hear when an agent finishes or needs your attention. See which pane needs you.**

Herdr Alerts plays a sound and flashes the affected pane when an agent finishes or becomes blocked. An included tone works immediately; optional game packs let you choose your own alert sounds.

```sh
herdr-sound play                  # Test your speakers
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

Requires Herdr 0.9.3+, Git, Python 3, zsh, and jq. Audio uses `afplay` on macOS or `ffplay` (FFmpeg) on Linux. Pane graphics use netcat and Perl with `MIME::Base64` and `JSON::PP`; sound-pack downloads also need uv.

```sh
herdr plugin install ariel-ps/herdr-alerts --ref main --yes
herdr plugin action invoke play --plugin dev.ariel.herdr-alerts
```

The second command previews the included tone. In Herdr, you can also choose **Preview alert sound** from the plugin actions. Use a commit or release tag instead of `main` to pin a version.

To use `herdr-sound` in your shell, source the installed plugin's `shell.bash` from `.bashrc`, or `shell.zsh` from `.zshrc`. These add its `bin` directory to `PATH`. Bash remains your shell; the plugin uses zsh internally. Herdr Setup configures this automatically.

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

Choices apply to the next alert without restarting Herdr. Missing game sounds fall back to the included tone during automatic alerts. Manual previews play sound only; automatic alerts also flash the pane and can show sprites when the corresponding assets are available.

## Commands

| Command | What it does |
| --- | --- |
| `herdr-sound play [NAME]` | Preview a sound; omit NAME for the included tone |
| `herdr-sound list` | Browse sounds and see which are ready |
| `herdr-sound download [PACK ...]` | Download selected packs; omit PACK to download all sound packs |
| `herdr-sound set blocked NAME` | Choose the needs-attention sound |
| `herdr-sound set done NAME` | Choose the finished sound |
| `herdr-sound enable` | Enable automatic alerts |
| `herdr-sound disable` | Mute automatic alerts; manual previews still work |
| `herdr-sound status` | Show settings, sound availability, and audio backend |

Run `herdr-sound COMMAND --help` for details. The aliases `sync`, `on`, and `off`, and the older `alert8play` and `herdr-sounds-sync` commands still work.

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

`data/packs.json` is the hand-authored alert catalog. Regenerate its committed
shell lookup after editing it:

```sh
python3 scripts/build/gen-alert-tables.py
```

The output, `generated/alerts.zsh`, starts with a generated/do-not-edit marker.
The event adapter lives in `hooks/`, private playback and download helpers live
in `libexec/`, and only the stable `alert8play` and `herdr-sound` commands live
in `bin/`. Sprite acquisition under `scripts/dev/` is maintainer tooling and is
not called at runtime.

Run `python3 tests/test_plugin.py`. Checks cover relocated paths containing
spaces, bash/zsh commands, settings, download dispatch, compatibility aliases,
generated data, and playback errors using stubs. They do not play audio or
download packs.

To generate a replacement included tone:

```sh
python3 scripts/build/generate-8bit-alert.py assets/audio/8bit-alert.wav --seed SEED
```

See [SECURITY.md](SECURITY.md) for private vulnerability reporting and
[CHANGELOG.md](CHANGELOG.md) for release history.

## License

Original project code and the generated included tone are licensed under the
[MIT License](LICENSE). Third-party code and media retain their own terms; this
license does not grant rights to game assets, downloaded themes, or other
third-party content. Known provenance limits for the sprite renderer are
documented in [vendor/sprite/ORIGIN.md](vendor/sprite/ORIGIN.md).
