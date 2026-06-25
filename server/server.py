# server/server.py
import json, asyncio, sys, os
from pathlib import Path
import websockets
from gestures import CameraGestureEngine

from urllib.parse import urlparse, quote

from executor import create_executor, detect_platform, is_wsl
from platform_keys import remap_intent_keys, app_switch_modifier, primary_modifier
from primitives import focused_typing, mailto_url
from nlu import (
    KEYMAP, SLOTS, slot_app, slot_site,
    local_route, ollama_route, validate_and_normalize_plan,
    OllamaUnavailable, probe_ollama, OLLAMA_URL,
)
import time
import datetime

# Single platform executor for all OS-specific operations (PRD §8.1).
EXEC = create_executor()

def now(): return datetime.datetime.now().strftime("%H:%M:%S")

REPEAT_BLOCKLIST = {"type_text", "mailto_compose"}  # intents we won't auto-repeat
LAST_EXECUTED = None  # ensure repeat works even before any action runs

# ===== Browser preference (DEMOTED — D1) =====
# Browser hotkeys now act on the frontmost browser (else open the default
# browser) — a uniform, OS-neutral rule (PRD §8.1, L-5). The old "preferred
# browser" / AppleScript active-tab routing is superseded. set_browser is kept
# as a near-no-op so the existing intent doesn't error.
LAST_REQUESTED_BROWSER = None

def set_preferred_browser(name: str):
    global LAST_REQUESTED_BROWSER
    if name:
        LAST_REQUESTED_BROWSER = str(name).strip()

# ===== Gesture → Action tuning =====
import pyautogui
pyautogui.FAILSAFE = False

# --- cross-browser navigation and zoom helpers (D1 frontmost-driven rule) ---
def _browser_hotkey(mac_keys, other_keys):
    """D1: send the hotkey to the frontmost browser; if no browser is focused,
    open the default browser instead (PRD §8.1)."""
    keys = mac_keys if detect_platform() == "darwin" else other_keys
    try:
        if EXEC.frontmost_is_browser():
            pyautogui.hotkey(*keys)
        else:
            EXEC.open_default_browser()
    except Exception as e:
        print("browser hotkey error:", e)

def browser_history_back():
    # Cmd+[ on macOS; Alt+Left elsewhere (Ctrl+[ is a no-op in Chrome — §8.2).
    _browser_hotkey(["command", "["], ["alt", "left"])

def browser_history_forward():
    _browser_hotkey(["command", "]"], ["alt", "right"])

def browser_next_tab():
    _browser_hotkey(["ctrl", "tab"], ["ctrl", "tab"])

def browser_prev_tab():
    _browser_hotkey(["ctrl", "shift", "tab"], ["ctrl", "shift", "tab"])

def browser_zoom_in():
    _browser_hotkey(["command", "="], ["ctrl", "="])

def browser_zoom_out():
    _browser_hotkey(["command", "-"], ["ctrl", "-"])

def browser_zoom_reset():
    _browser_hotkey(["command", "0"], ["ctrl", "0"])

def scroll_up(amount=240):
    try:
        pyautogui.scroll(abs(int(amount)))
    except Exception as e:
        print("scroll_up error:", e)

def scroll_down(amount=240):
    try:
        pyautogui.scroll(-abs(int(amount)))
    except Exception as e:
        print("scroll_down error:", e)

MOUSE_MODE = "cursor"           # cursor (not scroll)
# Extra smoothing/tuning (feel free to tweak live)
CURSOR_PIXELS_PER_SEC = 1800  # for vx/vy streaming path
CURSOR_DEAD_SPEED = 0.03      # slightly larger deadband to remove jitter

# --- Tilt-angle control (degrees and px/s), from version B ---
DEAD_ZONE_DEG = 10.0
V_MIN = 120.0          # px/s at threshold
V_MAX = 520.0          # px/s at saturation
SAT_ANGLE_DEG = 25.0   # degrees beyond the dead zone where speed saturates
ALPHA_ANGLE = 0.2      # low-pass on angles
MAX_STEP_PX = 16.0     # clamp per-tick pixel move
UPDATE_HZ = 30.0       # target update frequency (informational)

# --- Frontmost app / URL open / app launch / Gmail compose are all handled by
# EXEC (executor.py). The old macOS-only AppleScript browser helpers
# (get_frontmost_app_name, open_url_in_active_browser, open_mac_app,
# gmail_compose_in_active_browser, ...) are superseded by the platform executor
# and the D1 frontmost-driven rule (PRD §8.1, §8.3).

