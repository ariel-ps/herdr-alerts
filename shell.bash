# Load the Rust sound CLI and its compatibility commands.
_HERDR_ALERTS_ROOT=${HERDR_PLUGIN_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}
export PATH="$_HERDR_ALERTS_ROOT/bin:$PATH"
herdr-sounds-sync() { "$_HERDR_ALERTS_ROOT/bin/herdr-sound" download "$@"; }
