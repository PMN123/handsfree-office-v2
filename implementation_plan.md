# HandsFree Cross-Platform Migration — Merged Architecture Plan

## Step 1: Codebase Audit (Verified — unchanged from initial audit)

### 1.1 Complete macOS Dependency Inventory

Exhaustive list of every OS-specific coupling found across all files:

---

#### [primitives.py](file:///c:/code/GitPublic/handsfree-office-v2/server/primitives.py) — 4 macOS dependencies

| Line(s) | Dependency | Description |
|---------|-----------|-------------|
| L12-31 | `run_applescript()` → `osascript -e` | Core primitive. Every AppleScript-based action depends on this. |
| L37 | `pyautogui.hotkey("command", "v")` in `focused_typing()` | macOS `Cmd` modifier. Windows/Linux require `"ctrl"`. |
| L39-52 | `open_gmail_compose()` → hardcoded Chrome AppleScript | Directly talks to Chrome via AppleScript tab model. |
| L54-70 | `start_keynote_slideshow()` → Keynote AppleScript | macOS-only app. |

---

#### [server.py](file:///c:/code/GitPublic/handsfree-office-v2/server/server.py) — 16 macOS dependencies

| Line(s) | Dependency | Description |
|---------|-----------|-------------|
| L56-96 | `browser_history_back/forward`, `browser_zoom_in/out/reset` | All use `pyautogui.hotkey("command", ...)`. |
| L126-139 | `get_frontmost_app_name()` | Pure AppleScript via `System Events`. |
| L142-157 | `applescript_open_url_in_chrome_family()` | AppleScript Chrome tab API. |
| L160-175 | `applescript_open_url_in_safari()` | AppleScript Safari tab API. |
| L189-200 | Fallback `open -a` / `open` (subprocess) | macOS `open` command. |
| L229-267 | `open_mac_app()` | AppleScript `tell application`, fallback to `open -a`. |
| L288 | `pyautogui.hotkey("command", "enter")` | Gmail send hotkey. |
| L436-446 | App Switcher: `keyDown("command")` / `keyUp("command")` | macOS ⌘+Tab. Windows/Linux = `Alt+Tab`. |
| L538 | `pyautogui.hotkey(*plan["keys"])` in `apply_plan` | Reads macOS key names from keymap.json. |
| L594 | `pyautogui.hotkey("command", "enter")` | send_email intent. |

---

#### [keymap.json](file:///c:/code/GitPublic/handsfree-office-v2/config/keymap.json) — THE BIGGEST HIDDEN DEPENDENCY

> [!CAUTION]
> `keymap.json` contains **29 entries** using `"command"` as a modifier, **2** using `"option"`, and **2** using `"fn"`. **Verified**: `pyautogui` on Windows throws `InvalidKeyException` for `"command"` — it is NOT silently mapped to `ctrl`. This makes runtime key remapping **mandatory**, not optional.

---

#### [gestures.py](file:///c:/code/GitPublic/handsfree-office-v2/server/gestures.py) — OS-agnostic ✅ (code-level)

Uses only `cv2`, `mediapipe`, `math`, `threading`, `time`. The `on_action` callback in `server.py` is where OS-specific hotkeys live — `gestures.py` itself is clean.

> [!NOTE]
> **Windows camera optimization needed**: `cv2.VideoCapture(0)` on Line 127 defaults to MSMF backend on Windows, which has higher initialization latency vs DirectShow. Verified: `CAP_DSHOW` gives faster startup for single-camera use.

---

#### [nlu.py](file:///c:/code/GitPublic/handsfree-office-v2/server/nlu.py) — OS-agnostic ✅

Uses `scikit-learn`, `httpx`, `tenacity`, `json`, `re`, `pathlib`. No OS-specific code. BUT: `slot_app()` on L23-25 reads from `slots.json` which has macOS-only app names — the **function** is agnostic, the **data** is not.

---

#### [system_prompt.txt](file:///c:/code/GitPublic/handsfree-office-v2/config/system_prompt.txt) — Cosmetic macOS references

Line 1: `"on macOS"`, Line 15: `"<macOS display name>"`. Soft coupling (LLM text, not code), but should be platform-neutral.

#### [slots.json](file:///c:/code/GitPublic/handsfree-office-v2/config/slots.json) — macOS app names

