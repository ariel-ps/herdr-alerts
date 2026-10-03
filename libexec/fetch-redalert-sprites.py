#!/usr/bin/env python3
"""Build Red Alert sprite packs out of the game's own SHP archives.

Reuses fetch-redalert-sounds.py to read MIX files from OpenRA's base package, then
decodes the TD/RA sprite format: a 14-byte header, one 8-byte entry per frame
(absolute offset + format), and frames stored either LCW-compressed or as an
XOR delta against an earlier frame. LCW (Format80) and the XOR delta (Format40)
follow OpenRA's implementations rather than my reading of the spec.

Colours come from temperat.pal inside the same archives — a 6-bit VGA
palette. Index 0 is transparent and index 4 is the unit shadow, which would
otherwise render as a solid green slab.

Base package source: OpenRA's mods/ra-content/installer/downloads.yaml.
The URL and pinned checksum live in data/packs.json.

usage: fetch-redalert-sprites.py <dest-dir>
"""

import hashlib
import io
import json
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ra_sounds", ROOT / "libexec" / "fetch-redalert-sounds.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

index = _mod.index

SIZE = 40
SHADOW = 4
CONFIG = ROOT / "data" / "packs.json"
# MIX entries are keyed by a hash of the filename, not the name, so the ids are
# derived rather than written down.
WANTED_NAMES = json.loads(CONFIG.read_text())["redalert_sprites"]


def mix_id(name):
    """Westwood's TD/RA filename hash."""
    name = name.upper().encode("ascii")
    ln = len(name)
    a = ln >> 2
    if ln & 3:
        name += bytes([ln - (a << 2)])
        for _ in range(3 - (ln & 3)):
            name += name[(a << 2) + 1:(a << 2) + 2]
    crc = 0
    for i in range(0, len(name), 4):
        d = struct.unpack("<I", name[i:i + 4])[0]
        crc = ((crc << 1) | (crc >> 31)) & 0xFFFFFFFF
        crc = (crc + d) & 0xFFFFFFFF
    return crc


WANTED = {n: mix_id(n + ".shp") for n in WANTED_NAMES}


def lcw_decode(src, i, dest):
    d, n = 0, len(dest)
    while d < n:
        cmd = src[i]; i += 1
        if not cmd & 0x80:
            second = src[i]; i += 1
            count = ((cmd & 0x70) >> 4) + 3
            rpos = ((cmd & 0x0F) << 8) + second
            if d + count > n:
                return
            for k in range(count):
                dest[d + k] = dest[d - 1] if rpos == 1 else dest[d - rpos + k]
            d += count
        elif not cmd & 0x40:
            count = cmd & 0x3F
            if count == 0:
                return
            count = min(count, n - d)
            dest[d:d + count] = src[i:i + count]
            i += count; d += count
        else:
            c3 = cmd & 0x3F
            if c3 == 0x3E:
                count = struct.unpack("<H", src[i:i + 2])[0]; i += 2
                color = src[i]; i += 1
                count = min(count, n - d)
                for k in range(count):
                    dest[d + k] = color
                d += count
            else:
                count = struct.unpack("<H", src[i:i + 2])[0] if c3 == 0x3F else c3 + 3
                if c3 == 0x3F:
                    i += 2
                s = struct.unpack("<H", src[i:i + 2])[0]; i += 2
                count = min(count, n - d)
                for k in range(count):
                    dest[d + k] = dest[s + k]
                d += count


def xor_decode(src, i, dest):
    d, n = 0, len(dest)
    while True:
        cmd = src[i]; i += 1
        if not cmd & 0x80:
            count = cmd & 0x7F
            if count == 0:
                count = src[i]; i += 1
                val = src[i]; i += 1
                for _ in range(count):
                    if d >= n:
                        return
                    dest[d] ^= val; d += 1
            else:
                for _ in range(count):
                    if d >= n:
                        return
                    dest[d] ^= src[i]; i += 1; d += 1
        else:
            count = cmd & 0x7F
            if count:
                d += count
                continue
            count = struct.unpack("<H", src[i:i + 2])[0]; i += 2
            if count == 0:
                return
            if not count & 0x8000:
                d += count & 0x7FFF
            elif not count & 0x4000:
                for _ in range(count & 0x3FFF):
                    if d >= n:
                        return
                    dest[d] ^= src[i]; i += 1; d += 1
            else:
                val = src[i]; i += 1
                for _ in range(count & 0x3FFF):
                    if d >= n:
                        return
                    dest[d] ^= val; d += 1


