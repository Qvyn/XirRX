from __future__ import annotations
import ctypes, json, math, os, sys, time, logging, pathlib, faulthandler, weakref
from dataclasses import dataclass, asdict, replace
from PyQt6 import QtCore, QtGui, QtWidgets

# Try both import styles for sip
try:
    from PyQt6 import sip as _sip
except Exception:  # pragma: no cover
    import sip as _sip  # type: ignore

# ---------------- Logging & crash dump ----------------
LOG_PATH = str(pathlib.Path("input_refiner.log").resolve())
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
try:
    faulthandler.enable(open("faulthandler.dump", "w"))
except Exception:
    logging.exception("Failed to enable faulthandler")

# ---------------- Safe QObject reference ----------------
class SafeQObjectRef:
    __slots__ = ("_wr",)
    def __init__(self, obj: QtCore.QObject):
        self._wr = weakref.ref(obj)
    def isNull(self) -> bool:
        obj = self._wr(); return obj is None or _sip.isdeleted(obj)
    def get(self) -> QtCore.QObject | None:
        obj = self._wr(); return None if (obj is None or _sip.isdeleted(obj)) else obj

# ---------------- XInput + SendInput (mouse move only) ----------------
_XINPUT_DLLS = ["xinput1_4.dll","xinput1_3.dll","xinput9_1_0.dll","xinput1_2.dll","xinput1_1.dll"]

def _load_xinput():
    for n in _XINPUT_DLLS:
        try: return ctypes.WinDLL(n)
        except OSError: pass
    return None

XInput = _load_xinput()

XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = 8689

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]

# XInput button flags
XINPUT_GAMEPAD_DPAD_UP        = 0x0001
XINPUT_GAMEPAD_DPAD_DOWN      = 0x0002
XINPUT_GAMEPAD_DPAD_LEFT      = 0x0004
XINPUT_GAMEPAD_DPAD_RIGHT     = 0x0008
XINPUT_GAMEPAD_START          = 0x0010
XINPUT_GAMEPAD_BACK           = 0x0020
XINPUT_GAMEPAD_LEFT_THUMB     = 0x0040
XINPUT_GAMEPAD_RIGHT_THUMB    = 0x0080
XINPUT_GAMEPAD_LEFT_SHOULDER  = 0x0100
XINPUT_GAMEPAD_RIGHT_SHOULDER = 0x0200
XINPUT_GAMEPAD_A              = 0x1000
XINPUT_GAMEPAD_B              = 0x2000
XINPUT_GAMEPAD_X              = 0x4000
XINPUT_GAMEPAD_Y              = 0x8000
XINPUT_FACE_MASK              = (XINPUT_GAMEPAD_A|XINPUT_GAMEPAD_B|XINPUT_GAMEPAD_X|XINPUT_GAMEPAD_Y)

if XInput:
    XInput.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(XINPUT_STATE)]
    XInput.XInputGetState.restype  = ctypes.c_uint

PUL = ctypes.POINTER(ctypes.c_ulong)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),("mouseData",ctypes.c_ulong),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]

class INPUT_I(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", INPUT_I)]

SendInput = ctypes.windll.user32.SendInput
MOUSEEVENTF_MOVE = 0x0001

def send_mouse_move(dx:int, dy:int)->None:
    try:
        inp = INPUT(); inp.type = 0; extra = ctypes.c_ulong(0)
        inp.ii.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, ctypes.cast(ctypes.pointer(extra), PUL))
        SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    except Exception:
        logging.exception("SendInput failed")

GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
GetWindowTextW     = ctypes.windll.user32.GetWindowTextW
GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW

def get_foreground_title()->str:
    try:
        hwnd = GetForegroundWindow()
        if not hwnd: return ""
        ln = GetWindowTextLengthW(hwnd)
        if ln <= 0: return ""
        buf = ctypes.create_unicode_buffer(ln+1)
        GetWindowTextW(hwnd, buf, ln+1)
        return buf.value
    except Exception:
        return ""

# ----------------------------- Config -----------------------------
CONFIG_PATH = "input_refiner_config.json"

@dataclass
class Config:
    # general
    target_window_substring:str = "Gears of War: Reloaded"
    enabled:bool = True
    only_when_focused:bool = True
    invert_y:bool = False
    poll_hz:int = 240

    # mode: correlation vs explicit
    use_correlation:bool = True

    # explicit sensitivities
    base_sens:float = 0.35
    ads_sens:float  = 0.10

    # correlation inputs
    game_slider_max:int = 30
    game_slider_current:float = 12.0
    desired_base_slider:float = 18.0
    desired_ads_slider:float  = 10.0

    # shaping
    ads_trigger:str = "LT"
    ads_trigger_threshold:int = 45
    deadzone_right:int = XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE
    curve_exponent:float = 1.30
    pixel_scale:float = 12.0
    jitter_threshold:int = 1
    show_raw_vector:bool = True
    # stability/smoothing
    smoothing_alpha:float = 0.25      # 0..0.95 (higher = smoother, more lag)
    sens_ramp:float = 0.20           # 0..1    (how fast sensitivity changes adapt)
    max_pixels_per_tick:int = 40     # clamp per-tick dx/dy (prevents spikes)
    max_pixels_per_second:int = 3600 # global speed cap; good start for 1080p @ 240Hz (~15 px/tick)
    ads_hysteresis:int = 8           # adds hysteresis around ADS trigger threshold
    # debug overlay
    debug_overlay:bool = True
    debug_history:int = 360
    # engagement / soft zone / inhibition
    engage_threshold_norm:float = 0.020   # start sending only above this (norm units)
    release_threshold_norm:float = 0.015  # stop when below this (hysteresis)
    softzone_k:float = 1.80               # >1 softens near-zero motion
    idle_epsilon:float = 0.020            # treat as idle when processed |v| < epsilon
    idle_frames_to_zero:int = 8           # frames of idle before hard-zero filters
    inhibit_mouse_when_buttons:bool = True # pause mouse while A/B/X/Y held           # adds hysteresis around ADS trigger threshold


def load_config(p:str)->Config:
    if os.path.exists(p):
        try:
            raw = json.load(open(p,"r",encoding="utf-8"))
            base = asdict(Config()); base.update(raw or {})
            return Config(**base)
        except Exception:
            logging.exception("load_config failed")
    return Config()

def save_config(p:str, cfg:Config)->None:
    try:
        with open(p,"w",encoding="utf-8") as f: json.dump(asdict(cfg), f, indent=2)
    except Exception: logging.exception("save_config failed")