Maps to macOS display names (`"Keynote"`, `"zoom.us"` bundle ID). Need platform-specific variants.

---

### 1.2 Flutter Package Verification

#### What the Swift client sends ([MotionSpeechStreamer.swift](file:///c:/code/GitPublic/handsfree-office-v2/ios/HandsFreeOffice/MotionSpeechStreamer.swift)):

| Data | JSON payload | Source |
|------|-------------|--------|
| **Tilt** | `{"type":"gesture","kind":"tilt_angles","roll_deg":D,"pitch_deg":D,"dt":D}` | `CMDeviceMotion.attitude.roll/.pitch` in `.xArbitraryZVertical` frame, converted to degrees. Pitch inverted (L306). |
| **Tap** | `{"type":"gesture","kind":"tap"}` | `CMDeviceMotion.userAcceleration` magnitude > 1.10g |
| **Voice** | `{"type":"command","text":"..."}` | `SFSpeechRecognizer` with partial debounce (1.3s timer) |

#### Package verdicts:

| Package | Verdict | Rationale |
|---------|---------|-----------|
| `speech_to_text` | ✅ **Correct** | Platform speech APIs, partial results, multiple locales. |
| `motion_sensors` | ❌ **WRONG** | Gives raw gyroscope angular velocity — NOT fused attitude. Cannot replicate `CMDeviceMotion.attitude`. |
| `web_socket_channel` | ✅ **Correct** | Standard Dart WebSocket. |

> [!WARNING]
> **Both plans agree**: No Flutter package gives hardware-fused attitude (roll/pitch from sensor fusion). **Platform channels** are required — iOS `CMMotionManager` + Android `SensorManager.TYPE_ROTATION_VECTOR`.

**Tap detection**: `sensors_plus` `userAccelerometerEventStream()` provides acceleration minus gravity — exact equivalent of `CMDeviceMotion.userAcceleration`. No platform channel needed for this part.

---

### 1.3 pyautogui Cross-Platform Reality (verified via web search)

| Operation | Status | Notes |
|-----------|--------|-------|
| `moveRel()`, `mouseDown()/mouseUp()`, `click()` | ✅ | Works everywhere |
| `press()`, `hotkey()` | ⚠️ | Only if correct key names used per-platform |
| `scroll()` | ✅ | Works everywhere |
| `hotkey("command", ...)` on Windows | ❌ | **Throws `InvalidKeyException`**. Must use `"ctrl"`. |
| `hotkey("option", ...)` on Windows | ❌ | Must use `"alt"` |
| `hotkey("fn", ...)` on Windows | ❌ | `fn` not recognized. Must translate compound keys. |
| `pyperclip` | ✅ | Cross-platform. Linux needs `xclip` or `xsel` installed. |

---

## Step 2: Plan Comparison & Merged Strategy

### 2.1 Difference Analysis

