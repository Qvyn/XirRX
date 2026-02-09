# Universal UWP Game Launcher (single file)
# Launches UWP apps by AUMID via IApplicationActivationManager, passes arguments,
# then applies per-title CPU affinity and process priority. Includes a simple UI
# to add/edit titles and optionally create a desktop .lnk that calls this script.

import os, sys, json, time, subprocess, ctypes, platform, traceback
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen, Request
import threading, socket

# Third-party deps (install: pip install PyQt6 psutil comtypes)
try:
    import psutil
    import comtypes
    import comtypes.client as cc
    from comtypes import GUID, HRESULT, IUnknown, COMMETHOD
    from ctypes import wintypes
except ImportError as e:
    print("Missing dependency:", e)
    print("Install with: pip install PyQt6 psutil comtypes")
    sys.exit(1)

# Qt
from PyQt6 import QtWidgets, QtCore, QtGui

# --- Platform guard ---
if platform.system() != "Windows":
    print("This tool requires Windows.")
    sys.exit(1)

# ===== Win32 / COM constants =====
# Priority classes
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS         = 0x00000080
NORMAL_PRIORITY_CLASS       = 0x00000020
REALTIME_PRIORITY_CLASS     = 0x00000100
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

PRIORITY_MAP = {
    "Normal": NORMAL_PRIORITY_CLASS,
    "Above Normal": ABOVE_NORMAL_PRIORITY_CLASS,
    "High": HIGH_PRIORITY_CLASS,
    "Realtime (careful)": REALTIME_PRIORITY_CLASS,
    "Below Normal": BELOW_NORMAL_PRIORITY_CLASS
}

# IApplicationActivationManager
CLSID_ApplicationActivationManager = GUID("{45BA127D-10A8-46EA-8AB7-56EA9078943C}")
IID_IApplicationActivationManager  = GUID("{2E941141-7F97-4756-BA1D-9DECDE894A3D}")

# ActivateOptions
AO_NONE            = 0x0
AO_NOERRORUI       = 0x1
AO_NOSPLASHSCREEN  = 0x2

kernel32 = ctypes.windll.kernel32
user32   = ctypes.windll.user32
ASFW_ANY = -1  # AllowSetForegroundWindow

# ----- COM interface definition -----
class IApplicationActivationManager(IUnknown):
    _iid_ = IID_IApplicationActivationManager
    _methods_ = [
        COMMETHOD(
            [], HRESULT, 'ActivateApplication',
            (['in'],  ctypes.c_wchar_p, 'appUserModelId'),
            (['in'],  ctypes.c_wchar_p, 'arguments'),
            (['in'],  ctypes.c_uint,    'options'),
            (['out'], ctypes.POINTER(wintypes.DWORD), 'processId')
        ),
        # Stubs (unused but keep vtable layout)
        COMMETHOD([], HRESULT, 'ActivateForFile',
                  (['in'], ctypes.c_void_p, 'itemArray'),
                  (['in'], ctypes.c_wchar_p, 'verb'),
                  (['out'], ctypes.POINTER(wintypes.DWORD), 'processId')),
        COMMETHOD([], HRESULT, 'ActivateForProtocol',
                  (['in'], ctypes.c_void_p, 'itemArray'),
                  (['in'], ctypes.c_wchar_p, 'verb'),
                  (['out'], ctypes.POINTER(wintypes.DWORD), 'processId')),
    ]

def _create_activation_manager() -> IApplicationActivationManager:
    # Initialize COM and allow foreground
    comtypes.CoInitialize()
    user32.AllowSetForegroundWindow(ASFW_ANY)
    # Create the COM object (Local Server context)
    return cc.CreateObject(
        CLSID_ApplicationActivationManager,
        interface=IApplicationActivationManager,
        clsctx=comtypes.CLSCTX_LOCAL_SERVER
    )

