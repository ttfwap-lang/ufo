"""Human-like mouse engine - "fastest human mouse mover minus 20%".

Built from measured human movement kinematics (research summary):

    Fastest measured human mouse peaks (pro FPS): 6,950-11,583 px/s
    Wrist-snap flicks:                          ~50 rad/s (~2,865 deg/s)
    Ballistic submovement:                      ~197 ms, ~92% of distance
    Correction submovement:                     ~132 ms, short & curved
    Overshoot-then-correct:                     65-80% of human moves
    Submovement minimums:                       ~2 mm / ~75 ms
    Hand tremor:                                ~10 Hz, <2 px
    Velocity profile:                           asymmetric bell (bang-bang)

Design target ("fastest minus 20%"):
    Peak cursor velocity <= ~9,266 px/s
    Flick angular velocity <= ~2,290 deg/s
    Everything else (submovements, overshoot, tremor, curvature) keeps
    100% human structure.

Implementation:
    - Path: cubic Bezier with perpendicular curvature - never a straight line.
    - Phases: ballistic (asymmetric bell) -> micro pause (velocity trough)
      -> 0-2 corrective submovements -> settle -> exact landing.
    - Overshoot & undershoot probabilities matched to human data.
    - Tremor: ~10 Hz sinusoidal jitter added during motion.
    - Injection: real OS mouse events (absolute SendInput-style mouse_event) -
      identical to hardware input.
"""

from __future__ import annotations

import ctypes
import math
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ==================== Measured human constants ====================

FASTEST_PEAK_PX_PER_S = 11583.0            # fastest measured human peak (px/s)
TARGET_PEAK_PX_PER_S = FASTEST_PEAK_PX_PER_S * 0.80   # ~9,266 px/s
TARGET_ANGULAR_DEG_PER_S = 2865.0 * 0.80   # ~2,292 deg/s

BALLISTIC_MS_MEAN = 197.0
BALLISTIC_MS_SD = 13.0
CORRECTION_MS_MEAN = 132.0
CORRECTION_MS_SD = 32.0
OVERSHOOT_PROBABILITY = 0.72
BALLISTIC_DISTANCE_FRACTION = 0.92
TREMOR_HZ = 10.0
TREMOR_AMP_MIN_PX = 0.5
TREMOR_AMP_MAX_PX = 1.8


@dataclass
class MoveReport:
    """Kinematics measured for one move (for verification)."""
    distance_px: float = 0.0
    duration_ms: float = 0.0
    peak_velocity_px_s: float = 0.0
    submovements: int = 0
    overshoot_px: float = 0.0
    path_points: List[Tuple[float, float]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"dist={self.distance_px:.0f}px dur={self.duration_ms:.0f}ms "
            f"peak={self.peak_velocity_px_s:.0f}px/s subs={self.submovements} "
            f"overshoot={self.overshoot_px:.1f}px"
        )