| Aspect | My Plan (A) | Other Plan (B) | Verdict → Merged |
|--------|-------------|----------------|------------------|
| **Architecture pattern** | Registry + flat functions in `platform_ops.py` | Strategy pattern with `SystemExecutor` ABC | **B is better.** ABC makes the contract explicit, easier to test/mock, and naturally extends to WSL2. Adopted. |
| **Key remapping** | Separate `platform_keys.py` with compound key support (`fn+left` → `home`) | Mapping dict at top of `server.py`, modifier-only translation | **A is better.** Compound key handling is critical (verified: `fn` is not a valid key on Win/Linux). Separate module is cleaner and testable. B missed the `fn` issue entirely. Adopted from A. |
| **WSL2 edge case** | Not mentioned | Detect WSL2 via `/proc/version` containing "microsoft", route through `powershell.exe` | **B adds genuine value.** If server runs in WSL2, `sys.platform == 'linux'` but the desktop is Windows. Adopted from B. |
| **slots.json structure** | Separate sections (`apps_win32`, `apps_linux`), merged at load time | Nested per-entry dicts: `"presentation": {"darwin":"Keynote","win32":"powerpnt"}` | **B is cleaner.** Single-key lookup, no merge logic, `slot_app()` just indexes by platform. Adopted from B. |
| **Windows app launching** | `subprocess.Popen(["cmd","/c","start","",app])` | PowerShell `Start-Process` via subprocess | **Mixed.** PowerShell handles UWP apps and edge cases better, but spawning PowerShell adds ~200ms. Use `os.startfile` for URLs (fast), PowerShell `Start-Process` for named apps as fallback. |
| **Windows frontmost app** | `ctypes.windll.user32.GetForegroundWindow()` + `GetWindowTextW` (returns window title) | `Get-Process \| Where-Object {$_.MainWindowTitle}` | **A is faster** (no subprocess spawn) but returns window *title*, not process name. **Improved**: use ctypes to get foreground window PID → process name via `psapi.GetModuleFileNameExW`. Zero external deps, fast, gives actual app name. |
| **CV2 Windows camera** | Not mentioned | Use `cv2.CAP_DSHOW` for lower latency on Windows | **B adds value.** Verified: DirectShow gives faster single-camera startup on Windows. Adopted. |
| **Flutter motion** | Platform channel with `EventChannel('com.handsfree/motion')` | Platform channel with `FlutterMethodChannel('handsfree/motion')` | **Both agree.** Use `EventChannel` (streaming) not `MethodChannel` (request/response) since motion is a continuous stream. EventChannel is correct for this. |
| **Flutter tap detection** | `sensors_plus` `userAccelerometerEventStream()` | Not specified | **A is more specific.** `sensors_plus` gives exactly `userAcceleration` (gravity-subtracted). Adopted. |
| **Testing note** | "Test on Android emulator" | "Simulators won't provide gyroscope/sensor fusion — use physical device" | **B is correct.** Simulators don't have real gyros. Physical device required for motion testing. Adopted. |
| **`on_action` gesture callback** | Explicitly identified hardcoded `"command"` hotkeys in the callback | Not mentioned separately (implied by key modifier translation) | **A is more explicit.** The `on_action` callback at L416-448 has 3 hardcoded `"command"` references that must go through `remap_key`. Kept explicit in plan. |
| **`system_prompt.txt`** | Identified macOS-specific language, proposed changes | Not mentioned | **A catches more.** Kept. |
| **`pyperclip` Linux dep** | Noted `xclip`/`xsel` requirement | Not mentioned | **A catches more.** Kept. |
| **`compose_email` in executor** | Email compose handled by URL-based approach | `compose_email()` as abstract method on executor | **B adds structure.** Gmail compose via active browser is a platform-specific operation (browser detection varies). Making it an executor method is cleaner. Adopted. |
| **File naming** | `platform_keys.py` + `platform_ops.py` | `executor.py` | **Merged**: `executor.py` for the Strategy class, `platform_keys.py` stays separate (orthogonal concern). |

---

### 2.2 Merged Architecture

#### A. Python Backend

```
server/
├── executor.py          # [NEW] SystemExecutor ABC + Mac/Win/Linux/WSL implementations
├── platform_keys.py     # [NEW] Modifier key remapping + compound key translation
├── primitives.py        # [MODIFY] Use remap_key, guard AppleScript
├── server.py            # [MODIFY] Use executor + remap_keys throughout
├── nlu.py               # [MODIFY] slot_app() reads platform-keyed nested dict
├── gestures.py          # [MODIFY] cv2.CAP_DSHOW on Windows
├── requirements.txt     # [NO CHANGE] All deps already cross-platform
```

---

##### A.1 — `executor.py`: Strategy Pattern with Platform Implementations