# ===== Helpers =====
# ===== Steam Validation Helpers =====
def _get_steam_root() -> Optional[Path]:
    """Locate Steam root via registry or defaults."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            val, _ = winreg.QueryValueEx(k, "SteamPath")
            if val:
                p = Path(val)
                return p if p.exists() else None
    except Exception:
        pass
    # common default
    for guess in [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]:
        if guess.exists():
            return guess
    return None

def _steam_content_log_path() -> Optional[Path]:
    root = _get_steam_root()
    if not root:
        return None
    log = root / "logs" / "content_log.txt"
    return log if log.exists() else log  # return path anyway; it may be created on first write

def _open_steam_url(url: str) -> bool:
    """Open a steam:// URL without blocking."""
    try:
        # os.startfile supports protocol handlers on Windows
        os.startfile(url)
        return True
    except Exception:
        try:
            subprocess.Popen(['cmd', '/c', 'start', '', url], creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except Exception:
            return False



# ===== Steam OpenID Login (for launcher auth) =====
def _find_free_port(start=34123, end=34223):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
            try:
                so.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None

def _verify_openid_with_steam(params: Dict[str, Any]) -> bool:
    verify_params = params.copy()
    verify_params['openid.mode'] = 'check_authentication'
    data = urlencode(verify_params).encode('utf-8')
    try:
        req = Request("https://steamcommunity.com/openid/login", data=data, method="POST")
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            return 'is_valid:true' in body
    except Exception:
        return False

def steam_openid_login(timeout=180) -> Optional[str]:
    port = _find_free_port()
    if not port:
        return None
    result = {"steamid": None}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                q = urlparse(self.path)
                if q.path != "/callback":
                    self.send_response(404); self.end_headers(); return
                params = {k: v[0] for k, v in parse_qs(q.query).items()}
                ok = _verify_openid_with_steam(params)
                claimed = params.get("openid.claimed_id","")
                steamid = ""
                if claimed and claimed.rsplit("/", 1)[-1].isdigit():
                    steamid = claimed.rsplit("/", 1)[-1]
                if ok and steamid:
                    result["steamid"] = steamid
                    body = f"<html><body><h3>Login successful. You can close this window.</h3><p>SteamID: {steamid}</p></body></html>".encode("utf-8")
                else:
                    body = b"<html><body><h3>Login failed or canceled. Please close this window.</h3></body></html>"
                self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(body)
                done.set()
            except Exception:
                try:
                    self.send_response(500); self.end_headers()
                except Exception:
                    pass
                done.set()
        def log_message(self, format, *args): 
            return

    httpd = HTTPServer(("127.0.0.1", port), Handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()

    realm = f"http://127.0.0.1:{port}"
    return_to = f"{realm}/callback"
    openid_params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    url = "https://steamcommunity.com/openid/login?" + urlencode(openid_params)
    webbrowser.open(url)

    if not done.wait(timeout):
        try: httpd.shutdown()
        except Exception: pass
        return None
    try: httpd.shutdown()
    except Exception: pass
    return result["steamid"]

def sync_steam_library(steamid: str, api_key: Optional[str]) -> Tuple[bool, str, Optional[dict]]:
    if not steamid or not steamid.isdigit():
        return (False, "No valid SteamID.", None)
    if not api_key:
        return (False, "No Steam Web API key set. Add one to Settings to sync full library.", None)
    try:
        qs = urlencode({"key": api_key, "steamid": steamid, "include_appinfo": 1, "include_played_free_games": 1})
        url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?" + qs
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme for Steam API: {parsed.scheme}")
        with urlopen(url, timeout=15) as resp:  # nosec B310 - url is constructed with a fixed https base and validated scheme
            import json as _json
            data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
            return (True, f"Fetched {len(data.get('response',{}).get('games', []))} games.", data)
    except Exception as e:
        return (False, f"Failed to fetch library: {e}", None)
def steam_validate_and_wait(appid: str, timeout_s: int = 1800, poll_interval: float = 1.0, fallback_wait_s: int = 60):
    """
    Trigger Steam validation (steam://validate/<appid>) and wait until it's *likely* done.
    Priority 1: watch Steam window titles for any of: 'Validating', 'Verifying', 'Updating'.
                Once seen at least once and then absent for ~5s, consider it finished.
    Priority 2: if we never see those titles at all, fall back to a fixed wait (`fallback_wait_s`).
    No log parsing. No file I/O.
    """
    appid = str(appid).strip()
    if not appid.isdigit():
        return False, f"[x] Invalid Steam AppID: {appid}"

    _open_steam_url(f"steam://validate/{appid}")

    import time
    start_ts = time.time()
    last_seen = 0.0
    seen_any = False
    grace_after_hide = 5.0
    keywords = ("Validating", "Verifying", "Updating")

    while (time.time() - start_ts) < timeout_s:
        try:
            if any(_steam_window_title_has(k) for k in keywords):
                seen_any = True
                last_seen = time.time()
        except Exception:
            pass

        if seen_any and (time.time() - last_seen) >= grace_after_hide:
            return True, f"[✓] Steam validation finished for AppID {appid}."

        # Fallback path: never saw a 'validating' kind of title at all — just wait out a short window
        if (not seen_any) and (time.time() - start_ts) >= fallback_wait_s:
            return True, f"[~] Proceeding after fallback wait ({fallback_wait_s}s) for AppID {appid}."

        time.sleep(poll_interval)

    return False, f"[!] Timed out waiting for Steam validation of AppID {appid} after {timeout_s}s."
def set_priority_and_affinity(pid: int, priority_const: int, mask: Optional[int]) -> Tuple[bool, str]:
    """Apply priority and optional CPU affinity to a process."""
    try:
        PROCESS_SET_INFORMATION = 0x0200
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_SET_AFFINITY = 0x0100
        desired = PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_AFFINITY
        handle = kernel32.OpenProcess(desired, False, pid)
        if not handle:
            return False, f"OpenProcess failed (PID {pid}). Try running as Administrator."

        if not kernel32.SetPriorityClass(handle, priority_const):
            kernel32.CloseHandle(handle)
            return False, f"SetPriorityClass failed for PID {pid}. Try Admin."

        if mask is not None:
            pmask = ctypes.c_size_t(mask)
            if not kernel32.SetProcessAffinityMask(handle, pmask):
                kernel32.CloseHandle(handle)
                return False, f"SetProcessAffinityMask failed for PID {pid}. Mask=0x{mask:X}. Try Admin."

        kernel32.CloseHandle(handle)
        return True, "Applied priority{}.".format(" + affinity" if mask is not None else "")
    except Exception as e:
        return False, f"Win32 error: {e}"

def cpu_count_logical() -> int:
    return os.cpu_count() or 8

def mask_all_but_cpu0() -> int:
    n = cpu_count_logical()
    return ((1 << n) - 1) & ~0x1 if n > 1 else 1

def parse_hex_mask(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    if s.lower().startswith("0x"):
        s = s[2:]
    try:
        val = int(s, 16)
        return val if val > 0 else None
    except ValueError:
        return None

# ===== Storage =====
APPDATA_DIR = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "UniversalUWPLauncher"
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_SETTINGS = SCRIPT_DIR / "settings.json"
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
GAMES_PATH = APPDATA_DIR / "games.json"
SETTINGS_PATH = LOCAL_SETTINGS if LOCAL_SETTINGS.exists() else (APPDATA_DIR / "settings.json")

DEFAULT_SETTINGS = {
    "default_wait": 45,
    "default_priority": "High",
}

def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")

def load_games() -> Dict[str, Any]:
    data = _read_json(GAMES_PATH, {"games": []})
    if not isinstance(data.get("games"), list):
        data["games"] = []
    return data

def save_games(data: Dict[str, Any]) -> None:
    _write_json(GAMES_PATH, data)

def load_settings() -> Dict[str, Any]:
    # Load settings, tolerating corrupted / unexpected JSON by falling back to defaults.
    raw = _read_json(SETTINGS_PATH, DEFAULT_SETTINGS.copy())
    if not isinstance(raw, dict):
        raw = {}
    # Start from defaults, then overlay anything the user has stored.
    s: Dict[str, Any] = DEFAULT_SETTINGS.copy()
    s.update(raw)
    return s

def save_settings(s: Dict[str, Any]) -> None:
    _write_json(SETTINGS_PATH, s)

# ===== UWP discovery via PowerShell =====
def list_uwp_apps() -> List[Tuple[str, str]]:
    """Return (Name, AppID) using PowerShell Get-StartApps."""
    try:
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Depth 2"
        ]
        out = subprocess.check_output(cmd, creationflags=subprocess.CREATE_NO_WINDOW).decode("utf-8", errors="ignore").strip()
        if not out:
            return []
        data = json.loads(out)
        items = data if isinstance(data, list) else [data]
        apps = [(it.get("Name",""), it.get("AppID","")) for it in items if it and it.get("Name") and it.get("AppID")]
        apps.sort(key=lambda x: x[0].lower())
        return apps
    except Exception:
        return []

# ===== Desktop shortcut helper (optional) =====
def make_windows_shortcut(target_exe: str, args: str, out_path: Path, icon_path: Optional[str] = None) -> Tuple[bool, str]:
    try:
        out_path = out_path.with_suffix(".lnk")
        out_esc   = str(out_path).replace("'", "''")
        tgt_esc   = target_exe.replace("'", "''")
        args_esc  = args.replace("'", "''")
        workdir   = str(Path(target_exe).parent).replace("'", "''")

        ps  = "$WshShell = New-Object -ComObject WScript.Shell\n"
        ps += "$Shortcut = $WshShell.CreateShortcut('{}')\n".format(out_esc)
        ps += "$Shortcut.TargetPath = '{}'\n".format(tgt_esc)
        ps += "$Shortcut.Arguments  = '{}'\n".format(args_esc)
        ps += "$Shortcut.WorkingDirectory = '{}'\n".format(workdir)
        if icon_path:
            ps += "$Shortcut.IconLocation = '{}'\n".format(icon_path.replace("'", "''"))
        ps += "$Shortcut.Save()\n"

        subprocess.check_call(["powershell","-NoProfile","-ExecutionPolicy","Bypass", ps],
                              creationflags=subprocess.CREATE_NO_WINDOW)
        return True, str(out_path)
    except subprocess.CalledProcessError as e:
        return False, f"PowerShell failed: {e}"
    except Exception as e:
        return False, f"Shortcut error: {e}"

def this_python_executable() -> str:
    return sys.executable

# ===== Worker: Activate + tune =====
class LaunchWorker(QtCore.QThread):
    log_signal  = QtCore.pyqtSignal(str, str)
    done_signal = QtCore.pyqtSignal(bool, str)

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__()
        self.cfg = cfg

    def log(self, msg: str, level: str = "info"):
        self.log_signal.emit(level, msg)

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            self.log("ERROR: " + "".join(traceback.format_exception(e)), "error")
            self.done_signal.emit(False, str(e))

    def _run_impl(self):
        # Optional: Steam validation
        validate_only = bool(self.cfg.get("validate_only", False))
        appid = str(self.cfg.get("steam_appid", "") or "").strip()
        if (validate_only or bool(self.cfg.get("validate_steam", False))) and appid.isdigit():
            timeout_s = int(self.cfg.get("validate_timeout", 900) or 900)
            ok, msg = steam_validate_and_wait(appid, timeout_s=timeout_s)
            self.log(msg, "info" if ok else "warn")
            if validate_only:
                self.done_signal.emit(ok, msg)
                return

        aumid = (self.cfg.get("aumid") or "").strip()
        if not aumid:
            self.done_signal.emit(False, "Missing AUMID")
            return

        args = (self.cfg.get("flags") or "").strip()
        exe_name = (self.cfg.get("exe_name") or "").strip()
        wait_s = int(self.cfg.get("wait_seconds") or 45)
        priority_choice = self.cfg.get("priority") or "High"
        priority_const  = PRIORITY_MAP.get(priority_choice, HIGH_PRIORITY_CLASS)

        # Affinity
        affinity_hex = (self.cfg.get("affinity_hex") or "").strip()
        if self.cfg.get("auto_affinity", True) and not affinity_hex:
            mask = mask_all_but_cpu0()
            mask_note = "auto (all but CPU0) 0x{:X}".format(mask)
        else:
            mask = parse_hex_mask(affinity_hex)
            mask_note = "0x{:X}".format(mask) if mask is not None else "None"

        self.log(f"Activate AUMID: {aumid}")
        self.log(f"Args: {args or '(none)'} | EXE: {exe_name or '(auto-detect)'}")
        self.log(f"Wait: {wait_s}s | Priority: {priority_choice} | Affinity: {mask_note}")

        # Snapshot before launch (optimize: store set for O(1) membership)
        before_pids = set(psutil.pids())


        # Activate (AUMID vs protocol URL)
        root_pid = 0
        if "://" in aumid:
            if not _open_steam_url(aumid):
                self.done_signal.emit(False, "Failed to open URL: " + aumid)
                return
            self.log("Activated via URL protocol (no root PID).")
        else:
            aam = _create_activation_manager()
            try:
                result = aam.ActivateApplication(aumid, args, AO_NONE)
                root_pid = int(result[0]) if isinstance(result, tuple) else int(result)
            except comtypes.COMError as e:
                self.done_signal.emit(False, "ActivateApplication failed: HRESULT 0x{:08X}".format(e.hresult & 0xFFFFFFFF))
                return

                self.log(f"Activated, root PID: {root_pid}")

                ignore_substrings = ("explorer", "conhost", "powershell")

                def candidate_children() -> List[int]:
                    # Prefer children of the activation root; fall back to “new since snapshot”
                    out = []
                    try:
                        for c in psutil.Process(root_pid).children(recursive=True):
                            try:
                                nm = (c.name() or "").lower()
                                if all(x not in nm for x in ignore_substrings):
                                    out.append(c.pid)
                            except psutil.Error:
                                pass
                    except psutil.Error:
                        pass
                    if not out:
                        now_set = set(psutil.pids())
                        for pid in now_set - before_pids:
                            try:
                                nm = psutil.Process(pid).name().lower()
                                if all(x not in nm for x in ignore_substrings):
                                    out.append(pid)
                            except psutil.Error:
                                pass
                    return out

                def try_match_by_name(name: str) -> List[int]:
                    if not name:
                        return []
                    name_l = name.lower()
                    out = []
                    # optimize: single pass over processes with cached attrs
                    for p in psutil.process_iter(["pid", "name"]):
                        if (p.info.get("name") or "").lower() == name_l:
                            out.append(p.info["pid"])
                    return out

                # Poll for the game process
                deadline = time.time() + max(5, wait_s)
                target_pids: List[int] = []
                while time.time() < deadline and not target_pids:
                    time.sleep(0.4)  # slightly faster than 0.5s without being busy
                    target_pids = try_match_by_name(exe_name) if exe_name else []
                    if not target_pids:
                        target_pids = candidate_children()

                if not target_pids:
                    self.log(f"Timeout: didn’t see target process within {wait_s}s.", "warn")
                    self.done_signal.emit(False, "Target EXE not found")
                    return

                # Apply tuning
                ok_count = 0
                for pid in target_pids:
                    try:
                        nm = psutil.Process(pid).name()
                        self.log(f"Applying to PID {pid} ({nm}) …")
                        ok, msg = set_priority_and_affinity(pid, priority_const, mask)
                        self.log(("  ✓ " if ok else "  ✗ ") + msg, "ok" if ok else "warn")
                        if ok:
                            ok_count += 1
                    except psutil.NoSuchProcess:
                        self.log(f"PID {pid} vanished.", "warn")
                    except Exception as e:
                        self.log(f"Error on PID {pid}: {e}", "error")

                self.done_signal.emit(ok_count > 0, ("Updated {} process(es)".format(ok_count) if ok_count else "No processes updated"))

# ===== Add/Edit dialog =====
class GameDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings: Dict[str, Any], data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("Add / Edit UWP Game")
        self.resize(600, 410)
        self.settings = settings
        self.data = data or {}

        layout = QtWidgets.QVBoxLayout(self)

        # UWP apps
        row_app = QtWidgets.QHBoxLayout()
        self.app_combo = QtWidgets.QComboBox()
        self.app_combo.addItem("— (manual AUMID) —", "")
        self.btn_refresh = QtWidgets.QPushButton("Refresh UWP Apps")
        self.btn_refresh.clicked.connect(self._load_uwp_list)
        row_app.addWidget(QtWidgets.QLabel("Installed UWP Apps"))
        row_app.addWidget(self.app_combo, 1)
        row_app.addWidget(self.btn_refresh)

        # Form
        form = QtWidgets.QFormLayout()
        self.aumid_edit = QtWidgets.QLineEdit(self.data.get("aumid", ""))
        self.name_edit  = QtWidgets.QLineEdit(self.data.get("name", ""))
        self.name_edit.setPlaceholderText("Display name in launcher")
        self.flags_edit = QtWidgets.QLineEdit(self.data.get("flags", ""))
        self.flags_edit.setPlaceholderText("Arguments passed to the app")
        self.exe_edit   = QtWidgets.QLineEdit(self.data.get("exe_name", ""))
        self.exe_edit.setPlaceholderText("Exact target EXE (optional, improves matching)")

        self.wait_spin  = QtWidgets.QSpinBox(); self.wait_spin.setRange(5, 600); self.wait_spin.setValue(int(self.data.get("wait_seconds", self.settings.get("default_wait", 45))))
        self.prio_combo = QtWidgets.QComboBox(); self.prio_combo.addItems(list(PRIORITY_MAP.keys())); self.prio_combo.setCurrentText(self.data.get("priority", self.settings.get("default_priority", "High")))
        self.auto_aff   = QtWidgets.QCheckBox("Auto affinity (all but CPU0)"); self.auto_aff.setChecked(bool(self.data.get("auto_affinity", True)))
        self.aff_hex    = QtWidgets.QLineEdit(self.data.get("affinity_hex", "")); self.aff_hex.setPlaceholderText("Hex mask (e.g., 0xFE) if not using Auto")

        form.addRow("Display Name", self.name_edit)
        form.addRow("AUMID (AppID)", self.aumid_edit)
        form.addRow("Arguments", self.flags_edit)
        form.addRow("Target EXE", self.exe_edit)
        self.steam_appid_edit = QtWidgets.QLineEdit(self.data.get("steam_appid", ""))
        self.steam_appid_edit.setPlaceholderText("e.g. 123456 (optional)")
        self.validate_cb = QtWidgets.QCheckBox("Validate via Steam before launch")
        self.validate_cb.setChecked(bool(self.data.get("validate_steam", False)))
        self.validate_timeout = QtWidgets.QSpinBox()
        self.validate_timeout.setRange(60, 7200)
        self.validate_timeout.setValue(int(self.data.get("validate_timeout", 900)))
        form.addRow("Steam AppID", self.steam_appid_edit)
        form.addRow("", self.validate_cb)
        form.addRow("Validation timeout (s)", self.validate_timeout)
        form.addRow("Wait (s)", self.wait_spin)
        form.addRow("Priority", self.prio_combo)

        # Affinity row
        aff_row = QtWidgets.QHBoxLayout()
        aff_row.addWidget(self.auto_aff)
        aff_row.addSpacing(10)
        aff_row.addWidget(QtWidgets.QLabel("Affinity (hex)"))
        aff_row.addWidget(self.aff_hex, 1)

        # Buttons
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)

        layout.addLayout(row_app)
        layout.addLayout(form)
        layout.addLayout(aff_row)
        layout.addWidget(btns)

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        self._load_uwp_list()
        if self.aumid_edit.text():
            for i in range(self.app_combo.count()):
                if self.app_combo.itemData(i) == self.aumid_edit.text():
                    self.app_combo.setCurrentIndex(i)
                    break
        self.app_combo.currentIndexChanged.connect(self._combo_changed)

    def _combo_changed(self, idx: int):
        aumid = self.app_combo.itemData(idx)
        name  = self.app_combo.currentText()
        if aumid:
            self.aumid_edit.setText(aumid)
            if not self.name_edit.text().strip():
                self.name_edit.setText(name)

    def _load_uwp_list(self):
        self.app_combo.blockSignals(True)
        while self.app_combo.count() > 1:
            self.app_combo.removeItem(1)
        apps = list_uwp_apps()
        if not apps:
            self.app_combo.addItem("(No apps detected)", "")
        else:
            for nm, aid in apps:
                self.app_combo.addItem(nm, aid)
        self.app_combo.blockSignals(False)

    def result_data(self) -> Optional[Dict[str, Any]]:
        name = self.name_edit.text().strip()
        aumid = self.aumid_edit.text().strip()
        if not name or not aumid:
            return None
        return {
            "name": name,
            "aumid": aumid,
            "flags": self.flags_edit.text().strip(),
            "exe_name": self.exe_edit.text().strip(),
            "steam_appid": self.steam_appid_edit.text().strip(),
            "validate_steam": self.validate_cb.isChecked(),
            "validate_timeout": int(self.validate_timeout.value()),
            "wait_seconds": self.wait_spin.value(),
            "priority": self.prio_combo.currentText(),
            "auto_affinity": self.auto_aff.isChecked(),
            "affinity_hex": self.aff_hex.text().strip()
        }

# ===== Main Window =====

# ===== Simple Settings dialog =====
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        lay = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.api_edit = QtWidgets.QLineEdit(self.settings.get("steam_api_key",""))
        self.api_edit.setPlaceholderText("Paste your Steam Web API key")
        self.api_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal)
        form.addRow("Steam Web API Key", self.api_edit)

        self.id_label = QtWidgets.QLabel(self.settings.get("steamid64", "(not signed in)"))
        form.addRow("Signed in as (SteamID64)", self.id_label)

        lay.addLayout(form)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def apply(self):
        self.settings["steam_api_key"] = self.api_edit.text().strip()
        return self.settings

