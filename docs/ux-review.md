# Alert UI and UX review

Status: core UX interview complete. Animation import and complete-cycle playback
are implemented locally. The broader interactive CLI redesign remains planned.
Findings describe the experience reviewed during the interview.

## Scope

Scope: Herdr Alert's command line, installation experience, and sound, flash,
and sprite behavior. Existing Herdr menu entries are shortcuts; the user has
ruled out the menu as a viable primary interface.

## Existing behavior agreed in the discussion

- A focused pane displays its sprite for about a second, then clears it.
- An unfocused pane keeps its sprite until focus returns.
- Manual previews and automatic alerts follow the same focus behavior.
- Pack downloads include sounds and available sprite artwork; `sync` is an alias.

These are the current baseline, not new redesign decisions. Focus tracking can
be unavailable, and persistent sprites currently have a 30-minute limit.
Decision 15 extends the focused-pane display duration for longer scenes.

## Findings from the current product

| Finding | User consequence | Evidence |
| --- | --- | --- |
| The menu lists sounds but has no pack download or named-alert selection action. | Choosing an alert requires discovering CLI commands. | Herdr Setup: `config/quick-actions/herdr-setup-sounds.toml` |
| “Mute automatic sounds” disables the automatic event handler. | Visual alerts stop too, despite the audio-only label. | Menu template; `hooks/on-pane-agent-status-changed-alert.zsh` |
| Availability checks resolve audio files, not sprite artwork or focus support. | An alert can appear ready while showing fallback artwork or different dismissal behavior. | `src/main.rs`: catalog listing and status |
| The menu preview plays the included tone. | It does not directly demonstrate the user's chosen blocked or finished alert. | Menu template; `src/main.rs`: play command |
| Flash and sprite controls are separate On and Off actions. | Their current state is only available through another action. | Menu template |
| Names vary between Herdr Alert, Herdr Alerts, Status Alerts, and Sound and visual alerts. | Users have several names to recognize for the same product. | README, CLI help, plugin manifest, menu template |

## Decisions

1. **CLI first.** Provide the guided workflow through interactive terminal prompts.
   Existing Herdr menu entries can serve as shortcuts. The user selected this
   approach because a menu-led workflow is not possible in their setup.
   All alert settings must be configurable through the CLI.
2. **Interactive entry point.** Running `herdr-alert` with no arguments in a
   terminal opens the alert menu. It shows current settings and offers Preview,
   Configure, Download packs, and Diagnose. Explicit commands remain available
   for scripts; interactive prompts require a terminal.
3. **Download and preview.** Selecting an alert from a missing pack offers an
   explicit Download and preview action. Download its sounds and available
   artwork, verify them, then preview the selected alert. Do not require the
   user to navigate to a separate download workflow first.
4. **Partial downloads remain usable.** If sound succeeds but artwork fails,
   retain the sound and show **Sound ready / Artwork failed**. Offer **Retry
   artwork** and **Preview sound only**. Do not label the pack fully ready or
   silently substitute fallback artwork in this guided preview.
5. **Preview before applying.** Browsing and previewing do not change alert
   assignments. Save a choice through **Use for Needs attention** or **Use for
   Finished**. Existing explicit CLI `set` commands remain save actions.
6. **Event-specific previews.** Preview Needs attention and Preview Finished
   reproduce the selected event's sound, volume, flash, sprite rules, and focus
   behavior. An explicit sound-only preview remains labeled as such. Avoid a
   generic effects demonstration that differs from the configured notification.
7. **Separate mute and pause controls.** Mute sound silences automatic audio
   while preserving configured visual alerts. Pause all alerts suppresses all
   automatic effects. Keep these distinct in both labels and behavior.
8. **Previews respect mute.** Ordinary previews show configured visuals without
   audio when sound is muted. Offer **Play sound once** to explicitly play a
   sample without changing the mute setting.
9. **Pause until manually resumed.** Pause all alerts remains active until the
   user resumes through the CLI. No pause timer or duration picker.
10. **Previews work while paused.** Explicit previews do not resume automatic
    alerts. They continue to respect the separate sound-mute setting.
11. **Active immediately after installation.** Fresh installations enable
    automatic alerts with default settings, without requiring a first-run
    preview or activation step. Preserve existing users' saved settings.
12. **All effects enabled by default.** Fresh installations enable sound,
    sprites, and flash, subject to each event's effect rules. Users can configure
    each through the CLI.
13. **Fallback artwork for automatic alerts.** When selected sprite artwork is
    missing or broken, show the fallback animation and retain working configured
    effects. Expose the artwork problem and a repair option in the CLI; fallback
    use must not make the selected artwork appear ready.
14. **Labeled fallback in event previews.** Preview Needs attention and Preview
    Finished reproduce the automatic alert's fallback when assigned artwork is
    missing or broken. Show **Using fallback artwork** and offer repair. Guided
    pack downloads retain their retry-artwork and sound-only preview options.
15. **Complete scenes in focused panes.** When the pane is already focused,
    play one complete animation cycle, then clear it, even if the scene lasts
    longer than the current roughly one-second display. For example, a
    three-second Mario-and-turtle scene plays all three seconds. Unfocused
    panes retain the existing loop-until-focus behavior.

## Animation support

`herdr-alert set animation FILE` imports GIF or animated PNG artwork as a single
sequence of composed frames. The existing renderer plays complete sequences,
preserves rectangular dimensions and frame timing, and loops imported scenes
without a pause between passes. Returning focus during a repeated cycle clears
the scene promptly. Audio still plays once per event.

Imports are converted once and stored in the user data directory; failed imports
leave the previous selection intact. `set animation default` restores the
sound's paired artwork. Custom scenes use the existing preview and blocked-event
paths and obey the sprite on/off setting. See the README for import limits.

## Review notes

Keep focus-based dismissal, with the complete-cycle extension in decision 15.
Preview respects sound mute
but bypasses automatic-alert pause without changing either setting. Enabling
all effects by default preserves event-specific rules; it does not add sprites
to events that currently omit them. Fallback artwork keeps an alert usable but
does not establish that its selected pack is fully ready.
