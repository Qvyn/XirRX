# XirRx — v4.6

A streamlined Windows gaming suite that bundles four pieces into one app:

- **InputRX** — controller→mouse refinements and aim shaping with profiles and anti‑yank micro‑guard.  
- **CrossXir** — an on‑top crosshair overlay with styles, outline, bloom, audio‑reactive effects, and a crash watchdog.  
- **Launcher** — a universal UWP/Xbox (Microsoft Store) game launcher that applies **CPU affinity** and **process priority**, with optional **Steam validation** pre‑launch.  
- **Streamer Mode** — one toggle to hide the overlay from captures while you still see it.

> The suite hosts these tools and orchestrates them together; each tool keeps its own internal logic and UI. (See feature references at the end.)

---

## Modules at a glance

### InputRX
- **Goal**: Convert right‑stick motion into finely‑shaped mouse movement for third‑person/ADS use‑cases.  
- **Highlights**:
  - Profiles (save/load/delete), slider‑help text, crash‑hardened logging. fileciteturn3file2
  - **Micro‑jolt anti‑yank guard** for tiny stick inputs and rapid bursts. fileciteturn3file2
  - **Cover‑guard** window to reduce camera yank when entering/exiting cover. fileciteturn3file2
  - Continuous radial deadzone, curve exponent shaping, smoothing & slew limits. fileciteturn3file2
  - Foreground‑window targeting so it only runs when your game is focused. fileciteturn3file2

### CrossXir
- **Goal**: Crisp, configurable crosshair overlay that stays on top.  
- **Highlights**:
  - Multiple styles (Dot, Crosshair+Gap, Circle, Chevron, Tri‑Dot, etc.), outline pass, glow/bloom, rotation. fileciteturn3file1
  - **Audio‑Reaction** (optional mic/loopback): scale/opacity/glow pulse driven by amplitude. fileciteturn3file1
  - **Crash Watchdog** with auto‑restart and stall recovery, crash logs under AppData. fileciteturn3file1
  - XInput trigger awareness (e.g., sniper scaling on RMB/LT). fileciteturn3file1

### Streamer Mode & Suite
- **Goal**: Make the overlay invisible to recordings/screenshots while remaining visible to you.  
- **Highlights**:
  - `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` toggle from the **Streamer** tab and the **tray**. fileciteturn3file4
  - Tabs: **InputRX**, **CrossXir**, **Launcher**, **Streamer**. fileciteturn3file0
  - Passive watchdog (re‑applies capture exclusion), log routing to `/logs`, and clean shutdown hooks. fileciteturn3file4

---

## Requirements

- **Windows 10 2004+** or **Windows 11**  
- Runtime EXE requires no Python. (Python 3.10+ only if you’re building from source.) fileciteturn3file0
- Recommended packages for building: `PyQt6`, `psutil`, `comtypes`, `PyInstaller`. fileciteturn3file3

---
##CHANGELOG

- Removed Launcher completely

- The Launcher/UWP tab is gone (no sidebar button, no stack page).

- All Launcher code paths were removed, so the app no longer imports or depends on launcher.py.

- Tray/menu items related to Launcher were remov