class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal UWP Launcher")
        self.resize(1060, 680)

        self.settings = load_settings()
        self.games_db = load_games()   # {"games": [ {...} ]}
        self.worker: Optional[LaunchWorker] = None

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)

        # Left: list
        left = QtWidgets.QVBoxLayout()
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.currentRowChanged.connect(self._show_selected)
        left.addWidget(QtWidgets.QLabel("Games"))
        left.addWidget(self.list_widget, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("Add Game")
        self.btn_edit = QtWidgets.QPushButton("Edit")
        self.btn_del = QtWidgets.QPushButton("Remove")
        btn_row.addWidget(self.btn_add); btn_row.addWidget(self.btn_edit); btn_row.addWidget(self.btn_del)
        left.addLayout(btn_row)

        # Right: details + actions
        right = QtWidgets.QVBoxLayout()
        form = QtWidgets.QFormLayout()
        self.name_val  = QtWidgets.QLabel("-")
        self.aumid_val = QtWidgets.QLabel("-")
        self.flags_val = QtWidgets.QLabel("-")
        self.exe_val   = QtWidgets.QLabel("-")
        self.wait_val  = QtWidgets.QLabel("-")
        self.prio_val  = QtWidgets.QLabel("-")
        self.aff_val   = QtWidgets.QLabel("-")

        for lab in (self.name_val, self.aumid_val, self.flags_val, self.exe_val, self.wait_val, self.prio_val, self.aff_val):
            lab.setTextFormat(QtCore.Qt.TextFormat.PlainText)

        form.addRow("Name", self.name_val)
        form.addRow("AUMID", self.aumid_val)
        form.addRow("Arguments", self.flags_val)
        form.addRow("Target EXE", self.exe_val)
        self.steam_val = QtWidgets.QLabel("-")
        self.validate_val = QtWidgets.QLabel("-")
        form.addRow("Steam AppID", self.steam_val)
        form.addRow("Steam Validate", self.validate_val)
        form.addRow("Wait (s)", self.wait_val)
        form.addRow("Priority", self.prio_val)
        form.addRow("Affinity", self.aff_val)

        # Actions
        act_row1 = QtWidgets.QHBoxLayout()
        self.btn_launch = QtWidgets.QPushButton("LAUNCH")
        self.btn_launch.setMinimumHeight(42)
        self.btn_launch.setStyleSheet("font-weight:700;font-size:16px;")
        self.btn_shortcut = QtWidgets.QPushButton("Create Desktop Shortcut (.lnk)")
        act_row1.addWidget(self.btn_launch)
        self.btn_validate = QtWidgets.QPushButton("Validate via Steam")
        act_row1.addWidget(self.btn_validate)
        self.btn_steam_login = QtWidgets.QPushButton("Sign into Steam")
        act_row1.addWidget(self.btn_steam_login)
        self.btn_sync_lib = QtWidgets.QPushButton("Sync Steam Library")
        act_row1.addWidget(self.btn_sync_lib)
        act_row1.addWidget(self.btn_shortcut)
        self.btn_settings = QtWidgets.QPushButton("Settings…")
        act_row1.addWidget(self.btn_settings)

        # Logs
        self.log_box = QtWidgets.QPlainTextEdit(); self.log_box.setReadOnly(True); self.log_box.setMaximumBlockCount(2000)
        self.log_box.setPlaceholderText("Logs will appear here...")

        # Defaults
        def_row = QtWidgets.QHBoxLayout()
        self.wait_spin_def = QtWidgets.QSpinBox(); self.wait_spin_def.setRange(5, 600); self.wait_spin_def.setValue(int(self.settings.get("default_wait", 45)))
        self.prio_def = QtWidgets.QComboBox(); self.prio_def.addItems(list(PRIORITY_MAP.keys())); self.prio_def.setCurrentText(self.settings.get("default_priority","High"))
        self.btn_save_settings = QtWidgets.QPushButton("Save Defaults")
        # Safe-connect: if _save_defaults is missing, fall back to saving settings directly
        handler = getattr(self, "_save_defaults", None)
        if handler is None:
            def handler():
                save_settings(self.settings)
                self._log("[✓] Defaults saved.", "ok")
        self.btn_save_settings.clicked.connect(handler)
        def_row.addWidget(QtWidgets.QLabel("Default Wait (s)")); def_row.addWidget(self.wait_spin_def)
        def_row.addSpacing(12)
        def_row.addWidget(QtWidgets.QLabel("Default Priority")); def_row.addWidget(self.prio_def)
        def_row.addStretch(1)
        def_row.addWidget(self.btn_save_settings)

        # Assemble right
        right.addLayout(form)
        right.addSpacing(6)
        right.addLayout(act_row1)
        right.addWidget(self.log_box, 1)
        right.addLayout(def_row)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

        # Wire buttons
        self.btn_add.clicked.connect(self._add_game)
        self.btn_edit.clicked.connect(self._edit_game)
        self.btn_del.clicked.connect(self._remove_game)
        self.btn_launch.clicked.connect(self._launch_selected)
        self.btn_validate.clicked.connect(self._validate_selected)
        self.btn_steam_login.clicked.connect(self._sign_into_steam)
        self.btn_sync_lib.clicked.connect(self._sync_steam_library)
        self.btn_shortcut.clicked.connect(self._make_shortcut_selected)
        self.btn_settings.clicked.connect(self._open_settings)

        # Simple dark theme
        app = QtWidgets.QApplication.instance()
        app.setStyle("Fusion")
        pal = app.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(32,32,32))
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(230,230,230))
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(40,40,40))
        pal.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(60,60,60))
        app.setPalette(pal)

    # ===== List management =====
    def _refresh_list(self):
        self.list_widget.clear()
        for g in self.games_db["games"]:
            self.list_widget.addItem(g.get("name", "(unnamed)"))
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self._show_game(None)

    def _current_game(self) -> Optional[Dict[str, Any]]:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.games_db["games"]):
            return None
        return self.games_db["games"][row]

    def _show_selected(self, idx: int):
        self._show_game(self._current_game())

    def _show_game(self, g: Optional[Dict[str, Any]]):
        if not g:
            self.name_val.setText("-"); self.aumid_val.setText("-"); self.flags_val.setText("-"); self.exe_val.setText("-")
            self.wait_val.setText("-"); self.prio_val.setText("-"); self.aff_val.setText("-")
            return
        self.name_val.setText(g.get("name","-"))
        self.aumid_val.setText(g.get("aumid","-"))
        # flags may be stored as list or other types from older configs; normalise to string
        flags_val = g.get("flags", "-")
        if isinstance(flags_val, list):
            flags_val = " ".join(str(x) for x in flags_val)
        elif not isinstance(flags_val, str):
            flags_val = str(flags_val)
        self.flags_val.setText(flags_val)
        self.exe_val.setText(g.get("exe_name","-"))
        self.steam_val.setText(str(g.get("steam_appid","-")) or "-")
        self.validate_val.setText("Yes" if g.get("validate_steam") else "No")
        self.wait_val.setText(str(g.get("wait_seconds", self.settings.get("default_wait",45))))
        self.prio_val.setText(g.get("priority", self.settings.get("default_priority","High")))
        aff = "auto (all but CPU0)" if g.get("auto_affinity", True) and not g.get("affinity_hex") else (g.get("affinity_hex") or "None")
        self.aff_val.setText(aff)

    # ===== Add/Edit/Remove =====
    def _add_game(self):
        dlg = GameDialog(self, self.settings)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            data = dlg.result_data()
            if not data:
                self._log("[x] Name & AUMID required.", "error"); return
            self.games_db["games"].append(data)
            save_games(self.games_db)
            self._refresh_list()
            self._log(f"[✓] Added '{data['name']}'.", "ok")

    def _edit_game(self):
        g = self._current_game()
        if not g:
            return
        dlg = GameDialog(self, self.settings, data=g)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            data = dlg.result_data()
            if not data:
                self._log("[x] Name & AUMID required.", "error"); return
            idx = self.list_widget.currentRow()
            self.games_db["games"][idx] = data
            save_games(self.games_db)
            self._refresh_list()
            self._log(f"[✓] Updated '{data['name']}'.", "ok")

    def _remove_game(self):
        g = self._current_game()
        if not g:
            return
        idx = self.list_widget.currentRow()
        name = g.get("name","(unnamed)")
        del self.games_db["games"][idx]
        save_games(self.games_db)
        self._refresh_list()
        self._log(f"[!] Removed '{name}'.", "warn")

    def _sign_into_steam(self):
        """Sign the user into Steam (OpenID) so the launcher can access their library."""
        self._log("[i] Starting Steam sign-in (launcher)…", "info")
        steamid = steam_openid_login(timeout=180)
        if steamid:
            self.settings["steamid64"] = steamid
            save_settings(self.settings)
            self._log(f"[✓] Signed in as SteamID64: {steamid}", "ok")
            api_key = self.settings.get("steam_api_key")
            if api_key:
                ok, msg, _ = sync_steam_library(steamid, api_key)
                if ok:
                    self._log(f"[✓] {msg}", "ok")
                else:
                    self._log(f"[~] {msg}", "warn")
            else:
                self._log("[~] Tip: add 'steam_api_key' in settings JSON to enable full library sync.", "warn")
        else:
            self._log("[x] Steam sign-in failed or timed out.", "error")

    
    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            dlg.apply()
            save_settings(self.settings)
            self._log("[✓] Settings saved.", "ok")

    def _sync_steam_library(self):
        steamid = self.settings.get("steamid64","")
        if not steamid:
            self._log("[x] Not signed into Steam yet. Click 'Sign into Steam' first.", "error")
            return
        api_key = self.settings.get("steam_api_key")
        ok, msg, payload = sync_steam_library(steamid, api_key)
        if ok:
            self._log(f"[✓] {msg}", "ok")
            try:
                added, skipped = import_owned_games_to_db(self.games_db, payload, installed_only=True)
                if added:
                    save_games(self.games_db)
                    self._refresh_list()
                self._log(f"[i] Imported {added} new titles ({skipped} skipped).", "info")
            except Exception as e:
                self._log(f"[~] Synced but failed to import into list: {e}", "warn")
        else:
            self._log(f"[~] {msg}", "warn")

    def _validate_selected(self):
        g = self._current_game()
        if not g:
            return
        appid = str(g.get("steam_appid","" )).strip()
        if not appid.isdigit():
            self._log("[x] No valid Steam AppID set for this title.", "error")
            return
        self._log(f"[i] Validating via Steam for AppID {appid}…", "info")
        cfg = dict(g)
        cfg["validate_only"] = True
        self.btn_validate.setEnabled(False)
        self.worker = LaunchWorker(cfg)
        self.worker.log_signal.connect(self._on_worker_log)
        self.worker.done_signal.connect(self._on_worker_done_validate)
        self.worker.start()
    def _on_worker_done_validate(self, ok: bool, msg: str):
        self.btn_validate.setEnabled(True)
        self._on_worker_done(ok, msg)
        # Auto-launch after successful validation
        if ok:
            QtCore.QTimer.singleShot(1000, self._launch_selected)

    # ===== Launch & Shortcut =====
    def _launch_selected(self):
        g = self._current_game()
        if not g:
            return
        self.btn_launch.setEnabled(False)
        self._log(f"[i] Launching '{g.get('name','')}'…", "info")
        self.worker = LaunchWorker(g)
        self.worker.log_signal.connect(self._on_worker_log)
        self.worker.done_signal.connect(self._on_worker_done)
        self.worker.start()

    def _make_shortcut_selected(self):
        g = self._current_game()
        if not g:
            return
        name = g.get("name","UWP Game")
        target = this_python_executable()
        # avoid f-string backslash rule; use .format()
        args = '"{}" --run "{}"'.format(str(Path(__file__).absolute()), name.replace('"', ''))
        desktop = Path(os.path.join(os.path.expanduser("~"), "Desktop"))
        out = desktop / name
        ok, msg = make_windows_shortcut(target, args, out, icon_path=None)
        if ok:
            self._log(f"[✓] Shortcut created: {msg}", "ok")
            self._log("[i] You can add this .lnk to Steam as a Non-Steam game if desired.", "info")
        else:
            self._log(f"[x] Shortcut failed: {msg}", "error")

    def _on_worker_log(self, level: str, msg: str):
        self._log(msg, level)

    def _on_worker_done(self, ok: bool, msg: str):
        self._log(("Success: " if ok else "Failed: ") + msg, "ok" if ok else "error")
        self.btn_launch.setEnabled(True)

    # ===== Defaults =====
    def _save_defaults(self):
        self.settings["default_wait"] = self.wait_spin_def.value()
        self.settings["default_priority"] = self.prio_def.currentText()
        save_settings(self.settings)
        self._log("[✓] Defaults saved.", "ok")

    # ===== Logging =====
    def _log(self, msg: str, level: str = "info"):
        prefix = {"info":"[i] ", "ok":"[✓] ", "warn":"[!] ", "error":"[x] "}.get(level, "")
        self.log_box.appendPlainText(prefix + msg)

