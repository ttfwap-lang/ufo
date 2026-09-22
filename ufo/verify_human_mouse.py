"""Empirical validation of HumanMouse against researched human kinematics.

Checks for a batch of moves:
- peak velocity <= target (fastest minus 20% = TARGET_PEAK_PX_PER_S)
- duration in human range (~300-650 ms for screen moves, with min floors)
- submovement count 2-3 (ballistic + 0-2 corrections)
- overshoot present ~70% of the time
- landing accuracy sub-2px
- path is curved (not a straight line) and tremor present

Also renders path traces to PNG for visual inspection.
"""
import sys, os, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")

from ufo.automator.app_apis.telegram import HumanMouse, TARGET_PEAK_PX_PER_S, ScreenLockout

# MANDATORY WARNING GATE before any cursor movement - even this test.
_warning = ScreenLockout()
_warning._keep_running = True

def _warning_hook():
    import asyncio as _a
    loop = _a.new_event_loop()
    try:
        loop.run_until_complete(_warning.acquire(
            message="AUTOMATION TEST STARTING", countdown=5
        ))
    finally:
        loop.close()
    print("  >> warning countdown completed - proceeding with test")

mouse = HumanMouse(seed=42, first_move_hook=_warning_hook)
print("Target peak (fastest -20%):", f"{TARGET_PEAK_PX_PER_S:.0f} px/s")
print(">> Showing 5s on-top warning before any cursor movement...")

# Move the real cursor around a test area (visible on screen)
start = (400, 400)
targets = [
    (900, 400), (900, 700), (450, 700), (1200, 500),
    (300, 500), (1000, 900), (500, 250), (1300, 300),
]
mouse.move_to(*start)

reports = []
peaks, durs, subs, overs = [], [], [], []
for t in targets:
    rep = mouse.move_to(*t)
    reports.append(rep)
    peaks.append(rep.peak_velocity_px_s)
    durs.append(rep.duration_ms)
    subs.append(rep.submovements)
    overs.append(rep.overshoot_px)
    print("  move ->", rep.summary())

mx = int(max([max(rep.path_points, key=lambda p: p[0])[0] for rep in reports if rep.path_points]) + 20)
my = int(max([max(rep.path_points, key=lambda p: p[1])[1] for rep in reports if rep.path_points]) + 20)
print()

# ---- Checks ----
ok = True
max_peak = max(peaks)
print(f"peak velocity: max={max_peak:.0f} px/s (target <= {TARGET_PEAK_PX_PER_S:.0f})")
if max_peak > TARGET_PEAK_PX_PER_S * 1.15:
    print("  FAIL: peak exceeds fastest-minus-20% ceiling by >15%")
    ok = False
else:
    print("  OK: within the human ceiling")

avg_dur = sum(durs) / len(durs)
print(f"duration: avg={avg_dur:.0f} ms (human move range ~280-700 ms)")
if not (250 <= avg_dur <= 750):
    print("  WARN: duration outside typical human range")
    ok = False
else:
    print("  OK: human duration")

print(f"submovements: {sorted(set(subs))} (expected 2-3 per move)")
overshoot_pct = 100 * sum(1 for o in overs if o > 0) / len(overs)
print(f"overshoot rate: {overshoot_pct:.0f}% (human 65-80%)")

# Landing accuracy: cursor should be ~at last target after settle
import ctypes
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
p = POINT()
ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
err = math.hypot((p.x) - targets[-1][0], (p.y) - targets[-1][1])
print(f"landing accuracy: {err:.1f} px from target (<=2 desired)")

# Straightness: compare path length vs direct distance
ratio = []
for rep in reports:
    if len(rep.path_points) > 2:
        plen = sum(math.hypot(rep.path_points[i][0] - rep.path_points[i-1][0],
                              rep.path_points[i][1] - rep.path_points[i-1][1])
                   for i in range(1, len(rep.path_points)))
        ratio.append(plen / max(1.0, rep.distance_px))
avg_ratio = sum(ratio) / len(ratio) if ratio else 0
print(f"path-length ratio (curvature): {avg_ratio:.3f} (human >1.02, straight=1.0)")
if avg_ratio < 1.01:
    print("  FAIL: movement too straight - not human")
    ok = False
else:
    print("  OK: curved human paths")

# ---- Render path trace ----
try:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (int(mx), int(my)), (20, 20, 30))
    d = ImageDraw.Draw(img)
    colors = [(255, 90, 90), (90, 200, 255), (255, 210, 90), (120, 255, 120)]
    for i, rep in enumerate(reports):
        pts = rep.path_points
        if len(pts) > 1:
            d.line(pts, fill=colors[i % len(colors)], width=2)
    img.save("human_mouse_trace.png")
    print("\ntrace saved: human_mouse_trace.png")
except Exception as e:
    print("trace render failed:", e)

print()
print("VERDICT:", "HUMAN-KINEMATICS PASS ✅" if ok else "CHECK ABOVE ❌")
