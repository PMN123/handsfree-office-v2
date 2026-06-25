"""Tests for NLU local routing, per-platform slots, and Ollama fail-soft
(PRD §8.6 / §9).

Runnable with pytest OR directly:  python tests/test_nlu.py
"""
import sys
import time
import contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import httpx
import executor
import nlu


@contextlib.contextmanager
def platform(plat):
    orig = executor.detect_platform
    executor.detect_platform = lambda: plat
    try:
        yield
    finally:
        executor.detect_platform = orig


def route(text):
    return nlu.local_route(text)[0]


def test_local_cascade_resolves_d2_present():
    # D2 — "present" / "start presentation" reach Google Slides locally.
    assert route("present") == "start_presentation"
    assert route("start presentation") == "start_presentation"
    assert route("open presentation") == "start_presentation"
    assert route("google slides") == "start_presentation"


def test_local_cascade_resolves_d1_new_tab():
    # D1 — new tab phrasings resolve locally (not shadowed by open_app/open_url).
    assert route("new tab") == "new_tab"
    assert route("open a tab") == "new_tab"
    assert route("open a new tab") == "new_tab"


def test_local_cascade_resolves_d4_close_distinct():
    # D4 — close_tab and close_window are distinct intents.
    assert route("close tab") == "close_tab"
    assert route("close window") == "close_window"


def test_named_browser_open_resolves_locally():
    # D1 — named-browser opens resolve locally (open_url app-guess or open_app),
    # never falling through to the LLM.
    for phrase in ("open edge", "open brave", "launch brave", "start arc",
                   "open vivaldi", "open chrome", "open safari"):
        intent, slots, how = nlu.local_route(phrase)
        assert intent in ("open_url", "open_app"), f"{phrase} -> {intent}"
        assert how != "none"


def test_slot_app_per_platform():
    with platform("darwin"):
        assert nlu.slot_app("keynote") == "Keynote"
        assert nlu.slot_app("edge") == "Microsoft Edge"
        assert nlu.slot_app("safari") == "Safari"
        assert nlu.slot_app("vscode") == "Visual Studio Code"
    with platform("win32"):
        assert nlu.slot_app("keynote") == "POWERPNT.EXE"
        assert nlu.slot_app("edge") == "msedge"
        assert nlu.slot_app("safari") == "Google Chrome"   # default fallback
        assert nlu.slot_app("slack") == "Slack"            # flat string
    with platform("linux"):
        assert nlu.slot_app("keynote") == "libreoffice"
        assert nlu.slot_app("vscode") == "code"
        assert nlu.slot_app("brave") == "brave-browser"
    # Unknown app echoes the input unchanged.
    assert nlu.slot_app("totallynotanapp") == "totallynotanapp"


def test_ollama_unavailable_fails_fast_without_throwing_or_stalling():
    """A refused connection must raise OllamaUnavailable on the FIRST attempt
    (no 3x retry stall) and never bubble a raw httpx error (PRD §8.6)."""
    attempts = {"n": 0}

    class _DeadClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            attempts["n"] += 1
            raise httpx.ConnectError("connection refused")

    orig = httpx.Client
    httpx.Client = _DeadClient
    try:
        t0 = time.monotonic()
        raised = None
        try:
            nlu.ollama_route("some never-before-seen phrase")
        except nlu.OllamaUnavailable as e:
            raised = e
        except Exception as e:  # pragma: no cover - would be a failure
            raised = e
        dt = time.monotonic() - t0
    finally:
        httpx.Client = orig

    assert isinstance(raised, nlu.OllamaUnavailable), f"got {raised!r}"
    assert attempts["n"] == 1, f"expected 1 attempt (no retry), got {attempts['n']}"
    assert dt < 1.0, f"should fail fast, took {dt:.2f}s"


def test_default_ollama_model_is_qwen():
    # D3 — default model changed to qwen2.5:3b-instruct.
    assert nlu.OLLAMA_MODEL == "qwen2.5:3b-instruct"


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
