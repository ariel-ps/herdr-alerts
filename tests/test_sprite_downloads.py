"""Run with: uv run --with pillow --with pycryptodome python tests/test_sprite_downloads.py."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sprites', ROOT / 'libexec/fetch-redalert-sprites.py')
sprites = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sprites)


def mix(entries, modern=False):
    payload = b''
    index = b''
    for name, data in entries:
        index += struct.pack('<III', sprites.mix_id(name), len(payload), len(data))
        payload += data
    return (bytes(4) if modern else b'') + struct.pack('<HI', len(entries), len(payload)) + index + payload


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    # Both original and zero-flag modern MIX headers must expose their files.
    shp = struct.pack('<7H', 1, 0, 0, 1, 1, 0, 0) + struct.pack('<IHH', 0x80000026, 0, 0) + bytes(16) + b'\x81\x05\x80'
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('local.mix', mix([('temperat.pal', bytes(range(64)) * 12)]))
        package.writestr('conquer.mix', mix([(name + '.shp', shp) for name in sprites.WANTED], modern=True))
    data = archive.getvalue()
    config = root / 'packs.json'
    source = {'sprites': 'https://example.invalid/ra-base.zip', 'sprites_sha256': hashlib.sha256(data).hexdigest()}
    config.write_text(json.dumps({'games': {'redalert': source}}))
    dest = root / 'sprites'
    with patch.object(sprites, 'CONFIG', config), patch.object(sys, 'argv', ['fetch', str(dest)]):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(data)):
            assert sprites.main() == 0
        assert len(list(dest.glob('*.rgba'))) == len(sprites.WANTED)
        for pack in dest.glob('*.rgba'):
            raw = pack.read_bytes()
            assert struct.unpack('<4H', raw[:8]) == (1, 40, 40, 0)
            assert len(raw) == 8 + 40 * 40 * 4 and raw[11] == 255
        before = {p.name: p.read_bytes() for p in dest.iterdir()}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(data + b'corrupt')):
            assert sprites.main() == 1
        assert before == {p.name: p.read_bytes() for p in dest.iterdir()}
print('PASS: original/modern MIX archives, palette, sprite packs, checksum rejection')