# ----------------------------- Math --------------------------------

def normalize_right_stick(x:int, y:int, dz:int) -> tuple[float,float]:
    """Radial deadzone with *continuous* re-scaling.
    Avoids the 'snap' at the deadzone edge by remapping [dz..1] → [0..1]."""
    try:
        nx = max(-1.0, min(1.0, x/32767.0))
        ny = max(-1.0, min(1.0, y/32767.0))
        mag = math.hypot(nx, ny)
        dz_n = max(0.0, min(1.0, dz/32767.0))
        if mag <= dz_n:
            return 0.0, 0.0
        # Re-scale magnitude so that mag==dz maps to 0, mag==1 maps to 1
        new_mag = (mag - dz_n) / max(1e-6, (1.0 - dz_n))
        scale = new_mag / max(1e-6, mag)
        nx *= scale; ny *= scale
        # Clamp after remap
        return max(-1.0, min(1.0, nx)), max(-1.0, min(1.0, ny))
    except Exception:
        return 0.0, 0.0

def apply_curve(v:float, exp:float)->float:
    s = 1.0 if v>=0 else -1.0
    try:
        return s * (abs(v) ** max(0.1, float(exp)))
    except Exception:
        return s * abs(v)

def sens_multiplier_from_sliders(game_val:float, desired_val:float)->float:
    game = max(0.1, float(game_val)); desired = max(0.1, float(desired_val))
    return max(0.05, min(desired / game, 500.0))

# ------------------------ Signals & Worker -------------------------
class InputSample(QtCore.QObject):
    updated  = QtCore.pyqtSignal(float,float,float,float,float,bool,int,int)
    status   = QtCore.pyqtSignal(str)
    triggers = QtCore.pyqtSignal(int,int,int,bool)