# ----------------- Mouse Controller -----------------

class MouseController:
    def __init__(self):
        # filtered velocity components (normalized -1..1) for vx/vy path
        self.vx_f = 0.0
        self.vy_f = 0.0
        self.alpha = 0.35  # smoothing factor: higher = snappier, lower = smoother
        self.last_input_t = time.monotonic()
        self.idle_timeout = 0.04  # faster decay when stream stops

        # filtered angles (degrees) for angle path
        self.roll_f = 0.0
        self.pitch_f = 0.0

    def _clamp(self, x, lo, hi):
        return max(lo, min(hi, x))

    # ----- vx/vy streaming path (version A) -----
    def update_cursor(self, vx, vy, dt):
        now = time.monotonic()
        dt = self._clamp(dt, 0.005, 0.05)  # 20..200 Hz range

        # low-pass filter incoming velocity to reduce jitter
        a = self.alpha
        self.vx_f = a * vx + (1 - a) * self.vx_f
        self.vy_f = a * vy + (1 - a) * self.vy_f

        # small deadband
        if abs(self.vx_f) < CURSOR_DEAD_SPEED:
            self.vx_f = 0.0
        if abs(self.vy_f) < CURSOR_DEAD_SPEED:
            self.vy_f = 0.0

        # decay to zero if stream pauses (prevents drift)
        if (now - self.last_input_t) > self.idle_timeout:
            self.vx_f = 0.0
            self.vy_f = 0.0
        self.last_input_t = now

        # translate normalized velocity to pixel delta
        dx = self.vx_f * CURSOR_PIXELS_PER_SEC * dt
        dy = -self.vy_f * CURSOR_PIXELS_PER_SEC * dt  # screen y is down

        # clamp per-frame delta to avoid sudden jumps on network hiccups
        dx = self._clamp(dx, -24, 24)
        dy = self._clamp(dy, -24, 24)

        if dx == 0 and dy == 0:
            return
        try:
            pyautogui.moveRel(dx, dy, duration=0)  # duration=0 is essential for low latency
        except Exception as e:
            print("moveRel error:", e)

    # ----- angle path with single-axis dominance (version B) -----
    def _axis_speed(self, angle_deg: float) -> float:
        eff = max(0.0, abs(angle_deg) - DEAD_ZONE_DEG)
        n = min(1.0, eff / SAT_ANGLE_DEG)
        return V_MIN + (V_MAX - V_MIN) * (n * n)

    def update_cursor_from_angles(self, roll_deg: float, pitch_deg: float, dt: float):
        # low-pass filter the angles
        a = ALPHA_ANGLE
        self.roll_f  = a * roll_deg  + (1 - a) * self.roll_f
        self.pitch_f = a * pitch_deg + (1 - a) * self.pitch_f

        # Choose a single dominant axis (no diagonals)
        vx = 0.0
        vy = 0.0
        ax = abs(self.roll_f)
        ay = abs(self.pitch_f)

        # both inside dead zone → stop
        if ax <= DEAD_ZONE_DEG and ay <= DEAD_ZONE_DEG:
            vx = 0.0
            vy = 0.0
        elif ax >= ay:
            # horizontal dominates
            if ax > DEAD_ZONE_DEG:
                vx = (1.0 if self.roll_f > 0 else -1.0) * self._axis_speed(self.roll_f)
                vy = 0.0
        else:
            # vertical dominates; forward tilt (pitch > 0) moves cursor down (+y)
            if ay > DEAD_ZONE_DEG:
                vy = (1.0 if self.pitch_f > 0 else -1.0) * self._axis_speed(self.pitch_f)
                vx = 0.0

        # integrate to per-tick deltas and clamp
        dx = vx * dt
        dy = vy * dt

        dx = self._clamp(dx, -MAX_STEP_PX, MAX_STEP_PX)
        dy = self._clamp(dy, -MAX_STEP_PX, MAX_STEP_PX)

        if dx == 0.0 and dy == 0.0:
            return

        try:
            pyautogui.moveRel(dx, dy, duration=0)
        except Exception as e:
            print("moveRel error:", e)

    def click(self):
        try:
            pyautogui.mouseDown()
            pyautogui.mouseUp()
        except Exception as e:
            print("click error:", e)

MOUSE = MouseController()

