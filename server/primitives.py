# server/primitives.py
import time
import subprocess
import pyautogui
import pyperclip
from urllib.parse import quote
from typing import Optional

import executor
from platform_keys import primary_modifier

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

def run_applescript(script: str) -> Optional[str]:
    """
    Execute the given AppleScript and return stdout as a string (stripped).
    Returns None on failure. Errors are printed for debugging but do not raise.

    No-ops (returns None) off macOS — AppleScript / osascript exist only there.
    """
    if executor.detect_platform() != "darwin":
        return None
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if proc.returncode != 0:
            # Surface AppleScript failures without crashing the server.
            print("AppleScript error:", proc.stderr.strip())
        return (proc.stdout or "").strip()
    except Exception as e:
        print("AppleScript exception:", e)
        return None

def focused_typing(text: str):
    if not text:
        return
    pyperclip.copy(text)
    # Paste via the platform's primary modifier (Cmd on macOS, Ctrl elsewhere).
    pyautogui.hotkey(primary_modifier(), "v")

def open_gmail_compose():
    # SUPERSEDED by executor.SystemExecutor.compose_email() (cross-platform,
    # Gmail-web compose). Kept for reference; macOS-only (run_applescript
    # no-ops off macOS).
    script = """
    tell application "Google Chrome"
        activate
        if (count of windows) = 0 then make new window
        set newTab to make new tab at end of tabs of front window
        set URL of newTab to "https://mail.google.com/mail/u/0/#inbox?compose=new"
    end tell
    """
    run_applescript(script)
    time.sleep(1.0)
    try: pyautogui.press("c")  # Gmail compose fallback
    except: pass

def start_keynote_slideshow():
    # SUPERSEDED by executor.SystemExecutor.start_presentation() (D2: Google
    # Slides as the cross-platform path). Kept for reference; macOS-only.
    script = """
    tell application "Keynote"
        activate
        if (count of documents) = 0 then
            if (count of recent documents) > 0 then
                set recentDoc to item 1 of recent documents
                open recentDoc
            else
                return "no_recent"
            end if
        end if
        delay 0.4
        start document 1
    end tell
    """
    run_applescript(script)

def mailto_url(to_addr: str, subject: str = "", body: str = "") -> str:
    to = to_addr.strip()
    qs = []
    if subject: qs.append("subject=" + quote(subject))
    if body:    qs.append("body=" + quote(body))
    tail = ("?" + "&".join(qs)) if qs else ""
    return f"mailto:{to}{tail}"
