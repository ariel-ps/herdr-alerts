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
