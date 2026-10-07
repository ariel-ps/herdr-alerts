#!/usr/bin/env python3
"""Clone a git repo and copy its own sound clips into a local cache dir.

Used by `herdr-sound sync` to populate
  ${XDG_CACHE_HOME:-~/.cache}/herdr-kit/sounds/<game>/
for games whose source repo ships its own named audio clips instead of an
archive.org item (see fetch-game-sounds.py for that path). Picks ONE audio
format per clip basename (prefers wav > mp3 > ogg), same as the archive
fetcher, so a repo shipping both a .wav and .mp3 of the same clip isn't
downloaded twice. Stdlib only, no third-party deps.

usage: fetch-git-sounds.py <git-url> <dest>
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FORMAT_PREFERENCE = ("wav", "mp3", "ogg")


def clone(url: str, into: Path) -> None:
    subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(into)], check=True)


def find_clips(src: Path) -> list[Path]:
    """Every audio file under the repo, one per basename, preferring the same
    format order as fetch-game-sounds.py so sync behaves identically either way."""
    by_stem: dict[str, dict[str, Path]] = {}
    for ext in FORMAT_PREFERENCE:
        for path in src.rglob(f"*.{ext}"):
            by_stem.setdefault(path.stem, {})[ext] = path
    picked = []
    for stem, by_ext in by_stem.items():
        for ext in FORMAT_PREFERENCE:
            if ext in by_ext:
                picked.append(by_ext[ext])
                break
    return picked


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: fetch-git-sounds.py <git-url> <dest>", file=sys.stderr)
        return 2
    url, dest = sys.argv[1], Path(sys.argv[2]).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    if not shutil.which("git"):
        print("fetch-git-sounds: git not found", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "repo"
        try:
            clone(url, src)
        except subprocess.CalledProcessError as exc:
            print(f"fetch-git-sounds: clone failed for {url}: {exc}", file=sys.stderr)
            return 1

        clips = find_clips(src)
        if not clips:
            print(f"fetch-git-sounds: no audio files in {url}", file=sys.stderr)
            return 1

        got = skipped = 0
        for clip in clips:
            out = dest / clip.name
            if out.exists() and out.stat().st_size == clip.stat().st_size:
                skipped += 1
                continue
            shutil.copy2(clip, out)
            got += 1

    (dest / ".done").write_text(f"{got + skipped}\n")
    print(f"fetch-git-sounds: {url} -> {got} new, {skipped} cached ({len(clips)} total)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
