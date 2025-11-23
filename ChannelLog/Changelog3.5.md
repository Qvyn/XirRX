# Changelog — CrossXir
 
> Latest update: **2025-09-25**

---

## [3.5.0] — 2025-09-25
### Added
- **Audio Reaction** tab
  - Modes: **Scale**, **Opacity**, **GlowPulse** (reticle reacts to live audio level).
  - Controls for **Sensitivity**, **Smoothing (ms)**, and **Audio Device** (mic or loopback).
  - Live level meter.
  - Graceful fallback when audio backend is not installed (guidance shown).
  - Backend uses `sounddevice` + `numpy`. Enable with:
    ```bash
    pip install sounddevice numpy
    ```

- **Crash Watchdog**
  - Detects overlay stalls and attempts **automatic recovery**.
  - Optional **auto‑restart on crash** for the whole app.
  - **Crash log** written to: `%APPDATA%\eztools\crossxir_crash.log`.
  - Controls in **Advanced → Crash Watchdog** (enable, stall threshold, auto‑restart).

### Improved
- Theme polish for **Windows 11 / Neo Noir / Graphite / Minimal** skins.
- Preset handling: safer load with defaults + import/export in **Advanced**.
- Preview panel kept in sync with live overlay for faster iteration.

### Fixed
- Overlay stability during prolonged uptime (watchdog timer now monitors paint loop).
- Safer audio thread lifecycle (clean shutdown on app exit).

---

## Earlier highlights (rolling)
> These are long‑standing features

- Multiple **reticle styles**: Dot, Crosshair (+Gap/T‑Cross), Circle (+Dot/Hollow), Chevron, Tri‑Dot, Asterisk, Brackets, Square+Gap.
- **Outline** controls (color/thickness), **opacity**, **rotation**, **glow strength**.
- **Animations**: Pulse / Expand / Fade (with speed control).
- **Bloom** on LMB/RT and **Sniper scaling** on RMB/LT (XInput supported).
- **Position & Size**: multi‑monitor target, anchors (Center/Edges/Corners), pixel offsets, one‑click center.
- **Click‑through overlay** toggle (no mouse capture on the reticle window).
- **Presets**: quick built‑ins + save/delete your own.
- **Tray menu**: show/hide overlay, exit.

---

## Upgrade notes
1. If you want audio‑reactive effects, install the audio backend:
   ```bash
   pip install sounddevice numpy
   ```
2. On Windows, allow microphone access in **Settings → Privacy & security → Microphone**.
3. For game/music reaction, select a **loopback** or **Stereo Mix** device in the **Audio** tab.

---

## Troubleshooting
- **Overlay stops updating** → Watchdog will attempt recovery. If it persists, check `%APPDATA%\eztools\crossxir_crash.log` and consider enabling **Auto‑restart** in Advanced.
- **No movement on audio meter** → Pick another device in **Audio → Audio Device**; verify privacy permissions; confirm backend install.
- **Controller triggers not detected** → Ensure an XInput driver is present; try reconnecting the controller.

---

## Links
- Issues: please include your **changelog version**, **OS**, and the **last 50 lines** of `crossxir_crash.log` if relevant.

---

_Thank you for using CrossXir!_
