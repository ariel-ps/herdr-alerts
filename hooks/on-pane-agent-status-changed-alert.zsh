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
#   HERDR_SPRITE_BLOCKED=<game>:<sprite>  show a different alert's sprite
#   HERDR_SPRITE_DONE=<game>:<sprite>     instead of the sound alert's own
#   HERDR_SPRITE_BLOCKED=custom           show the imported custom animation
#   HERDR_SPRITE_DONE=custom              instead -- a category of sprite,
#                                         selected the same way as any other,
#                                         not a separate on/off switch
#   SPRITE_NAME=<name>          override the sprite the alert chose
#
# `herdr-alert auto` LLM-picks a name per project+branch from its branch and
# commits, caching it in ${XDG_DATA_HOME:-~/.local/share}/herdr-alert/projects.json,
# keyed first by the repository's git-common-dir (shared by every worktree of
# that repository) and then by branch name (or "detached:<toplevel>" for a
# worktree with no branch), the same two keys `herdr-alert auto`/`auto set`
# compute. Consulted here only when that file exists, so an install that
# never runs `auto` pays nothing extra: one `herdr pane get`, two `git
# rev-parse` calls, and one `jq` read, to turn the firing pane's cwd into its
# project+branch's pick, which then stands in for HERDR_ALERT_BLOCKED/DONE
# for this alert only (a literal HERDR_SOUND_* path still wins over it, same
# as a name).
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
           sound="$root/assets/audio/8bit-alert.wav"; vol="${HERDR_VOLUME_BLOCKED:-1.8}"
           sprite_pick="${HERDR_SPRITE_BLOCKED:-}" ;;
  done)    name="${HERDR_ALERT_DONE:-}";    override="${HERDR_SOUND_DONE:-}"
           sound="$root/assets/audio/8bit-alert.wav"; vol="${HERDR_VOLUME_DONE:-1.0}"
           sprite_pick="${HERDR_SPRITE_DONE:-}" ;;
  *)       exit 0 ;;
esac

# A project+branch-scoped pick from `herdr-alert auto`/`auto set`, consulted
# only when that cache file exists; wins over the plain global name but not
# a literal HERDR_SOUND_* path. One extra `herdr pane get` plus two `git
# rev-parse` calls plus one `jq` read, paid only by installs that have
# actually run `herdr-alert auto`/`auto set` at least once.
projects_file="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-alert/projects.json"
if [[ -r "$projects_file" && -n "$pane" && "$pane" != *[^a-zA-Z0-9_:-]* ]]; then
  pane_cwd=$("${HERDR_BIN_PATH:-herdr}" pane get "$pane" 2>/dev/null | jq -r '.result.pane.cwd // empty' 2>/dev/null)
  if [[ -n "$pane_cwd" && -d "$pane_cwd" ]]; then
    project_key=$(git -C "$pane_cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    branch=$(git -C "$pane_cwd" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [[ -n "$project_key" ]]; then
      if [[ -z "$branch" || "$branch" == HEAD ]]; then
        toplevel=$(git -C "$pane_cwd" rev-parse --show-toplevel 2>/dev/null)
        scope_key="detached:$toplevel"
      else
        scope_key="$branch"
      fi
      project_pick=$(jq -r --arg pk "$project_key" --arg sk "$scope_key" --arg event "$state" \
        '(.[$pk][$sk][$event]) // empty' "$projects_file" 2>/dev/null)
      [[ -n "$project_pick" ]] && name="$project_pick"
    fi
  fi
fi

# "custom" picked by `set blocked-sprite|done-sprite custom` (or the
# `set animation on` alias) selects the imported scene for this event only --
# a category of sprite, not a separate master switch. "<game>:<sprite>" picks
# a different alert's own sprite the same way. herdr-visuals re-checks either
# is actually available and falls back to the sound alert's own sprite (or
# none) otherwise, same degrade-one-step philosophy as everywhere else here.
sprite_file_pick= sprite_fullscreen_pick=
sprite_game_pick= sprite_name_pick=
if [[ "$sprite_pick" == custom ]]; then
  sprite_file_pick="${HERDR_ALERT_ANIMATION:-}"
  sprite_fullscreen_pick=1
elif [[ "$sprite_pick" == *:* ]]; then
  sprite_game_pick="${sprite_pick%%:*}"
  sprite_name_pick="${sprite_pick#*:}"
fi

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
  SPRITE_FILE="$sprite_file_pick" SPRITE_FULLSCREEN="$sprite_fullscreen_pick" \
  SPRITE_GAME="${sprite_game_pick:-}" SPRITE_NAME="${SPRITE_NAME:-$sprite_name_pick}" \
  zsh "$root/libexec/herdr-visuals" "$pane" "$state" "$name" \
    "${HERDR_ALERT_FLASH:-1}" "${HERDR_ALERT_SPRITE:-1}" &!
fi

[[ -r "$sound" ]] && sh "$root/libexec/herdr-play-sound" "$sound" "$vol" "${HERDR_ALERT_MAX_SECONDS:-}" &!

exit 0
