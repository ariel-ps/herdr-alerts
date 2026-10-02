# Herdr Alerts

Flash a pane and play a sound when an agent finishes or needs attention.

Hooks use the bundled tone unless an optional media pack is available. Run `herdr-sounds-sync` to fetch sound packs. Configure alert names, volume and duration in `config.sh`.

## Install

[Herdr Setup](https://github.com/ariel-ps/herdr-setup) installs prerequisites and lets you select this plugin in `dependencies.json`.

With Herdr 0.9.3+ already installed:

```sh
herdr plugin install ariel-ps/herdr-alerts --ref main --yes
```

Use a commit or release tag instead of `main` to pin a version. Supports macOS, Ubuntu/Debian, and Fedora.

Herdr Setup loads the enabled plugin's helpers in bash or zsh. For a manual installation, source the installed plugin's `shell.bash` in `.bashrc` or `shell.zsh` in `.zshrc`. Bash helpers call the same zsh implementation, so zsh must also be installed; you keep bash as your shell.

Edit `config.sh` in the directory printed by `herdr plugin config-dir dev.ariel.herdr-alerts`. Existing media caches are reused.
