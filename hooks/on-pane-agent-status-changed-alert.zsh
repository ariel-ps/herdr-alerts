#!/usr/bin/env zsh
# herdr event hook: flash the pane, play the alert, draw the sprite that goes
# with it.
#
# herdr's own [ui.sound] plays one mp3 and draws nothing. This pairs each sound
# with a flash on the pane that wants attention, and a sprite on the one event
# that needs a human.
#
# It cannot call those functions directly. Both flash through `flash-term`,
# which locates the GUI terminal by walking process ancestry; a hook is spawned
# by the herdr server, whose ancestry is the server, so the flash would land
# somewhere else or nowhere. Under herdr the right target is narrower anyway:
# write the colour to that one pane's pty, the way herdr-colorize does, and one
# pane out of nine lights up rather than the whole window.
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
# Env in: HERDR_PLUGIN_EVENT_JSON (pane_id, agent_status).
#   HERDR_ALERT_OFF=1           silence entirely
#   HERDR_ALERT_FLASH=0         sound only — no wash, and no sprite either
#   HERDR_ALERT_SPRITE=0        no sprite on blocked
#   HERDR_ALERT_BLOCKED=<name>  which named alert `blocked` plays
#   HERDR_ALERT_DONE=<name>     ...and which one `done` plays
#   HERDR_SOUND_BLOCKED=<path>  a literal file, which beats the name
#   HERDR_SOUND_DONE=<path>
#   HERDR_VOLUME_BLOCKED / HERDR_VOLUME_DONE    afplay -v
#   HERDR_ALERT_MAX_SECONDS     cap a clip, default 3, empty plays it in full
#   SPRITE_NAME=<name>          override the sprite the alert chose
#
# Run by hand to hear what a name is before committing to it. Neither mode
# touches a pane — auditioning a clip should not need a live agent to block:
#   herdr-sound list
#   herdr-sound play tesla

emulate -L zsh
setopt pipefail

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

__herdr_alert_list() {
  typeset -f __herdr_alert_names >/dev/null 2>&1 || {
    echo "alert-hook: no alert table — run scripts/build/gen-alert-tables.py" >&2; return 1
  }
  local n alert_game alert_clip alert_sprite
  printf "%-12s %-10s %-10s %s\n" SOUND PACK STATUS CLIP
  for n in ${=$(__herdr_alert_names)}; do
    __herdr_alert_spec "$n" || continue
    # A blank clip column is not missing data: it is the entry saying "anything
    # from this game", which is all a pack of numbered clips can offer.
    local available=missing
    __herdr_alert_resolve "$n" && available=ready
    printf "%-12s %-10s %-10s %s\n" "$n" "$alert_game" "$available" "${alert_clip:-(any)}"
  done
  print '\nPreview:  herdr-sound play NAME'
  print 'Download: herdr-sound download PACK'
}

__herdr_alert_status() {
  local event key name override volume availability player duration='no limit'
  print 'Herdr Sound\n'
  if [[ "${HERDR_ALERT_OFF:-}" == 1 ]]; then
    printf '  %-18s %s\n' 'Automatic alerts' 'disabled'
  else
    printf '  %-18s %s\n' 'Automatic alerts' 'enabled (requires the plugin to be enabled)'
  fi
  [[ -n "${HERDR_ALERT_MAX_SECONDS:-}" ]] && duration="$HERDR_ALERT_MAX_SECONDS seconds"
  printf '  %-18s %s\n' 'Duration limit' "$duration"
  print '\nAlerts'
  printf '  %-10s %-8s %s\n' EVENT VOLUME SOUND
  for event in blocked done; do
    key=HERDR_ALERT_${(U)event}; name=${(P)key}
    key=HERDR_SOUND_${(U)event}; override=${(P)key}
    key=HERDR_VOLUME_${(U)event}; volume=${(P)key}
    [[ -n "$volume" ]] || { [[ "$event" == blocked ]] && volume=1.8 || volume=1.0; }
    [[ -n "$name" ]] || name=$(__herdr_alert_for_state "$event")
    if [[ -n "$override" && -r "$override" ]]; then
      name=$override; availability='custom file'
    elif __herdr_alert_resolve "$name"; then
      availability=ready
    else
      availability='unavailable; using bundled tone'
    fi
    printf '  %-10s %-8s %s\n' "$event" "$volume" "$name ($availability)"
  done
  print '\nAudio'
  player=$(command -v afplay || command -v ffplay) || {
    print -u2 'herdr-sound: no audio player found. Install FFmpeg on Linux.'; return 1
  }
  printf '  %-18s %s\n' 'Player' "$player"
  printf '  %-18s %s\n' 'Configuration' "$config/config.sh"
  print '\nTest speakers: herdr-sound play'
}

case "${1:-}" in
  --list) __herdr_alert_list; exit $? ;;
  --status) __herdr_alert_status; exit $? ;;
  --play)
    sound="$root/assets/audio/8bit-alert.wav"
    if [[ -n "${2:-}" ]]; then
      __herdr_alert_spec "$2" || {
        print -u2 -- "herdr-sound: unknown sound '$2'. Run herdr-sound list."; exit 1
      }
      __herdr_alert_resolve "$2" || {
        print -u2 -- "herdr-sound: '$2' is not downloaded. Run herdr-sound download $alert_game."
        exit 1
      }
    fi
    print -r -- "Playing ${2:-included tone}..."
    sh "$root/libexec/herdr-play-sound" "$sound" "${HERDR_VOLUME_DONE:-1.0}" "${HERDR_ALERT_MAX_SECONDS:-}"
    exit $? ;;
