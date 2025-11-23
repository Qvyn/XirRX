# Changelog
All notable changes to this project will be documented in this file. ONLY FOR INPUTRX 

## [1.6.0] - 2025-09-28
### Added
- **Cover Guard** to prevent camera yanks when entering/exiting cover in *Gears of War Reloaded*.
  - Config fields: `cover_guard_enabled`, `cover_button`, `cover_guard_ms`, `cover_release_ms`, `cover_scale`, `cover_extra_clamp`, `cover_extra_slew`.
  - UI: dedicated **Cover Guard** panel with sliders/toggles and a **Cover+ (advanced)** sub‑section.
- **Cover+ (advanced anti‑yank)** decay clamp:
  - Dynamic per‑tick ceiling that **decays over time** after cover engage.
  - **Near‑center gate** for tighter control at tiny stick magnitudes.
  - **Simple yank dampener** when spikes are detected near center.
  - Optional `cover_ads_exempt` (skip extra clamp while ADS is active).
  - Extra config fields: `cover_snap_max_px`, `cover_gate_norm`, `cover_decay_ms`, `cover_ads_exempt`.
- **Scrollable UI**: entire main window content is wrapped in a `QScrollArea` with as‑needed scrollbars.
- **Scalable visualizers**: improved `QSizePolicy` for visualizer widgets to resize more gracefully.

### Changed
- **Window minimum width** lowered from 1320 → **980** to make scroll behavior usable on smaller displays.
- UI wiring uses `_stage(...)` to save all new Cover/Cover+ values into the staged config and profiles with no changes to existing features.

### Fixed
- Resolved early **NameError** on XInput flags by ensuring `_BUTTON_NAME_TO_FLAG` is declared *after* constants.
- Fixed `left` layout reference error when adding the Cover Guard box.
- Added missing UI helpers (`checkbox_row`, `combo_row`) to avoid `NameError` on startup.
- Corrected apply/save path so **Apply (soft restart)** updates the worker without auto‑loading a profile.

### Notes
- This release is **add‑only**: no removals or regressions intended. Existing behavior, profiles, and tabs remain intact.
- Recommended starting values for Gears of War: Reloaded:
  - `cover_guard_ms`: 180–220
  - `cover_release_ms`: 100–150
  - `cover_scale`: 0.85–0.90
  - `cover_extra_clamp`: 2
  - `cover_snap_max_px`: 5–6
  - `cover_gate_norm`: 0.10–0.12
  - `cover_decay_ms`: 180–220
  - Keep `dir_flip_guard = True`, `micro_slew_cap_pixels = 2–3`

### Upgrade Guide
1. Replace your script with `input_refiner_pyqt6_stable_patched_ultrasens_coverguard_PLUS_scrollable.py` (or the latest unified file).
2. Launch the app, verify **Target window contains** for the game title, and toggle **Enable Cover Guard** in the new panel.
3. Tune the Cover/Cover+ values as needed, press **Apply (soft restart)** to activate, and `Save Config` when satisfied.
4. (Optional) Rebuild your EXE with a custom icon (`.ico`).

---

## [3.5.5] - 2025-09-26
### Fixed
- Right‑stick not moving mouse in TPS mode after merge: restored mapping without removing other features.
- Soft‑restart now respects staged values and no longer reloads defaults on Apply.

## [3.5.0] - 2025-09-23
### Added
- Profiles (Save/Load/Delete), micro‑jolt guard, slew caps, and shaping controls.
- Basic visualizers and debug overlay.