# --- Camera gesture engine wiring ---
GEST_ENGINE = None

def ensure_gesture_engine():
    """
    Lazy-initialize a singleton CameraGestureEngine and return it.
    The engine invokes on_action(action: str) which we map to hotkeys.
    """
    global GEST_ENGINE
    if GEST_ENGINE is None:
        def on_action(a: str):
            try:
                if a == "zoom_in":
                    browser_zoom_in()
                    
                elif a == "zoom_out":
                    browser_zoom_out()     
                    
                elif a == "history_back":
                    browser_history_back()
                elif a == "history_forward":
                    browser_history_forward()
                elif a == "next_tab":
                    browser_next_tab()
                elif a == "prev_tab":
                    browser_prev_tab()
                elif a == "scroll_up":
                    pyautogui.scroll(5)
                elif a == "scroll_down":
                    pyautogui.scroll(-5)
                elif a == "app_switcher_start":
                    # Hold the switch modifier (Cmd on macOS, Alt elsewhere)
                    # and press Tab to reveal the switcher (§8.2).
                    pyautogui.keyDown(app_switch_modifier())
                    pyautogui.press("tab")
                elif a == "app_switcher_next":
                    pyautogui.press("tab")
                elif a == "app_switcher_prev":
                    pyautogui.hotkey("shift", "tab")
                elif a == "app_switcher_commit":
                    # Release the switch modifier to commit the selected app
                    pyautogui.keyUp(app_switch_modifier())
            except Exception as e:
                print("gesture action error:", a, e)
        try:
            GEST_ENGINE = CameraGestureEngine(on_action)
        except Exception as e:
            print("failed to init CameraGestureEngine:", e)
            GEST_ENGINE = None
    return GEST_ENGINE

# --- gesture handlers --------------------------------------------------------

def handle_tilt_vector(payload: dict):
    vx = float(payload.get("vx", 0.0))
    vy = float(payload.get("vy", 0.0))
    dt = float(payload.get("dt", 0.016))
    # guard dt to keep motion stable
    if not (0.0005 <= dt <= 0.2):
        dt = 0.016
    MOUSE.update_cursor(vx, vy, dt)
    return "tilt_ok"


def handle_tilt_angles(payload: dict):
    # read roll and pitch angles in DEGREES; dt in seconds
    # roll > 0 → right tilt; pitch > 0 → forward tilt (cursor down)
    roll = float(payload.get("roll_deg", payload.get("roll", 0.0)))
    pitch = float(payload.get("pitch_deg", payload.get("pitch", 0.0)))
    dt = float(payload.get("dt", 1.0 / UPDATE_HZ))
    if not (0.0005 <= dt <= 0.2):
        dt = 1.0 / UPDATE_HZ
    MOUSE.update_cursor_from_angles(roll, pitch, dt)
    return "tilt_angles_ok"


_last_click_t = 0.0

def handle_tap(_payload: dict):
    global _last_click_t
    now = time.monotonic()
    if now - _last_click_t < 0.10:  # 100ms debounce
        return "click_ignored"
    _last_click_t = now
    try:
        pyautogui.mouseDown(); pyautogui.mouseUp()
        return "click_ok"
    except Exception as e:
        print("click error:", e)
        return "click_failed"

# --- intent execution --------------------------------------------------------

