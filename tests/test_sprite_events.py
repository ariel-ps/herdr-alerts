"""Replay Herdr events through the real hook and renderer in an isolated PTY."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]


def check():
    with tempfile.TemporaryDirectory(prefix='sprite event ') as temporary:
        home = Path(temporary)
        plugin = home / 'plugin'
        for name in ('hooks/on-pane-agent-status-changed-alert.zsh',
                     'libexec/herdr-flash', 'libexec/herdr-visuals', 'vendor/sprite/sprite.pl'):
            target = plugin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        (plugin / 'libexec/herdr-play-sound').write_text('exit 0\n')
        (plugin / 'assets/audio').mkdir(parents=True)
        (plugin / 'assets/audio/8bit-alert.wav').touch()
        tools = home / 'tools'
        tools.mkdir()
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))

        def attach():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'],
                                  stdin=slave, stdout=slave, stderr=slave, preexec_fn=attach)
        try:
            herdr = tools / 'herdr'
            response = json.dumps({'result': {'process_info': {'shell_pid': holder.pid}}})
            focus = home / 'focus.json'
            def set_focus(focused):
                temporary_focus = focus.with_suffix('.tmp')
                temporary_focus.write_text(json.dumps({'result': {'pane': {'focused': focused}}}))
                temporary_focus.replace(focus)
            herdr.write_text("#!/bin/sh\nif [ \"$2\" = get ]; then cat \"$FOCUS_FILE\"; else printf '%s\\n' '" + response + "'; fi\n")
            herdr.chmod(0o755)
            env = {**os.environ, 'HERDR_PLUGIN_ROOT': str(plugin),
                   'HERDR_PLUGIN_CONFIG_DIR': temporary, 'FOCUS_FILE': str(focus),
                   'SPRITE_TTL': '8', 'SPRITE_LOOP_GAP': '0',
                   'XDG_CACHE_HOME': str(home / 'cache'), 'HERDR_BIN_PATH': str(herdr),
                   'PATH': str(tools) + ':' + os.environ['PATH']}
            env.pop('SPRITE_PERSIST', None)
            env.pop('KITTY_WINDOW_ID', None)
            data = {'type': 'pane_agent_status_changed', 'pane_id': 'w1:p1',
                    'workspace_id': 'w1', 'agent_status': 'blocked', 'agent': 'codex'}
            # Real Herdr events wrap fields in data; old manual callers pass them directly.
            for event in ({'event': 'pane_agent_status_changed', 'data': data}, data):
                env['HERDR_PLUGIN_EVENT_JSON'] = json.dumps(event)
                for flash in (0, 1):
                    set_focus(False)
                    (home / 'config.sh').write_text(
                        f'HERDR_ALERT_OFF=0\nHERDR_ALERT_FLASH={flash}\nHERDR_ALERT_SPRITE=1\n')
                    subprocess.run(['zsh', str(plugin / 'hooks/on-pane-agent-status-changed-alert.zsh')],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   check=True, timeout=5)
                    output = b''
                    focused = False
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], .05)[0]:
                            output += os.read(master, 65536)
                            ids = re.findall(rb'\x1b_Ga=T,[^;]*z=1,i=(\d+)', output)
                            if ids and b'\x1b_Ga=d,d=I,i=' + ids[0] + b',' in output:
                                assert focused, 'Automatic sprite disappeared before pane focus'
                                break
                            if len(ids) > 14 and not focused:
                                set_focus(True)
                                focused = True
                    frames = re.findall(rb'\x1b_Ga=T,[^;]*z=1,[^;]*;([^\x1b]+)', output)
                    assert len(set(frames)) > 1, f'No animation: envelope={"data" in event}, flash={flash}'
                    assert focused, 'Unfocused sprite did not keep animating'
                    assert b'\x1b_Ga=d,d=I,i=' + ids[0] + b',' in output, 'Sprite not cleared'
                    print(f'PASS: sprite persists until pane focus; envelope={"data" in event}, flash={flash}')
            # Previews and automatic alerts share the same rule: focused panes
            # play once; unfocused panes keep the sprite until focus returns.
            for state, initially_focused, switch_away in [
                ('preview', False, False), ('preview', True, False),
                ('blocked', True, False), ('preview', True, True),
            ]:
                set_focus(initially_focused)
                preview = subprocess.Popen(['zsh', str(plugin / 'libexec/herdr-visuals'),
                                            'w1:p1', state, '', '0', '1'], env=env)
                output = b''
                returned = False
                waits_for_return = not initially_focused or switch_away
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        output += os.read(master, 65536)
                        if b'\x1b_Ga=d,d=I,i=' in output:
                            assert not waits_for_return or returned, f'{state} disappeared before focus returned'
                            break
                        count = len(re.findall(rb'\x1b_Ga=T,', output))
                        if switch_away and count >= 2:
                            set_focus(False)
                            switch_away = False
                        assert waits_for_return or count <= 14, f'{state} repeated in an already-focused pane'
                        if waits_for_return and not returned and count > 14:
                            set_focus(True)
                            returned = True
                assert preview.wait(timeout=3) == 0
                assert b'\x1b_Ga=d,d=I,i=' in output, 'Focused sprite did not clear'
                if not waits_for_return:
                    assert len(re.findall(rb'\x1b_Ga=T,', output)) == 14
                else:
                    assert returned
                print(f'PASS: {state} clears while focused; initially focused={initially_focused}')
            # Callers can still explicitly request a single animation.
            set_focus(False)
            preview = subprocess.Popen(['zsh', str(plugin / 'libexec/herdr-visuals'),
                                        'w1:p1', 'preview', '', '0', '1'], env={**env, 'SPRITE_PERSIST': '0'})
            output = b''
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output += os.read(master, 65536)
                    if b'\x1b_Ga=d,d=I,i=' in output:
                        break
            assert preview.wait(timeout=3) == 0
            assert len(re.findall(rb'\x1b_Ga=T,', output)) == 14
            assert b'\x1b_Ga=d,d=I,i=' in output, 'Preview did not clear'
            print('PASS: explicit one-shot animation clears')
            # Real Mario packs have only two frames; they must remain visible
            # for a full animation interval before focused-pane cleanup.
            (home / 'short.rgba').write_bytes(
                struct.pack('<4H', 2, 1, 1, 0) + bytes([255, 0, 0, 255, 0, 0, 255, 255]))
            rendered = home / 'short-output'
            started = time.monotonic()
            subprocess.run(['perl', str(plugin / 'vendor/sprite/sprite.pl'), str(rendered), '80'],
                           env={**env, 'SPRITE_DIR': temporary, 'SPRITE_NAME': 'short',
                                'SPRITE_PERSIST': '0'}, check=True, timeout=5)
            assert time.monotonic() - started >= .8
            assert len(re.findall(rb'\x1b_Ga=T,', rendered.read_bytes())) == 16
            assert b'\x1b_Ga=d,d=I,i=' in rendered.read_bytes()
            print('PASS: short sprite packs remain visible for a full animation interval')
        finally:
            if 'focus' in locals():
                set_focus(True)
            holder.kill()
            holder.communicate(timeout=5)
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    check()
