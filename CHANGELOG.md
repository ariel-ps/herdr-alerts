# Changelog

All notable changes to Herdr Alerts are documented here.

## Unreleased

### Changed

- Replaced the Python sound CLI and shell audio backend with Rust.
- Preserved alert8play, settings/backups, automatic hooks, and optional Python downloaders.

- Reorganized hooks, private runtime helpers, build and development scripts,
  data, generated output, assets, and vendored code into the standard Herdr
  plugin structure.
- Preserved the `herdr-sound`, `alert8play`, and `herdr-sounds-sync` public
  commands and the existing plugin event and action IDs.

## 0.1.0 - 2026-10-02

- Initial standalone Herdr Alerts plugin.
