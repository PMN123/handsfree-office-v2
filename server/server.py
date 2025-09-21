# server/server.py
import json, asyncio, sys
from pathlib import Path
import websockets

from urllib.parse import urlparse, quote, urlencode

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

# ===== Browser preference state (active browser selection) =====
PREFERRED_BROWSER = None  # "Safari" or any app in CHROME_FAMILY

def set_preferred_browser(name: str):
  """Set the active browser preference. Accepts Safari or any of CHROME_FAMILY names."""
  global PREFERRED_BROWSER
  if not name:
      return
  n = str(name).strip()
  if n.lower() in {"safari", "apple safari"}:
      PREFERRED_BROWSER = "Safari"
  elif n in CHROME_FAMILY or n.lower() in {"google chrome", "chrome", "brave browser", "microsoft edge", "vivaldi"}:
      # normalize common lowercase to canonical names
      if n.lower() == "chrome": n = "Google Chrome"
      elif n.lower() == "brave": n = "Brave Browser"
      elif n.lower() == "edge": n = "Microsoft Edge"
      PREFERRED_BROWSER = n

# ===== Gesture → Action tuning =====
# --- at top of file
import pyautogui
pyautogui.FAILSAFE = False

MOUSE_MODE = "cursor"           # cursor (not scroll)
# Extra smoothing/tuning (feel free to tweak live)
CURSOR_PIXELS_PER_SEC = 1800  # a touch faster for gyro control
CURSOR_DEAD_SPEED = 0.03      # slightly larger deadband to remove jitter

# --- Frontmost app + browser/tab helpers ---------------------------------------------------------

def get_frontmost_app_name() -> str:
    """Return the name of the frontmost macOS app, or empty string on failure."""
    script = '''
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
    end tell
    return frontApp
    '''
    try:
        name = run_applescript(script)
        return str(name).strip()
    except Exception as e:
        print("frontmost app error:", e)
        return ""


def applescript_open_url_in_chrome_family(app_name: str, url: str) -> int:
    """Open a URL in a Chromium-based browser via AppleScript tab API."""
    script = f'''
    try
        tell application "{app_name}"
            activate
            if (count of windows) = 0 then make new window
            set newTab to make new tab at end of tabs of front window
            set URL of newTab to "{url}"
        end tell
        return 0
    on error errText number errNum
        return errNum
    end try
    '''
    return int(run_applescript(script))


def applescript_open_url_in_safari(url: str) -> int:
    script = f'''
    try
        tell application "Safari"
            activate
            if (count of windows) = 0 then make new document
            tell window 1
                set current tab to (make new tab with properties {{URL:"{url}"}})
            end tell
        end tell
        return 0
    on error errText number errNum
        return errNum
    end try
    '''
    return int(run_applescript(script))


CHROME_FAMILY = {
    "Google Chrome",
    "Brave Browser",
    "Microsoft Edge",
    "Vivaldi",
}

def open_url_in_browser(url: str, browser: str) -> str:
    """Open URL in the specific browser name provided."""
    if browser == "Safari":
        rc = applescript_open_url_in_safari(url)
        if rc == 0:
            return "opened_url_safari"
    elif browser in CHROME_FAMILY:
        rc = applescript_open_url_in_chrome_family(browser, url)
        if rc == 0:
            return f"opened_url_{browser.lower().replace(' ', '_')}"
    # If we get here, try a generic open -a
    import subprocess, shlex
    try:
        subprocess.check_call(f"open -a {shlex.quote(browser)} {shlex.quote(url)}", shell=True)
        return f"opened_url_{browser.lower().replace(' ', '_')}_fallback"
    except Exception as e:
        print("open -a fallback error:", e)
        # Final fallback: default handler
        try:
            subprocess.check_call(f"open {shlex.quote(url)}", shell=True)
            return "opened_url_default_fallback"
        except Exception as e2:
            print("open default fallback error:", e2)
            return "open_url_failed"

def open_url_in_active_browser(url: str) -> str:
    """
    Open URL in the active browser:
    - use PREFERRED_BROWSER if set
    - else use frontmost app if it is a browser
    - else use system default
    """
    if PREFERRED_BROWSER:
        return open_url_in_browser(url, PREFERRED_BROWSER)
    front = get_frontmost_app_name()
    if front == "Safari" or front in CHROME_FAMILY:
        return open_url_in_browser(url, front)
    # fall back to default if no browser is frontmost
    import subprocess, shlex
    try:
        subprocess.check_call(f"open {shlex.quote(url)}", shell=True)
        return "opened_url_default"
    except Exception as e:
        print("open default error:", e)
        return "open_url_failed"

