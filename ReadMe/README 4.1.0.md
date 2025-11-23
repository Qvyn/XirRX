# 🎮 Universal UWP / Steam Launcher
**Version:** 1.4 (Installed-Only Sync Build)   
**Release Date:** October 12, 2025  

---

## 🔰 What This App Does
This launcher lets you manage and launch **Steam**, **UWP**, and **custom games** from one place.  
You can:
- **Sign into Steam** to view your installed games.
- **Sync your Steam library** automatically.
- **Launch or validate** games through Steam.
- **Save your preferences** (like wait times and priorities).
- Use it completely offline after setup.

It’s a single-window, dark-themed launcher built for convenience and reliability.

---

## 🧩 Key Features
### 🔑 Steam Sign-In
- Click **“Sign into Steam”** and log in securely via Steam’s OpenID page.  
- Once signed in, your SteamID64 is saved automatically.  
- No credentials are stored — only your SteamID is used to read your library.

### 🧰 Steam API Key Setup
- Click **Settings…** in the top-right corner.  
- Paste your [Steam Web API Key](https://steamcommunity.com/dev/apikey).  

### 🎯 Sync Installed Games
- Click **Sync Steam Library** to import your **installed** Steam games.  
- The launcher reads your Steam folders (`libraryfolders.vdf`, `appmanifest_*.acf`) and skips anything not installed.  
- Re-sync anytime to refresh your list.

### 🗑️ Safe Game Removal
- Removing a game **only deletes it from the launcher list** — it does **not uninstall** or affect your Steam account.  
- Run **Sync Steam Library** again to restore missing titles.

### 🧠 Save Defaults
- Adjust your **Default Wait Time** and **Priority** options.  
- Click **Save Defaults** to remember your preferences.  
- Defaults apply automatically to new game entries.

---

## ⚙️ Settings & Storage
| Mode | Description |
|------|--------------|
| **AppData Mode (Default)** | Settings are saved in `%APPDATA%\UniversalUWPLauncher\settings.json`. |
| **Portable Mode** | If a `settings.json` file exists beside the `.py` launcher, it will use that instead. |

So if you want a **portable launcher**, just keep a copy of `settings.json` next to the `.py` file.  
If not, you can safely delete it — the app will handle everything in AppData automatically.

---

## 🧭 Quick Start
1. **Run** the launcher (`launcher_SETTINGS_INSTALLED_ONLY_FIXED4.py` or packaged `.exe`).
2. Click **Settings…** → paste your Steam API key → press OK.
3. Click **Sign into Steam** and wait for confirmation.
4. Click **Sync Steam Library** — installed games appear in the list.
5. Double-click or press **Launch** to start a game.

> 💡 To validate game files, use **Validate via Steam** — it runs Steam’s native validation and auto-launches the game when done.

---

## 🧩 Interface Guide
| Section | Purpose |
|----------|----------|
| **Left Pane** | Your current game list (installed or added manually). |
| **Right Pane** | Game details, launch options, log messages. |
| **Bottom Bar** | Buttons for Steam login, syncing, validation, settings, and shortcuts. |

**Color Codes:**
- `[✓]` Success  
- `[!]` Warning  
- `[x]` Error  
- `[i]` Info  

---

## 🧱 Technical Notes
- Built with **Python 3.11** and **PyQt5**.  
- Uses **Steam OpenID** for authentication.  
- Compatible with both `.py` and compiled `.exe` builds.  
- Runs on **Windows 10 / 11**.

---

## 🛠️ Troubleshooting
| Issue | Solution |
|--------|-----------|
| “Add API Key to settings.json” | Open **Settings…** and enter your Steam API key. |
| No games show after sync | Ensure you have games installed — this build imports *installed-only* titles. |
| Removed a game by mistake | Click **Sync Steam Library** to restore it. |
| “Failed to sign into Steam” | Retry login; Steam’s OpenID may have timed out. |

---

## 🏁 Credits  
**Design:** Dark Fusion UI  
**Project:** Universal UWP / Steam Launcher  

---

## 🌟 Future Plans
- Option to “Import all Steam games” (not just installed ones).  
- Multi-platform library sync (Epic, GOG, EA App).  
- Built-in repair tool for broken manifests.  

---

**Enjoy your games — faster, cleaner, and all in one place.**
