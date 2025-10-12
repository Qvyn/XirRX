# crosshair_x_designer_stack_patched.py — with Crash Watchdog + Audio‑Reaction settings
# Safe, runnable PyQt6 build. New in this patch:
#  - Crash Watchdog: logs crashes, optional auto‑restart, overlay stall recovery
#  - Audio Reaction: optional mic/loopback amplitude drives scale/opacity/glow pulse
#
# Notes:
#  • Audio reaction uses the optional 'sounddevice' (and numpy) backend if available.
#    If not installed, the Audio panel appears with guidance and controls are disabled.
#    To enable:  pip install sounddevice numpy
#  • No hooks/injection. Still polls GetAsyncKeyState/XInput for effects.

from __future__ import annotations
import sys, os, json, ctypes, math, time, traceback
from dataclasses import dataclass, asdict, fields
from typing import Dict, Any, Optional
from PyQt6 import QtCore, QtGui, QtWidgets

# -------- Optional audio backend --------
AUDIO_AVAILABLE = False
try:
    import sounddevice as sd  # type: ignore
    import numpy as np        # type: ignore
    AUDIO_AVAILABLE = True
except Exception:
    AUDIO_AVAILABLE = False

APP_NAME = "CrossXir"
ORG = "eztools"
DOMAIN = "crossxir"
APPDATA_DIR = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', ORG)
os.makedirs(APPDATA_DIR, exist_ok=True)
PRESETS_PATH = os.path.join(APPDATA_DIR, 'crossxir_presets.json')
LAST_STATE = os.path.join(APPDATA_DIR, 'crossxir_last_state.json')
CRASH_LOG = os.path.join(APPDATA_DIR, 'crossxir_crash.log')

IS_WIN = os.name == 'nt'

# ---------------- Windows helpers ----------------
GetAsyncKeyState = None
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
if IS_WIN:
    try:
        user32 = ctypes.windll.user32
        GetAsyncKeyState = user32.GetAsyncKeyState
    except Exception:
        GetAsyncKeyState = None

# XInput (controller triggers)
XINPUT_AVAILABLE = False
XINPUT_TRIGGER_THRESHOLD = 30
if IS_WIN:
    try:
        _xinput = None
        for _name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll", "xinput1_2.dll", "xinput1_1.dll"):
            try:
                _xinput = ctypes.windll.LoadLibrary(_name)
                break
            except Exception:
                _xinput = None
        if _xinput is not None:
            class XINPUT_GAMEPAD(ctypes.Structure):
                _fields_ = [
                    ("wButtons", ctypes.c_ushort),
                    ("bLeftTrigger", ctypes.c_ubyte),
                    ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short),
                    ("sThumbLY", ctypes.c_short),
                    ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short),
                ]
            class XINPUT_STATE(ctypes.Structure):
                _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]
            _XInputGetState = _xinput.XInputGetState
            _XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(XINPUT_STATE)]
            _XInputGetState.restype = ctypes.c_uint
            class XInputReader:
                _lt = 0; _rt = 0
                @classmethod
                def poll(cls):
                    st = XINPUT_STATE()
                    if _XInputGetState(0, ctypes.byref(st)) == 0:
                        cls._lt = st.Gamepad.bLeftTrigger
                        cls._rt = st.Gamepad.bRightTrigger
                @classmethod
                def lt_pressed(cls): return cls._lt >= XINPUT_TRIGGER_THRESHOLD
                @classmethod
                def rt_pressed(cls): return cls._rt >= XINPUT_TRIGGER_THRESHOLD
            XINPUT_AVAILABLE = True
    except Exception:
        XINPUT_AVAILABLE = False

# ---------------- Crash Watchdog ----------------
def _write_crash_log(msg: str):
    try:
        with open(CRASH_LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + "\n")
            f.write(msg + "\n\n")
    except Exception:
        pass

def _restart_app():
    try:
        python = sys.executable
        os.execl(python, python, *sys.argv)
    except Exception:
        os._exit(1)

def _install_excepthook():
    def _hook(exc_type, exc, tb):
        tb_str = ''.join(traceback.format_exception(exc_type, exc, tb))
        _write_crash_log(tb_str)
        try:
            st = load_last_state()
            if getattr(st, 'watchdog_auto_restart_app', True):
                _restart_app()
        except Exception:
            _restart_app()
    sys.excepthook = _hook

# ---------------- State ----------------
@dataclass
class CrosshairState:
    style: str = "Crosshair"  # Dot, Crosshair, Crosshair+Gap, T-Cross, Circle, HollowCircle, Circle+Dot, Dot+Outline
    size: int = 12
    thickness: int = 3
    gap: int = 4
    rotation: int = 0
    color: str = "#b366ff"
    opacity: float = 1.0
    click_through: bool = True
    offset_x: int = 0
    offset_y: int = 0
    screen_index: int = 0

    # outline
    outline_enabled: bool = True
    outline_thickness: int = 2
    outline_color: str = "#000000"

    # advanced
    sniper_mask_enabled: bool = False
    vignette_strength: int = 60  # 0-100
    enable_extra_styles: bool = False
    auto_fade_on_move: bool = False
    fade_min_opacity: float = 0.35
    fade_still_delay_ms: int = 250
    anchor_mode: str = "Center"  # Center/Edges/Corners

    # glow/anim
    glow_strength: int = 6
    anim_mode: str = "None"  # None, Pulse, Expand, Fade
    anim_speed: int = 4

    # sniper/bloom
    sniper_enabled: bool = True
    sniper_scale_pct: int = 160
    bloom_enabled: bool = True
    bloom_decay_ms: int = 220
    bloom_scale_pct: int = 120

    # audio reaction (new)
    audio_enabled: bool = False
    audio_mode: str = "Scale"   # Scale, Opacity, GlowPulse
    audio_sensitivity: int = 50  # 1-100 (50 ~ neutral)
    audio_smooth_ms: int = 150
    audio_device: str = "Default"

    # crash watchdog (new)
    watchdog_enabled: bool = True
    watchdog_overlay_threshold_ms: int = 5000
    watchdog_auto_restart_app: bool = True

# ---------------- IO ----------------

def save_last_state(st: CrosshairState):
    try:
        with open(LAST_STATE, 'w', encoding='utf-8') as f:
            json.dump(asdict(st), f, indent=2)
    except Exception:
        pass

