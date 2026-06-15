# HandsFree Office — Product Requirements Document

**Status:** Decisions integrated (D1–D6, §11) — ready for build
**Last updated:** 2026-06-14
**Supersedes:** the client portion of `implementation_plan.md` (Flutter approach). The server-side OS-abstraction strategy from that plan is carried forward here with corrections.

---

## 1. Summary

HandsFree Office lets a user drive a desktop computer hands-free from their phone. The phone is a **thin controller**: it streams device-motion (to move the cursor), detects taps (to click), and captures voice commands (to trigger actions). A **server** running on the computer translates these platform-neutral signals into real OS actions — keystrokes, app launches, URL opens, presentation control, email compose. An optional **camera-gesture engine runs on the computer** (not the phone) using the computer's webcam.

This PRD defines two deliverables:

1. **Two native client apps** — iOS (Swift/SwiftUI) and Android (Kotlin) — built separately but kept behaviorally identical against a shared protocol. This replaces the single-Flutter-codebase approach.
2. **A cross-platform server** — one Python server that runs on macOS, Windows, and X11 Linux, abstracting all OS-specific behavior behind a platform executor and a corrected key-remapping layer.

---

## 2. Goals & Non-Goals

### Goals

- **Any phone pairs with any supported computer.** An iPhone controlling a Windows PC is identical to an iPhone controlling a Mac, because the phone never knows the computer's OS. The cross-OS burden lives entirely server-side.
- **Native client per platform**, sharing one protocol contract — not one shared codebase.
- **Server runs on macOS (existing), Windows, and X11 Linux** with feature parity wherever the OS permits programmatic input injection.
- **Low-latency motion** — cursor control must feel real-time (target ≥ 30 Hz end-to-end, ideally 60 Hz).

### Non-Goals (explicit)

- **Chromebook / ChromeOS support.** ChromeOS only runs Linux apps inside the Crostini sandbox, which **cannot inject input into the ChromeOS host**, so it cannot drive Chrome or any host app. Out of scope — see §10.
- **Native-Wayland Linux input injection.** Wayland deliberately forbids arbitrary processes from synthesizing global input; `pyautogui`/`xdotool` do not work against Wayland-native windows. Supported Linux = **X11 (or XWayland for X11 target apps)** only. See §10.
- **A single shared client codebase.** Deliberately rejected for this app — see §5.
- **WSL2 as a first-class server target.** Input injection from WSL2 into the Windows desktop is not reliably possible. Documented limitation, not a goal. See §10.
- **Per-browser tab control on Windows/Linux.** No clean cross-browser tab API exists off macOS; non-Mac platforms open URLs in the default browser only. See §10.

---

## 3. Architecture Overview

```
┌─────────────────┐         WebSocket (JSON)          ┌──────────────────────────┐
│   Phone client  │  ws://<computer-ip>:8765          │     Computer (server)     │
│  (iOS / Android)│ ─────────────────────────────────▶│                          │
│                 │                                   │  ┌────────────────────┐  │
│  • Motion ──────┼── tilt_angles / tilt_vector ─────▶│  │ MouseController     │  │
│  • Tap ─────────┼── tap ───────────────────────────▶│  │ NLU (local + LLM)   │  │
│  • Voice (STT)──┼── command{text} ────────────────▶ │  │ SystemExecutor      │  │
│  • Buttons ─────┼── gestures_toggle / swipe ──────▶ │  │ KeyRemap            │  │
│                 │ ◀──── {ok, result, via} ──────────┤  │ CameraGestureEngine │  │
└─────────────────┘                                   │  └────────────────────┘  │
                                                       │   (uses computer's        │
                                                       │    keyboard/mouse/webcam) │
                                                       └──────────────────────────┘
```

**Key property — the phone × computer matrix decouples completely:**

| | macOS server | Windows server | X11 Linux server |
|---|:---:|:---:|:---:|
| **iPhone client** | ✅ | ✅ | ✅ |
| **Android client** | ✅ | ✅ | ✅ |

The phone emits platform-neutral intents and raw motion. Nothing in the client is OS-specific to the *computer*. This is the architecture's core strength and the reason two thin native clients are viable.

---

## 4. Platform Support Matrix

### Clients

| Platform | Tech | Status |
|---|---|---|
| iOS | Swift + SwiftUI, native sensor/speech APIs | Exists today (`ios/HandsFreeOffice/`); keep & extend |
| Android | Kotlin + Jetpack (Compose or Views), native sensor/speech APIs | New build |

### Servers

| Platform | Input injection | Status | Notes |
|---|:---:|---|---|
| macOS | ✅ AppleScript + pyautogui | Exists | Reference implementation |
| Windows | ✅ pyautogui + Win32 ctypes | Target | Needs corrected key remap (§8) |
| Linux (X11) | ✅ pyautogui + xdotool | Target | Requires X11 session |
| Linux (Wayland) | ❌ blocked by OS | Non-goal | See §10 |
| ChromeOS | ❌ Crostini sandbox | Non-goal | See §10 |
| WSL2 | ⚠️ unreliable | Non-goal | See §10 |

