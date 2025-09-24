# Channel Log – Apply/Profiles Reliability Fixes
**Date:** 2025-09-24 16:58 

## TL;DR
- **Apply no longer touches profiles.** It only pushes staged → runtime, signals the worker, and updates the UI.
- Fixed crashes and missing handlers from earlier patches.
- Kept all features/settings intact. Final build used: **`input_refiner_pyqt6_stable_patched_ultrasens
---
## Fixed 

### 1) Apply should not load/save profiles
- Removed the implicit profile save on Apply (`save_profile(...)`), so Apply **does not** create/overwrite profile files.
- Apply now simply:
  1. Copies **staged → runtime**
  2. `applyConfig.emit(...)` to the worker
  3. Soft restart signal (if present in your file)
  4. Updates the “Applied” label

**Result:** pressing **Apply** immediately takes effect without reloading or switching profiles.

### 2) Clear feedback without a status bar
-  `MainWindow` didn’t expose `statusBar()`. Removed the status-bar call to avoid the crash and updated the existing label text to:
  - **“Applied ✓ — no profile load”**

**Result:** no crash; explicit confirmation that Apply didn’t touch profiles.

### 3) Save button handler restored
- Reintroduced `_save_only()` and ensured it’s **inside** `MainWindow`.
- This resolves `AttributeError: 'MainWindow' object has no attribute '_save_only'` when clicking **Save**.

**Result:** the **Save** button works again and only writes the staged config to disk (no auto-apply).

---

## How to verify (quick)
1. Launch the file.
2. Ensure **Enabled** is on; uncheck **Only when focused** while testing on desktop.
3. Change a slider; press **Apply**.
4. Confirm:
   - Label shows **“Applied ✓ — no profile load.”**
   - Sens/dx/dy react immediately when you move the stick (or when your target window is focused, if gating is on).

---

## Notes & optional (deferred) improvements
- **Queued Apply → worker:** We can also wire `applyConfig` **directly to `worker.apply_config` with a `QueuedConnection`** inside `WorkerManager.start()` for extra determinism on some systems.  

- **Profiles usage:** Profiles remain manual: they’re only saved via **Save** and only loaded when you explicitly pick one. Apply doesn’t change profiles.

---

## Rollback
If you need to revert, keep your older file alongside and run that instead. No global changes were made; these were single‑file drop‑ins.

---

## Known runtime issues (unchanged behavior)
- **Focus gating:** If “Only when focused” is enabled and the active window title doesn’t match your target string, output is intentionally suppressed (it can look like Apply didn’t work). Test with gating **off** on desktop.
- **Controller hot‑swap:** Brief “not detected” periods can delay visible movement by a tick; your Apply still took, you’ll feel it once inputs resume.

