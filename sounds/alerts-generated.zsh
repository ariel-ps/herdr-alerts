# alerts-generated.zsh — GENERATED from sounds/packs.json. Do not edit.
# Regenerate with scripts/gen-alert-tables.py; the plugin's [[build]] step does.
#
# Sourced by alert-hook.sh. Committed rather than built on demand so a checkout
# that was linked instead of installed — no [[build]] run — still has a table.

# name -> game, clip basename (empty = any clip from the game),
# sprite basename (empty = any sprite from the game).
# Sets alert_game / alert_clip / alert_sprite; returns 1 on an
# unknown name so the caller can fall back rather than guess.
__herdr_alert_spec() {
  alert_game= alert_clip= alert_sprite=
  case "${1:-}" in
    unit-ready) alert_game='redalert'; alert_clip='EYESSIR1'; alert_sprite='1tnk' ;;
    tesla) alert_game='redalert'; alert_clip='TSLACHG2'; alert_sprite='tsla' ;;
    harvester) alert_game='redalert'; alert_clip='CASHTURN'; alert_sprite='harv' ;;
    orca) alert_game='redalert'; alert_clip='AACANON3'; alert_sprite='orca' ;;
    kaboom) alert_game='redalert'; alert_clip='KABOOM22'; alert_sprite='veh-hit1' ;;
    redalert) alert_game='redalert' ;;
    win) alert_game='mario'; alert_clip='Mario 1 - Win Stage'; alert_sprite='star' ;;
    1up) alert_game='mario'; alert_clip='1up'; alert_sprite='mushroom' ;;
    coin) alert_game='mario'; alert_clip='coin (nes)' ;;
    powerup) alert_game='mario'; alert_clip='Power Up (nes)'; alert_sprite='fireflower' ;;
    die) alert_game='mario'; alert_clip='Mario 1 - Die'; alert_sprite='goomba' ;;
    gameover) alert_game='mario'; alert_clip='Mario 1 - Game Over'; alert_sprite='koopa' ;;
    waiting) alert_game='mario'; alert_clip='Break Brick'; alert_sprite='jump' ;;
    dk) alert_game='mvdk'; alert_sprite='dk' ;;
    barrel) alert_game='mvdk'; alert_sprite='barrel' ;;
    punchout) alert_game='punchout'; alert_sprite='mac' ;;
    spin) alert_game='sonic'; alert_sprite='spin' ;;
    codec) alert_game='metalgear' ;;
    kirby) alert_game='kirby' ;;
    *) return 1 ;;
  esac
}

# Every name, for `alert-hook.sh --list` and for tab completion.
__herdr_alert_names() {
  print -r -- 'unit-ready tesla harvester orca kaboom redalert win 1up coin powerup die gameover waiting dk barrel punchout spin codec kirby'
}

# herdr transition -> the alert it plays when nothing overrides it.
__herdr_alert_for_state() {
  case "${1:-}" in
    blocked) print -r -- 'unit-ready' ;;
    done) print -r -- 'win' ;;
  esac
}
