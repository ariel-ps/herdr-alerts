#!/usr/bin/env python3
"""Convert a GIF or animated PNG once into a timed sprite pack.

Header: little-endian u16 frame count, width, height, version (1).
Each frame: u16 duration in milliseconds, then width * height * 4 RGBA bytes.
Version 0 packs omit durations and remain readable by the renderer.
"""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile

from PIL import Image


def convert(source, destination):
    with Image.open(source) as image:
        if image.format not in ('GIF', 'PNG'):
            raise ValueError('use a GIF or animated PNG')
        width, height = image.size
        first = int(bool(image.info.get('default_image', False)))
        count = getattr(image, 'n_frames', 1) - first
        if not (1 <= width <= 512 and 1 <= height <= 512 and 1 <= count <= 600):
            raise ValueError('animation must be at most 512×512 pixels and 600 frames')
        if 8 + count * (width * height * 4 + 2) > 64 * 1024 * 1024:
            raise ValueError('decoded animation must fit within 64 MiB')
        data = bytearray(struct.pack('<4H', count, width, height, 1))
        total = 0
        for index in range(first, first + count):
            image.seek(index)
            delay = round(image.info.get('duration', 100)) or 100
            if not 10 <= delay <= 10000:
                raise ValueError('frame durations must be between 10 ms and 10 seconds')
            total += delay
            if total > 30000:
                raise ValueError('one animation cycle must be at most 30 seconds')
            frame = image.convert('RGBA')
            if frame.size != (width, height):
                raise ValueError('frames must share a canvas')
            data.extend(struct.pack('<H', delay))
            data.extend(frame.tobytes())
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (hashlib.sha256(data).hexdigest() + '.rgba')
    # A failed import must not replace a working scene or leave a partial pack.
    with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target.resolve()


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('usage: import-animation.py INPUT.gif DESTINATION')
        print(convert(Path(sys.argv[1]), Path(sys.argv[2])))
    except (OSError, ValueError, EOFError, Image.DecompressionBombError) as error:
        print(f'herdr-alert: cannot import animation: {error}', file=sys.stderr)
        sys.exit(1)
