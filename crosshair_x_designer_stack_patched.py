from __future__ import annotations
import sys, os, json, ctypes, math, time
from dataclasses import dataclass, asdict, fields
from typing import Dict, Any
from PyQt6 import QtCore, QtGui, QtWidgets

APP_NAME = "CrossXir"
ORG = "eztools"
DOMAIN = "crossxir"
APPDATA_DIR = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', ORG)
os.makedirs(APPDATA_DIR, exist_ok=True)
PRESETS_PATH = os.path.join(APPDATA_DIR, 'crossxir_presets.json')
LAST_STATE = os.path.join(APPDATA_DIR, 'crossxir_last_state.json')

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


def draw_crosshair(p: QtGui.QPainter, rect: QtCore.QRect, state: CrosshairState, phase: float, bloom_factor: float, opacity_mult: float = 1.0):
    """Render all styles with thickness + optional outline pass."""
    p.save(); p.setOpacity(max(0.0, min(1.0, opacity_mult)))
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    center = rect.center()

    # Effective size with animations
    eff_size = state.size
    eff_thickness = max(1, state.thickness)
    if state.anim_mode == "Pulse":
        eff_size = int(state.size * (0.9 + 0.2*math.sin(phase*2*math.pi)))
    elif state.anim_mode == "Expand":
        eff_size = int(state.size * (1.0 + 0.4*phase))

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
        path = QtGui.QPainterPath()
        L = eff_size
        # simple V shape outline respecting thickness via path strokes
        path.moveTo(-L, 0); path.lineTo(0, -L); path.lineTo(L, 0)
        # stroke twice via draw_lines for consistent look
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
            # TL
            (QtCore.QPoint(center.x()-L-g2, center.y()-L-g2), QtCore.QPoint(center.x()-L//2, center.y()-L-g2)),
            (QtCore.QPoint(center.x()-L-g2, center.y()-L-g2), QtCore.QPoint(center.x()-L-g2, center.y()-L//2)),
            # TR
            (QtCore.QPoint(center.x()+L+g2, center.y()-L-g2), QtCore.QPoint(center.x()+L//2, center.y()-L-g2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()-L-g2), QtCore.QPoint(center.x()+L+g2, center.y()-L//2)),
            # BL
            (QtCore.QPoint(center.x()-L-g2, center.y()+L+g2), QtCore.QPoint(center.x()-L//2, center.y()+L+g2)),
            (QtCore.QPoint(center.x()-L-g2, center.y()+L+g2), QtCore.QPoint(center.x()-L-g2, center.y()+L//2)),
            # BR
            (QtCore.QPoint(center.x()+L+g2, center.y()+L+g2), QtCore.QPoint(center.x()+L//2, center.y()+L+g2)),
            (QtCore.QPoint(center.x()+L+g2, center.y()+L+g2), QtCore.QPoint(center.x()+L+g2, center.y()+L//2)),
        ]
        draw_lines(lines)

    # Center micro-dot
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(_qcolor("#ffffff", min(1.0, state.opacity)))
    p.drawEllipse(center, 1, 1)
    p.restore()

# ---------------- Overlay widget ----------------
class Overlay(QtWidgets.QWidget):
    def __init__(self, state: CrosshairState):
        super().__init__()
        self.state = state
        self.phase = 0.0
        self.bloom_until = 0
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        flags = (QtCore.Qt.WindowType.FramelessWindowHint
                 | QtCore.Qt.WindowType.Tool
                 | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.resize(300, 300)
        self.center_on_screen()
        QtCore.QTimer.singleShot(60, self.apply_click_through)

        self._opacity_mult = 1.0
        self._last_mouse_pos = QtGui.QCursor.pos()
        self._last_move_ms = int(time.time()*1000)
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
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        bloom_factor = 0.0
        if self.bloom_until:
            now = int(time.time()*1000)
            if now < self.bloom_until:
                bloom_factor = (self.bloom_until - now) / max(1, self.state.bloom_decay_ms)
            else:
                self.bloom_until = 0
        draw_crosshair(p, rect, self.state, self.phase, bloom_factor, self._opacity_mult)
        if self.state.sniper_mask_enabled and (IS_WIN and ((GetAsyncKeyState and (GetAsyncKeyState(VK_RBUTTON) & 0x8000)) or (XINPUT_AVAILABLE and XInputReader.lt_pressed()))):
            p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
            shade = QtGui.QColor(0,0,0,int(255 * max(0, min(1, self.state.vignette_strength/100.0))))
            path = QtGui.QPainterPath()
            path.addRect(QtCore.QRectF(rect))
            r = max(30, int(min(rect.width(), rect.height())*0.18))
            cx, cy = rect.center().x(), rect.center().y()
            hole = QtGui.QPainterPath()
            hole.addEllipse(QtCore.QRectF(float(cx - r), float(cy - r), float(2*r), float(2*r)))
            mask = path.subtracted(hole)
            p.fillPath(mask, shade)

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
        lay.addWidget(QtWidgets.QLabel("CrossXir — no hooks. Use Position tab for multi‑monitor & anchors. Import/Export presets in Advanced."))
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
        lay.addRow(btns)
        # Signals
        for w in (self.theme, self.chk_sniper_mask, self.vignette, self.chk_pack, self.chk_autofade, self.fade_min, self.fade_delay, self.anchor):
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
        draw_crosshair(p, self.rect(), self.overlay.state, 0.0, 0.0, 1.0)

# ---------------- Main Window ----------------
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(980,560)
        self.setWindowIcon(self._load_icon())
        self.overlay = Overlay(load_last_state()); self.overlay.show()

        root = QtWidgets.QHBoxLayout(self)
        self.sidebar = QtWidgets.QListWidget(); self.sidebar.setFixedWidth(200)
        self.sidebar.setSpacing(6)
        for item in ("Crosshairs","Display","Position & Size","Designer","Advanced","Support"):
            self.sidebar.addItem(item)

        self.stack = QtWidgets.QStackedWidget()
        self.designer = DesignerPanel(self.overlay)
        self.page_presets = PresetsPanel(self.designer)
        self.page_display = DisplayPanel(self.overlay)
        self.page_pos = PositionPanel(self.overlay)
        self.page_support = SupportPanel()
        self.page_adv = AdvancedPanel(self.overlay, self.designer)
        for w in (self.page_presets, self.page_display, self.page_pos, self.designer, self.page_adv, self.page_support):
            self.stack.addWidget(w)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(3)

        self.preview = Preview(self.overlay)
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.preview)
        splitter.setSizes([200,560,320])
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

    def _apply_theme(self, name: str):
        # Windows 11 visual language: low-radius corners (~8px), subdued borders, focus/hover clarity,
        # Segoe UI Variable if available. Other themes remain as before.
        if name == "Windows 11":
            accent = "#5B9BFA"   # Win11 accent-ish
            bg = "#0F1115"
            bg2 = "#141820"
            border = "#2A2F3A"
            text = "#E6E7EC"
            sub = "#B2B6C2"
            r = 8  # border radius in px (less round)
        elif name == "Neo Noir":
            accent = "#8A7AF5"; bg = "#0B0C10"; bg2 = "#0F1116"; border = "#242735"; text = "#E6E7EC"; sub = "#A9AABC"; r = 10
        elif name == "Graphite":
            accent = "#7A8C9E"; bg = "#0E0F12"; bg2 = "#12141A"; border = "#2A2D39"; text = "#E5E5E5"; sub = "#A7ABB3"; r = 10
        else:  # Minimal
            accent = "#ADB5BD"; bg = "#111216"; bg2 = "#151820"; border = "#242833"; text = "#E8E9ED"; sub = "#B5B8C1"; r = 8

        # Apply consistent, lower radii and a Windows-y font stack
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
        """Load branded icon if available; otherwise draw a square-ish fallback badge."""
        # Prefer local working dir icon
        local_path = os.path.join(os.getcwd(), 'CrossXir_icon_cool.ico')
        tweaker_path = os.path.join('E:\\DInputTweaker', 'CrossXir_icon_cool.ico')
        sandbox_path = os.path.join('/mnt/data', 'CrossXir_icon_cool.ico')
        for pth in (local_path, tweaker_path, sandbox_path):
            if os.path.exists(pth):
                return QtGui.QIcon(pth)
        # Fallback painter icon (Win11-ish square)
        pm = QtGui.QPixmap(64,64)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QtGui.QColor('#5B9BFA'))
        p.setPen(QtGui.QPen(QtGui.QColor('#2A2F3A'), 3))
        p.drawRoundedRect(10, 10, 44, 44, 6, 6)
        p.end()
        return QtGui.QIcon(pm)

# ---------------- main ----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
