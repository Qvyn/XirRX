import os, sys, json, subprocess, signal, shlex, pathlib, ctypes
from typing import List, Dict, Optional
from PyQt6 import QtCore, QtGui, QtWidgets

# Optional psutil for nicer process checks
try:
    import psutil
except Exception:
    psutil = None

# Expect these modules next to this suite
import input_refiner_pyqt6_stable_patched_ultrasens as inputrx
import crosshair_x_designer_stack_patched as crossxir

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
    def __init__(self, parent=None):
        super().__init__(parent)
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
    def __init__(self, parent=None):
        super().__init__(parent)
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

class LauncherTab(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = os.path.join(os.path.dirname(sys.argv[0]) or ".", "launchers.json")
        self.data: List[Dict] = []
        self.pids: Dict[str,int] = {}

        top = QtWidgets.QHBoxLayout(); top.setContentsMargins(0,0,0,0); top.setSpacing(8)
        self.addBtn = QtWidgets.QPushButton("Add"); self.editBtn = QtWidgets.QPushButton("Edit"); self.delBtn = QtWidgets.QPushButton("Remove")
        self.launchBtn = QtWidgets.QPushButton("Launch"); self.stopBtn = QtWidgets.QPushButton("Stop"); self.openBtn = QtWidgets.QPushButton("Open Folder")
        for w in (self.addBtn,self.editBtn,self.delBtn,self.launchBtn,self.stopBtn,self.openBtn): w.setFixedHeight(28)
        top.addWidget(self.addBtn); top.addWidget(self.editBtn); top.addWidget(self.delBtn); top.addStretch(1); top.addWidget(self.launchBtn); top.addWidget(self.stopBtn); top.addWidget(self.openBtn)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name","Path","Args","Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(8); root.addLayout(top); root.addWidget(self.table)

        self.addBtn.clicked.connect(self._add)
        self.editBtn.clicked.connect(self._edit)
        self.delBtn.clicked.connect(self._delete)
        self.launchBtn.clicked.connect(self._launch_selected)
        self.stopBtn.clicked.connect(self._stop_selected)
        self.openBtn.clicked.connect(self._open_folder)

        self._load(); self._refresh_table()

        self.timer = QtCore.QTimer(self); self.timer.setInterval(1500)
        self.timer.timeout.connect(self._refresh_status); self.timer.start()

    def _load(self):
        try:
            if os.path.exists(self.path):
                self.data = json.loads(pathlib.Path(self.path).read_text(encoding="utf-8"))
        except Exception:
            self.data = []

    def _save(self):
        try:
            pathlib.Path(self.path).write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            self.changed.emit()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Launcher", f"Failed to save launchers.json:\n{e}")

    def _refresh_table(self):
        self.table.setRowCount(0)
        for it in self.data:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r,0, QtWidgets.QTableWidgetItem(it.get("name","")))
            self.table.setItem(r,1, QtWidgets.QTableWidgetItem(it.get("path","")))
            self.table.setItem(r,2, QtWidgets.QTableWidgetItem(it.get("args","")))
            self.table.setItem(r,3, QtWidgets.QTableWidgetItem("running" if it.get("name","") in self.pids else "stopped"))
        self.table.resizeColumnsToContents()

    def _refresh_status(self):
        # Clean up dead processes
        if self.pids:
            if psutil:
                for name, pid in list(self.pids.items()):
                    try:
                        if not psutil.pid_exists(pid): self.pids.pop(name, None)
                    except Exception:
                        self.pids.pop(name, None)
            else:
                for name, pid in list(self.pids.items()):
                    try:
                        os.kill(pid, 0)
                    except Exception:
                        self.pids.pop(name, None)
        # Refresh table statuses
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            if not name_item: continue
            name = name_item.text()
            status = "running" if name in self.pids else "stopped"
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(status))

    def _selected_index(self) -> Optional[int]:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return next(iter(rows)) if rows else None

    def _edit_dialog(self, existing: Optional[Dict]=None) -> Optional[Dict]:
        d = QtWidgets.QDialog(self); d.setWindowTitle("Launcher Item"); d.resize(520, 220)
        form = QtWidgets.QFormLayout(d)
        name = QtWidgets.QLineEdit(existing.get("name","") if existing else "")
        path = QtWidgets.QLineEdit(existing.get("path","") if existing else "")
        args = QtWidgets.QLineEdit(existing.get("args","") if existing else "")
        browse = QtWidgets.QPushButton("Browse…")
        wd = QtWidgets.QLineEdit(existing.get("cwd","") if existing else "")
        form.addRow("Name:", name)
        h = QtWidgets.QHBoxLayout(); h.addWidget(path); h.addWidget(browse); form.addRow("Path:", h)
        form.addRow("Args:", args)
        form.addRow("Working Dir (optional):", wd)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok|QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=d)
        form.addRow(btns)

        def on_browse():
            file, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select executable", os.getcwd(), "Executable (*.exe);;All files (*)")
            if file: path.setText(file)
        browse.clicked.connect(on_browse)
        btns.accepted.connect(d.accept); btns.rejected.connect(d.reject)

        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            if not name.text().strip() or not path.text().strip():
                QtWidgets.QMessageBox.warning(self, "Launcher", "Name and Path are required."); return None
            return {"name": name.text().strip(), "path": path.text().strip(), "args": args.text().strip(), "cwd": wd.text().strip()}
        return None

    def _add(self):
        it = self._edit_dialog()
        if it: self.data.append(it); self._save(); self._refresh_table()

    def _edit(self):
        idx = self._selected_index()
        if idx is None: return
        it = self._edit_dialog(self.data[idx])
        if it: self.data[idx] = it; self._save(); self._refresh_table()

    def _delete(self):
        idx = self._selected_index()
        if idx is None: return
        name = self.data[idx].get("name",""); self.pids.pop(name, None)
        del self.data[idx]; self._save(); self._refresh_table()

    def _launch_selected(self):
        idx = self._selected_index()
        if idx is None: return
        self.launch_item(self.data[idx])

    def _stop_selected(self):
        idx = self._selected_index()
        if idx is None: return
        self.stop_item(self.data[idx])

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

class SuiteWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("InputRX + CrossXir — Suite")
        self.resize(1440, 880)

        self.tabs = QtWidgets.QTabWidget(); self.tabs.setDocumentMode(True)

        self.inputTab = InputRXSubTab(self.tabs)
        self.crossTab = CrossXirSubTab(self.tabs)
        self.launcherTab = LauncherTab(self.tabs)

        self.tabs.addTab(self.inputTab, "InputRX")
        self.tabs.addTab(self.crossTab, "CrossXir")
        self.tabs.addTab(self.launcherTab, "Launcher")

        central = QtWidgets.QWidget(); root = QtWidgets.QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.addWidget(self.tabs)
        self.setCentralWidget(central)

        QtWidgets.QApplication.instance().aboutToQuit.connect(self._graceful_shutdown)

    def _graceful_shutdown(self):
        try: self.inputTab.shutdown()
        except Exception: pass
        try: self.crossTab.shutdown()
        except Exception: pass

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
        self.launchers_menu.addAction("Open Launcher Tab").triggered.connect(lambda: self.win.tabs.setCurrentWidget(self.win.launcherTab))

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
        self._sync_labels()

    def _set_streamer_mode(self, enabled: bool):
        self.streamer_mode = enabled
        hwnd = overlay_hwnd(self.win)
        if hwnd: apply_capture_exclusion(hwnd, enabled)

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
    stream_tab = StreamerTab(addons, win.tabs)
    win.tabs.addTab(stream_tab, "Streamer")
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
