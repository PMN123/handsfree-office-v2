"""Tests for the per-intent key-override layer (PRD §8.2 / §9).

Runnable with pytest OR directly:  python tests/test_platform_keys.py
"""
import sys
import json
import contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import executor
import platform_keys as pk

KEYMAP = json.load(open(ROOT / "config" / "keymap.json"))


@contextlib.contextmanager
def platform(plat):
    """Temporarily force the detected platform (read live by platform_keys)."""
    orig = executor.detect_platform
    executor.detect_platform = lambda: plat
    try:
        yield
    finally:
        executor.detect_platform = orig


def remap(intent):
    return pk.remap_intent_keys(intent, KEYMAP[intent].get("keys", []))


def test_darwin_passthrough_and_normalization():
    with platform("darwin"):
        assert remap("copy") == ["command", "c"]
        assert remap("switch_app") == ["command", "tab"]
        assert remap("paste") == ["command", "v"]
        # Latent invalid-key bugs are normalized even on macOS:
        assert remap("zoom_in") == ["command", "="]      # was "plus" (no-op)
        assert remap("zoom_out") == ["command", "-"]      # was "minus"
        assert remap("next_tab") == ["ctrl", "tab"]       # was "control" (no-op)
        assert remap("previous_tab") == ["ctrl", "shift", "tab"]


def test_win32_override_cases():
    with platform("win32"):
        # The explicit §8.2 override cases:
        assert remap("switch_app") == ["alt", "tab"]
        assert remap("word_left") == ["ctrl", "left"]
        assert remap("word_right") == ["ctrl", "right"]
        assert remap("line_start") == ["home"]
        assert remap("line_end") == ["end"]
        assert remap("find_next") == ["f3"]
        assert remap("find_previous") == ["shift", "f3"]
        assert remap("redo") == ["ctrl", "y"]
        assert remap("scroll_top") == ["home"]
        assert remap("scroll_bottom") == ["end"]
        assert remap("minimize_window") == ["win", "down"]
        # D4 — close_tab and close_window diverge:
        assert remap("close_tab") == ["ctrl", "w"]
        assert remap("close_window") == ["alt", "f4"]
        # Simple-swap-correct cases:
        assert remap("copy") == ["ctrl", "c"]
        assert remap("paste") == ["ctrl", "v"]
        assert remap("new_tab") == ["ctrl", "t"]
        assert remap("zoom_in") == ["ctrl", "="]
        assert remap("send_email") == ["ctrl", "enter"]


def test_linux_override_cases():
    with platform("linux"):
        assert remap("switch_app") == ["alt", "tab"]
        assert remap("word_left") == ["ctrl", "left"]
        assert remap("line_start") == ["home"]
        assert remap("find_next") == ["f3"]
        assert remap("close_tab") == ["ctrl", "w"]        # D4
        assert remap("close_window") == ["alt", "f4"]     # D4
        assert remap("minimize_window") == ["win", "h"]
        assert remap("copy") == ["ctrl", "c"]


def test_fn_is_never_emitted_offmac():
    for plat in ("win32", "linux"):
        with platform(plat):
            assert remap("scroll_top") == ["home"]
            assert remap("scroll_bottom") == ["end"]
            for intent, spec in KEYMAP.items():
                if spec.get("type") == "hotkey":
                    assert "fn" not in remap(intent), f"{plat}/{intent} emitted fn"


def test_every_hotkey_emits_only_valid_pyautogui_keys():
    import pyautogui
    valid = set(pyautogui.KEYBOARD_KEYS)
    for plat in ("darwin", "win32", "linux"):
        with platform(plat):
            for intent, spec in KEYMAP.items():
                if spec.get("type") != "hotkey":
                    continue
                out = remap(intent)
                assert out, f"{plat}/{intent} produced no keys"
                for k in out:
                    assert k in valid, f"{plat}/{intent}: {k!r} is not a valid pyautogui key"
                if plat != "darwin":
                    for bad in ("fn", "plus", "minus", "control", "command", "option"):
                        assert bad not in out, f"{plat}/{intent} leaked {bad!r}"


def test_modifier_helpers():
    with platform("darwin"):
        assert pk.app_switch_modifier() == "command"
        assert pk.primary_modifier() == "command"
    for plat in ("win32", "linux"):
        with platform(plat):
            assert pk.app_switch_modifier() == "alt"
            assert pk.primary_modifier() == "ctrl"


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
