# Changelog

All notable changes to Herdr Alerts are documented here.

## Unreleased

### Fixed

- Accept Herdr's workspace-qualified pane IDs (for example, `wN:p3`) when
  flashing panes through manual previews or automatic alerts.

### Added

- `herdr-sound play [NAME] --flash` and `alert8play [NAME] --flash` preview
  sound with two terminal flashes, or green pane flashes when inside Herdr.
- Terminal previews work without a running Herdr instance and keep escape
  sequences out of redirected logs.
- Manual previews and automatic alerts share pane-flash rendering, with
  connection/error checks and a final cleanup attempt.

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