```python
# server/executor.py
import sys, os, subprocess, shlex
from abc import ABC, abstractmethod
from typing import Optional

def detect_platform() -> str:
    """Detect the actual target platform, including WSL2."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    # Linux — but check for WSL2
    try:
        with open("/proc/version", "r") as f:
            if "microsoft" in f.read().lower():
                return "wsl2"
    except (FileNotFoundError, PermissionError):
        pass
    return "linux"

PLATFORM = detect_platform()

class SystemExecutor(ABC):
    """Abstract base class defining the OS-specific operations contract."""

    @abstractmethod
    def open_app(self, app_name: str) -> int:
        """Launch an application by display name. Returns 0 on success."""
        ...

    @abstractmethod
    def open_url(self, url: str, browser: str = None) -> str:
        """Open URL, optionally in a specific browser. Returns status string."""
        ...

    @abstractmethod
    def get_frontmost_app(self) -> str:
        """Return the name of the foreground application."""
        ...

    @abstractmethod
    def start_presentation(self) -> None:
        """Start a slideshow in the platform's presentation app."""
        ...

    @abstractmethod
    def compose_email(self, to: str, subject: str, body: str, send: bool) -> str:
        """Open email compose (Gmail web preferred), optionally send."""
        ...


class MacExecutor(SystemExecutor):
    """macOS: AppleScript + 'open' command."""

    def _run_applescript(self, script: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if proc.returncode != 0:
                print("AppleScript error:", proc.stderr.strip())
            return (proc.stdout or "").strip()
        except Exception as e:
            print("AppleScript exception:", e)
            return None

    def open_app(self, app_name: str) -> int:
        # Existing AppleScript logic from server.py open_mac_app()
        app = app_name.strip()
        if not app:
            return 1
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
        rc = self._run_applescript(script)
        if str(rc).strip() == "0":
            return 0
        # Fallback: open -a
        try:
            subprocess.check_call(f"open -a {shlex.quote(app)}", shell=True)
            return 0
        except Exception:
            return 1

    def open_url(self, url: str, browser: str = None) -> str:
        # Existing AppleScript tab API for Safari/Chrome family
        # Falls back to 'open' command
        if browser:
            try:
                subprocess.check_call(
                    f"open -a {shlex.quote(browser)} {shlex.quote(url)}", shell=True)
                return f"opened_url_{browser.lower().replace(' ', '_')}"
            except Exception:
                pass
        try:
            subprocess.check_call(["open", url])
            return "opened_url_default"
        except Exception:
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        script = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
        end tell
        return frontApp
        '''
        try:
            return str(self._run_applescript(script)).strip()
        except Exception:
            return ""

    def start_presentation(self) -> None:
        script = '''
        tell application "Keynote"
            activate
            if (count of documents) = 0 then
                if (count of recent documents) > 0 then
                    open item 1 of recent documents
                else
                    return "no_recent"
                end if
            end if
            delay 0.4
            start document 1
        end tell
        '''
        self._run_applescript(script)

    def compose_email(self, to, subject, body, send=False) -> str:
        from urllib.parse import urlencode
        params = {"view":"cm","fs":"1","to":to or "","su":subject or "","body":body or ""}
        url = "https://mail.google.com/mail/?" + urlencode(params)
        self.open_url(url)
        import time; time.sleep(0.8)
        if send:
            import pyautogui
            pyautogui.hotkey("command", "enter")
        return "gmail_compose_opened"


class WinExecutor(SystemExecutor):
    """Windows: os.startfile, PowerShell Start-Process, ctypes for foreground."""

    def open_app(self, app_name: str) -> int:
        app = app_name.strip()
        if not app:
            return 1
        # Try os.startfile first (works for registered apps)
        try:
            os.startfile(app)
            return 0
        except OSError:
            pass
        # Fallback: PowerShell Start-Process (finds PATH + UWP apps)
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 f'Start-Process "{app}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return 0
        except Exception as e:
            print(f"open_app_windows error: {e}")
            return 1

    def open_url(self, url: str, browser: str = None) -> str:
        # os.startfile handles default browser association efficiently
        try:
            os.startfile(url)
            return "opened_url_default"
        except Exception as e:
            print(f"open_url_windows error: {e}")
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        """Get foreground app process name via Win32 API (no subprocess overhead)."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi

            hwnd = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if handle:
                buf = (ctypes.c_wchar * 260)()
                psapi.GetModuleFileNameExW(handle, None, buf, 260)
                kernel32.CloseHandle(handle)
                return os.path.basename(buf.value)  # e.g., "chrome.exe"
            return ""
        except Exception:
            return ""

    def start_presentation(self) -> None:
        import pyautogui
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 'Start-Process "POWERPNT.EXE"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            import time; time.sleep(2.0)
            pyautogui.press("f5")
        except Exception as e:
            print(f"start_presentation windows error: {e}")

    def compose_email(self, to, subject, body, send=False) -> str:
        from urllib.parse import urlencode
        params = {"view":"cm","fs":"1","to":to or "","su":subject or "","body":body or ""}
        url = "https://mail.google.com/mail/?" + urlencode(params)
        self.open_url(url)
        import time; time.sleep(0.8)
        if send:
            import pyautogui
            pyautogui.hotkey("ctrl", "enter")
        return "gmail_compose_opened"


class WSLExecutor(WinExecutor):
    """WSL2: Inherits WinExecutor but routes commands through the Windows host."""

    def open_app(self, app_name: str) -> int:
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command",
                 f'Start-Process "{app_name}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return 0
        except Exception as e:
            print(f"open_app_wsl error: {e}")
            return 1

    def open_url(self, url: str, browser: str = None) -> str:
        try:
            subprocess.check_call(["powershell.exe", "-NoProfile", "-Command",
                                   f'Start-Process "{url}"'])
            return "opened_url_default"
        except Exception:
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        # ctypes not available in WSL2 — use PowerShell
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | "
                 "Sort-Object -Property CPU -Descending | Select-Object -First 1).ProcessName"],
                capture_output=True, text=True, timeout=3
            )
            return result.stdout.strip()
        except Exception:
            return ""


class LinuxExecutor(SystemExecutor):
    """Linux: xdg-open, gtk-launch, xdotool."""

    def open_app(self, app_name: str) -> int:
        name_lower = app_name.lower().replace(" ", "-")
        for cmd in [name_lower, app_name]:
            try:
                subprocess.Popen([cmd], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return 0
            except FileNotFoundError:
                continue
        # Try gtk-launch for .desktop entries
        try:
            subprocess.check_call(["gtk-launch", name_lower])
            return 0
        except Exception:
            return 1

    def open_url(self, url: str, browser: str = None) -> str:
        try:
            subprocess.check_call(["xdg-open", url])
            return "opened_url_default"
        except Exception:
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=2
            )
            pid = int(result.stdout.strip())
            proc_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=2
            )
            return proc_result.stdout.strip()
        except Exception:
            return ""

    def start_presentation(self) -> None:
        import pyautogui
        try:
            subprocess.Popen(["libreoffice", "--impress"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time; time.sleep(2.0)
            pyautogui.press("f5")
        except Exception as e:
            print(f"start_presentation linux error: {e}")

    def compose_email(self, to, subject, body, send=False) -> str:
        from urllib.parse import urlencode
        params = {"view":"cm","fs":"1","to":to or "","su":subject or "","body":body or ""}
        url = "https://mail.google.com/mail/?" + urlencode(params)
        self.open_url(url)
        import time; time.sleep(0.8)
        if send:
            import pyautogui
            pyautogui.hotkey("ctrl", "enter")
        return "gmail_compose_opened"


def create_executor() -> SystemExecutor:
    """Factory: return the correct executor for the current platform."""
    if PLATFORM == "darwin":
        return MacExecutor()
    elif PLATFORM == "win32":
        return WinExecutor()
    elif PLATFORM == "wsl2":
        return WSLExecutor()
    else:
        return LinuxExecutor()
```

