# Herdr Alerts

Alerts help people notice when a coding agent finishes or needs attention.

## Language

**Alert**:
A notification presented through sound, a flash, a sprite, or a combination of these.
_Avoid_: Sound, when referring to the entire notification.

**Preview**:
An alert deliberately triggered by the user to experience its effects without
changing its assignment.

**Alert assignment**:
The saved choice of alert for Needs attention or Finished notifications.

**Alert menu**:
The interactive terminal menu for viewing settings, previewing and configuring
alerts, downloading packs, and diagnosing problems.

**Sound**:
The audible part of an alert.

**Mute sound**:
Suppress automatic alert audio and ordinary preview audio while preserving
configured visuals; an explicit **Play sound once** sample does not change mute.
_Avoid_: Pause all alerts, when visual notifications continue.

**Pause all alerts**:
Suppress all automatic alert effects, including sound, flashes, and sprites,
until manually resumed.
_Avoid_: Mute sound, when every automatic effect is suppressed.

**Flash**:
A brief visual change that draws attention to a pane.

**Sprite**:
An animated image associated with an alert.
_Avoid_: Loading indicator, when referring to alert artwork.

**Fallback animation**:
A substitute animation shown when selected sprite artwork is missing or broken;
it does not mean artwork is downloading.

**Animation cycle**:
One complete pass through an animation's frames, before it repeats or clears.

**Pack**:
A collection of sounds and any associated sprite artwork from a shared theme.

**Partial pack**:
A pack with some usable content and some expected content missing or failed.
A pack designed to contain only sounds is not partial merely because it has no artwork.

**Pane focus**:
The selection of a particular Herdr pane for interaction.

**Window focus**:
The desktop's selection of the terminal window containing Herdr for interaction.
_Avoid_: Focus alone, when the distinction from pane focus matters.
