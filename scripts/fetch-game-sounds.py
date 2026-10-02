#!/usr/bin/env python3
"""Download an archive.org item's sound effects into a local cache dir.

Used by the `alert8-sync` shell helper to populate
  ${XDG_CACHE_HOME:-~/.cache}/herdr-kit/sounds/<game>/
with 8-bit game sound files, later played at random by `alert8play`.

Picks ONE audio format per item (prefers wav > mp3 > ogg) so we don't download
the same clip three times. Idempotent: files already present with a matching
size are skipped. Stdlib only, no third-party deps.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

META_URL = "https://archive.org/metadata/{id}"
DL_URL = "https://archive.org/download/{id}/{name}"
FORMAT_PREFERENCE = ("wav", "mp3", "ogg")
USER_AGENT = "herdr-kit-fetch/1.0 (+personal use)"


def _get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_metadata(identifier: str) -> dict:
    with _get(META_URL.format(id=identifier)) as resp:
        return json.load(resp)


def pick_files(files: list) -> list:
    """Return the file list for the most-preferred format that exists."""
    by_ext = {ext: [] for ext in FORMAT_PREFERENCE}
    for f in files:
        name = f.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in by_ext:
            by_ext[ext].append(f)
    for ext in FORMAT_PREFERENCE:
        if by_ext[ext]:
            return by_ext[ext]
    return []


def download_one(identifier: str, name: str, dest: Path) -> bool:
    """Download a single file. Returns True if bytes were written."""
    # Flatten any archive-internal subpath into a safe basename.
    out = dest / Path(name).name
    url = DL_URL.format(id=identifier, name=urllib.parse.quote(name))
    tmp = out.with_suffix(out.suffix + ".part")
    with _get(url) as resp, open(tmp, "wb") as fh:
        while chunk := resp.read(65536):
            fh.write(chunk)
    tmp.replace(out)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("identifier", help="archive.org item identifier")
    ap.add_argument("dest", help="destination directory")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    def log(msg):
        if not args.quiet:
            print(msg, file=sys.stderr)

    try:
        meta = fetch_metadata(args.identifier)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        log(f"fetch-game-sounds: metadata failed for {args.identifier}: {exc}")
        return 1

    picked = pick_files(meta.get("files", []))
    if not picked:
        log(f"fetch-game-sounds: no audio files in {args.identifier}")
        return 1

    total = len(picked)
    got = skipped = failed = 0
    for i, f in enumerate(picked, 1):
        name = f["name"]
        out = dest / Path(name).name
        want = int(f.get("size", 0) or 0)
        if out.exists() and want and out.stat().st_size == want:
            skipped += 1
            continue
        try:
            download_one(args.identifier, name, dest)
            got += 1
            if not args.quiet and (got % 25 == 0 or i == total):
                log(f"  {args.identifier}: {i}/{total}")
        except (urllib.error.URLError, OSError) as exc:
            failed += 1
            log(f"  ! {name}: {exc}")

    # Marker lets the shell helper cheaply tell a game is populated.
    (dest / ".done").write_text(f"{got + skipped}\n")
    log(f"fetch-game-sounds: {args.identifier} -> {got} new, "
        f"{skipped} cached, {failed} failed ({total} total)")
    return 0 if failed < total else 1


if __name__ == "__main__":
    sys.exit(main())
