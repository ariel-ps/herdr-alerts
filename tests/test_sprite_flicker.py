"""Opt-in pixel regression test in an isolated X11 desktop (1440×900 or larger).

Requires Kitty and FFmpeg; --herdr also requires Herdr. Opens and closes its own
test terminal and isolated Herdr session, without touching existing sessions.

DISPLAY=:1 python3 tests/test_sprite_flicker.py [--herdr] [--renderer PATH]
"""
import argparse
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import time


def worker(directory, renderer):
    directory = Path(directory)
    fifo = directory / 'frames.pipe'
    os.mkfifo(fifo)
    (directory / 'ready').touch()
    while not (directory / 'go').exists():
        time.sleep(.01)
    child = subprocess.Popen(
        ['perl', renderer, str(fifo), str(os.get_terminal_size().columns)],
        env={**os.environ, 'SPRITE_FILE': str(directory / 'test.rgba'), 'SPRITE_PERSIST': '0'})
    # Slow down protocol delivery to expose partial uploads and replacement gaps.
    with fifo.open('rb', buffering=0) as source:
        buffer = b''
        while chunk := source.read(4096):
            buffer += chunk
            while b'\x1b\\' in buffer:
                end = buffer.index(b'\x1b\\') + 2
                os.write(1, buffer[:end])
                buffer = buffer[end:]
                time.sleep(.004)
        os.write(1, buffer)
    assert child.wait() == 0
    time.sleep(1)


def check(renderer, in_herdr):
    with tempfile.TemporaryDirectory(prefix='sprite-flicker-') as temporary:
        directory = Path(temporary)
        width, height, count = 160, 96, 12
        raw = bytearray(struct.pack('<4H', count, width, height, 1))
        for index in range(count):
            pixels = bytearray(bytes((25, 180, 240, 255)) * width * height)
            for y in range(40, 60):
                for x in range(index * 8, index * 8 + 20):
                    offset = (y * width + x) * 4
                    pixels[offset:offset + 4] = bytes((255, 50, 50, 255))
            raw += struct.pack('<H', 120) + pixels
        (directory / 'test.rgba').write_bytes(raw)
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', temporary, renderer]
        env = dict(os.environ)
        if in_herdr:
            shell = directory / 'shell'
            # This shell runs inside the new test session; stop only that session.
            shell.write_text('#!/bin/sh\n' + shlex.join(command) + '\nherdr server stop\n')
            shell.chmod(0o755)
            config = directory / 'config.toml'
            config.write_text(f'onboarding = false\n[terminal]\ndefault_shell = "{shell}"\n'
                              'kitty_graphics = true\n[experimental]\nkitty_graphics = true\n')
            env.update(XDG_CONFIG_HOME=str(directory / 'config-home'), HERDR_CONFIG_PATH=str(config))
            command = ['herdr', '--session', 'sprite-flicker-test']
        terminal = subprocess.Popen(
            ['kitty', '--start-as=fullscreen', '--title', 'sprite-flicker-check',
             '-o', 'background=#101010', '-o', 'cursor_blink_interval=0', *command],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        capture = None
        try:
            deadline = time.monotonic() + 10
            while not (directory / 'ready').exists():
                assert terminal.poll() is None and time.monotonic() < deadline, 'terminal did not start'
                time.sleep(.02)
            time.sleep(.4)
            output = directory / 'capture.rgb'
            capture = subprocess.Popen(
                ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'x11grab', '-framerate', '60',
                 '-probesize', '32', '-analyzeduration', '0', '-i', os.environ['DISPLAY'],
                 '-t', '5', '-vf', 'crop=400:200:1040:0', '-pix_fmt', 'rgb24',
                 '-f', 'rawvideo', '-flush_packets', '1', str(output)], stderr=subprocess.PIPE)
            deadline = time.monotonic() + 5
            while not output.exists() or output.stat().st_size < 400 * 200 * 3:
                assert capture.poll() is None and time.monotonic() < deadline, 'capture failed'
                time.sleep(.01)
            (directory / 'go').touch()
            _, error = capture.communicate(timeout=15)
            assert capture.returncode == 0, error
            data = output.read_bytes()
            size = 400 * 200 * 3
            snapshots = [data[i:i + size] for i in range(0, len(data) - size + 1, size)]
            samples = [frame.count(bytes((25, 180, 240))) for frame in snapshots]
            visible = [i for i, pixels in enumerate(samples) if pixels > 1000]
            assert len(visible) > 30, 'No sustained scene visible'
            gaps = [i for i in range(visible[0], visible[-1] + 1) if samples[i] < 1000]
            print(f'{len(visible)} visible samples; {len(gaps)} blank samples inside playback', flush=True)
            assert not gaps, f'Flicker: scene disappeared in {len(gaps)} captured frames'
            positions = {snapshots[i].find(bytes((255, 50, 50))) // 3 % 400 for i in visible}
            assert len(positions) > 3, 'Scene stayed visible but animation did not advance'
            assert samples[-1] < 1000, 'Scene was not cleared'
        finally:
            if capture and capture.poll() is None:
                capture.kill()
                capture.communicate()
            terminal.terminate()
            terminal.wait(timeout=5)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(*sys.argv[2:])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--herdr', action='store_true')
        parser.add_argument('--renderer', type=Path,
                            default=Path(__file__).resolve().parents[1] / 'vendor/sprite/sprite.pl')
        args = parser.parse_args()
        check(str(args.renderer.resolve()), args.herdr)
