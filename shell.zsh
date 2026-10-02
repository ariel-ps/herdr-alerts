# Source this file from zsh to load this plugin's commands.
typeset -g _HERDR_ALERTS_ROOT="${HERDR_PLUGIN_ROOT:-${0:A:h}}"
typeset -U path
path=("$_HERDR_ALERTS_ROOT/bin" $path)

# Compatibility name for the unified CLI.
herdr-sounds-sync() { "$_HERDR_ALERTS_ROOT/bin/herdr-sound" sync "$@"; }

# Download optional game sound packs for the unified CLI.
#
#   Not committed, and deliberately so: the packs are ~150MB of ripped game
#   audio across seven titles, none of it ours to redistribute. They come from
#   archive.org on demand into XDG cache, which is the same arrangement the
#   dotfiles version used and the reason a plugin can carry the mapping without
#   carrying the media.
#
#   Everything degrades without them — the alert falls back to the two bundled
#   clips and skips the sprite — so this is optional, not setup.
__herdr_sounds_sync() {
  local root; root=$_HERDR_ALERTS_ROOT
  local cache="${XDG_CACHE_HOME:-$HOME/.cache}/herdr-kit"
  local map="$root/data/packs.json"

  command -v jq >/dev/null 2>&1 || { echo "herdr: jq not found" >&2; return 1; }
  command -v uv >/dev/null 2>&1 || { echo "herdr-sound: uv is required to download sound packs" >&2; return 1; }
  [ -r "$map" ] || { echo "herdr: pack map missing at $map" >&2; return 1; }

  local -a games=("$@")

  local game id rc=0
  for game in $games; do
    # packs.json stores a scheme-tagged source per game ("archive:<item>"),
    # because sprites for the same game come from git instead. Only the
    # archive.org half is a sound pack.
    id=$(jq -r --arg g "$game" '.games[$g].sounds // "" | sub("^archive:"; "")' "$map")
    [ -n "$id" ] || { echo "herdr-sound: unknown game '$game'" >&2; rc=1; continue; }
    printf '\nDownloading %s...\n' "$game" >&2
    if [ "$game" = redalert ]; then
      # This game's clips live inside its own encrypted MIX archives, so it
      # needs a different fetcher and Blowfish — hence uv rather than python3.
      uv run --no-project --with pycryptodome python \
        "$root/libexec/fetch-redalert-sounds.py" "$cache/sounds/$game" || rc=1
    else
      uv run --no-project python "$root/libexec/fetch-game-sounds.py" "$id" "$cache/sounds/$game" || rc=1
    fi
  done
  return $rc
}
