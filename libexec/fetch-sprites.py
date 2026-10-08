#!/usr/bin/env python3
"""Build the sprite packs vendor/sprite/sprite.pl animates, one per game.

Each game's art comes from a project that ships both the sprite sheet and the
frame data describing it, so nothing here guesses at where a frame starts:

  mario     justinmeister/Mario-Level-1   frame rects in data/components/*.py
  mvdk      plemaster01/PythonDonkeyKong  one PNG per frame
  sonic     clarkeadg/opensonic-js        JSON grid + animation frame indices
  punchout  justin-austria/PunchOut       frame rects in lib/js/entities/*.js
  redalert  the game's own MIX archives   (see fetch-redalert-sprites.py)

Pack format, read by sprite.pl's load_pack: u16 frames, u16 w, u16 h,
u16 pad, then frames * w * h * 4 bytes of RGBA. Frames are square and share one
bounding box per pack — trimming each frame to its own content would make the
sprite jitter as it animates.

usage: fetch-sprites.py <dest-dir> [game ...]
"""

import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SIZE = 40          # packs are built at 40px; sprite.pl scales on load

CONFIG = Path(__file__).resolve().parents[1] / "data" / "packs.json"


def repos():
    """game -> clone URL, from packs.json. The per-game cutting below stays as
    code: it is frame geometry, not policy, and reads worse as data."""
    games = json.loads(CONFIG.read_text())["games"]
    return {g: spec["sprites"].split(":", 1)[1]
            for g, spec in games.items()
            if not g.startswith("_") and (spec.get("sprites") or "").startswith("git:")}


def clone(url, into):
    subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(into)],
                   check=True)


def transparent(im, key=None, tol=30):
    """Key colour -> alpha 0. key=None keys on black."""
    px = im.load()
    k = key if key else (0, 0, 0)
    for j in range(im.height):
        for i in range(im.width):
            r, g, b, a = px[i, j]
            if a == 0 or (abs(r - k[0]) < tol and abs(g - k[1]) < tol
                          and abs(b - k[2]) < tol):
                px[i, j] = (0, 0, 0, 0)
    return im


