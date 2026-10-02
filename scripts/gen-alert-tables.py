#!/usr/bin/env python3
"""Generate sounds/alerts-generated.zsh from sounds/packs.json.

The hook never parses the JSON. alert-hook.sh is spawned once per status change
on every pane — nine agents produce a steady trickle of them — and it already
pays two `jq` execs to read the event. Resolving an alert name the same way
would add several more to a path whose entire job is to be quick and quiet. A
sourced `case` table costs no subprocess at all.

The Python fetchers and herdr-sounds-sync do read packs.json directly, and that
is the point of generating rather than keeping a second table by hand: the
pairing of a sprite with the clip that belongs to it is stated once, in the file
that also says where both come from.

This is also the only validation either side gets. An alert naming a game or a
mood that does not exist fails here, at build time, rather than at 2am as an
alert that silently plays nothing.

usage: gen-alert-tables.py [packs.json] [out.zsh]
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_JSON = HERE.parent / "sounds" / "packs.json"
DEFAULT_OUT = HERE.parent / "sounds" / "alerts-generated.zsh"

HEADER = """# alerts-generated.zsh — GENERATED from sounds/packs.json. Do not edit.
# Regenerate with scripts/gen-alert-tables.py; the plugin's [[build]] step does.
#
# Sourced by alert-hook.sh. Committed rather than built on demand so a checkout
# that was linked instead of installed — no [[build]] run — still has a table.
"""


def strip(d):
    """Drop the _comment keys. They document the file for whoever edits it and
    are not data; every consumer would otherwise have to skip them."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def q(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def flatten_moods(moods):
    """"done|win|complete" is three names for one clip, so the table is stored
    the way it is written and expanded here rather than repeated there."""
    out = {}
    for key, clip in moods.items():
        for name in key.split("|"):
            out[name] = clip
    return out


def resolve(name, spec, moods, sprite_sound, games):
    """An alert names its clip directly, by mood, or by the sprite it goes with;
    naming none of them means "anything from this game", which is all the packs
    with numbered clips can honestly offer."""
    game = spec.get("game")
    if game not in games:
        raise ValueError(f"alert '{name}': unknown game '{game}'")
    sprite = spec.get("sprite") or ""
    clip = spec.get("clip")
    if not clip and spec.get("mood"):
        clip = moods.get(spec["mood"])
        if not clip:
            raise ValueError(f"alert '{name}': unknown mood '{spec['mood']}'")
    if not clip and sprite:
        clip = sprite_sound.get(sprite, "")
    return game, clip or "", sprite


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    cfg = json.loads(src.read_text())

    games = strip(cfg["games"])
    alerts = strip(cfg["alerts"])
    states = strip(cfg["states"])
    moods = flatten_moods(strip(cfg["moods"]))
    sprite_sound = strip(cfg["sprite_sound"])
    ra_sprites = cfg.get("redalert_sprites", [])

    rows = []
    for name, spec in alerts.items():
        game, clip, sprite = resolve(name, spec, moods, sprite_sound, games)
        # Red Alert art is cut from the game's own archives, and the fetcher only
        # builds the six in redalert_sprites. Naming another is a typo that would
        # otherwise show up as a procedural disc instead of a tank.
        if game == "redalert" and sprite and sprite not in ra_sprites:
            raise ValueError(f"alert '{name}': sprite '{sprite}' is not built "
                             f"by fetch-redalert-sprites.py")
        rows.append((name, game, clip, sprite))

    for state, name in states.items():
        if name not in alerts:
            raise ValueError(f"state '{state}': unknown alert '{name}'")

    parts = [HEADER]

    # Assignment rather than `print -r --`: an alert is one record of three
    # fields, and a lookup per field would be three command substitutions to
    # read one row. zsh scopes these dynamically, so the caller's `local`
    # declarations are what these land in and nothing escapes the hook.
    lines = ["# name -> game, clip basename (empty = any clip from the game),",
             "# sprite basename (empty = any sprite from the game).",
             "# Sets alert_game / alert_clip / alert_sprite; returns 1 on an",
             "# unknown name so the caller can fall back rather than guess.",
             "__herdr_alert_spec() {",
             "  alert_game= alert_clip= alert_sprite=",
             "  case \"${1:-}\" in"]
    for name, game, clip, sprite in rows:
        fields = [f"alert_game={q(game)}"]
        if clip:
            fields.append(f"alert_clip={q(clip)}")
        if sprite:
            fields.append(f"alert_sprite={q(sprite)}")
        lines.append(f"    {name}) {'; '.join(fields)} ;;")
    lines += ["    *) return 1 ;;", "  esac", "}", ""]
    parts.append("\n".join(lines))

    lines = ["# Every name, for `alert-hook.sh --list` and for tab completion.",
             "__herdr_alert_names() {",
             f"  print -r -- {q(' '.join(n for n, _, _, _ in rows))}",
             "}", ""]
    parts.append("\n".join(lines))

    lines = ["# herdr transition -> the alert it plays when nothing overrides it.",
             "__herdr_alert_for_state() {",
             "  case \"${1:-}\" in"]
    for state, name in states.items():
        lines.append(f"    {state}) print -r -- {q(name)} ;;")
    lines += ["  esac", "}", ""]
    parts.append("\n".join(lines))

    out.write_text("\n".join(parts))
    print(f"gen-alert-tables: {len(rows)} alerts -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, ValueError) as exc:
        # Loud on purpose. Everything downstream degrades quietly, so a bad
        # mapping has exactly one place left where it can still be shouted about.
        print(f"gen-alert-tables: {exc}", file=sys.stderr)
        sys.exit(1)
