# XirRX — Current Build

XirRX is a streamlined Windows gaming utility suite focused on two core tools:

- **InputRX — controller-to-mouse right-stick refinement for games that need mouse-like camera control from an XInput controller.
- **CrossXir** — an always-on-top crosshair overlay with configurable styles, outline/glow options, audio-reactive effects, and streamer/capture controls.

> **Launcher removed:** the old Launcher/UWP game launcher is no longer included in the current XirRX build.
---

## Current module status

### InputRX

InputRX is the part that changed the most recently. The refiner has been reworked around a stricter gameplay contract:

Recent refiner work focused on removing systems that were fighting third-person camera behavior in 3rd person-style games. The worker should no longer multiply, suppress, ramp, freeze, or replay camera movement based on cover state, action buttons, left-stick movement, pickup animations, or game camera correction. The refiner is not a game hook, memory editor, anti-recoil script, or macro executor. It sends OS-level relative mouse movement based on controller input.

---

### CrossXir

CrossXir is the crosshair overlay module. It has not changed much recently compared with the refiner, but it remains part of the current suite.

---

### Streamer / Capture Mode

Streamer Mode controls whether the overlay is visible to capture tools while still remaining visible locally when Windows supports it.

- Uses Windows display-affinity behavior where available.
- Can hide the overlay from screenshots/recording/stream capture depending on OS and capture method.
- Keeps capture-exclusion behavior separate from refiner input logic.

---

## What is no longer included

The following old XirRX pieces were removed from the current build:

- Launcher/UWP/Xbox game launcher
- Launcher sidebar tab/page
- Launcher tray/menu entries
- Launcher process-priority controls
- Launcher CPU-affinity controls
- Steam validation pre-launch workflow

If you see old README text describing a bundled Launcher, it is outdated.

---

## Requirements

### Running a packaged build

- Windows 10 or Windows 11
- XInput-compatible controller for InputRX
- A game/window target for focused input routing

A packaged `.exe` build should not require Python.

### Running from source

Recommended:

```powershell
py -3.11 -m pip install PyQt6 psutil comtypes
```

Then run the current app entrypoint used by the project build. If you are using the modular refiner-only package, run:

```powershell
py -3.11 run_refiner.py
```

or:

```powershell
py -3.11 -m jacinto_input_refiner
```

---

## Logs and troubleshooting

InputRX/refiner logs are written to:

```text
input_refiner.log
```

Common things to verify:

- The log should show the current worker version you expect to be running.
- In pure right-stick mode, the log should not show cover/action/left-stick/camera-settle suppression paths.
- Idle stick samples below the intent floor should log as zero output.
- Direct scaling should show the config value as the active full-stick speed rather than huge multiplied values.

---

## Safety

XirRX uses OS-level input and overlay behavior. The refiner does not inject into games, read game memory, patch game files, or execute gameplay macros. InputRX is intended to translate controller right-stick movement into controlled mouse movement for accessibility, tuning, and camera-feel refinement.
