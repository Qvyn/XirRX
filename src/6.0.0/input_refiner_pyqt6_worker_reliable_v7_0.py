
# Jacinto Input Refiner — PyQt6 (worker-reliable, crash‑hardened, profiles, anti‑yank microguard)
# - Micro‑jolt anti‑yank guard for tiny inputs and rapid right‑stick bursts
# - Descriptions/tooltips for sliders and toggles
# - Multiple profiles: save, load, delete from UI dropdown
# - v6.9: pure input ownership fix; config value is direct speed; stricter no-touch floor
#
# SAFE: OS-level mouse move only (SendInput). Macro tab uses a G HUB-style builder for profile/config actions. No keyboard/click playback, no Python eval, no DX hooks, no game memory access.

from __future__ import annotations
import ctypes, json, math, os, sys, time, logging, pathlib, faulthandler, weakref, shutil, threading, shlex
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

# UI-facing button names → XInput flags.
# Kept near the constants so Cover Guard cannot silently disable itself.
_BUTTON_NAME_TO_FLAG = {
    "A": XINPUT_GAMEPAD_A,
    "B": XINPUT_GAMEPAD_B,
    "X": XINPUT_GAMEPAD_X,
    "Y": XINPUT_GAMEPAD_Y,
    "LB": XINPUT_GAMEPAD_LEFT_SHOULDER,
    "RB": XINPUT_GAMEPAD_RIGHT_SHOULDER,
    "LS": XINPUT_GAMEPAD_LEFT_THUMB,
    "RS": XINPUT_GAMEPAD_RIGHT_THUMB,
    "START": XINPUT_GAMEPAD_START,
    "BACK": XINPUT_GAMEPAD_BACK,
}

def button_names_from_mask(mask: int) -> str:
    """Human-readable gamepad button list for diagnostics."""
    try:
        names = []
        for name, flag in _BUTTON_NAME_TO_FLAG.items():
            if int(mask) & int(flag):
                names.append(name)
        return "+".join(names) if names else "none"
    except Exception:
        return "unknown"

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

def send_mouse_move(dx:int, dy:int)->bool:
    """Send a relative OS mouse move and report whether Windows accepted it."""
    try:
        inp = INPUT(); inp.type = 0; extra = ctypes.c_ulong(0)
        inp.ii.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, ctypes.cast(ctypes.pointer(extra), PUL))
        sent = SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if sent != 1:
            try:
                err = ctypes.windll.kernel32.GetLastError()
            except Exception:
                err = 0
            logging.warning("SendInput returned %r for dx=%r dy=%r GetLastError=%r", sent, dx, dy, err)
            return False
        return True
    except Exception:
        logging.exception("SendInput failed")
        return False

GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
GetWindowTextW     = ctypes.windll.user32.GetWindowTextW
GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
OpenProcess = ctypes.windll.kernel32.OpenProcess
CloseHandle = ctypes.windll.kernel32.CloseHandle
QueryFullProcessImageNameW = ctypes.windll.kernel32.QueryFullProcessImageNameW
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

def get_foreground_window()->int:
    try:
        return int(GetForegroundWindow() or 0)
    except Exception:
        return 0

def get_window_title(hwnd:int)->str:
    try:
        if not hwnd: return ""
        ln = GetWindowTextLengthW(hwnd)
        if ln <= 0: return ""
        buf = ctypes.create_unicode_buffer(ln+1)
        GetWindowTextW(hwnd, buf, ln+1)
        return buf.value
    except Exception:
        return ""

def get_foreground_title()->str:
    return get_window_title(get_foreground_window())

def get_window_process_image(hwnd:int)->str:
    """Return the foreground process image path/name. Useful when a fullscreen game has an empty window title."""
    try:
        if not hwnd:
            return ""
        pid = ctypes.c_ulong(0)
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        hproc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            try: CloseHandle(hproc)
            except Exception: pass
    except Exception:
        pass
    return ""

def get_foreground_identity() -> tuple[str, str]:
    hwnd = get_foreground_window()
    return get_window_title(hwnd), get_window_process_image(hwnd)

def _split_target_terms(target: object) -> list[str]:
    """Allow target aliases separated by |, ;, or comma."""
    raw = str(target or "").lower()
    for sep in (";", ","):
        raw = raw.replace(sep, "|")
    return [part.strip() for part in raw.split("|") if part.strip()]

def target_matches_text(target: object, text: str) -> bool:
    terms = _split_target_terms(target)
    if not terms:
        return True
    text_l = (text or "").lower()
    return any(term in text_l for term in terms)

def target_matches_title(target: object, title: str) -> bool:
    return target_matches_text(target, title)

def target_matches_identity(target: object, title: str, image: str) -> bool:
    terms = _split_target_terms(target)
    if not terms:
        return True
    hay = f"{title or ''} | {image or ''}".lower()
    return any(term in hay for term in terms)

# ----------------------------- Config -----------------------------
CONFIG_PATH = "input_refiner_config.json"
PROFILE_DIR = "profiles"
SCRIPT_DIR = "scripts"

@dataclass
class Config:
    # general
    target_window_substring:str = "Gears of War|WarGame|Redux|Reloaded|WarGame.exe"
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
    sens_ramp:float = 0.0             # v6.8 pure path: config values apply immediately; no sensitivity ramp
    max_pixels_per_tick:int = 40      # clamp per-tick dx/dy (prevents spikes)
    max_pixels_per_second:int = 3600  # global speed cap
    ads_hysteresis:int = 8            # adds hysteresis around ADS trigger threshold

    # debug overlay
    debug_overlay:bool = True
    debug_history:int = 360

    # engagement / soft zone / inhibition
    engage_threshold_norm:float = 0.005
    release_threshold_norm:float = 0.003
    softzone_k:float = 1.80
    idle_epsilon:float = 0.020
    idle_frames_to_zero:int = 8
    inhibit_mouse_when_buttons:bool = False  # Redux/Gears: leave OFF unless you intentionally want face buttons to suppress output

    # profiles
    profile_name:str = "default"

    # micro‑jolt anti‑yank guard (new)
    micro_jolt_radius_norm: float = 0.12   # active for tiny stick magnitudes
    micro_slew_cap_pixels:  int   = 3      # max change per tick inside the tiny radius
    dir_flip_guard:         bool  = True   # extra clamp when dx/dy sign flips inside tiny radius

    # cover guard (prevents camera yank when entering / exiting cover)
    cover_guard_enabled: bool = True
    cover_button: str = "A"           # Gears cover bind
    cover_guard_ms: int = 180         # active window after press (ms)
    cover_release_ms: int = 120       # small settle window after release (ms)
    cover_scale: float = 0.85         # temporary sensitivity scale during guard
    cover_extra_clamp: int = 2        # extra px/tick clamp while guard active
    cover_extra_slew: int = 1         # extra slew tightening while guard active

    # cover guard+ tuning
    cover_snap_max_px: int = 6         # absolute px/tick ceiling right after cover engage
    cover_gate_norm: float = 0.10      # below this processed stick magnitude, clamp harder
    cover_decay_ms: int = 220          # extra clamp decays over this period from 100%->0%
    cover_ads_exempt: bool = True      # if ADS is active, skip extra cover clamp

    # gameplay reliability / diagnostics
    adaptive_caps_enabled: bool = True  # lets caps grow with sensitivity so slider changes are not flattened
    adaptive_cap_max_multiplier: float = 6.0
    runtime_diagnostics: bool = True    # status/log hints when focus, caps, gates, or SendInput block output

    # v6.2: Pure right-stick authority. This is the simple contract the app
    # should obey for Gears: only the current right-stick vector and the
    # configured stick sensitivity can create mouse output. Cover, action
    # buttons, left stick, camera-settle timers, ADS transitions, prior dx/dy,
    # and game camera movement never multiply, suppress, ramp, or replay input.
    pure_right_stick_authority: bool = True
    pure_right_stick_single_sensitivity: bool = False  # False keeps the selected ADS value; True uses base value even while LT is held
    pure_right_stick_log: bool = True
    # v6.5: stateless center floor. The app should not use stateful start/stop
    # gates or release-tail brakes; those created pops/stutters. This is a simple
    # right-stick-only rule: below this magnitude, emit zero; above it, emit the
    # current stick vector normally. No cover/action/left-stick/camera state is read.
    pure_center_floor_norm: float = 0.250
    pure_center_floor_log: bool = True

    # Legacy v6.3/v6.4 knobs are kept for config compatibility but ignored by
    # the v6.5 pure path. Defaults are OFF so stale profiles cannot revive them.
    pure_release_tail_brake_enabled: bool = False
    pure_release_tail_zero_norm: float = 0.12
    pure_release_tail_drop_norm: float = 0.012
    pure_release_tail_frames: int = 0
    pure_release_tail_log: bool = False
    pure_right_stick_start_norm: float = 0.0
    pure_right_stick_stop_norm: float = 0.0
    pure_right_stick_center_log: bool = False

    # v5.1: Right-stick authority mode for Gears/Redux.
    # In this mode, only the current right-stick vector and the selected base/ADS sensitivity
    # may determine mouse output. Cover state, left-stick movement, LT transition state, and
    # previous dx/dy are not allowed to multiply, decay, ramp, or replay camera motion.
    right_stick_authority_mode: bool = True
    authority_disable_state_guards: bool = True   # disable cover/ADS/left-stick output modifiers; keep right-stick deadzone/release flush
    authority_no_accumulator: bool = True          # no delayed subpixel bank; output is rounded from current stick only
    authority_rounding: str = "nearest"            # nearest | trunc
    authority_log_state_blocks: bool = True        # log if a non-right-stick state would have affected output

    # v5.4: strict analog authority. This keeps camera output proportional to the
    # current right-stick vector only. No soft-zone, curve, jitter gate, scheduler
    # per-second cap, or square axis clamp is allowed to reshape the aim vector.
    authority_linear_stick_response: bool = True   # bypass curve exponent in authority mode
    authority_disable_softzone: bool = True        # bypass soft-zone gain shaping in authority mode
    authority_jitter_threshold_max: int = 0        # avoid threshold pop/flicker in authority mode
    authority_fixed_cap_enabled: bool = True       # use a stable px/tick ceiling instead of dt-based cap changes
    authority_fixed_cap_px: int = 48              # stable authority cap; radial, angle-preserving
    preserve_vector_caps: bool = True             # caps scale the whole vector, never clamp X/Y separately

    # v5.4: cap-normalized authority. The fixed cap is the actual full-stick
    # speed, not a last-second clamp after a huge pre-cap value. This prevents
    # tiny right-stick input from becoming a large mouse delta during game camera
    # auto-rotation/cover angle changes.
    authority_direct_cap_output: bool = True       # dx/dy = right-stick vector * min(raw gain, fixed cap)
    authority_use_fixed_cap_as_speed: bool = True  # full-stick output max is authority_fixed_cap_px
    authority_center_zero_norm: float = 0.250      # hard zero post-deadzone idle residue; only intentional right-stick emits

    # v5.8 vertical pitch authority. Gears' third-person pitch camera is more
    # prone to snap/yank than yaw, especially while ADS or in cover. This is a
    # stable vertical axis contract, not a context sensitivity multiplier.
    authority_vertical_guard_enabled: bool = False
    authority_vertical_scale: float = 0.62          # constant pitch scalar, applied before rounding/caps
    authority_vertical_cap_px: int = 28             # global max vertical px/tick
    authority_ads_vertical_cap_px: int = 22         # LT/ADS pitch ceiling
    authority_cover_vertical_cap_px: int = 20       # cover/cover-window pitch ceiling
    authority_settle_vertical_cap_px: int = 16      # camera quarantine/ramp pitch ceiling
    authority_vertical_slew_enabled: bool = True
    authority_vertical_slew_px: int = 10            # normal max vertical step per tick
    authority_ads_cover_vertical_slew_px: int = 6   # max vertical step during ADS/cover/settle

    # Camera-settle lockout: the game can rotate/reframe the camera by itself
    # during cover/transition frames. From outside the game, we cannot read the
    # camera angle, so pause only tiny/non-deliberate mouse output for a few
    # frames after likely auto-camera events. Clear right-stick input overrides it.
    camera_settle_guard_enabled: bool = True
    camera_settle_ms: int = 220
    camera_settle_right_stick_override_norm: float = 0.18
    camera_settle_cover_button: bool = True
    camera_settle_ads_transition: bool = False
    # v5.4: Gears cover can rotate/reframe the camera even while the right stick
    # is held. During the first part of that camera snap, do not allow a
    # right-stick override; otherwise worker output stacks onto the game's
    # camera correction and feels like a yank.
    camera_settle_hard_lock_ms: int = 120
    camera_settle_flush_on_edge: bool = True
    # v5.6: Gears uses the same A button for cover, roll, roadie-run, and movement actions.
    # Treating both press and release as camera events caused repeated lock/unlock bursts.
    camera_settle_cover_press_edge: bool = True     # trigger settle on A/cover press
    camera_settle_cover_release_edge: bool = False  # release edge usually is not a camera snap; prevents double-trigger
    camera_settle_edge_debounce_ms: int = 160       # ignore repeated/bouncy cover edges for this long
    camera_settle_high_input_norm: float = 0.55     # if right stick is already active, use shorter hard lock
    camera_settle_high_input_hard_lock_ms: int = 55 # avoids full-stick lock/release yank
    # v6.2: cover camera settle uses capped live control, not full input freezing.
    # In Gears, cover attach/slide/peek can keep reframing after the initial button edge,
    # so right-stick override during the settle window can stack with the game camera.
    camera_settle_cover_full_lock: bool = False     # v6.0: do not fully freeze cover by default; use live capped control
    camera_settle_cover_lock_ms: int = 170          # cover control-quarantine duration; overrides generic settle_ms for cover
    camera_settle_cover_ramp_ms: int = 110          # slower ramp back in after cover control-quarantine
    camera_settle_cover_allow_micro_after_ms: int = 90 # legacy micro fallback if full-lock mode is manually re-enabled
    camera_settle_cover_micro_override_norm: float = 0.10 # legacy tiny right-stick max allowed during late full-lock mode
    camera_settle_cover_micro_cap_px: int = 3       # legacy late-cover micro aim cap, prevents frozen feel without yanks

    # v6.0 cover live-control mode. Instead of zeroing the camera while entering
    # cover, keep a small bounded amount of right-stick authority so the camera
    # remains steerable while Gears' third-person camera settles.
    camera_settle_cover_live_control: bool = True
    camera_settle_cover_live_cap_px: int = 12       # max vector px/tick during cover settle; still steerable
    camera_settle_cover_live_hard_cap_px: int = 8   # max vector px/tick during the first cover snap frames
    camera_settle_cover_live_vertical_cap_px: int = 4 # max pitch px/tick while cover live-control is active
    camera_settle_cover_live_log: bool = True
    # v6.2 stable mode: ignore stale v5.9/v6.0 profile values that re-enable
    # full cover lock or over-broad third-person quarantines. The last logs showed
    # those suppressors fighting the live-control model and causing worse yanks/no-control.
    gears_stable_cover_live_mode: bool = True

    # v5.7: third-person camera quarantine. Gears is not a static FPS camera;
    # movement, roadie run, roll/mantle, ADS, wall cover, and action animations
    # can all reframe the camera. These guards create short zero-output windows
    # plus a ramp-out so the worker does not stack mouse deltas onto game camera assists.
    third_person_camera_quarantine_enabled: bool = True
    third_person_settle_on_action_buttons: bool = False
    third_person_settle_on_left_move: bool = False
    third_person_left_move_threshold_norm: float = 0.58
    third_person_left_flip_min_norm: float = 0.62
    third_person_left_flip_dot_threshold: float = -0.20
    third_person_left_edge_hard_lock_ms: int = 35
    third_person_action_hard_lock_ms: int = 85
    third_person_ads_hard_lock_ms: int = 65
    third_person_post_settle_ramp_ms: int = 140
    third_person_ramp_min_scale: float = 0.18
    third_person_ramp_log: bool = False

    camera_settle_log_suppressed: bool = True
    camera_settle_log_first_n: int = 3       # log only first N suppressed frames per settle window
    camera_settle_log_interval_ms: int = 750 # then at most once per interval; gameplay unchanged

    # General ADS / LT anti-acceleration guard.
    # v4.8 only guarded ADS while the left stick was idle. The logs showed LT spikes can
    # also happen while left stick is active, so ADS gets a lighter sustained limiter too.
    ads_guard_enabled: bool = True
    ads_cap_px: int = 48                # sustained ADS absolute px/tick ceiling
    ads_slew_px: int = 10               # sustained ADS max output change per tick
    ads_cap_gain: float = 3.0           # sustained ADS adaptive cap gain ceiling

    # release/drift kill
    release_flush_enabled: bool = True      # hard-zero filter/accumulator when the right stick truly returns to center
    release_flush_raw_norm: float = 0.010   # normalized raw-stick magnitude treated as released after deadzone
    release_flush_frames: int = 2           # consecutive centered samples before hard-zero; 1-2 feels instant
    idle_accum_decay: float = 0.35          # decay any subpixel bank while released so jitter-hold cannot fake drift
    discard_clamped_backlog: bool = True # caps/slew are limiters, not queues; prevents delayed replay/yank after release
    max_accum_bank_px: float = 2.0          # max preserved accumulator after limiting; keeps only tiny fractional/subpixel residue

    # ADS / LT stationary anti-yank guard
    # Gears/Redux appears to react differently when LT is held and the player is not moving.
    # This path prevents ADS sensitivity/cap changes from becoming a stationary camera yank.
    ads_stationary_guard_enabled: bool = True
    ads_stationary_left_deadzone_norm: float = 0.12  # left stick magnitude below this counts as stationary
    ads_stationary_cap_px: int = 18                  # absolute px/tick ceiling while ADS + stationary
    ads_stationary_slew_px: int = 4                  # max per-tick output change while ADS + stationary
    ads_stationary_cap_gain: float = 2.0             # cap adaptive gain ceiling while ADS + stationary
    ads_release_flush_frames: int = 1                # centered right stick frames needed to flush while ADS + stationary
    ads_transition_flush_raw_norm: float = 0.04      # clear stale accumulator on LT edge if right stick is near center

    # v4.9 LT transition tuning: prevent ADS/LT from muting the worker or causing a one-frame flicker.
    ads_transition_damping_frames: int = 4           # short damp window after LT changes state; 0 disables
    ads_transition_slew_px: int = 8                  # max output step during the LT transition damp window
    ads_transition_cap_px: int = 24                  # hard cap during the LT transition damp window
    ads_transition_center_suppress_norm: float = 0.025 # suppress one-frame LT flicker only when right stick is truly near center
    ads_transition_filter_decay: float = 0.35        # keep some filter state on LT edge instead of zeroing active aim
    ads_jitter_threshold_max: int = 0                # ADS should not inherit a high hip-fire jitter value that mutes micro aim
    ads_stationary_min_output_px: int = 1            # allow valid ADS micro movement instead of feeling disabled

def ensure_profile_dir():
    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
    except Exception:
        logging.exception("ensure_profile_dir failed")

def profile_path(name:str)->str:
    ensure_profile_dir()
    safe = "".join(c for c in name if c.isalnum() or c in ("-","_")).strip() or "default"
    return os.path.join(PROFILE_DIR, f"{safe}.json")

def list_profiles()->list[str]:
    ensure_profile_dir()
    out = []
    for f in os.listdir(PROFILE_DIR):
        if f.endswith(".json"):
            out.append(os.path.splitext(f)[0])
    if "default" not in out:
        out.insert(0, "default")
    return sorted(set(out))

def _merged_config_dict(raw: object) -> dict:
    """Merge persisted config/profile JSON while ignoring stale unknown keys."""
    base = asdict(Config())
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in base:
                base[k] = v

    # Compatibility upgrade: older builds defaulted to a single Reloaded-only title.
    # Gears Redux/UE3 builds often expose different foreground titles, so allow common aliases.
    if str(base.get("target_window_substring", "")).strip() == "Gears of War: Reloaded":
        base["target_window_substring"] = "Gears of War|WarGame|Redux|Reloaded|WarGame.exe"

    # v4.4: old configs saved this as True, which made normal Gears gameplay feel dead
    # whenever A/B/X/Y were held. Keep it opt-in unless the user deliberately enables it.
    if not isinstance(raw, dict) or "inhibit_mouse_when_buttons" not in raw:
        base["inhibit_mouse_when_buttons"] = False
    return base

def load_config(p:str)->Config:
    if os.path.exists(p):
        try:
            raw = json.load(open(p,"r",encoding="utf-8"))
            return Config(**_merged_config_dict(raw))
        except Exception:
            logging.exception("load_config failed")
    return Config()

def save_config(p:str, cfg:Config)->None:
    try:
        with open(p,"w",encoding="utf-8") as f: json.dump(asdict(cfg), f, indent=2)
    except Exception: logging.exception("save_config failed")

def save_profile(name:str, cfg:Config)->None:
    try:
        save_config(profile_path(name), cfg)
    except Exception:
        logging.exception("save_profile failed")

def load_profile(name:str)->Config|None:
    try:
        p = profile_path(name)
        if os.path.exists(p):
            raw = json.load(open(p,"r",encoding="utf-8"))
            return Config(**_merged_config_dict(raw))
    except Exception:
        logging.exception("load_profile failed")
    return None

def delete_profile(name:str)->bool:
    try:
        if name == "default":  # safeguard
            return False
        p = profile_path(name)
        if os.path.exists(p):
            os.remove(p); return True
    except Exception:
        logging.exception("delete_profile failed")
    return False


def ensure_script_dir():
    try:
        os.makedirs(SCRIPT_DIR, exist_ok=True)
    except Exception:
        logging.exception("ensure_script_dir failed")

def script_path(name: str) -> str:
    ensure_script_dir()
    safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip() or "default"
    return os.path.join(SCRIPT_DIR, f"{safe}.jirs")

def list_scripts() -> list[str]:
    ensure_script_dir()
    out = []
    try:
        for f in os.listdir(SCRIPT_DIR):
            if f.endswith(".jirs"):
                out.append(os.path.splitext(f)[0])
    except Exception:
        logging.exception("list_scripts failed")
    return sorted(set(out))

