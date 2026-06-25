# server/executor.py
"""
Platform executor — Strategy pattern abstracting every OS-specific operation
behind a single contract (PRD §8.1).

`create_executor()` returns the right concrete executor for the host OS. All
OS-touching code in the server goes through `EXEC.*` so the rest of the
codebase stays platform-neutral.

Design notes:
- `detect_platform()` is read *live* (not cached into other modules) so tests
  can monkeypatch `executor.detect_platform` without import-order surprises
  (PRD §8.5).
- WSL2 is detected but mapped to "linux" (best-effort, non-goal — PRD §10 L-4).
- D1: browser hotkeys act on whatever is frontmost; `frontmost_is_browser()` /
  `open_default_browser()` implement the uniform OS-neutral rule.
- D2: `start_presentation()` uses Google Slides as the cross-platform path.
"""
import os
import sys
import shlex
import subprocess
from abc import ABC, abstractmethod
from urllib.parse import urlencode

# --- shared constants --------------------------------------------------------

# Tokens matched (case-insensitively, substring) against the frontmost app name
# to decide whether the focused app is a browser (PRD §8.1, D1).
BROWSER_TOKENS = frozenset({
    "safari", "chrome", "chromium", "edge", "msedge", "brave",
    "firefox", "vivaldi", "arc", "opera",
})

# D2 — Google Slides is the primary, OS-neutral presentation path.
GOOGLE_SLIDES_PRESENT_URL = "https://docs.google.com/presentation/u/0/"

# D1 — when no browser is focused, "new tab" opens the default browser to a
# fresh page. A real URL is used because `about:blank` is unreliable through
# `open` / `os.startfile` / `xdg-open`.
NEW_TAB_URL = "https://www.google.com"


def detect_platform() -> str:
    """Return "darwin" | "win32" | "linux" for the host OS.

    WSL2 is detected (sys.platform == "linux" but running under the Windows
    kernel) and reported as "linux" — best-effort, not a first-class target.
    """
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    return "linux"


def is_wsl() -> bool:
    """True if running inside WSL2 (Windows Subsystem for Linux)."""
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError, OSError):
        return False


def gmail_compose_url(to: str = "", subject: str = "", body: str = "") -> str:
    """Build a Gmail web compose URL. Identical across platforms (PRD §8.1)."""
    params = {
        "view": "cm",
        "fs": "1",
        "to": to or "",
        "su": subject or "",
        "body": body or "",
    }
    return "https://mail.google.com/mail/?" + urlencode(params)


# --- contract ----------------------------------------------------------------

class SystemExecutor(ABC):
    """OS-specific operations contract.

    Three operations are genuinely per-platform and abstract:
    `open_app`, `open_url`, `get_frontmost_app`. Everything else is shared
    behaviour expressed in terms of those, plus a per-class modifier constant.
    """

    # Primary command modifier for this platform's *internal* hotkeys
    # (Gmail send, Slides present). macOS overrides to "command".
    SEND_MODIFIER = "ctrl"
    PRESENT_MODIFIER = "ctrl"

    # -- abstract per-platform primitives --
    @abstractmethod
    def open_app(self, app_name: str) -> int:
        """Launch an application by display name / exec name. 0 on success."""
        ...

    @abstractmethod
    def open_url(self, url: str) -> str:
        """Open a URL in the default browser. Returns a status string."""
        ...

    @abstractmethod
    def get_frontmost_app(self) -> str:
        """Return the foreground application's name (form varies per OS)."""
        ...

    # -- shared concrete behaviour --
    def open_default_browser(self) -> str:
        """D1: open the default browser to a fresh tab/window."""
        return self.open_url(NEW_TAB_URL)

    def frontmost_is_browser(self) -> bool:
        """D1: True when the focused app is a known browser."""
        name = (self.get_frontmost_app() or "").lower().strip()
        if name.endswith(".exe"):
            name = name[:-4]
        return any(tok in name for tok in BROWSER_TOKENS)

    def start_presentation(self) -> str:
        """D2: open Google Slides and enter present mode (Ctrl/Cmd+F5)."""
        self.open_url(GOOGLE_SLIDES_PRESENT_URL)
        try:
            import time
            time.sleep(1.2)
            import pyautogui
            pyautogui.hotkey(self.PRESENT_MODIFIER, "f5")
        except Exception as e:
            print("start_presentation hotkey error:", e)
        return "presentation_started"

    def compose_email(self, to: str = "", subject: str = "",
                      body: str = "", send: bool = False) -> str:
        """Open a Gmail web compose window; optionally send (Ctrl/Cmd+Enter)."""
        self.open_url(gmail_compose_url(to, subject, body))
        try:
            import time
            time.sleep(0.8)
        except Exception:
            pass
        if send:
            try:
                import pyautogui
                pyautogui.hotkey(self.SEND_MODIFIER, "enter")
            except Exception as e:
                print("compose_email send error:", e)
                return "gmail_send_failed"
        return "gmail_compose_opened"


