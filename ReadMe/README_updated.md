# XirRX

A compact Windows suite that pairs a **clean crosshair overlay (CrossXir)** with **input tuning (InputRX)**, plus a **Launcher**, **Streamer Mode**, and a few training toys like **Drift Lab (Aim Pop)**. Built with PyQt on Windows.

---

## ✨ Highlights

- **CrossXir (overlay)** — crisp, adjustable crosshair that can stay on your screen while **Streamer Mode** hides it from recordings.
- **InputRX** — input helper/tweaker with simple start/stop and status indicators.
- **Launcher** — add games/apps and launch them from within XirRX. Backed by a fast `QAbstractTableModel` + `QTableView` for snappy updates.
- **Drift Lab (Aim Pop)** — an optional aim drill: spheres spawn at a configurable pace; click to “hit.” Shows **Score**, **Accuracy**, **Time Left**; crosshair overlay inside the canvas; no drag marks.
- **Pulse Bar / Anomaly Light** — subtle visual pulse feedback you can keep on-screen.
- **Tray menu** — quick Start/Stop/Show/Hide/Streamer toggles, optional shortcuts.
- **Neat folders** — app‑generated files are routed to `config/`, `logs/`, and `data/` next to the app.

---

## 🖥 Requirements

- Windows 10 (2004+) or Windows 11
- Microsoft Visual C++ redistributables (typical on gaming PCs)
- No install required for release builds — just run `XirRX.exe`

---

## 🚀 Quick Start

1. Download `XirRX.exe` and launch it.
2. Tabs you’ll see: **InputRX**, **CrossXir**, **Launcher**, **Streamer**, **Drift Lab**.
3. Right‑click the **tray icon** for quick actions.

### Streamer Mode
- **ON:** Crosshair is hidden from screen captures; **you still see it**.
- **OFF:** Overlay behaves normally.
- **OBS tip:** Prefer **Display Capture**; avoid capturing the overlay window directly if you want it hidden.

### Drift Lab (Aim Pop)
- Set **Time** (10–60s) and **Pace** (200–2000 ms), press **Start**.
- Only the spheres + crosshair render (no guides or drag path). Click targets to rack up hits.

---

## 📂 Folders & Logs

XirRX creates these next to your `.exe`/`.py`:

```
config/   # JSON/settings (e.g., launcher_data.json)
logs/     # suite.log, input_refiner.log, faulthandler.dump
data/     # future exports, scores, etc.
```

- On startup and periodically, XirRX **sweeps** the app root and moves stray logs (e.g., `input_refiner.log`, `faulthandler.dump`) into `logs/`. Empty root logs are removed.  
- The app uses **rotating file logging** in `logs/suite.log`.

---

## 🛠 Building from Source (Windows)

Install PyInstaller and build a single‑file exe with your icon:

```powershell
py -m pip install --upgrade pip pyinstaller
py -m PyInstaller .\suite_one_app_safe_baseline_PRO.py --name XirRx --onefile --windowed --icon .\XirRx.ico --clean --collect-all PyQt6
```

> If a `XirRx.spec` already exists, PyInstaller will use it and ignore CLI `--icon`. Either delete the spec first or edit its `icon=` path, then build the spec:
>
> ```powershell
> py -m PyInstaller .\XirRx.spec --clean
> ```

**Outputs:** `.\dist\XirRx.exe`

---

## 🧭 Launcher Usage

- **Add**: pick a game/app `.exe`, optional args & working dir → **Launch**.
- Status column updates periodically: **running / stopped**.
- Data is saved to `config/launcher_data.json` (created automatically).

---

## ❓ FAQ

- **Viewers can’t see my crosshair.** — Streamer Mode is **ON** (expected). Turn it **OFF** to show it on stream.
- **Overlay gone on stream but I see it locally.** — Streamer Mode **ON** (working as designed).
- **Start/Stop InputRX does nothing.** — Restart XirRX; run once as Administrator if needed.
- **Antivirus flagged it.** — New unsigned apps can warn; allow if you trust the source.
- **Logs in the root folder?** — The sweep should move them into `logs/` within a few seconds; otherwise delete any 0‑byte root logs and restart.

---

## 🔧 Dev Notes

- UI is scrollable so you can run windowed.
- Launcher uses `QAbstractTableModel` + `QTableView` (fast updates).  
- Drift Lab uses single‑shot timers for spawns and cached pens/brushes for low‑overhead drawing.
- Signals use `@pyqtSlot` on hot paths for a small dispatch win.

---

## 🔒 Privacy & Safety

- XirRX does **not** upload data.
- Streamer Mode only alters how Windows/recorders capture the overlay; it doesn’t inject into games or touch network data.
- Exiting the app stops all timers and background work.

---

## 📜 License

Copyright © 2025. All rights reserved unless otherwise noted.