def open_url_in_frontmost_browser(url: str) -> str:
    # Backwards-compat shim - now respects preferred browser if set
    return open_url_in_active_browser(url)

def open_mac_app(app_raw: str) -> int:
    """Open arbitrary macOS app by name or bundle id; return 0 on success, nonzero on failure."""
    app = app_raw.strip()
    if not app:
        return 1
    if "." in app:  # looks like bundle id, e.g., "zoom.us"
        script = f'''
        try
            tell application id "{app}"
                if it is not running then launch
                activate
            end tell
            return 0
        on error errText number errNum
            return errNum
        end try
        '''
    else:
        script = f'''
        try
            tell application "{app}"
                if it is not running then launch
                activate
            end tell
            return 0
        on error errText number errNum
            return errNum
        end try
        '''
    rc = run_applescript(script)
    if str(rc).strip() == "0":
        return 0
    # Fallback: open -a "App"
    import subprocess, shlex
    try:
        subprocess.check_call(f"open -a {shlex.quote(app)}", shell=True)
        return 0
    except Exception as e:
        print("open_app error:", e)
        return 1

def _gmail_compose_url(to: str = "", subject: str = "", body: str = "") -> str:
    params = {
        "view": "cm",
        "fs": "1",
        "to": to or "",
        "su": subject or "",
        "body": body or "",
    }
    return "https://mail.google.com/mail/?" + urlencode(params, doseq=False, safe=":/?&=")

def gmail_compose_in_active_browser(to: str, subject: str, body: str, send: bool = False) -> str:
    url = _gmail_compose_url(to, subject, body)
    res = open_url_in_active_browser(url)
    # small delay so the compose UI is ready
    time.sleep(0.8)
    if send:
        try:
            pyautogui.hotkey("command", "enter")
        except Exception as e:
            print("gmail send hotkey error:", e)
            return "gmail_send_failed"
    return "gmail_compose_opened" if res.startswith("opened_url") else "gmail_compose_failed"

class MouseController:
    def __init__(self):
        # filtered velocity components (normalized -1..1)
        self.vx_f = 0.0
        self.vy_f = 0.0
        self.alpha = 0.35  # smoothing factor: higher = snappier, lower = smoother
        self.last_input_t = time.monotonic()
        self.idle_timeout = 0.04  # faster decay when stream stops

    def _clamp(self, x, lo, hi):
        return max(lo, min(hi, x))

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

    # Open arbitrary macOS application by name or bundle id
    if t in {"applescript_open_app", "open_app"}:
        app_raw = (slots.get("app") or "").strip()
        if not app_raw:
            return "open_app_missing"
        # Resolve alias → canonical name/bundle id
        app_name = slot_app(app_raw) or app_raw
        rc = open_mac_app(app_name)
        return "opened_app" if rc == 0 else "open_app_failed"

    if t == "applescript_gmail_compose":
        open_gmail_compose(); return "opened_gmail"

    if t == "applescript_open_url":
        raw = slots.get("url", "")
        # Heuristic: if user said an app name (e.g., "safari", "keynote"), open the app instead of searching
        app_guess = slot_app(raw)
        if app_guess and raw and "." not in raw and "://" not in raw:
            rc = open_mac_app(app_guess)
            return "opened_app" if rc == 0 else "open_app_failed"

        url = slot_site(raw)  # alias → URL or normalized token
        parsed = urlparse(url)
        if not (parsed.scheme and parsed.netloc):
            url = f"https://www.google.com/search?q={quote(raw.strip())}"
        return open_url_in_active_browser(url)

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
        # Prefer Gmail web compose with fields if we have at least one field
        if to or subject or body:
            return gmail_compose_in_active_browser(to, subject, body, send=False)
        # Otherwise, open Gmail compose window
        open_gmail_compose()
        return "opened_gmail"

    return "noop"

def execute_intent(intent: str, slots: dict):
    # Handle server-level intents not present in keymap
    if intent == "set_browser":
        browser = (slots.get("browser") or "").strip()
        set_preferred_browser(browser)
        return "browser_set"

    if intent == "compose_email":
        return gmail_compose_in_active_browser(
            slots.get("to", ""),
            slots.get("subject", ""),
            slots.get("body", ""),
            send=False
        )

    if intent == "send_email":
        # one-shot send if fields provided; else send current compose
        to = slots.get("to"); subject = slots.get("subject"); body = slots.get("body")
        if any([to, subject, body]):
            return gmail_compose_in_active_browser(to or "", subject or "", body or "", send=True)
        try:
            pyautogui.hotkey("command", "enter")
            return "gmail_sent"
        except Exception as e:
            print("gmail send hotkey error:", e)
            return "gmail_send_failed"

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