esac

# Muting automatic alerts still allows explicit previews and listing sounds.
[[ "${HERDR_ALERT_OFF:-}" == 1 ]] && exit 0

command -v jq >/dev/null 2>&1 || exit 0

state=$(print -r -- "${HERDR_PLUGIN_EVENT_JSON:-}" | jq -r '.agent_status // .status // empty' 2>/dev/null)
pane=$(print -r -- "${HERDR_PLUGIN_EVENT_JSON:-}" | jq -r '.pane_id // empty' 2>/dev/null)

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

# An 8x8 solid RGBA wash at ~35% alpha, generated rather than inlined: the
# encoded form is 344 characters of base64, and a literal that long is a copy
# error waiting to happen — one truncated paste already shipped a 264-character
# string that herdr rejected as invalid_image with the flash silently dead.
# perl is already required here for the sprite and MIME::Base64 is core.
__herdr_alert_rgba() {
  perl -MMIME::Base64 -e 'print encode_base64(pack("C4", @ARGV) x 64, "")' "$@"
}

# One JSON object per line over the pane socket. No token, no websocket.
__herdr_alert_rpc() {
  printf '%s\n' "$1" | nc -U "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/herdr.sock" >/dev/null 2>&1
}

# Flash first so the light and the sound land together rather than in sequence.
if [[ "${HERDR_ALERT_FLASH:-1}" == 1 && -n "$pane" ]]; then
  (
    # A translucent wash composited over the pane, not OSC 11 on its pty.
    #
    # OSC 11 sets the terminal's default background, which a full-screen agent
    # never shows: Claude and Codex paint their own background across the whole
    # viewport, so the pane looks identical before and after. It flashes a bare
    # shell and silently does nothing to the panes that actually block. Pane
    # graphics composite above the cells instead, which is the same reason
    # kitty-sprite.pl draws at z=1, and herdr clips the placement to the pane —
    # hence grid numbers larger than any pane rather than querying its size.
    if [[ "$state" == done ]]; then
      px=$(__herdr_alert_rgba 60 220 130 80)
    else
      px=$(__herdr_alert_rgba 255 60 60 90)
    fi
    [[ -n "$px" ]] || exit 0

    for _ in 1 2; do
      __herdr_alert_rpc "{\"id\":\"flash\",\"method\":\"pane.graphics.set\",\"params\":{\"pane_id\":\"$pane\",\"format\":\"rgba\",\"image_width\":8,\"image_height\":8,\"data_base64\":\"$px\",\"layer_id\":\"alert\",\"z_index\":9,\"placement\":{\"viewport_col\":0,\"viewport_row\":0,\"grid_cols\":400,\"grid_rows\":200}}}"
      sleep 0.18
      __herdr_alert_rpc "{\"id\":\"clear\",\"method\":\"pane.graphics.clear\",\"params\":{\"pane_id\":\"$pane\",\"layer_id\":\"alert\"}}"
      sleep 0.12
    done
    # Belt and braces: a wash left behind would sit over the pane forever, and
    # this layer is ours alone, so clearing twice costs nothing.
    __herdr_alert_rpc "{\"id\":\"clear\",\"method\":\"pane.graphics.clear\",\"params\":{\"pane_id\":\"$pane\",\"layer_id\":\"alert\"}}"

    # Sprite after the wash rather than under it: both are layers now, and the
    # sprite is the one worth looking at. Only for blocked — it runs about a
    # second and is the "come and deal with this" signal.
    if [[ "$state" == blocked && "${HERDR_ALERT_SPRITE:-1}" == 1 ]]; then
      shell_pid=$(herdr pane process-info --pane "$pane" 2>/dev/null \
        | jq -r '.result.process_info.shell_pid // empty')
      if [[ -n "$shell_pid" ]]; then
        tty=$(ps -o tty= -p "$shell_pid" 2>/dev/null | tr -d ' ')
        sprite="$root/vendor/sprite/sprite.pl"
        cols=$(stty size < "/dev/$tty" 2>/dev/null | awk '{print $2}')
        if [[ -n "$tty" && -w "/dev/$tty" && -r "$sprite" && -n "$cols" ]]; then
          # sprite.pl defaults SPRITE_DIR to the dotfiles cache it was vendored
          # from, so the kit has to name its own tree or it draws someone else's
          # packs — and on any other machine, none. Exported inside this
          # subshell, which is the whole reason the flash runs in one.
          export SPRITE_DIR="$cache/sprites"
          [[ -n "$sprite_game" ]] && export SPRITE_GAME="$sprite_game"
          # Match the frame to the clip that just played, but only when that
          # pack is actually built: a name nothing has sends sprite.pl hunting
          # for that one file across every game and then falling to its
          # procedural disc, where dropping the name gets a real frame from the
          # right game instead.
          [[ -z "${SPRITE_NAME:-}" && -n "$sprite_name" \
             && -r "$SPRITE_DIR/$sprite_game/$sprite_name.rgba" ]] \
            && export SPRITE_NAME="$sprite_name"
          perl "$sprite" "/dev/$tty" "$cols" >/dev/null 2>&1
        fi
      fi
    fi
  ) &!
fi

[[ -r "$sound" ]] && sh "$root/libexec/herdr-play-sound" "$sound" "$vol" "${HERDR_ALERT_MAX_SECONDS:-}" &!

exit 0
