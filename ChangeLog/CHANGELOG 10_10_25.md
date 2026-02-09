# Changelog — Universal UWP Launcher

All notable changes to this project are documented here, following a simplified
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) style.

## [2025-10-10] CLEAN_FIXED5_SURGICAL2

### Added
- **Auto-launch after validation:** When “Validate via Steam” succeeds, the launcher immediately
  starts the selected game using your existing flags (priority/affinity, etc.).

### Changed
- **Validation logic (no logs):** Replaced log-parsing with a **window-title watcher**. The
  launcher now opens `steam://validate/<AppID>` and monitors Steam’s title for completion.
  - Recognizes any of: **“Validating”**, **“Verifying”**, **“Updating.”**
  - If none of those ever appear (localized clients/skins), a **fallback wait** (~60s) triggers
    and the launcher proceeds.

### Fixed
- **Validation hang:** Issue where Steam finished but the launcher never advanced to launch.
  The new watcher + fallback guarantees forward progress.
- **NameError/undefined helper race:** Ensured the helper used by the validator is available
  during runtime.
- **Stray return scope:** Prior top-level `return` that caused
  `SyntaxError: 'return' outside function` (from an earlier CLEAN build) is resolved.

### Not Changed (by design)
- No UI redesigns or feature removals.
- Existing launch path, flags, priority/affinity flow untouched.
- Game list, shortcut creation, and settings storage unchanged.

### Notes
- **Localization:** If your Steam shows a different word during validation, add it to the
  `keywords` tuple in `steam_validate_and_wait()` (single-line edit).
- **Fallback timing:** The default fallback wait is **60s**. Adjust `fallback_wait_s` in
  `steam_validate_and_wait()` if your validation typically takes longer/shorter.
- **No log dependency:** Improves reliability across machines (no permissions/path issues,
  no stale matches).

### Known Limits
- If Steam keeps a generic title that never reflects validation state *and* validation exceeds
  the fallback window, the launcher will proceed once the fallback period ends.

---

## [Earlier Builds]
- Historical notes available on request.
