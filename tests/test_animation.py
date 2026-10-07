"""Run with: uv run --with pillow python tests/test_animation.py."""
import base64
import importlib.util
import json
import os
import pty
from pathlib import Path
import re
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('animation', ROOT / 'libexec/import-animation.py')
animation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(animation)


def displayed_frames(path):
    commands = re.findall(rb'\x1b_G([^;\x1b]+)(?:;([^\x1b]*))?\x1b\\', path.read_bytes())
    uploads = [control for control, _ in commands if control.startswith(b'a=t,')]
    assert len(uploads) == 1, 'Playback must upload once, without replacing a visible image'
    width = int(re.search(rb',s=(\d+)', uploads[0])[1])
    pixels = base64.b64decode(b''.join(payload for _, payload in commands))
    frames = []
    for control, _ in commands:
        if not control.startswith(b'a=p,'):
            continue
        fields = dict(part.split(b'=') for part in control.split(b','))
        x, y, w, h = [int(fields[key]) for key in (b'x', b'y', b'w', b'h')]
        frame = b''.join(pixels[((y + row) * width + x) * 4:((y + row) * width + x + w) * 4]
                         for row in range(h))
        frames.append((control, frame))
    return frames


def check():
    subprocess.run(['cargo', 'build', '--locked', '--quiet'], cwd=ROOT, check=True)
    binary = ROOT / 'target/debug/herdr-sound'
    with tempfile.TemporaryDirectory(prefix='alert animation ') as temporary:
        home = Path(temporary).resolve()
        # Three seconds, rectangular, more than 16 distinct frames, variable timing.
        frames = [Image.new('RGBA', (4, 2), (i * 7, 32, 64, 255)) for i in range(30)]
        source = home / 'jump scene.gif'
        frames[0].save(source, save_all=True, append_images=frames[1:],
                       duration=[80, 120] * 15, loop=0)
        target = animation.convert(source, home / 'packs')
        raw = target.read_bytes()
        assert struct.unpack('<4H', raw[:8]) == (30, 4, 2, 1)
        assert [struct.unpack_from('<H', raw, 8 + i * 34)[0] for i in range(30)] == [80, 120] * 15
        assert raw[-32:] == frames[-1].tobytes()

        # APNG's optional poster frame is not part of the animation cycle.
        png = home / 'scene.png'
        frames[0].save(png, save_all=True, append_images=frames[1:3], default_image=True,
                       duration=[80, 120], loop=0)
        assert struct.unpack('<4H', animation.convert(png, home / 'packs').read_bytes()[:8]) == (2, 4, 2, 1)

        focus = home / 'focus'
        def set_focus(value):
            pending = home / 'focus.tmp'
            pending.write_text(json.dumps({'result': {'pane': {'focused': value}}}))
            pending.replace(focus)
        herdr = home / 'herdr'
        herdr.write_text('#!/bin/sh\ncat "$FOCUS_FILE"\n')
        herdr.chmod(0o755)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('SPRITE_', 'HERDR_', 'KITTY_'))}
        env.update(HOME=temporary, SPRITE_FILE=str(target), FOCUS_FILE=str(focus),
                   HERDR_BIN_PATH=str(herdr), SPRITE_PANE_ID='w1:p1', SPRITE_TTL='5')
        renderer = ['perl', str(ROOT / 'vendor/sprite/sprite.pl')]
        output = home / 'rendered'
        set_focus(True)
        started = time.monotonic()
        subprocess.run([*renderer, str(output), '80'], env=env, check=True, timeout=15)
        assert time.monotonic() - started >= 3
        rendered = displayed_frames(output)
        assert len(rendered) == 30, len(rendered)
        assert all(b'w=4,h=2,' in control for control, _ in rendered)
        assert [data for _, data in rendered] == [f.tobytes() for f in frames]
        assert b'\x1b_Ga=d,d=I,' in output.read_bytes()
        print('PASS: focused scene renders every frame, dimensions, and full timing')

        # A loop must wrap without the old 600ms pause, then stop during a cycle.
        master, slave = pty.openpty()
        set_focus(False)
        process = subprocess.Popen([*renderer, os.ttyname(slave), '80'], env=env)
        deadline = time.monotonic() + 15
        last_frame_at = None
        data = b''
        def read_output():
            nonlocal data
            if select.select([master], [], [], .02)[0]:
                data += os.read(master, 65536)
            return len(re.findall(rb'\x1b_Ga=p,', data))
        try:
            while time.monotonic() < deadline:
                count = read_output()
                if count >= 30 and last_frame_at is None:
                    last_frame_at = time.monotonic()
                if count >= 31:
                    assert time.monotonic() - last_frame_at < .55, 'Unexpected pause at loop boundary'
                    break
                time.sleep(.01)
            else:
                raise AssertionError('Scene did not loop')
            assert b'\x1b_Ga=d,d=I,' not in data
            set_focus(True)
            deadline = time.monotonic() + 1.5
            while b'\x1b_Ga=d,d=I,' not in data and time.monotonic() < deadline:
                read_output()
            assert b'\x1b_Ga=d,d=I,' in data, 'Focus did not dismiss mid-cycle'
            assert len(re.findall(rb'\x1b_Ga=p,', data)) < 60, 'Waited for a whole second cycle'
            assert process.wait(timeout=3) == 0
        finally:
            set_focus(True)
            if process.poll() is None:
                process.kill()
                process.wait()
            deadline = time.monotonic() + 2
            while b'\x1b_Ga=d,d=I,' not in data and time.monotonic() < deadline:
                read_output()
            os.close(master)
            os.close(slave)
        print('PASS: seamless looping and mid-cycle focus dismissal')

        # Reject truncated or oversized packs as a whole, never play partial data.
        for malformed in [raw[:-1], struct.pack('<4H', 600, 512, 512, 1),
                          struct.pack('<4H', 1, 1, 1, 9), b'bad']:
            broken = home / 'broken.rgba'
            broken.write_bytes(malformed)
            result = subprocess.run([*renderer, str(output), '80'],
                                    env={**env, 'SPRITE_FILE': str(broken)},
                                    capture_output=True, check=True, timeout=10)
            assert b'using fallback artwork' in result.stderr
            assert len(displayed_frames(output)) == 14

        # Exercise the actual public command, using this Pillow interpreter for uv.
        tools = home / 'bin'
        tools.mkdir()
        uv = tools / 'uv'
        uv.write_text(f'#!/bin/sh\nshift 5\nexec {shlex.quote(sys.executable)} "$@"\n')
        uv.chmod(0o755)
        plugin = home / 'plugin'
        (plugin / 'libexec').mkdir(parents=True)
        (plugin / 'config.sh').write_text('HERDR_ALERT_FLASH=0\nHERDR_ALERT_SPRITE=1\n')
        (plugin / 'libexec/import-animation.py').symlink_to(ROOT / 'libexec/import-animation.py')
        (plugin / 'libexec/herdr-visuals').write_text('print -r -- "$SPRITE_FILE" > "$VISUAL_LOG"\n')
        (plugin / 'libexec/herdr-play-sound').write_text('exit 0\n')
        (plugin / 'assets/audio').mkdir(parents=True)
        (plugin / 'assets/audio/8bit-alert.wav').touch()
        for player in ('afplay', 'ffplay'):
            (tools / player).write_text('#!/bin/sh\nexit 0\n')
            (tools / player).chmod(0o755)
        env.update(HERDR_PLUGIN_ROOT=str(plugin), HERDR_PLUGIN_CONFIG_DIR=str(home / 'config'),
                   XDG_DATA_HOME=str(home / 'data'), VISUAL_LOG=str(home / 'visual'),
                   PATH=str(tools) + ':' + os.environ['PATH'])
        def cli(*args, ok=True):
            result = subprocess.run([str(binary), *args], env=env, capture_output=True, text=True)
            assert (result.returncode == 0) == ok, result.stderr
            return result
        cli('set', 'animation', str(source))
        config = home / 'config/config.sh'
        saved = config.read_bytes()
        imported = next((home / 'data/herdr-alert/animations').glob('*.rgba'))
        assert imported.read_bytes() == raw
        assert str(imported).encode() in saved
        source.unlink()  # Playback must not depend on the original input file.
        # A bare preview (no NAME) isn't previewing any specific event, so it
        # never forces the custom scene on its own -- that would be the old
        # blanket-override behavior; the scene is now a category of sprite,
        # assigned per event.
        cli('play')
        assert (home / 'visual').read_text().strip() == ''
        (home / 'visual').unlink()
        cli('set', 'animation', 'on')
        subprocess.run(['zsh', str(ROOT / 'hooks/on-pane-agent-status-changed-alert.zsh')],
                       env={**env, 'HERDR_PLUGIN_EVENT_JSON': json.dumps({
                           'data': {'pane_id': 'w1:p1', 'agent_status': 'blocked'}})}, check=True)
        deadline = time.monotonic() + 3
        while (not (home / 'visual').exists() or not (home / 'visual').read_text()) and time.monotonic() < deadline:
            time.sleep(.01)
        assert (home / 'visual').read_text().strip() == str(imported)
        saved = config.read_bytes()  # Refresh: 'set animation on' above changed it.
        broken = home / 'bad.gif'
        broken.write_bytes(b'invalid')
        cli('set', 'animation', str(broken), ok=False)
        assert config.read_bytes() == saved
        assert imported.read_bytes() == raw
        large = home / 'large.png'
        Image.new('RGBA', (513, 1)).save(large)
        cli('set', 'animation', str(large), ok=False)
        assert config.read_bytes() == saved
        cli('set', 'animation', 'default')
        assert "HERDR_ALERT_ANIMATION=''" in config.read_text()
        cli('play')
        assert (home / 'visual').read_text().strip() == ''
        print('PASS: CLI import, persistent copy, preview/hook selection, failed import preservation, reset')


if __name__ == '__main__':
    check()