def save_script(name: str, text: str) -> None:
    try:
        with open(script_path(name), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        logging.exception("save_script failed")
        raise

def load_script(name: str) -> str | None:
    try:
        p = script_path(name)
        if os.path.exists(p):
            return open(p, "r", encoding="utf-8").read()
    except Exception:
        logging.exception("load_script failed")
    return None

def delete_script(name: str) -> bool:
    try:
        p = script_path(name)
        if os.path.exists(p):
            os.remove(p)
            return True
    except Exception:
        logging.exception("delete_script failed")
    return False

# ----------------------------- Math --------------------------------

def normalize_right_stick(x:int, y:int, dz:int) -> tuple[float,float]:
    """Radial deadzone with continuous re-scaling."""
    try:
        nx = max(-1.0, min(1.0, x/32767.0))
        ny = max(-1.0, min(1.0, y/32767.0))
        mag = math.hypot(nx, ny)
        dz_n = max(0.0, min(1.0, dz/32767.0))
        if mag <= dz_n:
            return 0.0, 0.0
        new_mag = (mag - dz_n) / max(1e-6, (1.0 - dz_n))
        scale = new_mag / max(1e-6, mag)
        nx *= scale; ny *= scale
        # v5.0: radial output must be capped to unit length, not only per-axis.
        # The previous per-axis clamp allowed diagonal magnitudes > 1.0, which
        # multiplied into huge ADS pre-cap deltas and felt like acceleration/yank.
        out_mag = math.hypot(nx, ny)
        if out_mag > 1.0:
            nx /= out_mag
            ny /= out_mag
        return max(-1.0, min(1.0, nx)), max(-1.0, min(1.0, ny))
    except Exception:
        return 0.0, 0.0

def apply_curve(v:float, exp:float)->float:
    s = 1.0 if v>=0 else -1.0
    try:
        return s * (abs(v) ** max(0.1, finite_float(exp, 1.0, 0.1, 10.0)))
    except Exception:
        return s * abs(v)

def clamp_vector_radial_int(dx:int, dy:int, cap:int) -> tuple[int, int]:
    """Limit vector magnitude without changing its aim angle.

    The older square clamp limited X and Y independently, so a vector like
    (302,-77) could become (54,-54), turning a mostly-horizontal right-stick
    input into a diagonal yank. This scales the whole vector instead.
    """
    try:
        cap_i = max(0, int(cap))
        if cap_i <= 0:
            return 0, 0
        mag = math.hypot(float(dx), float(dy))
        if mag <= float(cap_i) or mag <= 1e-9:
            return int(dx), int(dy)
        scale = float(cap_i) / mag
        ndx = int(round(float(dx) * scale))
        ndy = int(round(float(dy) * scale))
        # Rounding can very slightly exceed the circle; trim deterministically.
        for _ in range(4):
            if math.hypot(ndx, ndy) <= float(cap_i) + 1e-9:
                break
            if abs(ndx) >= abs(ndy) and ndx != 0:
                ndx -= 1 if ndx > 0 else -1
            elif ndy != 0:
                ndy -= 1 if ndy > 0 else -1
            else:
                break
        return ndx, ndy
    except Exception:
        return int(max(-cap, min(cap, dx))), int(max(-cap, min(cap, dy)))


def finite_float(value, default: float = 0.0, minv: float | None = None, maxv: float | None = None) -> float:
    """Return a finite float only; repair NaN/Inf/bad config values safely."""
    try:
        out = float(value)
    except Exception:
        out = float(default)
    if not math.isfinite(out):
        out = float(default)
    if minv is not None and out < minv:
        out = float(minv)
    if maxv is not None and out > maxv:
        out = float(maxv)
    return out

def finite_int(value, default: int = 0, minv: int | None = None, maxv: int | None = None) -> int:
    """Return an int only after rejecting NaN/Inf, so int() never crashes the worker."""
    out_f = finite_float(value, float(default), None, None)
    try:
        out = int(out_f)
    except Exception:
        out = int(default)
    if minv is not None and out < minv:
        out = int(minv)
    if maxv is not None and out > maxv:
        out = int(maxv)
    return out

def finite_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on", "enabled"):
            return True
        if v in ("0", "false", "no", "off", "disabled"):
            return False
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    return bool(default)

_CONFIG_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "poll_hz": (60, 1000),
    "base_sens": (0.01, 1000.0),
    "ads_sens": (0.01, 1000.0),
    "game_slider_max": (1, 10000),
    "game_slider_current": (0.1, 10000.0),
    "desired_base_slider": (0.1, 10000.0),
    "desired_ads_slider": (0.1, 10000.0),
    "ads_trigger_threshold": (0, 255),
    "deadzone_right": (0, 32767),
    "curve_exponent": (0.1, 10.0),
    "pixel_scale": (0.0, 100000.0),
    "jitter_threshold": (0, 1000),
    "smoothing_alpha": (0.0, 0.95),
    "sens_ramp": (0.0, 1.0),
    "max_pixels_per_tick": (1, 100000),
    "max_pixels_per_second": (1, 1000000),
    "ads_hysteresis": (0, 255),
    "debug_history": (60, 5000),
    "engage_threshold_norm": (0.0, 0.5),
    "release_threshold_norm": (0.0, 0.5),
    "softzone_k": (1.0, 10.0),
    "idle_epsilon": (0.0, 1.0),
    "idle_frames_to_zero": (1, 10000),
    "micro_jolt_radius_norm": (0.0, 1.0),
    "micro_slew_cap_pixels": (1, 1000),
    "cover_guard_ms": (0, 2000),
    "cover_release_ms": (0, 2000),
    "cover_scale": (0.5, 1.0),
    "cover_extra_clamp": (0, 1000),
    "cover_extra_slew": (0, 1000),
    "cover_snap_max_px": (1, 1000),
    "cover_gate_norm": (0.0, 1.0),
    "cover_decay_ms": (1, 5000),
    "adaptive_cap_max_multiplier": (1.0, 20.0),
    "ads_cap_px": (1, 1000),
    "ads_slew_px": (1, 1000),
    "ads_cap_gain": (1.0, 20.0),
    "release_flush_raw_norm": (0.0, 0.20),
    "release_flush_frames": (1, 20),
    "idle_accum_decay": (0.0, 1.0),
    "max_accum_bank_px": (0.0, 100.0),
    "ads_stationary_left_deadzone_norm": (0.0, 1.0),
    "ads_stationary_cap_px": (1, 1000),
    "ads_stationary_slew_px": (1, 1000),
    "ads_stationary_cap_gain": (1.0, 20.0),
    "ads_release_flush_frames": (1, 20),
    "ads_transition_flush_raw_norm": (0.0, 0.25),
    "ads_transition_damping_frames": (0, 60),
    "ads_transition_slew_px": (1, 1000),
    "ads_transition_cap_px": (1, 1000),
    "ads_transition_center_suppress_norm": (0.0, 0.25),
    "ads_transition_filter_decay": (0.0, 1.0),
    "ads_jitter_threshold_max": (0, 1000),
    "ads_stationary_min_output_px": (0, 1000),
    "authority_jitter_threshold_max": (0, 1000),
    "authority_fixed_cap_px": (1, 1000),
    "authority_center_zero_norm": (0.0, 0.50),
    "pure_center_floor_norm": (0.0, 0.50),
    "pure_release_tail_zero_norm": (0.0, 0.30),
    "pure_release_tail_drop_norm": (0.0, 0.10),
    "pure_release_tail_frames": (0, 30),
    "pure_right_stick_start_norm": (0.0, 0.50),
    "pure_right_stick_stop_norm": (0.0, 0.50),
    "authority_vertical_scale": (0.05, 1.0),
    "authority_vertical_cap_px": (1, 1000),
    "authority_ads_vertical_cap_px": (1, 1000),
    "authority_cover_vertical_cap_px": (1, 1000),
    "authority_settle_vertical_cap_px": (1, 1000),
    "authority_vertical_slew_px": (1, 1000),
    "authority_ads_cover_vertical_slew_px": (1, 1000),
    "camera_settle_ms": (0, 2000),
    "camera_settle_right_stick_override_norm": (0.0, 1.0),
    "camera_settle_hard_lock_ms": (0, 1000),
    "camera_settle_edge_debounce_ms": (0, 2000),
    "camera_settle_high_input_norm": (0.0, 1.0),
    "camera_settle_high_input_hard_lock_ms": (0, 1000),
    "camera_settle_cover_lock_ms": (0, 2000),
    "camera_settle_cover_ramp_ms": (0, 2000),
    "camera_settle_cover_allow_micro_after_ms": (0, 2000),
    "camera_settle_cover_micro_override_norm": (0.0, 1.0),
    "camera_settle_cover_micro_cap_px": (0, 1000),
    "camera_settle_cover_live_cap_px": (0, 1000),
    "camera_settle_cover_live_hard_cap_px": (0, 1000),
    "camera_settle_cover_live_vertical_cap_px": (0, 1000),
    "third_person_left_move_threshold_norm": (0.0, 1.0),
    "third_person_left_flip_min_norm": (0.0, 1.0),
    "third_person_left_flip_dot_threshold": (-1.0, 1.0),
    "third_person_left_edge_hard_lock_ms": (0, 1000),
    "third_person_action_hard_lock_ms": (0, 1000),
    "third_person_ads_hard_lock_ms": (0, 1000),
    "third_person_post_settle_ramp_ms": (0, 2000),
    "third_person_ramp_min_scale": (0.0, 1.0),
    "camera_settle_log_first_n": (0, 100),
    "camera_settle_log_interval_ms": (0, 10000),
}

def _coerce_config_value(key: str, value, default):
    lo, hi = _CONFIG_BOUNDS.get(key, (None, None))
    if isinstance(default, bool):
        return finite_bool(value, default)
    if isinstance(default, int) and not isinstance(default, bool):
        return finite_int(value, default, None if lo is None else int(lo), None if hi is None else int(hi))
    if isinstance(default, float):
        return finite_float(value, default, lo, hi)
    if isinstance(default, str):
        return str(value if value is not None else default)
    return value

def sanitize_config_payload(cfg_obj: object) -> dict:
    """Return a complete, type-safe Config dict. Bad values get repaired before reaching the worker loop."""
    defaults = asdict(Config())
    if isinstance(cfg_obj, Config):
        raw = asdict(cfg_obj)
    elif isinstance(cfg_obj, dict):
        raw = dict(cfg_obj)
    elif hasattr(cfg_obj, "__dict__"):
        raw = dict(vars(cfg_obj))
    else:
        raw = {}
    out = dict(defaults)
    for k, v in raw.items():
        if k in defaults:
            out[k] = _coerce_config_value(k, v, defaults[k])
    # Normalize enumerated string settings.
    out["ads_trigger"] = str(out.get("ads_trigger", "LT")).upper()
    if out["ads_trigger"] not in ("LT", "RT"):
        out["ads_trigger"] = defaults["ads_trigger"]
    out["cover_button"] = str(out.get("cover_button", "A")).upper()
    if out["cover_button"] not in _BUTTON_NAME_TO_FLAG:
        out["cover_button"] = defaults["cover_button"]
    return out