class InputWorker(QtCore.QObject):
    def __init__(self, cfg:Config, bus:InputSample):
        super().__init__(); self.cfg = cfg; self.bus_ref = SafeQObjectRef(bus)
        self._run = True; self._state = XINPUT_STATE()
        self._accum_x = 0.0; self._accum_y = 0.0; self._last_pad_idx = None
        self._ui_min_interval = 1.0/120.0  # cap UI updates at 120 Hz
        self._ui_next = 0.0
        # filters/state
        self._f_nx = 0.0; self._f_ny = 0.0
        self._sens_curr = 0.0
        self._t_prev = time.perf_counter()
        self._last_emit = 0.0
        self._engaged = False
        self._idle_frames = 0
        self._ads_prev = False
        self._dx_prev = 0
        self._dy_prev = 0

    @QtCore.pyqtSlot(object)
    def apply_config(self, cfg_dict:object):
        try:
            items = cfg_dict.items() if isinstance(cfg_dict, dict) else (vars(cfg_dict).items() if hasattr(cfg_dict, "__dict__") else [])
            for k, v in items:
                if hasattr(self.cfg, k): setattr(self.cfg, k, v)
            self._emit_status("Config applied to worker")
        except Exception: logging.exception("apply_config failed")

    def _emit_updated(self, *args) -> bool:
        bus = self.bus_ref.get();
        if not bus: return False
        try: bus.updated.emit(*args); return True
        except RuntimeError: return False

    def _emit_status(self, text:str) -> bool:
        bus = self.bus_ref.get();
        if not bus: return False
        try: bus.status.emit(text); return True
        except RuntimeError: return False

    def _emit_triggers(self, lt:int, rt:int, thr:int, ads:bool) -> bool:
        bus = self.bus_ref.get();
        if not bus: return False
        try: bus.triggers.emit(lt, rt, thr, ads); return True
        except RuntimeError: return False

    def stop(self): self._run=False

    @QtCore.pyqtSlot()
    def pulse_restart(self):
        try:
            self._accum_x = 0.0; self._accum_y = 0.0
            self._f_nx = 0.0; self._f_ny = 0.0
            self._sens_curr = 0.0
            self._dx_prev = 0
            self._dy_prev = 0
            self._emit_status("Worker: soft restart")
        except Exception: logging.exception("pulse_restart failed")

    @QtCore.pyqtSlot()
    def run(self):
        try:
            if not XInput:
                logging.warning("XInput DLL not found; idling.")
                while self._run:
                    time.sleep(0.25)
                return
            while self._run:
                if self.bus_ref.isNull():
                    break
                # snapshot cfg to avoid mid‑tick mutations
                cfg = self.cfg
                tick = 1.0 / max(60, int(getattr(cfg,'poll_hz',240) or 240))
                time.sleep(tick)
                now = time.perf_counter()
                dt = max(1e-4, min(0.1, now - self._t_prev))
                self._t_prev = now
                emitted = False
                try:
                    if not getattr(cfg,'enabled',True):
                        if now >= self._ui_next:
                            self._ui_next = now + self._ui_min_interval
                            if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                            emitted = True
                        if (now - self._last_emit) > 0.5 and not emitted:
                            if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                            emitted = True
                        if emitted: self._last_emit = now
                        continue

                    if getattr(cfg,'only_when_focused',True):
                        if str(getattr(cfg,'target_window_substring','')).lower() not in get_foreground_title().lower():
                            if now >= self._ui_next:
                                self._ui_next = now + self._ui_min_interval
                                if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                                emitted = True
                            if (now - self._last_emit) > 0.5 and not emitted:
                                if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                                emitted = True
                            if emitted: self._last_emit = now
                            continue

                    connected = False; gp = None
                    for pad_idx in range(4):
                        try:
                            if XInput.XInputGetState(pad_idx, ctypes.byref(self._state)) == 0:
                                gp = self._state.Gamepad; connected = True
                                if self._last_pad_idx != pad_idx:
                                    self._last_pad_idx = pad_idx; self._emit_status(f"Controller: XInput pad #{pad_idx} connected")
                                break
                        except Exception:
                            continue
                    if not connected or gp is None:
                        if now >= self._ui_next:
                            self._ui_next = now + self._ui_min_interval
                            self._emit_status("Controller: not detected")
                            if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                            emitted = True
                        if (now - self._last_emit) > 0.5 and not emitted:
                            if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                            emitted = True
                        if emitted: self._last_emit = now
                        continue

                    # Inputs
                    nx_raw, ny_raw = normalize_right_stick(gp.sThumbRX, gp.sThumbRY, int(getattr(cfg,'deadzone_right',XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE)))
                    nx = apply_curve(nx_raw, float(getattr(cfg,'curve_exponent',1.3)))
                    ny = apply_curve(ny_raw, float(getattr(cfg,'curve_exponent',1.3)))
                    if bool(getattr(cfg,'invert_y',False)):
                        ny = -ny

                    thr = max(0, min(255, int(getattr(cfg,'ads_trigger_threshold',45))))
                    lt, rt = int(gp.bLeftTrigger), int(gp.bRightTrigger)
                    trig = str(getattr(cfg,'ads_trigger','LT'))
                    hyst = max(0, int(getattr(cfg,'ads_hysteresis',8)))
                    if self._ads_prev:
                        ads = (lt > max(0, thr - hyst)) if (trig=="LT") else (rt > max(0, thr - hyst))
                    else:
                        ads = (lt > min(255, thr + hyst)) if (trig=="LT") else (rt > min(255, thr + hyst))
                    self._ads_prev = ads

                    # Target sensitivity
                    if bool(getattr(cfg,'use_correlation',True)):
                        base_mult = sens_multiplier_from_sliders(float(getattr(cfg,'game_slider_current',12.0)), float(getattr(cfg,'desired_base_slider',18.0)))
                        ads_mult  = sens_multiplier_from_sliders(float(getattr(cfg,'game_slider_current',12.0)), float(getattr(cfg,'desired_ads_slider',10.0)))
                        sens_tgt = ads_mult if ads else base_mult
                    else:
                        sens_tgt = float(getattr(cfg,'ads_sens',0.10) if ads else getattr(cfg,'base_sens',0.35))
                    sens_tgt = max(0.01, float(sens_tgt))

                    # Ramp sensitivity to avoid sudden jumps
                    if self._sens_curr <= 0.0:
                        self._sens_curr = sens_tgt
                    ramp = max(0.0, min(1.0, float(getattr(cfg,'sens_ramp',0.20))))
                    self._sens_curr = self._sens_curr + ramp * (sens_tgt - self._sens_curr)
                    sens_eff = self._sens_curr

                    # Axis smoothing (low-pass)
                    beta = max(0.0, min(0.95, float(getattr(cfg,'smoothing_alpha',0.25))))
                    self._f_nx += beta * (nx - self._f_nx)
                    self._f_ny += beta * (ny - self._f_ny)

                    # Soft zone near zero (reduces tiny-angle yank)
                    magp = math.hypot(self._f_nx, self._f_ny)
                    k = max(1.0, float(getattr(cfg,'softzone_k', 1.8)))
                    if magp > 1e-6 and k > 1.0:
                        scale_soft = magp ** (k - 1.0)
                        self._f_nx *= scale_soft; self._f_ny *= scale_soft
                        magp = math.hypot(self._f_nx, self._f_ny)

                    # Engage/release gating to avoid mouse/controller mode fights
                    engage = max(0.0, min(0.5, float(getattr(cfg,'engage_threshold_norm',0.02))))
                    release = max(0.0, min(0.5, float(getattr(cfg,'release_threshold_norm',0.015))))
                    if not self._engaged:
                        if magp >= engage:
                            self._engaged = True
                    else:
                        if magp < release:
                            self._engaged = False

                    # Mouse
                    scale = float(getattr(cfg,'pixel_scale',12.0)) * sens_eff
                    dx_f = self._f_nx * scale
                    dy_f = -self._f_ny * scale
                    self._accum_x += dx_f; self._accum_y += dy_f
                    dx = int(self._accum_x); dy = int(self._accum_y)
                    self._accum_x -= dx; self._accum_y -= dy

                    # Clamp to prevent spikes (per-tick and per-second)
                    cap_tick = max(2, int(getattr(cfg,'max_pixels_per_tick',40)))
                    cap_ps   = max(200, int(getattr(cfg,'max_pixels_per_second',3600)))
                    cap_dt   = max(2, int(min(cap_tick, cap_ps * dt)))
                    if dx > cap_dt: dx = cap_dt
                    elif dx < -cap_dt: dx = -cap_dt
                    if dy > cap_dt: dy = cap_dt
                    elif dy < -cap_dt: dy = -cap_dt

                    # Slew-rate limiter to prevent sudden dx/dy jumps ("anti-yank")
                    try:
                        slew_cap = max(1, int(cap_dt // 3))  # limit change to ~1/3 of per-tick cap
                        if dx > self._dx_prev + slew_cap: dx = self._dx_prev + slew_cap
                        elif dx < self._dx_prev - slew_cap: dx = self._dx_prev - slew_cap
                        if dy > self._dy_prev + slew_cap: dy = self._dy_prev + slew_cap
                        elif dy < self._dy_prev - slew_cap: dy = self._dy_prev - slew_cap
                    except Exception:
                        pass

                    jt = max(0, int(getattr(cfg,'jitter_threshold',1)))
                    if -jt <= dx <= jt and -jt <= dy <= jt:
                        dx = dy = 0

                    # Optional inhibition while face buttons are held (prevents mode flips during actions)
                    inhibit = bool(getattr(cfg,'inhibit_mouse_when_buttons',True)) and (gp.wButtons & XINPUT_FACE_MASK)

                    # Idle settle hard-zero
                    if magp < float(getattr(cfg,'idle_epsilon',0.02)) and dx == 0 and dy == 0:
                        self._idle_frames += 1
                        if self._idle_frames >= int(getattr(cfg,'idle_frames_to_zero',8)):
                            self._f_nx = 0.0; self._f_ny = 0.0; self._accum_x = 0.0; self._accum_y = 0.0
                            self._idle_frames = 0
                    else:
                        self._idle_frames = 0

                        # light decay of previous dx/dy toward 0 when moving
                        self._dx_prev = int(self._dx_prev * 0.9)
                        self._dy_prev = int(self._dy_prev * 0.9)
                    if dx or dy:
                        if self._engaged and not inhibit:
                            send_mouse_move(dx, dy)
                        self._dx_prev, self._dy_prev = dx, dy

                    # Throttled UI emit
                    if now >= self._ui_next:
                        self._ui_next = now + self._ui_min_interval
                        if not self._emit_updated(nx_raw, ny_raw, nx, ny, sens_eff, ads, dx, dy): break
                        if not self._emit_triggers(lt, rt, thr, ads): break
                        emitted = True

                    if emitted:
                        self._last_emit = now
                    elif (now - self._last_emit) > 0.5:
                        # UI heartbeat (keeps visualizers alive if gating stalls)
                        if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                        self._last_emit = now
                except Exception:
                    logging.exception("Worker tick failed"); time.sleep(0.02)
        except Exception:
            logging.exception("Worker thread crashed")

# --------------------------- Visualizers ---------------------------
class _SafePaintWidget(QtWidgets.QWidget):
    def paintEvent(self, e:QtGui.QPaintEvent):
        try:
            self._safe_paint(e)
        except Exception:
            # swallow paint errors to avoid app termination under stress
            logging.exception("paintEvent failed")
    def _safe_paint(self, e:QtGui.QPaintEvent):
        pass

class StickVisualizer(_SafePaintWidget):
    def __init__(self, cfg:Config):
        super().__init__(); self.cfg=cfg; self.setMinimumSize(300, 300)
        self.nx_raw=self.ny_raw=0.0; self.nx_proc=self.ny_proc=0.0; self.sens=0.0; self.ads=False; self.dx=self.dy=0
    @QtCore.pyqtSlot(float,float,float,float,float,bool,int,int)
    def on_sample(self, nxr, nyr, nxp, nyp, sens, ads, dx, dy):
        self.nx_raw,self.ny_raw,self.nx_proc,self.ny_proc = nxr,nyr,nxp,nyp; self.sens,self.ads,self.dx,self.dy = sens,ads,dx,dy; self.update()
    def _safe_paint(self, e:QtGui.QPaintEvent):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10,10,-10,-10)
        size = max(10, min(rect.width(), rect.height()))
        cx = rect.left()+rect.width()//2; cy = rect.top()+rect.height()//2; r = max(4, size//2)
        p.fillRect(self.rect(), QtGui.QColor(18,18,18))
        pen = QtGui.QPen(QtGui.QColor(220,220,220)); pen.setWidth(2); p.setPen(pen); p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(QtCore.QPoint(cx,cy), r, r)
        dz_ratio = max(0.0, min(1.0, self.cfg.deadzone_right/32767.0)); dz_r = int(r * dz_ratio)
        pen = QtGui.QPen(QtGui.QColor(200,80,80)); pen.setStyle(QtCore.Qt.PenStyle.DashLine); p.setPen(pen)
        p.drawEllipse(QtCore.QPoint(cx,cy), dz_r, dz_r)
        if self.cfg.show_raw_vector:
            pen = QtGui.QPen(QtGui.QColor(150,150,150)); pen.setWidth(2); p.setPen(pen)
            rx = int(cx + self.nx_raw*(r-4)); ry = int(cy - self.ny_raw*(r-4))
            p.drawLine(cx,cy,rx,ry); p.setBrush(pen.color()); p.drawEllipse(QtCore.QPoint(rx,ry),3,3)
        pen = QtGui.QPen(QtGui.QColor(90,200,255) if not self.ads else QtGui.QColor(255,180,70)); pen.setWidth(3); p.setPen(pen)
        px = int(cx + self.nx_proc*(r-4)); py = int(cy - self.ny_proc*(r-4))
        p.drawLine(cx,cy,px,py); p.setBrush(pen.color()); p.drawEllipse(QtCore.QPoint(px,py),4,4)
        p.setPen(QtGui.QColor(230,230,230)); font=p.font(); font.setPointSize(9); p.setFont(font)
        mode = "Correlation" if self.cfg.use_correlation else "Explicit"
        lines = [f"Mode: {mode}   Sens: {self.sens:.2f}" + ("  (ADS)" if self.ads else ""),
                 f"Curve: {self.cfg.curve_exponent:.2f}   DZ: {self.cfg.deadzone_right}   Poll: {self.cfg.poll_hz} Hz",
                 f"Jitter: ±{self.cfg.jitter_threshold}   dx/dy: {self.dx:+d}/{self.dy:+d}"]
        y = rect.bottom()-(len(lines)*16)
        for line in lines: p.drawText(rect.left()+6, y, rect.width()-12, 18, QtCore.Qt.AlignmentFlag.AlignLeft, line); y+=16
        p.end()

class TriggerVisualizer(_SafePaintWidget):
    def __init__(self, cfg:Config):
        super().__init__(); self.cfg=cfg; self.setMinimumSize(200, 160)
        self.lt = 0; self.rt = 0; self.thr = cfg.ads_trigger_threshold; self.ads = False
    @QtCore.pyqtSlot(int,int,int,bool)
    def on_triggers(self, lt:int, rt:int, thr:int, ads:bool):
        self.lt, self.rt, self.thr, self.ads = int(lt), int(rt), int(thr), bool(ads); self.update()
    def _safe_paint(self, e:QtGui.QPaintEvent):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10,10,-10,-10)
        p.fillRect(self.rect(), QtGui.QColor(18,18,18))
        w = rect.width(); h = rect.height(); bar_w = int(w*0.35); gap = int(w*0.3 - bar_w)
        lt_rect = QtCore.QRect(rect.left(), rect.top(), bar_w, h)
        rt_rect = QtCore.QRect(rect.left()+bar_w+gap, rect.top(), bar_w, h)
        def draw_bar(value:int, label:str, highlighted:bool):
            p.setPen(QtCore.Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(40,40,40)); p.drawRect(lt_rect if label=="LT" else rt_rect)
            frac = max(0.0, min(1.0, value/255.0)); fh = int(h*frac)
            r = lt_rect if label=="LT" else rt_rect
            fill_rect = QtCore.QRect(r.left(), r.bottom()-fh, r.width(), fh)
            p.setBrush(QtGui.QColor(90,200,255) if not highlighted else QtGui.QColor(255,180,70)); p.drawRect(fill_rect)
            p.setPen(QtGui.QPen(QtGui.QColor(120,120,120))); p.setBrush(QtCore.Qt.BrushStyle.NoBrush); p.drawRect(r)
            p.setPen(QtGui.QColor(230,230,230))
            p.drawText(r.adjusted(0,0,0,-h+16), QtCore.Qt.AlignmentFlag.AlignLeft, f"{label}")
            p.drawText(r.adjusted(0,0,0,0), QtCore.Qt.AlignmentFlag.AlignBottom|QtCore.Qt.AlignmentFlag.AlignHCenter, f"{value}")
        draw_bar(self.lt, "LT", self.ads and self.cfg.ads_trigger=="LT")
        draw_bar(self.rt, "RT", self.ads and self.cfg.ads_trigger=="RT")
        frac_thr = max(0.0, min(1.0, self.thr/255.0)); y_thr = rect.bottom() - int(h*frac_thr)
        p.setPen(QtGui.QPen(QtGui.QColor(200,80,80), 2, QtCore.Qt.PenStyle.DashLine)); p.drawLine(rect.left()-4, y_thr, rect.right()+4, y_thr)
        p.setPen(QtGui.QColor(230,230,230)); p.drawText(rect.left(), rect.top()-2, f"Threshold: {self.thr}")

