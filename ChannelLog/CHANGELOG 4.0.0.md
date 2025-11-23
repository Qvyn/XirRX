# Changelog

## [4.0.0] – 2025-10-05

### Added
- **UWP Launch** tab integrated into the suite (no external tools needed):
  - AUMID picker (with manual AUMID support).
  - Per-title **Arguments**, **Target EXE**, **Wait (s)**.
  - Per-title **Priority** (Normal / Above Normal / High / Realtime) and **CPU Affinity**:
    - **Auto** = all logical CPUs except CPU0.
    - Hex mask (e.g., `0xFE`) when Auto is off.
  - **Desktop Shortcut (.lnk)** generation that launches XirRx with `--run "<Game Name>"` to apply profile automatically.
  - COM activation with **shell fallback** (`explorer.exe shell:AppsFolder\<AUMID>`), plus verbose logs (PID detection, process matching).
- **Tray menu**: quick toggles for InputRX, CrossXir, Streamer Mode, and shortcuts to added UWP titles.
- **Windowed build** (no console window) via new `build_XirRx_WINDOWED.bat`.
- **Builder with launcher integration**: `launcher.py` bundled along with `comtypes` and `psutil`.

### Changed
- **Suite integration**: UWP Launch is a first-class tab, wired like InputRX and CrossXir (no removal of existing features).
- **Logging**: clearer lifecycle messages (activation, wait period, target detection, priority/affinity apply results).
- **Defaults**: sensible initial **Wait (s)** / **Priority** preserved; easy override per-game or globally.

### Fixed
- Streamer tab wiring restored so the **Streamer** button switches correctly.
- Sidebar navigation: consistent button checking/highlighting when switching to **UWP Launch**.
- Indentation and naming mismatches in Suite methods (e.g., `launcherTab` vs `launchTab`) to prevent runtime errors.
- Shortcut creation script quoting to handle paths with spaces.

### Removed
- Nothing. All prior tabs and behaviors remain.

### Notes / Upgrade Tips
- If a UWP title spawns multiple processes, consider setting **Target EXE** to the final game executable and increasing **Wait (s)**.
- Some AV tools may warn on unsigned binaries; this is a common false positive for new utilities.
- For OBS, **Streamer Mode** hides the overlay from capture while you still see it; turn it off if you want viewers to see the crosshair.