def sens_multiplier_from_sliders(game_val:float, desired_val:float, game_max:float|None=None)->float:
    # Base ratio of what you want vs what the game is set to
    game = max(0.1, float(game_val)); desired = max(0.1, float(desired_val))
    mul = desired / game
    # If a game max is provided, softly clamp extreme multipliers that are unrealistic relative to menu scale
    if game_max is not None:
        try:
            # If desired or game is out of menu bounds, keep sane
            gmax = max(0.1, float(game_max))
            # Allow up to 4x of menu scale delta before hard clamp
            soft_cap = max(2.0, min(8.0, gmax / max(0.1, min(desired, game))))
            if mul > soft_cap:
                mul = soft_cap + (mul - soft_cap) * 0.25  # compress tail
        except Exception:
            pass
    return max(0.05, min(mul, 500.0))

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
        self._next_pad_scan = 0.0
        # Keep mouse polling high, but throttle UI paint traffic to avoid needless CPU/GPU churn.
        self._ui_min_interval = 1.0/30.0
        self._ui_next = 0.0
        self._next_focus_check = 0.0
        self._focused_window_ok = True
        self._command_lock = threading.Lock()
        self._pending_cfg_dict: dict | None = None
        self._restart_requested = False
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
        self._nxp_prev = 0.0  # prev processed stick X (after curve/filters)
        self._nyp_prev = 0.0
        self._cover_until = 0.0
        self._cover_active = False
        self._cover_pressed_prev = False
        self._next_status_emit = 0.0
        self._last_sendinput_ok = True
        self._force_sens_snap = True
        self._cap_hit_streak = 0
        self._gate_block_streak = 0
        self._send_attempt_count = 0
        self._raw_idle_frames = 0
        self._ads_stationary_guard_active_prev = False
        self._ads_transition_damp_frames_left = 0
        self._camera_settle_until = 0.0
        self._camera_settle_hard_until = 0.0
        self._camera_settle_reason = ""
        self._camera_settle_started_at = 0.0
        self._camera_settle_cover_until = 0.0
        self._camera_settle_cover_ramp_until = 0.0
        self._cover_button_pressed_prev = False
        self._last_camera_settle_edge_time = -999.0
        self._camera_settle_ramp_until = 0.0
        self._left_move_active_prev = False
        self._left_dir_prev = (0.0, 0.0)
        self._third_person_action_mask_prev = 0
        self._settle_suppress_count = 0
        self._last_settle_log_time = 0.0
        self._pure_prev_raw_mag = 0.0
        self._pure_release_tail_frames_left = 0
        self._pure_last_tail_log_time = 0.0
        self._pure_stick_active = False
        self._pure_last_center_log_time = 0.0


    def _reset_motion_state(self) -> None:
        self._accum_x = 0.0; self._accum_y = 0.0
        self._f_nx = 0.0; self._f_ny = 0.0
        self._sens_curr = 0.0
        self._dx_prev = 0
        self._dy_prev = 0
        self._nxp_prev = 0.0
        self._nyp_prev = 0.0
        self._engaged = False
        self._idle_frames = 0
        self._cover_until = 0.0
        self._cover_active = False
        self._cover_pressed_prev = False
        self._gate_block_streak = 0
        self._cap_hit_streak = 0
        self._raw_idle_frames = 0
        self._ads_stationary_guard_active_prev = False
        self._ads_transition_damp_frames_left = 0
        self._camera_settle_until = 0.0
        self._camera_settle_hard_until = 0.0
        self._camera_settle_reason = ""
        self._camera_settle_started_at = 0.0
        self._camera_settle_cover_until = 0.0
        self._camera_settle_cover_ramp_until = 0.0
        self._cover_button_pressed_prev = False
        self._last_camera_settle_edge_time = -999.0
        self._camera_settle_ramp_until = 0.0
        self._left_move_active_prev = False
        self._left_dir_prev = (0.0, 0.0)
        self._third_person_action_mask_prev = 0
        self._settle_suppress_count = 0
        self._last_settle_log_time = 0.0
        self._pure_prev_raw_mag = 0.0
        self._pure_release_tail_frames_left = 0
        self._pure_last_tail_log_time = 0.0
        self._pure_stick_active = False
        self._pure_last_center_log_time = 0.0

    def _apply_config_now(self, cfg_dict:object) -> None:
        # Merge partial payloads over the current config before sanitizing.
        # Full GUI applies still work, and future targeted applies cannot reset unrelated values.
        merged = asdict(self.cfg)
        if isinstance(cfg_dict, dict):
            incoming = cfg_dict.items()
        elif hasattr(cfg_dict, "__dict__"):
            incoming = vars(cfg_dict).items()
        else:
            incoming = []
        for k, v in incoming:
            if k in merged:
                merged[k] = v
        safe = sanitize_config_payload(merged)
        changed = []
        for k, v in safe.items():
            if hasattr(self.cfg, k):
                old_v = getattr(self.cfg, k)
                setattr(self.cfg, k, v)
                if old_v != v:
                    changed.append(k)
        if changed:
            logging.info("Worker config applied: %s", ",".join(changed))
            # Structural/focus changes should not keep stale accumulators or ADS/cover state.
            structural = {
                "enabled", "target_window_substring", "only_when_focused", "poll_hz",
                "pure_right_stick_authority", "pure_right_stick_single_sensitivity", "pure_right_stick_log",
                "pure_center_floor_norm", "pure_center_floor_log",
                "pure_release_tail_brake_enabled", "pure_release_tail_zero_norm",
                "pure_release_tail_drop_norm", "pure_release_tail_frames", "pure_release_tail_log",
                "pure_right_stick_start_norm", "pure_right_stick_stop_norm", "pure_right_stick_center_log",
                "deadzone_right", "curve_exponent", "invert_y", "ads_trigger",
                "ads_trigger_threshold", "cover_button", "cover_guard_enabled",
                "inhibit_mouse_when_buttons", "engage_threshold_norm", "release_threshold_norm",
                "release_flush_enabled", "release_flush_raw_norm", "release_flush_frames",
                "right_stick_authority_mode", "authority_disable_state_guards",
                "authority_no_accumulator", "authority_rounding",
                "ads_stationary_guard_enabled", "ads_stationary_left_deadzone_norm",
                "ads_stationary_cap_px", "ads_stationary_slew_px",
                "ads_release_flush_frames", "ads_transition_flush_raw_norm",
                "ads_transition_damping_frames", "ads_transition_slew_px",
                "ads_transition_cap_px", "ads_transition_center_suppress_norm",
                "ads_transition_filter_decay", "ads_jitter_threshold_max",
                "ads_stationary_min_output_px", "ads_guard_enabled", "ads_cap_px", "ads_slew_px",
                "authority_linear_stick_response", "authority_disable_softzone",
                "authority_jitter_threshold_max", "authority_fixed_cap_enabled",
                "authority_fixed_cap_px", "preserve_vector_caps",
                "authority_direct_cap_output", "authority_use_fixed_cap_as_speed",
                "authority_center_zero_norm", "authority_vertical_guard_enabled",
                "authority_vertical_scale", "authority_vertical_cap_px",
                "authority_ads_vertical_cap_px", "authority_cover_vertical_cap_px",
                "authority_settle_vertical_cap_px", "authority_vertical_slew_enabled",
                "authority_vertical_slew_px", "authority_ads_cover_vertical_slew_px",
                "camera_settle_guard_enabled",
                "camera_settle_ms", "camera_settle_right_stick_override_norm",
                "camera_settle_cover_button", "camera_settle_ads_transition",
                "camera_settle_hard_lock_ms", "camera_settle_flush_on_edge",
                "camera_settle_cover_press_edge", "camera_settle_cover_release_edge",
                "camera_settle_edge_debounce_ms", "camera_settle_high_input_norm",
                "camera_settle_high_input_hard_lock_ms",
                "camera_settle_cover_full_lock", "camera_settle_cover_lock_ms",
                "camera_settle_cover_ramp_ms", "camera_settle_cover_allow_micro_after_ms",
                "camera_settle_cover_micro_override_norm", "camera_settle_cover_micro_cap_px",
                "camera_settle_cover_live_control", "camera_settle_cover_live_cap_px",
                "camera_settle_cover_live_hard_cap_px", "camera_settle_cover_live_vertical_cap_px",
                "camera_settle_cover_live_log", "gears_stable_cover_live_mode",
                "third_person_camera_quarantine_enabled",
                "third_person_settle_on_action_buttons", "third_person_settle_on_left_move",
                "third_person_left_move_threshold_norm", "third_person_left_flip_min_norm",
                "third_person_left_flip_dot_threshold", "third_person_left_edge_hard_lock_ms",
                "third_person_action_hard_lock_ms", "third_person_ads_hard_lock_ms",
                "third_person_post_settle_ramp_ms", "third_person_ramp_min_scale",
                "third_person_ramp_log",
                "camera_settle_log_suppressed", "camera_settle_log_first_n",
                "camera_settle_log_interval_ms",
            }
            sens_keys = {
                "use_correlation", "base_sens", "ads_sens", "game_slider_current",
                "desired_base_slider", "desired_ads_slider", "game_slider_max",
                "pixel_scale", "sens_ramp", "adaptive_caps_enabled",
                "adaptive_cap_max_multiplier", "discard_clamped_backlog",
                "max_accum_bank_px", "ads_stationary_cap_gain", "ads_cap_gain",
            }
            if any(k in structural for k in changed):
                self._reset_motion_state()
                self._force_sens_snap = True
                if "cover_guard_enabled" in changed and not bool(getattr(self.cfg, "cover_guard_enabled", False)):
                    self._cover_until = 0.0
                    self._cover_active = False
                    self._cover_pressed_prev = False
                    if bool(getattr(self.cfg, 'runtime_diagnostics', True)):
                        self._emit_status("Cover Guard OFF — cover damping and cover clamps cleared")
                if "inhibit_mouse_when_buttons" in changed and not bool(getattr(self.cfg, "inhibit_mouse_when_buttons", False)):
                    if bool(getattr(self.cfg, 'runtime_diagnostics', True)):
                        self._emit_status("Face-button inhibit OFF — A/B/X/Y will not suppress output")
            elif any(k in sens_keys for k in changed):
                # Make a live sensitivity change visible on the very next tick.
                # The old code could hide changes behind a slow/zero ramp.
                self._force_sens_snap = True
            if bool(getattr(self.cfg, 'runtime_diagnostics', True)):
                shown = ",".join(changed[:8]) + ("..." if len(changed) > 8 else "")
                self._emit_status(f"Worker applied: {shown}")

    def request_apply_config(self, cfg_dict:object):
        try:
            if isinstance(cfg_dict, dict):
                pending = {k: v for k, v in cfg_dict.items() if hasattr(self.cfg, k)}
            elif hasattr(cfg_dict, "__dict__"):
                pending = {k: v for k, v in vars(cfg_dict).items() if hasattr(self.cfg, k)}
            else:
                pending = {}
            with self._command_lock:
                self._pending_cfg_dict = pending
        except Exception:
            logging.exception("request_apply_config failed")

    def request_restart(self):
        with self._command_lock:
            self._restart_requested = True

    def _drain_control_requests(self) -> None:
        with self._command_lock:
            pending = self._pending_cfg_dict
            restart = self._restart_requested
            self._pending_cfg_dict = None
            self._restart_requested = False
        if pending is not None:
            self._apply_config_now(pending)
            self._emit_status("Config applied to worker")
        if restart:
            self._reset_motion_state()
            self._emit_status("Worker: soft restart")

    @QtCore.pyqtSlot(object)
    def apply_config(self, cfg_dict:object):
        # Slot-compatible wrapper. The polling loop applies it at a safe tick boundary.
        self.request_apply_config(cfg_dict)

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
            self.request_restart()
        except Exception: logging.exception("pulse_restart failed")

    @QtCore.pyqtSlot()
    def run(self):
        try:
            if not XInput:
                logging.warning("XInput DLL not found; idling.")
                while self._run:
                    time.sleep(0.25)
                return
            logging.info("=== Jacinto Input Refiner v7.0 worker session start ===")
            while self._run:
                if self.bus_ref.isNull():
                    break
                self._drain_control_requests()
                cfg = self.cfg
                pure_authority = bool(getattr(cfg, 'pure_right_stick_authority', True))
                if pure_authority:
                    # v6.2: enforce the simple contract at runtime, overriding stale saved
                    # profile values from v5.4-v6.1. These features tried to infer Gears
                    # camera state from buttons/left stick and caused lock/unlock yanks.
                    try:
                        cfg.right_stick_authority_mode = True
                        cfg.authority_disable_state_guards = True
                        cfg.authority_no_accumulator = True
                        cfg.authority_linear_stick_response = True
                        cfg.authority_disable_softzone = True
                        cfg.authority_jitter_threshold_max = 0
                        cfg.camera_settle_guard_enabled = False
                        cfg.camera_settle_cover_full_lock = False
                        cfg.camera_settle_cover_live_control = False
                        cfg.camera_settle_ads_transition = False
                        cfg.third_person_camera_quarantine_enabled = False
                        cfg.third_person_settle_on_action_buttons = False
                        cfg.third_person_settle_on_left_move = False
                        cfg.cover_guard_enabled = False
                        cfg.inhibit_mouse_when_buttons = False
                        cfg.authority_vertical_guard_enabled = False
                        cfg.pure_release_tail_brake_enabled = False
                        cfg.pure_right_stick_start_norm = 0.0
                        cfg.pure_right_stick_stop_norm = 0.0
                        # v6.9 bugfix: saved profiles from v6.4-v6.8 could keep the
                        # center floor too low (0.075), allowing near-idle stick
                        # residue around 0.08-0.09 to emit mouse movement. In pure
                        # mode this is the only gate: below it, the right stick is
                        # not considered intentionally in use.
                        cfg.pure_center_floor_norm = 0.250
                        cfg.authority_center_zero_norm = 0.250
                    except Exception:
                        pass
                strict_authority = bool(getattr(cfg, 'right_stick_authority_mode', True))
                state_guards_allowed = not (strict_authority and bool(getattr(cfg, 'authority_disable_state_guards', True)))
                tick = 1.0 / max(60, finite_int(getattr(cfg,'poll_hz',240) or 240, 240, 60, 1000))
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
                        if now >= self._next_focus_check:
                            target = getattr(cfg,'target_window_substring','')
                            active_title, active_image = get_foreground_identity()
                            self._focused_window_ok = target_matches_identity(target, active_title, active_image)
                            self._next_focus_check = now + 0.05
                            if not self._focused_window_ok and now >= self._next_status_emit:
                                terms = " | ".join(_split_target_terms(target)) or "<any>"
                                shown_title = active_title[:70] if active_title else "<no title>"
                                shown_exe = os.path.basename(active_image) if active_image else "<no exe>"
                                self._emit_status(f"Waiting for target: {terms} | active: {shown_title} / {shown_exe}")
                                self._next_status_emit = now + 1.0
                        if not self._focused_window_ok:
                            self._reset_motion_state()
                            if now >= self._ui_next:
                                self._ui_next = now + self._ui_min_interval
                                if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                                emitted = True
                            if (now - self._last_emit) > 0.5 and not emitted:
                                if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                                emitted = True
                            if emitted: self._last_emit = now
                            continue
                    else:
                        self._focused_window_ok = True

                    connected = False; gp = None
                    # Prefer the last known pad and only rescan all four pads when needed.
                    if self._last_pad_idx is not None:
                        try:
                            if XInput.XInputGetState(int(self._last_pad_idx), ctypes.byref(self._state)) == 0:
                                gp = self._state.Gamepad; connected = True
                            else:
                                self._last_pad_idx = None
                        except Exception:
                            self._last_pad_idx = None
                    if not connected and now >= self._next_pad_scan:
                        self._next_pad_scan = now + 0.50
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

                    # Inputs → normalized, curved, smoothed
                    nx_raw, ny_raw = normalize_right_stick(gp.sThumbRX, gp.sThumbRY, finite_int(getattr(cfg,'deadzone_right',XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE), XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE, 0, 32767))
                    raw_mag = math.hypot(nx_raw, ny_raw)
                    try:
                        lx_norm = max(-1.0, min(1.0, gp.sThumbLX/32767.0))
                        ly_norm = max(-1.0, min(1.0, gp.sThumbLY/32767.0))
                        lx_raw_mag = math.hypot(lx_norm, ly_norm)
                        # Use a physical 0..1 magnitude for state decisions; diagonals can exceed 1
                        # mathematically, but should not disable guard logic or confuse diagnostics.
                        if lx_raw_mag > 1.0:
                            lx_norm /= lx_raw_mag
                            ly_norm /= lx_raw_mag
                            lx_raw_mag = 1.0
                    except Exception:
                        lx_norm = 0.0
                        ly_norm = 0.0
                        lx_raw_mag = 0.0
                    if strict_authority and bool(getattr(cfg, 'authority_linear_stick_response', True)):
                        # Strict analog authority: do not apply a curve that can feel like
                        # acceleration. Current right-stick vector owns the frame.
                        nx, ny = nx_raw, ny_raw
                    else:
                        nx = apply_curve(nx_raw, finite_float(getattr(cfg,'curve_exponent',1.3), 1.3, 0.1, 10.0))
                        ny = apply_curve(ny_raw, finite_float(getattr(cfg,'curve_exponent',1.3), 1.3, 0.1, 10.0))
                    if bool(getattr(cfg,'invert_y',False)):
                        ny = -ny

                    thr = finite_int(getattr(cfg,'ads_trigger_threshold',45), 45, 0, 255)
                    lt, rt = int(gp.bLeftTrigger), int(gp.bRightTrigger)
                    trig = str(getattr(cfg,'ads_trigger','LT')).upper()

                    # Physical cover/action button edge tracking. This is separate from the
                    # old Cover Guard clamps; even in strict authority mode we still need to
                    # know when Gears is likely to auto-reframe the camera.
                    cover_btn_name = str(getattr(cfg, 'cover_button', 'A')).upper()
                    cover_flag = _BUTTON_NAME_TO_FLAG.get(cover_btn_name, XINPUT_GAMEPAD_A)
                    cover_phys_pressed = bool(gp.wButtons & cover_flag)

                    # --- Cover Guard: tame camera snap when entering/exiting cover ---
                    try:
                        if bool(getattr(cfg, 'cover_guard_enabled', True)):
                            now_s = now
                            pressed = cover_phys_pressed

                            # Refresh only while held, then add release-settle once on the release edge.
                            if pressed:
                                self._cover_until = max(self._cover_until, now_s + finite_int(getattr(cfg,'cover_guard_ms',180), 180, 0, 2000)/1000.0)
                            elif self._cover_pressed_prev:
                                rel_ms = finite_int(getattr(cfg,'cover_release_ms',120), 120, 0, 2000)
                                self._cover_until = max(self._cover_until, now_s + rel_ms/1000.0)

                            self._cover_pressed_prev = pressed
                            self._cover_active = (now_s <= self._cover_until)
                        else:
                            self._cover_until = 0.0
                            self._cover_active = False
                            self._cover_pressed_prev = False
                    except Exception:
                        self._cover_active = False
                    hyst = finite_int(getattr(cfg,'ads_hysteresis',8), 8, 0, 255)
                    ads_before = bool(self._ads_prev)
                    if self._ads_prev:
                        ads = (lt > max(0, thr - hyst)) if (trig=="LT") else (rt > max(0, thr - hyst))
                    else:
                        ads = (lt > min(255, thr + hyst)) if (trig=="LT") else (rt > min(255, thr + hyst))
                    ads_transition = (bool(ads) != ads_before)
                    self._ads_prev = ads

                    # v5.7 third-person camera quarantine. Gears is a third-person camera:
                    # cover, roadie run, roll, mantle, ADS, action buttons, and movement camera
                    # assist can all reframe the camera independent of mouse input. Treat these
                    # as brief camera events, not sensitivity changes. During the hard window we
                    # output zero; during the ramp window we ease back in instead of snapping.
                    camera_settle_edge = False
                    if bool(getattr(cfg, 'camera_settle_guard_enabled', True)):
                        debounce_s = finite_int(getattr(cfg, 'camera_settle_edge_debounce_ms', 160), 160, 0, 2000) / 1000.0

                        def _begin_camera_settle(reason: str, hard_ms_override: int | None = None, use_debounce: bool = True) -> None:
                            nonlocal camera_settle_edge
                            if use_debounce and (now - self._last_camera_settle_edge_time) < debounce_s:
                                return
                            camera_settle_edge = True
                            self._camera_settle_reason = reason
                            self._last_camera_settle_edge_time = now
                            settle_ms = finite_int(getattr(cfg, 'camera_settle_ms', 220), 220, 0, 2000)
                            hard_ms = finite_int(getattr(cfg, 'camera_settle_hard_lock_ms', 120), 120, 0, 1000)
                            cover_reason = str(reason).startswith('cover-button')
                            if cover_reason:
                                # v6.0: cover is still a special camera event, but default behavior is
                                # live capped control, not a full zero-output freeze. Full-lock mode is
                                # still available as an emergency fallback.
                                settle_ms = max(settle_ms, finite_int(getattr(cfg, 'camera_settle_cover_lock_ms', 170), 170, 0, 2000))
                                ramp_ms = finite_int(getattr(cfg, 'camera_settle_cover_ramp_ms', 110), 110, 0, 2000)
                                if bool(getattr(cfg, 'camera_settle_cover_full_lock', False)):
                                    hard_ms = max(hard_ms, settle_ms)
                                else:
                                    high_norm = finite_float(getattr(cfg, 'camera_settle_high_input_norm', 0.55), 0.55, 0.0, 1.0)
                                    if raw_mag >= high_norm:
                                        hard_ms = min(hard_ms, finite_int(getattr(cfg, 'camera_settle_high_input_hard_lock_ms', 55), 55, 0, 1000))
                            else:
                                if hard_ms_override is not None:
                                    hard_ms = min(hard_ms, finite_int(hard_ms_override, hard_ms, 0, 1000))
                                high_norm = finite_float(getattr(cfg, 'camera_settle_high_input_norm', 0.55), 0.55, 0.0, 1.0)
                                if raw_mag >= high_norm:
                                    hard_ms = min(hard_ms, finite_int(getattr(cfg, 'camera_settle_high_input_hard_lock_ms', 55), 55, 0, 1000))
                                ramp_ms = finite_int(getattr(cfg, 'third_person_post_settle_ramp_ms', 140), 140, 0, 2000) if bool(getattr(cfg, 'third_person_camera_quarantine_enabled', True)) else 0
                            self._camera_settle_started_at = now
                            self._camera_settle_until = max(self._camera_settle_until, now + settle_ms / 1000.0)
                            self._camera_settle_hard_until = max(self._camera_settle_hard_until, now + hard_ms / 1000.0)
                            if cover_reason:
                                self._camera_settle_cover_until = max(self._camera_settle_cover_until, now + settle_ms / 1000.0)
                                self._camera_settle_cover_ramp_until = max(self._camera_settle_cover_ramp_until, now + (settle_ms + ramp_ms) / 1000.0)
                            self._camera_settle_ramp_until = max(self._camera_settle_ramp_until, now + (settle_ms + ramp_ms) / 1000.0)
                            self._settle_suppress_count = 0
                            self._last_settle_log_time = 0.0
                            if bool(getattr(cfg, 'camera_settle_flush_on_edge', True)):
                                self._accum_x = 0.0
                                self._accum_y = 0.0
                                self._dx_prev = 0
                                self._dy_prev = 0
                                self._f_nx = 0.0
                                self._f_ny = 0.0

                        cover_pressed_edge = cover_phys_pressed and not self._cover_button_pressed_prev
                        cover_released_edge = (not cover_phys_pressed) and self._cover_button_pressed_prev
                        if bool(getattr(cfg, 'camera_settle_cover_button', True)):
                            if cover_pressed_edge and bool(getattr(cfg, 'camera_settle_cover_press_edge', True)):
                                _begin_camera_settle('cover-button-press')
                            elif cover_released_edge and bool(getattr(cfg, 'camera_settle_cover_release_edge', False)):
                                _begin_camera_settle('cover-button-release')

                        # ADS camera tightening/reframing can also stack with mouse output.
                        if bool(getattr(cfg, 'camera_settle_ads_transition', True)) and ads_transition:
                            _begin_camera_settle('ads-transition', finite_int(getattr(cfg, 'third_person_ads_hard_lock_ms', 65), 65, 0, 1000))

                        if bool(getattr(cfg, 'third_person_camera_quarantine_enabled', True)):
                            # Face/action button presses beyond A can trigger vault, melee, reload/pickup,
                            # interact, or animation camera assists. Only press edges trigger quarantine.
                            # v6.2: do not let A/cover also fire the generic action-button
                            # quarantine. Cover has its own capped live-control path; double-firing
                            # action-button was causing repeated lock/release behavior.
                            action_mask = int((XINPUT_FACE_MASK | XINPUT_GAMEPAD_LEFT_SHOULDER | XINPUT_GAMEPAD_RIGHT_SHOULDER) & ~int(cover_flag))
                            action_state = int(gp.wButtons) & action_mask
                            action_edges = action_state & ~int(self._third_person_action_mask_prev)
                            if bool(getattr(cfg, 'third_person_settle_on_action_buttons', True)) and action_edges:
                                _begin_camera_settle('action-button', finite_int(getattr(cfg, 'third_person_action_hard_lock_ms', 85), 85, 0, 1000))

                            # Movement camera assist: trigger only on start of strong movement or
                            # a major left-stick direction flip. Do not retrigger every normal frame.
                            left_thr = finite_float(getattr(cfg, 'third_person_left_move_threshold_norm', 0.58), 0.58, 0.0, 1.0)
                            left_active = lx_raw_mag >= left_thr
                            left_edge = left_active and not self._left_move_active_prev
                            flip_min = finite_float(getattr(cfg, 'third_person_left_flip_min_norm', 0.62), 0.62, 0.0, 1.0)
                            flip_dot_thr = finite_float(getattr(cfg, 'third_person_left_flip_dot_threshold', -0.20), -0.20, -1.0, 1.0)
                            prev_lx, prev_ly = self._left_dir_prev
                            flip_edge = False
                            if lx_raw_mag >= flip_min and math.hypot(prev_lx, prev_ly) >= flip_min:
                                dot = lx_norm * prev_lx + ly_norm * prev_ly
                                flip_edge = dot <= flip_dot_thr
                            if bool(getattr(cfg, 'third_person_settle_on_left_move', True)) and (left_edge or flip_edge):
                                _begin_camera_settle('left-move' if left_edge else 'left-flip', finite_int(getattr(cfg, 'third_person_left_edge_hard_lock_ms', 35), 35, 0, 1000))

                            self._third_person_action_mask_prev = action_state
                            self._left_move_active_prev = left_active
                            if lx_raw_mag >= 0.20:
                                self._left_dir_prev = (lx_norm, ly_norm)
                            elif lx_raw_mag <= 0.08:
                                self._left_dir_prev = (0.0, 0.0)

                    self._cover_button_pressed_prev = cover_phys_pressed

                    left_idle_thr = finite_float(getattr(cfg, 'ads_stationary_left_deadzone_norm', 0.12), 0.12, 0.0, 1.0)
                    left_stationary = lx_raw_mag <= left_idle_thr
                    ads_guard_raw = bool(getattr(cfg, 'ads_guard_enabled', True)) and bool(ads)
                    ads_stationary_guard_raw = bool(getattr(cfg, 'ads_stationary_guard_enabled', True)) and bool(ads) and left_stationary
                    ads_guard = state_guards_allowed and ads_guard_raw
                    ads_stationary_guard = state_guards_allowed and ads_stationary_guard_raw
                    if ads_transition and state_guards_allowed:
                        # LT changes the game's internal aim state. v4.8 hard-zeroed the filter here,
                        # which prevented yanks but could make LT feel like it disabled the worker.
                        # v4.9 uses a short damp window and only hard-suppresses when the stick is
                        # truly centered; active right-stick input is still allowed through.
                        self._ads_transition_damp_frames_left = finite_int(getattr(cfg, 'ads_transition_damping_frames', 4), 4, 0, 60)
                        if left_stationary and raw_mag <= finite_float(getattr(cfg, 'ads_transition_flush_raw_norm', 0.04), 0.04, 0.0, 0.25):
                            self._accum_x = 0.0
                            self._accum_y = 0.0
                            self._dx_prev = 0
                            self._dy_prev = 0
                            center_suppress = finite_float(getattr(cfg, 'ads_transition_center_suppress_norm', 0.025), 0.025, 0.0, 0.25)
                            if raw_mag <= center_suppress:
                                self._f_nx = 0.0
                                self._f_ny = 0.0
                            else:
                                keep = finite_float(getattr(cfg, 'ads_transition_filter_decay', 0.35), 0.35, 0.0, 1.0)
                                self._f_nx *= keep
                                self._f_ny *= keep

                    # Target sensitivity
                    if bool(getattr(cfg,'use_correlation',True)):
                        base_mult = sens_multiplier_from_sliders(finite_float(getattr(cfg,'game_slider_current',12.0), 12.0, 0.1, 10000.0), finite_float(getattr(cfg,'desired_base_slider',18.0), 18.0, 0.1, 10000.0), finite_float(getattr(cfg,'game_slider_max',30), 30.0, 0.1, 10000.0))
                        ads_mult  = sens_multiplier_from_sliders(finite_float(getattr(cfg,'game_slider_current',12.0), 12.0, 0.1, 10000.0), finite_float(getattr(cfg,'desired_ads_slider',10.0), 10.0, 0.1, 10000.0), finite_float(getattr(cfg,'game_slider_max',30), 30.0, 0.1, 10000.0))
                        sens_tgt = ads_mult if ads else base_mult
                    else:
                        sens_tgt = finite_float(getattr(cfg,'ads_sens',0.10) if ads else getattr(cfg,'base_sens',0.35), 0.10 if ads else 0.35, 0.01, 1000.0)
                    sens_tgt = max(0.01, float(sens_tgt))
                    if pure_authority and bool(getattr(cfg, 'pure_right_stick_single_sensitivity', False)):
                        # Optional stricter mode: even LT/ADS does not switch gain. The
                        # default remains False so the configured ADS value still works,
                        # but no cover/movement/camera state can alter it.
                        if bool(getattr(cfg,'use_correlation',True)):
                            sens_tgt = sens_multiplier_from_sliders(
                                finite_float(getattr(cfg,'game_slider_current',12.0), 12.0, 0.1, 10000.0),
                                finite_float(getattr(cfg,'desired_base_slider',18.0), 18.0, 0.1, 10000.0),
                                finite_float(getattr(cfg,'game_slider_max',30), 30.0, 0.1, 10000.0))
                        else:
                            sens_tgt = finite_float(getattr(cfg,'base_sens',0.35), 0.35, 0.01, 1000.0)

                    # Ramp sensitivity to avoid sudden jumps.
                    # Reliability fix: ramp==0 now means "instant/no ramp" instead of freezing sensitivity forever.
                    ramp = finite_float(getattr(cfg,'sens_ramp',0.20), 0.20, 0.0, 1.0)
                    if self._sens_curr <= 0.0 or self._force_sens_snap or ramp <= 0.0:
                        self._sens_curr = sens_tgt
                        self._force_sens_snap = False
                    else:
                        self._sens_curr = self._sens_curr + ramp * (sens_tgt - self._sens_curr)
                    sens_eff = self._sens_curr
                    if pure_authority:
                        # v6.9 bugfix: pure mode must apply the current config value
                        # directly to the current right-stick sample. A sensitivity
                        # ramp is another time-based state machine and can feel like
                        # acceleration after ADS/cover/camera animation changes.
                        sens_eff = sens_tgt
                        self._sens_curr = sens_tgt

                    if pure_authority:
                        # v6.6 pure path: current right-stick sample only.
                        # No cover/action/left-stick/camera heuristics, no release-tail brake,
                        # no start/stop state gate, no accumulator, no smoothing, no vertical modifier.
                        # The only bug fix is a single existing center floor: post-deadzone residue
                        # below this value is not intentional right-stick input, so it emits zero.
                        center = max(0.250, finite_float(getattr(cfg, 'pure_center_floor_norm', 0.250), 0.250, 0.0, 0.50))
                        center_floor = raw_mag <= center
                        effective_mag = 0.0
                        if center_floor:
                            dx = 0
                            dy = 0
                        else:
                            # v7.0 bugfix: the center floor must not be a hard output cliff.
                            # v6.9 used the floor as an on/off switch only, so raw_mag 0.249
                            # emitted zero but raw_mag 0.251 immediately emitted several pixels.
                            # That destroyed micro-adjustment and felt like random acceleration.
                            # Keep the rule pure/current-sample only: remove the idle floor from
                            # the magnitude, preserve direction, and start output from zero.
                            raw_scale = finite_float(sens_eff, 0.0, 0.0, 100000.0)
                            scale = min(raw_scale, finite_float(getattr(cfg, 'authority_fixed_cap_px', 48), 48.0, 1.0, 1000.0))
                            effective_mag = (raw_mag - center) / max(1e-6, (1.0 - center))
                            effective_mag = max(0.0, min(1.0, effective_mag))
                            dir_scale = effective_mag / max(1e-6, raw_mag)
                            dx_f = nx * dir_scale * scale
                            dy_f = -ny * dir_scale * scale
                            rounding = str(getattr(cfg, 'authority_rounding', 'nearest')).lower()
                            if rounding == 'trunc':
                                dx = finite_int(dx_f, 0, -1000000, 1000000)
                                dy = finite_int(dy_f, 0, -1000000, 1000000)
                            else:
                                dx = finite_int(round(dx_f), 0, -1000000, 1000000)
                                dy = finite_int(round(dy_f), 0, -1000000, 1000000)
                            if bool(getattr(cfg, 'authority_fixed_cap_enabled', True)):
                                dx, dy = clamp_vector_radial_int(dx, dy, finite_int(getattr(cfg, 'authority_fixed_cap_px', 48), 48, 1, 1000))
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                        self._f_nx = nx
                        self._f_ny = ny
                        self._dx_prev = dx
                        self._dy_prev = dy
                        self._pure_prev_raw_mag = raw_mag
                        if dx or dy:
                            ok = send_mouse_move(dx, dy)
                            self._send_attempt_count += 1
                            if ok:
                                self._last_sendinput_ok = True
                            elif now >= self._next_status_emit:
                                self._last_sendinput_ok = False
                                self._emit_status("SendInput failed — run this app at the same privilege level as the game, or the game may be blocking injected mouse input")
                                self._next_status_emit = now + 1.0
                        if center_floor and raw_mag > 0.0 and bool(getattr(cfg, 'pure_center_floor_log', True)) and now >= self._pure_last_center_log_time + 0.75:
                            logging.info("Pure idle zero: raw_mag=%.4f floor=%.4f dx=0 dy=0",
                                         raw_mag, center)
                            self._pure_last_center_log_time = now
                        if bool(getattr(cfg, 'pure_right_stick_log', True)) and (dx or dy) and now >= self._last_settle_log_time + 2.0:
                            logging.info("Pure right-stick output: raw_mag=%.4f floor=%.4f eff_mag=%.4f dx=%s dy=%s sens=%.3f direct_scale=%.3f ads=%s scale_mode=%s",
                                         raw_mag, center, effective_mag if 'effective_mag' in locals() else 0.0, dx, dy, sens_eff, scale if 'scale' in locals() else 0.0, ads, 'ads' if ads and not bool(getattr(cfg, 'pure_right_stick_single_sensitivity', False)) else 'base')
                            self._last_settle_log_time = now
                        self._nxp_prev, self._nyp_prev = nx, ny
                        if now >= self._ui_next:
                            self._ui_next = now + self._ui_min_interval
                            if not self._emit_updated(nx_raw, ny_raw, nx, ny, sens_eff, ads, dx, dy): break
                            if not self._emit_triggers(lt, rt, thr, ads): break
                            emitted = True
                        if emitted:
                            self._last_emit = now
                        elif (now - self._last_emit) > 0.5:
                            if not self._emit_updated(0,0,0,0,0.0,False,0,0): break
                            self._last_emit = now
                        continue

                    # If cover guard is active, temporarily soften sensitivity.
                    # v5.1 authority mode disables this: cover state must not change gain.
                    if self._cover_active and state_guards_allowed:
                        sens_eff *= finite_float(getattr(cfg,'cover_scale',0.85), 0.85, 0.5, 1.0)

                    # Axis smoothing (low-pass).
                    # Reliability fix: smoothing==0 now means raw/no smoothing instead of locking the filter at zero.
                    beta = finite_float(getattr(cfg,'smoothing_alpha',0.25), 0.25, 0.0, 0.95)
                    if strict_authority:
                        # Right-stick authority: no filter inertia. Current right-stick value owns output.
                        self._f_nx = nx
                        self._f_ny = ny
                    elif beta <= 0.0:
                        self._f_nx = nx
                        self._f_ny = ny
                    else:
                        self._f_nx += beta * (nx - self._f_nx)
                        self._f_ny += beta * (ny - self._f_ny)
                    if not (math.isfinite(self._f_nx) and math.isfinite(self._f_ny)):
                        logging.warning("Non-finite filter state repaired: f=(%r,%r)", self._f_nx, self._f_ny)
                        self._f_nx = 0.0
                        self._f_ny = 0.0

                    # v4.7 release-flush drift kill:
                    # When the physical stick returns to deadzone/center, do not let smoothing,
                    # previous dx/dy, or v4.5's subpixel accumulator "bleed off" as fake camera drift.
                    released = False
                    if bool(getattr(cfg, 'release_flush_enabled', True)):
                        release_raw = finite_float(getattr(cfg, 'release_flush_raw_norm', 0.010), 0.010, 0.0, 0.20)
                        if raw_mag <= release_raw:
                            self._raw_idle_frames += 1
                        else:
                            self._raw_idle_frames = 0
                        release_frames = finite_int(getattr(cfg, 'ads_release_flush_frames', 1), 1, 1, 20) if ads_stationary_guard else finite_int(getattr(cfg, 'release_flush_frames', 2), 2, 1, 20)
                        released = self._raw_idle_frames >= release_frames
                    else:
                        self._raw_idle_frames = 0

                    if released:
                        # v4.7: hard release flush. v4.6 decayed the accumulator, but if a
                        # cap-limited backlog existed it could still replay as a let-go yank/sway.
                        self._f_nx = 0.0
                        self._f_ny = 0.0
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                        self._dx_prev = 0
                        self._dy_prev = 0
                        self._engaged = False
                        self._idle_frames = 0

                    ads_transition_damping = state_guards_allowed and (self._ads_transition_damp_frames_left > 0)
                    if ads_transition_damping and raw_mag <= finite_float(getattr(cfg, 'ads_transition_center_suppress_norm', 0.025), 0.025, 0.0, 0.25):
                        # Remove the tiny one-frame LT flicker when the right stick is centered.
                        # This does not mute valid aim because it only applies below this tiny raw threshold.
                        self._accum_x = 0.0
                        self._accum_y = 0.0

                    # Soft zone near zero. In strict authority mode this is disabled by
                    # default because it changes gain based on stick magnitude and can feel
                    # like acceleration in cover-heavy Gears camera states.
                    magp = math.hypot(self._f_nx, self._f_ny)
                    if not (strict_authority and bool(getattr(cfg, 'authority_disable_softzone', True))):
                        k = finite_float(getattr(cfg,'softzone_k', 1.8), 1.8, 1.0, 10.0)
                        if magp > 1e-6 and k > 1.0:
                            scale_soft = magp ** (k - 1.0)
                            self._f_nx *= scale_soft; self._f_ny *= scale_soft
                            magp = math.hypot(self._f_nx, self._f_ny)

                    # Engage/release gating
                    engage = finite_float(getattr(cfg,'engage_threshold_norm',0.02), 0.02, 0.0, 0.5)
                    release = finite_float(getattr(cfg,'release_threshold_norm',0.015), 0.015, 0.0, 0.5)
                    if not self._engaged:
                        if magp >= engage:
                            self._engaged = True
                    else:
                        if magp < release:
                            self._engaged = False

                    # Mouse scaling
                    raw_scale = finite_float(getattr(cfg,'pixel_scale',12.0), 12.0, 0.0, 100000.0) * finite_float(sens_eff, 0.0, 0.0, 100000.0)
                    if strict_authority and bool(getattr(cfg, 'authority_direct_cap_output', True)):
                        # v5.4: in authority mode the fixed cap is the actual full-stick speed,
                        # not a post-process clamp after calculating hundreds of pixels. This
                        # keeps small right-stick values small during cover/camera auto-rotation.
                        fixed_speed = finite_float(getattr(cfg, 'authority_fixed_cap_px', 48), 48.0, 1.0, 1000.0)
                        scale = min(raw_scale, fixed_speed) if bool(getattr(cfg, 'authority_use_fixed_cap_as_speed', True)) else raw_scale
                        if raw_mag <= finite_float(getattr(cfg, 'authority_center_zero_norm', 0.018), 0.018, 0.0, 0.20):
                            dx_f = 0.0
                            dy_f = 0.0
                        else:
                            dx_f = self._f_nx * scale
                            dy_f = -self._f_ny * scale
                            if bool(getattr(cfg, 'authority_vertical_guard_enabled', True)):
                                # v5.8: apply a constant pitch scalar before integer rounding.
                                # This prevents up/down stick from reaching the same px/tick as yaw,
                                # which logs showed as full-cap vertical yanks in ADS/cover.
                                dy_f *= finite_float(getattr(cfg, 'authority_vertical_scale', 0.62), 0.62, 0.05, 1.0)
                    else:
                        scale = raw_scale
                        dx_f = self._f_nx * scale
                        dy_f = -self._f_ny * scale
                    # Crash hardening: bad saved config values can produce NaN/Inf.
                    # Never feed NaN/Inf into int(); reset the accumulator instead.
                    if not (math.isfinite(dx_f) and math.isfinite(dy_f) and
                            math.isfinite(self._accum_x) and math.isfinite(self._accum_y)):
                        logging.warning("Non-finite mouse delta repaired: dx_f=%r dy_f=%r accum=(%r,%r)",
                                        dx_f, dy_f, self._accum_x, self._accum_y)
                        dx_f = dy_f = 0.0
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                    if strict_authority and bool(getattr(cfg, 'authority_no_accumulator', True)):
                        # v5.1: no history bank. Output is rounded from the current right-stick
                        # value only, so cover/ADS/previous dx cannot replay as acceleration.
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                        rounding = str(getattr(cfg, 'authority_rounding', 'nearest')).lower()
                        if rounding == 'trunc':
                            dx = finite_int(dx_f, 0, -1000000, 1000000)
                            dy = finite_int(dy_f, 0, -1000000, 1000000)
                        else:
                            dx = finite_int(round(dx_f), 0, -1000000, 1000000)
                            dy = finite_int(round(dy_f), 0, -1000000, 1000000)
                    else:
                        self._accum_x = finite_float(self._accum_x + dx_f, 0.0, -1000000.0, 1000000.0)
                        self._accum_y = finite_float(self._accum_y + dy_f, 0.0, -1000000.0, 1000000.0)
                        dx = finite_int(self._accum_x, 0, -1000000, 1000000)
                        dy = finite_int(self._accum_y, 0, -1000000, 1000000)
                    # v4.5 reliability fix:
                    # Do NOT consume the integer accumulator here. The final dx/dy can still be
                    # clamped, slew-limited, or jitter-held below. Consuming early caused tiny
                    # 1px Redux movements and cap-limited motion to be thrown away forever.
                    # We subtract only the final emitted/consumed delta after all gates run.
                    if released:
                        # Released means the physical stick is centered; final output must be zero.
                        # This prevents the UI dx/dy from "counting down" and prevents camera sway.
                        dx = 0
                        dy = 0

                    # Clamp to prevent spikes (per-tick and per-second).
                    # Adaptive cap prevents sensitivity changes from being flattened by the same old ceiling.
                    cap_tick_base = finite_int(getattr(cfg,'max_pixels_per_tick',40), 40, 2, 100000)
                    cap_ps_base   = finite_int(getattr(cfg,'max_pixels_per_second',3600), 3600, 200, 1000000)
                    cap_gain = 1.0
                    if bool(getattr(cfg, 'adaptive_caps_enabled', True)):
                        try:
                            max_gain = finite_float(getattr(cfg, 'adaptive_cap_max_multiplier', 6.0), 6.0, 1.0, 20.0)
                            cap_gain = max(1.0, min(max_gain, math.sqrt(max(1.0, float(sens_eff)))))
                        except Exception:
                            cap_gain = 1.0
                    if ads_guard:
                        # Sustained LT/ADS should not inherit a hip-fire cap gain of 6x+; that
                        # showed up as LT acceleration/yank even when the stationary guard was off.
                        cap_gain = min(cap_gain, finite_float(getattr(cfg, 'ads_cap_gain', 3.0), 3.0, 1.0, 20.0))
                    if ads_stationary_guard:
                        cap_gain = min(cap_gain, finite_float(getattr(cfg, 'ads_stationary_cap_gain', 2.0), 2.0, 1.0, 20.0))
                    if strict_authority and bool(getattr(cfg, 'authority_fixed_cap_enabled', True)):
                        # Stable cap: do not let scheduler dt/per-second cap variation alter feel.
                        # This is still a cap, but it is fixed and radial so the stick angle is preserved.
                        cap_gain = 1.0
                        cap_tick = finite_int(getattr(cfg, 'authority_fixed_cap_px', 48), 48, 1, 1000)
                        cap_ps = cap_ps_base
                        cap_dt = cap_tick
                    else:
                        cap_tick = finite_int(cap_tick_base * cap_gain, cap_tick_base, 2, 100000)
                        cap_ps   = finite_int(cap_ps_base * cap_gain, cap_ps_base, 200, 1000000)
                        cap_dt   = finite_int(min(cap_tick, cap_ps * dt), 2, 2, cap_tick)
                    pre_cap_dx, pre_cap_dy = dx, dy
                    cap_mode = "none"

                    # Cover+ decay clamp: during cover window, add a dynamic ceiling that decays over time
                    try:
                        if state_guards_allowed and self._cover_active and not (bool(getattr(cfg,'cover_ads_exempt',True)) and ads):
                            # time-based strength from now to end of window
                            rem = max(0.0, self._cover_until - now)
                            decay = finite_int(getattr(cfg,'cover_decay_ms',220), 220, 1, 5000) / 1000.0
                            strength = max(0.0, min(1.0, rem / max(1e-3, decay)))
                            # compute a snap cap that blends with base cap
                            gate_norm = finite_float(getattr(cfg,'cover_gate_norm',0.10), 0.10, 0.0, 1.0)
                            snap_ceiling = finite_int(finite_float(getattr(cfg,'cover_snap_max_px',6), 6.0, 1.0, 1000.0) * (0.5 + 0.5*strength), 6, 1, 1000)
                            # if stick is near center, clamp even harder
                            magp_now = magp
                            if magp_now <= gate_norm:
                                cap_dt = min(cap_dt, snap_ceiling)
                            else:
                                # slight clamp even above gate to smooth animation
                                cap_dt = min(cap_dt, snap_ceiling + 2)
                            # simple yank detector: if change jumps too much while near center, damp it
                            jump = abs(dx - self._dx_prev) + abs(dy - self._dy_prev)
                            if magp_now <= gate_norm and jump > (snap_ceiling + 2):
                                dx = int(self._dx_prev + (dx - self._dx_prev) * 0.5)
                                dy = int(self._dy_prev + (dy - self._dy_prev) * 0.5)
                    except Exception:
                        pass

                    # Tighten caps under cover guard. Disabled in right-stick authority mode.
                    if state_guards_allowed and self._cover_active:
                        cap_dt = max(1, cap_dt - finite_int(getattr(cfg,'cover_extra_clamp',2), 2, 0, 1000))
                    if state_guards_allowed and ads_guard:
                        # General LT limiter: catches ADS yanks even while the left stick is moving.
                        cap_dt = min(cap_dt, finite_int(getattr(cfg, 'ads_cap_px', 48), 48, 1, 1000))
                    if state_guards_allowed and ads_stationary_guard:
                        # LT held while standing still is the exact Redux yank case. Keep it on a
                        # separate hard ceiling regardless of the high base/adaptive cap settings.
                        cap_dt = min(cap_dt, finite_int(getattr(cfg, 'ads_stationary_cap_px', 18), 18, 1, 1000))
                    if ads_transition_damping:
                        # Short LT-edge limiter: prevents a one-frame ADS flicker without disabling aim.
                        cap_dt = min(cap_dt, finite_int(getattr(cfg, 'ads_transition_cap_px', 24), 24, 1, 1000))
                    if bool(getattr(cfg, 'preserve_vector_caps', True)) or strict_authority:
                        old_dx, old_dy = dx, dy
                        dx, dy = clamp_vector_radial_int(dx, dy, cap_dt)
                        cap_mode = "radial" if (dx != old_dx or dy != old_dy) else "none"
                    else:
                        old_dx, old_dy = dx, dy
                        if dx > cap_dt: dx = cap_dt
                        elif dx < -cap_dt: dx = -cap_dt
                        if dy > cap_dt: dy = cap_dt
                        elif dy < -cap_dt: dy = -cap_dt
                        cap_mode = "square" if (dx != old_dx or dy != old_dy) else "none"

                    # v5.8 vertical pitch authority cap/slew. Keep yaw responsive, but prevent
                    # up/down from hitting full yaw speed. This is especially important in ADS/cover
                    # where the game camera is already pitching/reframing on its own.
                    vertical_guard_active = strict_authority and bool(getattr(cfg, 'authority_vertical_guard_enabled', True))
                    vertical_cap_mode = "none"
                    if vertical_guard_active:
                        ycap = finite_int(getattr(cfg, 'authority_vertical_cap_px', 28), 28, 1, 1000)
                        camera_settle_for_y = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and (now <= self._camera_settle_until or now <= self._camera_settle_ramp_until)
                        if ads:
                            ycap = min(ycap, finite_int(getattr(cfg, 'authority_ads_vertical_cap_px', 22), 22, 1, 1000))
                        if self._cover_active or cover_phys_pressed:
                            ycap = min(ycap, finite_int(getattr(cfg, 'authority_cover_vertical_cap_px', 20), 20, 1, 1000))
                        if camera_settle_for_y:
                            ycap = min(ycap, finite_int(getattr(cfg, 'authority_settle_vertical_cap_px', 16), 16, 1, 1000))
                        old_dy_v = dy
                        if dy > ycap:
                            dy = ycap
                        elif dy < -ycap:
                            dy = -ycap
                        if dy != old_dy_v:
                            vertical_cap_mode = "cap"
                        if bool(getattr(cfg, 'authority_vertical_slew_enabled', True)):
                            yslew = finite_int(getattr(cfg, 'authority_vertical_slew_px', 10), 10, 1, 1000)
                            if ads or self._cover_active or cover_phys_pressed or camera_settle_for_y:
                                yslew = min(yslew, finite_int(getattr(cfg, 'authority_ads_cover_vertical_slew_px', 6), 6, 1, 1000))
                            old_dy_s = dy
                            if dy > self._dy_prev + yslew:
                                dy = self._dy_prev + yslew
                            elif dy < self._dy_prev - yslew:
                                dy = self._dy_prev - yslew
                            if dy != old_dy_s:
                                vertical_cap_mode = "slew" if vertical_cap_mode == "none" else vertical_cap_mode + "+slew"

                    cap_limited = (dx != pre_cap_dx or dy != pre_cap_dy)
                    camera_settle_active_for_log = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and now <= self._camera_settle_until
                    if cap_limited:
                        self._cap_hit_streak += 1
                    else:
                        self._cap_hit_streak = max(0, self._cap_hit_streak - 1)
                    if (self._cap_hit_streak >= 30 and bool(getattr(cfg, 'runtime_diagnostics', True))
                            and now >= self._next_status_emit):
                        # Cap hits are normal during high stick deflection. Do not spam the GUI
                        # with this as a failure; log it for tuning instead.
                        logging.info("Output cap limiting movement: cap_dt=%s pre=(%s,%s) final=(%s,%s) sens=%.3f cap_gain=%.3f cap_mode=%s y_mode=%s ads=%s ads_guard=%s cover=%s left_mag=%.3f ads_stationary=%s ads_transition=%s raw_mag=%.4f authority=%s state_guards=%s linear=%s fixed_cap=%s direct_cap=%s camera_settle=%s camera_hard=%s reason=%s",
                                     cap_dt, pre_cap_dx, pre_cap_dy, dx, dy, sens_eff, cap_gain, cap_mode, vertical_cap_mode if 'vertical_cap_mode' in locals() else 'none', ads, ads_guard, self._cover_active, lx_raw_mag, ads_stationary_guard, ads_transition_damping, raw_mag, strict_authority, state_guards_allowed, bool(getattr(cfg, 'authority_linear_stick_response', True)), bool(getattr(cfg, 'authority_fixed_cap_enabled', True)), bool(getattr(cfg, 'authority_direct_cap_output', True)), camera_settle_active_for_log, now <= self._camera_settle_hard_until, self._camera_settle_reason)
                        self._next_status_emit = now + 2.0

                    # --- Micro‑jolt anti‑yank guard (extra layer for tiny inputs/rapid right stick) ---
                    try:
                        if strict_authority:
                            raise RuntimeError('authority mode skips history-based micro slew')
                        tiny_r = finite_float(getattr(cfg,'micro_jolt_radius_norm',0.12), 0.12, 0.0, 1.0)
                        micro_cap = finite_int(getattr(cfg,'micro_slew_cap_pixels',3), 3, 1, 1000)
                        if ads_guard:
                            micro_cap = min(micro_cap, finite_int(getattr(cfg, 'ads_slew_px', 10), 10, 1, 1000))
                        if ads_stationary_guard:
                            micro_cap = min(micro_cap, finite_int(getattr(cfg, 'ads_stationary_slew_px', 4), 4, 1, 1000))
                        if ads_transition_damping:
                            micro_cap = min(micro_cap, finite_int(getattr(cfg, 'ads_transition_slew_px', 8), 8, 1, 1000))
                        if magp <= max(0.02, tiny_r):
                            # only allow small per‑tick change inside tiny radius
                            if dx > self._dx_prev + micro_cap: dx = self._dx_prev + micro_cap
                            elif dx < self._dx_prev - micro_cap: dx = self._dx_prev - micro_cap
                            if dy > self._dy_prev + micro_cap: dy = self._dy_prev + micro_cap
                            elif dy < self._dy_prev - micro_cap: dy = self._dy_prev - micro_cap
                            # extra clamp on sign flips inside tiny radius
                            if bool(getattr(cfg,'dir_flip_guard',True)):
                                if self._dx_prev != 0 and (dx == 0 or (dx > 0) != (self._dx_prev > 0)):
                                    dx = int(self._dx_prev * 0.5)
                                if self._dy_prev != 0 and (dy == 0 or (dy > 0) != (self._dy_prev > 0)):
                                    dy = int(self._dy_prev * 0.5)
                    except Exception:
                        pass

                    # Slew-rate limiter (general anti-yank)
                    try:
                        if strict_authority:
                            raise RuntimeError('authority mode skips history-based slew')
                        slew_cap = max(1, int(cap_dt // 3))
                        if self._cover_active:
                            slew_cap = max(1, slew_cap - finite_int(getattr(cfg,'cover_extra_slew',1), 1, 0, 1000))
                        if ads_guard:
                            slew_cap = min(slew_cap, finite_int(getattr(cfg, 'ads_slew_px', 10), 10, 1, 1000))
                        if ads_stationary_guard:
                            slew_cap = min(slew_cap, finite_int(getattr(cfg, 'ads_stationary_slew_px', 4), 4, 1, 1000))
                        if ads_transition_damping:
                            slew_cap = min(slew_cap, finite_int(getattr(cfg, 'ads_transition_slew_px', 8), 8, 1, 1000))
                        if dx > self._dx_prev + slew_cap: dx = self._dx_prev + slew_cap
                        elif dx < self._dx_prev - slew_cap: dx = self._dx_prev - slew_cap
                        if dy > self._dy_prev + slew_cap: dy = self._dy_prev + slew_cap
                        elif dy < self._dy_prev - slew_cap: dy = self._dy_prev - slew_cap
                    except Exception:
                        pass

                    # Final limiter check after cap, micro-jolt, and slew-rate limiting.
                    # If final output differs from the integer accumulator request, do not queue
                    # the remainder for later replay; that delayed replay is the let-go yank.
                    output_limited_final = (dx != pre_cap_dx or dy != pre_cap_dy)

                    jt = finite_int(getattr(cfg,'jitter_threshold',1), 1, 0, 1000)
                    if strict_authority:
                        # A high jitter threshold creates a dead band followed by a sudden 1+px pop.
                        # In strict analog authority, clamp it so micro input stays proportional.
                        jt = min(jt, finite_int(getattr(cfg, 'authority_jitter_threshold_max', 0), 0, 0, 1000))
                    elif ads and state_guards_allowed:
                        # ADS micro-aim should not inherit a high hip-fire jitter value; values like
                        # jitter=3 made LT feel like it disabled the worker by swallowing small deltas.
                        jt = min(jt, finite_int(getattr(cfg, 'ads_jitter_threshold_max', 0), 0, 0, 1000))
                    if ads_transition_damping and raw_mag <= finite_float(getattr(cfg, 'ads_transition_center_suppress_norm', 0.025), 0.025, 0.0, 0.25):
                        dx = dy = 0
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                    elif -jt <= dx <= jt and -jt <= dy <= jt:
                        # v4.7: jitter is a HOLD only while the stick is physically active.
                        # If the stick is released, clear the bank so held subpixels cannot
                        # accumulate into fake drift or a delayed "countdown" movement.
                        dx = dy = 0
                        if released:
                            self._accum_x = 0.0
                            self._accum_y = 0.0
                    elif ads_stationary_guard and (dx or dy):
                        # Keep LT micro aim alive when the stationary guard is active. This avoids the
                        # "LT disables it" feel while still allowing the cap/slew guards to tame yanks.
                        min_ads = finite_int(getattr(cfg, 'ads_stationary_min_output_px', 1), 1, 0, 1000)
                        if min_ads > 0:
                            if dx == 0 and abs(pre_cap_dx) > jt:
                                dx = min_ads if pre_cap_dx > 0 else -min_ads
                            if dy == 0 and abs(pre_cap_dy) > jt:
                                dy = min_ads if pre_cap_dy > 0 else -min_ads

                    # v5.4: camera-settle lockout after likely game-driven camera reframes.
                    # This is intentionally not a sensitivity modifier: it only suppresses small
                    # non-deliberate output during the brief period where the game is rotating the
                    # camera on its own. Clear right-stick intent overrides the lockout.
                    camera_settle_active = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and now <= self._camera_settle_until
                    camera_settle_hard_active = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and now <= self._camera_settle_hard_until
                    camera_settle_override = finite_float(getattr(cfg, 'camera_settle_right_stick_override_norm', 0.18), 0.18, 0.0, 1.0)
                    cover_window_active = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and now <= self._camera_settle_cover_until
                    cover_full_lock_enabled = bool(getattr(cfg, 'camera_settle_cover_full_lock', False))
                    cover_settle_active = cover_window_active and cover_full_lock_enabled
                    cover_settle_ramp_active = bool(getattr(cfg, 'camera_settle_guard_enabled', True)) and now <= self._camera_settle_cover_ramp_until
                    late_cover_micro_allowed = False
                    if cover_settle_active:
                        elapsed_ms = max(0.0, (now - self._camera_settle_started_at) * 1000.0)
                        late_after = finite_int(getattr(cfg, 'camera_settle_cover_allow_micro_after_ms', 160), 160, 0, 2000)
                        micro_norm = finite_float(getattr(cfg, 'camera_settle_cover_micro_override_norm', 0.10), 0.10, 0.0, 1.0)
                        late_cover_micro_allowed = elapsed_ms >= late_after and raw_mag <= micro_norm
                    # v5.4: hard-lock the first part of a cover/camera transition even if
                    # the right stick is held. Gears can rotate the camera on its own during
                    # cover attach/detach; letting mouse output through at the same instant
                    # stacks both rotations and feels like uncommanded acceleration.
                    cover_live_control = (cover_window_active and bool(getattr(cfg, 'camera_settle_cover_live_control', True)) and not cover_full_lock_enabled)
                    if strict_authority and cover_live_control and (dx or dy):
                        # v6.0: cover needs control, not total silence. While Gears is settling
                        # its third-person cover camera, bound the stick output to a small live
                        # vector instead of forcing dx/dy to zero. This prevents yanks without
                        # making the camera feel disconnected on cover entry.
                        old_dx, old_dy = dx, dy
                        live_cap = finite_int(getattr(cfg, 'camera_settle_cover_live_cap_px', 14), 14, 0, 1000)
                        if camera_settle_hard_active:
                            live_cap = min(live_cap, finite_int(getattr(cfg, 'camera_settle_cover_live_hard_cap_px', 8), 8, 0, 1000))
                        dx, dy = clamp_vector_radial_int(dx, dy, live_cap) if live_cap > 0 else (0, 0)
                        y_live = finite_int(getattr(cfg, 'camera_settle_cover_live_vertical_cap_px', 4), 4, 0, 1000)
                        if y_live <= 0:
                            dy = 0
                        elif dy > y_live:
                            dy = y_live
                        elif dy < -y_live:
                            dy = -y_live
                        if bool(getattr(cfg, 'camera_settle_cover_live_log', True)) and (old_dx != dx or old_dy != dy):
                            self._settle_suppress_count += 1
                            first_n = finite_int(getattr(cfg, 'camera_settle_log_first_n', 3), 3, 0, 100)
                            interval = finite_int(getattr(cfg, 'camera_settle_log_interval_ms', 750), 750, 0, 10000) / 1000.0
                            should_log = self._settle_suppress_count <= first_n
                            if not should_log and interval > 0.0 and (now - self._last_settle_log_time) >= interval:
                                should_log = True
                            if should_log:
                                logging.info("Cover-live capped output: raw_mag=%.4f pre=(%s,%s) final=(%s,%s) hard=%s reason=%s count=%s",
                                             raw_mag, old_dx, old_dy, dx, dy, camera_settle_hard_active, self._camera_settle_reason, self._settle_suppress_count)
                                self._last_settle_log_time = now
                        self._accum_x = 0.0
                        self._accum_y = 0.0
                    elif strict_authority and camera_settle_active and (cover_settle_active or (not cover_window_active and camera_settle_hard_active) or raw_mag <= camera_settle_override):
                        if cover_settle_active and late_cover_micro_allowed and (dx or dy):
                            # Legacy full-lock fallback: after the unsafe cover snap has had time
                            # to settle, allow only tiny micro-correction.
                            micro_cap = finite_int(getattr(cfg, 'camera_settle_cover_micro_cap_px', 3), 3, 0, 1000)
                            old_dx, old_dy = dx, dy
                            dx, dy = clamp_vector_radial_int(dx, dy, micro_cap) if micro_cap > 0 else (0, 0)
                            if bool(getattr(cfg, 'camera_settle_log_suppressed', True)) and (old_dx != dx or old_dy != dy):
                                self._settle_suppress_count += 1
                                first_n = finite_int(getattr(cfg, 'camera_settle_log_first_n', 3), 3, 0, 100)
                                if self._settle_suppress_count <= first_n:
                                    logging.info("Cover-settle micro-capped output: raw_mag=%.4f pre=(%s,%s) final=(%s,%s) reason=%s count=%s",
                                                 raw_mag, old_dx, old_dy, dx, dy, self._camera_settle_reason, self._settle_suppress_count)
                                    self._last_settle_log_time = now
                        else:
                            if dx or dy:
                                self._settle_suppress_count += 1
                                if bool(getattr(cfg, 'camera_settle_log_suppressed', True)):
                                    first_n = finite_int(getattr(cfg, 'camera_settle_log_first_n', 3), 3, 0, 100)
                                    interval = finite_int(getattr(cfg, 'camera_settle_log_interval_ms', 750), 750, 0, 10000) / 1000.0
                                    should_log = self._settle_suppress_count <= first_n
                                    if not should_log and interval > 0.0 and (now - self._last_settle_log_time) >= interval:
                                        should_log = True
                                    if should_log:
                                        logging.info("Camera-settle suppressed output: raw_mag=%.4f dx=%s dy=%s hard=%s cover_full=%s reason=%s count=%s",
                                                     raw_mag, dx, dy, camera_settle_hard_active, cover_settle_active, self._camera_settle_reason, self._settle_suppress_count)
                                        self._last_settle_log_time = now
                            dx = 0
                            dy = 0
                            self._accum_x = 0.0
                            self._accum_y = 0.0
                            self._dx_prev = 0
                            self._dy_prev = 0
                    elif strict_authority and now <= self._camera_settle_ramp_until and (dx or dy):
                        # v5.7: do not jump straight from zero-output camera quarantine to
                        # full-speed mouse output. Ease back in so game-driven camera
                        # reframe and worker output do not stack into a release yank.
                        ramp_ms = finite_int(getattr(cfg, 'third_person_post_settle_ramp_ms', 140), 140, 1, 2000)
                        ramp_start = self._camera_settle_ramp_until - ramp_ms / 1000.0
                        t_ramp = max(0.0, min(1.0, (now - ramp_start) / max(1e-6, ramp_ms / 1000.0)))
                        min_scale = finite_float(getattr(cfg, 'third_person_ramp_min_scale', 0.18), 0.18, 0.0, 1.0)
                        ramp_scale = min(1.0, max(min_scale, t_ramp))
                        if cover_settle_ramp_active:
                            # Cover ramp comes back more cautiously than generic action/movement ramp.
                            ramp_scale = min(ramp_scale, max(0.08, ramp_scale * 0.55))
                        old_dx, old_dy = dx, dy
                        dx = finite_int(round(dx * ramp_scale), 0, -1000000, 1000000)
                        dy = finite_int(round(dy * ramp_scale), 0, -1000000, 1000000)
                        if bool(getattr(cfg, 'third_person_ramp_log', False)):
                            logging.info("Camera-settle ramped output: scale=%.3f pre=(%s,%s) final=(%s,%s) reason=%s", ramp_scale, old_dx, old_dy, dx, dy, self._camera_settle_reason)
                    elif not camera_settle_active and now > self._camera_settle_ramp_until:
                        self._settle_suppress_count = 0
                        self._camera_settle_reason = ""
                        self._camera_settle_started_at = 0.0
                        self._camera_settle_cover_until = 0.0
                        self._camera_settle_cover_ramp_until = 0.0

                    # Optional generic face-button suppression. This is independent from Cover Guard.
                    # Reliability fix: the configured cover button is NEVER part of this mask, even
                    # when Cover Guard is disabled. Otherwise unchecking Cover Guard could make A
                    # become blocked again through the generic inhibit path.
                    inhibit_mask = XINPUT_FACE_MASK & ~cover_flag
                    held_inhibit_mask = int(gp.wButtons) & int(inhibit_mask)
                    inhibit = bool(getattr(cfg,'inhibit_mouse_when_buttons',False)) and bool(held_inhibit_mask)

                    # Idle settle hard-zero
                    if magp < finite_float(getattr(cfg,'idle_epsilon',0.02), 0.02, 0.0, 1.0) and dx == 0 and dy == 0:
                        self._idle_frames += 1
                        if self._idle_frames >= finite_int(getattr(cfg,'idle_frames_to_zero',8), 8, 1, 10000):
                            self._f_nx = 0.0; self._f_ny = 0.0; self._accum_x = 0.0; self._accum_y = 0.0
                            self._idle_frames = 0
                    else:
                        self._idle_frames = 0
                        self._dx_prev = int(self._dx_prev * 0.9)
                        self._dy_prev = int(self._dy_prev * 0.9)
                    if dx or dy:
                        # Reliability fix: once processing has produced a real integer mouse delta,
                        # do not let the engage gate discard it. The deadzone/jitter filters already
                        # protect against drift; this keeps tiny but valid sensitivity changes visible
                        # in games like Redux.
                        gate_allows_output = True
                        if gate_allows_output and not inhibit:
                            ok = send_mouse_move(dx, dy)
                            self._send_attempt_count += 1
                            self._gate_block_streak = 0
                            if ok:
                                self._last_sendinput_ok = True
                            elif now >= self._next_status_emit:
                                self._last_sendinput_ok = False
                                self._emit_status("SendInput failed — run this app at the same privilege level as the game, or the game may be blocking injected mouse input")
                                self._next_status_emit = now + 1.0
                        elif inhibit and now >= self._next_status_emit:
                            btns = button_names_from_mask(held_inhibit_mask)
                            self._emit_status(f"Input inhibited by face-button guard: {btns} — turn Face-button inhibit OFF for Redux")
                            self._next_status_emit = now + 0.75
                        # Consume movement after the final output decision.
                        # v5.1 authority mode has no accumulator/backlog by design.
                        if strict_authority and bool(getattr(cfg, 'authority_no_accumulator', True)):
                            self._accum_x = 0.0
                            self._accum_y = 0.0
                        elif bool(getattr(cfg, 'discard_clamped_backlog', True)) and output_limited_final:
                            self._accum_x = finite_float(self._accum_x - pre_cap_dx, 0.0, -1000000.0, 1000000.0)
                            self._accum_y = finite_float(self._accum_y - pre_cap_dy, 0.0, -1000000.0, 1000000.0)
                        else:
                            self._accum_x = finite_float(self._accum_x - dx, 0.0, -1000000.0, 1000000.0)
                            self._accum_y = finite_float(self._accum_y - dy, 0.0, -1000000.0, 1000000.0)

                        # Keep only a tiny accumulator residue. This preserves fractional precision,
                        # but prevents hundreds/thousands of pixels from being replayed later.
                        bank = 0.0 if (strict_authority and bool(getattr(cfg, 'authority_no_accumulator', True))) else finite_float(getattr(cfg, 'max_accum_bank_px', 2.0), 2.0, 0.0, 100.0)
                        if ads_stationary_guard:
                            bank = min(bank, 1.0)
                        if abs(self._accum_x) > bank:
                            self._accum_x = math.copysign(bank, self._accum_x) if bank > 0.0 else 0.0
                        if abs(self._accum_y) > bank:
                            self._accum_y = math.copysign(bank, self._accum_y) if bank > 0.0 else 0.0
                        self._dx_prev, self._dy_prev = dx, dy
                    else:
                        if released:
                            self._accum_x = 0.0
                            self._accum_y = 0.0
                            self._dx_prev = 0
                            self._dy_prev = 0
                        if not self._engaged and (abs(nx_raw) > 0.0 or abs(ny_raw) > 0.0):
                            self._gate_block_streak += 1
                            if (self._gate_block_streak >= 60 and bool(getattr(cfg, 'runtime_diagnostics', True))
                                    and now >= self._next_status_emit):
                                # Quiet/non-failure diagnostic. At this point the accumulator is
                                # preserving subpixel movement; no input is being thrown away.
                                logging.info("Subpixel stick input holding: processed=%.4f engage=%.4f jitter=%s accum=(%.3f,%.3f)",
                                             magp, engage, jt, self._accum_x, self._accum_y)
                                self._next_status_emit = now + 2.0
                        else:
                            self._gate_block_streak = max(0, self._gate_block_streak - 1)

                    if self._ads_transition_damp_frames_left > 0:
                        self._ads_transition_damp_frames_left -= 1

                    # store previous processed vector (for future extensions/diagnostics)
                    self._nxp_prev, self._nyp_prev = self._f_nx, self._f_ny

                    # Throttled UI emit
                    if now >= self._ui_next:
                        self._ui_next = now + self._ui_min_interval
                        if not self._emit_updated(nx_raw, ny_raw, nx, ny, sens_eff, ads, dx, dy): break
                        if not self._emit_triggers(lt, rt, thr, ads): break
                        emitted = True

                    if emitted:
                        self._last_emit = now
                    elif (now - self._last_emit) > 0.5:
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
        for frac in (0.0, 0.5, 1.0):
            y = rect.bottom() - int(frac * rect.height())
            pen = QtGui.QPen(QtGui.QColor(60,60,60)); pen.setStyle(QtCore.Qt.PenStyle.DashLine); p.setPen(pen)
            p.drawLine(rect.left(), y, rect.right(), y)
        dzf = max(0.0, min(1.0, getattr(self.cfg, 'deadzone_right', 0) / 32767.0))
        y_dz = rect.bottom() - int(dzf * rect.height())
        p.setPen(QtGui.QPen(QtGui.QColor(200,80,80), 1, QtCore.Qt.PenStyle.DotLine)); p.drawLine(rect.left(), y_dz, rect.right(), y_dz)
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
        p.setPen(QtGui.QPen(QtGui.QColor(230,230,230)))
        p.drawText(rect.left()+6, rect.top()-2, "Debug: |raw| vs |processed|")

# ---------------------------- UI Helpers ---------------------------
def slider_row(label:str, minv, maxv, step, init, decimals=2, tip:str=""):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(label); lab.setMinimumWidth(190)
    if tip: lab.setToolTip(tip)
    sld = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    sld.setRange(0, int((maxv-minv)/step)); sld.setValue(int((init-minv)/step)); 
    sld.setToolTip(tip or label)
    box = QtWidgets.QDoubleSpinBox(); box.setRange(float(minv), float(maxv)); box.setDecimals(decimals)
    box.setSingleStep(step); box.setValue(float(init)); box.setToolTip(tip or label)
    row.addWidget(lab); row.addWidget(sld, 1); row.addWidget(box)
    return row, sld, box, lab, box  # return label & spin for tooltips


def checkbox_row(label:str, checked:bool=False, tip:str|None=None):
    row = QtWidgets.QHBoxLayout()
    chk = QtWidgets.QCheckBox(label)
    chk.setChecked(bool(checked))
    if tip: chk.setToolTip(tip)
    row.addWidget(chk); row.addStretch(1)
    return row, chk

def combo_row(label:str, items:list[str], current:str, tip:str|None=None):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(label); lab.setMinimumWidth(240)
    combo = QtWidgets.QComboBox()
    for it in items: combo.addItem(it)
    idx = max(0, combo.findText(str(current)))
    combo.setCurrentIndex(idx)
    if tip: lab.setToolTip(tip); combo.setToolTip(tip)
    row.addWidget(lab); row.addWidget(combo, 1)
    return row, combo

def slider_row_int(label:str, minv:int, maxv:int, step:int, init:int, tip:str=""):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(label); lab.setMinimumWidth(190)
    if tip: lab.setToolTip(tip)
    sld = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    sld.setRange(0, int((maxv-minv)//step)); sld.setValue(int((init-minv)//step)); 
    sld.setToolTip(tip or label)
    box = QtWidgets.QSpinBox(); box.setRange(int(minv), int(maxv)); box.setSingleStep(step); box.setValue(int(init))
    box.setToolTip(tip or label)
    row.addWidget(lab); row.addWidget(sld, 1); row.addWidget(box)
    return row, sld, box, lab, box

def set_desc(widget:QtWidgets.QWidget, text:str):
    widget.setToolTip(text)


def _make_button(text: str, tip: str = "") -> QtWidgets.QPushButton:
    btn = QtWidgets.QPushButton(text)
    if tip:
        btn.setToolTip(tip)
    return btn


def _apply_compact_theme(widget: QtWidgets.QWidget) -> None:
    """Small visual cleanup without changing widget behavior or custom paint logic."""
    try:
        widget.setStyleSheet("""
        QWidget {
            font-size: 13px;
        }
        QGroupBox {
            border: 1px solid rgba(128, 128, 128, 90);
            border-radius: 10px;
            margin-top: 10px;
            padding: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QPushButton {
            min-height: 26px;
            padding: 5px 10px;
            border-radius: 8px;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            min-height: 24px;
        }
        """)
    except Exception:
        logging.exception("Failed to apply compact theme")

# ------------------------------- Main UI -------------------------------
class MainWindow(QtWidgets.QWidget):
    applyConfig = QtCore.pyqtSignal(object)
    hardRestart = QtCore.pyqtSignal()
    def __init__(self, cfg:Config):
        super().__init__(); self.runtime_cfg = cfg; self.staged_cfg  = replace(cfg)
        self._syncing_controls = False
        self._script_running = False
        self._script_steps: list[tuple[int, str, list[str], str]] = []
        self._script_index = 0
        self._script_stop_requested = False
        self.setWindowTitle("Jacinto Input Refiner (PyQt6) — v6.3 Pure Right-Stick Tail Brake")
        self.setMinimumWidth(980); QtWidgets.QApplication.setStyle("Fusion")

        # Header
        hdr = QtWidgets.QLabel("<b>External input shaper</b> — mouse move only. Changes live-apply to the worker; <b>Apply</b> also saves and soft-restarts.")
        hdr.setWordWrap(True)
        hdr.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        hdr.setMaximumHeight(42)

        # Profiles bar
        profBar = QtWidgets.QHBoxLayout()
        self.profileCombo = QtWidgets.QComboBox(); self._refresh_profiles_dropdown(select=self.staged_cfg.profile_name or "default")
        self.profileNameEdit = QtWidgets.QLineEdit(self.staged_cfg.profile_name or "default")
        self.btnSaveProfile = QtWidgets.QPushButton("Save As")
        self.btnLoadProfile = QtWidgets.QPushButton("Load")
        self.btnDeleteProfile = QtWidgets.QPushButton("Delete")
        for w in (self.profileCombo, self.profileNameEdit, self.btnSaveProfile, self.btnLoadProfile, self.btnDeleteProfile):
            w.setToolTip("Profiles let you save & switch complete configurations instantly.")
        profBar.addWidget(QtWidgets.QLabel("Profile:"))
        profBar.addWidget(self.profileCombo, 1)
        profBar.addWidget(QtWidgets.QLabel("Name:"))
        profBar.addWidget(self.profileNameEdit, 1)
        profBar.addWidget(self.btnSaveProfile)
        profBar.addWidget(self.btnLoadProfile)
        profBar.addWidget(self.btnDeleteProfile)

        # Quick presets: reduces slider-by-slider testing. Values are conservative and reversible.
        self.quickBox = QtWidgets.QGroupBox("Quick presets")
        self.quickBox.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.quickBox.setMaximumHeight(96)
        qLay = QtWidgets.QHBoxLayout(self.quickBox)
        qLay.setContentsMargins(12, 12, 12, 12)
        qLay.setSpacing(12)
        self.btnPresetBalanced = _make_button("Balanced", "Safe default: smooth but responsive.")
        self.btnPresetSmoothCover = _make_button("Smooth Cover", "More damping around Gears cover/roadie-run camera snaps.")
        self.btnPresetLowLatency = _make_button("Low Latency", "Less smoothing/ramp delay. More raw feel, slightly more twitch.")
        self.btnPresetLowCpu = _make_button("Low CPU", "Lower runtime polling and hides the debug graph.")
        self.expertMode = QtWidgets.QCheckBox("Show all tuning sliders")
        self.expertMode.setChecked(True)
        self.expertMode.setToolTip("ON shows the full v2/v3 control set. Turn this OFF only when you want simple preset mode.")
        self.showDiag = QtWidgets.QCheckBox("Diagnostics graph")
        self.showDiag.setChecked(bool(getattr(self.staged_cfg, 'debug_overlay', True)))
        self.showDiag.setToolTip("Shows/hides the history graph. Runtime shaping is unaffected.")
        qLay.addWidget(self.btnPresetBalanced)
        qLay.addWidget(self.btnPresetSmoothCover)
        qLay.addWidget(self.btnPresetLowLatency)
        qLay.addWidget(self.btnPresetLowCpu)
        qLay.addStretch(1)
        qLay.addWidget(self.showDiag)
        qLay.addWidget(self.expertMode)

        # Top grid: toggles
        grid = QtWidgets.QGridLayout()
        self.titleEdit  = QtWidgets.QLineEdit(self.staged_cfg.target_window_substring)
        self.enabledBox = QtWidgets.QCheckBox("Enabled"); self.enabledBox.setChecked(self.staged_cfg.enabled)
        self.focusOnly  = QtWidgets.QCheckBox("Only when target window focused"); self.focusOnly.setChecked(self.staged_cfg.only_when_focused)
        self.invertY    = QtWidgets.QCheckBox("Invert Y"); self.invertY.setChecked(self.staged_cfg.invert_y)
        self.showRaw    = QtWidgets.QCheckBox("Show RAW stick vector"); self.showRaw.setChecked(self.staged_cfg.show_raw_vector)
        self.useCorr    = QtWidgets.QCheckBox("Use in-game slider correlation"); self.useCorr.setChecked(self.staged_cfg.use_correlation)
        self.adsTrigger = QtWidgets.QComboBox(); self.adsTrigger.addItems(["LT","RT"]); self.adsTrigger.setCurrentText(self.staged_cfg.ads_trigger)
        tip_target = "The app will only move the mouse when the active window title contains this text."
        tip_enabled = "Master on/off switch for shaping."
        tip_focus = "When enabled, shaping only occurs while your target game window is focused."
        tip_invert = "Flips Y axis if your game expects opposite vertical direction."
        tip_showraw = "Draw a light vector for raw right-stick input inside the circle."
        tip_corr = "Correlates your game's in‑menu sensitivity value to your desired feel values."
        tip_ads = "Choose which trigger (LT/RT) counts as ADS for sensitivity switching."
        self.titleEdit.setToolTip(tip_target)
        self.enabledBox.setToolTip(tip_enabled)
        self.focusOnly.setToolTip(tip_focus)
        self.invertY.setToolTip(tip_invert)
        self.showRaw.setToolTip(tip_showraw)
        self.useCorr.setToolTip(tip_corr)
        self.adsTrigger.setToolTip(tip_ads)

        self.pollRow, self.pollSld, self.pollBox, _, _ = slider_row_int(
            "Poll rate (Hz)", 60, 360, 30, self.staged_cfg.poll_hz,
            "How often the controller is sampled and the UI updates. Higher = smoother but more CPU."
        )
        grid.addWidget(QtWidgets.QLabel("Target window contains:"), 0,0); grid.addWidget(self.titleEdit, 0,1,1,3)
        grid.addWidget(self.enabledBox, 1,0); grid.addWidget(self.focusOnly, 1,1); grid.addWidget(self.invertY, 1,2); grid.addWidget(self.showRaw,1,3)
        grid.addWidget(self.useCorr, 2,0); grid.addWidget(QtWidgets.QLabel("ADS trigger:"), 2,1); grid.addWidget(self.adsTrigger,2,2)
        grid.addLayout(self.pollRow, 3,0,1,4)

        # Explicit sensitivities
        self.explicitBox = QtWidgets.QGroupBox("Explicit sensitivities (used when correlation is OFF)")
        eLay = QtWidgets.QVBoxLayout(self.explicitBox)
        row, self.baseSld, self.baseBox, labA, boxA = slider_row("Base sensitivity", 0.05, 200.0, 0.05, self.staged_cfg.base_sens, 2,
            "Direct scalar for hip-fire movement when correlation is OFF. Higher = faster cursor per stick deflection.")
        eLay.addLayout(row)
        row, self.adsSld,  self.adsBox, labB, boxB = slider_row("ADS sensitivity",  0.05, 200.0, 0.05, self.staged_cfg.ads_sens,   2,
            "Direct scalar for ADS movement when correlation is OFF. Usually lower than base for precision.")
        eLay.addLayout(row)

        # Correlation block
        self.corrBox = QtWidgets.QGroupBox("In-game slider correlation (used when correlation is ON)")
        cLay = QtWidgets.QVBoxLayout(self.corrBox)
        row, self.maxSld, self.maxBox, _, _ = slider_row_int("Game slider max", 10, 120, 1, self.staged_cfg.game_slider_max,
            "The maximum value your game's sensitivity slider allows (from the menu).")
        cLay.addLayout(row)
        row, self.curSld, self.curBox, _, _ = slider_row("Your in-game value", 0.1, 120.0, 0.1, self.staged_cfg.game_slider_current, 2,
            "Your current in‑game sensitivity value. Used as the baseline for correlation math.")
        cLay.addLayout(row)
        row, self.desBSld, self.desBBox, _, _ = slider_row("Desired base feel", 0.1, 120.0, 0.1, self.staged_cfg.desired_base_slider, 2,
            "What base feel you want relative to the game's scale. > value = faster; < value = slower.")
        cLay.addLayout(row)
        row, self.desASld, self.desABox, _, _ = slider_row("Desired ADS feel",  0.1, 120.0, 0.1, self.staged_cfg.desired_ads_slider,  2,
            "What ADS feel you want relative to the game's scale. Typically lower than base for accuracy.")
        cLay.addLayout(row)

        # Shaping
        common = QtWidgets.QGroupBox("Shaping & Stability")
        sLay = QtWidgets.QVBoxLayout(common)
        # Cover Guard (prevents camera yank when entering cover)
        self.coverBox = QtWidgets.QGroupBox("Cover Guard (Gears cover snap tamer)")
        cgLay = QtWidgets.QVBoxLayout(self.coverBox)

        row, self.coverEnableChk = checkbox_row("Enable Cover Guard", bool(self.staged_cfg.cover_guard_enabled),
            "When ON, briefly softens sensitivity and tightens clamps right as you enter/exit cover to prevent camera yanks.")
        cgLay.addLayout(row)

        row, self.coverBtnCombo = combo_row("Cover button", ["A","B","X","Y","LB","RB","LS","RS","START","BACK"],
            self.staged_cfg.cover_button, "Which gamepad button triggers the guard (A is Gears cover).")
        cgLay.addLayout(row)

        row, self.coverMsSld, self.coverMsBox, _, _ = slider_row_int("Guard duration (ms)", 40, 400, 5, int(self.staged_cfg.cover_guard_ms),
            "How long to apply extra damping immediately after pressing cover.")
        cgLay.addLayout(row)

        row, self.coverRelSld, self.coverRelBox, _, _ = slider_row_int("Release settle (ms)", 0, 300, 5, int(self.staged_cfg.cover_release_ms),
            "Extra small window after the button is released to keep things stable as the cover animation finishes.")
        cgLay.addLayout(row)

        row, self.coverScaleSld, self.coverScaleBox, _, _ = slider_row("Sensitivity scale in cover", 0.50, 1.00, 0.01, float(self.staged_cfg.cover_scale), 2,
            "Temporary sensitivity multiplier during the guard window. 1.00 = no change; lower = softer.")
        cgLay.addLayout(row)

        row, self.coverClampSld, self.coverClampBox, _, _ = slider_row_int("Extra per‑tick clamp (px)", 0, 8, 1, int(self.staged_cfg.cover_extra_clamp),
            "Subtract this from the normal per‑tick cap while the guard is active (tighter = less spike room).")
        cgLay.addLayout(row)

        row, self.coverSlewSld, self.coverSlewBox, _, _ = slider_row_int("Extra slew tightening (px)", 0, 5, 1, int(self.staged_cfg.cover_extra_slew),
            "Subtract this from the normal slew cap while the guard is active (tighter = smoother).")
        cgLay.addLayout(row)

        row, self.curveSld, self.curveBox, _, _ = slider_row("Curve exponent", 1.00, 3.0,  0.05, self.staged_cfg.curve_exponent, 2,
            "Non‑linear response: >1 slows near center and speeds at edge for finer aim around zero.")
        sLay.addLayout(row)
        row, self.deadSld,  self.deadBox, _, _  = slider_row_int("Right-stick deadzone", 0, 32767, 50, self.staged_cfg.deadzone_right,
            "Ignore tiny stick movement until this threshold. Helps worn sticks; too high causes delay.")
        sLay.addLayout(row)
        row, self.pixSld,   self.pixBox, _, _   = slider_row("Pixel scale",    4.0, 40.0, 0.5,  self.staged_cfg.pixel_scale,     1,
            "Base pixels per tick at full stick deflection before sensitivity multipliers.")
        sLay.addLayout(row)
        row, self.jitSld,   self.jitBox, _, _   = slider_row_int("Jitter threshold (pixels)", 0, 6, 1, self.staged_cfg.jitter_threshold,
            "Rounds tiny dx/dy to 0 to avoid shaking. If set too high you will lose micro‑adjustments.")
        sLay.addLayout(row)
        row, self.adsThrSld, self.adsThrBox, _, _ = slider_row_int("ADS trigger threshold", 0, 255, 5, self.staged_cfg.ads_trigger_threshold,
            "Trigger pressure level that activates ADS sensitivity. Hysteresis reduces flicker.")
        sLay.addLayout(row)
        row, self.smoothSld, self.smoothBox, _, _ = slider_row("Axis smoothing (0..1)", 0.0, 0.95, 0.05, self.staged_cfg.smoothing_alpha, 2,
            "Low‑pass filter on stick axes. 0 = raw/no smoothing; higher = smoother but adds latency.")
        sLay.addLayout(row)
        row, self.rampSld,   self.rampBox, _, _   = slider_row("Sensitivity ramp (0..1)", 0.0, 1.0, 0.05, self.staged_cfg.sens_ramp, 2,
            "How quickly we converge to the new target sensitivity after ADS/hip changes. 0 = instant/no ramp.")
        sLay.addLayout(row)
        row, self.maxPixSld, self.maxPixBox, _, _ = slider_row_int("Max pixels per tick", 2, 100, 2, self.staged_cfg.max_pixels_per_tick,
            "Caps per‑tick dx/dy. Prevents sudden spikes from turning into huge mouse jumps.")
        sLay.addLayout(row)
        row, self.maxPpsSld, self.maxPpsBox, _, _ = slider_row_int("Max pixels per second", 200, 20000, 100, self.staged_cfg.max_pixels_per_second,
            "Global speed cap scaled by time; keeps motion sane across different frame rates.")
        sLay.addLayout(row)
        row, self.adaptCapsChk = checkbox_row("Adaptive caps follow sensitivity", bool(getattr(self.staged_cfg, 'adaptive_caps_enabled', True)),
            "When ON, the output cap grows with sensitivity so value changes do not get flattened during gameplay.")
        sLay.addLayout(row)
        row, self.adaptCapMaxSld, self.adaptCapMaxBox, _, _ = slider_row("Adaptive cap max multiplier", 1.0, 12.0, 0.5, float(getattr(self.staged_cfg, 'adaptive_cap_max_multiplier', 6.0)), 1,
            "Safety ceiling for adaptive caps. Higher lets extreme sensitivity settings show through more, but can feel jumpier.")
        sLay.addLayout(row)
        row, self.runtimeDiagChk = checkbox_row("Runtime diagnostics", bool(getattr(self.staged_cfg, 'runtime_diagnostics', True)),
            "Shows status/log messages when focus matching, caps, gates, or SendInput may be blocking output.")
        sLay.addLayout(row)
        row, self.faceInhibitChk = checkbox_row("Block mouse while face buttons held", bool(getattr(self.staged_cfg, 'inhibit_mouse_when_buttons', False)),
            "Optional safety gate. For Redux/Gears, keep this OFF so A/B/X/Y gameplay actions do not make the worker feel dead.")
        sLay.addLayout(row)
        row, self.hystSld,   self.hystBox, _, _   = slider_row_int("ADS hysteresis", 0, 50, 1, self.staged_cfg.ads_hysteresis,
            "Buffer around the ADS threshold to avoid rapid toggling when hovering near the boundary.")
        sLay.addLayout(row)
        row, self.engSld, self.engBox, _, _ = slider_row("Engage threshold (norm)", 0.0, 0.2, 0.005, self.staged_cfg.engage_threshold_norm, 3,
            "Diagnostic gate threshold near center. v4.4 still sends real dx/dy once produced, so this should not make Redux feel dead.")
        sLay.addLayout(row)
        row, self.relSld, self.relBox, _, _ = slider_row("Release threshold (norm)", 0.0, 0.2, 0.005, self.staged_cfg.release_threshold_norm, 3,
            "Release point for near-center diagnostics and filter settling.")
        sLay.addLayout(row)
        row, self.softkSld, self.softkBox, _, _ = slider_row("Soft zone k", 1.0, 3.0, 0.05, self.staged_cfg.softzone_k, 2,
            "Exponent that softens motion near zero (micro‑aim help). 1.0 disables soft‑zone.")
        sLay.addLayout(row)
        row, self.idleESld, self.idleEBox, _, _ = slider_row("Idle epsilon (norm)", 0.0, 0.1, 0.005, self.staged_cfg.idle_epsilon, 3,
            "If magnitude and dx/dy settle below this, we hard‑zero accumulators after a few frames.")
        sLay.addLayout(row)
        row, self.idleFSld, self.idleFBox, _, _ = slider_row_int("Idle frames to zero", 0, 60, 1, self.staged_cfg.idle_frames_to_zero,
            "How many idle frames before we clear filters to absolute zero.")
        sLay.addLayout(row)

        # New micro‑jolt guard controls (hidden advanced)
        advBox = QtWidgets.QGroupBox("Anti‑Yank Micro‑Jolt Guard")
        aLay = QtWidgets.QVBoxLayout(advBox)
        row, self.mjrSld, self.mjrBox, _, _ = slider_row("Micro‑radius (norm)", 0.02, 0.3, 0.005, self.staged_cfg.micro_jolt_radius_norm, 3,
            "Inside this stick radius we aggressively clamp per‑tick changes to kill tiny yanks.")
        aLay.addLayout(row)
        row, self.mcapSld, self.mcapBox, _, _ = slider_row_int("Micro slew cap (px/tick)", 1, 8, 1, self.staged_cfg.micro_slew_cap_pixels,
            "Max dx/dy change allowed per tick while inside the micro‑radius.")
        aLay.addLayout(row)
        self.flipGuard = QtWidgets.QCheckBox("Directional flip guard"); self.flipGuard.setChecked(self.staged_cfg.dir_flip_guard)
        self.flipGuard.setToolTip("If dx/dy tries to reverse sign inside the tiny radius, clamp it further to avoid yank.")
        aLay.addWidget(self.flipGuard)

        # Buttons/status
        btns = QtWidgets.QHBoxLayout()
        self.testBtn = QtWidgets.QPushButton("Test Mouse Move")
        self.applyBtn = QtWidgets.QPushButton("Apply (soft restart)")
        self.saveBtn  = QtWidgets.QPushButton("Save Config (default.json)")
        self.appliedLabel = QtWidgets.QLabel(""); self.appliedLabel.setStyleSheet("color: #7CFC00; font-weight: bold;")
        self.statusLabel = QtWidgets.QLabel("Controller: —")
        self.quitBtn  = QtWidgets.QPushButton("Quit")
        btns.addWidget(self.testBtn); btns.addWidget(self.applyBtn); btns.addWidget(self.saveBtn)
        btns.addStretch(1); btns.addWidget(self.statusLabel); btns.addWidget(self.appliedLabel); btns.addWidget(self.quitBtn)

        # Visuals
        self.stickViz = StickVisualizer(self.staged_cfg)
        self.stickViz.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.trigViz  = TriggerVisualizer(self.staged_cfg)
        self.trigViz.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        self.stickThrBar = RightStickThresholdBar(self.staged_cfg)
        self.stickThrBar.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        self.debugViz = DebugOverlay(self.staged_cfg)
        self.debugViz.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.debugViz.setVisible(getattr(self.staged_cfg, 'debug_overlay', True))

        # Layout
        self.commonBox = common
        self.advBox = advBox
        left = QtWidgets.QVBoxLayout()
        left.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        left.addWidget(hdr); left.addLayout(profBar); left.addWidget(self.quickBox)
        left.addLayout(grid); left.addWidget(self.explicitBox); left.addWidget(self.corrBox)
        left.addWidget(self.coverBox)
        left.addWidget(self.commonBox); left.addWidget(self.advBox); left.addLayout(btns)
        right = QtWidgets.QVBoxLayout(); right.addWidget(self.stickViz, 1); right.addWidget(self.trigViz, 0)
        right.addWidget(self.stickThrBar, 0); right.addWidget(self.debugViz, 0)
        top = QtWidgets.QHBoxLayout()
        top.addLayout(left, 1); top.addLayout(right, 0)
        content = QtWidgets.QWidget()
        content.setLayout(top)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(scroll, "Input Refiner")
        self.tabs.addTab(self._build_scripts_tab(), "Scripts / Macros")
        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(self.tabs)

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
        self.adaptCapsChk.stateChanged.connect(lambda _: self._stage('adaptive_caps_enabled', self.adaptCapsChk.isChecked()))
        self.adaptCapMaxSld.valueChanged.connect(lambda v: self.adaptCapMaxBox.setValue(1.0 + v*0.5))
        self.adaptCapMaxBox.valueChanged.connect(lambda v: self._stage('adaptive_cap_max_multiplier', float(v)))
        self.runtimeDiagChk.stateChanged.connect(lambda _: self._stage('runtime_diagnostics', self.runtimeDiagChk.isChecked()))
        self.faceInhibitChk.stateChanged.connect(lambda _: self._stage('inhibit_mouse_when_buttons', self.faceInhibitChk.isChecked()))
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

        
        # cover guard wiring
        self.coverEnableChk.stateChanged.connect(lambda _: self._stage('cover_guard_enabled', self.coverEnableChk.isChecked()))
        self.coverBtnCombo.currentTextChanged.connect(lambda t: self._stage('cover_button', t))
        self.coverMsSld.valueChanged.connect(lambda v: self.coverMsBox.setValue(int(v)))
        self.coverMsBox.valueChanged.connect(lambda v: self._stage('cover_guard_ms', int(v)))
        self.coverRelSld.valueChanged.connect(lambda v: self.coverRelBox.setValue(int(v)))
        self.coverRelBox.valueChanged.connect(lambda v: self._stage('cover_release_ms', int(v)))
        self.coverScaleSld.valueChanged.connect(lambda v: self.coverScaleBox.setValue(round(v, 2)))
        self.coverScaleBox.valueChanged.connect(lambda v: self._stage('cover_scale', float(v)))
        self.coverClampSld.valueChanged.connect(lambda v: self.coverClampBox.setValue(int(v)))
        self.coverClampBox.valueChanged.connect(lambda v: self._stage('cover_extra_clamp', int(v)))
        self.coverSlewSld.valueChanged.connect(lambda v: self.coverSlewBox.setValue(int(v)))
        self.coverSlewBox.valueChanged.connect(lambda v: self._stage('cover_extra_slew', int(v)))
# micro‑jolt wiring
        self.mjrSld.valueChanged.connect(lambda v: self.mjrBox.setValue(0.02 + v*0.005))
        self.mjrBox.valueChanged.connect(lambda v: self._stage('micro_jolt_radius_norm', float(v)))
        self.mcapSld.valueChanged.connect(lambda v: self.mcapBox.setValue(1 + v*1))
        self.mcapBox.valueChanged.connect(lambda v: self._stage('micro_slew_cap_pixels', int(v)))
        self.flipGuard.stateChanged.connect(lambda _: self._stage('dir_flip_guard', self.flipGuard.isChecked()))

        # profile wiring
        self.profileCombo.currentTextChanged.connect(self._on_profile_selected)
        self.btnSaveProfile.clicked.connect(self._on_save_profile)
        self.btnLoadProfile.clicked.connect(self._on_load_profile)
        self.btnDeleteProfile.clicked.connect(self._on_delete_profile)

        # preset/simple-mode wiring
        self.btnPresetBalanced.clicked.connect(lambda: self._apply_quick_preset("balanced"))
        self.btnPresetSmoothCover.clicked.connect(lambda: self._apply_quick_preset("smooth_cover"))
        self.btnPresetLowLatency.clicked.connect(lambda: self._apply_quick_preset("low_latency"))
        self.btnPresetLowCpu.clicked.connect(lambda: self._apply_quick_preset("low_cpu"))
        self.expertMode.stateChanged.connect(lambda _: self._update_mode_visibility())
        self.showDiag.stateChanged.connect(lambda _: self._stage('debug_overlay', self.showDiag.isChecked()))

        self.testBtn.clicked.connect(lambda: send_mouse_move(50, 0))
        self.applyBtn.clicked.connect(self._apply)
        self.saveBtn.clicked.connect(self._save_only)
        self.quitBtn.clicked.connect(QtWidgets.QApplication.instance().quit)

        self._update_mode_visibility()
        self._ensure_default_profile()
        _apply_compact_theme(self)


    # --------------------------- Script Lab ---------------------------
    def _build_scripts_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        info = QtWidgets.QLabel(
            "<b>Macro Builder</b> — G HUB-style action builder for this app's profiles and tuning settings. "
            "Use the builder to insert actions, or edit the plain-text macro directly underneath."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        top = QtWidgets.QHBoxLayout()
        self.scriptCombo = QtWidgets.QComboBox()
        self.scriptNameEdit = QtWidgets.QLineEdit("smooth_cover_test")
        self.btnScriptSave = QtWidgets.QPushButton("Save")
        self.btnScriptLoad = QtWidgets.QPushButton("Load")
        self.btnScriptDelete = QtWidgets.QPushButton("Delete")
        self.btnScriptExample = QtWidgets.QPushButton("Example")
        self.btnScriptValidate = QtWidgets.QPushButton("Validate")
        self.btnScriptRun = QtWidgets.QPushButton("Run")
        self.btnScriptStop = QtWidgets.QPushButton("Stop")
        self.btnScriptStop.setEnabled(False)
        top.addWidget(QtWidgets.QLabel("Script:"))
        top.addWidget(self.scriptCombo, 1)
        top.addWidget(QtWidgets.QLabel("Name:"))
        top.addWidget(self.scriptNameEdit, 1)
        for w in (self.btnScriptSave, self.btnScriptLoad, self.btnScriptDelete, self.btnScriptExample,
                  self.btnScriptValidate, self.btnScriptRun, self.btnScriptStop):
            top.addWidget(w)
        root.addLayout(top)

        builderBox = QtWidgets.QGroupBox("Macro Builder")
        builderLay = QtWidgets.QVBoxLayout(builderBox)
        builderIntro = QtWidgets.QLabel("Pick an action, fill the relevant field, then press Insert Action. The editor below stays editable, so this works like a simple macro timeline.")
        builderIntro.setWordWrap(True)
        builderLay.addWidget(builderIntro)

        form = QtWidgets.QGridLayout()
        self.builderActionCombo = QtWidgets.QComboBox()
        self.builderActionCombo.addItems([
            "Preset", "Set value", "Toggle setting", "Wait", "Status message",
            "Apply", "Save config", "Save profile", "Load profile"
        ])
        self.builderPresetCombo = QtWidgets.QComboBox()
        self.builderPresetCombo.addItems(["balanced", "smooth_cover", "low_latency", "low_cpu"])
        self.builderKeyCombo = QtWidgets.QComboBox()
        self.builderValueEdit = QtWidgets.QLineEdit()
        self.builderValueEdit.setPlaceholderText("value, for example 0.35 or true")
        self.builderToggleCombo = QtWidgets.QComboBox()
        self.builderToggleCombo.addItems(["on", "off"])
        self.builderWaitSpin = QtWidgets.QSpinBox()
        self.builderWaitSpin.setRange(0, 60000)
        self.builderWaitSpin.setSingleStep(50)
        self.builderWaitSpin.setValue(250)
        self.builderWaitSpin.setSuffix(" ms")
        self.builderMessageEdit = QtWidgets.QLineEdit()
        self.builderMessageEdit.setPlaceholderText("message shown in the output/status area")
        self.builderProfileEdit = QtWidgets.QLineEdit()
        self.builderProfileEdit.setPlaceholderText("profile name")
        self.builderInsertBtn = QtWidgets.QPushButton("Insert Action")

        self.builderPresetLabel = QtWidgets.QLabel("Preset")
        self.builderKeyLabel = QtWidgets.QLabel("Setting")
        self.builderValueLabel = QtWidgets.QLabel("Value")
        self.builderToggleLabel = QtWidgets.QLabel("State")
        self.builderWaitLabel = QtWidgets.QLabel("Delay")
        self.builderMessageLabel = QtWidgets.QLabel("Message")
        self.builderProfileLabel = QtWidgets.QLabel("Profile")

        form.addWidget(QtWidgets.QLabel("Action"), 0, 0)
        form.addWidget(self.builderActionCombo, 0, 1)
        form.addWidget(self.builderPresetLabel, 0, 2)
        form.addWidget(self.builderPresetCombo, 0, 3)
        form.addWidget(self.builderKeyLabel, 1, 0)
        form.addWidget(self.builderKeyCombo, 1, 1)
        form.addWidget(self.builderValueLabel, 1, 2)
        form.addWidget(self.builderValueEdit, 1, 3)
        form.addWidget(self.builderToggleLabel, 1, 2)
        form.addWidget(self.builderToggleCombo, 1, 3)
        form.addWidget(self.builderWaitLabel, 2, 0)
        form.addWidget(self.builderWaitSpin, 2, 1)
        form.addWidget(self.builderMessageLabel, 2, 0)
        form.addWidget(self.builderMessageEdit, 2, 1, 1, 3)
        form.addWidget(self.builderProfileLabel, 2, 0)
        form.addWidget(self.builderProfileEdit, 2, 1, 1, 3)
        form.addWidget(self.builderInsertBtn, 3, 3)
        builderLay.addLayout(form)

        templateRow = QtWidgets.QHBoxLayout()
        self.builderTemplateCombo = QtWidgets.QComboBox()
        self.builderTemplateCombo.addItems([
            "Smooth cover setup", "Balanced startup", "Low latency test",
            "Low CPU mode", "Diagnostics toggle", "Save current profile"
        ])
        self.builderInsertTemplateBtn = QtWidgets.QPushButton("Insert Template")
        self.builderClearBtn = QtWidgets.QPushButton("Clear Editor")
        templateRow.addWidget(QtWidgets.QLabel("Template:"))
        templateRow.addWidget(self.builderTemplateCombo, 1)
        templateRow.addWidget(self.builderInsertTemplateBtn)
        templateRow.addWidget(self.builderClearBtn)
        builderLay.addLayout(templateRow)
        root.addWidget(builderBox)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QWidget(); leftLay = QtWidgets.QVBoxLayout(left); leftLay.setContentsMargins(0, 0, 0, 0)
        self.scriptEditor = QtWidgets.QPlainTextEdit()
        self.scriptEditor.setPlainText(self._default_script_text())
        self.scriptEditor.setPlaceholderText("Write simple commands here. Example: preset smooth_cover, set smoothing_alpha 0.35, apply")
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        self.scriptEditor.setFont(mono)
        leftLay.addWidget(self.scriptEditor, 1)
        splitter.addWidget(left)

        right = QtWidgets.QWidget(); rightLay = QtWidgets.QVBoxLayout(right); rightLay.setContentsMargins(0, 0, 0, 0)
        helpText = QtWidgets.QLabel(self._script_help_html())
        helpText.setWordWrap(True)
        helpText.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.scriptOutput = QtWidgets.QPlainTextEdit()
        self.scriptOutput.setReadOnly(True)
        self.scriptOutput.setMaximumBlockCount(500)
        self.scriptOutput.setFont(mono)
        rightLay.addWidget(helpText)
        rightLay.addWidget(QtWidgets.QLabel("Output:"))
        rightLay.addWidget(self.scriptOutput, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self._refresh_scripts_dropdown()
        self.scriptCombo.currentTextChanged.connect(lambda name: self.scriptNameEdit.setText(name) if name else None)
        self.btnScriptSave.clicked.connect(self._on_save_script)
        self.btnScriptLoad.clicked.connect(self._on_load_script)
        self.btnScriptDelete.clicked.connect(self._on_delete_script)
        self.btnScriptExample.clicked.connect(lambda: self.scriptEditor.setPlainText(self._default_script_text()))
        self.btnScriptValidate.clicked.connect(self._on_validate_script)
        self.btnScriptRun.clicked.connect(self._on_run_script)
        self.btnScriptStop.clicked.connect(self._on_stop_script)
        self.builderActionCombo.currentTextChanged.connect(lambda _: self._refresh_macro_builder_fields())
        self.builderInsertBtn.clicked.connect(self._on_builder_insert_action)
        self.builderInsertTemplateBtn.clicked.connect(self._on_builder_insert_template)
        self.builderClearBtn.clicked.connect(lambda: self.scriptEditor.clear())
        self._refresh_macro_builder_fields()
        return page

    def _default_script_text(self) -> str:
        return """# Smooth-cover setup macro
# Builder-created macros are plain text, so you can edit them directly.

status Loading Smooth Cover tuning...
preset smooth_cover
set base_sens 34.25
set ads_sens 14.70
apply
wait 250
status Smooth Cover tuning applied.
"""

    def _script_help_html(self) -> str:
        return """
        <b>Plain-text macro commands</b><br>
        The builder inserts these for you, but you can also type them manually.<br><br>
        <code>preset balanced</code>, <code>preset smooth_cover</code>,
        <code>preset low_latency</code>, <code>preset low_cpu</code><br>
        <code>set key value</code> — change a config value, for example
        <code>set smoothing_alpha 0.35</code><br>
        <code>toggle key on/off</code> — bool-only shortcut.<br>
        <code>apply</code> — push staged settings to the worker.<br>
        <code>wait 250</code> — wait milliseconds before next command.<br>
        <code>status text...</code> — print to output/status label.<br>
        <code>save_config</code>, <code>save_profile name</code>, <code>load_profile name</code>.<br><br>
        <b>Macro engine scope:</b> this is for this app's tuning/profile actions.
        It intentionally does not play back keyboard or mouse-button input.
        """
    def _macro_config_keys(self, bool_only: bool = False) -> list[str]:
        try:
            items = asdict(self.staged_cfg).items()
        except Exception:
            items = asdict(Config()).items()
        keys = []
        for key, value in items:
            if bool_only and not isinstance(value, bool):
                continue
            keys.append(key)
        preferred = [
            "enabled", "only_when_focused", "use_correlation", "base_sens", "ads_sens",
            "game_slider_current", "desired_base_slider", "desired_ads_slider", "curve_exponent",
            "deadzone_right", "pixel_scale", "smoothing_alpha", "sens_ramp", "max_pixels_per_tick",
            "max_pixels_per_second", "cover_guard_enabled", "cover_button", "cover_scale",
            "micro_jolt_radius_norm", "micro_slew_cap_pixels", "debug_overlay"
        ]
        ordered = [k for k in preferred if k in keys]
        ordered.extend(k for k in sorted(keys) if k not in ordered)
        return ordered

    def _refresh_macro_builder_fields(self) -> None:
        if not hasattr(self, 'builderActionCombo'):
            return
        action = self.builderActionCombo.currentText()
        bool_only = action == "Toggle setting"
        current = self.builderKeyCombo.currentText()
        self.builderKeyCombo.blockSignals(True)
        try:
            self.builderKeyCombo.clear()
            self.builderKeyCombo.addItems(self._macro_config_keys(bool_only=bool_only))
            if current and self.builderKeyCombo.findText(current) >= 0:
                self.builderKeyCombo.setCurrentText(current)
        finally:
            self.builderKeyCombo.blockSignals(False)

        show_preset = action == "Preset"
        show_key = action in ("Set value", "Toggle setting")
        show_value = action == "Set value"
        show_toggle = action == "Toggle setting"
        show_wait = action == "Wait"
        show_message = action == "Status message"
        show_profile = action in ("Save profile", "Load profile")

        for w in (self.builderPresetLabel, self.builderPresetCombo):
            w.setVisible(show_preset)
        for w in (self.builderKeyLabel, self.builderKeyCombo):
            w.setVisible(show_key)
        for w in (self.builderValueLabel, self.builderValueEdit):
            w.setVisible(show_value)
        for w in (self.builderToggleLabel, self.builderToggleCombo):
            w.setVisible(show_toggle)
        for w in (self.builderWaitLabel, self.builderWaitSpin):
            w.setVisible(show_wait)
        for w in (self.builderMessageLabel, self.builderMessageEdit):
            w.setVisible(show_message)
        for w in (self.builderProfileLabel, self.builderProfileEdit):
            w.setVisible(show_profile)

    def _quote_macro_arg(self, text: str) -> str:
        text = str(text).strip()
        if not text:
            return '""'
        try:
            return shlex.quote(text)
        except Exception:
            return '"' + text.replace('"', '\\"') + '"'

    def _insert_macro_text(self, text: str) -> None:
        cursor = self.scriptEditor.textCursor()
        if not cursor.atBlockStart():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertText("\n")
        cursor.insertText(text.rstrip() + "\n")
        self.scriptEditor.setTextCursor(cursor)
        self.scriptEditor.setFocus()

    def _on_builder_insert_action(self) -> None:
        action = self.builderActionCombo.currentText()
        try:
            if action == "Preset":
                line = f"preset {self.builderPresetCombo.currentText()}"
            elif action == "Set value":
                key = self.builderKeyCombo.currentText().strip()
                value = self.builderValueEdit.text().strip()
                if not key:
                    raise ValueError("Choose a setting key.")
                if value == "":
                    raise ValueError("Enter a value for the selected setting.")
                line = f"set {key} {self._quote_macro_arg(value)}"
            elif action == "Toggle setting":
                key = self.builderKeyCombo.currentText().strip()
                if not key:
                    raise ValueError("Choose a boolean setting key.")
                line = f"toggle {key} {self.builderToggleCombo.currentText().lower()}"
            elif action == "Wait":
                line = f"wait {int(self.builderWaitSpin.value())}"
            elif action == "Status message":
                msg = self.builderMessageEdit.text().strip() or "Macro step completed."
                line = "status " + self._quote_macro_arg(msg)
            elif action == "Apply":
                line = "apply"
            elif action == "Save config":
                line = "save_config"
            elif action == "Save profile":
                name = self.builderProfileEdit.text().strip() or self.profileNameEdit.text().strip() or "macro_profile"
                line = "save_profile " + self._quote_macro_arg(name)
            elif action == "Load profile":
                name = self.builderProfileEdit.text().strip() or self.profileCombo.currentText().strip() or "default"
                line = "load_profile " + self._quote_macro_arg(name)
            else:
                raise ValueError(f"Unknown builder action '{action}'.")
            self._insert_macro_text(line)
            self._append_script_log(f"Inserted: {line}")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Insert failed", str(exc))

    def _macro_template_text(self, name: str) -> str:
        templates = {
            "Smooth cover setup": """# Smooth cover setup\nstatus Loading Smooth Cover tuning...\npreset smooth_cover\napply\nwait 250\nstatus Smooth Cover tuning applied.\n""",
            "Balanced startup": """# Balanced startup\nstatus Loading Balanced tuning...\npreset balanced\napply\nstatus Balanced tuning applied.\n""",
            "Low latency test": """# Low latency test\nstatus Loading Low Latency tuning...\npreset low_latency\napply\nwait 250\nstatus Low Latency tuning applied.\n""",
            "Low CPU mode": """# Low CPU mode\nstatus Loading Low CPU tuning...\npreset low_cpu\napply\nstatus Low CPU tuning applied.\n""",
            "Diagnostics toggle": """# Diagnostics toggle\ntoggle debug_overlay on\napply\nstatus Diagnostics graph enabled.\n""",
            "Save current profile": """# Save current staged settings as a profile\nstatus Saving current tuning profile...\nsave_profile my_tuning_profile\nsave_config\nstatus Profile and default config saved.\n""",
        }
        return templates.get(name, templates["Smooth cover setup"])

    def _on_builder_insert_template(self) -> None:
        name = self.builderTemplateCombo.currentText()
        self._insert_macro_text(self._macro_template_text(name))
        self._append_script_log(f"Inserted template: {name}")


    def _refresh_scripts_dropdown(self, select: str | None = None) -> None:
        if not hasattr(self, 'scriptCombo'):
            return
        names = list_scripts()
        self.scriptCombo.blockSignals(True)
        try:
            self.scriptCombo.clear()
            self.scriptCombo.addItems(names)
            if select and select in names:
                self.scriptCombo.setCurrentText(select)
        finally:
            self.scriptCombo.blockSignals(False)

    def _append_script_log(self, text: str) -> None:
        try:
            stamp = time.strftime("%H:%M:%S")
            self.scriptOutput.appendPlainText(f"[{stamp}] {text}")
        except Exception:
            logging.exception("script log append failed")

    def _on_save_script(self) -> None:
        name = self.scriptNameEdit.text().strip() or "script"
        try:
            save_script(name, self.scriptEditor.toPlainText())
            self._refresh_scripts_dropdown(select=name)
            self._append_script_log(f"Saved script '{name}'.")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Save failed", str(exc))

    def _on_load_script(self) -> None:
        name = self.scriptCombo.currentText().strip() or self.scriptNameEdit.text().strip()
        text = load_script(name)
        if text is None:
            QtWidgets.QMessageBox.warning(self, "Load failed", f"Script '{name}' not found.")
            return
        self.scriptEditor.setPlainText(text)
        self.scriptNameEdit.setText(name)
        self._append_script_log(f"Loaded script '{name}'.")

    def _on_delete_script(self) -> None:
        name = self.scriptCombo.currentText().strip() or self.scriptNameEdit.text().strip()
        if not name:
            return
        if delete_script(name):
            self._refresh_scripts_dropdown()
            self._append_script_log(f"Deleted script '{name}'.")
        else:
            QtWidgets.QMessageBox.warning(self, "Delete failed", f"Could not delete '{name}'.")

    def _strip_script_comment(self, line: str) -> str:
        # Keep quoted # characters intact.
        out = []
        quote = None
        escape = False
        for ch in line:
            if escape:
                out.append(ch); escape = False; continue
            if ch == "\\":
                out.append(ch); escape = True; continue
            if quote:
                if ch == quote:
                    quote = None
                out.append(ch); continue
            if ch in ("'", '"'):
                quote = ch; out.append(ch); continue
            if ch == "#":
                break
            out.append(ch)
        return "".join(out).strip()

    def _compile_script(self, source: str) -> tuple[list[tuple[int, str, list[str], str]], list[str]]:
        steps: list[tuple[int, str, list[str], str]] = []
        errors: list[str] = []
        allowed = {"preset", "set", "toggle", "apply", "wait", "status", "save_config", "save_profile", "load_profile"}
        blocked = {"python", "eval", "exec", "import", "sendinput", "mouse", "click", "key", "keydown", "keyup",
                   "autofire", "rapidfire", "recoil", "aimbot", "loop", "while", "for"}
        for lineno, raw in enumerate(source.splitlines(), 1):
            line = self._strip_script_comment(raw)
            if not line:
                continue
            try:
                parts = shlex.split(line)
            except Exception as exc:
                errors.append(f"Line {lineno}: parse error: {exc}")
                continue
            if not parts:
                continue
            cmd = parts[0].lower()
            if cmd in blocked:
                errors.append(f"Line {lineno}: '{cmd}' is intentionally blocked in this safe macro engine.")
                continue
            if cmd not in allowed:
                errors.append(f"Line {lineno}: unknown command '{cmd}'.")
                continue
            args = parts[1:]
            if cmd == "preset" and len(args) != 1:
                errors.append(f"Line {lineno}: preset requires one name.")
            elif cmd == "set" and len(args) < 2:
                errors.append(f"Line {lineno}: set requires key and value.")
            elif cmd == "toggle" and len(args) != 2:
                errors.append(f"Line {lineno}: toggle requires key and on/off.")
            elif cmd == "wait":
                if len(args) != 1:
                    errors.append(f"Line {lineno}: wait requires milliseconds.")
                else:
                    try:
                        ms = int(float(args[0]))
                        if ms < 0 or ms > 60000:
                            errors.append(f"Line {lineno}: wait must be 0..60000 ms.")
                    except Exception:
                        errors.append(f"Line {lineno}: wait value must be numeric.")
            elif cmd in ("save_profile", "load_profile") and len(args) != 1:
                errors.append(f"Line {lineno}: {cmd} requires one profile name.")
            steps.append((lineno, cmd, args, line))
        return steps, errors

    def _parse_bool_value(self, value: str) -> bool:
        v = str(value).strip().lower()
        if v in ("1", "true", "yes", "on", "enabled"):
            return True
        if v in ("0", "false", "no", "off", "disabled"):
            return False
        raise ValueError(f"Invalid bool value '{value}'. Use on/off or true/false.")

    def _coerce_config_value(self, key: str, value_text: str):
        if not hasattr(self.staged_cfg, key):
            raise KeyError(f"Unknown config key '{key}'.")
        current = getattr(self.staged_cfg, key)
        if isinstance(current, bool):
            return self._parse_bool_value(value_text)
        if isinstance(current, int) and not isinstance(current, bool):
            return finite_int(value_text, current)
        if isinstance(current, float):
            return finite_float(value_text, current)
        return str(value_text)

    def _set_config_from_script(self, key: str, value_text: str) -> None:
        value = self._coerce_config_value(key, value_text)
        if key == "ads_trigger" and value not in ("LT", "RT"):
            raise ValueError("ads_trigger must be LT or RT.")
        if key == "cover_button" and str(value).upper() not in _BUTTON_NAME_TO_FLAG:
            raise ValueError("cover_button must be A/B/X/Y/LB/RB/LS/RS/START/BACK.")
        if key == "cover_button":
            value = str(value).upper()
        setattr(self.staged_cfg, key, value)
        self._repopulate_controls_from_cfg()

    def _on_validate_script(self) -> None:
        steps, errors = self._compile_script(self.scriptEditor.toPlainText())
        if errors:
            self._append_script_log("Validation failed:")
            for e in errors:
                self._append_script_log("  " + e)
            return
        self._append_script_log(f"Validation OK: {len(steps)} command(s).")

    def _on_run_script(self) -> None:
        if self._script_running:
            self._append_script_log("A script is already running.")
            return
        steps, errors = self._compile_script(self.scriptEditor.toPlainText())
        if errors:
            self._append_script_log("Run blocked; validation failed:")
            for e in errors:
                self._append_script_log("  " + e)
            return
        self._script_steps = steps
        self._script_index = 0
        self._script_stop_requested = False
        self._script_running = True
        self.btnScriptRun.setEnabled(False)
        self.btnScriptStop.setEnabled(True)
        self._append_script_log(f"Running script: {len(steps)} command(s).")
        QtCore.QTimer.singleShot(0, self._run_next_script_step)

    def _on_stop_script(self) -> None:
        if self._script_running:
            self._script_stop_requested = True
            self._append_script_log("Stop requested.")

    def _finish_script(self, message: str) -> None:
        self._script_running = False
        self._script_stop_requested = False
        self.btnScriptRun.setEnabled(True)
        self.btnScriptStop.setEnabled(False)
        self._append_script_log(message)

    def _run_next_script_step(self) -> None:
        if not self._script_running:
            return
        if self._script_stop_requested:
            self._finish_script("Script stopped.")
            return
        if self._script_index >= len(self._script_steps):
            self._finish_script("Script finished.")
            return
        lineno, cmd, args, line = self._script_steps[self._script_index]
        self._script_index += 1
        try:
            if cmd == "wait":
                ms = max(0, min(60000, int(float(args[0]))))
                self._append_script_log(f"Line {lineno}: wait {ms} ms")
                QtCore.QTimer.singleShot(ms, self._run_next_script_step)
                return
            self._execute_script_step(lineno, cmd, args, line)
        except Exception as exc:
            logging.exception("script step failed")
            self._finish_script(f"Line {lineno}: ERROR: {exc}")
            return
        QtCore.QTimer.singleShot(0, self._run_next_script_step)

    def _execute_script_step(self, lineno: int, cmd: str, args: list[str], line: str) -> None:
        if cmd == "status":
            msg = " ".join(args) if args else ""
            self.statusLabel.setText(msg)
            self.appliedLabel.setText(msg)
            self._append_script_log(f"Line {lineno}: {msg}")
        elif cmd == "preset":
            preset = args[0].strip().lower().replace("-", "_")
            allowed_presets = {"balanced", "smooth_cover", "low_latency", "low_cpu"}
            if preset not in allowed_presets:
                raise ValueError(f"Unknown preset '{args[0]}'.")
            self._apply_quick_preset(preset)
            self._append_script_log(f"Line {lineno}: preset {preset}")
        elif cmd == "set":
            key = args[0]
            value_text = " ".join(args[1:])
            self._set_config_from_script(key, value_text)
            self._append_script_log(f"Line {lineno}: set {key} = {getattr(self.staged_cfg, key)!r}")
        elif cmd == "toggle":
            key = args[0]
            if not hasattr(self.staged_cfg, key) or not isinstance(getattr(self.staged_cfg, key), bool):
                raise ValueError(f"toggle requires a boolean config key; got '{key}'.")
            value = self._parse_bool_value(args[1])
            setattr(self.staged_cfg, key, value)
            self._repopulate_controls_from_cfg()
            self._append_script_log(f"Line {lineno}: toggle {key} = {value}")
        elif cmd == "apply":
            self.runtime_cfg = replace(self.staged_cfg)
            self.applyConfig.emit(asdict(self.runtime_cfg))
            self.hardRestart.emit()
            self.appliedLabel.setText("Script applied ✓")
            self._append_script_log(f"Line {lineno}: applied staged settings")
        elif cmd == "save_config":
            save_config(CONFIG_PATH, self.staged_cfg)
            self._append_script_log(f"Line {lineno}: saved {CONFIG_PATH}")
        elif cmd == "save_profile":
            name = args[0]
            cfg = replace(self.staged_cfg); cfg.profile_name = name
            save_profile(name, cfg)
            self._refresh_profiles_dropdown(select=name)
            self._append_script_log(f"Line {lineno}: saved profile '{name}'")
        elif cmd == "load_profile":
            name = args[0]
            cfg = load_profile(name)
            if cfg is None:
                raise ValueError(f"Profile '{name}' not found.")
            self.staged_cfg = cfg
            self.runtime_cfg = replace(cfg)
            self._repopulate_controls_from_cfg()
            self.applyConfig.emit(asdict(self.runtime_cfg))
            self.hardRestart.emit()
            self._append_script_log(f"Line {lineno}: loaded profile '{name}'")
        else:
            raise ValueError(f"Unknown command '{cmd}'.")

    def _ensure_default_profile(self):
        ensure_profile_dir()
        if not os.path.exists(profile_path("default")):
            cfg = replace(self.staged_cfg); cfg.profile_name = "default"
            save_profile("default", cfg)

    def _refresh_profiles_dropdown(self, select:str|None=None):
        ensure_profile_dir()
        names = list_profiles()
        self.profileCombo.blockSignals(True)
        self.profileCombo.clear()
        self.profileCombo.addItems(names)
        if select and select in names:
            self.profileCombo.setCurrentText(select)
        self.profileCombo.blockSignals(False)

    def _on_profile_selected(self, name:str):
        # just update the name edit; user must press Load to activate
        self.profileNameEdit.setText(name)

    def _on_save_profile(self):
        name = self.profileNameEdit.text().strip() or "default"
        self.staged_cfg.profile_name = name
        save_profile(name, self.staged_cfg)
        self._refresh_profiles_dropdown(select=name)
        QtWidgets.QMessageBox.information(self, "Saved", f"Saved profile '{name}'.")

    def _on_load_profile(self):
        name = self.profileCombo.currentText().strip() or "default"
        cfg = load_profile(name)
        if cfg is None:
            QtWidgets.QMessageBox.warning(self, "Load failed", f"Profile '{name}' not found.")
            return
        self.staged_cfg = cfg
        self.runtime_cfg = replace(cfg)
        self._repopulate_controls_from_cfg()
        self.applyConfig.emit(asdict(self.runtime_cfg))
        self.hardRestart.emit()
        self.appliedLabel.setText(f"Loaded '{name}' ✓")

    def _on_delete_profile(self):
        name = self.profileCombo.currentText().strip()
        if not name or name == "default":
            QtWidgets.QMessageBox.warning(self, "Not allowed", "Cannot delete 'default' profile.")
            return
        if delete_profile(name):
            self._refresh_profiles_dropdown(select="default")
            QtWidgets.QMessageBox.information(self, "Deleted", f"Deleted profile '{name}'.")
        else:
            QtWidgets.QMessageBox.warning(self, "Delete failed", f"Could not delete '{name}'.")

    def _repopulate_controls_from_cfg(self):
        # Update all widgets to match self.staged_cfg values without spamming live-apply signals.
        c = self.staged_cfg
        self._syncing_controls = True
        try:
            # Profile loading replaces the Config object, so repoint visualizers at the active config.
            self.stickViz.cfg = c
            self.trigViz.cfg = c
            self.stickThrBar.cfg = c
            self.debugViz.cfg = c

            def set_slider_spin(slider, spin, val, minv, step):
                slider.blockSignals(True); spin.blockSignals(True)
                try:
                    slider.setValue(int((val - minv) / step) if isinstance(spin, QtWidgets.QDoubleSpinBox) else int((val - minv) // step))
                    spin.setValue(val)
                finally:
                    slider.blockSignals(False); spin.blockSignals(False)

            widgets_to_block = [
                self.titleEdit, self.enabledBox, self.focusOnly, self.invertY, self.showRaw,
                self.useCorr, self.adsTrigger, self.maxBox, self.curBox, self.desBBox, self.desABox,
                self.curveBox, self.deadBox, self.pixBox, self.jitBox, self.adsThrBox, self.smoothBox,
                self.rampBox, self.maxPixBox, self.maxPpsBox, self.adaptCapsChk, self.adaptCapMaxBox,
                self.runtimeDiagChk, self.faceInhibitChk, self.hystBox, self.engBox, self.relBox,
                self.softkBox, self.idleEBox, self.idleFBox, self.coverEnableChk, self.coverBtnCombo,
                self.coverMsBox, self.coverRelBox, self.coverScaleBox, self.coverClampBox, self.coverSlewBox,
                self.mjrBox, self.mcapBox, self.flipGuard, self.showDiag,
            ]
            for w in widgets_to_block:
                w.blockSignals(True)
            try:
                self.titleEdit.setText(c.target_window_substring)
                self.enabledBox.setChecked(c.enabled)
                self.focusOnly.setChecked(c.only_when_focused)
                self.invertY.setChecked(c.invert_y)
                self.showRaw.setChecked(c.show_raw_vector)
                self.useCorr.setChecked(c.use_correlation)
                self.adsTrigger.setCurrentText(c.ads_trigger)
                set_slider_spin(self.pollSld, self.pollBox, c.poll_hz, 60, 30)

                set_slider_spin(self.baseSld, self.baseBox, c.base_sens, 0.05, 0.05)
                set_slider_spin(self.adsSld,  self.adsBox,  c.ads_sens,  0.05, 0.05)

                set_slider_spin(self.maxSld, self.maxBox, c.game_slider_max, 10, 1)
                set_slider_spin(self.curSld, self.curBox, c.game_slider_current, 0.1, 0.1)
                set_slider_spin(self.desBSld, self.desBBox, c.desired_base_slider, 0.1, 0.1)
                set_slider_spin(self.desASld, self.desABox, c.desired_ads_slider, 0.1, 0.1)

                set_slider_spin(self.curveSld, self.curveBox, c.curve_exponent, 1.0, 0.05)
                set_slider_spin(self.deadSld, self.deadBox, c.deadzone_right, 0, 50)
                set_slider_spin(self.pixSld, self.pixBox, c.pixel_scale, 4.0, 0.5)
                set_slider_spin(self.jitSld, self.jitBox, c.jitter_threshold, 0, 1)
                set_slider_spin(self.adsThrSld, self.adsThrBox, c.ads_trigger_threshold, 0, 5)
                set_slider_spin(self.smoothSld, self.smoothBox, c.smoothing_alpha, 0.0, 0.05)
                set_slider_spin(self.rampSld, self.rampBox, c.sens_ramp, 0.0, 0.05)
                set_slider_spin(self.maxPixSld, self.maxPixBox, c.max_pixels_per_tick, 2, 2)
                set_slider_spin(self.maxPpsSld, self.maxPpsBox, c.max_pixels_per_second, 200, 100)
                self.adaptCapsChk.setChecked(bool(getattr(c, 'adaptive_caps_enabled', True)))
                set_slider_spin(self.adaptCapMaxSld, self.adaptCapMaxBox, float(getattr(c, 'adaptive_cap_max_multiplier', 6.0)), 1.0, 0.5)
                self.runtimeDiagChk.setChecked(bool(getattr(c, 'runtime_diagnostics', True)))
                self.faceInhibitChk.setChecked(bool(getattr(c, 'inhibit_mouse_when_buttons', False)))
                set_slider_spin(self.hystSld, self.hystBox, c.ads_hysteresis, 0, 1)
                set_slider_spin(self.engSld, self.engBox, c.engage_threshold_norm, 0.0, 0.005)
                set_slider_spin(self.relSld, self.relBox, c.release_threshold_norm, 0.0, 0.005)
                set_slider_spin(self.softkSld, self.softkBox, c.softzone_k, 1.0, 0.05)
                set_slider_spin(self.idleESld, self.idleEBox, c.idle_epsilon, 0.0, 0.005)
                set_slider_spin(self.idleFSld, self.idleFBox, c.idle_frames_to_zero, 0, 1)

                self.coverEnableChk.setChecked(c.cover_guard_enabled)
                self.coverBtnCombo.setCurrentText(c.cover_button)
                set_slider_spin(self.coverMsSld, self.coverMsBox, c.cover_guard_ms, 40, 5)
                set_slider_spin(self.coverRelSld, self.coverRelBox, c.cover_release_ms, 0, 5)
                set_slider_spin(self.coverScaleSld, self.coverScaleBox, c.cover_scale, 0.50, 0.01)
                set_slider_spin(self.coverClampSld, self.coverClampBox, c.cover_extra_clamp, 0, 1)
                set_slider_spin(self.coverSlewSld, self.coverSlewBox, c.cover_extra_slew, 0, 1)

                set_slider_spin(self.mjrSld, self.mjrBox, c.micro_jolt_radius_norm, 0.02, 0.005)
                set_slider_spin(self.mcapSld, self.mcapBox, c.micro_slew_cap_pixels, 1, 1)
                self.flipGuard.setChecked(c.dir_flip_guard)
                self.showDiag.setChecked(bool(getattr(c, 'debug_overlay', True)))
            finally:
                for w in widgets_to_block:
                    w.blockSignals(False)
        finally:
            self._syncing_controls = False

        self._update_mode_visibility()

    def _apply_quick_preset(self, preset: str):
        """Apply a small known-good bundle so users do not have to test every slider one by one."""
        presets = {
            "balanced": {
                "poll_hz": 240,
                "curve_exponent": 1.30,
                "pixel_scale": 12.0,
                "jitter_threshold": 1,
                "smoothing_alpha": 0.25,
                "sens_ramp": 0.20,
                "max_pixels_per_tick": 40,
                "max_pixels_per_second": 3600,
                "ads_hysteresis": 8,
                "engage_threshold_norm": 0.005,
                "release_threshold_norm": 0.003,
                "softzone_k": 1.80,
                "idle_epsilon": 0.020,
                "idle_frames_to_zero": 8,
                "micro_jolt_radius_norm": 0.12,
                "micro_slew_cap_pixels": 3,
                "dir_flip_guard": True,
                "cover_guard_enabled": True,
                "cover_scale": 0.85,
                "cover_extra_clamp": 2,
                "cover_extra_slew": 1,
                "cover_snap_max_px": 6,
                "cover_gate_norm": 0.10,
                "cover_decay_ms": 220,
                "cover_ads_exempt": True,
                "debug_overlay": True,
                "adaptive_caps_enabled": True,
                "adaptive_cap_max_multiplier": 6.0,
                "runtime_diagnostics": True,
                "inhibit_mouse_when_buttons": False,
            },
            "smooth_cover": {
                "poll_hz": 240,
                "curve_exponent": 1.35,
                "pixel_scale": 11.5,
                "jitter_threshold": 1,
                "smoothing_alpha": 0.35,
                "sens_ramp": 0.15,
                "max_pixels_per_tick": 34,
                "max_pixels_per_second": 3200,
                "ads_hysteresis": 10,
                "engage_threshold_norm": 0.006,
                "release_threshold_norm": 0.004,
                "softzone_k": 1.95,
                "idle_epsilon": 0.022,
                "idle_frames_to_zero": 8,
                "micro_jolt_radius_norm": 0.14,
                "micro_slew_cap_pixels": 2,
                "dir_flip_guard": True,
                "cover_guard_enabled": True,
                "cover_scale": 0.75,
                "cover_extra_clamp": 4,
                "cover_extra_slew": 2,
                "cover_snap_max_px": 5,
                "cover_gate_norm": 0.12,
                "cover_decay_ms": 260,
                "cover_ads_exempt": True,
                "debug_overlay": True,
                "adaptive_caps_enabled": True,
                "adaptive_cap_max_multiplier": 6.0,
                "runtime_diagnostics": True,
                "inhibit_mouse_when_buttons": False,
            },
            "low_latency": {
                "poll_hz": 360,
                "curve_exponent": 1.20,
                "pixel_scale": 12.0,
                "jitter_threshold": 0,
                "smoothing_alpha": 0.10,
                "sens_ramp": 0.40,
                "max_pixels_per_tick": 50,
                "max_pixels_per_second": 5000,
                "ads_hysteresis": 6,
                "engage_threshold_norm": 0.004,
                "release_threshold_norm": 0.002,
                "softzone_k": 1.45,
                "idle_epsilon": 0.015,
                "idle_frames_to_zero": 6,
                "micro_jolt_radius_norm": 0.09,
                "micro_slew_cap_pixels": 4,
                "dir_flip_guard": True,
                "cover_guard_enabled": True,
                "cover_scale": 0.90,
                "cover_extra_clamp": 1,
                "cover_extra_slew": 0,
                "cover_snap_max_px": 8,
                "cover_gate_norm": 0.08,
                "cover_decay_ms": 180,
                "cover_ads_exempt": True,
                "debug_overlay": False,
                "adaptive_caps_enabled": True,
                "adaptive_cap_max_multiplier": 6.0,
                "runtime_diagnostics": True,
                "inhibit_mouse_when_buttons": False,
            },
            "low_cpu": {
                "poll_hz": 120,
                "curve_exponent": 1.30,
                "pixel_scale": 12.0,
                "jitter_threshold": 1,
                "smoothing_alpha": 0.25,
                "sens_ramp": 0.20,
                "max_pixels_per_tick": 40,
                "max_pixels_per_second": 3200,
                "ads_hysteresis": 8,
                "engage_threshold_norm": 0.005,
                "release_threshold_norm": 0.003,
                "softzone_k": 1.80,
                "idle_epsilon": 0.020,
                "idle_frames_to_zero": 8,
                "micro_jolt_radius_norm": 0.12,
                "micro_slew_cap_pixels": 3,
                "dir_flip_guard": True,
                "cover_guard_enabled": True,
                "cover_scale": 0.85,
                "cover_extra_clamp": 2,
                "cover_extra_slew": 1,
                "cover_snap_max_px": 6,
                "cover_gate_norm": 0.10,
                "cover_decay_ms": 220,
                "cover_ads_exempt": True,
                "debug_overlay": False,
                "adaptive_caps_enabled": True,
                "adaptive_cap_max_multiplier": 6.0,
                "runtime_diagnostics": True,
                "inhibit_mouse_when_buttons": False,
            }
        }
        changes = presets.get(preset)
        if not changes:
            return
        for key, value in changes.items():
            if hasattr(self.staged_cfg, key):
                setattr(self.staged_cfg, key, value)
        self.runtime_cfg = replace(self.staged_cfg)
        self._repopulate_controls_from_cfg()
        self.applyConfig.emit(asdict(self.runtime_cfg))
        self.hardRestart.emit()
        pretty = preset.replace("_", " ").title()
        self.appliedLabel.setText(f"Preset: {pretty} ✓")

    def _update_mode_visibility(self):
        on = self.staged_cfg.use_correlation
        self.corrBox.setVisible(on)
        self.explicitBox.setVisible(not on)
        expert = bool(getattr(self, 'expertMode', None) and self.expertMode.isChecked())
        # Full-controls mode exposes the exact same advanced widgets as v2/v3.
        # Turning it off only hides them visually; no settings are deleted.
        self.coverBox.setVisible(expert)
        self.commonBox.setVisible(expert)
        self.advBox.setVisible(expert)
        self.debugViz.setVisible(bool(getattr(self.staged_cfg, 'debug_overlay', True)))

    def _stage(self, key:str, value):
        setattr(self.staged_cfg, key, value)
        # Keep runtime_cfg synchronized with the live-applied staged config.
        # Earlier builds could leave manager-side runtime state stale until Apply was pressed.
        self.runtime_cfg = replace(self.staged_cfg)
        if getattr(self, '_syncing_controls', False):
            return
        self.appliedLabel.setText("")
        if key in ("deadzone_right","curve_exponent","show_raw_vector"):
            self.stickViz.update(); self.stickThrBar.update()
        if key == "debug_overlay":
            self.debugViz.setVisible(bool(value))
        # Live-apply the whole safe config, not just a hand-picked subset.
        # This prevents the GUI from showing a changed value while the worker keeps the old one.
        try:
            self.applyConfig.emit(asdict(self.staged_cfg))
        except Exception:
            logging.exception("live apply failed")

    def _apply(self):
        self.runtime_cfg = replace(self.staged_cfg)
        save_config(CONFIG_PATH, self.runtime_cfg)
        self.applyConfig.emit(asdict(self.runtime_cfg))
        self.hardRestart.emit()
        self.appliedLabel.setText("Applied ✓ — no profile load")
    def _save_only(self):
            save_config(CONFIG_PATH, self.staged_cfg)
            QtWidgets.QMessageBox.information(self, "Saved", f"Saved staged config to {CONFIG_PATH}\n(Changes are already live-applied; Apply also soft-restarts)")

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
        if win is not None:
            try:
                win.hardRestart.connect(self.request_restart)
            except Exception:
                logging.exception("connect request_restart failed")
    def request_restart(self):
        if self._worker is not None:
            try: self._worker.request_restart()
            except Exception: logging.exception("request_restart forwarding failed")
    def apply_to_worker(self, cfg_dict: object):
        if self._worker is not None:
            try: self._worker.request_apply_config(cfg_dict)
            except Exception: logging.exception("apply_to_worker forwarding failed")
        win = self._win_ref.get()
        if win is not None:
            try:
                # Keep manager-side copy sane too.
                self._cfg = Config(**sanitize_config_payload(win.runtime_cfg))
            except Exception:
                self._cfg = win.runtime_cfg
    def stop(self):
        if self._worker is None or self._thread is None: return
        try:
            self._worker.stop(); self._thread.quit(); self._thread.wait(2000)
            if self._thread.isRunning():
                logging.warning("Worker thread did not stop within timeout")
            self._worker.deleteLater(); self._thread.deleteLater()
        except Exception: logging.exception("WorkerManager.stop failed")
        finally: self._worker = None; self._thread = None

# ------------------------------ Boot ------------------------------
def main():
    if sys.platform != "win32":
        print("Windows only."); sys.exit(1)
    ensure_profile_dir()
    ensure_script_dir()
    # Bootstrap: ensure default profile exists and merges into runtime cfg
    cfg_disk = load_config(CONFIG_PATH)
    if not os.path.exists(profile_path(cfg_disk.profile_name)):
        save_profile(cfg_disk.profile_name, cfg_disk)
    app = QtWidgets.QApplication(sys.argv); app.setQuitOnLastWindowClosed(True)
    bus = InputSample()
    win = MainWindow(cfg_disk); win.resize(1360, 640); win.show()
    manager = WorkerManager(cfg_disk, bus, win); manager.start()
    win.applyConfig.connect(manager.apply_to_worker)
    bus.updated.connect(win.stickViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.status.connect(win.statusLabel.setText, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.triggers.connect(win.trigViz.on_triggers, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.updated.connect(win.stickThrBar.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    bus.updated.connect(win.debugViz.on_sample, QtCore.Qt.ConnectionType.QueuedConnection)
    app.aboutToQuit.connect(manager.stop)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
