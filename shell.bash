# Bash entry points reuse the plugin's zsh implementation.
_HERDR_ALERTS_ROOT=${HERDR_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}
export PATH="$_HERDR_ALERTS_ROOT/bin:$PATH"

herdr-sounds-sync() {
  zsh -fc 'source "$1/shell.zsh"; shift; herdr-sounds-sync "$@"' herdr-sounds-sync "$_HERDR_ALERTS_ROOT" "$@"
}