# ===== CLI support (for shortcut) =====
def _parse_cli_run(argv: List[str]) -> Optional[str]:
    try:
        if "--run" in argv:
            idx = argv.index("--run")
            return argv[idx+1] if idx+1 < len(argv) else None
        for a in argv:
            if a.startswith("--run="):
                return a.split("=",1)[1].strip().strip('"')
    except Exception:
        pass
    return None

def main():
    run_name = _parse_cli_run(sys.argv[1:])
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if run_name:
        names = [g.get("name","") for g in win.games_db["games"]]
        if run_name in names:
            row = names.index(run_name)
            win.list_widget.setCurrentRow(row)
            QtCore.QTimer.singleShot(250, win._launch_selected)
        else:
            win._log(f"[x] Game '{run_name}' not found.", "error")
    sys.exit(app.exec())

def _steam_window_title_has(substr: str) -> bool:
    try:
        import psutil
    except Exception:
        return False
    substr_l = substr.lower()
    steam_pids = set()
    for proc in psutil.process_iter(['name']):
        try:
            nm = (proc.info.get('name') or '').lower()
            if nm.startswith('steam'):
                steam_pids.add(proc.pid)
        except Exception:
            pass
    if not steam_pids:
        return False
    user32 = ctypes.windll.user32
    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    IsWindowVisible = user32.IsWindowVisible
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    @EnumWindowsProc
    def _enum_proc(hwnd, lparam):
        if not IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in steam_pids:
            return True
        length = GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        if substr_l in title.lower():
            return False
        return True
    EnumWindows(_enum_proc, 0)
    return False

