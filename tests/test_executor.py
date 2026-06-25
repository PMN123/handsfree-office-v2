"""Tests for the platform executor (PRD §8.1 / §9).

Runnable with pytest OR directly:  python tests/test_executor.py
"""
import sys
import contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import executor
from executor import (
    MacExecutor, WinExecutor, LinuxExecutor, create_executor,
    gmail_compose_url, GOOGLE_SLIDES_PRESENT_URL, NEW_TAB_URL,
)


@contextlib.contextmanager
def platform(plat):
    orig = executor.detect_platform
    executor.detect_platform = lambda: plat
    try:
        yield
    finally:
        executor.detect_platform = orig


@contextlib.contextmanager
def stub_io():
    """Stub time.sleep and pyautogui.hotkey so executor methods don't block or
    actually press keys. Returns a dict that records the hotkey call."""
    import time
    import pyautogui
    rec = {}
    o_sleep, o_hotkey = time.sleep, pyautogui.hotkey
    time.sleep = lambda *a, **k: None
    pyautogui.hotkey = lambda *keys: rec.__setitem__("hotkey", list(keys))
    try:
        yield rec
    finally:
        time.sleep, pyautogui.hotkey = o_sleep, o_hotkey


def test_factory_returns_correct_class():
    with platform("darwin"):
        assert isinstance(create_executor(), MacExecutor)
    with platform("win32"):
        assert isinstance(create_executor(), WinExecutor)
    with platform("linux"):
        assert isinstance(create_executor(), LinuxExecutor)


def test_gmail_compose_url_is_correct():
    url = gmail_compose_url("a@b.com", "Hello", "Body & more")
    assert url.startswith("https://mail.google.com/mail/?")
    assert "view=cm" in url
    assert "fs=1" in url
    assert "to=a%40b.com" in url
    assert "su=Hello" in url
    # The '&' in the body must be percent-encoded, not break the query string.
    assert "Body" in url and "%26" in url and "&body" not in url.split("body=")[1]


def test_per_class_modifiers():
    assert MacExecutor.SEND_MODIFIER == "command"
    assert MacExecutor.PRESENT_MODIFIER == "command"
    assert WinExecutor.SEND_MODIFIER == "ctrl"
    assert WinExecutor.PRESENT_MODIFIER == "ctrl"
    assert LinuxExecutor.SEND_MODIFIER == "ctrl"
    assert LinuxExecutor.PRESENT_MODIFIER == "ctrl"


def test_frontmost_is_browser_matches_browsers_set():
    ex = MacExecutor()
    cases = {
        "Google Chrome": True, "Safari": True, "Microsoft Edge": True,
        "Brave Browser": True, "firefox": True, "Arc": True, "Vivaldi": True,
        "chrome.exe": True, "msedge.exe": True, "firefox.exe": True,
        "Finder": False, "Microsoft PowerPoint": False, "Slack": False,
        "Terminal": False, "Notes": False, "": False,
    }
    for name, expected in cases.items():
        ex.get_frontmost_app = lambda n=name: n
        assert ex.frontmost_is_browser() == expected, f"{name!r} -> {expected}"


def test_start_presentation_builds_google_slides_action():
    for cls, mod in [(MacExecutor, "command"), (WinExecutor, "ctrl"), (LinuxExecutor, "ctrl")]:
        ex = cls()
        opened = []
        ex.open_url = lambda u, _o=opened: (_o.append(u) or "opened_url_default")
        with stub_io() as rec:
            res = ex.start_presentation()
        assert opened == [GOOGLE_SLIDES_PRESENT_URL]
        assert rec.get("hotkey") == [mod, "f5"]
        assert res == "presentation_started"


def test_compose_email_send_hotkey_and_url():
    for cls, mod in [(MacExecutor, "command"), (WinExecutor, "ctrl"), (LinuxExecutor, "ctrl")]:
        ex = cls()
        opened = []
        ex.open_url = lambda u, _o=opened: (_o.append(u) or "opened_url_default")
        with stub_io() as rec:
            res = ex.compose_email("x@y.com", "S", "B", send=True)
        assert opened and opened[0].startswith("https://mail.google.com/mail/?")
        assert rec.get("hotkey") == [mod, "enter"]
        assert res == "gmail_compose_opened"
        # send=False must NOT issue a hotkey.
        opened.clear()
        ex2 = cls()
        ex2.open_url = lambda u, _o=opened: (_o.append(u) or "opened_url_default")
        with stub_io() as rec2:
            ex2.compose_email("x@y.com", "S", "B", send=False)
        assert "hotkey" not in rec2


def test_open_default_browser_opens_fresh_tab_url():
    ex = WinExecutor()
    opened = []
    ex.open_url = lambda u, _o=opened: (_o.append(u) or "opened_url_default")
    ex.open_default_browser()
    assert opened == [NEW_TAB_URL]


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
