#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cargo build --release --locked --manifest-path "$root/Cargo.toml" --target-dir "$root/target"
mkdir -p "$root/libexec"
cp "$root/target/release/herdr-sound" "$root/libexec/.herdr-sound.$$"
mv "$root/libexec/.herdr-sound.$$" "$root/libexec/herdr-sound"