---

## 5. Decision Record — Two Native Apps vs. Flutter

**Decision: build two native apps (iOS Swift, Android Kotlin), not one Flutter app.**

### Rationale

The value of a shared (Flutter) codebase scales with the ratio:

> (shared UI + app logic) ÷ (unshareable per-platform native code)

For this app that ratio is **unusually low**:

1. **The client is thin.** All "business logic" — NLU, keymaps, OS actions — lives in the server. The client is a sensor/mic → JSON pump plus a handful of buttons. There is almost nothing to share.
2. **The hard parts are native either way.** Hardware-fused attitude (iOS `CMMotionManager` / Android `SensorManager.TYPE_ROTATION_VECTOR`) and speech (`SFSpeechRecognizer` / Android `SpeechRecognizer`) have **no cross-platform Flutter package** — they require platform channels. Flutter would force us to write the same native Swift + Kotlin *and* a Dart bridge on top. It adds a layer; it removes nothing hard.
3. **An iOS app already exists and works.** Flutter means discarding tuned native code and re-implementing the hardest-to-test path (motion) from scratch. Native-Android-only keeps the working iOS app and adds exactly one new thing.
4. **Latency risk.** Flutter would stream ~60 Hz motion across a Dart↔native `EventChannel` boundary — a latency and debugging seam in the exact path that's most sensitive. Native debugs motion on the metal, in one language.

### When this decision flips

The decision is conditional on the device matrix. If the target set fans out beyond phones — a **web-based controller, a desktop controller, tablet/TV UIs** — then one Flutter (or KMP) codebase amortizing shared UI across many targets becomes the more feasible path, and this decision should be revisited.

- **2 phone OSes (current scope)** → two native apps. ✅ this PRD.
- **Phones + web/desktop/other form factors, growing** → reconsider Flutter.

### Cost accepted

Two codebases, two languages, two toolchains/release pipelines, and a risk of protocol drift. Mitigated by §6 — a single shared protocol spec is the contract, not the code.

### Sub-decision: Kotlin over Java for Android

Use **Kotlin**, not Java. It is Google's Android default and maps cleanly onto Swift idioms (closures, null-safety, structured concurrency), so the two apps *read* alike — directly serving the "as similar as possible" goal. The sensor/speech APIs are identical Android APIs either way.

---

## 6. The Shared Contract — WebSocket Protocol Spec

> This spec is the single source of truth that keeps the two native apps in lockstep. Both apps build against it; the server (`server/server.py`) defines it. **Do not let the apps mirror each other's code — let them mirror this contract.**

### 6.1 Transport

- **URL:** `ws://<computer-ip>:8765` (plain WebSocket, no TLS on LAN).
- **Server bind:** `0.0.0.0:8765`, `ping_interval=None` (`server/server.py:717-720`).
- **Encoding:** UTF-8 JSON text frames, one JSON object per frame.
- **Server IP** is user-configured in the app (must not be hardcoded — current Swift hardcodes it; both apps require a settings field).

### 6.2 Connection lifecycle

1. On TCP/WS connect, **server** sends: `{"ok": true, "type": "hello", "from": "server"}`.
2. Client may send `{"type":"hello"}`; server replies `{"ok": true, "type": "hello_ack"}`.
3. Client streams gesture/command frames; server replies to each (see below).
4. **Reconnect:** client auto-reconnects with exponential backoff **0.5 s → 6 s** on drop. Apps should surface connection state in the UI.

### 6.3 Inbound messages (phone → server)

| `type` | `kind` | Fields | Server reply |
|---|---|---|---|
| `command` | — | `text: string` | `{ok, result, via}` or `{ok:false, error}` |
| `gesture` | `tilt_angles` | `roll_deg: float`, `pitch_deg: float`, `dt: float` (sec) | `{ok, result:"tilt_angles_ok"}` |
| `gesture` | `tilt_vector` | `vx: float`, `vy: float`, `dt: float` | `{ok, result:"tilt_ok"}` |
| `gesture` | `tap` | — | `{ok, result:"click_ok"\|"click_ignored"}` |
| `gesture` | `swipe` | `direction: "left"\|"right"\|"up"\|"down"` *(or* `dx,dy` *floats)* | `{ok, result:"history_back"\|...}` |
| `gesture` | `gestures_toggle` | `enabled: bool` | `{ok, result:"gestures_on"\|"gestures_off"\|"gestures_unavailable"}` |
| `gesture` | `motion_started` | — | `{ok, result:"motion_started"}` |
| `hello` | — | — | `{ok, type:"hello_ack"}` |

Notes:
- `tilt_angles` also accepts legacy keys `roll`/`pitch` as fallbacks (`server/server.py:472-473`). **New apps must send `roll_deg`/`pitch_deg`.**
- The recommended motion path is **`tilt_angles`** (degrees from fused attitude). `tilt_vector` (normalized velocity) is the older path; new apps should standardize on `tilt_angles`.
- `swipe`, `gestures_toggle` originate from app buttons or the computer's camera engine.