---

##### A.2 — `platform_keys.py`: Modifier Remapping + Compound Key Translation

```python
# server/platform_keys.py
from executor import PLATFORM

# Map macOS modifier names → pyautogui key names per platform.
# "command" on macOS → "ctrl" on Win/Linux (for copy/paste/etc.)
# NOTE: "command" → "ctrl" is correct for SHORTCUTS (Cmd+C = Ctrl+C).
#       App switcher is special: macOS Cmd+Tab = Win/Linux Alt+Tab.
#       That case is handled explicitly in server.py, not here.
_MOD_MAP = {
    "darwin": {"command": "command", "option": "option", "control": "control", "fn": "fn"},
    "win32":  {"command": "ctrl",    "option": "alt",    "control": "ctrl",    "fn": None},
    "wsl2":   {"command": "ctrl",    "option": "alt",    "control": "ctrl",    "fn": None},
    "linux":  {"command": "ctrl",    "option": "alt",    "control": "ctrl",    "fn": None},
}

# Compound key translations: sequences that don't map 1:1 across platforms.
# macOS Fn+Arrow = Home/End/PgUp/PgDn on Windows/Linux.
_COMPOUND_MAP = {
    "win32": {
        ("fn", "left"):  ["home"],
        ("fn", "right"): ["end"],
        ("fn", "up"):    ["pageup"],
        ("fn", "down"):  ["pagedown"],
    },
    "wsl2": {
        ("fn", "left"):  ["home"],
        ("fn", "right"): ["end"],
        ("fn", "up"):    ["pageup"],
        ("fn", "down"):  ["pagedown"],
    },
    "linux": {
        ("fn", "left"):  ["home"],
        ("fn", "right"): ["end"],
        ("fn", "up"):    ["pageup"],
        ("fn", "down"):  ["pagedown"],
    },
}

def remap_key(key: str) -> str | None:
    """Map a single macOS-centric key name to the current platform's equivalent.
    Returns None if the key has no equivalent (e.g., 'fn' on Windows)."""
    mapping = _MOD_MAP.get(PLATFORM, _MOD_MAP["linux"])
    return mapping.get(key, key)  # pass through non-modifier keys unchanged

def remap_keys(keys: list[str]) -> list[str]:
    """Remap a list of keys (as from keymap.json) for the current platform.
    Handles compound translations (fn+arrow → home/end/pgup/pgdn)."""
    compounds = _COMPOUND_MAP.get(PLATFORM, {})
    key_tuple = tuple(keys)
    if key_tuple in compounds:
        return compounds[key_tuple]
    return [mapped for k in keys if (mapped := remap_key(k)) is not None]

# App-switcher modifier: Cmd on macOS, Alt on Windows/Linux.
# This is different from the copy/paste "command"→"ctrl" mapping.
_APP_SWITCH_MOD = {
    "darwin": "command",
    "win32":  "alt",
    "wsl2":   "alt",
    "linux":  "alt",
}

def app_switch_modifier() -> str:
    """Return the correct modifier for app switching (⌘ on Mac, Alt on Win/Linux)."""
    return _APP_SWITCH_MOD.get(PLATFORM, "alt")
```

