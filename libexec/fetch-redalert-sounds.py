#!/usr/bin/env python3
"""Extract Command & Conquer: Red Alert sound effects into a local cache dir.

No archive.org item ships RA's sounds as loose audio files, so this pulls them
out of the game itself: the Allied CD's MAIN.MIX is on archive.org as a loose
file, and archive.org honours HTTP range requests. We read only the encrypted
MIX headers, walk down to the nested MIXes that hold Westwood .AUD clips, and
download just those (~7 MB of a 454 MB file). ffmpeg converts .AUD to .wav.

Needs `pycryptodome` (Blowfish) and `ffmpeg` on PATH. Invoked by
`herdr-sound sync` through `libexec/fetch-redalert-sounds.py`.
"""

import argparse
import base64
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from Crypto.Cipher import Blowfish

ITEM = "main_20260628"
FILE = "MAIN.MIX"
URL = f"https://archive.org/download/{ITEM}/{FILE}"
# Westwood's RSA public key, wrapping the Blowfish key of an encrypted MIX.
PUBKEY = "AihRvNoIbTn85FZRYNZRcT+i6KpU+maCsEqr3Q5q+LDB5tH7Tz2qQ38V"
UA = {"User-Agent": "herdr-kit-fetch/1.0 (+personal use)"}
# Entries bigger than this are the movie and score MIXes, not sound effects.
MAX_SUBMIX = 3_000_000
# Clips this short are inaudible as an alert.
MIN_SECONDS = 0.3


def get_range(url, start, length, tries=5):
    req = urllib.request.Request(
        url, headers={**UA, "Range": f"bytes={start}-{start + length - 1}"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if len(data) == length:
                return data
        except (urllib.error.URLError, OSError):
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise IOError(f"short read at {start}+{length}")


def blowfish_key(blob80):
    key = base64.b64decode(PUBKEY)
    assert key[0] == 0x02, f"unexpected pubkey tag {key[0]:#x}"
    n = int.from_bytes(key[2:2 + key[1]], "big")
    step = (n.bit_length() - 1) // 8 + 1
    out = b""
    for i in range(2):
        m = int.from_bytes(blob80[i * step:(i + 1) * step], "little")
        out += pow(m, 65537, n).to_bytes(step, "little")[:step - 1]
    return out[:56]


def index(read, base=0):
    """Parse a MIX header. read(offset, length) -> bytes. -> (entries, body)."""
    flags = struct.unpack("<I", read(base, 4))[0]
    if flags & 0xFFFF:
        count = struct.unpack("<H", read(base, 2))[0]
        head, idx_at = base + 6, base + 6
    elif not flags & 0x00020000:
        count = struct.unpack("<H", read(base + 4, 2))[0]
        head, idx_at = base + 10, base + 10
    else:
        bf = Blowfish.new(blowfish_key(read(base + 4, 80)), Blowfish.MODE_ECB)
        first = bf.decrypt(read(base + 84, 8))
        count = struct.unpack("<H", first[:2])[0]
        total = ((6 + count * 12 + 7) // 8) * 8
        idx = (first[6:] + bf.decrypt(read(base + 92, total - 8)))[:count * 12]
        body = base + 84 + total
        return [struct.unpack("<IiI", idx[i * 12:(i + 1) * 12])
                for i in range(count)], body

    idx = read(idx_at, count * 12)
    return [struct.unpack("<IiI", idx[i * 12:(i + 1) * 12])
            for i in range(count)], head + count * 12


def is_aud(blob):
    if len(blob) < 12:
        return False
    rate = struct.unpack("<H", blob[:2])[0]
    return rate in (11025, 22050) and blob[11] in (1, 99)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dest", help="destination directory")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    def log(msg):
        if not args.quiet:
            print(msg, file=sys.stderr)

    if not shutil_which("ffmpeg"):
        log("fetch-redalert-sounds: ffmpeg not found")
        return 1

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    remote = lambda off, ln: get_range(URL, off, ln)          # noqa: E731
    try:
        top, body = index(remote)
    except Exception as exc:
        log(f"fetch-redalert-sounds: cannot read {FILE}: {exc}")
        return 1

    tmp = dest / ".aud"
    tmp.mkdir(exist_ok=True)
    written = 0
    for eid, off, size in top:
        if size > MAX_SUBMIX:
            continue
        blob = b""
        while len(blob) < size:
            blob += get_range(URL, body + off + len(blob),
                              min(2 << 20, size - len(blob)))
        try:
            ents, sub_body = index(lambda o, l: blob[o:o + l])
        except Exception:
            continue
        for s_id, s_off, s_size in ents:
            clip = blob[sub_body + s_off:sub_body + s_off + s_size]
            if is_aud(clip):
                (tmp / f"{eid:08x}_{s_id:08x}.aud").write_bytes(clip)
                written += 1
        log(f"  {eid:#010x}: {written} clips so far")

    if not written:
        log("fetch-redalert-sounds: no .AUD clips found")
        return 1

    kept = dropped = failed = 0
    for aud in sorted(tmp.glob("*.aud")):
        wav = dest / f"{aud.stem}.wav"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(aud), "-ar", "22050",
             str(wav)], capture_output=True)
        if proc.returncode or not wav.exists() or not wav.stat().st_size:
            wav.unlink(missing_ok=True)
            failed += 1
        elif duration(wav) < MIN_SECONDS:
            wav.unlink()
            dropped += 1
        else:
            kept += 1
        aud.unlink()
    tmp.rmdir()

    (dest / ".done").write_text(f"{kept}\n")
    log(f"fetch-redalert-sounds: {kept} clips "
        f"({dropped} too short, {failed} failed)")
    return 0 if kept else 1


def duration(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def shutil_which(name):
    from shutil import which
    return which(name)


if __name__ == "__main__":
    sys.exit(main())