class RightStickThresholdBar(_SafePaintWidget):
    def __init__(self, cfg:Config):
        super().__init__(); self.cfg=cfg; self.setMinimumSize(100, 180)
        self.mag = 0.0; self.dx = 0; self.dy = 0
    @QtCore.pyqtSlot(float,float,float,float,float,bool,int,int)
    def on_sample(self, nxr, nyr, nxp, nyp, sens, ads, dx, dy):
        self.mag = max(0.0, min(1.0, math.hypot(nxr, nyr))); self.dx, self.dy = int(dx), int(dy); self.update()
    def _safe_paint(self, e:QtGui.QPaintEvent):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12,12,-12,-12)
        p.fillRect(self.rect(), QtGui.QColor(18,18,18))
        w = rect.width(); h = rect.height(); bar_rect = QtCore.QRect(rect.left()+w//3, rect.top(), w//3, h)
        p.setPen(QtCore.Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(40,40,40)); p.drawRect(bar_rect)
        p.setPen(QtGui.QPen(QtGui.QColor(120,120,120))); p.setBrush(QtCore.Qt.BrushStyle.NoBrush); p.drawRect(bar_rect)
        fh = int(h * self.mag); fill = QtCore.QRect(bar_rect.left(), bar_rect.bottom()-fh, bar_rect.width(), fh)
        above = self.mag > (self.cfg.deadzone_right/32767.0)
        p.setPen(QtCore.Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(90,200,255) if not above else QtGui.QColor(255,180,70)); p.drawRect(fill)
        thr_frac = max(0.0, min(1.0, self.cfg.deadzone_right/32767.0)); y_thr = bar_rect.bottom() - int(h*thr_frac)
        p.setPen(QtGui.QPen(QtGui.QColor(200,80,80), 2, QtCore.Qt.PenStyle.DashLine)); p.drawLine(bar_rect.left()-6, y_thr, bar_rect.right()+6, y_thr)
        p.setPen(QtGui.QColor(230,230,230)); p.drawText(rect.left(), rect.top()-2, "Right Stick Threshold")
        p.drawText(rect.left(), rect.bottom()+2, f"|raw|: {self.mag:.2f}  thr: {thr_frac:.2f}  dx/dy: {self.dx:+d}/{self.dy:+d}")

class DebugOverlay(_SafePaintWidget):
    def __init__(self, cfg:Config):
        super().__init__(); self.cfg = cfg; self.setMinimumHeight(180)
        self._raw: list[float] = []; self._proc: list[float] = []
    @QtCore.pyqtSlot(float,float,float,float,float,bool,int,int)
    def on_sample(self, nxr, nyr, nxp, nyp, sens, ads, dx, dy):
        try:
            mag_r = max(0.0, min(1.0, math.hypot(nxr, nyr)))
            mag_p = max(0.0, min(1.0, math.hypot(nxp, nyp)))
            cap = max(60, int(getattr(self.cfg, 'debug_history', 360)))
            self._raw.append(mag_r); self._proc.append(mag_p)
            if len(self._raw) > cap: del self._raw[0]
            if len(self._proc) > cap: del self._proc[0]
            self.update()
        except Exception:
            logging.exception('debug on_sample failed')
    def _safe_paint(self, e: QtGui.QPaintEvent):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10,10,-10,-10)
        p.fillRect(self.rect(), QtGui.QColor(18,18,18))
        p.setPen(QtGui.QPen(QtGui.QColor(60,60,60))); p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        # grid
        for frac in (0.0, 0.5, 1.0):
            y = rect.bottom() - int(frac * rect.height())
            pen = QtGui.QPen(QtGui.QColor(60,60,60)); pen.setStyle(QtCore.Qt.PenStyle.DashLine); p.setPen(pen)
            p.drawLine(rect.left(), y, rect.right(), y)
        # deadzone guide
        dzf = max(0.0, min(1.0, getattr(self.cfg, 'deadzone_right', 0) / 32767.0))
        y_dz = rect.bottom() - int(dzf * rect.height())
        p.setPen(QtGui.QPen(QtGui.QColor(200,80,80), 1, QtCore.Qt.PenStyle.DotLine)); p.drawLine(rect.left(), y_dz, rect.right(), y_dz)
        # paths
        def make_path(vals: list[float]):
            path = QtGui.QPainterPath()
            if not vals: return path
            cap = max(1, int(getattr(self.cfg, 'debug_history', 360)))
            n = len(vals)
            step = rect.width() / max(1, cap-1)
            x = rect.right() - step * (n-1)
            y = rect.bottom() - vals[0] * rect.height()
            path.moveTo(x, y)
            for i in range(1, n):
                x = rect.right() - step * (n-1-i)
                y = rect.bottom() - vals[i] * rect.height()
                path.lineTo(x, y)
            return path
        raw_path  = make_path(self._raw)
        proc_path = make_path(self._proc)
        p.setPen(QtGui.QPen(QtGui.QColor(150,150,150), 2)); p.drawPath(raw_path)
        p.setPen(QtGui.QPen(QtGui.QColor(90,200,255), 2)); p.drawPath(proc_path)
        # legend
        p.setPen(QtGui.QPen(QtGui.QColor(230,230,230)))
        p.drawText(rect.left()+6, rect.top()-2, "Debug: |raw| vs |processed|")

