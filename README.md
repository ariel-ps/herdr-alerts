# Herdr Alerts

**Hear when an agent finishes or needs your attention, and see which pane it is in.**

Herdr Alerts pairs a sound with a flash on the agent's pane. An included tone works immediately; optional game packs add familiar sounds and downloaded sprite assets can add visual cues.

## Install

[Herdr Setup](https://github.com/ariel-ps/herdr-setup) installs Herdr, this plugin, and its prerequisites. It makes `alert8play` available in a new bash or zsh terminal.

For standalone installation, you need **Herdr 0.9.3+**, Git, zsh, jq, and Python 3 or uv for the build. Playback uses macOS's `afplay` or Linux's `ffplay` (FFmpeg); pane graphics also use netcat and Perl with `MIME::Base64` and `JSON::PP`. Downloading sound packs requires uv.

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
alert8play             # Hear the included tone without downloading anything
alert8play --list      # See the available game-sound names
herdr-sounds-sync mario
alert8play 1up         # Hear a Mario sound after downloading its pack
```

For Tesla: run `herdr-sounds-sync redalert`, then `alert8play tesla`.

Previews play sound only. Automatic alerts also flash the affected pane when an agent becomes blocked or finishes; unavailable game sounds fall back to the included tone. Listing names does not download their packs.

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

Set `HERDR_ALERT_OFF=1` to mute automatic alerts. Explicit `alert8play` previews still work and use the configured done-volume and duration. Downloaded packs are stored under `${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit` and reused across upgrades.

## Development

Run `python3 tests/test_plugin.py`. The check exercises bash and zsh commands, configuration, missing packs, and playback failures using a recording stub, without playing audio.