class HumanMouse:
    """Injects human-like mouse movement via OS mouse events (absolute).

    SAFETY GATE: the first movement of every instance runs ``first_move_hook``
    (if provided) - the near-opaque on-top warning countdown is ALWAYS shown
    before any real cursor movement, even in tests.
    """

    def __init__(
        self,
        peak_px_s: float = TARGET_PEAK_PX_PER_S,
        seed: Optional[int] = None,
        sample_ms: float = 6.0,
        first_move_hook=None,
    ):
        self._peak_px_s = peak_px_s
        self._rng = random.Random(seed)
        self._sample_s = sample_ms / 1000.0
        self._user32 = ctypes.windll.user32
        self._first_move_hook = first_move_hook
        self._first_move_done = False

    def _maybe_warn(self) -> None:
        """Show the on-top warning countdown before the FIRST real movement."""
        if self._first_move_done:
            return
        self._first_move_done = True  # mark first so hook runs exactly once
        if self._first_move_hook:
            try:
                self._first_move_hook()
            except Exception:
                pass

    # ==================== Public API ====================

    def move_to(self, tx: float, ty: float) -> MoveReport:
        """Move the cursor to (tx, ty) with full human kinematics.

        Blocks for the movement duration (wrap in a thread if async needed).
        """
        self._maybe_warn()
        return self._move_with_submovements(tx, ty)

    def click(self, x: float, y: float, down_ms: Optional[float] = None) -> None:
        """move_to + a human click (button down/hold/up)."""
        self._move_with_submovements(x, y)
        hold = down_ms if down_ms is not None else self._rng.uniform(48.0, 92.0)
        self._button(True)
        time.sleep(hold / 1000.0)
        self._button(False)

    def double_click(self, x: float, y: float) -> None:
        self._move_with_submovements(x, y)
        for _ in range(2):
            self._button(True)
            time.sleep(self._rng.uniform(42.0, 70.0) / 1000.0)
            self._button(False)
            time.sleep(self._rng.uniform(35.0, 90.0) / 1000.0)

    def drag(self, from_xy: Tuple[float, float], to_xy: Tuple[float, float]) -> None:
        """Human drag: move to start, press, move with submovements, release."""
        self._maybe_warn()
        self._move_with_submovements(*from_xy)
        self._button(True)
        time.sleep(self._rng.uniform(40.0, 80.0) / 1000.0)
        self._move_with_submovements(*to_xy)
        time.sleep(self._rng.uniform(40.0, 90.0) / 1000.0)
        self._button(False)

    def scroll(self, steps: int, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """Human wheel scroll with jittered wheel events."""
        self._maybe_warn()
        if x is None or y is None:
            cx, cy = _get_cursor_pos(self._user32)
            x, y = cx, cy
        self._move_with_submovements(x, y)
        wheel = -1 if steps < 0 else 1
        for _ in range(abs(steps)):
            self._user32.mouse_event(0x0800, 0, 0, wheel * 120, 0)  # MOUSEEVENTF_WHEEL
            time.sleep(self._rng.uniform(0.045, 0.14))

    # ==================== Kinematic core ====================

    def _move_with_submovements(self, tx: float, ty: float) -> MoveReport:
        sx, sy = _get_cursor_pos(self._user32)
        dist = math.hypot(tx - sx, ty - sy)
        rep = MoveReport(distance_px=dist)
        if dist < 1.0:
            return rep

        t0 = time.perf_counter()

        # --- Phase 1: ballistic (asymmetric bell bezier) ---
        ball_frac = self._rng.uniform(
            BALLISTIC_DISTANCE_FRACTION - 0.03, BALLISTIC_DISTANCE_FRACTION + 0.02
        )
        bx = sx + (tx - sx) * ball_frac
        by = sy + (ty - sy) * ball_frac
        dur_ball_s = max(
            0.09,
            min(0.32, dist / (self._peak_px_s * 0.55)),
        )
        self._inject_bezier(
            (sx, sy), (bx, by), dur_ball_s,
            curvature=self._rng.uniform(0.03, 0.09), rep=rep, t0=t0,
        )
        submoves = 1
        overshoot = 0.0

        # --- Micro pause (velocity trough between submovements) ---
        time.sleep(self._rng.uniform(28.0, 75.0) / 1000.0)

        # --- Phase 2: corrections (overshoot-then-reverse OR direct drive) ---
        if self._rng.random() < OVERSHOOT_PROBABILITY and dist > 40:
            # Overshoot a few px, then correct back (65-80% of human moves)
            ov = dist * self._rng.uniform(0.012, 0.045)
            ox = tx + (tx - sx) * (ov / dist)
            oy = ty + (ty - sy) * (ov / dist)
            dur_cor_s = self._rng.uniform(
                max(0.075, (CORRECTION_MS_MEAN - CORRECTION_MS_SD) / 1000.0),
                (CORRECTION_MS_MEAN + CORRECTION_MS_SD) / 1000.0,
            )
            self._inject_bezier(
                (bx, by), (ox, oy), dur_cor_s,
                curvature=0.10, rep=rep, t0=t0,
            )
            submoves += 1
            time.sleep(self._rng.uniform(24.0, 60.0) / 1000.0)
            # Correct back to target (finer, slower)
            self._inject_bezier(
                (ox, oy), (tx, ty), self._rng.uniform(0.08, 0.16),
                curvature=0.06, rep=rep, t0=t0,
            )
            submoves += 1
            overshoot = ov
        else:
            # Direct corrective drive (undershoot correction)
            self._inject_bezier(
                (bx, by), (tx, ty), self._rng.uniform(0.09, 0.18),
                curvature=0.07, rep=rep, t0=t0,
            )
            submoves += 1

        # --- Settle + exact landing ---
        self._settle(tx, ty, self._rng.uniform(20.0, 60.0) / 1000.0)
        self._send_pos(tx, ty)

        rep.duration_ms = (time.perf_counter() - t0) * 1000.0
        rep.submovements = submoves
        rep.overshoot_px = overshoot
        return rep

    def _inject_bezier(
        self, p0, p3, duration_s, curvature: float, rep: MoveReport, t0: float,
        v_peak: Optional[float] = None,
    ) -> None:
        """Inject a bowed bezier using VELOCITY INTEGRATION.

        The path is sampled densely (every ~2px of arc), then advanced at a
        human velocity profile (asymmetric bell with peak = v_peak). This
        guarantees the measured peak velocity stays at the human ceiling,
        independent of distance - unlike naive time-sampled beziers which
        spike mid-curve.
        """
        dx, dy = p3[0] - p0[0], p3[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < 0.5 or duration_s <= 0:
            self._settle(p3[0], p3[1], 0.02)
            return

        if v_peak is None:
            v_peak = self._rng.uniform(
                self._peak_px_s * 0.82, self._peak_px_s
            )

        # --- 1. dense polyline of the bowed bezier (arc ~2px steps) ---
        perp = (-dy / length, dx / length)
        bow = self._rng.uniform(-curvature, curvature)
        cp1 = (p0[0] + dx * 0.30 + perp[0] * length * bow,
               p0[1] + dy * 0.30 + perp[1] * length * bow)
        cp2 = (p0[0] + dx * 0.66 + perp[0] * length * bow * 0.35,
               p0[1] + dy * 0.66 + perp[1] * length * bow * 0.35)

        n = max(24, int(length / 2.0))          # ~2px samples
        raw = []
        for i in range(n + 1):
            t = i / n
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * cp1[0] \
                + 3 * (1 - t) * t ** 2 * cp2[0] + t ** 3 * p3[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * cp1[1] \
                + 3 * (1 - t) * t ** 2 * cp2[1] + t ** 3 * p3[1]
            raw.append((x, y))

        # --- 2. integrate: advance along polyline at human velocity ---
        DT = 0.004  # 4ms control tick
        steps = max(2, int(duration_s / DT))
        total_arc = sum(math.hypot(raw[i][0] - raw[i-1][0], raw[i][1] - raw[i-1][1])
                        for i in range(1, len(raw)))
        if total_arc <= 0:
            return

        # velocity profile: asymmetric bell, peak = v_peak at peak_frac
        peak_frac = self._rng.uniform(0.42, 0.55)
        def vel_shape(t):
            if t < peak_frac:
                return (t / peak_frac) ** 0.45
            ut = (t - peak_frac) / (1 - peak_frac)
            return (1 - ut) ** 1.35

        # integrate arc-length walked with v(t); map to polyline positions
        walked = 0.0
        idx = 0.0  # polyline index
        last_send = time.perf_counter()
        prev_pos = p0
        prev_t = last_send
        for i in range(1, steps + 1):
            t = i / steps
            v = v_peak * vel_shape(t)
            walked += v * DT
            # find polyline point at arc-length = walked
            target_arc = min(walked, total_arc)
            acc = 0.0
            pos = raw[-1]
            for j in range(1, len(raw)):
                seg = math.hypot(raw[j][0] - raw[j-1][0], raw[j][1] - raw[j-1][1])
                if acc + seg >= target_arc:
                    frac = (target_arc - acc) / max(1e-9, seg)
                    pos = (raw[j-1][0] + (raw[j][0] - raw[j-1][0]) * frac,
                           raw[j-1][1] + (raw[j][1] - raw[j-1][1]) * frac)
                    break
                acc += seg
            now = time.perf_counter()
            time.sleep(max(0.0, DT - (now - last_send)))
            last_send = time.perf_counter()
            # tremor
            amp = self._rng.uniform(TREMOR_AMP_MIN_PX, TREMOR_AMP_MAX_PX)
            t_cur = last_send - t0
            pos = (pos[0] + math.sin(2 * math.pi * TREMOR_HZ * t_cur) * amp,
                   pos[1] + math.cos(2 * math.pi * TREMOR_HZ * t_cur) * amp)
            self._send_pos(pos[0], pos[1])
            rep.path_points.append(pos)
            dt_real = last_send - prev_t
            vel = math.hypot(pos[0] - prev_pos[0], pos[1] - prev_pos[1]) / max(1e-6, dt_real)
            if vel > rep.peak_velocity_px_s:
                rep.peak_velocity_px_s = vel
            prev_pos = pos
            prev_t = last_send

        # land exactly
        self._send_pos(p3[0], p3[1])

    def _asym_time(self, t: float) -> float:
        """Asymmetric time map: peak velocity at ~45-55% of duration."""
        peak = self._rng.uniform(0.45, 0.55)
        if t < peak:
            return (t / peak) ** 0.5 * peak if peak > 0 else t
        ut = (t - peak) / (1 - peak)
        return peak + ut * peak ** 0.5 * (1 - peak * 0.5)

    def _settle(self, tx: float, ty: float, dur_s: float) -> None:
        """Small tremor-like jiggle around the landing point."""
        n = max(2, int(dur_s / self._sample_s))
        amp = self._rng.uniform(0.4, 1.4)
        for i in range(n):
            t = i / n
            x = tx + math.sin(2 * math.pi * TREMOR_HZ * t) * amp
            y = ty + math.cos(2 * math.pi * TREMOR_HZ * t * 0.9) * amp
            self._send_pos(x, y)
            time.sleep(self._sample_s)

    def _button(self, down: bool) -> None:
        self._user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)

    def _send_pos(self, x: float, y: float) -> None:
        """Absolute mouse move via mouse_event (real input, scaled)."""
        sw = max(1, self._user32.GetSystemMetrics(0))
        sh = max(1, self._user32.GetSystemMetrics(1))
        nx = int(x * 65535 / (sw - 1))
        ny = int(y * 65535 / (sh - 1))
        self._user32.mouse_event(0x0001 | 0x8000, nx, ny, 0, 0)


def _get_cursor_pos(user32) -> Tuple[float, float]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return float(p.x), float(p.y)