> [!IMPORTANT]
> **keymap.json stays as-is** (macOS key names). Remapping happens at runtime. This avoids breaking the existing macOS path and avoids maintaining multiple keymaps.

---

##### A.3 — Changes to existing files

#### [MODIFY] [server.py](file:///c:/code/GitPublic/handsfree-office-v2/server/server.py)

Key changes:
1. Import `executor.create_executor()` and `platform_keys.remap_key/remap_keys/app_switch_modifier`
2. Create global `EXEC = create_executor()` at module level
3. **All browser helper functions** (L56-96): replace `"command"` with `remap_key("command")`
4. **`apply_plan()`** (L537-538): wrap `plan["keys"]` through `remap_keys()` before passing to `pyautogui.hotkey()`
5. **`apply_plan()` applescript types**: route `"applescript_open_app"` → `EXEC.open_app()`, `"applescript_open_url"` → `EXEC.open_url()`, `"applescript_keynote_start"` → `EXEC.start_presentation()`
6. **`on_action()` callback** (L416-448): use `remap_key("command")` for zoom/history hotkeys, `app_switch_modifier()` for app switcher `keyDown`/`keyUp`
7. **`execute_intent()`** (L594): `pyautogui.hotkey("command", "enter")` → `pyautogui.hotkey(remap_key("command"), "enter")`
8. **`gmail_compose_in_active_browser()`** (L288): same modifier remap
9. Replace all `open_mac_app()`, `get_frontmost_app_name()`, `open_url_in_*()` calls with `EXEC.*` methods

#### [MODIFY] [primitives.py](file:///c:/code/GitPublic/handsfree-office-v2/server/primitives.py)

1. `focused_typing()`: `pyautogui.hotkey("command", "v")` → `pyautogui.hotkey(remap_key("command"), "v")`
2. `run_applescript()`: Add platform guard — return `None` if not `darwin`
3. `open_gmail_compose()`: Deprecate (replaced by `EXEC.compose_email()`)
4. `start_keynote_slideshow()`: Deprecate (replaced by `EXEC.start_presentation()`)

#### [MODIFY] [gestures.py](file:///c:/code/GitPublic/handsfree-office-v2/server/gestures.py)

Single change at L127:
```python
# Before:
cap = cv2.VideoCapture(0)
# After:
import sys
if sys.platform == "win32":
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
else:
    cap = cv2.VideoCapture(0)
```

#### [MODIFY] [nlu.py](file:///c:/code/GitPublic/handsfree-office-v2/server/nlu.py)

