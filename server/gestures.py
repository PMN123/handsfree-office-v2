import time
import math
import threading
from collections import deque

try:
    import cv2
    import mediapipe as mp
except Exception as e:
    cv2 = None
    mp = None

def _v(ax, ay, bx, by):
    return (ax - bx, ay - by)

def _angle_deg(ax, ay, bx, by, cx, cy):
    # angle ABC in degrees
    v1x, v1y = _v(ax, ay, bx, by)   # BA
    v2x, v2y = _v(cx, cy, bx, by)   # BC
    dot = v1x*v2x + v1y*v2y
    n1 = (v1x*v1x + v1y*v1y) ** 0.5
    n2 = (v2x*v2x + v2y*v2y) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    c = max(-1.0, min(1.0, dot/(n1*n2)))
    return math.degrees(math.acos(c))

def _is_extended(lm, tip, pip, mcp, thresh_deg=160.0):
    # Finger extended if the PIP angle is "open" (near straight line)
    t, p, m = lm[tip], lm[pip], lm[mcp]
    ang = _angle_deg(t.x, t.y, p.x, p.y, m.x, m.y)
    return ang >= thresh_deg

class CameraGestureEngine:
    """
    Simple, thread-based gesture recognizer using MediaPipe Hands.
    Emits high-level actions via a callback: on_action(str).

    Actions emitted:
      - "zoom_in", "zoom_out"
      - "history_back", "history_forward"
      - "next_tab", "prev_tab"
      - "scroll_up", "scroll_down"   (continuous pulses while moving)
      - "app_switcher_start", "app_switcher_next", "app_switcher_prev", "app_switcher_commit"
    """
    def __init__(self, on_action, camera_index=0):
        self.on_action = on_action
        self.camera_index = camera_index
        self._thr = None
        self._stop = threading.Event()
        self._started = False

        # runtime state
        self._last_pinch_d = None
        self._last_emit = {}
        self._mode_appswitch = False

        # velocity smoothing
        self._centroid_hist = deque(maxlen=5)
        self._last_t = None
        self._open_hand_start_t = None      # for app-switcher 3s hold
        self._state_hist = deque(maxlen=6)  # temporal smoothing (last 6 frames)

    def start(self):
        if self._started:
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._run, daemon=True)
        self._thr.start()
        self._started = True

    def stop(self):
        self._stop.set()
        self._started = False

    def _emit(self, action, cooldown=0.25):
        now = time.monotonic()
        last = self._last_emit.get(action, 0.0)
        if now - last >= cooldown:
            self._last_emit[action] = now
            try:
                self.on_action(action)
            except Exception:
                pass

    def _finger_extended(self, lm, tip, pip, mcp):
        # heuristic: finger extended if tip is farther from wrist than pip/mcp along y-axis in image space
        return lm[tip].y < lm[pip].y < lm[mcp].y

    def _classify(self, lm):
        # basic centroid
        cx = sum([p.x for p in lm]) / len(lm)
        cy = sum([p.y for p in lm]) / len(lm)

        # robust finger extension (ignore thumb for 4-finger gestures)
        ext_idx  = _is_extended(lm, tip=8,  pip=6,  mcp=5)
        ext_mid  = _is_extended(lm, tip=12, pip=10, mcp=9)
        ext_ring = _is_extended(lm, tip=16, pip=14, mcp=13)
        ext_pky  = _is_extended(lm, tip=20, pip=18, mcp=17)
        ext_thumb = _is_extended(lm, tip=4, pip=3, mcp=2, thresh_deg=160.0)

        four_ext = int(ext_idx) + int(ext_mid) + int(ext_ring) + int(ext_pky) + int(ext_thumb)

        # Fist: all four non-thumb fingers curled
        is_fist = (four_ext == 0)

        # Pinch distance still available if you need it for other gestures
        def dist(a, b):
            dx = lm[a].x - lm[b].x
            dy = lm[a].y - lm[b].y
            return math.hypot(dx, dy)
        pinch_d = dist(4, 8)

        return {
            "cx": cx, "cy": cy,
            "ext_idx": ext_idx, "ext_mid": ext_mid, "ext_ring": ext_ring, "ext_pky": ext_pky,
            "four_ext": four_ext,
            "is_fist": is_fist,
            "pinch": pinch_d
        }

    def _run(self):
        if cv2 is None or mp is None:
            # cannot run - missing deps
            return
        # cap = cv2.VideoCapture(self.camera_index)
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FPS, 60)
        hands = mp.solutions.hands.Hands(model_complexity=0, max_num_hands=1, min_detection_confidence=0.5, min_tracking_confidence=0.5)
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.02)
                    continue
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = hands.process(rgb)
                t = time.monotonic()

                if res.multi_hand_landmarks:
                    lm = res.multi_hand_landmarks[0].landmark
                    feats = self._classify(lm)
                    four_ext = feats["four_ext"]   # number of extended non-thumb fingers (0–5)
                    is_fist  = feats["is_fist"]    # True if all 5 fingers curled

                    # velocity from centroid
                    if self._last_t is None:
                        self._last_t = t
                        self._centroid_hist.clear()
                        self._centroid_hist.append((feats["cx"], feats["cy"], t))
                        continue
                    self._centroid_hist.append((feats["cx"], feats["cy"], t))
                    vx, vy = 0.0, 0.0
                    if len(self._centroid_hist) >= 2:
                        x0, y0, t0 = self._centroid_hist[0]
                        x1, y1, t1 = self._centroid_hist[-1]
                        dt = max(1e-3, t1 - t0)
                        vx = (x1 - x0) / dt
                        vy = (y1 - y0) / dt

                    # gestures
                    pinch = feats["pinch"]

                    # Record state for smoothing
                    self._state_hist.append({
                        "four_ext": feats["four_ext"],
                        "is_fist": feats["is_fist"],
                        "cy": feats["cy"],
                        "vx": vx,
                        "vy": vy,
                    })

                    # Majority vote over last K frames
                    def _maj(field, pred):
                        return sum(1 for s in self._state_hist if pred(s[field])) > len(self._state_hist)//2

                    four_open_now = _maj("four_ext", lambda n: n == 4)    # four fingers clearly extended
                    fist_now      = _maj("is_fist", lambda b: b is True)

                    # Smooth velocities (last two samples) for direction
                    vy_sm = 0.0
                    if len(self._state_hist) >= 2:
                        vy_sm = sum(s["vy"] for s in list(self._state_hist)[-2:]) / 2.0

                    # ======= SCROLL: single-finger pose =======
                    # index-only => scroll up; pinky-only => scroll down
                    idx_only  = feats.get("ext_idx")  and not feats.get("ext_mid") and not feats.get("ext_ring") and not feats.get("ext_pky") and not feats.get("ext_thumb", False)
                    pky_only  = feats.get("ext_pky")  and not feats.get("ext_idx") and not feats.get("ext_mid")  and not feats.get("ext_ring") and not feats.get("ext_thumb", False)

                    # Add a tiny motion/deadzone guard so random jitter doesn't scroll
                    # Use smoothed vertical velocity if you already compute it (vy_sm), else fallback to vy
                    vy_used = vy_sm if 'vy_sm' in locals() else vy

                    if idx_only:
                        # pointer up -> scroll up (gentle, frequent ticks)
                        self._emit("scroll_up", cooldown=0.01)
                    elif pky_only:
                        # pinky up -> scroll down
                        self._emit("scroll_down", cooldown=0.01)

                    # ======= ZOOM: 3-4-fingers up/down by motion =======
                    # Require clear 3-4-finger pose AND vertical motion to avoid accidental triggers.
                    if (four_ext >= 3 and four_ext <= 4) and abs(vy_sm) > 0.9 and abs(vy_sm) > abs(vx)*1.2:
                        if vy_sm < 0:
                            self._emit("zoom_in", cooldown=0.5)   # 4-fingers move up
                        else:
                            self._emit("zoom_out", cooldown=0.5)  # 4-fingers move down

                    # history by horizontal swipes with open hand (>=3 fingers)
                    if four_ext == 5 and abs(vx) > 1.2 and abs(vx) > abs(vy)*1.3:
                        if vx > 0:
                            self._emit("history_forward")
                        else:
                            self._emit("history_back")

                    # tab switching with two fingers extended
                    if four_ext == 2 and abs(vx) > 1.0 and abs(vx) > abs(vy)*1.2:
                        if vx > 0:
                            self._emit("next_tab")
                        else:
                            self._emit("prev_tab")

                    # app switcher: require a steady open hand (≥3 fingers) for 3s to start
                    if not self._mode_appswitch:
                        if four_ext >= 5 and (abs(vx) + abs(vy) < 0.3):
                            if self._open_hand_start_t is None:
                                # start timing the hold
                                self._open_hand_start_t = t
                            elif t - self._open_hand_start_t >= 2.0:
                                # held steady for 3s → enter app switcher
                                self._emit("app_switcher_start")
                                self._mode_appswitch = True
                                self._mode_started_t = t
                                self._open_hand_start_t = None  # reset timer
                        else:
                            # not a steady open hand → reset timer
                            self._open_hand_start_t = None  

                    elif self._mode_appswitch:
                        # navigate by horizontal motion         
                        if abs(vx) > 1.0 and abs(vx) > abs(vy):
                            if vx > 0:
                                self._emit("app_switcher_next")
                            else:
                                self._emit("app_switcher_prev")

                        # commit when fist (0 fingers)
                        if is_fist:
                            self._emit("app_switcher_commit")
                            self._mode_appswitch = False
                            self._open_hand_start_t = None  # safety reset
                else:
                    self._last_t = None
                    self._centroid_hist.clear()
                    self._last_pinch_d = None

                # run ~30 fps without UI
                time.sleep(0.001)
        finally:
            try:
                cap.release()
            except Exception:
                pass
            try:
                hands.close()
            except Exception:
                pass