# --- macOS -------------------------------------------------------------------

class MacExecutor(SystemExecutor):
    """macOS: AppleScript + the `open` command."""

    SEND_MODIFIER = "command"
    PRESENT_MODIFIER = "command"

    def _run_applescript(self, script: str):
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                check=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            if proc.returncode != 0:
                print("AppleScript error:", proc.stderr.strip())
            return (proc.stdout or "").strip()
        except Exception as e:
            print("AppleScript exception:", e)
            return None

    def open_app(self, app_name: str) -> int:
        app = (app_name or "").strip()
        if not app:
            return 1
        if "." in app:  # looks like a bundle id, e.g. "zoom.us"
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
        rc = self._run_applescript(script)
        if str(rc).strip() == "0":
            return 0
        # Fallback: open -a "App"
        try:
            subprocess.check_call(f"open -a {shlex.quote(app)}", shell=True)
            return 0
        except Exception as e:
            print("open_app error:", e)
            return 1

    def open_url(self, url: str) -> str:
        # D1: open in the default browser (drops the old AppleScript
        # active/preferred-browser tab API — frontmost rule supersedes it).
        try:
            subprocess.check_call(["open", url])
            return "opened_url_default"
        except Exception as e:
            print("open_url error:", e)
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        script = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
        end tell
        return frontApp
        '''
        try:
            return str(self._run_applescript(script) or "").strip()
        except Exception as e:
            print("frontmost app error:", e)
            return ""


# --- Windows -----------------------------------------------------------------

class WinExecutor(SystemExecutor):
    """Windows: os.startfile / PowerShell Start-Process / Win32 ctypes."""

    def open_app(self, app_name: str) -> int:
        app = (app_name or "").strip()
        if not app:
            return 1
        try:
            os.startfile(app)  # type: ignore[attr-defined]
            return 0
        except OSError:
            pass
        except Exception:
            pass
        # Fallback: PowerShell Start-Process (resolves PATH + App Paths + UWP).
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", f'Start-Process "{app}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return 0
        except Exception as e:
            print("open_app (win) error:", e)
            return 1

    def open_url(self, url: str) -> str:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return "opened_url_default"
        except Exception as e:
            print("open_url (win) error:", e)
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        """Foreground process name via Win32 API (no subprocess spawn)."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32       # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32   # type: ignore[attr-defined]
            psapi = ctypes.windll.psapi         # type: ignore[attr-defined]

            hwnd = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not handle:
                return ""
            try:
                buf = (ctypes.c_wchar * 260)()
                if psapi.GetModuleFileNameExW(handle, None, buf, 260):
                    return os.path.basename(buf.value)  # e.g. "chrome.exe"
                return ""
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return ""


# --- Linux (X11) -------------------------------------------------------------

class LinuxExecutor(SystemExecutor):
    """Linux/X11: xdg-open / gtk-launch / exec by name; xdotool for frontmost."""

    def open_app(self, app_name: str) -> int:
        app = (app_name or "").strip()
        if not app:
            return 1
        # Try the raw name, then a slug, as a direct executable.
        slug = app.lower().replace(" ", "-")
        for cmd in (app, slug):
            try:
                subprocess.Popen([cmd], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return 0
            except FileNotFoundError:
                continue
            except Exception:
                continue
        # Fallback: gtk-launch against a .desktop id.
        try:
            subprocess.check_call(["gtk-launch", slug])
            return 0
        except Exception as e:
            print("open_app (linux) error:", e)
            return 1

    def open_url(self, url: str) -> str:
        try:
            subprocess.check_call(["xdg-open", url])
            return "opened_url_default"
        except Exception as e:
            print("open_url (linux) error:", e)
            return "open_url_failed"

    def get_frontmost_app(self) -> str:
        try:
            wid = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=2,
            )
            pid = (wid.stdout or "").strip()
            if not pid:
                return ""
            ps = subprocess.run(
                ["ps", "-p", pid, "-o", "comm="],
                capture_output=True, text=True, timeout=2,
            )
            return (ps.stdout or "").strip()
        except Exception:
            return ""


# --- factory -----------------------------------------------------------------

def create_executor() -> SystemExecutor:
    """Return the executor for the host platform (read live for testability)."""
    plat = detect_platform()
    if plat == "darwin":
        return MacExecutor()
    if plat == "win32":
        return WinExecutor()
    return LinuxExecutor()


# Informational constant for logging; prefer detect_platform() in hot paths.
PLATFORM = detect_platform()
