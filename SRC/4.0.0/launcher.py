# Universal UWP Game Launcher (single file)
# Launches UWP apps by AUMID via IApplicationActivationManager, passes arguments,
# then applies per-title CPU affinity and process priority. Includes a simple UI
# to add/edit titles and optionally create a desktop .lnk that calls this script.

import os, sys, json, time, subprocess, ctypes, platform, traceback
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

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
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
GAMES_PATH = APPDATA_DIR / "games.json"
SETTINGS_PATH = APPDATA_DIR / "settings.json"

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
    s = _read_json(SETTINGS_PATH, DEFAULT_SETTINGS.copy())
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
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

        # Activate
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
            "wait_seconds": self.wait_spin.value(),
            "priority": self.prio_combo.currentText(),
            "auto_affinity": self.auto_aff.isChecked(),
            "affinity_hex": self.aff_hex.text().strip()
        }

# ===== Main Window =====
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
        act_row1.addWidget(self.btn_shortcut)

        # Logs
        self.log_box = QtWidgets.QPlainTextEdit(); self.log_box.setReadOnly(True); self.log_box.setMaximumBlockCount(2000)
        self.log_box.setPlaceholderText("Logs will appear here...")

        # Defaults
        def_row = QtWidgets.QHBoxLayout()
        self.wait_spin_def = QtWidgets.QSpinBox(); self.wait_spin_def.setRange(5, 600); self.wait_spin_def.setValue(int(self.settings.get("default_wait", 45)))
        self.prio_def = QtWidgets.QComboBox(); self.prio_def.addItems(list(PRIORITY_MAP.keys())); self.prio_def.setCurrentText(self.settings.get("default_priority","High"))
        self.btn_save_settings = QtWidgets.QPushButton("Save Defaults")
        self.btn_save_settings.clicked.connect(self._save_defaults)
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
        self.btn_shortcut.clicked.connect(self._make_shortcut_selected)

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
        self.flags_val.setText(g.get("flags","-"))
        self.exe_val.setText(g.get("exe_name","-"))
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

if __name__ == "__main__":
    main()
