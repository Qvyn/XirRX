Input Refiner, Crosshair overlay, game launcher, and streamer mode to hide overlays
# XirRX

A clean Windows desktop **suite** that hosts your two tools — **InputRX** (input refinement/tuning) and **CrossXir** (crosshair overlay) — plus a **Launcher** for external apps and a **Streamer Mode** switch that hides the overlay from recordings/screenshots (while keeping it visible to you).

 This suite only *hosts* your apps. It does **not** change InputRX or CrossXir internals.

------------------------------------------

## Features

- **InputRX tab**
  - Start/Stop InputRX worker.
  - Shows the full InputRX UI inside the suite.
- **CrossXir tab**
  - Show/Hide the overlay window without leaving the suite.
- **Launcher tab**
  - Create named entries (Path, Args, optional Working Dir).
  - Launch/Stop processes and see live “running/stopped” status.
  - Stores entries in `launchers.json` next to the EXE.
- **Streamer tab**
  - One checkbox to toggle **Streamer Mode** (capture exclusion).
  - Mirror of the tray toggle.
- **Tray menu**
  - Start/Stop InputRX
  - Show/Hide Overlay
  - Streamer Mode (hide overlay from capture)
  - Launchers → “Open Launcher Tab”
  - Quit
- **Passive watchdog**
  - No auto start/stop/hide/show.
  - Only re-applies Streamer Mode capture-exclusion if enabled.

---

## How Streamer Mode works

XirRX toggles Microsoft’s **`SetWindowDisplayAffinity`** on the CrossXir overlay window:

- When **ON** → `WDA_EXCLUDEFROMCAPTURE`: overlay is **excluded from screenshots and screen recording**, but remains visible to you.
- When **OFF** → `WDA_NONE`: normal capture.

**Requirements & notes**

- Windows 10 **2004** (20H1) or newer / Windows 11.
- Works with most capture paths (PrintScreen, Snipping Tool, Windows GraphicsCapture-based tools).
- **OBS tips**
  - *Display Capture* usually respects exclusion (overlay not captured).
  - *Game Capture* that hooks the game render pipeline typically won’t include a separate overlay window anyway.
  - Avoid explicitly capturing the overlay window or using legacy capture drivers if you want it hidden.

---

## Requirements

- **Windows** (x64 recommended)
- **Python 3.10+** ONLY TO BUILD
- Packages:
  - `PyQt6` (UI)
  - `psutil` *(optional, improves process status checks for Launcher)*
  - `PyInstaller` *(only for packaging to EXE)*
- Your app modules next to the suite file:
  - `input_refiner_pyqt6_stable_patched_ultrasens.py`
  - `crosshair_x_designer_stack_patched.py`

```
pip install PyQt6 psutil pyinstaller
```

---

## Project layout (suggested)

```
XirRX/
├─ suite_one_app_safe_baseline_fixed.py   # the suite
├─ input_refiner_pyqt6_stable_patched_ultrasens.py
├─ crosshair_x_designer_stack_patched.py
├─ launchers.json                          # auto-created/edited by the suite
├─ icons/
│  └─ Suite_Streamer_Crosshair_InputRX.ico
```

---

## Quick start (source)

```
py suite_one_app_safe_baseline_fixed.py
```

- Use the tabs to control InputRX and CrossXir.
- Add tools on the **Launcher** tab (Name, Path, Args, optional Working Dir).
- Toggle **Streamer Mode** from the **Streamer** tab or the **tray**.

---

## Build an EXE

Use the custom icon and set the app name to **XirRX**:

```
py -m PyInstaller --onefile --windowed --name XirRX --icon "icons/Suite_Streamer_Crosshair_InputRX.ico" suite_one_app_safe_baseline_fixed.py
```

The EXE will appear in `./dist/XirRX.exe`.

> If Windows Defender flags unknown publisher EXEs, sign it or add it to allowed list.

---

## Configuration files

- **`launchers.json`** (auto-created)
  - Array of entries like:
    ```json
    [
      {"name": "Steam", "path": "C:\\Program Files (x86)\\Steam\\steam.exe", "args": "", "cwd": ""},
      {"name": "Notepad", "path": "C:\\Windows\\System32\\notepad.exe", "args": "", "cwd": ""}
    ]
    ```
  - The **Launcher** tab manages this for you.

> *Auto-rules* are intentionally **disabled** in this baseline to avoid side-effects. If you want them back later, we can add a guarded `auto_rules.json` + toggle.

---

## Troubleshooting

**QWidget: Must construct a QApplication before a QWidget**  
Run the suite as the main entry script (don’t import it into another process without a `QApplication`).

**Nothing happens when I click Start/Stop**  
Check the console for Python exceptions. Ensure `input_refiner_pyqt6_stable_patched_ultrasens.py` and `crosshair_x_designer_stack_patched.py` are present next to the suite.

**OBS still shows the overlay**  
- Make sure **Streamer Mode** is ON (tray or Streamer tab).  
- Prefer **Display Capture** on modern Windows; avoid explicitly capturing the overlay window; try disabling legacy capture methods.

**Launcher says “Path does not exist”**  
Use **Browse…** to select the exact `.exe`. If the app needs a working directory, fill in **Working Dir**.

**Windows blocks the EXE**  
Unsigned EXEs may show SmartScreen warnings. You can sign the binary or allow it on your machine.
