# XirRx — v4.0.5

A streamlined Windows gaming suite that bundles four pieces into one app:

- **InputRX** — controller→mouse refinements and aim shaping with profiles and anti‑yank micro‑guard.  
- **CrossXir** — an on‑top crosshair overlay with styles, outline, bloom, audio‑reactive effects, and a crash watchdog.  
- **Launcher** — a universal UWP/Xbox (Microsoft Store) game launcher that applies **CPU affinity** and **process priority**, with optional **Steam validation** pre‑launch.  
- **Streamer Mode** — one toggle to hide the overlay from captures while you still see it.

> The suite hosts these tools and orchestrates them together; each tool keeps its own internal logic and UI. (See feature references at the end.)

---

## What’s new in 4.0.5

**Better Steam validation → launch flow**  
- No log parsing. The launcher opens `steam://validate/<AppID>`, **watches Steam’s window title** for *Validating / Verifying / Updating*, and when it disappears for a few seconds, it **auto‑launches** your game.  
- If Steam never shows those words (localization/skin), there’s a **safe fallback wait** so you never get stuck.

**Suite polish & stability**  
- InputRX and CrossXir are hosted inside tabs with clean start/stop and show/hide controls, plus a tray menu.  
- Watchdogs and fault handlers write to `/logs` so crashes are easy to diagnose.

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

### Launcher (UWP/Xbox + Steam validation)
- **Goal**: Launch UWP apps by **AUMID**, then apply **priority** and **CPU affinity** to the running process.  
- **Highlights**:
  - COM activation via `IApplicationActivationManager` with fallback, per‑title args, optional desktop shortcut creation. fileciteturn3file3
  - **Priority/affinity** mapping including “all but CPU0” convenience mask. fileciteturn3file3
  - **Steam validation first, then launch** using a **window‑title watcher** + **fallback wait** — no log parsing. fileciteturn3file3

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

## Quick start (as a user)

1. Run **XirRx.exe**.  
2. Tabs:  
   - **InputRX** → Start/Stop worker; tweak sliders; save profiles.  
   - **CrossXir** → Show/Hide overlay; pick style, size, gap, outline, effects.  
   - **Launcher** → Add UWP title (AUMID), set args/priority/affinity; *optional*: Steam AppID.  
   - **Streamer** → Toggle **Hide from capture** (you still see the overlay).  
3. Use the **tray icon** for quick toggles and to launch saved titles. fileciteturn3file0

---

## Steam validation flow (optional)

Some titles require a validation pass before each launch (anti‑cheat or Platform rules).  
- Set a **Steam AppID** on the entry and click **Validate via Steam**.  
- XirRx opens `steam://validate/<AppID>`, **watches Steam’s title** for “Validating / Verifying / Updating”, and when it’s gone for ~5s, it **auto‑launches** your game.  
- If your Steam skin/language doesn’t show those words, XirRx uses a **fallback wait** so you still launch. fileciteturn3file3

---

## Build from source

Baseline one‑file build (icon/name optional): fileciteturn3file0
```powershell
py -m PyInstaller --onefile --windowed --name XirRx ^
  --icon "icons/Suite_Streamer_Crosshair_InputRX.ico" suite_one_app_safe_baseline_fixed.py
```

---

## Troubleshooting

- **Overlay shows on stream** → Ensure **Streamer Mode** is ON and capture via modern **Display Capture**; don’t capture the overlay window directly. fileciteturn3file0  
- **Tweaks didn’t apply** → Increase **Wait (s)** or set **Target EXE** exactly in the Launcher entry; verify AUMID. fileciteturn3file3  
- **Controller not detected** → Check XInput drivers/cables; the worker logs to `input_refiner.log` under `/logs`. fileciteturn3file2  
- **Crashes** → Crash watchdog will log and optionally auto‑restart CrossXir; check AppData crash log. fileciteturn3file1

---

## Privacy

- No telemetry. No remote calls. All logs are local to your machine. fileciteturn3file4

---

## Credits / File Map

- **Suite shell** (tabs, tray, capture exclusion, logs): `suite_one_app_safe_baseline_fixed.py`. fileciteturn3file4  
- **Launcher** (UWP + Steam validation + priority/affinity): `launcher.py`. fileciteturn3file3  
- **InputRX** (aim shaping, profiles, anti‑yank, cover‑guard): `input_refiner_pyqt6_stable_patched_ultrasens.py`. fileciteturn3file2  
- **CrossXir** (overlay styles, audio reaction, watchdog): `crosshair_x_designer_stack_patched.py`. fileciteturn3file1

---

## Changelog (high‑level)

**4.0.5**  
- Added **auto‑launch** after Steam validation.  
- Replaced log parsing with a **window‑title watcher** + **fallback wait**.  
- Stability & logging improvements across suite hosting and watchdogs. fileciteturn3file3turn3file4
