# XirRx Input Refiner 

A Windows tool for smoothing and shaping controller → mouse translation with a focus on **third‑person shooters**. It adds fine‑grained stability controls, profile management, and a new **Cover Guard** that prevents camera yanks when entering/exiting cover in *Gears of War Reloaded*.

![Status](https://img.shields.io/badge/status-active-brightgreen) ![Platform](https://img.shields.io/badge/platform-Windows%2010%2B-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## ✨ Highlights
- **Cover Guard**: clamps per‑tick deltas and eases sensitivity for a short window as you enter/exit cover (fixes the “snap‑yank”).
- **Cover+ (advanced)**: time‑decay clamp + near‑center gate + yank dampener; optional ADS exemption.
- **Micro‑jolt guard & slew caps**: tame tiny jitters and sudden sign‑flip spikes.
- **Profiles**: save, load, and swap tuning presets instantly.
- **Visualizers & debug overlay**: see stick and trigger input behavior in real time.
- **Scrollable UI**: full window content sits in a scroll area; works on small displays.

> All changes in recent releases are **add‑only**. Nothing was removed; defaults remain safe.

---

## 🚀 Quick Start (Run from Source)
**Requirements**
- Windows 10/11
- Python **3.11+**
- `pip install -r requirements.txt` (PyQt6 and any listed deps)

**Run**
```powershell
py .\input_refiner_pyqt6_stable_patched_ultrasens.py
**First steps**
1. Set **Target window contains** to match your game window title.
2. Toggle **Enable Cover Guard** in the Cover Guard panel.
3. Press **Apply (soft restart)** to activate changes.
4. (Optional) **Save Config** to persist defaults.

---

## 🎯 Recommended Settings (Gears of War Reloaded)
Start here and tweak to taste:
- `cover_guard_ms`: **180–220**
- `cover_release_ms`: **100–150**
- `cover_scale`: **0.85–0.90**
- `cover_extra_clamp`: **2**
- `cover_snap_max_px`: **5–6**
- `cover_gate_norm`: **0.10–0.12**
- `cover_decay_ms`: **180–220**
- Keep `dir_flip_guard = True`, `micro_slew_cap_pixels = 2–3`

**Tip:** If the camera still tugs on snap‑in, lower `cover_snap_max_px` by 1 or shorten `cover_guard_ms` ~20ms.

---

## 🧰 Features (Detail)
### Cover Guard
- Detects your **cover button** (default: `A`) and engages a short stabilization window.
- Temporarily **scales sensitivity** and **tightens per‑tick clamps** to stop spikes.

### Cover+ (Advanced)
- **Decay clamp**: extra ceiling fades over time after the snap.
- **Near‑center gate**: tighter control when stick magnitude is tiny.
- **Yank dampener**: damps sudden jumps around center.
- **ADS exemption**: optionally disables the extra clamp while ADS is held.

### Micro‑Jolt / Slew / Shaping
- Guard against sub‑pixel jitters and abrupt sign flips.
- Curve controls (base/ADS) for precise feel.

### Profiles
- Save, Load, Delete named presets.
- Defaults are stored in a human‑readable JSON file.

---

## 🛠️ Build a Standalone EXE (Optional)
1. Install PyInstaller:  
   ```powershell
   pip install pyinstaller
   ```
2. Build:
   ```powershell
   pyinstaller -F -w -i "\XirRx.ico" -n XirRx ".\input_refiner_pyqt6_stable_patched_ultrasens.py"
   ```
   Replace the icon path with any `.ico` you prefer.

**Where’s the EXE?** `./dist/XirRx.exe`

---

## 🔧 Troubleshooting
- **Apply doesn’t change anything**: make sure you’re editing the staged values and pressing **Apply (soft restart)**, not just Save.
- **No controller input**: confirm Windows sees your pad; close other input mappers that might capture XInput.
- **Guard feels too heavy in cover**: raise `cover_scale` toward 0.90; shorten `cover_decay_ms` and/or `cover_guard_ms`.
- **Micro‑aim feels sticky**: lower `cover_gate_norm` slightly (e.g., 0.08), or reduce `cover_extra_clamp` by 1.
- **Only want it active on the game**: ensure **Only when target window focused** is enabled and the title substring matches.

---

## 🙏 Credits & Disclaimer
- Built with **PyQt6** and Windows **SendInput**.
- This tool adjusts input shaping on your PC; it doesn’t modify game files or memory.
- Tune responsibly and respect game ToS.

---

## 🔗 Changelog
See **[CHANGELOG.md](CHANGELOG.md)** for a detailed list of changes.