def apply_plan(plan: dict, slots: dict):
    t = plan.get("type")

    # Open an application by name or bundle id (cross-platform via EXEC).
    if t in {"applescript_open_app", "open_app"}:
        app_raw = (slots.get("app") or "").strip()
        if not app_raw:
            return "open_app_missing"
        # Resolve alias → platform-specific name/bundle id
        app_name = slot_app(app_raw) or app_raw
        rc = EXEC.open_app(app_name)
        return "opened_app" if rc == 0 else "open_app_failed"

    if t == "applescript_gmail_compose":
        return EXEC.compose_email("", "", "", send=False)

    if t == "applescript_open_url":
        raw = slots.get("url", "")
        # If the user said an app name (e.g. "safari", "keynote"), open the app.
        app_guess = slot_app(raw)
        if app_guess and raw and "." not in raw and "://" not in raw:
            rc = EXEC.open_app(app_guess)
            return "opened_app" if rc == 0 else "open_app_failed"

        url = slot_site(raw)  # alias → URL or normalized token
        parsed = urlparse(url)
        if not (parsed.scheme and parsed.netloc):
            url = f"https://www.google.com/search?q={quote(raw.strip())}"
        return EXEC.open_url(url)

    if t == "applescript_keynote_start":
        # D2: Google Slides is the cross-platform presentation path.
        return EXEC.start_presentation()

    if plan.get("intent") == "type_text":
        txt = (slots.get("text") or "").strip()
        if txt:
            focused_typing(txt); return "typed"
        return "typed_empty"

    if t == "hotkey":
        keys = remap_intent_keys(plan.get("intent", ""), plan.get("keys", []))
        if keys:
            try:
                pyautogui.hotkey(*keys)
            except Exception as e:
                print("hotkey error:", e); return "hotkey_failed"
        return "hotkey"
    if t == "key":
        pyautogui.press(plan["key"]); return "key"
    if t == "scroll":
        pyautogui.scroll(plan.get("amount", -600)); return "scroll"

    if t == "repeat_last":
        global LAST_EXECUTED
        if not LAST_EXECUTED: return "no_last_action"
        if LAST_EXECUTED["intent"] in REPEAT_BLOCKLIST: return "repeat_blocked"
        return apply_plan(LAST_EXECUTED["plan"], LAST_EXECUTED["slots"])

    if t == "mailto_compose":
        # Prefer Gmail web compose; fall back to a mailto: URL if it fails.
        to = (slots.get("to") or "").strip()
        subject = (slots.get("subject") or "").strip()
        body = (slots.get("body") or "").strip()
        res = EXEC.compose_email(to, subject, body, send=False)
        if res != "gmail_compose_opened" and (to or subject or body):
            EXEC.open_url(mailto_url(to, subject, body))
            time.sleep(1.0)
            return "mailto_composed"
        return res

    return "noop"


def execute_intent(intent: str, slots: dict):
    # Server-level intents
    if intent == "set_browser":
        # Demoted to a near-no-op (D1) — frontmost rule supersedes preference.
        set_preferred_browser((slots.get("browser") or "").strip())
        return "browser_set"

    if intent == "compose_email":
        return EXEC.compose_email(
            slots.get("to", ""),
            slots.get("subject", ""),
            slots.get("body", ""),
            send=False
        )

    if intent == "send_email":
        # one-shot send if fields provided; else send current compose
        to = slots.get("to"); subject = slots.get("subject"); body = slots.get("body")
        if any([to, subject, body]):
            return EXEC.compose_email(to or "", subject or "", body or "", send=True)
        try:
            pyautogui.hotkey(primary_modifier(), "enter")  # Cmd/Ctrl+Enter
            return "gmail_sent"
        except Exception as e:
            print("gmail send hotkey error:", e)
            return "gmail_send_failed"

    if intent == "new_tab":
        # D1: new tab in the frontmost browser; if none is focused, open the
        # default browser (which yields a fresh window/tab).
        try:
            if EXEC.frontmost_is_browser():
                keys = remap_intent_keys("new_tab", KEYMAP.get("new_tab", {}).get("keys", ["command", "t"]))
                pyautogui.hotkey(*keys)
                return "new_tab"
            EXEC.open_default_browser()
            return "opened_browser"
        except Exception as e:
            print("new_tab error:", e)
            return "new_tab_failed"

    global LAST_EXECUTED
    plan = KEYMAP.get(intent)
    if not plan: return "unknown_intent"
    plan = {**plan, "intent": intent}
    status = apply_plan(plan, slots)
    if intent not in REPEAT_BLOCKLIST and status not in {"noop","unknown_intent"}:
        LAST_EXECUTED = {"intent": intent, "plan": plan, "slots": slots}
    return status

# --- websocket server --------------------------------------------------------

