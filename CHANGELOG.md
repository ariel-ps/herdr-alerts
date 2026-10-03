# Changelog

All notable changes to Herdr Alerts are documented here.

## Unreleased

### Fixed

- Read Herdr's event `data` envelope so automatic sounds, flashes, and blocked
  sprites actually run. Keep flat payloads working for manual callers.
- Reuse the original `flash-term` background effect outside Herdr and the
  existing sprite renderer's Kitty protocol inside Herdr. Remove the unsupported
  graphics API and invisible visual-bell fallback; verify rendered pixels.
- Accept Herdr's workspace-qualified pane IDs (for example, `wN:p3`) when
  flashing panes through manual previews or automatic alerts.

### Added

- `herdr-alert` is the main CLI; `herdr-sound` and `alert8play` remain compatible.
- Manual previews show sprites using the saved sprite setting and the same
  renderer as automatic alerts. Previews animate once, then clear the image.
- `herdr-sound set sprite on|off` saves the blocked-alert animation preference,
  independently of flashing. Status shows both settings.

- `herdr-sound set flash on|off` saves a shared preference for previews and
  automatic alerts. Flashing defaults to on; no playback flag is needed.
- Previews flash green four times, using the original flash-term timing.
- Terminal previews work without a running Herdr instance and keep escape
  sequences out of redirected logs.
- Manual previews and automatic alerts share flash rendering and cleanup.

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
