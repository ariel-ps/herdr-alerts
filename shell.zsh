# Load the Rust sound CLI and its compatibility commands.
typeset -g _HERDR_ALERTS_ROOT="${HERDR_PLUGIN_ROOT:-${0:A:h}}"
typeset -U path
path=("$_HERDR_ALERTS_ROOT/bin" $path)
herdr-sounds-sync() { "$_HERDR_ALERTS_ROOT/bin/herdr-sound" download "$@"; }
