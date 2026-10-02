# Herdr Alerts

**Hear when an agent finishes or needs your attention, and see which pane it is in.**

Herdr Alerts pairs a sound with a flash on the agent's pane. An included tone works immediately; optional game packs add familiar sounds and downloaded sprite assets can add visual cues.

## Install

[Herdr Setup](https://github.com/ariel-ps/herdr-setup) installs Herdr, this plugin, and its prerequisites. It makes `herdr-sound` available in a new bash or zsh terminal.

For standalone installation, you need **Herdr 0.9.3+**, Git, Python 3, zsh, and jq. Playback uses macOS's `afplay` or Linux's `ffplay` (FFmpeg); pane graphics also use netcat and Perl with `MIME::Base64` and `JSON::PP`. Downloading sound packs requires uv.

```sh
herdr plugin install ariel-ps/herdr-alerts --ref main --yes
herdr plugin action invoke play --plugin dev.ariel.herdr-alerts
```

The second command previews the included tone. You can also choose **Preview alert sound** from Herdr's plugin actions.

Supports macOS, Ubuntu/Debian, and Fedora. Use a commit or release tag instead of `main` to pin a version.

<details>
<summary>Shell commands after standalone installation</summary>

Source the installed plugin's `shell.bash` from `.bashrc`, or `shell.zsh` from `.zshrc`. These add the plugin's `bin` directory to `PATH`. Bash helpers still use zsh internally; you keep bash as your shell. Herdr Setup handles this integration automatically.

</details>

## Try it

After installing through Herdr Setup, open a new terminal:

```sh
herdr-sound play        # Hear the included tone without downloading anything
herdr-sound list        # See which named sounds are ready or missing
herdr-sound sync mario  # Download a game pack once
herdr-sound play 1up    # Preview its sound
herdr-sound set done 1up
```

For Tesla: run `herdr-sound sync redalert`, then `herdr-sound play tesla`.

Previews play sound only. Automatic alerts also flash the affected pane when an agent becomes blocked or finishes; unavailable game sounds fall back to the included tone. Listing names does not download their packs.

## Everyday commands

| Command | Purpose |
| --- | --- |
| `herdr-sound play [NAME]` | Preview a named sound, or the included tone |
| `herdr-sound list` | List sound names, packs, and download availability |
| `herdr-sound sync [PACK ...]` | Download selected sound packs; no names downloads all sound packs |
| `herdr-sound on` / `herdr-sound off` | Enable or mute automatic alerts; explicit previews still work |
| `herdr-sound set blocked NAME` | Choose the sound for an agent needing attention |
| `herdr-sound set done NAME` | Choose the sound for an agent finishing |
| `herdr-sound status` | Show effective settings and the available audio player |

`herdr-sound --help` shows usage. The previous `alert8play [NAME]`, `alert8play --list`, and `herdr-sounds-sync [PACK ...]` commands still work.

## Configure

Find your settings directory:

```sh
herdr plugin config-dir dev.ariel.herdr-alerts
```

Edit or create `config.sh` there:

```sh
HERDR_ALERT_BLOCKED=tesla
HERDR_ALERT_DONE=1up
HERDR_VOLUME_DONE=1.0
HERDR_ALERT_MAX_SECONDS=3
```

`set`, `on`, and `off` save choices in a marked section at the end of this file and back up existing settings. Choosing a sound with `set` clears that event's custom file override so the chosen name takes effect. Changes apply to the next alert without restarting Herdr.

Explicit previews use the configured done-volume and duration, even when automatic alerts are off. Downloaded packs are stored under `${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit` and reused across upgrades.

If you hear nothing, run `herdr-sound status`, then `herdr-sound play` and read any playback error. Status checks settings and player availability; it cannot confirm that speakers are audible. Linux needs a working audio session and output device; containers and SSH sessions may not have one.

## Development

Run `python3 tests/test_plugin.py`. The check exercises bash and zsh commands, saved settings, download dispatch, compatibility commands, and playback failures using stubs, without playing audio or downloading packs.

## License

Original project code is licensed under the [MIT License](LICENSE). Third-party code and media retain their own terms; this license does not grant rights to game assets, downloaded themes, or other third-party content.