def shp_frames(blob):
    if len(blob) < 14:
        return None
    nimg, _a, _b, w, h = struct.unpack("<HHHHH", blob[:10])
    if not (0 < nimg < 1000 and 0 < w <= 640 and 0 < h <= 400):
        return None
    if len(blob) < 14 + (nimg + 2) * 8:
        return None
    heads = []
    for i in range(nimg):
        v, ref, _rf = struct.unpack("<IHH", blob[14 + i * 8:22 + i * 8])
        heads.append({"off": v & 0xFFFFFF, "fmt": v >> 24, "ref": ref, "data": None})
    by_off = {hd["off"]: i for i, hd in enumerate(heads)}

    def build(i, depth=0):
        hd = heads[i]
        if hd["data"] is not None or depth > nimg:
            return hd["data"]
        buf = bytearray(w * h)
        if hd["fmt"] == 0x80:
            lcw_decode(blob, hd["off"], buf)
        elif hd["fmt"] in (0x20, 0x40):
            ref = i - 1 if hd["fmt"] == 0x20 else by_off.get(hd["ref"])
            if ref is None or ref < 0:
                return None
            base = build(ref, depth + 1)
            if base is None:
                return None
            buf[:] = base
            xor_decode(blob, hd["off"], buf)
        else:
            return None
        hd["data"] = buf
        return buf

    out = []
    for i in range(nimg):
        try:
            f = build(i)
        except (IndexError, struct.error):
            f = None
        out.append(f if f is not None else bytearray(w * h))
    return w, h, out


def main() -> int:
    dest = Path(sys.argv[1]).expanduser()
    try:
        source = json.loads(CONFIG.read_text())["games"]["redalert"]
        with urllib.request.urlopen(source["sprites"], timeout=120) as response:
            archive = response.read(32 * 1024 * 1024 + 1)
        if hashlib.sha256(archive).hexdigest() != source["sprites_sha256"]:
            raise ValueError("base package checksum mismatch")
        package = zipfile.ZipFile(io.BytesIO(archive))
    except Exception as exc:
        print(f"fetch-redalert-sprites: cannot read base package: {exc}", file=sys.stderr)
        return 1

    want = set(WANTED.values())
    by_id = {v: k for k, v in WANTED.items()}
    written = 0
    palette = None
    sprites = {}
    for name in ("local.mix", "conquer.mix"):
        blob = package.read(name)
        try:
            ents, sub_body = index(lambda o, l: blob[o:o + l])
        except Exception:
            continue
        for s_id, s_off, s_size in ents:
            if s_id == mix_id("temperat.pal"):
                palette = blob[sub_body + s_off:sub_body + s_off + s_size]
            if s_id not in want:
                continue
            res = shp_frames(blob[sub_body + s_off:sub_body + s_off + s_size])
            if not res:
                continue
            sprites[s_id] = res

    if palette is None or len(palette) != 768 or max(palette) > 63:
        print("fetch-redalert-sprites: valid temperat.pal not found in base package", file=sys.stderr)
        return 1
    rgb = [tuple(c * 255 // 63 for c in palette[i:i + 3]) for i in range(0, 768, 3)]
    for s_id, (w, h, frames) in sprites.items():
        frames = frames[:16]
        out = bytearray(struct.pack("<HHHH", len(frames), SIZE, SIZE, 0))
        for fr in frames:
            im = Image.new("RGBA", (w, h))
            px = im.load()
            for y in range(h):
                for x in range(w):
                    v = fr[y * w + x]
                    px[x, y] = (0, 0, 0, 0) if v in (0, SHADOW) \
                        else (*rgb[v], 255)
            side = max(w, h)
            pad = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            pad.paste(im, ((side - w) // 2, (side - h) // 2))
            out += pad.resize((SIZE, SIZE), Image.NEAREST).tobytes()
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{by_id[s_id]}.rgba").write_bytes(bytes(out))
        written += 1

    print(f"fetch-redalert-sprites: {written} packs", file=sys.stderr)
    return 0 if written == len(WANTED) else 1


if __name__ == "__main__":
    sys.exit(main())