`slot_app()` updated to read platform-keyed nested dicts:
```python
from executor import PLATFORM

def slot_app(name: str) -> str:
    n = (name or "").lower().strip()
    entry = SLOTS.get("apps", {}).get(n)
    if entry is None:
        return name
    if isinstance(entry, dict):
        return entry.get(PLATFORM, entry.get("default", name))
    return entry  # backward compat with flat strings
```

#### [MODIFY] [slots.json](file:///c:/code/GitPublic/handsfree-office-v2/config/slots.json)

Convert to nested per-platform format:
```json
{
  "apps": {
    "keynote":      {"darwin": "Keynote", "win32": "POWERPNT.EXE", "linux": "libreoffice --impress", "default": "Keynote"},
    "presentation": {"darwin": "Keynote", "win32": "POWERPNT.EXE", "linux": "libreoffice --impress", "default": "Keynote"},
    "chrome":       "Google Chrome",
    "safari":       {"darwin": "Safari", "default": "Google Chrome"},
    "...": "remaining entries stay flat strings if identical across platforms"
  },
  "sites": { "...unchanged..." }
}
```

#### [MODIFY] [system_prompt.txt](file:///c:/code/GitPublic/handsfree-office-v2/config/system_prompt.txt)

- `"on macOS"` → `"on the user's computer"`
- `"<macOS display name>"` → `"<application display name>"`

---

#### B. Flutter Client Architecture

```
flutter_client/
├── lib/
│   ├── main.dart
│   ├── screens/
│   │   └── home_screen.dart
│   ├── services/
│   │   ├── websocket_service.dart      # Connection, reconnect (0.5s→6s backoff), ping
│   │   ├── speech_service.dart         # speech_to_text + partial debounce (1.3s)
│   │   ├── motion_service.dart         # EventChannel for platform-fused attitude
│   │   └── tap_service.dart            # sensors_plus userAccelerometerEventStream
│   └── models/
│       └── messages.dart               # JSON payloads matching server protocol
├── android/
│   └── app/src/main/kotlin/.../MotionPlugin.kt
│       # SensorManager.TYPE_ROTATION_VECTOR → getRotationMatrixFromVector
│       # → getOrientation → extract roll/pitch → convert to degrees
│       # + TYPE_LINEAR_ACCELERATION for tap
├── ios/
│   └── Runner/MotionPlugin.swift
│       # CMMotionManager.startDeviceMotionUpdates(using: .xArbitraryZVertical)
│       # → attitude.roll/pitch → degrees (with pitch inversion)
│       # + userAcceleration for tap
└── pubspec.yaml
```

**Flutter dependencies:**

| Package | Version | Purpose |
|---------|---------|---------|
| `web_socket_channel` | `^3.0.0` | WebSocket transport |
| `speech_to_text` | `^7.0.0` | Voice commands with partial results |
| `sensors_plus` | `^6.0.0` | Tap detection (`userAccelerometerEventStream`) |
| `permission_handler` | `^11.0.0` | Mic, motion permissions |

**Platform channel contract** (`EventChannel('com.handsfree/motion')`):

```dart
// Stream emits map per frame (~60Hz):
// { "roll_deg": double, "pitch_deg": double, "dt": double }
//
// Android: TYPE_ROTATION_VECTOR → quaternion → euler → degrees
//          Axes mapped to match iOS .xArbitraryZVertical output:
//          - roll > 0 = right tilt
//          - pitch > 0 = forward tilt (cursor down)
//
// iOS: CMDeviceMotion.attitude.roll/pitch with pitch inverted
```

> [!WARNING]
> **Physical devices required for motion testing.** Emulators/simulators do not provide real gyroscope or sensor fusion hardware. The motion path MUST be tested on physical iOS and Android devices.

---

## Phased Execution Plan

### Phase 1: Python Backend OS Abstraction
*Test with existing iOS client or `test_client.py` before building Flutter.*

