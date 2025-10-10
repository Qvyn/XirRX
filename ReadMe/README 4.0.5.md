# XirRx

XirRx is a lightweight Windows toolkit that brings three things together:

- **CrossXir** – a clean, adjustable crosshair overlay that stays on top of your games.
- **InputRX** – input tuning so your mouse/controller feels just right.
- **UWP Launch** – add and launch **UWP (Microsoft Store/Xbox)** games with per‑title flags, wait time, **process priority**, and **CPU affinity**; also creates desktop shortcuts that launch straight into your chosen profile.

---

## Requirements

- Windows 10 **2004+** or Windows 11  
- No installer; just run `XirRx.exe`  
- Some AV tools warn on unsigned/new apps. If you trust the source, choose **Run anyway** (false positive).

---

## Quick Start (≈2 minutes)

1. Launch `XirRx.exe`.
2. Tabs available:
   - **InputRX** – start/stop input tuning.
   - **CrossXir** – show/hide the crosshair overlay.
   - **UWP Launch** – add and launch Microsoft Store/Xbox apps with advanced options.
   - **Streamer** – hides the overlay from captures while *you* still see it.
3. Use the **system tray icon** for quick toggles and game shortcuts you create.

---

## UWP Launch (Microsoft Store/Xbox apps)

Add a game once, then launch it with your runtime tweaks every time.

### Add a game
1. Open **UWP Launch** → **Add**.
2. Pick an installed app from the drop‑down or paste an **AUMID** manually.
3. Options:
   - **Arguments** – flags passed to the app (e.g., `-dx12`, `-nomovie`).
   - **Target EXE** – exact process name to match (improves detection).
   - **Wait (s)** – time to wait before applying tweaks (lets child processes spawn).
   - **Priority** – Normal / Above Normal / High / Realtime (careful).
   - **Affinity** – **Auto** (all but CPU0) or hex mask (e.g., `0xFE`).
4. Click **LAUNCH**.

### What happens
- XirRx activates the UWP app (COM activation with a shell fallback).
- Waits up to **Wait (s)** for the target.
- Applies **priority** and **affinity** to the matching process (logged in the tab).

### Desktop shortcut (.lnk)
- Select the game → **Create Desktop Shortcut (.lnk)**.
- The shortcut runs `XirRx.exe --run "<Game Name>"` and applies your profile automatically.

---

## Steam Validation (optional, for titles that require it) — **Updated 2025-10-10**

Some games (e.g., Skate.,anti‑cheat protected games..) must be validated in Steam before every launch.

- Set the game’s **Steam AppID** in its entry.
- Click **Validate via Steam** (or enable per‑title validation if you expose that option).
- XirRx will:
  1) open `steam://validate/<AppID>`  
  2) **watch Steam’s window title** for completion (no log parsing)  
     - recognizes: **“Validating”**, **“Verifying”**, **“Updating”**  
     - once one of those appears at least once **and then disappears for ~5s**, validation is considered finished  
  3) **auto‑launch** the game with your selected flags (priority/affinity) as soon as validation completes
- **Fallback:** if Steam never shows those words (localization/skin), XirRx waits a short fallback period (defaults to ~60s) and then proceeds so you aren’t stuck.

> Tip: If your Steam client is in another language, update the keyword list in `steam_validate_and_wait()` with the exact word your client shows.

---

## Streamer Mode

- **ON**: Overlay is **hidden from captures** (screenshots/screen recording/OBS), but **you** still see it.
- **OFF**: Overlay behaves normally.

*Tips*: In OBS, prefer **Display Capture** or avoid capturing the overlay window directly.

---

## Tray Menu

Right‑click the tray icon to:
- Start/Stop **InputRX**
- Show/Hide **CrossXir**
- Toggle **Streamer Mode**
- Launch any UWP titles you’ve added

---

## FAQ

**The crosshair doesn’t show on stream but I see it.**  
Streamer Mode is ON. Turn it OFF if you want viewers to see the overlay.

**UWP tweaks didn’t apply.**  
Increase **Wait (s)** or set **Target EXE** exactly (e.g., `GearsOfWar.exe`).

**Steam finishes validating but nothing launches.**  
This release switches to a **window‑title watcher** and adds a **fallback wait**. If your Steam uses different wording than “Validating/Verifying/Updating,” add your localized word to the keywords list.

**Antivirus flagged the EXE.**  
New unsigned utilities can trigger warnings. If you trust the source, allow it (false positive).

---

## Notes & Troubleshooting

- UWP titles may need a longer **Wait (s)**.
- **Auto affinity** = all logical CPUs except CPU0.
- Closing XirRx stops all workers/overlays (no background services).
- Steam validation no longer depends on reading log files; it’s UI‑based with a safe fallback.

---

## Changelog (high level)

### 
- **Added:** auto‑launch immediately after Steam validation succeeds.
- **Changed:** replaced log parsing with **window‑title watcher** (recognizes “Validating/Verifying/Updating”).
- **Added:** **fallback wait** so validation never leaves you stuck if titles don’t appear.
- **Fixed:** prior condition where validation completed but the launcher didn’t proceed.

---

## Privacy

- XirRx does **not** upload data.
- Streamer Mode only changes how Windows captures the overlay window.