def load_last_state() -> CrosshairState:
    try:
        if os.path.exists(LAST_STATE):
            with open(LAST_STATE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            defaults = {f.name: getattr(CrosshairState(), f.name) for f in fields(CrosshairState)}
            defaults.update(d)
            return CrosshairState(**defaults)
    except Exception:
        pass
    return CrosshairState()

def _qcolor(hex_or_name: str, alpha: float = 1.0):
    c = QtGui.QColor(hex_or_name)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c

def save_presets(data: Dict[str, Any]):
    try:
        with open(PRESETS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Failed to save presets:", e)

def load_presets():
    if not os.path.exists(PRESETS_PATH):
        defaults = {
            "Headshot Dot": asdict(CrosshairState(style="Dot", size=7, thickness=5, outline_enabled=True, outline_thickness=2, color="#ffffff", opacity=1.0)),
            "Classic CS": asdict(CrosshairState(style="Crosshair+Gap", size=10, thickness=3, outline_enabled=True, outline_thickness=1, color="#00ff00", opacity=1.0, gap=6)),
            "Neon Pixel": asdict(CrosshairState(style="Dot+Outline", size=3, thickness=3, outline_enabled=True, outline_thickness=2, color="#b366ff")),
            "Circle+Dot": asdict(CrosshairState(style="Circle+Dot", size=10, thickness=2, outline_enabled=True, outline_thickness=2, color="#ff6666")),
        }
        save_presets(defaults)
    try:
        with open(PRESETS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print("Failed to load presets:", e)
        return {}

# ---------------- Drawing ----------------

def _set_pen(p: QtGui.QPainter, color: QtGui.QColor, width: int):
    pen = QtGui.QPen(color, max(1, width))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)


def draw_crosshair(p: QtGui.QPainter, rect: QtCore.QRect, state: CrosshairState, phase: float, bloom_factor: float, opacity_mult: float = 1.0,
                   audio_factor: float = 0.0, audio_mode: str = "None"):
    """Render all styles with thickness + optional outline pass.
       audio_factor: 0..1, audio_mode in {None, Scale, Opacity, GlowPulse}
    """
    audio_factor = max(0.0, min(1.0, audio_factor))

    # Opacity modulation by audio (if chosen)
    eff_opacity = opacity_mult
    if audio_mode == "Opacity":
        eff_opacity = max(0.05, min(1.0, opacity_mult * (0.6 + 0.4*audio_factor)))

    p.save(); p.setOpacity(max(0.0, min(1.0, eff_opacity)))
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    center = rect.center()

    # Effective size with animations
    eff_size = state.size
    eff_thickness = max(1, state.thickness)
    if state.anim_mode == "Pulse":
        eff_size = int(state.size * (0.9 + 0.2*math.sin(phase*2*math.pi)))
    elif state.anim_mode == "Expand":
        eff_size = int(state.size * (1.0 + 0.4*phase))

    # Audio scale (if chosen)
    if audio_mode == "Scale":
        eff_size = int(eff_size * (1.0 + 0.35*audio_factor))

    # Sniper scaling
    def _sniper_active():
        mouse_ok = IS_WIN and GetAsyncKeyState and (GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        lt_ok = IS_WIN and XINPUT_AVAILABLE and XInputReader.lt_pressed()
        return state.sniper_enabled and (mouse_ok or lt_ok)
    if _sniper_active():
        eff_size = int(eff_size * max(1.0, state.sniper_scale_pct/100.0))

    # Bloom scaling
    if state.bloom_enabled and bloom_factor > 0.0:
        b = 1.0 + (max(1.0, state.bloom_scale_pct/100.0)-1.0) * max(0.0, min(1.0, bloom_factor))
        eff_size = int(eff_size * b)

    def main_color(a=1.0): return _qcolor(state.color, state.opacity * a)
    def outline_color(a=1.0): return _qcolor(state.outline_color, state.opacity * a)

    def draw_lines(lines):
        if state.outline_enabled and state.outline_thickness > 0:
            _set_pen(p, outline_color(), eff_thickness + 2*state.outline_thickness)
            for a,b in lines: p.drawLine(a,b)
        _set_pen(p, main_color(), eff_thickness)
        for a,b in lines: p.drawLine(a,b)

    def draw_rect_outline(r: QtCore.QRect):
        if state.outline_enabled and state.outline_thickness > 0:
            _set_pen(p, outline_color(), eff_thickness + 2*state.outline_thickness)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawRect(r)
        _set_pen(p, main_color(), eff_thickness)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(r)

    def draw_ellipse(c: QtCore.QPoint, rx: int, ry: int, filled=True):
        if state.outline_enabled and state.outline_thickness > 0:
            _set_pen(p, outline_color(), eff_thickness + 2*state.outline_thickness)
            p.setBrush(outline_color() if filled else QtCore.Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rx, ry)
        _set_pen(p, main_color(), eff_thickness if not filled else 1)
        p.setBrush(main_color() if filled else QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, rx, ry)

    g = state.gap
    style = state.style

    # --- Styles ---
    if style == "Dot":
        r = max(1, eff_thickness)
        draw_ellipse(center, r, r, filled=True)

    elif style == "Dot+Outline":
        r = max(1, eff_thickness)
        draw_ellipse(center, r, r, filled=True)

    elif style in ("Crosshair", "Crosshair+Gap", "T-Cross"):
        L = eff_size; gap = (g if style != "Crosshair" else 0)
        p.save(); p.translate(center); p.rotate(state.rotation)
        lines = []
        if style != "T-Cross":
            lines.append((QtCore.QPoint(0, -(L + gap)), QtCore.QPoint(0, -gap)))
        lines.append((QtCore.QPoint(0, gap), QtCore.QPoint(0, L + gap)))
        lines.append((QtCore.QPoint(-(L + gap), 0), QtCore.QPoint(-gap, 0)))
        lines.append((QtCore.QPoint(gap, 0), QtCore.QPoint(L + gap, 0)))
        draw_lines(lines)
        p.restore()

    elif style == "Circle":
        draw_ellipse(center, eff_size, eff_size, filled=False)

    elif style == "HollowCircle":
        draw_ellipse(center, eff_size, eff_size, filled=False)

    elif style == "Circle+Dot":
        draw_ellipse(center, eff_size, eff_size, filled=False)
        r = max(1, eff_size // 3)
        draw_ellipse(center, r, r, filled=True)

    elif style == "Chevron":
        p.save(); p.translate(center); p.rotate(state.rotation)
        L = eff_size
        lines = [(QtCore.QPoint(-L, 0), QtCore.QPoint(0, -L)), (QtCore.QPoint(0, -L), QtCore.QPoint(L, 0))]
        draw_lines(lines)
        p.restore()

    elif style == "Square+Gap":
        rect2 = QtCore.QRect(center.x()-eff_size, center.y()-eff_size, 2*eff_size, 2*eff_size)
        draw_rect_outline(rect2)

    elif style == "Tri-Dot":
        r = max(1, eff_thickness)
        pts = [QtCore.QPoint(center.x(), center.y()-eff_size),
               QtCore.QPoint(center.x()-int(0.866*eff_size), center.y()+int(0.5*eff_size)),
               QtCore.QPoint(center.x()+int(0.866*eff_size), center.y()+int(0.5*eff_size))]
        for pt in pts:
            draw_ellipse(pt, r, r, filled=True)

    elif style == "Asterisk":
        p.save(); p.translate(center); p.rotate(state.rotation)
        L = eff_size
        lines = [
            (QtCore.QPoint(0, -L), QtCore.QPoint(0, L)),
            (QtCore.QPoint(-int(L*0.866), -int(L*0.5)), QtCore.QPoint(int(L*0.866), int(L*0.5))),
            (QtCore.QPoint(-int(L*0.866), int(L*0.5)), QtCore.QPoint(int(L*0.866), -int(L*0.5))),
        ]
        draw_lines(lines)
        p.restore()

    elif style == "Brackets":
        L = eff_size; g2 = g
        lines = [
            (QtCore.QPoint(center.x()-L-g2, center.y()-L-g2), QtCore.QPoint(center.x()-L//2, center.y()-L-g2)),
            (QtCore.QPoint(center.x()-L-g2, center.y()-L-g2), QtCore.QPoint(center.x()-L-g2, center.y()-L//2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()-L-g2), QtCore.QPoint(center.x()+L//2, center.y()-L-g2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()-L-g2), QtCore.QPoint(center.x()+L+g2, center.y()-L//2)),
            (QtCore.QPoint(center.x()-L-g2, center.y()+L+g2), QtCore.QPoint(center.x()-L//2, center.y()+L+g2)),
            (QtCore.QPoint(center.x()-L-g2, center.y()+L+g2), QtCore.QPoint(center.x()-L-g2, center.y()+L//2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()+L+g2), QtCore.QPoint(center.x()+L//2, center.y()+L+g2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()+L+g2), QtCore.QPoint(center.x()+L+g2, center.y()+L//2)),
        ]
        draw_lines(lines)

    # Center micro-dot
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(_qcolor("#ffffff", min(1.0, state.opacity)))
    p.drawEllipse(center, 1, 1)
    p.restore()

# ---------------- Audio monitor ----------------
class AudioMonitor(QtCore.QThread):
    levelChanged = QtCore.pyqtSignal(float)  # 0..~1
    def __init__(self, device: Optional[int] = None, parent=None):
        super().__init__(parent)
        self._stop = False
        self._device = device

    def run(self):
        if not AUDIO_AVAILABLE:
            return
        try:
            def _cb(indata, frames, time_info, status):
                try:
                    if status:
                        pass
                    # RMS level per block
                    rms = float(np.sqrt(np.mean(np.square(indata))))
                    # Clip to ~[0,1]
                    self.levelChanged.emit(max(0.0, min(1.0, rms * 8.0)))
                except Exception:
                    pass
            with sd.InputStream(channels=1, samplerate=44100, blocksize=1024, callback=_cb, device=self._device):
                while not self._stop:
                    sd.sleep(100)
        except Exception as e:
            _write_crash_log(f"AudioMonitor error: {e}")

    def stop(self):
        self._stop = True

# ---------------- Overlay widget ----------------
class Overlay(QtWidgets.QWidget):
    def __init__(self, state: CrosshairState):
        super().__init__()
        self.state = state
        self.phase = 0.0
        self.bloom_until = 0
        self._last_paint_ms = int(time.time()*1000)
        self._opacity_mult = 1.0
        self._last_mouse_pos = QtGui.QCursor.pos()
        self._last_move_ms = int(time.time()*1000)
        # audio dynamics
        self._audio_raw = 0.0
        self._audio_smoothed = 0.0

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        flags = (QtCore.Qt.WindowType.FramelessWindowHint
                 | QtCore.Qt.WindowType.Tool
                 | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.resize(300, 300)
        self.center_on_screen()
        QtCore.QTimer.singleShot(60, self.apply_click_through)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def center_on_screen(self):
        screens = QtWidgets.QApplication.screens()
        idx = max(0, min(len(screens)-1, self.state.screen_index))
        g = screens[idx].geometry()
        cx = g.center().x() - self.width()//2
        cy = g.center().y() - self.height()//2
        margin = 24
        am = getattr(self.state, 'anchor_mode', 'Center')
        if am == "Top":
            cy = g.top() + margin
        elif am == "Bottom":
            cy = g.bottom() - self.height() - margin
        elif am == "Left":
            cx = g.left() + margin
        elif am == "Right":
            cx = g.right() - self.width() - margin
        elif am == "Top-Left":
            cx, cy = g.left()+margin, g.top()+margin
        elif am == "Top-Right":
            cx, cy = g.right()-self.width()-margin, g.top()+margin
        elif am == "Bottom-Left":
            cx, cy = g.left()+margin, g.bottom()-self.height()-margin
        elif am == "Bottom-Right":
            cx, cy = g.right()-self.width()-margin, g.bottom()-self.height()-margin
        cx += self.state.offset_x
        cy += self.state.offset_y
        self.move(cx, cy)

    def apply_click_through(self):
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, self.state.click_through)

    def set_state(self, new_state: CrosshairState):
        self.state = new_state
        self.apply_click_through()
        self.center_on_screen()
        save_last_state(self.state)
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.01 * max(1, self.state.anim_speed)) % 1.0
        if IS_WIN and XINPUT_AVAILABLE:
            XInputReader.poll()
        rt_active = IS_WIN and XINPUT_AVAILABLE and XInputReader.rt_pressed()
        lmb_active = IS_WIN and GetAsyncKeyState and (GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        if self.state.bloom_enabled and (rt_active or lmb_active):
            now = int(time.time() * 1000)
            self.bloom_until = now + max(50, int(self.state.bloom_decay_ms))

        # auto-fade on mouse move
        if self.state.auto_fade_on_move:
            now = int(time.time()*1000)
            pos = QtGui.QCursor.pos()
            if pos != self._last_mouse_pos:
                self._last_move_ms = now
                self._last_mouse_pos = pos
            moving = (now - self._last_move_ms) < max(0, int(self.state.fade_still_delay_ms))
            target = max(0.05, min(1.0, self.state.fade_min_opacity)) if moving else 1.0
            self._opacity_mult += (target - self._opacity_mult) * 0.2
        else:
            self._opacity_mult += (1.0 - self._opacity_mult) * 0.2

        # audio smoothing
        if self.state.audio_enabled:
            dt = 16.0
            tau = max(1.0, float(self.state.audio_smooth_ms))
            alpha = min(1.0, dt / tau)
            target = max(0.0, min(1.0, self._audio_raw * (self.state.audio_sensitivity/50.0)))
            self._audio_smoothed += (target - self._audio_smoothed) * alpha
        else:
            self._audio_smoothed *= 0.92

        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        now = int(time.time()*1000)
        self._last_paint_ms = now

        # click-trigger bloom decay
        bloom_factor = 0.0
        if self.bloom_until:
            if now < self.bloom_until:
                bloom_factor = (self.bloom_until - now) / max(1, self.state.bloom_decay_ms)
            else:
                self.bloom_until = 0

        # audio influence for glow pulse
        audio_factor = self._audio_smoothed if self.state.audio_enabled else 0.0
        if self.state.audio_enabled and self.state.audio_mode == "GlowPulse":
            bloom_factor = max(bloom_factor, audio_factor)

        draw_crosshair(p, rect, self.state, self.phase, bloom_factor, self._opacity_mult,
                       audio_factor=audio_factor, audio_mode=(self.state.audio_mode if self.state.audio_enabled else "None"))

# ---------------- Designer panel ----------------
class DesignerPanel(QtWidgets.QWidget):
    stateChanged = QtCore.pyqtSignal(CrosshairState)
    def __init__(self, overlay: Overlay):
        super().__init__()
        self.overlay = overlay
        self._build_ui()
        self._apply_theme()
        self._load_from_disk()
        self._load_presets()

    def _build_ui(self):
        layout = QtWidgets.QFormLayout(self)
        self.style = QtWidgets.QComboBox(); self.refresh_styles()
        self.color_btn = QtWidgets.QPushButton("Pick Color"); self.color_btn.clicked.connect(self._pick_color)
        self.size = self._slider(1,200,self.overlay.state.size)
        self.thickness = self._slider(1,20,self.overlay.state.thickness)
        self.gap = self._slider(0,60,self.overlay.state.gap)
        self.rotation = self._slider(0,359,self.overlay.state.rotation)
        self.opacity = self._slider(5,100,int(self.overlay.state.opacity*100))
        self.out_enable = QtWidgets.QCheckBox("Outline Enabled"); self.out_enable.setChecked(self.overlay.state.outline_enabled)
        self.out_thickness = self._slider(0,12,self.overlay.state.outline_thickness)
        self.out_color_btn = QtWidgets.QPushButton("Outline Color"); self.out_color_btn.clicked.connect(self._pick_outline_color)
        self.glow = self._slider(0,20,self.overlay.state.glow_strength)
        self.anim = QtWidgets.QComboBox(); self.anim.addItems(["None","Pulse","Expand","Fade"]); self.anim.setCurrentText(self.overlay.state.anim_mode)
        self.anim_speed = self._slider(1,10,self.overlay.state.anim_speed)
        self.sniper = QtWidgets.QCheckBox("Sniper (RMB/LT)"); self.sniper.setChecked(self.overlay.state.sniper_enabled)
        self.sniper_scale = self._slider(100,300,self.overlay.state.sniper_scale_pct)
        self.bloom = QtWidgets.QCheckBox("Bloom (LMB/RT)"); self.bloom.setChecked(self.overlay.state.bloom_enabled)
        self.bloom_scale = self._slider(100,300,self.overlay.state.bloom_scale_pct)
        self.bloom_decay = self._slider(50,1000,self.overlay.state.bloom_decay_ms)
        self.click = QtWidgets.QCheckBox("Click-through overlay"); self.click.setChecked(self.overlay.state.click_through)
        self.presets = QtWidgets.QComboBox()
        self.save_preset_btn = QtWidgets.QPushButton("Save Preset")
        self.delete_preset_btn = QtWidgets.QPushButton("Delete Preset")

        layout.addRow("Style", self.style)
        layout.addRow("Color", self.color_btn)
        layout.addRow("Size", self.size)
        layout.addRow("Thickness", self.thickness)
        layout.addRow("Gap", self.gap)
        layout.addRow("Rotation", self.rotation)
        layout.addRow("Opacity", self.opacity)
        layout.addRow(self.out_enable)
        layout.addRow("Outline Thickness", self.out_thickness)
        layout.addRow("Outline Color", self.out_color_btn)
        layout.addRow("Glow Strength", self.glow)
        layout.addRow("Animation", self.anim)
        layout.addRow("Anim Speed", self.anim_speed)
        layout.addRow(self.sniper)
        layout.addRow("Sniper Scale %", self.sniper_scale)
        layout.addRow(self.bloom)
        layout.addRow("Bloom Scale %", self.bloom_scale)
        layout.addRow("Bloom Decay (ms)", self.bloom_decay)
        layout.addRow(self.click)
        layout.addRow("Presets", self.presets)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.save_preset_btn); row.addWidget(self.delete_preset_btn)
        layout.addRow(row)

        for w in (self.style, self.size, self.thickness, self.gap, self.rotation, self.opacity,
                  self.out_enable, self.out_thickness, self.glow, self.anim, self.anim_speed,
                  self.sniper, self.sniper_scale, self.bloom, self.bloom_scale, self.bloom_decay, self.click):
            if isinstance(w, QtWidgets.QComboBox): w.currentTextChanged.connect(self._apply)
            elif isinstance(w, QtWidgets.QSlider): w.valueChanged.connect(self._apply)
            elif isinstance(w, QtWidgets.QCheckBox): w.toggled.connect(self._apply)
        self.save_preset_btn.clicked.connect(self._save_preset)
        self.delete_preset_btn.clicked.connect(self._delete_preset)

    def refresh_styles(self):
        current = self.style.currentText() if self.style.count() else None
        base = ["Dot","Dot+Outline","Crosshair","Crosshair+Gap","T-Cross","Circle","HollowCircle","Circle+Dot"]
        extra = ["Chevron","Square+Gap","Tri-Dot","Asterisk","Brackets"] if getattr(self.overlay.state,'enable_extra_styles',False) else []
        items = base + extra
        self.style.blockSignals(True); self.style.clear(); self.style.addItems(items); self.style.blockSignals(False)
        if current in items: self.style.setCurrentText(current)

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget{background:#0e0e12;color:#eaeaea;}
            QPushButton{background:#15151b;border:1px solid #2a2a33;border-radius:6px;}
            QSlider::groove:horizontal{height:6px;background:#2a2a33;border-radius:3px;}
            QSlider::handle:horizontal{width:16px;height:16px;margin:-6px 0;border-radius:8px;background:#b366ff;border:1px solid #5a2ea6;}
            QSlider::sub-page:horizontal{background:#6f3bd1;}
        """)

    def _slider(self, a,b,v):
        s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        s.setRange(a,b); s.setValue(v); return s

    def _pick_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.overlay.state.color), self, "Pick color", QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if col.isValid():
            self.overlay.state.color = col.name(QtGui.QColor.NameFormat.HexRgb)
            self._apply()

    def _pick_outline_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.overlay.state.outline_color), self, "Pick outline color", QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if col.isValid():
            self.overlay.state.outline_color = col.name(QtGui.QColor.NameFormat.HexRgb)
            self._apply()

    def _load_presets(self):
        data = load_presets()
        self.presets.blockSignals(True); self.presets.clear()
        for name in data.keys(): self.presets.addItem(name)
        self.presets.blockSignals(False)
        self.presets.currentTextChanged.connect(self._apply_preset_by_name)

    def _apply_preset_by_name(self, name):
        data = load_presets()
        if name in data:
            d = data[name]
            defaults = {f.name: getattr(CrosshairState(), f.name) for f in fields(CrosshairState)}
            defaults.update(d)
            st = CrosshairState(**defaults)
            self.overlay.set_state(st)
            self.stateChanged.emit(st)

    def _save_preset(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name.strip():
            data = load_presets()
            data[name.strip()] = asdict(self.overlay.state)
            save_presets(data)
            self._load_presets()

    def _delete_preset(self):
        name = self.presets.currentText()
        if not name: return
        if QtWidgets.QMessageBox.question(self, "Delete Preset", f"Delete '{name}'?") == QtWidgets.QMessageBox.StandardButton.Yes:
            data = load_presets(); data.pop(name, None); save_presets(data); self._load_presets()

    def _load_from_disk(self):
        st = load_last_state()
        self.overlay.set_state(st)

    def _apply(self, *_):
        s = self.overlay.state
        s.style = self.style.currentText()
        s.size = self.size.value()
        s.thickness = self.thickness.value()
        s.gap = self.gap.value()
        s.rotation = self.rotation.value()
        s.opacity = max(0.05, self.opacity.value()/100.0)
        s.outline_enabled = self.out_enable.isChecked()
        s.outline_thickness = self.out_thickness.value()
        s.glow_strength = self.glow.value()
        s.anim_mode = self.anim.currentText()
        s.anim_speed = self.anim_speed.value()
        s.sniper_enabled = self.sniper.isChecked()
        s.sniper_scale_pct = self.sniper_scale.value()
        s.bloom_enabled = self.bloom.isChecked()
        s.bloom_scale_pct = self.bloom_scale.value()
        s.bloom_decay_ms = self.bloom_decay.value()
        s.click_through = self.click.isChecked()
        self.overlay.set_state(s)
        self.stateChanged.emit(s)
        save_last_state(s)

# ---------------- Position panel ----------------
class PositionPanel(QtWidgets.QWidget):
    def __init__(self, overlay: Overlay):
        super().__init__()
        self.overlay = overlay
        lay = QtWidgets.QFormLayout(self)
        self.screens = QtWidgets.QComboBox()
        for i, scr in enumerate(QtWidgets.QApplication.screens()):
            geom = scr.geometry(); self.screens.addItem(f"Screen {i+1} ({geom.width()}x{geom.height()})")
        self.screens.setCurrentIndex(self.overlay.state.screen_index)
        self.screens.currentIndexChanged.connect(self._screen_changed)
        self.offx = QtWidgets.QSpinBox(); self.offx.setRange(-4000,4000); self.offx.setValue(self.overlay.state.offset_x)
        self.offy = QtWidgets.QSpinBox(); self.offy.setRange(-4000,4000); self.offy.setValue(self.overlay.state.offset_y)
        self.offx.valueChanged.connect(self._offset_changed); self.offy.valueChanged.connect(self._offset_changed)
        self.anchor = QtWidgets.QComboBox(); self.anchor.addItems(["Center","Top","Bottom","Left","Right","Top-Left","Top-Right","Bottom-Left","Bottom-Right"]) ; self.anchor.setCurrentText(self.overlay.state.anchor_mode)
        self.anchor.currentTextChanged.connect(self._offset_changed)
        self.center_btn = QtWidgets.QPushButton("Center"); self.center_btn.clicked.connect(self._center)
        lay.addRow("Target screen", self.screens)
        lay.addRow("Anchor", self.anchor)
        lay.addRow("Offset X", self.offx)
        lay.addRow("Offset Y", self.offy)
        lay.addRow(self.center_btn)

    def _screen_changed(self, idx):
        s = self.overlay.state; s.screen_index = idx; self.overlay.set_state(s)

    def _offset_changed(self, *_):
        s = self.overlay.state
        s.offset_x = self.offx.value(); s.offset_y = self.offy.value()
        s.anchor_mode = self.anchor.currentText()
        self.overlay.set_state(s)

    def _center(self):
        self.overlay.center_on_screen()

# ---------------- Display panel ----------------
class DisplayPanel(QtWidgets.QWidget):
    def __init__(self, overlay: Overlay):
        super().__init__()
        self.overlay = overlay
        lay = QtWidgets.QFormLayout(self)
        self.opacity = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.opacity.setRange(5,100); self.opacity.setValue(int(self.overlay.state.opacity*100))
        self.opacity.valueChanged.connect(self._on_opacity)
        lay.addRow("Master Opacity", self.opacity)

    def _on_opacity(self, v):
        s = self.overlay.state
        s.opacity = max(0.05, v/100.0)
        self.overlay.set_state(s)

# ---------------- Presets quick panel ----------------
class PresetsPanel(QtWidgets.QWidget):
    def __init__(self, designer: DesignerPanel):
        super().__init__()
        self.designer = designer
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Quick Presets"))
        row = QtWidgets.QHBoxLayout()
        for name in ("Headshot Dot","Classic CS","Neon Pixel","Circle+Dot"):
            btn = QtWidgets.QPushButton(name)
            btn.clicked.connect(lambda _, n=name: designer._apply_preset_by_name(n))
            row.addWidget(btn)
        lay.addLayout(row)
        lay.addStretch(1)

# ---------------- Support ----------------
class SupportPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        msg = "CrossXir — no hooks. Use Position tab for multi‑monitor & anchors. Import/Export presets in Advanced."
        if not AUDIO_AVAILABLE:
            msg += "\n\nAudio: install 'sounddevice' + 'numpy' to enable Audio Reaction (pip install sounddevice numpy)."
        lay.addWidget(QtWidgets.QLabel(msg))
        lay.addStretch(1)

# ---------------- Advanced panel ----------------
class AdvancedPanel(QtWidgets.QWidget):
    themeChanged = QtCore.pyqtSignal(str)
    def __init__(self, overlay: Overlay, designer: DesignerPanel):
        super().__init__()
        self.overlay = overlay; self.designer = designer
        lay = QtWidgets.QFormLayout(self)
        # Theme selector (mature palettes)
        self.theme = QtWidgets.QComboBox(); self.theme.addItems(["Windows 11","Neo Noir","Graphite","Minimal"]) ; self.theme.setCurrentText("Windows 11")
        # Toggles
        self.chk_sniper_mask = QtWidgets.QCheckBox("Sniper mask (vignette)"); self.chk_sniper_mask.setChecked(self.overlay.state.sniper_mask_enabled)
        self.vignette = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.vignette.setRange(0,100); self.vignette.setValue(self.overlay.state.vignette_strength)
        self.chk_pack = QtWidgets.QCheckBox("Enable animated/extra reticles"); self.chk_pack.setChecked(self.overlay.state.enable_extra_styles)
        self.chk_autofade = QtWidgets.QCheckBox("Auto-fade while moving mouse"); self.chk_autofade.setChecked(self.overlay.state.auto_fade_on_move)
        self.fade_min = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.fade_min.setRange(5,100); self.fade_min.setValue(int(self.overlay.state.fade_min_opacity*100))
        self.fade_delay = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.fade_delay.setRange(50,1500); self.fade_delay.setValue(self.overlay.state.fade_still_delay_ms)
        self.anchor = QtWidgets.QComboBox(); self.anchor.addItems(["Center","Top","Bottom","Left","Right","Top-Left","Top-Right","Bottom-Left","Bottom-Right"]) ; self.anchor.setCurrentText(self.overlay.state.anchor_mode)
        # Watchdog controls (new)
        self.chk_watchdog = QtWidgets.QCheckBox("Crash Watchdog (recover overlay)"); self.chk_watchdog.setChecked(self.overlay.state.watchdog_enabled)
        self.watchdog_thresh = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.watchdog_thresh.setRange(1000,15000); self.watchdog_thresh.setValue(self.overlay.state.watchdog_overlay_threshold_ms)
        self.chk_watchdog_restart = QtWidgets.QCheckBox("Auto‑restart app on crash"); self.chk_watchdog_restart.setChecked(self.overlay.state.watchdog_auto_restart_app)
        # Preset import/export
        btns = QtWidgets.QHBoxLayout(); self.btn_export = QtWidgets.QPushButton("Export Presets..."); self.btn_import = QtWidgets.QPushButton("Import Presets...")
        btns.addWidget(self.btn_export); btns.addWidget(self.btn_import)
        # Layout
        lay.addRow("Theme", self.theme)
        lay.addRow(self.chk_sniper_mask)
        lay.addRow("Vignette Strength", self.vignette)
        lay.addRow(self.chk_pack)
        lay.addRow(self.chk_autofade)
        lay.addRow("Fade Min Opacity", self.fade_min)
        lay.addRow("Fade Still Delay (ms)", self.fade_delay)
        lay.addRow("Anchor", self.anchor)
        # Watchdog section
        lay.addRow(self.chk_watchdog)
        lay.addRow("Overlay stall threshold (ms)", self.watchdog_thresh)
        lay.addRow(self.chk_watchdog_restart)
        lay.addRow(btns)
        # Signals
        for w in (self.theme, self.chk_sniper_mask, self.vignette, self.chk_pack, self.chk_autofade, self.fade_min, self.fade_delay, self.anchor,
                  self.chk_watchdog, self.watchdog_thresh, self.chk_watchdog_restart):
            if isinstance(w, QtWidgets.QCheckBox): w.toggled.connect(self._apply)
            elif isinstance(w, QtWidgets.QSlider): w.valueChanged.connect(self._apply)
            elif isinstance(w, QtWidgets.QComboBox): w.currentTextChanged.connect(self._apply)
        self.theme.currentTextChanged.connect(self._on_theme)
        self.btn_export.clicked.connect(self._export)
        self.btn_import.clicked.connect(self._import)

    def _on_theme(self, name):
        self.themeChanged.emit(name)

    def _apply(self, *_):
        s = self.overlay.state
        s.sniper_mask_enabled = self.chk_sniper_mask.isChecked()
        s.vignette_strength = self.vignette.value()
        s.enable_extra_styles = self.chk_pack.isChecked()
        s.auto_fade_on_move = self.chk_autofade.isChecked()
        s.fade_min_opacity = max(0.05, self.fade_min.value()/100.0)
        s.fade_still_delay_ms = self.fade_delay.value()
        s.anchor_mode = self.anchor.currentText()
        # watchdog
        s.watchdog_enabled = self.chk_watchdog.isChecked()
        s.watchdog_overlay_threshold_ms = self.watchdog_thresh.value()
        s.watchdog_auto_restart_app = self.chk_watchdog_restart.isChecked()
        self.overlay.set_state(s)
        self.designer.refresh_styles()

    def _export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Presets", "crossxir_presets.json", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f: json.dump(load_presets(), f, indent=2)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Export Failed", str(e))

    def _import(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import Presets", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
                if not isinstance(data, dict): raise ValueError("Invalid preset file")
                save_presets(data); self.designer._load_presets()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Import Failed", str(e))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import Presets", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
                if not isinstance(data, dict): raise ValueError("Invalid preset file")
                save_presets(data); self.designer._load_presets()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Import Failed", str(e))

# ---------------- Audio panel ----------------
class AudioPanel(QtWidgets.QWidget):
    def __init__(self, overlay: Overlay, on_settings_changed):
        super().__init__()
        self.overlay = overlay
        self._on_settings_changed = on_settings_changed
        lay = QtWidgets.QFormLayout(self)

        self.enable = QtWidgets.QCheckBox("Enable Audio Reaction"); self.enable.setChecked(self.overlay.state.audio_enabled)
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(["Scale","Opacity","GlowPulse"]); self.mode.setCurrentText(self.overlay.state.audio_mode)
        self.sens = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.sens.setRange(1,100); self.sens.setValue(self.overlay.state.audio_sensitivity)
        self.smooth = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.smooth.setRange(0,1000); self.smooth.setValue(self.overlay.state.audio_smooth_ms)

        self.device = QtWidgets.QComboBox()
        self.device.addItem("Default")
        if AUDIO_AVAILABLE:
            try:
                for i, dev in enumerate(sd.query_devices()):
                    if dev.get('max_input_channels', 0) > 0:
                        self.device.addItem(f"{i}: {dev['name']}")
            except Exception:
                pass
        self.device.setCurrentText(self.overlay.state.audio_device if self.overlay.state.audio_device else "Default")

        self.level = QtWidgets.QProgressBar(); self.level.setRange(0,100); self.level.setValue(0)
        self._meter_timer = QtCore.QTimer(self); self._meter_timer.setInterval(60); self._meter_timer.timeout.connect(self._tick_meter); self._meter_timer.start()

        lay.addRow(self.enable)
        lay.addRow("Reaction Mode", self.mode)
        lay.addRow("Sensitivity", self.sens)
        lay.addRow("Smoothing (ms)", self.smooth)
        lay.addRow("Audio Device", self.device)
        lay.addRow("Live Level", self.level)

        if not AUDIO_AVAILABLE:
            hint = QtWidgets.QLabel("Install 'sounddevice' + 'numpy' to enable (pip install sounddevice numpy).")
            hint.setStyleSheet("color:#c97a7a")
            lay.addRow(hint)
            # Disable controls when backend missing
            for w in (self.enable, self.mode, self.sens, self.smooth, self.device):
                w.setEnabled(False)

        for w in (self.enable, self.mode, self.sens, self.smooth, self.device):
            if isinstance(w, QtWidgets.QCheckBox): w.toggled.connect(self._apply)
            elif isinstance(w, QtWidgets.QComboBox): w.currentTextChanged.connect(self._apply)
            elif isinstance(w, QtWidgets.QSlider): w.valueChanged.connect(self._apply)

    def _tick_meter(self):
        val = int(max(0.0, min(1.0, getattr(self.overlay, '_audio_smoothed', 0.0))) * 100)
        self.level.setValue(val)

    def _apply(self, *_):
        s = self.overlay.state
        s.audio_enabled = self.enable.isChecked()
        s.audio_mode = self.mode.currentText()
        s.audio_sensitivity = self.sens.value()
        s.audio_smooth_ms = self.smooth.value()
        s.audio_device = self.device.currentText() or "Default"
        self.overlay.set_state(s)
        save_last_state(s)
        self._on_settings_changed()

# ---------------- Preview ----------------
class Preview(QtWidgets.QWidget):
    def __init__(self, overlay: Overlay):
        super().__init__()
        self.overlay = overlay
        self.setMinimumWidth(300)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#0c0c10"))
        p.setPen(QtGui.QPen(QtGui.QColor(40,40,48),1))
        for x in range(0, self.width(), 20): p.drawLine(x,0,x,self.height())
        for y in range(0, self.height(), 20): p.drawLine(0,y,self.width(),y)
        draw_crosshair(p, self.rect(), self.overlay.state, 0.0, 0.0, 1.0, audio_factor=0.0, audio_mode="None")

# ---------------- Main Window ----------------
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(1040,560)
        self.setWindowIcon(self._load_icon())
        self.overlay = Overlay(load_last_state()); self.overlay.show()

        root = QtWidgets.QHBoxLayout(self)
        self.sidebar = QtWidgets.QListWidget(); self.sidebar.setFixedWidth(200)
        self.sidebar.setSpacing(6)
        for item in ("Crosshairs","Display","Position & Size","Designer","Advanced","Audio","Support"):
            self.sidebar.addItem(item)

        self.stack = QtWidgets.QStackedWidget()
        self.designer = DesignerPanel(self.overlay)
        self.page_presets = PresetsPanel(self.designer)
        self.page_display = DisplayPanel(self.overlay)
        self.page_pos = PositionPanel(self.overlay)
        self.page_support = SupportPanel()
        self.page_adv = AdvancedPanel(self.overlay, self.designer)
        self.page_audio = AudioPanel(self.overlay, self._sync_audio_monitor)
        for w in (self.page_presets, self.page_display, self.page_pos, self.designer, self.page_adv, self.page_audio, self.page_support):
            self.stack.addWidget(w)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(3)

        self.preview = Preview(self.overlay)
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.preview)
        splitter.setSizes([200,580,320])
        root.addWidget(splitter)

        # keep preview live with overlay timer
        try: self.overlay.timer.timeout.connect(self.preview.update)
        except Exception: pass
        self.designer.stateChanged.connect(lambda *_: self.preview.update())

        icon = self._load_icon()
        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        menu = QtWidgets.QMenu(); menu.addAction("Hide/Show Overlay", lambda: self.overlay.setVisible(not self.overlay.isVisible()))
        menu.addAction("Exit", QtWidgets.QApplication.instance().quit)
        self.tray.setContextMenu(menu); self.tray.setIcon(icon); self.tray.show()

        # Apply mature theme (and listen for changes from Advanced panel)
        self._apply_theme("Windows 11")
        self.page_adv.themeChanged.connect(self._apply_theme)

        # Watchdog timer
        self._wd_timer = QtCore.QTimer(self); self._wd_timer.setInterval(1000); self._wd_timer.timeout.connect(self._watchdog_tick); self._wd_timer.start()

        # Audio monitor (lazy start depending on settings)
        self.audio_monitor: Optional[AudioMonitor] = None
        self._sync_audio_monitor()

    def _apply_theme(self, name: str):
        if name == "Windows 11":
            accent = "#5B9BFA"; bg = "#0F1115"; bg2 = "#141820"; border = "#2A2F3A"; text = "#E6E7EC"; sub = "#B2B6C2"; r = 8
        elif name == "Neo Noir":
            accent = "#8A7AF5"; bg = "#0B0C10"; bg2 = "#0F1116"; border = "#242735"; text = "#E6E7EC"; sub = "#A9AABC"; r = 10
        elif name == "Graphite":
            accent = "#7A8C9E"; bg = "#0E0F12"; bg2 = "#12141A"; border = "#2A2D39"; text = "#E5E5E5"; sub = "#A7ABB3"; r = 10
        else:
            accent = "#ADB5BD"; bg = "#111216"; bg2 = "#151820"; border = "#242833"; text = "#E8E9ED"; sub = "#B5B8C1"; r = 8
        self.setStyleSheet(f"""
            * {{ font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', system-ui, -apple-system, 'Helvetica Neue', Arial; }}
            QWidget{{background:{bg};color:{text};font-size:13px;}}
            QListWidget{{background:{bg2};color:{text};border:1px solid {border};border-radius:{r}px;}}
            QListWidget::item{{padding:8px 12px;margin:2px;border-radius:{r-2}px;}}
            QListWidget::item:selected{{background:{border};color:{text};}}
            QStackedWidget{{background:{bg2};border:1px solid {border};border-radius:{r}px;}}
            QLabel{{color:{sub};}}
            QPushButton{{background:{bg2};border:1px solid {border};border-radius:{r}px;padding:8px 12px;}}
            QPushButton:hover{{border-color:{accent};}}
            QPushButton:focus{{outline: none; border: 1px solid {accent};}}
            QSlider::groove:horizontal{{height:6px;background:{border};border-radius:{max(0,r-4)}px;}}
            QSlider::handle:horizontal{{width:16px;height:16px;margin:-6px 0;border-radius:{max(0,r-4)}px;background:{accent};border:1px solid {border};}}
            QSlider::sub-page:horizontal{{background:{accent};}}
            QComboBox, QSpinBox, QLineEdit{{background:{bg2};border:1px solid {border};border-radius:{r}px;padding:6px;}}
            QMenu{{background:{bg2};color:{text};border:1px solid {border};border-radius:{r}px;}}
        """)

    def _load_icon(self) -> QtGui.QIcon:
        local_path = os.path.join(os.getcwd(), 'CrossXir_icon_cool.ico')
        tweaker_path = os.path.join('E:\\DInputTweaker', 'CrossXir_icon_cool.ico')
        sandbox_path = os.path.join('/mnt/data', 'CrossXir_icon_cool.ico')
        for pth in (local_path, tweaker_path, sandbox_path):
            if os.path.exists(pth):
                return QtGui.QIcon(pth)
        pm = QtGui.QPixmap(64,64)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QtGui.QColor('#5B9BFA'))
        p.setPen(QtGui.QPen(QtGui.QColor('#2A2F3A'), 3))
        p.drawRoundedRect(10, 10, 44, 44, 6, 6)
        p.end()
        return QtGui.QIcon(pm)

    # ---------- Audio monitor plumbing ----------
    def _on_audio_level(self, val: float):
        try:
            self.overlay._audio_raw = float(max(0.0, min(1.0, val)))
        except Exception:
            pass

    def _device_index_for_name(self, label: str) -> Optional[int]:
        if not AUDIO_AVAILABLE or not label or label == "Default":
            return None
        try:
            if ":" in label:
                idx_str = label.split(":",1)[0].strip()
                return int(idx_str)
        except Exception:
            pass
        return None

    def _sync_audio_monitor(self):
        s = self.overlay.state
        if s.audio_enabled and AUDIO_AVAILABLE:
            dev_idx = self._device_index_for_name(s.audio_device)
            need_restart = False
            if self.audio_monitor is None:
                need_restart = True
            else:
                if self.audio_monitor.isRunning() and self.audio_monitor._device != dev_idx:
                    self._stop_audio_monitor(); need_restart = True
                elif not self.audio_monitor.isRunning():
                    need_restart = True
            if need_restart:
                try:
                    self.audio_monitor = AudioMonitor(device=dev_idx)
                    self.audio_monitor.levelChanged.connect(self._on_audio_level)
                    self.audio_monitor.start()
                except Exception as e:
                    _write_crash_log(f"Failed to start audio monitor: {e}")
        else:
            self._stop_audio_monitor()

    def _stop_audio_monitor(self):
        m = self.audio_monitor
        if m is not None:
            try:
                m.stop()
                m.wait(1000)
            except Exception:
                pass
        self.audio_monitor = None

    # ---------- Watchdog ----------
    def _watchdog_tick(self):
        try:
            s = self.overlay.state
            if not getattr(s, 'watchdog_enabled', True):
                return
            now = int(time.time()*1000)
            last = getattr(self.overlay, '_last_paint_ms', now)
            if now - last > max(1000, int(s.watchdog_overlay_threshold_ms)):
                # Attempt overlay recovery first
                try:
                    self.overlay.timer.stop()
                    self.overlay.timer.start(16)
                    self.overlay.update()
                    self.overlay._last_paint_ms = now
                except Exception:
                    if getattr(s, 'watchdog_auto_restart_app', True):
                        _write_crash_log('Watchdog: restarting app due to overlay stall')
                        _restart_app()
        except Exception as e:
            _write_crash_log(f"Watchdog tick error: {e}")

    def closeEvent(self, ev: QtGui.QCloseEvent):
        try:
            self._stop_audio_monitor()
        except Exception:
            pass
        super().closeEvent(ev)

# ---------------- main ----------------
def main():
    _install_excepthook()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
