"""Run directly: python3 tests/test_plugin.py."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check():
    # A relocated standalone plugin must work without the old toolkit or siblings.
    with tempfile.TemporaryDirectory(prefix='plugin user ') as temporary:
        home = Path(temporary)
        plugin = home / 'plugin copy'
        shutil.copytree(ROOT, plugin, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        result = subprocess.run(
            ['zsh', '-fc', 'plugin=$1; source "$plugin/shell.zsh"; zsh "$plugin/alert-hook.sh" --list', 'check', str(plugin)],
            env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                 'XDG_CACHE_HOME': str(home / 'cache')}, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert 'tesla' in result.stdout

        # Exercise the installed command without sending sound to the host device.
        recorded = home / 'playback'
        (plugin / 'bin/herdr-play-sound').write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$PLAYBACK_LOG"\nexit "${PLAYBACK_EXIT:-0}"\n')
        config = home / 'config/herdr/plugins/config/dev.ariel.herdr-alerts'
        config.mkdir(parents=True)
        initial_config = '# Keep this comment\nCUSTOM_SETTING=preserved\nHERDR_VOLUME_DONE=0.4\nHERDR_ALERT_MAX_SECONDS=0.5\nHERDR_ALERT_OFF=1\n'
        (config / 'config.sh').write_text(initial_config)
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
               'XDG_CACHE_HOME': str(home / 'cache'), 'PLAYBACK_LOG': str(recorded),
               'HERDR_PLUGIN_CONFIG_DIR': '', 'HERDR_PLUGIN_ROOT': ''}
        for shell, integration in [('bash', 'shell.bash'), ('zsh', 'shell.zsh')]:
            def invoke(*args, extra_env=None, command='alert8play'):
                return subprocess.run(
                    [shell, '-fc', 'source "$1/$2"; shift 2; "$@"',
                     'check', str(plugin), integration, command, *args],
                    env={**env, **(extra_env or {})}, text=True, capture_output=True)

            result = invoke()
            assert result.returncode == 0, result.stderr
            assert recorded.read_text().splitlines() == [
                str(plugin.resolve() / 'sounds/8bit-alert.wav'), '0.4', '0.5']
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
            rows = {line.split()[0]: line.split()[2] for line in result.stdout.splitlines()[1:]}
            assert rows['1up'] == 'ready' and rows['tesla'] == 'missing', rows
            for args in [('set', 'done', '1up'), ('on',), ('off',)]:
                result = invoke(*args, command='herdr-sound')
                assert result.returncode == 0, result.stderr
                assert (config / 'config.sh').read_text().startswith(initial_config)
                if args == ('on',):
                    result = invoke('status', command='herdr-sound')
                    assert 'Automatic alerts: on' in result.stdout, result.stderr
                    assert 'done: 1up (ready)' in result.stdout, result.stdout
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

        # Download dispatch and the old sync name share the same implementation.
        tools = home / 'tools'
        tools.mkdir()
        uv = tools / 'uv'
        uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$SYNC_LOG"\nexit "${SYNC_EXIT:-0}"\n')
        uv.chmod(0o755)
        sync_log = home / 'sync-log'
        sync_env = {'PATH': str(tools) + ':' + os.environ['PATH'], 'SYNC_LOG': str(sync_log)}
        result = invoke('sync', 'mario', extra_env=sync_env, command='herdr-sound')
        assert result.returncode == 0, result.stderr
        assert 'fetch-game-sounds.py' in sync_log.read_text()
        assert str(home / 'cache/herdr-kit/sounds/mario') in sync_log.read_text()
        sync_log.unlink()
        assert invoke('mario', extra_env=sync_env, command='herdr-sounds-sync').returncode == 0
        assert 'fetch-game-sounds.py' in sync_log.read_text()
        sync_log.unlink()
        assert invoke('sync', '../invalid', extra_env=sync_env, command='herdr-sound').returncode == 2
        assert not sync_log.exists()
        assert invoke('sync', 'mario', extra_env={**sync_env, 'SYNC_EXIT': '7'}, command='herdr-sound').returncode == 1
        sync_log.unlink()
        assert invoke('sync', extra_env=sync_env, command='herdr-sound').returncode == 0
        packs = json.loads((plugin / 'sounds/packs.json').read_text())['games']
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
        result = subprocess.run(['zsh', str(plugin / 'alert-hook.sh')],
                                env={**env, 'HERDR_PLUGIN_EVENT_JSON': '{"agent_status":"done"}'},
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert not recorded.exists()

        # Verify bash forwards literal arguments, cwd, and failures to the implementation.
        commands = ["herdr-sounds-sync"]
        (plugin / 'shell.zsh').write_text('\n'.join(
            name + '() { printf "%s\\n" "$PWD" "${HERDR_AGENT_ARGS:-}" "$@"; return 7; }'
            for name in commands))
        arguments = ['two words', '$(touch unexpected)', '', '--option']
        for command in commands:
            result = subprocess.run(
                ['bash', '--noprofile', '--norc', '-c',
                 'source "$1/shell.bash"; shift; HERDR_AGENT_ARGS="two flags"; "$@"',
                 'check', str(plugin), command, *arguments], cwd=home,
                env={**os.environ, 'HOME': str(home)}, text=True, capture_output=True)
            assert result.returncode == 7, result.stderr
            assert result.stdout.splitlines() == [str(home.resolve()), os.environ.get('HERDR_AGENT_ARGS', ''), *arguments], result.stdout
        assert not (home / 'unexpected').exists()


def check_player_errors():
    with tempfile.TemporaryDirectory(prefix='audio test ') as temporary:
        root = Path(temporary)
        for name in ['mktemp', 'rm', 'cat']:
            (root / name).symlink_to(shutil.which(name))
        ffplay = root / 'ffplay'
        ffplay.write_text('#!/bin/sh\nprintf "%s" "${PLAYER_ERROR:-}" >&2\nexit "${PLAYER_EXIT:-0}"\n')
        ffplay.chmod(0o755)
        env = {**os.environ, 'PATH': str(root)}
        for error, code, expected in [('', '0', 0), ('audio open failed\n', '0', 1), ('device failure\n', '7', 7)]:
            result = subprocess.run(['/bin/sh', str(ROOT / 'bin/herdr-play-sound'),
                                     str(ROOT / 'sounds/8bit-alert.wav'), '0.4', '0.5'],
                                    env={**env, 'PLAYER_ERROR': error, 'PLAYER_EXIT': code}, text=True, capture_output=True)
            assert result.returncode == expected, result.stderr
            if expected:
                assert error in result.stderr and 'playback failed' in result.stderr


if __name__ == '__main__':
    check()
    check_player_errors()
