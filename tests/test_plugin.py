"""Run directly: python3 tests/test_plugin.py."""
import os
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
        (config / 'config.sh').write_text(
            'HERDR_VOLUME_DONE=0.4\nHERDR_ALERT_MAX_SECONDS=0.5\nHERDR_ALERT_OFF=1\n')
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
               'XDG_CACHE_HOME': str(home / 'cache'), 'PLAYBACK_LOG': str(recorded),
               'HERDR_PLUGIN_CONFIG_DIR': '', 'HERDR_PLUGIN_ROOT': ''}
        for shell, integration in [('bash', 'shell.bash'), ('zsh', 'shell.zsh')]:
            def invoke(*args, extra_env=None):
                return subprocess.run(
                    [shell, '-fc', 'source "$1/$2"; shift 2; alert8play "$@"',
                     'check', str(plugin), integration, *args],
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


if __name__ == '__main__':
    check()
