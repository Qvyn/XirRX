
# suite_one_app_safe_baseline_fixed.py
# Clean baseline:
# - Manual controls only (no auto stop/hide/start/show)
# - Streamer Mode (exclude overlay from capture) via tray + Streamer tab
# - Tabs: InputRX, CrossXir, Launcher, Streamer
# - No Safety Mode, Auto-Rules disabled (not included here)
# - Passive watchdog (only re-applies capture exclusion)
import os, sys, json, subprocess, signal, shlex, pathlib, ctypes, math
from typing import List, Dict, Optional
from PyQt6 import QtCore, QtGui, QtWidgets
import launcher as uwplauncher

# Optional psutil for nicer process checks
try:
    import psutil
except Exception:
    psutil = None

# Expect these modules next to this suite
import input_refiner_pyqt6_stable_patched_ultrasens as inputrx
import crosshair_x_designer_stack_patched as crossxir
# --- App directories (created next to executable/script) ---
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
DIRS = {
    "logs": os.path.join(APP_DIR, "logs"),
    "config": os.path.join(APP_DIR, "config"),
    "data": os.path.join(APP_DIR, "data"),
}
def _ensure_dirs():
    for d in DIRS.values():
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
_ensure_dirs()

# --- Logging into /logs ---

# --- Fault handler and loose-file redirect ---
def _redirect_loose_files():
    try:
        # 1) Route Python faulthandler to /logs/faulthandler.dump
        import faulthandler
        _fh_path = os.path.join(DIRS["logs"], "faulthandler.dump")
        try:
            _fh_file = open(_fh_path, "w", encoding="utf-8")
            try:
                faulthandler.enable(_fh_file)
            except Exception:
                try: faulthandler.enable()
                except Exception: pass
        except Exception:
            pass

        # 2) Ensure an 'input_refiner.log' handler in /logs
        try:
            import logging, logging.handlers
            _ir_path = os.path.join(DIRS["logs"], "input_refiner.log")
            # Avoid duplicates: only add if no handler already points to input_refiner.log
            root = logging.getLogger()
            if not any(getattr(h, "baseFilename", "").endswith("input_refiner.log") for h in root.handlers):
                _ir = logging.handlers.RotatingFileHandler(_ir_path, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
                _ir.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
                root.addHandler(_ir)
        except Exception:
            pass

        # 3) Move any existing loose files into /logs (best effort)
        try:
            app_root = APP_DIR
            for fname in ("faulthandler.dump", "input_refiner.log"):
                src = os.path.join(app_root, fname)
                if os.path.exists(src):
                    dst = os.path.join(DIRS["logs"], fname)
                    # If a dst already exists, append a numeric suffix
                    if os.path.abspath(src) != os.path.abspath(dst):
                        base, ext = os.path.splitext(dst)
                        k = 1
                        final = dst
                        while os.path.exists(final):
                            final = f"{base}.{k}{ext}"
                            k += 1
                        try:
                            shutil.move(src, final)
                        except Exception:
                            pass
        except Exception:
            pass
    except Exception:
        pass

_redirect_loose_files()

# --- Input refiner hardlink into /logs ---
def _is_samefile(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except Exception:
        try:
            return os.path.abspath(a) == os.path.abspath(b) and os.path.exists(a) and os.path.exists(b)
        except Exception:
            return False

def _set_hidden(path: str):
    # Windows: hide the root link to avoid clutter
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass

def _ensure_hardlink(src_at_root: str, dst_in_logs: str):
    """Move root file into /logs and leave a hidden hardlink at root pointing to /logs file."""
    try:
        root_path = os.path.join(APP_DIR, src_at_root)
        log_path = os.path.join(DIRS["logs"], dst_in_logs)
        # Ensure logs file exists (move or create empty)
        if os.path.exists(root_path) and not _is_samefile(root_path, log_path):
            try:
                os.replace(root_path, log_path)  # atomic move/overwrite
            except Exception:
                # Fallback: copy then remove
                try:
                    import shutil
                    shutil.copy2(root_path, log_path)
                    try: os.remove(root_path)
                    except Exception: pass
                except Exception:
                    pass
        # If nothing at logs yet, touch it so we can link
        if not os.path.exists(log_path):
            try:
                open(log_path, "a", encoding="utf-8").close()
            except Exception:
                pass
        # Now ensure a hardlink at root that points to logs
        try:
            # If already same file, we're done
            if os.path.exists(root_path) and _is_samefile(root_path, log_path):
                _set_hidden(root_path)
                return
            # Remove stray file then create link
            try:
                if os.path.exists(root_path):
                    os.remove(root_path)
            except Exception:
                pass
            try:
                os.link(log_path, root_path)   # requires NTFS
                _set_hidden(root_path)
            except Exception:
                # Fallback: try symlink (requires privileges) else leave as-is
                try:
                    os.symlink(log_path, root_path)
                    _set_hidden(root_path)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass

# --- Robust mover & periodic sweep ---
def _move_to_logs(filename: str):
    """Move APP_DIR/<filename> into DIRS['logs']/<filename>. Overwrites if needed."""
    try:
        src = os.path.join(APP_DIR, filename)
        if not os.path.exists(src):
            return
        os.makedirs(DIRS.get('logs', os.path.join(APP_DIR, 'logs')), exist_ok=True)
        dst = os.path.join(DIRS['logs'], filename)
        # If source is empty and dest exists, just remove src
        try:
            if os.path.getsize(src) == 0 and os.path.exists(dst):
                os.remove(src)
                return
        except Exception:
            pass
        # Atomic replace; fallback to copy then remove
        try:
            os.replace(src, dst)
        except Exception:
            import shutil
            try:
                shutil.copy2(src, dst)
                try:
                    os.remove(src)
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass

def _sweep_loose_logs():
    for fname in ("faulthandler.dump", "input_refiner.log"):
        _move_to_logs(fname)

try:
    import logging, logging.handlers, logging.handlers
    _log_path = os.path.join(DIRS["logs"], "suite.log")
    _handler = logging.handlers.RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    _handler.setFormatter(_fmt)
    logging.getLogger().addHandler(_handler)
    logging.getLogger().setLevel(logging.INFO)
except Exception:
    pass

def app_path(category: str, filename: str) -> str:
    base = DIRS.get(category, APP_DIR)
    return os.path.join(base, filename)


# Windows capture exclusion flags
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Win10 2004+

def apply_capture_exclusion(hwnd: int, enabled: bool) -> bool:
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE)
        return True
    except Exception:
        return False

def overlay_hwnd(win) -> Optional[int]:
    try:
        ctab = getattr(win, "crossTab", None)
        ov = getattr(ctab.win, "overlay", None) if ctab else None
        if ov is None:
            return None
        wid = ov.winId()
        return int(wid)
    except Exception:
        return None

class FlatBar(QtWidgets.QFrame):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

class InputRXSubTab(QtWidgets.QWidget):
    def _ensure_pens(self):
        return

    def __init__(self, parent=None):
        super().__init__(parent)
        getattr(self, '_ensure_pens', lambda: None)()
        bar = FlatBar(); hb = QtWidgets.QHBoxLayout(bar); hb.setContentsMargins(0,0,0,0); hb.setSpacing(8)
        self.toggleBtn = QtWidgets.QPushButton("Stop InputRX"); self.toggleBtn.setCheckable(True); self.toggleBtn.setChecked(True); self.toggleBtn.setFixedHeight(28)
        self.statusLbl = QtWidgets.QLabel("running"); self.statusLbl.setStyleSheet("font-weight:600;")
        hb.addWidget(self.toggleBtn); hb.addWidget(self.statusLbl); hb.addStretch(1)

        self.cfg = inputrx.load_config(inputrx.CONFIG_PATH)
        self.bus = inputrx.InputSample()
        self.win = inputrx.MainWindow(self.cfg)

        self.manager = inputrx.WorkerManager(self.cfg, self.bus, self.win)
        self.manager.start()

        self.win.applyConfig.connect(self.manager.apply_to_worker)
        self.bus.updated.connect(self.win.stickViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
        self.bus.status.connect(self.win.statusLabel.setText, QtCore.Qt.ConnectionType.QueuedConnection)
        self.bus.triggers.connect(self.win.trigViz.on_triggers, QtCore.Qt.ConnectionType.QueuedConnection)
        self.bus.updated.connect(self.win.stickThrBar.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
        self.bus.updated.connect(self.win.debugViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        topWrap = QtWidgets.QWidget(); tw = QtWidgets.QVBoxLayout(topWrap); tw.setContentsMargins(0,0,0,0); tw.addWidget(bar)
        splitter.addWidget(topWrap); splitter.addWidget(self.win); splitter.setSizes([36, 10000])

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(8); root.addWidget(splitter)
        self.toggleBtn.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        if checked:
            if self.manager is None:
                try:
                    self.manager = inputrx.WorkerManager(self.cfg, self.bus, self.win)
                    self.manager.start()
                    self.win.applyConfig.connect(self.manager.apply_to_worker)
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, "InputRX", f"Failed to start worker:\n{e}")
                    self.manager = None; self.toggleBtn.setChecked(False); self.statusLbl.setText("stopped"); return
            self.toggleBtn.setText("Stop InputRX"); self.statusLbl.setText("running")
        else:
            try:
                if self.manager is not None: self.manager.stop()
            except Exception:
                pass
            self.manager = None; self.toggleBtn.setText("Start InputRX"); self.statusLbl.setText("stopped")

    def shutdown(self):
        try:
            if self.manager is not None: self.manager.stop()
        except Exception:
            pass

class CrossXirSubTab(QtWidgets.QWidget):
    def _ensure_pens(self):
        return

    def __init__(self, parent=None):
        super().__init__(parent)
        getattr(self, '_ensure_pens', lambda: None)()
        bar = FlatBar(); hb = QtWidgets.QHBoxLayout(bar); hb.setContentsMargins(0,0,0,0); hb.setSpacing(8)
        self.toggleBtn = QtWidgets.QPushButton("Hide Overlay"); self.toggleBtn.setCheckable(True); self.toggleBtn.setChecked(True); self.toggleBtn.setFixedHeight(28)
        self.statusLbl = QtWidgets.QLabel("overlay: visible"); self.statusLbl.setStyleSheet("font-weight:600;")
        hb.addWidget(self.toggleBtn); hb.addWidget(self.statusLbl); hb.addStretch(1)

        self.win = crossxir.MainWindow()

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        topWrap = QtWidgets.QWidget(); tw = QtWidgets.QVBoxLayout(topWrap); tw.setContentsMargins(0,0,0,0); tw.addWidget(bar)
        splitter.addWidget(topWrap); splitter.addWidget(self.win); splitter.setSizes([36, 10000])

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(8); root.addWidget(splitter)
        self.toggleBtn.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        try:
            if hasattr(self.win, "overlay"):
                if checked:
                    self.win.overlay.show(); self.toggleBtn.setText("Hide Overlay"); self.statusLbl.setText("overlay: visible")
                else:
                    self.win.overlay.hide(); self.toggleBtn.setText("Show Overlay"); self.statusLbl.setText("overlay: hidden")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "CrossXir", f"Overlay toggle problem:\n{e}")

    def shutdown(self):
        try:
            if hasattr(self.win, "overlay"): self.win.overlay.hide()
        except Exception:
            pass


class LauncherModel(QtCore.QAbstractTableModel):
    COLS = ["Name", "Path", "Args", "Status"]

    def __init__(self, data: list, pids_ref: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._pids = pids_ref

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.COLS)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            return None
        r, c = index.row(), index.column()
        it = self._data[r]
        if c == 0:
            v = it.get("name","")
        elif c == 1:
            v = it.get("path","")
        elif c == 2:
            v = it.get("args","")
        else:
            v = "running" if it.get("name","") in self._pids else "stopped"
        return v

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == QtCore.Qt.Orientation.Horizontal:
            return self.COLS[section]
        return str(section+1)

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        return (QtCore.Qt.ItemFlag.ItemIsSelectable |
                QtCore.Qt.ItemFlag.ItemIsEnabled)

    def addRow(self, it: dict):
        self.beginInsertRows(QtCore.QModelIndex(), len(self._data), len(self._data))
        self._data.append(it)
        self.endInsertRows()

    def removeRowAt(self, row: int):
        if 0 <= row < len(self._data):
            self.beginRemoveRows(QtCore.QModelIndex(), row, row)
            self._data.pop(row)
            self.endRemoveRows()

    def updateAll(self):
        # structure changed (e.g., after load/save); refresh everything
        self.beginResetModel()
        self.endResetModel()

    def bumpStatus(self):
        # status column changed for all rows
        if not self._data:
            return
        tl = self.index(0, 3)
        br = self.index(len(self._data)-1, 3)
        self.dataChanged.emit(tl, br, [QtCore.Qt.ItemDataRole.DisplayRole])
class LauncherTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        getattr(self, '_ensure_pens', lambda: None)()
        self.data = []  # list of dicts
        self.pids = {}  # name -> pid
        self._build_ui()
        self._load()
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1500)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self); layout.setContentsMargins(8,8,8,8); layout.setSpacing(8)
        # Controls row
        ctr = QtWidgets.QHBoxLayout()
        self.addBtn = QtWidgets.QPushButton("Add")
        self.editBtn = QtWidgets.QPushButton("Edit")
        self.delBtn = QtWidgets.QPushButton("Delete")
        self.runBtn = QtWidgets.QPushButton("Launch")
        self.stopBtn = QtWidgets.QPushButton("Stop")
        for b in (self.addBtn, self.editBtn, self.delBtn, self.runBtn, self.stopBtn):
            b.setFixedHeight(28)
        ctr.addWidget(self.addBtn); ctr.addWidget(self.editBtn); ctr.addWidget(self.delBtn); ctr.addStretch(1); ctr.addWidget(self.runBtn); ctr.addWidget(self.stopBtn)
        layout.addLayout(ctr)

        # Table as QTableView + model
        self.model = LauncherModel(self.data, self.pids, self)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        # wiring
        self.addBtn.clicked.connect(self._add_item)
        self.editBtn.clicked.connect(self._edit_item)
        self.delBtn.clicked.connect(self._delete_item)
        self.runBtn.clicked.connect(self._launch_selected)
        self.stopBtn.clicked.connect(self._stop_selected)

    def _refresh_table(self):
        # called after structural changes
        self.model.updateAll()
        self.table.resizeColumnsToContents()

    @QtCore.pyqtSlot()
    def _refresh_status(self):
        # Clean up dead processes
        if self.pids:
            try:
                import psutil  # optional
            except Exception:
                psutil = None
            if psutil:
                for name, pid in list(self.pids.items()):
                    try:
                        if not psutil.pid_exists(pid):
                            self.pids.pop(name, None)
                    except Exception:
                        self.pids.pop(name, None)
            else:
                for name, pid in list(self.pids.items()):
                    try:
                        os.kill(pid, 0)
                    except Exception:
                        self.pids.pop(name, None)
        # Nudge only the Status column in the model
        self.model.bumpStatus()


    def _add_item(self):
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Add Launcher Item")
        form = QtWidgets.QFormLayout(dlg)
        name = QtWidgets.QLineEdit()
        path = QtWidgets.QLineEdit()
        args = QtWidgets.QLineEdit()
        cwd  = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse…")
        def pick():
            f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select executable", "", "Programs (*.exe *.bat *.cmd);;All Files (*)")
            if f: path.setText(f)
        browse.clicked.connect(pick)
        path_row = QtWidgets.QHBoxLayout(); path_row.addWidget(path); path_row.addWidget(browse)
        form.addRow("Name", name)
        wrap = QtWidgets.QWidget(); wrap.setLayout(path_row)
        form.addRow("Path", wrap)
        form.addRow("Args", args)
        form.addRow("Working Dir", cwd)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            it = {"name": name.text().strip(), "path": path.text().strip(), "args": args.text().strip(), "cwd": cwd.text().strip()}
            if not it["name"] or not it["path"]:
                QtWidgets.QMessageBox.warning(self, "Launcher", "Name and Path are required."); return
            self.model.addRow(it)
            self._save(); self._refresh_table()

    def _edit_item(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs: return
        row = idxs[0].row()
        cur = dict(self.data[row])
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Edit Launcher Item")
        form = QtWidgets.QFormLayout(dlg)
        name = QtWidgets.QLineEdit(cur.get("name",""))
        path = QtWidgets.QLineEdit(cur.get("path",""))
        args = QtWidgets.QLineEdit(cur.get("args",""))
        cwd  = QtWidgets.QLineEdit(cur.get("cwd",""))
        browse = QtWidgets.QPushButton("Browse…")
        def pick():
            f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select executable", "", "Programs (*.exe *.bat *.cmd);;All Files (*)")
            if f: path.setText(f)
        browse.clicked.connect(pick)
        path_row = QtWidgets.QHBoxLayout(); path_row.addWidget(path); path_row.addWidget(browse)
        form.addRow("Name", name)
        wrap = QtWidgets.QWidget(); wrap.setLayout(path_row)
        form.addRow("Path", wrap)
        form.addRow("Args", args)
        form.addRow("Working Dir", cwd)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            cur.update({"name": name.text().strip(), "path": path.text().strip(), "args": args.text().strip(), "cwd": cwd.text().strip()})
            if not cur["name"] or not cur["path"]:
                QtWidgets.QMessageBox.warning(self, "Launcher", "Name and Path are required."); return
            self.data[row] = cur
            self._save(); self._refresh_table()

    def _delete_item(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs: return
        row = idxs[0].row()
        it = self.data[row]
        if QtWidgets.QMessageBox.question(self, "Delete", f"Delete '{it.get('name','')}'?") == QtWidgets.QMessageBox.StandardButton.Yes:
            self.model.removeRowAt(row)
            self._save(); self._refresh_table()


    def _conf_path(self):
        # Robust: compute config dir even if DIRS isn't in globals
        try:
            base = globals().get("DIRS", {}).get("config")
            if not base:
                base = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config")
            os.makedirs(base, exist_ok=True)
        except Exception:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        return os.path.join(base, "launcher_data.json")

    def _load(self):
        try:
            with open(self._conf_path(), "r", encoding="utf-8") as f:
                self.data[:] = json.load(f)
        except Exception:
            self.data[:] = []
        self._refresh_table()

    def _save(self):
        try:
            with open(self._conf_path(), "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print("Failed to save launcher data:", e)
    def _launch_selected(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return
        row = idxs[0].row()
        it = self.data[row]
        self.launch_item(it)

    def _stop_selected(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return
        row = idxs[0].row()
        it = self.data[row]
        self.stop_item(it)

    def _open_folder(self):
        idx = self._selected_index()
        if idx is None: return
        p = self.data[idx].get("path","")
        if p: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(p)))

    def launch_item(self, it: Dict):
        name = it.get("name","")
        if name in self.pids:
            QtWidgets.QMessageBox.information(self, "Launcher", f"{name} is already running."); return
        path = it.get("path",""); args = it.get("args",""); cwd = it.get("cwd","") or None
        if not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "Launcher", f"Path does not exist:\n{path}"); return
        try:
            cmd = [path] + (shlex.split(args) if args else [])
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(cmd, cwd=cwd, creationflags=flags, close_fds=False)
            try:
                self.window().eventBus.emit('launch')
            except Exception:
                pass
            self.pids[name] = proc.pid
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Launcher", f"Failed to launch:\n{e}")
        self._refresh_status(); self._refresh_table()
    def stop_item(self, it: Dict):
        name = it.get("name","")
        pid = self.pids.get(name)
        if not pid:
            QtWidgets.QMessageBox.information(self, "Launcher", f"{name} not running."); return
        try:
            if psutil:
                p = psutil.Process(pid)
                for ch in p.children(recursive=True):
                    try: ch.terminate()
                    except Exception: pass
                p.terminate()
                try: p.wait(2)
                except Exception: pass
                if p.is_running(): p.kill()
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Launcher", f"Failed to stop:\n{e}")
        self.pids.pop(name, None)
        self._refresh_status(); self._refresh_table()
class StreamerTab(QtWidgets.QWidget):
    def __init__(self, addons, parent=None):
        super().__init__(parent)
        self.addons = addons
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(12,12,12,12); v.setSpacing(12)
        title = QtWidgets.QLabel("Streamer Mode"); title.setStyleSheet("font-size:16px; font-weight:700;")
        desc = QtWidgets.QLabel("Hide CrossXir overlay from screenshots & recordings while keeping it visible to you.\nRequires Windows 10 2004+ / Windows 11."); desc.setWordWrap(True)
        self.chk = QtWidgets.QCheckBox("Enable Streamer Mode (exclude overlay from capture)")
        self.chk.setChecked(False)
        self.chk.toggled.connect(self.on_toggled)
        v.addWidget(title); v.addWidget(desc); v.addWidget(self.chk); v.addStretch(1)

    def on_toggled(self, enabled: bool):
        if hasattr(self.addons, "_set_streamer_mode"):
            self.addons._set_streamer_mode(enabled)
            if hasattr(self.addons, "act_stream"):
                self.addons.act_stream.blockSignals(True)
                self.addons.act_stream.setChecked(enabled)
                self.addons.act_stream.blockSignals(False)


class TileButton(QtWidgets.QPushButton):
    def __init__(self, text: str, icon: QtGui.QIcon | None = None, parent=None):
        super().__init__(text, parent)
        if icon is not None:
            self.setIcon(icon)
            self.setIconSize(QtCore.QSize(22,22))
        self.setCheckable(True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(44)
        self.setStyleSheet("""
            QPushButton {
                text-align: left; padding: 10px 12px; border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.08);
                background: rgba(255,255,255,0.04);
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(255,255,255,0.08); }
            QPushButton:checked {
                background: rgba(56,128,255,0.18);
                border: 1px solid rgba(56,128,255,0.35);
            }
        """)




class PulseBar(QtWidgets.QWidget):
    """Thin animated pulse bar that reacts to suite events and optional anomaly warnings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        getattr(self, '_ensure_pens', lambda: None)()
        self.setFixedHeight(6)
        self._phase = 0.0
        self._color = QtGui.QColor(80, 160, 255)   # calm blue
        self._warn_color = QtGui.QColor(255, 90, 90)  # anomaly red
        self._state_until = 0  # ms epoch when special color expires
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def flash(self, kind: str = "event", duration_ms: int = 1200):
        # kind can be "event" (teal) or "warn" (red)
        if kind == "warn":
            self._color = self._warn_color
        else:
            self._color = QtGui.QColor(80, 200, 170)  # teal for normal events
        self._state_until = QtCore.QTime.currentTime().msecsSinceStartOfDay() + duration_ms

    def paintEvent(self, e: QtGui.QPaintEvent):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0,0,0,-1)
        t = QtCore.QTime.currentTime().msecsSinceStartOfDay()
        # If the flash window expired, return to calm blue
        if t > self._state_until:
            base = QtGui.QColor(80, 160, 255)
        else:
            base = self._color

        # Create a moving gradient
        grad = QtGui.QLinearGradient(0, 0, rect.width(), 0)
        off = self._phase
        grad.setColorAt(max(0.0, off-0.2), base.darker(120))
        grad.setColorAt(off, base)
        grad.setColorAt(min(1.0, off+0.2), base.darker(120))

        p.fillRect(rect, grad)
        # subtle top/bottom lines
        pen = QtGui.QPen(base.darker(150))
        p.setPen(pen)
        p.drawLine(rect.bottomLeft(), rect.bottomRight())

class DriftLabTab(QtWidgets.QWidget):
    """Mini-challenge canvas: trace targets with the mouse; computes drift/error score."""

    def _ensure_pens(self):
        # Create cached pens/brushes if missing (robust against earlier init errors)
        if not hasattr(self, "_pen_target"):
            self._pen_target = QtGui.QPen(QtGui.QColor(30,120,100,220), 2)
        if not hasattr(self, "_brush_target"):
            self._brush_target = QtGui.QBrush(QtGui.QColor(80,200,170,230))
        if not hasattr(self, "_pen_cross"):
            self._pen_cross = QtGui.QPen(QtGui.QColor(255,255,255,230), 1)
        if not hasattr(self, "_pen_cross_shadow"):
            self._pen_cross_shadow = QtGui.QPen(QtGui.QColor(0,0,0,180), 1)
        if not hasattr(self, "_pen_path"):
            self._pen_path = QtGui.QPen(QtGui.QColor(200,200,200,200))
            self._pen_path.setWidth(2)
    def __init__(self, parent=None):
        super().__init__(parent)
        getattr(self, '_ensure_pens', lambda: None)()
        self.setMouseTracking(True)
        self.running = False
        self.duration_ms = 10000
        self.elapsed = 0
        self.score_history = []
        self.path = []  # collected points
        self.target = "circle"  # circle or points
        self._timer = QtCore.QTimer(self); self._timer.timeout.connect(self._tick)

        # UI
        top = QtWidgets.QHBoxLayout(); top.setContentsMargins(0,0,0,0); top.setSpacing(8)
        self.startBtn = QtWidgets.QPushButton("Start 10s"); self.resetBtn = QtWidgets.QPushButton("Reset")
        self.modeBox = QtWidgets.QComboBox(); self.modeBox.addItems(["Circle", "Line", "Targets", "Aim Pop"])
        self.durSpin = QtWidgets.QSpinBox(); self.durSpin.setRange(10, 60); self.durSpin.setValue(10)
        self.durSpin.setSuffix(" s")
        self.paceSpin = QtWidgets.QSpinBox(); self.paceSpin.setRange(200, 2000); self.paceSpin.setSingleStep(50); self.paceSpin.setValue(900)
        self.paceSpin.setSuffix(" ms")
        self.infoLbl = QtWidgets.QLabel("Idle"); self.scoreLbl = QtWidgets.QLabel("Score: 0 | Acc: 0% | Left: 10s")
        for w in (self.startBtn, self.resetBtn, self.modeBox): w.setFixedHeight(28)
        top.addWidget(self.startBtn); top.addWidget(self.resetBtn); top.addWidget(QtWidgets.QLabel("Mode:")); top.addWidget(self.modeBox); top.addWidget(QtWidgets.QLabel("Time:")); top.addWidget(self.durSpin); top.addWidget(QtWidgets.QLabel("Pace:")); top.addWidget(self.paceSpin); top.addStretch(1); top.addWidget(self.infoLbl); top.addWidget(self.scoreLbl)

        self.canvas = QtWidgets.QFrame(); self.canvas.setFrameShape(QtWidgets.QFrame.Shape.NoFrame); self.canvas.setMinimumHeight(340)
        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(8); root.addLayout(top); root.addWidget(self.canvas, 1)

        self.startBtn.clicked.connect(self.start)
        self.resetBtn.clicked.connect(self.reset)
        self.modeBox.currentTextChanged.connect(self._set_mode)

        self._last_mouse = None
        self._crosshair = None  # QPointF in canvas coords when running
        try:
            self.durSpin.setEnabled(False); self.paceSpin.setEnabled(False)
        except Exception:
            pass
        # Aim Pop mode state
        self.pop_targets = []   # list of dicts: {'pos': QPointF, 'r': int}
        self.pop_radius = 16
        self.pop_spawn_ms = 900
        self.pop_last_spawn = 0
        self.pop_hits = 0
        self.pop_shots = 0


    def _set_mode(self, m):
        self.target = m.lower()
        if self.target == 'aim pop':
            self.pop_targets.clear(); self.pop_hits = 0; self.pop_shots = 0
            try:
                self.durSpin.setEnabled(True); self.paceSpin.setEnabled(True)
            except Exception:
                pass
        else:
            try:
                self.durSpin.setEnabled(False); self.paceSpin.setEnabled(False)
            except Exception:
                pass
        self.update()

    def start(self):
        if self.running: return
        self.running = True; self.elapsed = 0; self.path.clear(); self.score_history.clear()
        if self.target == 'aim pop':
            self.pop_targets.clear(); self.pop_hits = 0; self.pop_shots = 0; self.pop_last_spawn = 0
            try:
                self.duration_ms = int(self.durSpin.value()) * 1000
                self.pop_spawn_ms = int(self.paceSpin.value())
            except Exception:
                pass
            self._schedule_spawn()
        self._timer.start(16); self.infoLbl.setText("Running…")

    def reset(self):
        self.running = False; self._timer.stop(); self.elapsed = 0; self.path.clear(); self.update(); self.infoLbl.setText("Idle")

    def _tick(self):
        self.elapsed += 16
        if self.target == 'aim pop' and self.running:
            acc = (self.pop_hits / self.pop_shots * 100.0) if self.pop_shots else 0.0
            left = max(0, (self.duration_ms - self.elapsed)//1000)
            self.scoreLbl.setText(f"Score: {self.pop_hits} | Acc: {acc:.0f}% | Left: {left}s")
        if self.elapsed >= self.duration_ms:
            self.running = False; self._timer.stop()
            if self.target == 'aim pop':
                acc = (self.pop_hits / self.pop_shots * 100.0) if self.pop_shots else 0.0
                self.infoLbl.setText(f"Hits: {self.pop_hits}  Acc: {acc:.0f}%")
            else:
                score = self._compute_score()
                self.infoLbl.setText(f"Score (lower=better): {score:.2f}")
        self.update()



    def _schedule_spawn(self):
        if not getattr(self, "_spawn_timer", None):
            self._spawn_timer = QtCore.QTimer(self)
            self._spawn_timer.setSingleShot(True)
            self._spawn_timer.timeout.connect(self._on_spawn_timeout)
        if self.running and self.target == 'aim pop':
            self._spawn_timer.start(int(self.pop_spawn_ms))

    @QtCore.pyqtSlot()
    def _on_spawn_timeout(self):
        if not self.running or self.target != 'aim pop':
            return
        self._spawn_pop_target()
        self._schedule_spawn()

    def _spawn_pop_target(self):
        rect = self.canvas.rect()
        margin = self.pop_radius + 8
        import random
        w = max(0, rect.width() - margin*2)
        h = max(0, rect.height() - margin*2)
        x = (margin + random.randint(0, w)) if w > 0 else rect.center().x()
        y = (margin + random.randint(0, h)) if h > 0 else rect.center().y()
        self.pop_targets.append({'pos': QtCore.QPointF(x, y), 'r': self.pop_radius})
        if len(self.pop_targets) > 4:
            self.pop_targets.pop(0)

    def mousePressEvent(self, ev: QtGui.QMouseEvent):
        if self.target != 'aim pop' or not self.running:
            return
        canvas_rect = self.canvas.geometry()
        if not canvas_rect.contains(ev.position().toPoint()):
            return
        click = ev.position() - QtCore.QPointF(canvas_rect.x(), canvas_rect.y())
        self.pop_shots += 1
        hit_idx = None
        for i, t in enumerate(self.pop_targets):
            d = ((click.x()-t['pos'].x())**2 + (click.y()-t['pos'].y())**2)**0.5
            if d <= t['r']:
                hit_idx = i; break
        if hit_idx is not None:
            self.pop_hits += 1
            self.pop_targets.pop(hit_idx)
            try:
                self.window().eventBus.emit('aim_hit')
            except Exception:
                pass
        self.update()
    def mouseMoveEvent(self, ev: QtGui.QMouseEvent):
        if not self.running: return
        canvas_rect = self.canvas.geometry()
        if canvas_rect.contains(ev.position().toPoint()):
            self._crosshair = ev.position() - QtCore.QPointF(canvas_rect.x(), canvas_rect.y())
        if self.target == 'aim pop':
            self.update(); return
        # Record mouse position relative to canvas area
        if canvas_rect.contains(ev.position().toPoint()):
            pt = ev.position().toPoint()
            if not self.path or (abs(pt.x()-self.path[-1].x()) + abs(pt.y()-self.path[-1].y())) >= 1:
                self.path.append(pt)
        self.update()

    def _ideal_point(self, tfrac: float, rect: QtCore.QRect):
        if self.target == "circle":
            r = min(rect.width(), rect.height()) * 0.35
            cx, cy = rect.center().x(), rect.center().y()
            ang = 2*3.14159*tfrac
            return QtCore.QPointF(cx + r*math.cos(ang), cy + r*math.sin(ang))
        elif self.target == "line":
            # left to right sweep
            y = rect.center().y()
            x = rect.left() + rect.width() * tfrac
            return QtCore.QPointF(x, y)
        else:
            # targets: 4 points around
            pts = [
                rect.center() + QtCore.QPoint(int(rect.width()*0.3), 0),
                rect.center() + QtCore.QPoint(0, int(-rect.height()*0.3)),
                rect.center() + QtCore.QPoint(int(-rect.width()*0.3), 0),
                rect.center() + QtCore.QPoint(0, int(rect.height()*0.3)),
            ]
            idx = int(tfrac*len(pts)) % len(pts)
            return QtCore.QPointF(pts[idx])

    def _compute_score(self):
        if not self.path:
            return 0.0
        rect = self.canvas.rect()
        n = len(self.path)
        ideals = [self._ideal_point(i / max(1, n-1), rect) for i in range(n)]
        total = 0.0
        for (pt, ideal) in zip(self.path, ideals):
            total += math.hypot(pt.x()-ideal.x(), pt.y()-ideal.y())
        return total / n

    def paintEvent(self, e):
        super().paintEvent(e)
        getattr(self, '_ensure_pens', lambda: None)()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        # draw only in canvas rect
        rect = self.canvas.geometry()
        p.translate(rect.x(), rect.y())
        r = QtCore.QRect(0,0,rect.width(),rect.height())

        # background
        p.fillRect(r, QtGui.QColor(24,24,24,120))

        # Aim Pop only visuals
        if self.target == 'aim pop':
            # draw spheres
            p.setBrush(self._brush_target)
            p.setPen(self._pen_target)
            for t in self.pop_targets:
                rr = int(t['r']); cx = int(t['pos'].x()); cy = int(t['pos'].y())
                p.drawEllipse(QtCore.QRect(cx-rr, cy-rr, rr*2, rr*2))
            # crosshair in Aim Pop when running
            if self.running and self._crosshair is not None:
                chx, chy = int(self._crosshair.x()), int(self._crosshair.y())
                p.setPen(QtGui.QPen(QtGui.QColor(255,255,255,230), 1))
                p.drawLine(chx-10, chy, chx+10, chy)
                p.drawLine(chx, chy-10, chx, chy+10)
                p.setPen(QtGui.QPen(QtGui.QColor(0,0,0,180), 1))
                p.drawEllipse(QtCore.QRect(chx-3, chy-3, 6, 6))
        else:
            # background
            p.fillRect(r, QtGui.QColor(24,24,24,120))
            # target guide
            tfrac = (self.elapsed % self.duration_ms)/self.duration_ms if self.duration_ms else 0.0
            ideal = self._ideal_point(tfrac, r)
            pen = QtGui.QPen(QtGui.QColor(100,100,255,180)); pen.setWidth(2); p.setPen(pen)
            if self.target == "circle":
                radius = int(min(r.width(), r.height())*0.35)
                p.drawEllipse(r.center(), radius, radius)
            elif self.target == "line":
                p.drawLine(r.left()+10, r.center().y(), r.right()-10, r.center().y())
            else:
                for pt in [self._ideal_point(k/4.0, r) for k in range(4)]:
                    p.drawEllipse(QtCore.QRectF(pt.x()-6, pt.y()-6, 12, 12))
            # ideal marker
            p.setBrush(QtGui.QColor(255,255,255))
            p.drawEllipse(QtCore.QRectF(ideal.x()-3, ideal.y()-3, 6, 6))
            # draw path

        if self.path:
            p.setPen(self._pen_path)
            for i in range(1, len(self.path)):
                p.drawLine(self.path[i-1] - QtCore.QPoint(rect.x(), rect.y()), self.path[i] - QtCore.QPoint(rect.x(), rect.y()))

class UWPLaunchSubTab(QtWidgets.QWidget):
    """Embed launcher.py's MainWindow inside a suite tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.win = uwplauncher.MainWindow()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8,8,8,8)
        lay.setSpacing(8)
        lay.addWidget(self.win)
    def shutdown(self):
        try:
            if hasattr(self.win, "worker") and self.win.worker is not None:
                self.win.worker.terminate()
        except Exception:
            pass

class SuiteWindow(QtWidgets.QMainWindow):
    eventBus = QtCore.pyqtSignal(str)
    def __init__(self):
        super().__init__()



        # ensure input_refiner.log writes land in /logs via hardlink
        try:
            _ensure_hardlink("input_refiner.log", "input_refiner.log")
        except Exception:
            pass
# periodic sweep to keep stray logs out of the app root
        try:
            self._log_sweep = QtCore.QTimer(self)
            self._log_sweep.timeout.connect(lambda: _sweep_loose_logs())
            self._log_sweep.start(5000)
            _sweep_loose_logs()  # initial sweep
        except Exception:
            pass
# Ensure a default window icon exists so QSystemTrayIcon has one
        if self.windowIcon().isNull():
            pm = QtGui.QPixmap(32, 32)
            pm.fill(QtGui.QColor(20, 20, 24))
            painter = QtGui.QPainter(pm)
            painter.setPen(QtGui.QPen(QtGui.QColor(80, 160, 255)))
            painter.setFont(QtGui.QFont("Segoe UI", 14, QtGui.QFont.Weight.Bold))
            painter.drawText(pm.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "IX")
            painter.end()
            self.setWindowIcon(QtGui.QIcon(pm))
        self.setWindowTitle("InputRX + CrossXir — Suite")
        self.resize(1320, 820)

        self.sidebar_width = 220
        # Sidebar
        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setFixedWidth(self.sidebar_width)
        self.sidebar.setMaximumWidth(self.sidebar_width)
        self.sidebar.setStyleSheet("QFrame { background: transparent; }")

        sb_layout = QtWidgets.QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(12,12,12,12)
        sb_layout.setSpacing(8)

        title = QtWidgets.QLabel("Suite")
        title.setStyleSheet("font-size:18px; font-weight:800;")
        sb_layout.addWidget(title)

        def make_btn(text):
            b = TileButton(text)
            b.setMinimumHeight(0)
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding)
            return b

        self.btn_input = make_btn(" InputRX")
        self.btn_cross = make_btn(" CrossXir")
        self.btn_launch = make_btn(" Launcher")
        self.btn_stream = make_btn(" Streamer")
        self.btn_drift  = make_btn(" Drift Lab")
        self.btn_uwp  = make_btn(" UWP Launch")

        for b in (self.btn_input, self.btn_cross, self.btn_launch, self.btn_stream, self.btn_drift, self.btn_uwp):
            sb_layout.addWidget(b, 1)

        # Main stack
        self.stack = QtWidgets.QStackedWidget()
        self.inputTab = InputRXSubTab(self.stack)
        self.crossTab = CrossXirSubTab(self.stack)
        
        # Attach addons and build Streamer tab
        addons = attach_addons(self)
        self.streamTab = StreamerTab(addons, self.stack)
        self.launcherTab = LauncherTab(self.stack)
        self.driftTab = DriftLabTab(self.stack)
        self.uwpLaunchTab = UWPLaunchSubTab(self.stack)

        for w in (self.inputTab, self.crossTab, self.launcherTab, self.streamTab, self.driftTab, self.uwpLaunchTab):
            self.stack.addWidget(w)

        # Pulse bar
        self.pulse = PulseBar()

        # Layout inside a scrollable container
        content = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(content); vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(0)
        vbox.addWidget(self.pulse)
        row = QtWidgets.QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(0)
        row.addWidget(self.sidebar); row.addWidget(self.stack, 1)
        vbox.addLayout(row)
        scroll = QtWidgets.QScrollArea(); scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame); scroll.setWidgetResizable(True); scroll.setWidget(content)
        self.setCentralWidget(scroll)

        # Toolbar
        tb = QtWidgets.QToolBar("Main", self); tb.setMovable(False); tb.setIconSize(QtCore.QSize(16,16))
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
        act_toggle = QtGui.QAction("☰ Sidebar", self); act_toggle.setShortcut(QtGui.QKeySequence("Ctrl+B")); act_toggle.triggered.connect(self.toggle_sidebar); tb.addAction(act_toggle)

        # Wiring
        self.btn_input.clicked.connect(lambda: self.set_page("InputRX"))
        self.btn_cross.clicked.connect(lambda: self.set_page("CrossXir"))
        self.btn_launch.clicked.connect(lambda: self.set_page("Launcher"))
        self.btn_stream.clicked.connect(lambda: self.set_page("Streamer"))
        self.btn_drift.clicked.connect(lambda: self.set_page("Drift"))
        self.btn_uwp.clicked.connect(lambda: self.set_page("UWP Launch"))

        self.eventBus.connect(self._on_suite_event)
        try:
            self.inputTab.bus.status.connect(self._on_inputrx_status, QtCore.Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass
        try:
            # fire event when Apply button is clicked if available
            self.inputTab.win.applyBtn.clicked.connect(lambda: self.eventBus.emit('apply'))
        except Exception:
            pass

        self.set_page("InputRX")

    @QtCore.pyqtSlot(str)
    def _on_suite_event(self, kind: str):
        self.pulse.flash("event", 900)

    @QtCore.pyqtSlot(str)
    def _on_inputrx_status(self, text: str):
        t = text.lower()
        if 'jitter' in t:
            import re as _re
            m = _re.search(r'jitter[^0-9\-+]*([0-9]+(\.[0-9]+)?)', t)
            if m:
                try:
                    val = float(m.group(1))
                    if val >= 3.0:
                        self.pulse.flash('warn', 1400)
                except Exception:
                    pass

    def toggle_sidebar(self):
        showing = self.sidebar.maximumWidth() > 0
        if showing:
            self.sidebar.setMaximumWidth(0); self.sidebar.setFixedWidth(0)
        else:
            self.sidebar.setMaximumWidth(self.sidebar_width); self.sidebar.setFixedWidth(self.sidebar_width)

    def add_page(self, name: str, widget: QtWidgets.QWidget):
        if name == "Streamer":
            self.streamerTab = widget
            self.stack.addWidget(widget)

    def set_page(self, name: str):
        idx = None
        if name == "InputRX":
            idx = self.stack.indexOf(self.inputTab)
            self._check_btn(self.btn_input)
        elif name == "CrossXir":
            idx = self.stack.indexOf(self.crossTab)
            self._check_btn(self.btn_cross)
        elif name == "Launcher":
            idx = self.stack.indexOf(self.launcherTab)
            self._check_btn(self.btn_launch)
        elif name == "Streamer" and getattr(self, 'streamTab', None) is not None:
            idx = self.stack.indexOf(self.streamTab)
            self._check_btn(self.btn_stream)
        elif name == "Drift" and getattr(self, 'driftTab', None) is not None:
            idx = self.stack.indexOf(self.driftTab)
            self._check_btn(self.btn_drift)
        elif name == "UWP Launch" and getattr(self, 'uwpLaunchTab', None) is not None:
            idx = self.stack.indexOf(self.uwpLaunchTab)
            self._check_btn(self.btn_uwp)
        if idx is not None and idx >= 0:
            self.stack.setCurrentIndex(idx)

    def _check_btn(self, btn: QtWidgets.QPushButton):
        # Uncheck all known buttons
        for b in (
            getattr(self, 'btn_input', None),
            getattr(self, 'btn_cross', None),
            getattr(self, 'btn_launch', None),
            getattr(self, 'btn_stream', None),
            getattr(self, 'btn_drift', None),
            getattr(self, 'btn_uwp', None),
        ):
            try:
                if b is not None and b is not btn:
                    b.setChecked(False)
            except Exception:
                pass
        try:
            btn.setChecked(True)
        except Exception:
            pass

class _SuiteAddons(QtCore.QObject):
    def __init__(self, win: SuiteWindow):
        super().__init__(win)
        self.win = win
        self.tray = None
        self.streamer_mode = False

        self.watchdog_timer = QtCore.QTimer(self); self.watchdog_timer.setInterval(1500)
        self.watchdog_timer.timeout.connect(self._tick_watchdog); self.watchdog_timer.start()

        self._build_tray()
        self._install_menu()

    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self.win.windowIcon(), self.win)
        menu = QtWidgets.QMenu()

        self.act_irx = QtGui.QAction("Stop InputRX", menu, checkable=True); self.act_irx.setChecked(True)
        self.act_irx.toggled.connect(self._toggle_inputrx); menu.addAction(self.act_irx)

        self.act_cxr = QtGui.QAction("Hide Overlay", menu, checkable=True); self.act_cxr.setChecked(True)
        self.act_cxr.toggled.connect(self._toggle_crossxir); menu.addAction(self.act_cxr)

        menu.addSeparator()
        self.act_stream = QtGui.QAction("Streamer Mode (hide from capture)", menu, checkable=True)
        self.act_stream.toggled.connect(self._set_streamer_mode); menu.addAction(self.act_stream)

        menu.addSeparator()
        self.launchers_menu = menu.addMenu("Launchers")
        self.launchers_menu.addAction("Open Launcher Tab").triggered.connect(lambda: self.win.set_page("Launcher"))

        menu.addSeparator()
        quit_act = QtGui.QAction("Quit", menu); quit_act.triggered.connect(self.win.close); menu.addAction(quit_act)

        self.tray.setContextMenu(menu); self.tray.show()

    def _install_menu(self):
        mb = self.win.menuBar(); suite_menu = mb.addMenu("Suite")
        suite_menu.addAction(self.act_irx); suite_menu.addAction(self.act_cxr); suite_menu.addAction(self.act_stream)

    def _toggle_inputrx(self, running: bool):
        try:
            tab = self.win.inputTab
            if bool(tab.toggleBtn.isChecked()) != bool(running):
                tab.toggleBtn.blockSignals(True)
                tab.toggleBtn.setChecked(bool(running))
                tab.toggleBtn.blockSignals(False)
        except Exception:
            pass
        try:
            self.win.eventBus.emit('inputrx_toggle')
        except Exception:
            pass
        self._sync_labels()

    def _toggle_crossxir(self, visible: bool):
        try:
            tab = self.win.crossTab
            if bool(tab.toggleBtn.isChecked()) != bool(visible):
                tab.toggleBtn.blockSignals(True)
                tab.toggleBtn.setChecked(bool(visible))
                tab.toggleBtn.blockSignals(False)
        except Exception:
            pass
        try:
            self.win.eventBus.emit('crossxir_toggle')
        except Exception:
            pass
        self._sync_labels()

    def _set_streamer_mode(self, enabled: bool):
        self.streamer_mode = enabled
        hwnd = overlay_hwnd(self.win)
        if hwnd: apply_capture_exclusion(hwnd, enabled)
        try:
            self.win.eventBus.emit('streamer_mode')
        except Exception:
            pass

    def _tick_watchdog(self):
        # Passive: only re-apply capture exclusion if enabled; no auto start/stop/hide/show.
        try:
            if self.streamer_mode:
                hwnd = overlay_hwnd(self.win)
                if hwnd: apply_capture_exclusion(hwnd, True)
        except Exception:
            pass
        self._sync_labels()

    def _sync_labels(self):
        try:
            self.act_irx.setText("Stop InputRX" if self.act_irx.isChecked() else "Start InputRX")
            self.act_cxr.setText("Hide Overlay" if self.act_cxr.isChecked() else "Show Overlay")
        except Exception:
            pass

def attach_addons(win: SuiteWindow):
    win.__addons = _SuiteAddons(win)
    return win.__addons

def main():
    # High DPI
    for flag in ("AA_EnableHighDpiScaling","AA_UseHighDpiPixmaps"):
        attr = getattr(QtCore.Qt.ApplicationAttribute, flag, None)
        if attr is not None:
            QtWidgets.QApplication.setAttribute(attr, True)

    app = QtWidgets.QApplication(sys.argv)
    win = SuiteWindow()
    addons = attach_addons(win)
    # Visible Streamer tab
    stream_tab = StreamerTab(addons, win)
    win.add_page("Streamer", stream_tab)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