### 6.4 Outbound messages (server → phone)

- Per command: `{"ok": true, "result": "<status>", "via": "regex"|"keyword"|"tfidf:<score>"|"llm"}`
- Per gesture: `{"ok": true, "result": "<status>"}`
- Errors: `{"ok": false, "error": "bad_json"|"unknown_type"|"nlu_failed:<reason>"}`

### 6.5 Motion axis & sign conventions (CRITICAL for parity)

The server expects (`server/server.py:469-478`, MouseController `update_cursor_from_angles`):

- **`roll_deg > 0` → tilt phone right → cursor moves right (+x).**
- **`pitch_deg > 0` → tilt phone forward (top edge away) → cursor moves down (+y).**
- Server picks a **single dominant axis** (no diagonals): whichever of |roll|, |pitch| is larger wins; the other is zeroed.
- `dt` is clamped server-side to `[0.0005, 0.2]`; out-of-range → defaults to `1/30 s`.

**Per-platform native caveat (the single trickiest correctness item):**
- **iOS** (`CMMotionManager`, `.xArbitraryZVertical` frame): use `attitude.roll`/`attitude.pitch`, **pitch is inverted** before sending (existing Swift behavior).
- **Android** (`TYPE_ROTATION_VECTOR` → `getRotationMatrixFromVector` → `getOrientation`): the rotation-vector frame differs from iOS. Android **must remap/sign-flip axes so its output matches the iOS convention above.** This is the #1 thing to verify on a physical device. Identical effort whether native or Flutter — not a differentiator.

### 6.6 Tuning constants (must be identical across both apps)

| Constant | Value | Where |
|---|---|---|
| Tap acceleration threshold | **> 1.10 g** (userAcceleration / linear-accel magnitude) | client |
| Tap client cooldown | **0.25 s** | client |
| Tap server debounce | **0.10 s** | `server/server.py:486` |
| Speech partial-result debounce | **1.3 s** | client |
| Motion send rate | **~60 Hz** (throttle), server consumes ≥30 Hz | client |
| `dt` valid range | `[0.0005, 0.2]` s | server |

