"""Opt-in rendered-pixel check in an X11 desktop running Herdr and Kitty.

Example: XDG_CONFIG_HOME=/home/tester/preferences DISPLAY=:1 python3 \
tests/test_flash_visual.py --pane w1:p1 --crop 100:100:800:300
Choose a crop entirely inside the test pane, away from text or the cursor.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pane', required=True)
    parser.add_argument('--crop', required=True, help='width:height:x:y within the X11 display')
    args = parser.parse_args()
    width, height, x, y = map(int, args.crop.split(':'))
    assert width > 0 and height > 0 and x >= 0 and y >= 0
    helper = Path(__file__).resolve().parents[1] / 'libexec/herdr-flash'
    with tempfile.TemporaryDirectory() as temporary:
        frames = Path(temporary) / 'frames.rgb'
        video = subprocess.Popen([
            'ffmpeg', '-loglevel', 'error', '-y', '-f', 'x11grab', '-framerate', '30',
            '-probesize', '32', '-analyzeduration', '0', '-i', os.environ['DISPLAY'],
            '-t', '3', '-vf', f'crop={args.crop}', '-pix_fmt', 'rgb24',
            '-f', 'rawvideo', '-flush_packets', '1', str(frames),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not frames.exists() or frames.stat().st_size < width * height * 3:
                assert video.poll() is None and time.monotonic() < deadline, 'capture did not start'
                time.sleep(.02)
            subprocess.run(['zsh', str(helper), args.pane], check=True, timeout=10)
            _, error = video.communicate(timeout=10)
            assert video.returncode == 0, error.decode()
            raw = frames.read_bytes()
            colors = [tuple(raw[n:n+3]) for n in range(0, len(raw), width * height * 3)]
            print('Rendered background colors:', sorted(set(colors)))
            assert (0, 204, 68) in colors, 'No visible green flash'
            assert colors[0] == colors[-1], 'Background was not restored'
            print('PASS: visible flash and background restoration')
        finally:
            if video.poll() is None:
                video.kill()
                video.communicate()


if __name__ == '__main__':
    main()
