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

        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                  stdin=slave, stdout=slave, stderr=slave, preexec_fn=attach)
        try:
            herdr = tools / 'herdr'
            response = json.dumps({'result': {'process_info': {'shell_pid': holder.pid}}})
            herdr.write_text("#!/bin/sh\nprintf '%s\\n' '" + response + "'\n")
            herdr.chmod(0o755)
            kitty = tools / 'kitty'
            kitty.write_text('''#!/bin/sh
printf '%s\\n' '[{"is_focused":false,"tabs":[{"is_active":true,"windows":[{"id":123,"is_focused":true}]}]}]'
''')
            kitty.chmod(0o755)
            env = {**os.environ, 'HERDR_PLUGIN_ROOT': str(plugin),
                   'HERDR_PLUGIN_CONFIG_DIR': temporary, 'KITTY_WINDOW_ID': '123',
                   'SPRITE_TTL': '2', 'SPRITE_LOOP_GAP': '0',
                   'XDG_CACHE_HOME': str(home / 'cache'), 'HERDR_BIN_PATH': str(herdr),
                   'PATH': str(tools) + ':' + os.environ['PATH']}
            env.pop('SPRITE_PERSIST', None)
            data = {'type': 'pane_agent_status_changed', 'pane_id': 'w1:p1',
                    'workspace_id': 'w1', 'agent_status': 'blocked', 'agent': 'codex'}
            # Real Herdr events wrap fields in data; old manual callers pass them directly.
            for event in ({'event': 'pane_agent_status_changed', 'data': data}, data):
                env['HERDR_PLUGIN_EVENT_JSON'] = json.dumps(event)
                for flash in (0, 1):
                    (home / 'config.sh').write_text(
                        f'HERDR_ALERT_OFF=0\nHERDR_ALERT_FLASH={flash}\nHERDR_ALERT_SPRITE=1\n')
                    subprocess.run(['zsh', str(plugin / 'hooks/on-pane-agent-status-changed-alert.zsh')],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   check=True, timeout=5)
                    output = b''
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], .05)[0]:
                            output += os.read(master, 65536)
                            ids = re.findall(rb'\x1b_Ga=T,[^;]*z=1,i=(\d+)', output)
                            if ids and b'\x1b_Ga=d,d=I,i=' + ids[0] + b',' in output:
                                break
                    frames = re.findall(rb'\x1b_Ga=T,[^;]*z=1,[^;]*;([^\x1b]+)', output)
                    assert len(set(frames)) > 1, f'No animation: envelope={"data" in event}, flash={flash}'
                    assert len(frames) == 14, 'Unfocused sprite repeated instead of clearing after one animation'
                    assert b'\x1b_Ga=d,d=I,i=' + ids[0] + b',' in output, 'Sprite not cleared'
                    print(f'PASS: animated sprite; envelope={"data" in event}, flash={flash}')
        finally:
            holder.terminate()
            holder.communicate(timeout=5)
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    check()
