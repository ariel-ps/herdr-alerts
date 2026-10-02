"""Run directly: python3 tests/test_plugin.py."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import tomllib
import base64
import errno
import pty
import select
import signal
import time

ROOT = Path(__file__).resolve().parents[1]


def check():
    # A relocated standalone plugin must work without the old toolkit or siblings.
    with tempfile.TemporaryDirectory(prefix='plugin user ') as temporary:
        home = Path(temporary)
        plugin = home / 'plugin copy'
        shutil.copytree(ROOT, plugin, ignore=shutil.ignore_patterns('.git', 'target', '__pycache__'))
        required = [
            'CHANGELOG.md', 'SECURITY.md',
            'hooks/on-pane-agent-status-changed-alert.zsh',
            'bin/alert8play', 'bin/herdr-sound',
            'libexec/herdr-play-sound', 'libexec/fetch-game-sounds.py',
            'libexec/fetch-redalert-sounds.py',
            'scripts/build/gen-alert-tables.py',
            'scripts/build/generate-8bit-alert.py',
            'scripts/dev/fetch-sprites.py',
            'scripts/dev/fetch-redalert-sprites.py',
            'data/packs.json', 'generated/alerts.zsh',
            'assets/audio/8bit-alert.wav',
            'vendor/sprite/sprite.pl', 'vendor/sprite/ORIGIN.md',
        ]
        assert all((plugin / path).exists() for path in required)
        assert os.access(plugin / 'hooks/on-pane-agent-status-changed-alert.zsh', os.X_OK)
        assert os.access(plugin / 'bin/alert8play', os.X_OK)
        assert os.access(plugin / 'bin/herdr-sound', os.X_OK)
        generated = plugin / 'generated/alerts.zsh'
        assert generated.read_text().startswith('# GENERATED')
        assert 'DO NOT EDIT' in generated.read_text().splitlines()[0]
        committed_generated = generated.read_bytes()
        manifest = tomllib.loads((plugin / 'herdr-plugin.toml').read_text())
        assert manifest['id'] == 'dev.ariel.herdr-alerts'
        assert manifest['build'] == [
            {'command': ['sh', './scripts/build/install.sh']},
            {'command': ['sh', './scripts/build/generate-alert-tables.sh']}]
        assert manifest['events'] == [{
            'on': 'pane.agent_status_changed',
            'command': ['zsh', './hooks/on-pane-agent-status-changed-alert.zsh'],
        }]
        assert manifest['actions'] == [
            {'id': 'alerts', 'title': 'List the named alerts',
             'command': ['./bin/herdr-sound', 'list']},
            {'id': 'play', 'title': 'Preview alert sound',
             'command': ['./bin/herdr-sound', 'play'],
             'contexts': ['pane', 'workspace']},
        ]

        result = subprocess.run(
            ['python3', str(plugin / 'scripts/build/gen-alert-tables.py')],
            cwd=home, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert generated.read_bytes() == committed_generated

        build_tools = home / 'build tools'
        build_tools.mkdir()
        (build_tools / 'sh').symlink_to('/bin/sh')
        (build_tools / 'python3').symlink_to(sys.executable)
        (build_tools / 'dirname').symlink_to(shutil.which('dirname'))
        generated.write_text('# stale generated table\n')
        result = subprocess.run(
            manifest['build'][1]['command'], cwd=plugin,
            env={**os.environ, 'PATH': str(build_tools)},
            text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert generated.read_bytes() == committed_generated

        result = subprocess.run(
            ['zsh', '-fc', 'plugin=$1; source "$plugin/shell.zsh"; zsh "$plugin/hooks/on-pane-agent-status-changed-alert.zsh" --list', 'check', str(plugin)],
            env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                 'XDG_CACHE_HOME': str(home / 'cache')}, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert 'tesla' in result.stdout

        # Exercise the installed command without sending sound to the host device.
        recorded = home / 'playback'
        audio = home / 'audio-tools'
        audio.mkdir()
        for player in ['afplay', 'ffplay']:
            stub = audio / player
            stub.write_text('''#!/bin/sh
volume=1.0 duration=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -v) volume=$2; shift 2 ;;
    -af) volume=${2#volume=}; shift 2 ;;
    -t) duration=$2; shift 2 ;;
    -i) sound=$2; shift 2 ;;
    -*) shift ;;
    *) sound=$1; shift ;;
  esac
done
printf '%s\\n' "$sound" "$volume" "$duration" > "$PLAYBACK_LOG"
exit "${PLAYBACK_EXIT:-0}"
''')
            stub.chmod(0o755)
        config = home / 'config/herdr/plugins/config/dev.ariel.herdr-alerts'
        config.mkdir(parents=True)
        initial_config = '# Keep this comment\nCUSTOM_SETTING=preserved\nHERDR_VOLUME_DONE=0.4\nHERDR_ALERT_MAX_SECONDS=0.5\nHERDR_ALERT_OFF=1\n'
        (config / 'config.sh').write_text(initial_config)
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
               'XDG_CACHE_HOME': str(home / 'cache'), 'PLAYBACK_LOG': str(recorded),
               'HERDR_PLUGIN_CONFIG_DIR': '', 'HERDR_PLUGIN_ROOT': '',
               'PATH': str(audio) + ':' + os.environ['PATH']}
        for shell, integration in [('bash', 'shell.bash'), ('zsh', 'shell.zsh')]:
            def invoke(*args, extra_env=None, command='alert8play'):
                return subprocess.run(
                    [shell, '-fc', 'source "$1/$2"; shift 2; "$@"',
                     'check', str(plugin), integration, command, *args],
                    env={**env, **(extra_env or {})}, text=True, capture_output=True)

            result = invoke()
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == 'Playing included tone...', result.stdout
            assert recorded.read_text().splitlines() == [
                str(plugin.resolve() / 'assets/audio/8bit-alert.wav'), '0.4', '0.5'], recorded.read_text()
            recorded.unlink()
            for args, status in [(('--list',), 0), (('--help',), 0), (('--bad',), 2),
                                 (('one', 'two'), 2), (('unknown-alert',), 1), (('tesla',), 1)]:
                result = invoke(*args)
                assert result.returncode == status, (args, result.stderr)
                assert not recorded.exists(), args
                if args == ('--list',):
                    assert 'tesla' in result.stdout
            clip = home / 'cache/herdr-kit/sounds/mario/1up.wav'
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.touch()
            result = invoke('1up')
            assert result.returncode == 0, result.stderr
            assert recorded.read_text().splitlines()[0] == str(clip)
            assert invoke(extra_env={'PLAYBACK_EXIT': '7'}).returncode == 7
            recorded.unlink()

            result = invoke('list', command='herdr-sound')
            assert result.returncode == 0, result.stderr
            rows = {line.split()[0]: line.split()[2] for line in result.stdout.split('\n\n')[0].splitlines()[1:]}
            assert rows['1up'] == 'ready' and rows['tesla'] == 'missing', rows
            assert 'herdr-sound download PACK' in result.stdout
            for command in ['', 'play', 'list', 'download', 'set', 'enable', 'disable', 'status']:
                result = invoke(*([command] if command else []), '--help', command='herdr-sound')
                assert result.returncode == 0 and 'usage:' in result.stdout.lower(), result.stderr
            for args in [('set', 'done', '1up'), ('enable',), ('disable',), ('on',), ('off',)]:
                result = invoke(*args, command='herdr-sound')
                assert result.returncode == 0, result.stderr
                assert (config / 'config.sh').read_text().startswith(initial_config)
                if args in [('enable',), ('on',)]:
                    result = invoke('status', command='herdr-sound')
                    assert 'Automatic alerts   enabled' in result.stdout, result.stderr
                    assert 'done       0.4      1up (ready)' in result.stdout, result.stdout
                    assert '0.5 seconds' in result.stdout, result.stdout
            settings = (config / 'config.sh').read_text()
            assert settings.count('# >>> herdr-sound >>>') == 1
            assert "HERDR_SOUND_DONE=''" in settings
            assert list(config.glob('config.sh.*.bak'))
            assert invoke('off', command='herdr-sound').returncode == 0
            assert (config / 'config.sh').read_text() == settings
            for args in [('set', 'working', '1up'), ('set', 'done', '$(touch unexpected)'),
                         ('set', 'done', '_comment'), ('play', 'one', 'two')]:
                assert invoke(*args, command='herdr-sound').returncode == 2
                assert (config / 'config.sh').read_text() == settings
            assert not (home / 'unexpected').exists()
            assert invoke('play', command='herdr-sound').returncode == 0
            recorded.unlink()

        # Settings follow symlinks, preserve permissions, and back up the target.
        actual_config = home / 'actual settings.sh'
        (config / 'config.sh').rename(actual_config)
        actual_config.chmod(0o640)
        (config / 'config.sh').symlink_to(actual_config)
        assert invoke('on', command='herdr-sound').returncode == 0
        assert (config / 'config.sh').is_symlink()
        assert actual_config.stat().st_mode & 0o777 == 0o640
        backups = list(home.glob('actual settings.sh.*.bak'))
        assert backups and all(path.stat().st_mode & 0o777 == 0o600 for path in backups)

        # Download dispatch and the old sync name share the same implementation.
        tools = home / 'tools'
        tools.mkdir()
        uv = tools / 'uv'
        uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$SYNC_LOG"\nexit "${SYNC_EXIT:-0}"\n')
        uv.chmod(0o755)
        sync_log = home / 'sync-log'
        sync_env = {'PATH': str(tools) + ':' + os.environ['PATH'], 'SYNC_LOG': str(sync_log)}
        result = invoke('download', 'mario', extra_env=sync_env, command='herdr-sound')
        assert result.returncode == 0, result.stderr
        assert 'fetch-game-sounds.py' in sync_log.read_text()
        assert str(home / 'cache/herdr-kit/sounds/mario') in sync_log.read_text()
        assert 'Downloading mario...' in result.stderr
        sync_log.unlink()
        assert invoke('mario', extra_env=sync_env, command='herdr-sounds-sync').returncode == 0
        assert 'fetch-game-sounds.py' in sync_log.read_text()
        sync_log.unlink()
        assert invoke('sync', '../invalid', extra_env=sync_env, command='herdr-sound').returncode == 2
        assert not sync_log.exists()
        assert invoke('sync', 'mario', extra_env={**sync_env, 'SYNC_EXIT': '7'}, command='herdr-sound').returncode == 1
        sync_log.unlink()
        assert invoke('sync', extra_env=sync_env, command='herdr-sound').returncode == 0
        packs = json.loads((plugin / 'data/packs.json').read_text())['games']
        assert sync_log.read_text().splitlines().count('run') == sum(
            isinstance(spec, dict) and bool(spec.get('sounds')) for spec in packs.values())
        assert 'pycryptodome' in sync_log.read_text()

        # Refuse malformed managed settings without changing the user's file.
        malformed = initial_config + '# >>> herdr-sound >>>\n'
        (config / 'config.sh').write_text(malformed)
        result = invoke('on', command='herdr-sound')
        assert result.returncode == 1 and 'Malformed' in result.stderr, result.stderr
        assert (config / 'config.sh').read_text() == malformed
        (config / 'config.sh').write_text(initial_config)
        # Muting still suppresses automatic events.
        result = subprocess.run(['zsh', str(plugin / 'hooks/on-pane-agent-status-changed-alert.zsh')],
                                env={**env, 'HERDR_PLUGIN_EVENT_JSON': '{"agent_status":"done"}'},
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert not recorded.exists()

        # Verify bash forwards literal arguments, cwd, and failures to the implementation.
        commands = ["herdr-sounds-sync"]
        (plugin / 'bin/herdr-sound').write_text(
            '#!/bin/sh\nprintf "%s\\n" "$PWD" "${HERDR_AGENT_ARGS:-}" "$@"; exit 7\n')
        arguments = ['two words', '$(touch unexpected)', '', '--option']
        for command in commands:
            result = subprocess.run(
                ['bash', '--noprofile', '--norc', '-c',
                 'source "$1/shell.bash"; shift; HERDR_AGENT_ARGS="two flags"; "$@"',
                 'check', str(plugin), command, *arguments], cwd=home,
                env={**os.environ, 'HOME': str(home)}, text=True, capture_output=True)
            assert result.returncode == 7, result.stderr
            assert result.stdout.splitlines() == [str(home.resolve()), os.environ.get('HERDR_AGENT_ARGS', ''), 'download', *arguments], result.stdout
        assert not (home / 'unexpected').exists()


def check_player_errors():
    with tempfile.TemporaryDirectory(prefix='audio test ') as temporary:
        root = Path(temporary)
        ffplay = root / 'ffplay'
        ffplay.write_text('#!/bin/sh\nprintf "%s" "${PLAYER_ERROR:-}" >&2\nexit "${PLAYER_EXIT:-0}"\n')
        ffplay.chmod(0o755)
        env = {**os.environ, 'PATH': str(root)}
        for error, code, expected in [('', '0', 0), ('audio open failed\n', '0', 1), ('device failure\n', '7', 7)]:
            result = subprocess.run([str(ROOT / 'libexec/herdr-sound'), 'play-file',
                                     str(ROOT / 'assets/audio/8bit-alert.wav'), '0.4', '0.5'],
                                    env={**env, 'PLAYER_ERROR': error, 'PLAYER_EXIT': code}, text=True, capture_output=True)
            assert result.returncode == expected, result.stderr
            if expected:
                assert error in result.stderr and 'playback failed' in result.stderr


def check_flashes():
    # Pane IDs are validated before a detached flash helper is launched.
    with tempfile.TemporaryDirectory(prefix='flash-', dir='/tmp') as temporary:
        home = Path(temporary)
        config = home / 'herdr'
        config.mkdir()
        (config / 'config.sh').write_text('HERDR_ALERT_OFF=1\nHERDR_ALERT_FLASH=0\n')
        audio = home / 'afplay'
        audio.write_text('#!/bin/sh\nexit "${PLAYBACK_EXIT:-0}"\n')
        audio.chmod(0o755)
        env = {**os.environ, 'HOME': temporary, 'XDG_CONFIG_HOME': temporary,
               'HERDR_PLUGIN_CONFIG_DIR': str(config), 'HERDR_PLUGIN_ROOT': str(ROOT),
               'HERDR_PANE_ID': 'wN:p3', 'PATH': temporary + ':' + os.environ['PATH']}
        binary = str(ROOT / 'libexec/herdr-sound')
        for pane in ['bad"pane', 'wN:p3\n', '../pane']:
            result = subprocess.run([binary, 'play', '--flash'], env={**env, 'HERDR_PANE_ID': pane},
                                    text=True, capture_output=True)
            assert result.returncode == 1 and 'invalid HERDR_PANE_ID' in result.stderr
            result = subprocess.run(['zsh', str(ROOT / 'libexec/herdr-flash'), pane, 'done'],
                                    env=env, text=True, capture_output=True)
            assert result.returncode == 2 and 'valid pane ID' in result.stderr
        for args in [['play', '--flash', '--flash'], ['--alert8play', '--list', '--flash']]:
            result = subprocess.run([binary, *args], env=env, text=True, capture_output=True)
            assert result.returncode == 2, result.stderr


def check_terminal_flashes():
    # Exercise both background and pane-image flashes in a real controlling PTY.
    with tempfile.TemporaryDirectory(prefix='terminal-flash-', dir='/tmp') as temporary:
        home = Path(temporary)
        herdr = home / 'herdr-stub'
        herdr.mkdir()
        (herdr / 'herdr').write_text('''#!/bin/sh
test "$*" = 'pane process-info --pane wN:p3' || exit 2
printf '{"result":{"process_info":{"shell_pid":%s}}}\\n' "$FLASH_SHELL_PID"
''')
        (herdr / 'stty').write_text("#!/bin/sh\nprintf '24 80\\n'\n")
        for stub in herdr.iterdir():
            stub.chmod(0o755)
        player = home / 'afplay'
        player.write_text('#!/bin/sh\nexit "${PLAYBACK_EXIT:-0}"\n')
        player.chmod(0o755)
        env = {**os.environ, 'HOME': temporary, 'XDG_CONFIG_HOME': temporary,
               'HERDR_PLUGIN_CONFIG_DIR': '', 'HERDR_PLUGIN_ROOT': str(ROOT),
               'HERDR_PANE_ID': '', 'PATH': str(herdr) + ':' + temporary + ':' + os.environ['PATH']}
        for shell, command, term, audio_exit, pane in [
            ('bash', 'alert8play', 'xterm-256color', '0', ''),
            ('zsh', 'herdr-sound', 'xterm-256color', '7', ''),
            ('bash', 'alert8play', 'dumb', '0', ''),
            ('bash', 'alert8play', 'xterm-256color', '0', 'wN:p3'),
        ]:
            log = home / 'output.log'
            pid, terminal = pty.fork()
            if pid == 0:
                with log.open('w') as output:
                    os.dup2(output.fileno(), 1)
                args = [str(ROOT / 'bin' / command)]
                if command == 'herdr-sound':
                    args.append('play')
                args.append('--flash')
                os.execvpe(shell, [shell, '-fc', '"$@"', 'check', *args],
                           {**env, 'TERM': term, 'PLAYBACK_EXIT': audio_exit,
                            'HERDR_PANE_ID': pane, 'FLASH_SHELL_PID': str(os.getpid())})
            captured = b''
            reaped = False
            deadline = time.monotonic() + 10
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and select.select([terminal], [], [], remaining)[0], 'flash timed out'
                    try:
                        data = os.read(terminal, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not data:
                        break
                    captured += data
                _, status = os.waitpid(pid, 0)
                reaped = True
            finally:
                os.close(terminal)
                if not reaped:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == int(audio_exit), captured
            assert '\033' not in log.read_text(), log.read_text()
            assert 'Playing included tone' in log.read_text()
            if pane:
                assert captured.count(b'\x1b_Ga=T') == 4, captured
                assert captured.count(b'\x1b_Ga=d,d=I') == 5, captured
                encoded_green = base64.b64encode(bytes([0, 204, 68, 255]) * 64)
                assert captured.count(b';' + encoded_green + b'\x1b\\') == 4, captured
            else:
                assert captured.count(b'\x1b]11;#00cc44\x1b\\') == 4, captured
                assert captured.count(b'\x1b]111\x1b\\') == 5, captured
        result = subprocess.run([str(ROOT / 'bin/alert8play'), '--flash'],
                                env={**env, 'TERM': 'xterm-256color'}, start_new_session=True,
                                text=True, capture_output=True)
        assert result.returncode == 1 and 'interactive terminal' in result.stderr, result.stderr
        assert '\033' not in result.stdout + result.stderr


if __name__ == '__main__':
    subprocess.run(['sh', str(ROOT / 'scripts/build/install.sh')], check=True)
    check()
    check_player_errors()
    check_flashes()
    check_terminal_flashes()
