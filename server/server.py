# server/server.py
import json, asyncio, sys
from pathlib import Path
import websockets

from urllib.parse import urlparse, quote

from primitives import (
    run_applescript, focused_typing, open_gmail_compose,
    start_keynote_slideshow, mailto_url
)
from nlu import (
    KEYMAP, SLOTS, slot_app, slot_site,
    local_route, ollama_route, validate_and_normalize_plan
)
import time


import datetime
def now(): return datetime.datetime.now().strftime("%H:%M:%S")

REPEAT_BLOCKLIST = {"type_text", "mailto_compose"}  # intents we won't auto-repeat

# ===== Gesture → Action tuning =====
# --- at top of file
import pyautogui
pyautogui.FAILSAFE = False

MOUSE_MODE = "cursor"           # cursor (not scroll)
# Extra smoothing/tuning (feel free to tweak live)
CURSOR_PIXELS_PER_SEC = 1800  # a touch faster for gyro control
CURSOR_DEAD_SPEED = 0.03      # slightly larger deadband to remove jitter

# --- Tilt-angle control (degrees and px/s), per prompt ---
DEAD_ZONE_DEG = 10.0
V_MIN = 120.0          # px/s at threshold
V_MAX = 520.0          # px/s at saturation
SAT_ANGLE_DEG = 25.0   # degrees beyond the 5° dead zone where speed saturates
ALPHA_ANGLE = 0.2      # low-pass on angles
MAX_STEP_PX = 16.0     # clamp per-tick pixel move
UPDATE_HZ = 30.0       # target update frequency (informational)

class MouseController:
    def __init__(self):
        # filtered velocity components (normalized -1..1)
        self.vx_f = 0.0
        self.vy_f = 0.0
        self.alpha = 0.35  # smoothing factor: higher = snappier, lower = smoother
        self.last_input_t = time.monotonic()
        self.idle_timeout = 0.04  # faster decay when stream stops

        # filtered angles (degrees)
        self.roll_f = 0.0
        self.pitch_f = 0.0

    def _clamp(self, x, lo, hi):
        return max(lo, min(hi, x))

    def _axis_speed(self, angle_deg: float) -> float:
        eff = max(0.0, abs(angle_deg) - DEAD_ZONE_DEG)
        n = min(1.0, eff / SAT_ANGLE_DEG)
        return V_MIN + (V_MAX - V_MIN) * (n * n)

    def update_cursor(self, vx, vy, dt):
        now = time.monotonic()
        # sanitize dt to avoid huge jumps
        dt = self._clamp(dt, 0.005, 0.05)  # 20..200 Hz range

        # 1) low‑pass filter incoming velocity to reduce jitter
        a = self.alpha
        self.vx_f = a * vx + (1 - a) * self.vx_f
        self.vy_f = a * vy + (1 - a) * self.vy_f

        # 2) small deadband
        if abs(self.vx_f) < CURSOR_DEAD_SPEED:
            self.vx_f = 0.0
        if abs(self.vy_f) < CURSOR_DEAD_SPEED:
            self.vy_f = 0.0

        # 3) decay to zero if stream pauses (prevents drift)
        if (now - self.last_input_t) > self.idle_timeout:
            self.vx_f = 0.0
            self.vy_f = 0.0
        self.last_input_t = now

        # 4) translate normalized velocity to pixel delta
        dx = self.vx_f * CURSOR_PIXELS_PER_SEC * dt
        dy = -self.vy_f * CURSOR_PIXELS_PER_SEC * dt  # screen y is down

        # clamp per‑frame delta to avoid sudden jumps on network hiccups
        dx = self._clamp(dx, -24, 24)
        dy = self._clamp(dy, -24, 24)

        if dx == 0 and dy == 0:
            return
        try:
            pyautogui.moveRel(dx, dy, duration=0)  # duration=0 is essential for low latency
        except Exception as e:
            print("moveRel error:", e)

    def update_cursor_from_angles(self, roll_deg: float, pitch_deg: float, dt: float):
        # low-pass filter the angles
        a = ALPHA_ANGLE
        self.roll_f  = a * roll_deg  + (1 - a) * self.roll_f
        self.pitch_f = a * pitch_deg + (1 - a) * self.pitch_f

        # velocities (px/s) from filtered angles with 5° dead zone
        # Choose a single dominant axis (no diagonals): whichever |angle| is larger wins
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

# --- add these handlers
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

def apply_plan(plan: dict, slots: dict):
    t = plan.get("type")

    if t == "applescript_gmail_compose":
        open_gmail_compose(); return "opened_gmail"

    if t == "applescript_open_url":
        raw = slots.get("url", "")
        url = slot_site(raw)  # alias → URL or normalized token
        # final sanity: valid URL? else fallback to a Google search
        parsed = urlparse(url)
        if not (parsed.scheme and parsed.netloc):
            url = f"https://www.google.com/search?q={quote(raw.strip())}"
        script = f'''
        tell application "Google Chrome"
            activate
            if (count of windows) = 0 then make new window
            set newTab to make new tab at end of tabs of front window
            set URL of newTab to "{url}"
        end tell
        '''
        run_applescript(script); return "opened_url"

    if t == "applescript_keynote_start":
        start_keynote_slideshow(); return "opened_presentation"

    if plan.get("intent") == "type_text":
        txt = (slots.get("text") or "").strip()
        if txt:
            focused_typing(txt); return "typed"
        return "typed_empty"

    if t == "hotkey":
        pyautogui.hotkey(*plan["keys"]); return "hotkey"
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
        to = (slots.get("to") or "").strip()
        subject = (slots.get("subject") or "").strip()
        body = (slots.get("body") or "").strip()
        if not to:
            open_gmail_compose(); return "opened_gmail"
        url = mailto_url(to, subject, body)
        script = f'''
        tell application "Google Chrome"
            activate
            if (count of windows) = 0 then make new window
            set newTab to make new tab at end of tabs of front window
            set URL of newTab to "{url}"
        end tell
        '''
        run_applescript(script); time.sleep(1.0); return "mailto_composed"

    return "noop"

def execute_intent(intent: str, slots: dict):
    global LAST_EXECUTED
    plan = KEYMAP.get(intent)
    if not plan: return "unknown_intent"
    plan = {**plan, "intent": intent}
    status = apply_plan(plan, slots)
    if intent not in REPEAT_BLOCKLIST and status not in {"noop","unknown_intent"}:
        LAST_EXECUTED = {"intent": intent, "plan": plan, "slots": slots}
    return status

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
                # LLM fallback
                plan = ollama_route(text) or {}
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
                    # swipe handler removed per instructions, so fallback
                    res = "gesture_ignored"
                elif kind == "motion_started":
                    res = "motion_started"
                else:
                    res = "gesture_ignored"
                await websocket.send(json.dumps({"ok": True, "result": res}))
            else:
                await websocket.send(json.dumps({"ok": False, "error": "unknown_type"}))
    finally:
        print(f"[{now()}] 📴 client disconnected: {websocket.remote_address}")
async def main():
    print("Server listening on ws://0.0.0.0:8765")
    async with websockets.serve(ws_handler, "0.0.0.0", 8765, ping_interval=None):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        import asyncio; asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)