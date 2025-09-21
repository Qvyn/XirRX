# XirRX — Channel Log (All Recent Updates)

This log summarizes **all new features, UI changes, optimizations, logging/routing fixes, and build steps** added since the baseline.

---

## 🚀 New Features

- **Drift Lab — “Aim Pop” mode** with adjustable **Time (10–60s)** and **Pace (200–2000 ms)**; score HUD shows **Score / Accuracy / Time Left**. Targets are the only elements visible during runs; a minimal **crosshair visualizer** appears when started. Spawns use a **single‑shot timer** for consistent pacing.  
- **Streamer Mode**: Excludes the overlay from capture (you see it; your viewers don’t). Accessible via tab and tray. 
- **Launcher, modernized**: Converted to **QAbstractTableModel + QTableView** for snappier refresh, with **Add / Edit / Delete / Launch / Stop** actions and a periodic **status refresh**. 

---

## 🧭 UI & UX Changes

- **Sidebar tiles** aligned to fill the full sidebar and **toggleable** to reclaim space for InputRX/CrossXir canvases (visual refresh).
- **Entire UI is scrollable** so you don’t need full‑screen to access everything.
- **Drift Lab crosshair** shows when the run starts for better aiming feedback. (may not work correctly)
> Notes: The base app structure remains the same (InputRX, CrossXir, Launcher, Streamer tabs).

---

## ⚙️ Performance Optimizations

- **Single‑shot timers** for Aim Pop spawns (replaces modulo checks). 
- **Cached pens/brushes** in Drift Lab (no allocation inside `paintEvent`). (See Drift Lab initializations and drawing usage.) 
- **`@pyqtSlot` on hot paths** (status refresh, spawn handler) to reduce dispatch overhead. 
- **Launcher refactor to model/view**: partial updates via `dataChanged` on just the Status column instead of full table rewrites.

---

## 🧰 Reliability & Bug Fixes

- Fixed **init and paint** errors in Drift Lab by ensuring cached resources exist and normalizing indentation for all methods (e.g., `_set_mode`, `start`, `paintEvent`). 
- Added **no‑op `_ensure_pens()`** in non‑drawing tabs (InputRX / CrossXir / Launcher) to prevent attribute errors. 
- Hardened **Launcher save path** and routing so configs land in `/config/` and are created 

---

## 🗂 Folderization & Logging

- App now creates and uses **`config/`**, **`logs/`**, and **`data/`** folders next to the executable.
- **Launcher config** saved to `config/launcher_data.json`. (Previously loose in root.) 
- **Rotating app log** at `logs/suite.log` and **sweep** that moves stray `input_refiner.log` and `faulthandler.dump` into `logs/`. (Empty root logs are removed; moves are atomic where possible.)
- **Streamer Mode / capture exclusion** remains as in baseline (Win10 2004+). 

---

## 🧪 Drift Lab Details

- **Controls**: Start, Reset, Mode, Time (s), Pace (ms). 
- **Run lifecycle**: starts a 16 ms timer; Aim Pop schedules its own spawns; HUD updates each tick; run auto‑stops at configured duration and shows results. 

---

## 🧭 Launcher Details

- **Model/View** wiring: add/edit/delete plus **Launch/Stop** with **periodic status**. 
- **Selective updates**: only the Status column emits `dataChanged`. 

---

## 🧱 Baseline Carry‑Over

- Core tabs and behaviors (InputRX, CrossXir, Launcher, Streamer) from the fixed baseline remain in place. fileciteturn5file2L4-L7
- Overlay capture exclusion uses Windows **WDA_EXCLUDEFROMCAPTURE** flag. 

---

## 🏗 Build (one‑liner)

```powershell
py -m PyInstaller .\suite_one_app_safe_baseline_PRO.py --name XirRx --onefile --windowed --icon .\XirRx.ico --clean --collect-all PyQt6