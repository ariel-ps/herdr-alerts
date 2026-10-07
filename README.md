# Herdr Alerts

**Hear when an agent finishes or needs your attention. See which pane needs you.**

Herdr Alerts plays a sound and flashes the affected pane when an agent finishes or becomes blocked. Its Rust CLI, `herdr-alert`, previews sounds, flashes, and animated sprites. An included tone works immediately; optional game packs let you choose your own alert sounds.

```sh
herdr-alert play                 # Preview sound, flash, and sprite
herdr-alert set flash off        # Disable flashing
herdr-alert download mario       # Get sounds and sprite artwork
herdr-alert set done 1up         # Use it when an agent finishes
```

## Install

[Herdr Setup](https://github.com/ariel-ps/herdr-setup#prerequisites) installs Herdr, this plugin, and the other setup plugins with their dependencies. Supports macOS, Ubuntu/Debian, and Fedora, with bash or zsh.

```sh
curl -fsSL https://raw.githubusercontent.com/ariel-ps/herdr-setup/main/install.sh | sh
```

You need internet access, `curl`, and `tar`. macOS also needs Homebrew and its command-line build tools; Linux needs `apt-get` or `dnf`, with sudo or root access. Herdr does not need to be installed already.

Open a new terminal, then run `herdr-alert play`. You should hear a short tone, see four green flashes, then an animated sprite in the top-right corner. No sound-pack download is required.

<details>
<summary>Install only this plugin into an existing Herdr installation</summary>

Requires Herdr 0.9.3+, Git, a stable Rust toolchain (Cargo and rustc), Python 3, zsh, and jq. Installation compiles the Rust CLI. Audio uses `afplay` on macOS or `ffplay` (FFmpeg) on Linux. Pane graphics use Perl with `MIME::Base64`, `JSON::PP`, and `Time::HiRes` (Fedora package `perl-Time-HiRes`); optional sound-pack downloads use the existing Python fetchers through uv.

```sh
herdr plugin install ariel-ps/herdr-alerts --ref main --yes
herdr plugin action invoke play --plugin dev.ariel.herdr-alerts
```

The second command previews the included tone. In Herdr, you can also choose **Preview alert sound** from the plugin actions. Use a commit or release tag instead of `main` to pin a version.

To use `herdr-alert` in your shell, source the installed plugin's `shell.bash` from `.bashrc`, or `shell.zsh` from `.zshrc`. These add its `bin` directory to `PATH`. Bash remains your shell. The Rust CLI uses zsh to read existing shell configuration, and the automatic pane hook remains a zsh script. Herdr Setup configures shell integration automatically.

</details>

## Choose your sounds

```sh
herdr-alert list                  # Browse names, packs, and availability
herdr-alert download mario
herdr-alert play 1up              # Preview before choosing
herdr-alert set done 1up

herdr-alert download redalert
herdr-alert set blocked tesla
```

Choices apply to the next alert without restarting Herdr. Missing game sounds fall back to the included tone during automatic alerts. Automatic alerts also flash the pane and show sprites when an agent needs attention.

Downloads include both sound and available sprite artwork. If you downloaded
sounds with an older version, add the missing artwork without downloading audio again:

```sh
herdr-alert download --sprites mario redalert
herdr-alert play 1up
```

The yellow circular animation is the built-in fallback, not downloaded game artwork.
Sprites play a complete cycle (at least about a second for legacy packs) and disappear when the affected pane is focused. If it is
unfocused, they keep animating until you return. This applies to automatic alerts,
`play`, and menu previews. Focus tracking uses Herdr's pane state, with Kitty window
focus when available; a 30-minute limit prevents abandoned animations. Without
focus tracking, or with `SPRITE_PERSIST=0`, sprites animate once.

Flashing is on by default. Run `herdr-alert set flash off` to disable flashing, or `herdr-alert set flash on` to enable it. This preference is saved for manual previews (`herdr-alert play` and `alert8play`) and automatic alerts. Herdr does not need to be running for terminal previews.

Outside Herdr, this uses the original `flash-term` background-color effect (OSC 11). It restores Kitty's current background when remote control is available, or resets to the terminal's configured background otherwise. Inside Herdr, it draws and removes a temporary Kitty graphics overlay without changing pane colors; enable `experimental.kitty_graphics = true` in Herdr's configuration. Explicit previews work even when automatic alerts are muted. For background jobs without a terminal, turn both flash and sprite off.

Sprites are on by default for previews and blocked-agent alerts. Use `herdr-alert set sprite off` or `herdr-alert set sprite on` to save your preference. Sprites work independently of flashing; turn both off for sound only. Cached sprite packs supply game artwork; otherwise a built-in animated indicator appears. Sprite rendering requires Kitty graphics support, either through Herdr or a compatible terminal.

## Let the LLM pick a sound per project

```sh
cd ~/projects/my-repo
herdr-alert auto              # Picks and saves both blocked and done for this project
herdr-alert auto blocked      # Picks and saves just one
```

Reads the current git branch name and last few commit subjects, and asks the installed `claude` CLI to pick the best-fitting sound from the full catalog's short vibe tags (a bugfix branch tends to land on something like `die`; a feature branch on something like `davewin`). Requires Claude Code installed and signed in; costs a small amount per run (well under a cent on Haiku) and takes a few seconds, so it only runs when you ask for it — never automatically from an alert itself.

The pick is saved per git repository (by its root path) in `${XDG_DATA_HOME:-~/.local/share}/herdr-alert/projects.json`, and applies to every pane working in that project or a subdirectory of it, overriding the global `set blocked`/`set done` choice but not a literal `HERDR_SOUND_*` override. Projects that never run `herdr-alert auto` are completely unaffected. Re-run it any time — for example after switching branches — to update the pick.

## Use your own animation

Import a GIF or animated PNG containing the complete scene, such as a character
jumping over an obstacle:

```sh
herdr-alert set animation ./jump-scene.gif
herdr-alert set sprite on
herdr-alert set animation on
herdr-alert play
herdr-alert set animation off      # Use normal sprites; keep the imported scene saved
herdr-alert set animation default  # Return to each sound's paired artwork
```

Import requires `uv` and uses Pillow, the same image library used by sprite
downloads. The scene is copied into the user data directory and converted once;
the original file is no longer needed. Import preserves frame timing, transparency,
and aspect ratio. Scenes may contain up to 600 frames, measure up to 512×512 pixels,
last up to 30 seconds per cycle, and occupy up to 64 MiB when decoded.

A focused pane plays the whole scene once. An unfocused pane loops it without a
pause between cycles and clears it when you return. Sound plays once per alert.
Custom scenes apply to previews and needs-attention alerts; finished alerts keep
their existing sound and flash behavior. Use `herdr-alert set animation off` to
use normal sprites while keeping your scene saved, and `herdr-alert set animation on`
to restore it. Custom animations are enabled by default. Sprite on/off still
controls visibility of both normal sprites and custom animations.

## Commands

| Command | What it does |
| --- | --- |
| `herdr-alert configure` | Full-screen interactive configuration (alerts, settings, downloads, status) |
| `herdr-alert play [NAME]` | Preview sound, flash, and sprite using your saved settings |
| `herdr-alert list [PACK]` | Browse sounds and see which are ready, optionally one pack at a time |
| `herdr-alert download [PACK ...]` | Download sounds and available sprites; omit PACK for all packs |
| `herdr-alert download --sprites [PACK ...]` | Download only sprite artwork |
| `herdr-alert auto [blocked\|done]` | LLM-pick a sound fitting this project's branch/commits; cached per repo |
| `herdr-alert set blocked NAME` | Choose the needs-attention sound |
| `herdr-alert set done NAME` | Choose the finished sound |
| `herdr-alert set blocked-sprite\|done-sprite NAME` | Show a different alert's sprite instead of the sound's own |
| `herdr-alert set blocked-sprite\|done-sprite default` | Use the sound alert's own sprite again |
| `herdr-alert set volume blocked\|done NUMBER` | Set that event's playback volume |
| `herdr-alert set duration NUMBER\|full` | Cap, or stop capping, clip playback length |
| `herdr-alert set flash on\|off` | Save the flash preference for previews and automatic alerts |
| `herdr-alert set sprite on\|off` | Save the sprite preference for previews and blocked-agent alerts |
| `herdr-alert set animation on\|off` | Enable or disable custom artwork without clearing the imported scene |
| `herdr-alert set animation FILE` | Import a GIF or animated PNG for previews and needs-attention alerts |
| `herdr-alert set animation default` | Restore the artwork paired with each sound |
| `herdr-alert enable` | Enable automatic alerts |
| `herdr-alert disable` | Mute automatic alerts; manual previews still work |
| `herdr-alert status` | Show settings, sound availability, and audio backend |

Run `herdr-alert COMMAND --help` for details. The aliases `sync`, `on`, and `off`, and the older `herdr-sound`, `alert8play`, and `herdr-sounds-sync` commands still work. `herdr-sound play [NAME]` and `alert8play [NAME]` use the same sound, flash, and sprite settings.

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
HERDR_ALERT_FLASH=1   # 0 disables flashing
HERDR_ALERT_SPRITE=1  # 0 disables sprites
HERDR_ALERT_ANIMATION_ENABLED=1  # 0 uses normal sprites instead of custom artwork
```

Previews use the done-volume and duration settings. The CLI saves sound choices, flash, sprite and animation preferences, and enabled state in a marked section at the end of this file, backing up existing settings. `set blocked` and `set done` also clear that event's custom file override.

## No sound?

Run `herdr-alert status`, then `herdr-alert play`. Status checks settings and the audio player; the preview tests playback. Read any reported error, and check whether another application can play audio. Linux requires a working audio session and output device.

If a named sound is missing, run `herdr-alert download PACK` using the pack shown by `list`. Downloads are cached under `${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit` and reused across upgrades.

## Development

The catalog is `data/packs.json`; regenerate the committed event lookup after editing it:

```sh
python3 scripts/build/gen-alert-tables.py
```

`src/` contains the Rust CLI. `bin/` contains its public launchers, `hooks/` contains the pane event adapter, and `libexec/` contains the compiled binary and private playback/download helpers. `generated/alerts.zsh` is the generated lookup. The old `scripts/dev/` sprite entry points delegate to the runtime downloaders.

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
python3 tests/test_plugin.py
python3 tests/test_sprite_events.py
uv run --with pillow --with pycryptodome python tests/test_sprite_downloads.py
uv run --with pillow python tests/test_animation.py
```

The integration check compiles the Rust executable, then tests Bash/Zsh commands, settings, downloads, compatibility aliases, and playback errors with stubs. It does not play audio or download sound packs. Build locally with `sh scripts/build/install.sh`. Cargo dependencies are pinned in `Cargo.lock`.

`tests/test_sprite_flicker.py --herdr` records actual animation pixels in an isolated
X11 desktop with Kitty, Herdr, and FFmpeg. It checks for blank frames during slow
image delivery, verifies movement, and confirms cleanup. Run without `--herdr`
to check Kitty directly.

`tests/test_flash_visual.py` checks actual rendered pixels in an X11 desktop with Herdr and Kitty. Run it with an explicit test pane and crop, as shown in the script's help, to verify the flash appears and the background is restored.

## License

See [CHANGELOG.md](CHANGELOG.md) for release history and [SECURITY.md](SECURITY.md) for vulnerability reporting. Sprite-renderer provenance is recorded in [vendor/sprite/ORIGIN.md](vendor/sprite/ORIGIN.md).

Original project code is licensed under the [MIT License](LICENSE). Third-party code and media retain their own terms; this license does not grant rights to game assets, downloaded themes, or other third-party content.