1. Create `server/executor.py` — `SystemExecutor` ABC + `Mac/Win/WSL/Linux` implementations + `detect_platform()`
2. Create `server/platform_keys.py` — modifier remapping + compound key translation + `app_switch_modifier()`
3. Refactor `server/primitives.py` — use `remap_key`, guard `run_applescript`, deprecate macOS-only functions
4. Refactor `server/server.py` — use `EXEC.*` for all platform ops, `remap_keys()` in `apply_plan`, `on_action`, and all browser helpers
5. Update `config/slots.json` — nested per-platform app names
6. Update `config/system_prompt.txt` — platform-neutral language
7. Update `server/nlu.py` — `slot_app()` reads nested dicts
8. Update `server/gestures.py` — `cv2.CAP_DSHOW` on Windows
9. **Verify**: Run server on Windows, test all commands via `test_client.py`

### Phase 2: Flutter Client — Platform Channels & Core
1. Initialize Flutter project, add dependencies
2. Build iOS `MotionPlugin.swift` — port `CMMotionManager` from existing `MotionSpeechStreamer.swift`
3. Build Android `MotionPlugin.kt` — `TYPE_ROTATION_VECTOR` → euler → degrees, axis-mapped to match iOS
4. Build `WebSocketService` — connection lifecycle, reconnect backoff, ping
5. Build `SpeechService` — `speech_to_text` with partial debounce (1.3s)
6. Build `TapService` — `sensors_plus` `userAccelerometerEventStream`, 1.10g threshold, 0.25s cooldown
7. Build `MotionService` — `EventChannel` consumer, 60Hz throttle, send `tilt_angles` JSON

### Phase 3: Flutter UI
1. Build `HomeScreen` — port `ContentView.swift` to Flutter `Scaffold`
2. Buttons: Start/Stop listening, Start/Stop motion, Toggle hand gestures
3. Status indicators: connection, motion active, gestures active
4. Server IP configuration field (currently hardcoded in Swift)

### Phase 4: Integration & Validation
1. End-to-end: Flutter → WebSocket → Python server → OS actions on **Windows**
2. Verify cursor latency matches 60Hz update rate on **physical device**
3. Verify speech → NLU → hotkey pipeline on all platforms
4. Verify camera gestures with `cv2.CAP_DSHOW` on Windows

---

## Open Questions

> [!IMPORTANT]
> **Q1: Browser control depth on Windows/Linux.**
> macOS uses AppleScript to open specific URLs in specific browser tabs (Chrome family tab API, Safari tab API). On Windows/Linux, no equivalent clean API exists without browser extensions. The merged plan uses `os.startfile(url)` / `xdg-open` which opens in the **default** browser only. Is default-browser-open acceptable, or do you need per-browser tab control on Win/Linux?

> [!IMPORTANT]
> **Q2: Presentation app scope.**
> macOS targets Keynote. The plan maps Windows → PowerPoint and Linux → LibreOffice Impress. Should we also support Google Slides (web-based, cross-platform)? The "start slideshow" logic differs significantly per app.

> [!WARNING]
> **Q3: Existing Flutter project state.**
> `flutter_client/build/` has cached artifacts for `sensors_plus`, `speech_to_text`, `permission_handler_android`, `camera_android_camerax`. Should I build on any existing Flutter scaffold, or create fresh?

> [!IMPORTANT]
> **Q4: Ollama dependency.**
> The NLU fallback calls a local Ollama instance (`http://127.0.0.1:11434`). Should cross-platform support assume Ollama is installed everywhere, or add a cloud LLM fallback (e.g., OpenAI API)?

> [!IMPORTANT]
> **Q5: WSL2 — pyautogui considerations.**
> If the server runs in WSL2, `pyautogui` needs access to the Windows display (X11 forwarding via WSLg or similar). The executor routes app/URL commands through `powershell.exe`, but hotkey simulation (`pyautogui.hotkey("ctrl", "c")`) still needs a display server. Should WSL2 be a first-class target, or a best-effort/documented-limitation?

## Verification Plan

### Automated Tests
- `python -m pytest tests/test_platform_keys.py` — verify key remapping for all 4 platforms (darwin/win32/wsl2/linux) using mocked `PLATFORM`
- `python -m pytest tests/test_executor.py` — verify executor factory returns correct class per platform
- `python scripts/test_client.py` — end-to-end command flow on Windows

### Manual Verification
- Run Python server on Windows, send all test commands, verify hotkeys execute correctly
- Run Flutter app on **physical** iOS and Android devices — verify motion, speech, tap
- Verify gesture camera toggle cross-platform
- Verify `cv2.CAP_DSHOW` camera startup on Windows