async def ws_handler(websocket):
    print(f"[{now()}] 🚪 client connected: {websocket.remote_address}")
    # send hello so iPhone can confirm
    await websocket.send(json.dumps({"ok": True, "type": "hello", "from": "server"}))
    try:
        async for msg in websocket:
            print(f"[{now()}] ⇦ rx: {msg[:200]}")
            try:
                data = json.loads(msg)
            except:
                await websocket.send(json.dumps({"ok": False, "error": "bad_json"}))
                continue

            typ = data.get("type")
            if typ == "hello":
                await websocket.send(json.dumps({"ok": True, "type": "hello_ack"}))
                continue

            if typ == "command":
                text = data.get("text","")
                # local route first
                intent, slots, how = local_route(text)
                if intent:
                    res = execute_intent(intent, slots)
                    await websocket.send(json.dumps({"ok": True, "result": res, "via": how}))
                    continue
                # LLM fallback (fail-soft — PRD §8.6). A dead/missing Ollama
                # must not crash or stall the socket; it degrades cleanly.
                try:
                    plan = ollama_route(text) or {}
                except OllamaUnavailable:
                    await websocket.send(json.dumps({"ok": False, "error": "nlu_failed:llm_unavailable"}))
                    continue
                except Exception as e:
                    print("ollama_route error:", e)
                    await websocket.send(json.dumps({"ok": False, "error": "nlu_failed:llm_error"}))
                    continue
                vr = validate_and_normalize_plan(plan)
                err = None
                action = None
                slots = {}

                # Accept (action, slots) OR ((action, slots), err) OR {"action":..., "slots":...}
                if isinstance(vr, tuple):
                    if len(vr) == 2 and isinstance(vr[0], str):
                        action, slots = vr
                    elif len(vr) == 2 and isinstance(vr[0], tuple):
                        (action, slots), err = vr
                elif isinstance(vr, dict):
                    action = vr.get("action") or vr.get("intent")
                    slots = vr.get("slots", {})

                if err or not action:
                    await websocket.send(json.dumps({"ok": False, "error": f"nlu_failed:{err or 'bad_plan'}"}))
                    continue

                res = execute_intent(action, slots)
                await websocket.send(json.dumps({"ok": True, "result": res, "via": "llm"}))

            elif typ == "gesture":
                kind = data.get("kind")
                if kind == "tilt_vector":
                    res = handle_tilt_vector(data)
                elif kind == "tilt_angles":
                    res = handle_tilt_angles(data)
                elif kind == "tap":
                    res = handle_tap(data)
                elif kind == "swipe":
                    # Swipe mapping (from phone or camera):
                    # right → history forward
                    # left  → history back
                    # up    → scroll up
                    # down  → scroll down
                    direction = (data.get("direction") or "").lower()
                    if not direction:
                        try:
                            dx = float(data.get("dx", 0.0))
                            dy = float(data.get("dy", 0.0))
                            if abs(dx) >= abs(dy):
                                direction = "right" if dx > 0 else "left"
                            else:
                                direction = "down" if dy > 0 else "up"
                        except Exception:
                            direction = ""
                    if direction == "right":
                        browser_history_forward(); res = "history_forward"
                    elif direction == "left":
                        browser_history_back(); res = "history_back"
                    elif direction == "up":
                        scroll_up(); res = "scroll_up"
                    elif direction == "down":
                        scroll_down(); res = "scroll_down"
                    else:
                        res = "gesture_ignored"
                elif kind == "gestures_toggle":
                    enabled = bool(data.get("enabled"))
                    eng = ensure_gesture_engine()
                    if not eng:
                        res = "gestures_unavailable"
                    else:
                        if enabled:
                            eng.start(); res = "gestures_on"
                        else:
                            eng.stop(); res = "gestures_off"
                elif kind == "motion_started":
                    res = "motion_started"
                else:
                    res = "gesture_ignored"
                await websocket.send(json.dumps({"ok": True, "result": res}))
            else:
                await websocket.send(json.dumps({"ok": False, "error": "unknown_type"}))
    finally:
        print(f"[{now()}] 📴 client disconnected: {websocket.remote_address}")


def print_startup_warnings():
    """One-time loud warnings for unsupported/degraded environments (§8.5)."""
    plat = detect_platform()
    print(f"Platform: {plat} ({type(EXEC).__name__})")
    if plat == "linux":
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            print("⚠️  Wayland session detected — global input injection is "
                  "blocked by the OS. Use an X11 session (or XWayland for X11 "
                  "target apps). See PRD §10 (L-3).")
        if is_wsl():
            print("⚠️  WSL2 detected — hotkey injection into the Windows "
                  "desktop is unreliable; WSL2 is not a supported target "
                  "(PRD §10 L-4).")
    if not probe_ollama():
        print(f"⚠️  Ollama not reachable at {OLLAMA_URL} → local NLU only "
              "(regex / keyword / TF-IDF). The LLM fallback is disabled until "
              "Ollama is running — see setup.sh / setup.ps1.")


async def main():
    print_startup_warnings()
    print("Server listening on ws://0.0.0.0:8765")
    async with websockets.serve(ws_handler, "0.0.0.0", 8765, ping_interval=None):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        import asyncio; asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)