Server-side cursor dynamics (informational; apps don't set these): `DEAD_ZONE_DEG=10`, `V_MIN=120`, `V_MAX=520 px/s`, `SAT_ANGLE_DEG=25`, `ALPHA_ANGLE=0.2` low-pass, `MAX_STEP_PX=16` (`server/server.py:116-122`).

---

## 7. Client App Requirements (iOS & Android)

### 7.1 Functional requirements (both apps)

| ID | Requirement |
|---|---|
| C-1 | Connect/disconnect to a user-entered server IP on port 8765; auto-reconnect with 0.5→6 s backoff. |
| C-2 | Stream fused-attitude motion as `tilt_angles` (`roll_deg`, `pitch_deg`, `dt`) at ~60 Hz while "motion" is enabled. |
| C-3 | Detect a tap (accel magnitude > 1.10 g, 0.25 s cooldown) and send `tap`. |
| C-4 | Capture voice via on-device/platform speech recognition; debounce partials at 1.3 s; send final text as `command`. |
| C-5 | Toggle the computer's camera-gesture engine via `gestures_toggle{enabled}`. |
| C-6 | Buttons: Start/Stop listening (voice), Start/Stop motion, Toggle hand gestures. |
| C-7 | Status indicators: connection state, motion active, gestures active, last server result. |
| C-8 | Send `motion_started` when motion begins (server acknowledges). |
| C-9 | Request and gracefully handle permission denial for microphone, speech recognition, and motion. |

### 7.2 iOS specifics

- **Motion:** `CMMotionManager.startDeviceMotionUpdates(using: .xArbitraryZVertical)`; `attitude.roll`/`.pitch` → degrees; **invert pitch**.
- **Tap:** `CMDeviceMotion.userAcceleration` magnitude (gravity already removed).
- **Speech:** `SFSpeechRecognizer` + `AVAudioEngine`; partial results with 1.3 s debounce.
- **Permissions:** `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`, `NSMotionUsageDescription`.
- **Existing asset:** `ios/HandsFreeOffice/MotionSpeechStreamer.swift`, `ContentView.swift` — extend, don't rewrite.

### 7.3 Android specifics

- **UI toolkit (D6):** **Jetpack Compose** + Material 3. Mirrors SwiftUI's declarative model for parity. Target a deliberate, modern look (clear hierarchy, real spacing/typography, one accent color, motion/connection state always visible) — not a stock template and not careless. Single-activity, `ViewModel` + `StateFlow` driving the UI.
- **WebSocket:** OkHttp `WebSocket` (or Ktor client) in a foreground/bound service; reconnect with the §6.2 backoff. Keep the socket off the main thread.
- **Motion:** `SensorManager.TYPE_ROTATION_VECTOR` → `getRotationMatrixFromVector` → `getOrientation` → roll/pitch in degrees; **axis-map/sign-flip to match the iOS convention in §6.5.**
- **Tap:** `TYPE_LINEAR_ACCELERATION` (gravity removed) magnitude.
- **Speech:** Android `SpeechRecognizer` (or Speech Services); replicate 1.3 s partial debounce.
- **Permissions:** `RECORD_AUDIO`; runtime permission flow; `HIGH_SAMPLING_RATE_SENSORS` if needed.
- **Sensor delay:** request `SENSOR_DELAY_GAME` (~50 Hz) or faster to approach 60 Hz; throttle to the send rate.
- **Debuggability (D6, REQUIRED):** tagged logging (e.g. `Log.d("HFO/WS", …)`, `"HFO/Motion"`, `"HFO/Speech"`) for every outbound frame and connection-state transition, plus an in-app **debug overlay** toggle showing live connection state, last server `result`, current `roll_deg`/`pitch_deg`/`dt`, and tap events. This is the on-device equivalent of the server's stdout log and the fastest way to triage the §6.5 axis problem without a wired debugger. Mirror the same overlay in iOS for symmetry.

### 7.4 Cross-app parity requirements

- Identical message schema, field names, axis conventions, and tuning constants (§6).
- Identical UI affordances and states (C-6, C-7) — same controls, same labels, same semantics. **Structural code symmetry is NOT a requirement; behavioral parity is.**
- A shared `PROTOCOL.md` (extracted from §6) is the contract both teams build against. Any protocol change updates that doc first, then both apps.

### 7.5 Client caveats

- **Motion cannot be tested on simulators/emulators** — no real gyroscope or sensor fusion. Physical iOS and Android devices are mandatory for motion/tap validation.
- **Android axis mapping** (§6.5) is the highest-risk correctness item; budget device-tuning time.
- **Speech recognition differs** between platforms (accuracy, locale handling, on-device vs cloud). Expect per-platform tuning; the server NLU is tolerant of phrasing, which helps.
- **Network reachability is a hard dependency** — see §10.

---

## 8. Server Requirements

The server abstracts every OS-specific behavior. Carries forward the executor strategy from `implementation_plan.md`, **with the key-remapping layer corrected** (the original plan's modifier-only swap is unsafe — see §8.2).

### 8.1 Platform executor (`server/executor.py` — new)

- `detect_platform() -> "darwin" | "win32" | "linux"` (WSL2 detected but treated as best-effort/non-goal).
- `SystemExecutor` ABC with concrete `MacExecutor`, `WinExecutor`, `LinuxExecutor`.
- Abstract operations: `open_app`, `open_url`, `get_frontmost_app`, `frontmost_is_browser`, `open_default_browser`, `start_presentation`, `compose_email`.
- `compose_email` (Gmail-URL building) is **identical across platforms except the send hotkey** → put it on the ABC as a concrete method; only the modifier differs (`command+enter` vs `ctrl+enter`). Avoid the 4× copy-paste in the original plan.
- **Browser model (D1):** `new_tab`/`close_tab`/`reload_tab`/zoom/history act on whatever is frontmost. The shared flow is: `if frontmost_is_browser(): send hotkey  else: open_default_browser()`. `frontmost_is_browser()` compares `get_frontmost_app()` against a per-platform `BROWSERS` set (Safari, Chrome, Edge, Brave, Firefox, Vivaldi, Arc, …). This replaces the old macOS-only AppleScript "active-browser tab API" with a uniform, OS-neutral rule.
- `create_executor()` factory selects by platform.

| Operation | macOS | Windows | Linux (X11) |
|---|---|---|---|
| `open_app` | AppleScript `tell application` → fallback `open -a` | `os.startfile` → fallback PowerShell `Start-Process` | `xdg-open`/`gtk-launch`/exec by name |
| `open_url` | `open <url>` (or AppleScript for the active-tab nicety) | `os.startfile(url)` (default browser) | `xdg-open` (default browser) |
| `open_default_browser` | `open -a "Safari"`/`open <about:blank>` | `os.startfile("http://")` / default-browser launch | `xdg-open about:blank` / `x-www-browser` |
| `get_frontmost_app` | AppleScript System Events | Win32 ctypes: foreground HWND → PID → `GetModuleFileNameExW` (fast, accurate) | `xdotool getactivewindow getwindowpid` → `ps` |
| `frontmost_is_browser` | name ∈ `BROWSERS` | name ∈ `BROWSERS` | name ∈ `BROWSERS` |
| `start_presentation` | **Google Slides: open deck URL → `Cmd+F5` present (primary).** Keynote: open recent doc → start show (extra) | **Google Slides → `Ctrl+F5` (primary).** PowerPoint: `Start-Process POWERPNT` → F5 *(weaker)* | **Google Slides → `Ctrl+F5` (primary).** Impress → F5 *(weaker)* |
| `compose_email` | Gmail web URL + (optional) `command+enter` | Gmail web URL + (optional) `ctrl+enter` | Gmail web URL + (optional) `ctrl+enter` |

### 8.2 Key remapping (`server/platform_keys.py` — new) — CORRECTED

> **Critical correction to `implementation_plan.md`:** that plan assumed "`command` → `ctrl` is correct for shortcuts" with only `fn`+arrow and the app-switcher as exceptions. **This is wrong for a large fraction of `config/keymap.json`** — many macOS shortcuts map to a *different key*, not a different modifier. A naive modifier swap silently breaks (and in two cases fires a *different* action). Remapping MUST be a **per-intent table**, not a modifier substitution.

**Mac → Windows/Linux override table** (entries where naive `command→ctrl` / `option→alt` is WRONG):

| Intent | keymap (macOS) | Naive swap (WRONG) | Correct Win/Linux | Failure if uncorrected |
|---|---|---|---|---|
| `switch_app` | `command+tab` | `ctrl+tab` | **`alt+tab`** | Switches browser *tab*, not app |
| `word_left` | `option+left` | `alt+left` | **`ctrl+left`** | `alt+left` = browser **Back** |
| `word_right` | `option+right` | `alt+right` | **`ctrl+right`** | `alt+right` = browser **Forward** |
| `line_start` | `command+left` | `ctrl+left` | **`home`** | `ctrl+left` = word-left (wrong granularity) |
| `line_end` | `command+right` | `ctrl+right` | **`end`** | wrong granularity |
| `find_next` | `command+g` | `ctrl+g` | **`f3`** | `ctrl+g` = "go to" / no-op |
| `find_previous` | `command+shift+g` | `ctrl+shift+g` | **`shift+f3`** | no-op in most apps |
| `redo` | `command+shift+z` | `ctrl+shift+z` | **`ctrl+y`** | `ctrl+shift+z` unreliable outside browsers |
| `minimize_window` | `command+m` | `ctrl+m` | **`win+down`** (Win); WM-specific (Linux) | `ctrl+m` does unrelated things |
| `scroll_top` | `fn+left` | (invalid `fn`) | **`home`** | `fn` not a valid key off macOS |
| `scroll_bottom` | `fn+right` | (invalid `fn`) | **`end`** | `fn` not a valid key off macOS |
| `close_tab` | `command+w` | `ctrl+w` | **`ctrl+w`** (correct) | — (D4) |
| `close_window` | `command+w` | `ctrl+w` (closes tab, not window) | **`alt+f4`** (Win); **`alt+f4`→`ctrl+q`** (Linux WM) | Closes a tab instead of the window |

**Also fix the in-code browser helpers** (`server/server.py:56-66`), which are not in keymap.json:

| Helper | macOS | Correct Win/Linux |
|---|---|---|
| `browser_history_back` | `command+[` | **`alt+left`** (`ctrl+[` is a no-op in Chrome) |
| `browser_history_forward` | `command+]` | **`alt+right`** |

**Entries where the simple swap IS correct** (`command→ctrl`): `new_tab, close_tab, reload_tab, select_all, copy, paste, cut, undo, bold, italic, underline, find, zoom_in, zoom_out, zoom_reset, new_window, send_email (Gmail Ctrl+Enter)`. Universal keys (`tab, enter, esc, backspace, delete, arrows, home, end`) pass through unchanged. `next_tab`/`previous_tab` already use `control` and are correct everywhere.

**Resolved (D4):** `close_tab` and `close_window` are **both `command+w` on macOS but must diverge off macOS**: `close_tab` → `ctrl+w`, `close_window` → `alt+f4` (Linux: `alt+f4`, falling back to `ctrl+q` where the WM ignores `alt+f4`). Both are now distinct rows in the override table above. **Note:** because they collide on macOS, the NLU must be able to distinguish the two intents from phrasing ("close tab" vs "close window") — verify both have examples in `intents.json`.

**Design:** a single `KEY_OVERRIDES[platform][intent] -> [keys]` table consulted first; fall back to per-key modifier mapping only for intents not in the override table. `fn` has no equivalent off macOS and must never be emitted (it raises `InvalidKeyException` on Windows pyautogui).

### 8.3 Changes to existing files

| File | Change |
|---|---|
| `server/server.py` | Create `EXEC = create_executor()`; route `applescript_open_app`→`EXEC.open_app`, `applescript_open_url`→`EXEC.open_url`, `applescript_keynote_start`→`EXEC.start_presentation`, `applescript_gmail_compose` (L511-512) and the no-field `mailto_compose` branch (L567) → `EXEC.compose_email`; wrap all `pyautogui.hotkey(*plan["keys"])` (L538) and the browser/zoom/history helpers (L56-96) and the `on_action` callback (L416-448) through the key-override layer; use `EXEC.get_frontmost_app`. **Do not miss the gmail-compose and mailto call sites** (omitted by the original plan). |
| `server/server.py` — **browser-active helpers (NEW callout, easy to miss)** | The macOS build already contains AppleScript-backed browser logic the original plan never enumerated: `get_frontmost_app_name()` (L126+), `open_url_in_active_browser()`, `gmail_compose_in_active_browser()`, `set_preferred_browser()`/`PREFERRED_BROWSER`, and the `CHROME_FAMILY` set (L26-49). These are **macOS-only AppleScript** and must be abstracted behind the executor too, or guarded to no-op off macOS. Per **D1**, replace "preferred browser" routing with the frontmost-driven rule (`frontmost_is_browser` → hotkey, else `open_default_browser`); `set_browser` becomes a near-no-op. |
| `server/primitives.py` | `focused_typing` paste hotkey via remap; guard `run_applescript` to no-op off macOS; mark `open_gmail_compose`/`start_keynote_slideshow` superseded by executor methods. |
| `server/nlu.py` | `slot_app()` reads platform-keyed nested dicts (with flat-string backward-compat). **Change default `OLLAMA_MODEL` (L68) from `llama3.1:8b` → `qwen2.5:3b-instruct`** (D3). Make `ollama_route` failure (connection refused / model missing) non-fatal: the command handler must fall through to a clear `nlu_failed:llm_unavailable` rather than bubbling an exception (see §8.6). |
| `config/slots.json` | Add browser names used by D1 (`edge`→Microsoft Edge, `brave`→Brave Browser, `arc`→Arc, `vivaldi`→Vivaldi) and a `slides`/`google slides` site entry usable as the present target. Per-platform app names where they differ (Keynote/POWERPNT/Impress, etc.); keep flat strings where identical. |
| `config/intents.json` | Add/curate examples so the NLU can resolve the D1/D2/D4 intents locally without the LLM: distinct `close_tab` vs `close_window`, `new_tab` ("new tab", "open a tab"), named-browser opens ("open edge", "open brave"), and present-Google-Slides phrasing. |
| `config/system_prompt.txt` | Platform-neutral language ("on the user's computer"). |
| `server/gestures.py` | Use `cv2.CAP_DSHOW` on Windows for lower camera-startup latency (L127). |
| `setup.sh` / `setup.ps1` (**NEW**, D3) | Bootstrap script: install Ollama if absent, `ollama pull qwen2.5:3b-instruct`, install `server/requirements.txt`. Document as the one prerequisite step. |

### 8.4 Camera-gesture engine clarification

The hand-gesture engine (`CameraGestureEngine`, OpenCV + MediaPipe) **runs on the computer using the computer's webcam**, not the phone's. The phone's "hand gestures" button is just a remote on/off (`gestures_toggle`). This is OS-agnostic in code; only the `cv2` capture backend differs (`CAP_DSHOW` on Windows).

### 8.5 Server caveats

- **Wayland / ChromeOS:** input injection blocked — see §10. The server should detect Wayland (`XDG_SESSION_TYPE=wayland`) and warn loudly at startup.
- **Native presentation start is weaker off macOS:** Keynote opens the most-recent document then starts the show; `Start-Process POWERPNT`/Impress land on an empty start screen where F5 may do nothing. Per **D2**, prefer the **Google Slides** path (open deck URL → `Ctrl/Cmd+F5`) as the cross-platform default; treat native apps as best-effort with "open recent" where the app exposes it.
- **Per-browser tab control lost off macOS** (§10) — `open_url` opens the default browser only; the `set_browser` feature degrades to a no-op there.
- **Testing `PLATFORM` constant:** it is computed at import and copied via `from executor import PLATFORM` into `platform_keys`/`nlu`. Tests must patch each module's binding (or have functions read `executor.detect_platform()` live). Prefer the latter to avoid import-order surprises.

### 8.6 NLU & local LLM (D3 — local-only, bundled Ollama)

**No cloud, no API keys, ever.** Routing is a cascade; the LLM is the last resort:

1. **regex** (`local_route`, `nlu.py:170`) → 2. **keyword contains** → 3. **TF-IDF** (`LocalRouter`, threshold 0.42) → 4. **local LLM** (`ollama_route`, `nlu.py:71`).

- **Model:** default `qwen2.5:3b-instruct` (fast on CPU / modest GPU; `temperature=0`). `qwen2.5:7b-instruct` is the quality knob. Selectable via the existing `OLLAMA_MODEL` env var — no code change to switch.
- **Bundling/bootstrap:** `setup.sh`/`setup.ps1` installs Ollama and pulls the model. "Ship with server" = the model is pulled at setup, not vendored into the repo (multi-GB).
- **Graceful degradation (REQUIRED):** if Ollama is not running or the model is missing, steps 1–3 still work; step 4 must fail soft. The server logs a loud one-time warning at startup (`ollama not reachable → local NLU only`) and per-command returns `{ok:false, error:"nlu_failed:llm_unavailable"}` instead of throwing. The `@retry(stop_after_attempt(3))` on `ollama_route` (`nlu.py:71`) currently amplifies a dead-Ollama into ~3× backoff per command — **cap or short-circuit it when a connection probe fails**, or each unmatched utterance stalls the socket for seconds.
- **Latency budget:** the regex/keyword/TF-IDF layers are sub-millisecond and cover the canonical phrasings; the LLM (seconds on CPU) is only hit on novel phrasing. **Demo guidance: seed `intents.json` so the common commands never reach the LLM.**
- **First-run cost:** `ollama pull` is a multi-GB download; document it as a one-time setup, not a runtime surprise.

---

## 9. Testing & Acceptance Criteria

### Automated

- `tests/test_platform_keys.py` — for each platform, assert every `keymap.json` intent maps to the **correct** keys per §8.2 (explicitly assert the override cases: `switch_app→alt+tab`, `word_left→ctrl+left`, `line_start→home`, `find_next→f3`, and **D4: `close_tab→ctrl+w`, `close_window→alt+f4`**).
- `tests/test_executor.py` — factory returns the right class per platform; `compose_email` builds the correct Gmail URL; `frontmost_is_browser` matches the `BROWSERS` set; `start_presentation` builds the correct Google Slides present action (D2).
- `tests/test_nlu.py` — local cascade resolves the D1/D2/D4 intents (named-browser open, `new_tab`, distinct `close_tab`/`close_window`, present Google Slides) **without** the LLM; and `ollama_route` failure degrades to `nlu_failed:llm_unavailable` (mock a refused connection) without throwing or 3× stalling (D3, §8.6).

### Manual / device

- Run server on **Windows** and **X11 Linux**; send every command via `test_client.py`; verify each fires the intended OS action (special attention to the §8.2 override cases).
- Run each app on a **physical** iOS and Android device; verify motion direction matches §6.5 conventions, tap clicks, voice → action.
- Verify Android axis mapping produces the same cursor direction as iOS for the same physical tilt.
- Verify camera-gesture toggle and `CAP_DSHOW` startup on Windows.

### Acceptance criteria

- ✅ Same phone drives Mac, Windows, and X11 Linux with no client change.
- ✅ All §8.2 override intents fire the correct action on Windows and Linux (zero "wrong action" regressions), including D4 `close_tab`/`close_window`.
- ✅ Cursor moves in the correct direction on both iOS and Android for identical physical tilt.
- ✅ Startup warning shown on Wayland/unsupported environments.
- ✅ **D1:** "open <browser>" launches that browser; "new tab" opens a tab in the frontmost browser, or the default browser when none is focused — on all three OSes.
- ✅ **D2:** "present" / "start presentation" enters Google Slides present mode on all three OSes.
- ✅ **D3:** with Ollama stopped, canonical commands still work via local NLU and the server stays responsive (no multi-second stall, no crash).

---

## 10. Consolidated Caveats & Known Limitations

| # | Limitation | Why | Disposition |
|---|---|---|---|
| L-1 | **Network is the real dependency.** Phone and computer must be on the same LAN; port 8765 reachable; host firewall must allow it (Windows Defender prompts on first run). | It's a LAN socket app. | Provide setup guidance + in-app IP field; surface clear connection errors. |
| L-2 | **Chromebook unsupported.** Crostini Linux container cannot inject input into the ChromeOS host, so it can't drive Chrome/host apps. | OS security boundary, not effort. | Non-goal. Would require a different control mechanism (browser extension), losing OS-level control. |
| L-3 | **Native-Wayland Linux unsupported.** Wayland forbids synthetic global input; pyautogui/xdotool fail on Wayland-native windows. | OS security model. | Support X11 (or XWayland for X11 apps) only; warn on Wayland. |
| L-4 | **WSL2 not first-class.** Can route app/URL via `powershell.exe`, but hotkeys (the bulk of the app) can't reach the Windows desktop. | No shared display. | Documented limitation; don't model as a full executor. |
| L-5 | **No per-browser *background* targeting off macOS** (e.g. "open a tab in Chrome while Safari is focused"). Per **D1** we don't need it: browser hotkeys act on the **frontmost** browser, else open the default browser — which IS cross-platform. | No clean cross-browser background API. | D1 frontmost-driven rule. `set_browser` demoted to a near-no-op. |
| L-6 | **Native presentation start is weaker off macOS.** PowerPoint/Impress launch to an empty start screen; F5 may no-op. | App-specific. | **D2: Google Slides is the primary, cross-platform path** (`Ctrl/Cmd+F5`); native apps are best-effort extras with "open recent" where supported. |
| L-7 | **Motion needs physical devices; Android axes need tuning.** | Simulators lack sensors; rotation-vector frame ≠ iOS frame. | Mandatory device testing; §6.5 is the spec. |
| L-8 | **Two codebases can drift.** | Native-twice. | `PROTOCOL.md` is the single contract; protocol changes update it first. |
| L-9 | **Speech accuracy varies per platform.** | Different STT engines. | Per-platform tuning; lean on tolerant server NLU. |
| L-10 | **Local LLM adds setup weight + cold latency** (D3). Ollama install + multi-GB `ollama pull`; first/novel command can take seconds on CPU. | Local-only by mandate (no API budget). | One-time `setup.sh`/`setup.ps1`; seed `intents.json` so common commands never hit the LLM; fail soft to local NLU if Ollama is down (§8.6). |

---

## 11. Resolved Decisions

All prior open questions are now decided. Each decision is propagated into the body section noted; this section is the authoritative changelog.

- **D1 — Browser control (replaces Q1).** Spoken browser names launch that browser by name (`open edge` → Microsoft Edge, `open safari` → Safari) via `open_app` — works on every OS. **`new tab` (and every other browser hotkey) acts on the currently-frontmost app:** if the frontmost app is a known browser, send the new-tab hotkey to it; **if the frontmost app is not a browser (or no browser is open), open the default browser** (which yields a fresh window/tab). No per-browser *targeting from the background* is required, so this is fully cross-platform — see §8.1, §10 L-5. The legacy `set_browser`/`PREFERRED_BROWSER` preference is demoted (frontmost-driven supersedes it).

- **D2 — Presentations: add Google Slides, cross-platform first (replaces Q2).** Google Slides is the **primary, OS-neutral** presentation path: open the deck URL and enter present mode (`Ctrl/Cmd+F5`, or the `/present` URL form). Native Keynote / PowerPoint / Impress remain as platform extras. Non-Mac platforms implement "open most recent presentation" to match Mac UX where the app exposes it. See §8.1, §8.5, §10 L-6.

- **D3 — NLU is local-only; bundle Ollama (replaces Q3).** No cloud LLM, no API keys — ever. The LLM fallback stays the local Ollama at `http://127.0.0.1:11434`. The server **ships with a bootstrap step that installs Ollama and pulls a small model** (default `qwen2.5:3b-instruct`; bump to `qwen2.5:7b-instruct` for quality). If Ollama is absent/unreachable, the server **degrades to local NLU only** (regex → keyword → TF-IDF) and warns loudly rather than crashing. See §8.6.

- **D4 — `close_tab` = `Ctrl+W`, `close_window` = `Alt+F4` (replaces Q4).** Resolved in the §8.2 override table; the ambiguity note is removed. Linux `close_window` uses `Alt+F4` where the WM honors it, `Ctrl+Q` fallback.

- **D5 — iOS + Android phones only; native-vs-Flutter decision stands (replaces Q5).** No web/desktop/tablet on the horizon, so the §5 trigger to revisit Flutter is **not** activated. Two native apps confirmed.

- **D6 — Android UI = Jetpack Compose (replaces Q6).** Compose (declarative, mirrors SwiftUI). Bar: a **modern, intentional design** — not template/"AI-slop" and not careless. Plus an explicit **debuggability requirement**: structured/tagged logging of every sent frame and connection-state transition, and an in-app debug overlay (live connection state, last server result, current roll/pitch/dt, tap events). See §7.3.

---

## 12. Phased Rollout

**Phase 1 — Cross-platform server (independently shippable).**
1. `executor.py` (ABC + Mac/Win/Linux + `detect_platform`), incl. `frontmost_is_browser`/`open_default_browser` and the `start_presentation` Google-Slides path (D1, D2).
2. `platform_keys.py` with the **per-intent override table** (§8.2) — not modifier-only (incl. D4 `close_tab`/`close_window`).
3. Refactor `server.py`/`primitives.py` to route through `EXEC` + key overrides (incl. the gmail/mailto call sites **and the browser-active AppleScript helpers** — §8.3); wire the D1 frontmost-driven browser rule.
4. `slots.json` (browser names + slides), `intents.json` (D1/D2/D4 examples), `system_prompt.txt`, `nlu.slot_app`, `nlu` Ollama default + fail-soft (§8.6), `gestures.py` (CAP_DSHOW).
5. `setup.sh`/`setup.ps1` Ollama bootstrap (D3).
6. Verify on Windows + X11 Linux with the existing iOS client and `test_client.py`.
   → *Delivers Windows/Linux support with the current iOS app. No client work required.*

**Phase 2 — Android native client.**
1. Kotlin app: WebSocket service (0.5→6 s backoff), motion (`TYPE_ROTATION_VECTOR`, axis-mapped to §6.5), tap (`TYPE_LINEAR_ACCELERATION`), speech (`SpeechRecognizer`, 1.3 s debounce).
2. UI parity with iOS (C-6/C-7); server-IP config.
3. Device-test motion direction against iOS.

**Phase 3 — iOS polish & parity.**
1. Extract `PROTOCOL.md` from §6; conform existing iOS app (standardize on `tilt_angles`, add server-IP field if missing).
2. Align UI/states with Android.

**Phase 4 — Integration & validation.**
1. Full matrix: {iPhone, Android} × {Mac, Windows, X11 Linux}.
2. Acceptance criteria (§9), including the §8.2 override regression checks.