def write_pack(frames, dest):
    boxes = [f.getbbox() for f in frames if f.getbbox()]
    if not boxes:
        raise ValueError(f"no visible frames for {dest.name}")
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[2] for b in boxes)
    bottom = max(b[3] for b in boxes)
    out = bytearray(struct.pack("<HHHH", len(frames), SIZE, SIZE, 0))
    for f in frames:
        c = f.crop((left, top, right, bottom))
        side = max(c.width, c.height)
        pad = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        pad.paste(c, ((side - c.width) // 2, (side - c.height) // 2))
        out += pad.resize((SIZE, SIZE), Image.NEAREST).tobytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(out))
    return True


def from_rects(sheet_path, rects, key=None):
    sheet = Image.open(sheet_path).convert("RGBA")
    k = key if key != "corner" else sheet.getpixel((0, 0))[:3]
    return [transparent(sheet.crop((x, y, x + w, y + h)).copy(), k)
            for (x, y, w, h) in rects]


def from_files(paths):
    return [transparent(Image.open(p).convert("RGBA")) for p in paths]


def composite(canvas_size, layers):
    """One frame built from several (sheet, rect, paste_xy) crops, stacked in
    order. Used where no single sheet cell shows the interaction (e.g. Mario
    standing on a Koopa) but the source draws it as separate sprites anyway."""
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    sheets = {}
    for sheet_path, rect, xy in layers:
        sheet = sheets.setdefault(sheet_path, Image.open(sheet_path).convert("RGBA"))
        x, y, w, h = rect
        crop = transparent(sheet.crop((x, y, x + w, y + h)).copy())
        canvas.paste(crop, xy, crop)
    return canvas


def build_mario(src, out):
    g = src / "resources/graphics"
    mario_sheet = g / "mario_bros.png"
    enemies_sheet = g / "smb_enemies_sheet.png"
    packs = {
        # mario.py:111-115, bounced so the loop reads as a walk
        "walk": (g / "mario_bros.png",
                 [(80, 32, 15, 16), (96, 32, 16, 16), (112, 32, 16, 16),
                  (96, 32, 16, 16)]),
        "jump": (g / "mario_bros.png",
                 [(144, 32, 16, 16), (130, 32, 14, 16), (178, 32, 12, 16)]),
        "goomba": (g / "smb_enemies_sheet.png",
                   [(0, 4, 16, 16), (30, 4, 16, 16)]),
        "koopa": (g / "smb_enemies_sheet.png",
                  [(150, 0, 16, 24), (180, 0, 16, 24)]),
        # powerups.py:95,115 — the mushroom has no animation of its own, so the
        # red one and the 1-up alternate to give the pack something to loop.
        "mushroom": (g / "item_objects.png",
                     [(0, 0, 16, 16), (16, 0, 16, 16)]),
        "fireflower": (g / "item_objects.png",          # powerups.py:128-134
                       [(0, 32, 16, 16), (16, 32, 16, 16),
                        (32, 32, 16, 16), (48, 32, 16, 16)]),
        "star": (g / "item_objects.png",                # powerups.py:186-189
                 [(1, 48, 15, 16), (17, 48, 15, 16),
                  (33, 48, 15, 16), (49, 48, 15, 16)]),
    }
    for name, (sheet, rects) in packs.items():
        write_pack(from_rects(sheet, rects), out / f"{name}.rgba")

    # Mario jumping on a Koopa: his falling frame (mario.py:117) over the
    # Koopa's walk frames, landing on its shell frame (enemies.py:172,
    # jumped_on's frame_index 2) — the same stomp-to-shell sequence the game
    # itself plays, just drawn as one scene instead of two separate sprites.
    jump_rect = (144, 32, 16, 16)
    stomp_frames = [
        composite((16, 40), [(enemies_sheet, (150, 0, 16, 24), (0, 16)),
                             (mario_sheet, jump_rect, (0, 4))]),
        composite((16, 40), [(enemies_sheet, (180, 0, 16, 24), (0, 16)),
                             (mario_sheet, jump_rect, (0, 0))]),
        composite((16, 40), [(enemies_sheet, (360, 5, 16, 15), (0, 25)),
                             (mario_sheet, jump_rect, (0, 9))]),
    ]
    write_pack(stomp_frames, out / "stomp.rgba")
    return len(packs) + 1


def build_mvdk(src, out):
    g = src / "assets/images"
    packs = {
        "dk": [g / "dk/dk1.png", g / "dk/dk2.png", g / "dk/dk3.png",
               g / "dk/dk2.png"],
        "barrel": [g / "barrels/barrel.png", g / "barrels/barrel2.png",
                   g / "barrels/barrel3.png"],
        "jumpman": [g / "mario/running.png", g / "mario/jumping.png",
                    g / "mario/standing.png"],
        "peach": [g / "peach/peach1.png", g / "peach/peach2.png"],
    }
    for name, files in packs.items():
        write_pack(from_files(files), out / f"{name}.rgba")
    return len(packs)


def build_sonic(src, out):
    spec = json.loads((src / "public/data/sprites/surge.json").read_text())["SD_SONIC"]
    rect, fs = spec["source_rect"], spec["frame_size"]
    sheet_name = spec["source_file"].split("/")[-1]
    sheet = src / "public/data/images" / sheet_name
    cols = rect["width"] // fs["width"]

    def rects(idxs):
        return [(rect["xpos"] + (i % cols) * fs["width"],
                 rect["ypos"] + (i // cols) * fs["height"],
                 fs["width"], fs["height"]) for i in idxs]

    packs = {"run": range(30, 38), "walk": range(26, 30), "spin": range(15, 20)}
    for name, idxs in packs.items():
        write_pack(from_rects(sheet, rects(idxs), "corner"), out / f"{name}.rgba")
    return len(packs)


def build_punchout(src, out):
    g = src / "assets/img"
    # These sheets sit on an opaque background and the sprites are outlined in
    # black, so they key on the sheet's own corner colour, never on black.
    packs = {
        "mac": (g / "little_mac2.png", [(28, 10, 72, 161), (98, 10, 72, 161)]),
        "mac_dodge": (g / "little_mac2.png",
                      [(21, 160, 72, 161), (91, 160, 72, 161),
                       (161, 160, 72, 161)]),
        "glass_joe": (g / "glass_joe.png",
                      [(19, 26, 80, 220), (109, 26, 80, 220),
                       (199, 26, 80, 220)]),
    }
    for name, (sheet, rects) in packs.items():
        write_pack(from_rects(sheet, rects, "corner"), out / f"{name}.rgba")
    return len(packs)


BUILDERS = {"mario": build_mario, "mvdk": build_mvdk,
            "sonic": build_sonic, "punchout": build_punchout}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    dest = Path(sys.argv[1]).expanduser()
    games = sys.argv[2:] or list(BUILDERS)

    if not shutil.which("git"):
        print("fetch-sprites: git not found", file=sys.stderr)
        return 1

    urls = repos()
    rc = 0
    for game in games:
        if game not in BUILDERS:
            print(f"fetch-sprites: no sprite source for '{game}'", file=sys.stderr)
            rc = 1
            continue
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / game
            try:
                clone(urls[game], src)
                n = BUILDERS[game](src, dest / game)
            except (subprocess.CalledProcessError, OSError, KeyError,
                    ValueError) as exc:
                print(f"fetch-sprites: {game} failed: {exc}", file=sys.stderr)
                rc = 1
                continue
        print(f"fetch-sprites: {game} -> {n} packs", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
