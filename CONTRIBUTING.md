# Contributing

## Before you start

For anything beyond a small fix, open an issue first describing what you want
to change and why. It saves a rewritten PR if the approach needs discussion.

## Setup

See [README.md's Development section](README.md#development) for
dependencies and how to build. In short:

```sh
sh scripts/build/install.sh                # build and install the CLI
python3 scripts/build/gen-alert-tables.py   # after editing data/packs.json
```

## Before opening a PR

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
python3 tests/test_plugin.py
uv run --with pillow python tests/test_animation.py
uv run --with pillow --with pycryptodome python tests/test_sprite_downloads.py
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push and pull
request against `main`. The remaining tests under `tests/` need a real X11
desktop, Kitty, or Herdr session and are opt-in — see each file's own
docstring for how to run it locally.

## Conventions

- Commit messages: `type: short summary`, matching `git log` (`feat`, `fix`,
  `docs`, `chore`, `refactor`, `revert`). Explain *why* in the body when it
  isn't obvious from the summary.
- `data/packs.json` is the single source of truth for what an alert sounds
  and looks like; regenerate `generated/alerts.zsh` after editing it rather
  than hand-editing the generated file.
- New game packs or sprite art should come from a source that ships its own
  frame/asset data (see the comment at the top of `libexec/fetch-sprites.py`)
  rather than hand-guessed crop coordinates.
- Keep the terminology in [CONTEXT.md](CONTEXT.md) in mind — it defines what
  this codebase means by "alert", "sprite", "pack", and so on.

## Reporting a vulnerability

Don't open a public issue — see [SECURITY.md](SECURITY.md).