# ---------------------------- UI Helpers ---------------------------

def slider_row(label:str, minv, maxv, step, init, decimals=2):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(label); lab.setMinimumWidth(170)
    sld = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    sld.setRange(0, int((maxv-minv)/step)); sld.setValue(int((init-minv)/step))
    box = QtWidgets.QDoubleSpinBox(); box.setRange(float(minv), float(maxv)); box.setDecimals(decimals)
    box.setSingleStep(step); box.setValue(float(init))
    row.addWidget(lab); row.addWidget(sld, 1); row.addWidget(box)
    return row, sld, box

def slider_row_int(label:str, minv:int, maxv:int, step:int, init:int):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(label); lab.setMinimumWidth(170)
    sld = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    sld.setRange(0, int((maxv-minv)//step)); sld.setValue(int((init-minv)//step))
    box = QtWidgets.QSpinBox(); box.setRange(int(minv), int(maxv)); box.setSingleStep(step); box.setValue(int(init))
    row.addWidget(lab); row.addWidget(sld, 1); row.addWidget(box)
    return row, sld, box

# ------------------------------- Main UI -------------------------------
class MainWindow(QtWidgets.QWidget):
    applyConfig = QtCore.pyqtSignal(object)
    hardRestart = QtCore.pyqtSignal()   # now triggers soft restart inside worker
    def __init__(self, cfg:Config):
        super().__init__(); self.runtime_cfg = cfg; self.staged_cfg  = replace(cfg)
        self.setWindowTitle("Jacinto Input Refiner (PyQt6) — Stable")
        self.setMinimumWidth(1240); QtWidgets.QApplication.setStyle("Fusion")
        hdr = QtWidgets.QLabel("<b>External input shaper</b> — mouse move only. Use <b>Apply</b> to push changes (soft restart; no thread teardown).")
        hdr.setWordWrap(True)
        grid = QtWidgets.QGridLayout()
        self.titleEdit  = QtWidgets.QLineEdit(self.staged_cfg.target_window_substring)
        self.enabledBox = QtWidgets.QCheckBox("Enabled"); self.enabledBox.setChecked(self.staged_cfg.enabled)
        self.focusOnly  = QtWidgets.QCheckBox("Only when target window focused"); self.focusOnly.setChecked(self.staged_cfg.only_when_focused)
        self.invertY    = QtWidgets.QCheckBox("Invert Y"); self.invertY.setChecked(self.staged_cfg.invert_y)
        self.showRaw    = QtWidgets.QCheckBox("Show RAW stick vector"); self.showRaw.setChecked(self.staged_cfg.show_raw_vector)
        self.useCorr    = QtWidgets.QCheckBox("Use in-game slider correlation"); self.useCorr.setChecked(self.staged_cfg.use_correlation)
        self.adsTrigger = QtWidgets.QComboBox(); self.adsTrigger.addItems(["LT","RT"]); self.adsTrigger.setCurrentText(self.staged_cfg.ads_trigger)
        self.pollRow, self.pollSld, self.pollBox = slider_row_int("Poll rate (Hz)", 60, 360, 30, self.staged_cfg.poll_hz)
        grid.addWidget(QtWidgets.QLabel("Target window contains:"), 0,0); grid.addWidget(self.titleEdit, 0,1,1,3)
        grid.addWidget(self.enabledBox, 1,0); grid.addWidget(self.focusOnly, 1,1); grid.addWidget(self.invertY, 1,2); grid.addWidget(self.showRaw,1,3)
        grid.addWidget(self.useCorr, 2,0); grid.addWidget(QtWidgets.QLabel("ADS trigger:"), 2,1); grid.addWidget(self.adsTrigger,2,2)
        grid.addLayout(self.pollRow, 3,0,1,4)
        self.explicitBox = QtWidgets.QGroupBox("Explicit sensitivities (used when correlation is OFF)")
        eLay = QtWidgets.QVBoxLayout(self.explicitBox)
        row, self.baseSld, self.baseBox = slider_row("Base sensitivity", 0.05, 200.0, 0.05, self.staged_cfg.base_sens, 2); eLay.addLayout(row)
        row, self.adsSld,  self.adsBox  = slider_row("ADS sensitivity",  0.05, 200.0, 0.05, self.staged_cfg.ads_sens,   2); eLay.addLayout(row)
        self.corrBox = QtWidgets.QGroupBox("In-game slider correlation (used when correlation is ON)")
        cLay = QtWidgets.QVBoxLayout(self.corrBox)
        row, self.maxSld, self.maxBox = slider_row_int("Game slider max", 10, 120, 1, self.staged_cfg.game_slider_max); cLay.addLayout(row)
        row, self.curSld, self.curBox = slider_row("Your in-game value", 0.1, 120.0, 0.1, self.staged_cfg.game_slider_current, 2); cLay.addLayout(row)
        row, self.desBSld, self.desBBox = slider_row("Desired base feel", 0.1, 120.0, 0.1, self.staged_cfg.desired_base_slider, 2); cLay.addLayout(row)
        row, self.desASld, self.desABox = slider_row("Desired ADS feel",  0.1, 120.0, 0.1, self.staged_cfg.desired_ads_slider,  2); cLay.addLayout(row)
        common = QtWidgets.QGroupBox("Shaping")
        sLay = QtWidgets.QVBoxLayout(common)
        row, self.curveSld, self.curveBox = slider_row("Curve exponent", 1.00, 3.0,  0.05, self.staged_cfg.curve_exponent, 2); sLay.addLayout(row)
        row, self.deadSld,  self.deadBox  = slider_row_int("Right-stick deadzone", 0, 32767, 50, self.staged_cfg.deadzone_right); sLay.addLayout(row)
        row, self.pixSld,   self.pixBox   = slider_row("Pixel scale",    4.0, 40.0, 0.5,  self.staged_cfg.pixel_scale,     1); sLay.addLayout(row)
        row, self.jitSld,   self.jitBox   = slider_row_int("Jitter threshold (pixels)", 0, 6, 1, self.staged_cfg.jitter_threshold); sLay.addLayout(row)
        row, self.adsThrSld, self.adsThrBox = slider_row_int("ADS trigger threshold", 0, 255, 5, self.staged_cfg.ads_trigger_threshold); sLay.addLayout(row)
        row, self.smoothSld, self.smoothBox = slider_row("Axis smoothing (0..1)", 0.0, 0.95, 0.05, self.staged_cfg.smoothing_alpha, 2); sLay.addLayout(row)
        row, self.rampSld,   self.rampBox   = slider_row("Sensitivity ramp (0..1)", 0.0, 1.0, 0.05, self.staged_cfg.sens_ramp, 2); sLay.addLayout(row)
        row, self.maxPixSld, self.maxPixBox = slider_row_int("Max pixels per tick", 2, 100, 2, self.staged_cfg.max_pixels_per_tick); sLay.addLayout(row)
        row, self.maxPpsSld, self.maxPpsBox = slider_row_int("Max pixels per second", 200, 20000, 100, self.staged_cfg.max_pixels_per_second); sLay.addLayout(row)
        row, self.hystSld,   self.hystBox   = slider_row_int("ADS hysteresis", 0, 50, 1, self.staged_cfg.ads_hysteresis); sLay.addLayout(row)
        # New stability controls
        row, self.engSld, self.engBox = slider_row("Engage threshold (norm)", 0.0, 0.2, 0.005, self.staged_cfg.engage_threshold_norm, 3); sLay.addLayout(row)
        row, self.relSld, self.relBox = slider_row("Release threshold (norm)", 0.0, 0.2, 0.005, self.staged_cfg.release_threshold_norm, 3); sLay.addLayout(row)
        row, self.softkSld, self.softkBox = slider_row("Soft zone k", 1.0, 3.0, 0.05, self.staged_cfg.softzone_k, 2); sLay.addLayout(row)
        row, self.idleESld, self.idleEBox = slider_row("Idle epsilon (norm)", 0.0, 0.1, 0.005, self.staged_cfg.idle_epsilon, 3); sLay.addLayout(row)
        row, self.idleFSld, self.idleFBox = slider_row_int("Idle frames to zero", 0, 60, 1, self.staged_cfg.idle_frames_to_zero); sLay.addLayout(row)
        self.inhibitFace = QtWidgets.QCheckBox("Pause mouse while A/B/X/Y held"); self.inhibitFace.setChecked(self.staged_cfg.inhibit_mouse_when_buttons)
        sLay.addWidget(self.inhibitFace)
        row, self.maxPpsSld, self.maxPpsBox = slider_row_int("Max pixels per second", 200, 20000, 100, self.staged_cfg.max_pixels_per_second); sLay.addLayout(row)
        btns = QtWidgets.QHBoxLayout()
        self.testBtn = QtWidgets.QPushButton("Test Mouse Move")
        self.applyBtn = QtWidgets.QPushButton("Apply (soft restart)")
        self.saveBtn  = QtWidgets.QPushButton("Save Config")
        self.appliedLabel = QtWidgets.QLabel(""); self.appliedLabel.setStyleSheet("color: #7CFC00; font-weight: bold;")
        self.statusLabel = QtWidgets.QLabel("Controller: —")
        self.quitBtn  = QtWidgets.QPushButton("Quit")
        btns.addWidget(self.testBtn); btns.addWidget(self.applyBtn); btns.addWidget(self.saveBtn)
        btns.addStretch(1); btns.addWidget(self.statusLabel); btns.addWidget(self.appliedLabel); btns.addWidget(self.quitBtn)
        self.stickViz = StickVisualizer(self.staged_cfg)
        self.trigViz  = TriggerVisualizer(self.staged_cfg)
        self.stickThrBar = RightStickThresholdBar(self.staged_cfg)
        self.debugViz = DebugOverlay(self.staged_cfg)
        self.debugViz.setVisible(getattr(self.staged_cfg, 'debug_overlay', True))
        left = QtWidgets.QVBoxLayout(); left.addWidget(hdr); left.addLayout(grid); left.addWidget(self.explicitBox); left.addWidget(self.corrBox); left.addWidget(common); left.addLayout(btns)
        right = QtWidgets.QVBoxLayout(); right.addWidget(self.stickViz, 1); right.addWidget(self.trigViz, 0); right.addWidget(self.stickThrBar, 0); right.addWidget(self.debugViz, 0)
        root = QtWidgets.QHBoxLayout(self); root.addLayout(left, 1); root.addLayout(right, 0)
        # Wiring
        self.titleEdit.textChanged.connect(lambda t: self._stage('target_window_substring', t))
        self.enabledBox.stateChanged.connect(lambda _: self._stage('enabled', self.enabledBox.isChecked()))
        self.focusOnly.stateChanged.connect(lambda _: self._stage('only_when_focused', self.focusOnly.isChecked()))
        self.invertY.stateChanged.connect(lambda _: self._stage('invert_y', self.invertY.isChecked()))
        self.showRaw.stateChanged.connect(lambda _: self._stage('show_raw_vector', self.showRaw.isChecked()))
        self.useCorr.stateChanged.connect(lambda _: (self._stage('use_correlation', self.useCorr.isChecked()), self._update_mode_visibility()))
        self.adsTrigger.currentTextChanged.connect(lambda t: self._stage('ads_trigger', t))
        self.pollSld.valueChanged.connect(lambda v: self.pollBox.setValue(60 + v*30))
        self.pollBox.valueChanged.connect(lambda v: self._stage('poll_hz', int(v)))
        self.baseSld.valueChanged.connect(lambda v: self.baseBox.setValue(0.05 + v*0.05))
        self.baseBox.valueChanged.connect(lambda v: self._stage('base_sens', float(v)))
        self.adsSld.valueChanged.connect(lambda v: self.adsBox.setValue(0.05 + v*0.05))
        self.adsBox.valueChanged.connect(lambda v: self._stage('ads_sens', float(v)))
        self.maxSld.valueChanged.connect(lambda v: self.maxBox.setValue(10 + v*1))
        self.maxBox.valueChanged.connect(lambda v: self._stage('game_slider_max', int(v)))
        self.curSld.valueChanged.connect(lambda v: self.curBox.setValue(0.1 + v*0.1))
        self.curBox.valueChanged.connect(lambda v: self._stage('game_slider_current', float(v)))
        self.desBSld.valueChanged.connect(lambda v: self.desBBox.setValue(0.1 + v*0.1))
        self.desBBox.valueChanged.connect(lambda v: self._stage('desired_base_slider', float(v)))
        self.desASld.valueChanged.connect(lambda v: self.desABox.setValue(0.1 + v*0.1))
        self.desABox.valueChanged.connect(lambda v: self._stage('desired_ads_slider', float(v)))
        self.curveSld.valueChanged.connect(lambda v: self.curveBox.setValue(1.0 + v*0.05))
        self.curveBox.valueChanged.connect(lambda v: self._stage('curve_exponent', float(v)))
        self.deadSld.valueChanged.connect(lambda v: self.deadBox.setValue(0 + v*50))
        self.deadBox.valueChanged.connect(lambda v: self._stage('deadzone_right', int(v)))
        self.pixSld.valueChanged.connect(lambda v: self.pixBox.setValue(4.0 + v*0.5))
        self.pixBox.valueChanged.connect(lambda v: self._stage('pixel_scale', float(v)))
        self.jitSld.valueChanged.connect(lambda v: self.jitBox.setValue(0 + v*1))
        self.jitBox.valueChanged.connect(lambda v: self._stage('jitter_threshold', int(v)))
        self.adsThrSld.valueChanged.connect(lambda v: self.adsThrBox.setValue(0 + v*5))
        self.adsThrBox.valueChanged.connect(lambda v: self._stage('ads_trigger_threshold', int(v)))
        self.smoothSld.valueChanged.connect(lambda v: self.smoothBox.setValue(0.0 + v*0.05))
        self.smoothBox.valueChanged.connect(lambda v: self._stage('smoothing_alpha', float(v)))
        self.rampSld.valueChanged.connect(lambda v: self.rampBox.setValue(0.0 + v*0.05))
        self.rampBox.valueChanged.connect(lambda v: self._stage('sens_ramp', float(v)))
        self.maxPixSld.valueChanged.connect(lambda v: self.maxPixBox.setValue(2 + v*2))
        self.maxPixBox.valueChanged.connect(lambda v: self._stage('max_pixels_per_tick', int(v)))
        self.hystSld.valueChanged.connect(lambda v: self.hystBox.setValue(0 + v*1))
        self.hystBox.valueChanged.connect(lambda v: self._stage('ads_hysteresis', int(v)))
        self.maxPpsSld.valueChanged.connect(lambda v: self.maxPpsBox.setValue(200 + v*100))
        self.maxPpsBox.valueChanged.connect(lambda v: self._stage('max_pixels_per_second', int(v)))
        # New stability wiring
        self.engSld.valueChanged.connect(lambda v: self.engBox.setValue(0.0 + v*0.005))
        self.engBox.valueChanged.connect(lambda v: self._stage('engage_threshold_norm', float(v)))
        self.relSld.valueChanged.connect(lambda v: self.relBox.setValue(0.0 + v*0.005))
        self.relBox.valueChanged.connect(lambda v: self._stage('release_threshold_norm', float(v)))
        self.softkSld.valueChanged.connect(lambda v: self.softkBox.setValue(1.0 + v*0.05))
        self.softkBox.valueChanged.connect(lambda v: self._stage('softzone_k', float(v)))
        self.idleESld.valueChanged.connect(lambda v: self.idleEBox.setValue(0.0 + v*0.005))
        self.idleEBox.valueChanged.connect(lambda v: self._stage('idle_epsilon', float(v)))
        self.idleFSld.valueChanged.connect(lambda v: self.idleFBox.setValue(0 + v*1))
        self.idleFBox.valueChanged.connect(lambda v: self._stage('idle_frames_to_zero', int(v)))
        self.inhibitFace.stateChanged.connect(lambda _: self._stage('inhibit_mouse_when_buttons', self.inhibitFace.isChecked()))
        self.testBtn.clicked.connect(lambda: send_mouse_move(50, 0))
        self.applyBtn.clicked.connect(self._apply)
        self.saveBtn.clicked.connect(self._save_only)
        self.quitBtn.clicked.connect(QtWidgets.QApplication.instance().quit)
        self._update_mode_visibility()
    def _update_mode_visibility(self):
        on = self.staged_cfg.use_correlation
        self.corrBox.setVisible(on); self.explicitBox.setVisible(not on)
    def _stage(self, key:str, value):
        setattr(self.staged_cfg, key, value); self.appliedLabel.setText("")
        if key in ("deadzone_right","curve_exponent","show_raw_vector"):
            self.stickViz.update(); self.stickThrBar.update()
    def _apply(self):
        self.runtime_cfg = replace(self.staged_cfg)
        save_config(CONFIG_PATH, self.runtime_cfg)
        self.applyConfig.emit(asdict(self.runtime_cfg))
        self.hardRestart.emit()  # soft restart (worker flush)
        self.appliedLabel.setText("Applied ✓")
    def _save_only(self):
        save_config(CONFIG_PATH, self.staged_cfg)
        QtWidgets.QMessageBox.information(self, "Saved", f"Saved staged config to {CONFIG_PATH}\n(Press Apply to activate)")

# --------------------------- Worker Manager ---------------------------
class WorkerManager(QtCore.QObject):
    def __init__(self, cfg: Config, bus: InputSample, win: 'MainWindow'):
        super().__init__(); self._cfg = cfg; self._bus = bus; self._win_ref = SafeQObjectRef(win)
        self._worker: InputWorker | None = None; self._thread: QtCore.QThread | None = None
    def start(self):
        win = self._win_ref.get()
        if win is not None: self._cfg = win.runtime_cfg
        worker = InputWorker(self._cfg, self._bus)
        th = QtCore.QThread(); worker.moveToThread(th)
        th.started.connect(worker.run)
        th.start(); self._worker, self._thread = worker, th
        # Soft restart wiring (UI -> worker)
        if win is not None:
            try:
                win.hardRestart.connect(worker.pulse_restart, QtCore.Qt.ConnectionType.QueuedConnection)
            except Exception:
                logging.exception("connect pulse_restart failed")
    def apply_to_worker(self, cfg_dict: object):
        if self._worker is not None:
            try: self._worker.apply_config(cfg_dict)
            except Exception: logging.exception("apply_to_worker forwarding failed")
        win = self._win_ref.get()
        if win is not None: self._cfg = win.runtime_cfg
    def stop(self):
        if self._worker is None or self._thread is None: return
        try:
            self._worker.stop(); self._thread.quit(); self._thread.wait(2000)
            self._worker.deleteLater(); self._thread.deleteLater()
        except Exception: logging.exception("WorkerManager.stop failed")
        finally: self._worker = None; self._thread = None

# ------------------------------ Boot ------------------------------

def main():
    if sys.platform != "win32":
        print("Windows only."); sys.exit(1)
    cfg = load_config(CONFIG_PATH)
    app = QtWidgets.QApplication(sys.argv); app.setQuitOnLastWindowClosed(True)
    bus = InputSample()
    win = MainWindow(cfg); win.resize(1280, 600); win.show()
    manager = WorkerManager(cfg, bus, win); manager.start()
    win.applyConfig.connect(manager.apply_to_worker)
    # Note: hardRestart is already connected to worker in start()
    bus.updated.connect(win.stickViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.status.connect(win.statusLabel.setText, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.triggers.connect(win.trigViz.on_triggers, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.updated.connect(win.stickThrBar.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.updated.connect(win.debugViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    app.aboutToQuit.connect(manager.stop)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
