#!/usr/bin/env zsh
# herdr event hook: flash the pane, play the alert, draw the sprite that goes
# with it.
#
# herdr's own [ui.sound] plays one mp3 and draws nothing. This pairs each sound
# with a flash on the pane that wants attention, and a sprite on the one event
# that needs a human.
#
# The shared flash helper targets the event's pane through Herdr graphics,
# so one pane lights up rather than the whole terminal window.
#
# The clip is not hardcoded. data/packs.json names a set of alerts — a game,
# which clip inside it, and the sprite that belongs with that clip — and
# scripts/build/gen-alert-tables.py turns that into the case table sourced
# below, so
# the pairing is written once in the file that also says where the media comes
# from. Nothing here parses JSON: this runs once per status change on every
# pane, and it already pays two `jq` execs to read the event.
#
# Every step of the picker degrades on its own. No table, no synced pack, or a
# clip that is not in it, and the bundled pair plays with no sprite — an alert
# that fires plainly beats one that does not fire.
#
# Env in: HERDR_PLUGIN_EVENT_JSON ({event, data: {pane_id, agent_status}}).
#   HERDR_ALERT_OFF=1           silence entirely
#   HERDR_ALERT_FLASH=0         no flash; sprites are controlled separately
#   HERDR_ALERT_SPRITE=0        no sprite on blocked
#   HERDR_ALERT_BLOCKED=<name>  which named alert `blocked` plays
#   HERDR_ALERT_DONE=<name>     ...and which one `done` plays
#   HERDR_SOUND_BLOCKED=<path>  a literal file, which beats the name
#   HERDR_SOUND_DONE=<path>
#   HERDR_VOLUME_BLOCKED / HERDR_VOLUME_DONE    afplay -v
#   HERDR_ALERT_MAX_SECONDS     cap a clip, default 3, empty plays it in full
#   SPRITE_NAME=<name>          override the sprite the alert chose
#
# Manual previews use the same saved flash setting:
#   herdr-sound list
#   herdr-sound set flash on
#   herdr-sound play tesla

emulate -L zsh
setopt pipefail extendedglob

# HERDR_PLUGIN_ROOT is set by herdr; the ${0:A:h:h} fallback keeps the hook
# runnable by hand, which is how it gets tested.
root="${HERDR_PLUGIN_ROOT:-${0:A:h:h}}"

# Sounds are overridable so a user can bring their own without editing the
# plugin. Anything unreadable falls through to the bundled pair.
config="${HERDR_PLUGIN_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/herdr/plugins/config/dev.ariel.herdr-alerts}"
[[ -r "$config/config.sh" ]] || config=$root
[[ -r "$config/config.sh" ]] && source "$config/config.sh"

# Generated, and absent on a checkout that never ran the build step — hence the
# `typeset -f` guards below rather than a hard require.
[[ -r "$root/generated/alerts.zsh" ]] && source "$root/generated/alerts.zsh"

# Same tree the fetchers write into: sounds/<game>/, sprites/<game>/.
cache="${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit"

# Resolve an alert name to a clip on disk plus the sprite that belongs with it.
# Sets `sound`, `sprite_game`, `sprite_name`; returns 1 without touching `sound`
# when it cannot, so the caller keeps whatever fallback it already had.
#
# It degrades one step at a time and never across games: "I picked the Mario win
# sound" quietly becoming a random Kirby music track is a worse answer than the
# beep the kit ships with.
__herdr_alert_resolve() {
  local name="${1:-}"
  local alert_game alert_clip alert_sprite
  local dir
  local -a hit
  sprite_game= sprite_name=

  typeset -f __herdr_alert_spec >/dev/null 2>&1 || return 1
  __herdr_alert_spec "$name" || return 1
  sprite_game="$alert_game" sprite_name="$alert_sprite"

  dir="$cache/sounds/$alert_game"
  # The clip name is quoted and the extension group is not: basenames carry
  # spaces and parentheses ("coin (nes)"), which must stay literal.
  [[ -n "$alert_clip" ]] && hit=("$dir/$alert_clip".(wav|mp3|ogg)(N.))
  (( $#hit )) || hit=("$dir"/*.(wav|mp3|ogg)(N.))
  (( $#hit )) || return 1
  sound="${hit[RANDOM % $#hit + 1]}"
  return 0
}

# All manual sound commands share the Rust CLI.
case "${1:-}" in
  --list|--status) exec "$root/bin/herdr-sound" "${1#--}" ;;
  --play) shift; exec "$root/bin/herdr-sound" play "$@" ;;
esac

# Muting automatic alerts still allows explicit previews and listing sounds.
[[ "${HERDR_ALERT_OFF:-}" == 1 ]] && exit 0

command -v jq >/dev/null 2>&1 || exit 0

# Herdr wraps event fields in data; accept flat payloads for manual callers too.
state=$(print -r -- "${HERDR_PLUGIN_EVENT_JSON:-}" | jq -r '(.data // .) | .agent_status // .status // empty' 2>/dev/null)
pane=$(print -r -- "${HERDR_PLUGIN_EVENT_JSON:-}" | jq -r '(.data // .) | .pane_id // empty' 2>/dev/null)

# Only the two transitions worth interrupting someone for. `working` and `idle`
# fire constantly and would turn the alert into noise nobody reacts to.
case "$state" in
  blocked) name="${HERDR_ALERT_BLOCKED:-}"; override="${HERDR_SOUND_BLOCKED:-}"
           sound="$root/assets/audio/8bit-alert.wav"; vol="${HERDR_VOLUME_BLOCKED:-1.8}" ;;
  done)    name="${HERDR_ALERT_DONE:-}";    override="${HERDR_SOUND_DONE:-}"
           sound="$root/assets/audio/8bit-alert.wav"; vol="${HERDR_VOLUME_DONE:-1.0}" ;;
  *)       exit 0 ;;
esac

# A literal path is the user saying exactly what to play, so it outranks a name;
# a name outranks the bundled clip; the bundled clip is always there.
if [[ -n "$override" && -r "$override" ]]; then
  sound="$override"
else
  [[ -n "$name" ]] || { typeset -f __herdr_alert_for_state >/dev/null 2>&1 \
    && name=$(__herdr_alert_for_state "$state") }
  __herdr_alert_resolve "$name"
fi

# Flash first so the light and the sound land together rather than in sequence.
if [[ -n "$pane" && "$pane" != *[^a-zA-Z0-9_:-]* ]]; then
  SPRITE_FILE="${HERDR_ALERT_ANIMATION:-}" SPRITE_NAME="${SPRITE_NAME:-}" zsh "$root/libexec/herdr-visuals" "$pane" "$state" "$name" \
    "${HERDR_ALERT_FLASH:-1}" "${HERDR_ALERT_SPRITE:-1}" &!
fi

[[ -r "$sound" ]] && sh "$root/libexec/herdr-play-sound" "$sound" "$vol" "${HERDR_ALERT_MAX_SECONDS:-}" &!

exit 0
