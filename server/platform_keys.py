# server/platform_keys.py
"""
Key remapping (PRD §8.2) — CORRECTED per-intent override table.

The original implementation_plan assumed `command→ctrl` was a safe blanket
swap. It is not: many macOS shortcuts map to a *different key* off macOS (not
just a different modifier), and two cases (`switch_app`, `word_left/right`)
would fire a *different action* under a naive swap. So remapping is driven by a
per-intent override table consulted first, with a per-key modifier fallback
only for intents not in the table.

`config/keymap.json` stays the macOS reference; this layer translates it for
the running platform. `detect_platform()` is read live so tests can monkeypatch
`executor.detect_platform` (PRD §8.5).
"""
import executor

# --- key-name normalization (applies on ALL platforms) -----------------------
# These names appear in keymap.json but are NOT valid pyautogui key names, so
# pyautogui silently drops them (a latent no-op bug even on macOS). Normalize
# them to valid names everywhere.
#   "control" -> "ctrl"   (pyautogui's modifier name)
#   "plus"    -> "="      ("plus" is not a key; Cmd/Ctrl + "=" zooms in)
#   "minus"   -> "-"
_ALIASES = {"control": "ctrl", "plus": "=", "minus": "-"}

# --- per-intent override table (PRD §8.2) ------------------------------------
# Win/Linux key lists for intents where a naive modifier swap is WRONG.
# darwin is NOT listed here — it uses keymap.json (after normalization) as-is.
_OVERRIDES_COMMON = {
    "switch_app":    ["alt", "tab"],     # Cmd+Tab; ctrl+tab would switch a TAB
    "word_left":     ["ctrl", "left"],   # Opt+Left; alt+left = browser Back
    "word_right":    ["ctrl", "right"],  # Opt+Right; alt+right = browser Forward
    "line_start":    ["home"],           # Cmd+Left; ctrl+left = word-left
    "line_end":      ["end"],            # Cmd+Right
    "find_next":     ["f3"],             # Cmd+G; ctrl+g = "go to"/no-op
    "find_previous": ["shift", "f3"],    # Cmd+Shift+G
    "redo":          ["ctrl", "y"],      # Cmd+Shift+Z; ctrl+shift+z unreliable
    "scroll_top":    ["home"],           # Fn+Left; fn is invalid off macOS
    "scroll_bottom": ["end"],            # Fn+Right
    "close_tab":     ["ctrl", "w"],      # D4 — distinct from close_window
    "close_window":  ["alt", "f4"],      # D4 — Cmd+W would close a TAB
}

# minimize_window diverges between Win and Linux (WM-specific on Linux).
KEY_OVERRIDES = {
    "win32": {**_OVERRIDES_COMMON, "minimize_window": ["win", "down"]},
    "linux": {**_OVERRIDES_COMMON, "minimize_window": ["win", "h"]},
}

# Off-macOS modifier remap for intents NOT in the override table.
# `fn` has no equivalent off macOS and must never be emitted.
_MODIFIER_MAP = {"command": "ctrl", "option": "alt", "fn": None}


def _platform() -> str:
    return executor.detect_platform()


def _normalize(key: str) -> str:
    return _ALIASES.get(key, key)


def _map_key_offmac(key: str):
    """Map a single macOS key to its Win/Linux equivalent. None = drop it."""
    if key in _MODIFIER_MAP:
        return _MODIFIER_MAP[key]
    return _normalize(key)


def remap_intent_keys(intent: str, keys) -> list:
    """Return the correct pyautogui key list for `intent` on the host platform.

    macOS: keymap.json names (normalized to valid pyautogui names).
    Win/Linux: per-intent override table first, else per-key modifier mapping.
    """
    plat = _platform()
    if plat == "darwin":
        return [_normalize(k) for k in keys]
    overrides = KEY_OVERRIDES.get(plat) or KEY_OVERRIDES["linux"]
    if intent in overrides:
        return list(overrides[intent])
    out = []
    for k in keys:
        mapped = _map_key_offmac(k)
        if mapped is not None:
            out.append(mapped)
    return out


def remap_keys(keys) -> list:
    """Remap a bare key list with no intent context (per-key only)."""
    plat = _platform()
    if plat == "darwin":
        return [_normalize(k) for k in keys]
    out = []
    for k in keys:
        mapped = _map_key_offmac(k)
        if mapped is not None:
            out.append(mapped)
    return out


def app_switch_modifier() -> str:
    """Modifier HELD for the app switcher: Cmd on macOS, Alt elsewhere."""
    return "command" if _platform() == "darwin" else "alt"


def primary_modifier() -> str:
    """Primary command modifier: 'command' on macOS, 'ctrl' elsewhere.

    For the simple command→ctrl shortcuts issued directly in code (paste,
    Gmail send).
    """
    return "command" if _platform() == "darwin" else "ctrl"