# ===== Steam library import helper =====

# ===== Installed Steam titles detector =====
def _parse_libraryfolders_vdf(vdf_path: Path) -> List[Path]:
    """Very light parser to extract library folder paths from libraryfolders.vdf"""
    libs = []
    try:
        txt = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return libs
    # Match lines like: "1"    "D:\\SteamLibrary"
    for m in re.finditer(r'"\d+"\s*"([^"]+)"', txt):
        try:
            lib = Path(m.group(1).replace('\\\\', '\\'))
            if lib.exists():
                libs.append(lib)
        except Exception:
            pass
    # Always include the default Steam root library
    root = _get_steam_root()
    if root:
        libs.append(root)
    # De-dup
    uniq = []
    seen = set()
    for lp in libs:
        key = str(lp.resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(lp)
    return uniq

def get_installed_steam_appids() -> set:
    """Return a set of installed Steam appids by scanning steamapps manifests across libraries."""
    appids = set()
    root = _get_steam_root()
    if not root:
        return appids
    steamapps = root / "steamapps"
    # libraryfolders.vdf lists additional libraries
    libs = []
    try:
        libs = _parse_libraryfolders_vdf(steamapps / "libraryfolders.vdf")
    except Exception:
        libs = []
    # Always include root steamapps
    if root not in libs:
        libs.append(root)
    # Scan manifests in each library's steamapps
    for lib_root in libs:
        sa = lib_root / "steamapps"
        if not sa.exists():
            continue
        for mf in sa.glob("appmanifest_*.acf"):
            # appmanifest_12345.acf
            m = re.search(r"appmanifest_(\d+)\.acf$", mf.name, re.I)
            if m:
                appids.add(m.group(1))
            else:
                # fallback: try reading file for "appid" "12345"
                try:
                    t = mf.read_text(encoding="utf-8", errors="ignore")
                    m2 = re.search(r'"appid"\s*"(\d+)"', t)
                    if m2:
                        appids.add(m2.group(1))
                except Exception:
                    pass
    return appids

def import_owned_games_to_db(db: Dict[str, Any], payload: dict, installed_only: bool = True) -> Tuple[int, int]:
    try:
        games = payload.get("response", {}).get("games", [])
        installed = get_installed_steam_appids() if installed_only else set()
    except Exception:
        games = []
    if not isinstance(games, list):
        return (0, 0)
    existing = {str(item.get("steam_appid","")).strip() for item in db.get("games", [])}
    added = 0
    skipped = 0
    for item in games:
        appid = str(item.get("appid","")).strip()
        if (not appid.isdigit()) or (appid in existing) or (installed_only and appid not in installed):
            skipped += 1; continue
        name = item.get("name") or f"App {appid}"
        db.setdefault("games", []).append({
            "name": name,
            "steam_appid": appid,
            "aumid": "",
            "args": "",
            "exe": "",
            "validate_steam": False,
            "validate_timeout": 900,
            "wait": 45,
            "priority": "High",
            "affinity": ""
        })
        existing.add(appid)
        added += 1
    return (added, skipped)

if __name__ == "__main__":
    main()


# ---- Steam validation window/title helpers ----
import ctypes
from ctypes import wintypes