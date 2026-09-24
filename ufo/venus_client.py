"""UI-Venus client: semantic UI grounding fused with WinRT OCR boxes.

WHY THIS EXISTS
---------------
The UFO bridge needs to answer "where do I click for label X?". OCR alone
fails on icon-only controls, and a vision model alone is ambiguous when the
same label appears several times. Venus (UI-Venus-2-9B on gx10) resolves
*which* element is meant; OCR supplies exact pixel boxes. We therefore:

  1. ask Venus for a click point,
  2. correct its x into image pixels  (Venus emits x NORMALISED to 0-1000),
  3. snap that point onto the nearest OCR box with a matching label when one
     exists (kills multi-instance ambiguity + sub-pixel drift),
  4. report the strategy that produced the result.

Measured on 10 real Telegram captures (bench_venus2.py):
    raw Venus point      : 0/10 within 25px, median error 253px
    x-corrected          : 8/10 within 25px, median error   6px
    + OCR snap           : resolves the remaining multi-instance misses

Coordinate convention (empirically verified, see bench_venus2.py):
    Venus returns x in [0, 1000] regardless of the image width, and y in
    absolute pixels of the supplied image.  x_px = x_venus / 1000 * width.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

VENUS_URL = os.environ.get("VENUS_URL", "http://100.67.13.78:8002/v1")
VENUS_MODEL = os.environ.get("VENUS_MODEL", "ui-venus")
OCR_PS1 = os.environ.get(
    "UFO_OCR_PS1",
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ocr_shot.ps1")

Box = Tuple[int, int, int, int, str]   # x, y, w, h, text


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
def ocr_words(png_path: str, timeout: int = 240) -> List[Box]:
    """Run the WinRT OCR helper and return word boxes (x, y, w, h, text)."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR_PS1, png_path],
            capture_output=True, timeout=timeout)
    except Exception:
        return []
    out = (proc.stdout or b"").decode("utf-8", "replace")
    boxes: List[Box] = []
    for line in out.splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s+(\d+)\]\s+(.*)", line)
        if m:
            boxes.append((int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)),
                          m.group(5).strip().strip("'\"")))
    return boxes


def _centre(box: Box) -> Tuple[float, float]:
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def group_phrases(boxes: Sequence[Box], max_gap: int = 26,
                  same_line: int = 8) -> List[Box]:
    """Merge adjacent word boxes into phrase boxes (left-to-right, per line).

    WinRT OCR emits one box per WORD, so a UI label like "General Horoscopes"
    arrives as two boxes and can never match as a phrase. Grouping them gives
    phrase-level boxes with the union geometry, which is what label lookup
    actually needs (and clicking the union centre is more robust than clicking
    one word of the label).
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: (b[1], b[0]))
    out: List[Box] = []
    cur: List[Box] = []

    def flush():
        if not cur:
            return
        x0 = min(b[0] for b in cur)
        y0 = min(b[1] for b in cur)
        x1 = max(b[0] + b[2] for b in cur)
        y1 = max(b[1] + b[3] for b in cur)
        text = " ".join(b[4] for b in sorted(cur, key=lambda b: b[0]))
        out.append((x0, y0, x1 - x0, y1 - y0, text))
        cur.clear()

    for b in ordered:
        if not cur:
            cur.append(b)
            continue
        prev = cur[-1]
        same_row = abs(b[1] - prev[1]) <= same_line
        gap = b[0] - (prev[0] + prev[2])
        if same_row and 0 <= gap <= max_gap:
            cur.append(b)
        else:
            flush()
            cur.append(b)
    flush()
    return out


# --------------------------------------------------------------------------
# Venus
# --------------------------------------------------------------------------
def _post_json(url: str, payload: Dict[str, Any], timeout: int = 300) -> Dict:
    import urllib.request
    req = urllib.request.Request(
        url, data=__import__("json").dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return __import__("json").loads(resp.read().decode())


def venus_point(png_path: str, label: str, *,
                url: str = VENUS_URL,
                model: str = VENUS_MODEL,
                reasoning: bool = False,
                temperature: Optional[float] = None,
                max_tokens: int = 48) -> Optional[Tuple[float, float]]:
    """Return Venus' click point for `label` in IMAGE PIXELS, or None.

    COORDINATE CONVENTION (measured, see bench_venus2.py / bench_icons.py):
    Venus emits BOTH axes NORMALISED to 0-1000 relative to the image's own
    width and height, so

        x_px = x_venus / 1000 * image_width
        y_px = y_venus / 1000 * image_height

    Verified on 1438x1000 Telegram captures (median 6px error) and on
    938x842 captures where the UIA rects of icon buttons are matched within
    0-2px. Do NOT hardcode the image size: read it from the file.
    """
    from PIL import Image
    with Image.open(png_path) as im:
        width, height = im.size
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()

    prompt = (f"Locate the UI element labelled '{label}' in this screenshot. "
              "Reply with only its click point as (x, y).")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt}]}],
        "temperature": 0.0 if temperature is None else temperature,
        "max_tokens": max_tokens,
    }
    if not reasoning:
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    data = _post_json(url.rstrip("/") + "/chat/completions", payload, 300)
    txt = (data["choices"][0]["message"].get("content") or "")
    m = re.search(r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?", txt)
    if not m:
        return None
    vx, vy = float(m.group(1)), float(m.group(2))
    return vx / 1000.0 * width, vy / 1000.0 * height


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------
@dataclass
class LocateResult:
    found: bool
    x: float = 0.0
    y: float = 0.0
    strategy: str = "none"
    label: str = ""
    venus_raw: Optional[Tuple[float, float]] = None
    venus_px: Optional[Tuple[float, float]] = None
    snapped_box: Optional[Box] = None
    snap_distance: Optional[float] = None
    seconds: float = 0.0
    note: str = ""
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found, "x": round(self.x, 1), "y": round(self.y, 1),
            "strategy": self.strategy, "label": self.label,
            "venus_px": (list(self.venus_px) if self.venus_px else None),
            "snap_distance": (round(self.snap_distance, 1)
                              if self.snap_distance is not None else None),
            "seconds": round(self.seconds, 2), "note": self.note,
        }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()

def _label_matches(needle: str, text: str) -> bool:
    """STRICT label matching.

    Deliberately conservative: a false match is far more damaging than a miss,
    because a miss hands the decision to the vision model (which is accurate)
    whereas a false match clicks the wrong control.

      * exact (normalised) equality of the whole phrase, or
      * the single-word needle equals the phrase, or
      * the needle is a whole-word prefix/substring of a SHORT phrase.

    A long descriptive query ("the back arrow navigation button") will not
    fuzzy-match short OCR words, so it correctly falls through to the vision
    model instead of snapping onto an unrelated character.
    """
    n, t = _norm(needle), _norm(text)
    if not n or not t:
        return False
    if n == t:
        return True
    nw, tw = n.split(), t.split()
    if len(nw) == 1 and len(tw) == 1:
        return n == t
    if len(nw) == 1 and len(tw) <= 3:
        return n in tw            # needle is one of the phrase's words
    if len(nw) > 1 and len(tw) <= 3:
        return n in t              # needle is a sub-phrase of the box
    return False



def locate(png_path: str, label: str, *,
           ocr_boxes: Optional[Sequence[Box]] = None,
           prefer: str = "auto",
           snap_radius: float = 220.0,
           url: str = VENUS_URL) -> LocateResult:
    """Locate `label` on the screenshot.

    Policy (prefer="auto", the default):

      * >=1 exact OCR match, exactly one instance
          -> trust OCR. WinRT word boxes are pixel-exact for text; a vision
             point that disagrees wildly is a semantic false positive (e.g.
             Venus read the chat message titled "General Horoscopes" instead
             of the actionable info-panel link of the same name).
      * >=1 exact OCR match, SEVERAL instances
          -> ask Venus which one is meant and take the nearest box. Venus is
             the disambiguator; OCR still supplies the pixels.
      * 0 OCR matches (icon-only controls, or the caller described the target
        semantically rather than quoting its label)
          -> use the Venus point directly. This is the case OCR cannot solve
          at all and the reason the vision model is in the loop.

    prefer="venus" forces the raw vision point; "ocr" never calls the model.
    The chosen box's distance to the Venus point is reported as `agreement`,
    which is a usable confidence signal for the agent.
    """
    t0 = time.time()
    res = LocateResult(found=False, label=label)

    boxes = list(ocr_boxes) if ocr_boxes is not None else ocr_words(png_path)
    # Word boxes for reporting, PHRASE boxes for matching ("General Horoscopes"
    # is two OCR words but one label).
    cands = [b for b in group_phrases(boxes)
             if _label_matches(label, b[4])] or \
           [b for b in boxes if _label_matches(label, b[4])]

    if prefer == "ocr":
        if cands:
            best = max(cands, key=lambda b: b[2] * b[3])
            cx, cy = _centre(best)
            res.found, res.x, res.y = True, cx, cy
            res.strategy, res.snapped_box = "ocr", best
            res.seconds = time.time() - t0
            return res
        res.note = "label not present in OCR output"
        res.seconds = time.time() - t0
        return res

    # ---- ask the vision model (always, so we can report agreement) -------
    try:
        raw = venus_point(png_path, label, url=url)
    except Exception as exc:
        raw = None
        res.note = f"venus unavailable: {type(exc).__name__}"
    res.venus_px = raw

    if prefer == "venus":
        if raw:
            res.found, res.x, res.y = True, raw[0], raw[1]
            res.strategy = "venus"
        elif cands:
            best = max(cands, key=lambda b: b[2] * b[3])
            cx, cy = _centre(best)
            res.found, res.x, res.y = True, cx, cy
            res.strategy, res.snapped_box = "ocr-fallback", best
        res.seconds = time.time() - t0
        return res

    # ---- prefer="auto" ----------------------------------------------------
    def _dist(b):
        bx, by = _centre(b)
        return ((bx - raw[0]) ** 2 + (by - raw[1]) ** 2) ** 0.5 if raw else 1e9

    if not cands:
        # OCR blind -> this is exactly what the vision model is for.
        if raw:
            res.found, res.x, res.y = True, raw[0], raw[1]
            res.strategy = "venus-only"
        res.seconds = time.time() - t0
        return res

    res.candidates = [{"text": b[4], "box": [b[0], b[1], b[2], b[3]],
                       "dist": round(_dist(b), 1)} for b in cands]

    if len(cands) == 1:
        best = cands[0]
        res.strategy = "ocr-sole-match"
    else:
        best = min(cands, key=_dist)
        res.strategy = "venus-disambiguated"

    bx, by = _centre(best)
    res.found, res.x, res.y = True, bx, by
    res.snapped_box = best
    res.snap_distance = _dist(best)
    if raw and res.snap_distance and res.snap_distance > snap_radius:
        res.note = (f"venus point disagreed by {res.snap_distance:.0f}px; "
                    "used the OCR box (pixel-exact)")
    res.seconds = time.time() - t0
    return res


# --------------------------------------------------------------------------
# OmniParser V2 (YOLO icon detector + Florence-2 captioner) on gx10
# --------------------------------------------------------------------------
OMNIPARSER_URL = os.environ.get("OMNIPARSER_URL",
                                "http://100.67.13.78:7861").rstrip("/")


def omniparser_elements(png_path: str, *, url: str = OMNIPARSER_URL,
                        use_paddleocr: bool = True,
                        imgsz: int = 1024) -> List[Dict[str, Any]]:
    """Parse a screenshot into semantic elements (boxes in absolute pixels).

    Complements Venus: OmniParser enumerates EVERY control it sees with an
    icon caption (150 elements on a typical Telegram window in ~7s), whereas
    Venus answers one grounding question at a time.
    """
    import json as _json
    import urllib.request as _ur
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()
    payload = {"image_b64": b64, "use_paddleocr": use_paddleocr, "imgsz": imgsz}
    req = _ur.Request(url + "/api/parse", data=_json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with _ur.urlopen(req, timeout=600) as r:
        data = _json.loads(r.read().decode())
    if "elements" not in data:
        raise RuntimeError(f"omniparser error: {str(data)[:200]}")
    return data["elements"]


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are",
    "was", "were", "its", "you", "your", "not", "but", "can", "will",
    "has", "have", "had", "they", "them", "their", "there", "here", "some",
    "other", "which", "what", "when", "where", "while", "about", "into",
    "over", "under", "next", "near", "one", "two", "use", "using", "used",
}


def _content_words(s: str) -> set:
    return {w for w in _norm(s).split()
            if len(w) > 2 and w not in _STOPWORDS}


def _caption_score(needle: str, caption: str) -> float:
    """Fraction of the needle's CONTENT words present in an OmniParser caption.

    Captions are terse and icon-like ('Toggle Box', 'Minimize', 'a button to
    close or close a window.'), so a hard threshold rejects the right answer;
    we rank by score and let the caller judge the confidence. Stopwords are
    removed first, otherwise 'the' matches half the captions.
    """
    nn = _content_words(needle)
    cn = _content_words(caption)
    if not nn or not cn:
        return 0.0
    return len(nn & cn) / len(nn)


def locate_multi(png_path: str, label: str, *,
                 ocr_boxes: Optional[Sequence[Box]] = None,
                 engines: Sequence[str] = ("venus", "omni"),
                 agree_px: float = 40.0) -> Dict[str, Any]:
    """Locate `label` by CROSS-VALIDATING Venus and OmniParser.

    Two independently trained models agreeing on a point is the strongest
    confidence signal available here; disagreement is a loud signal that the
    target was not really found.
    """
    boxes = list(ocr_boxes) if ocr_boxes is not None else ocr_words(png_path)
    primary = locate(png_path, label, ocr_boxes=boxes, prefer="auto")
    out: Dict[str, Any] = {"label": label, "primary": primary.as_dict()}
    est: Dict[str, Tuple[float, float]] = {}
    if "venus" in engines and primary.venus_px:
        est["venus"] = primary.venus_px
    if "omni" in engines:
        try:
            elems = omniparser_elements(png_path)
            scored = [(e, _caption_score(label, e.get("content", "")))
                      for e in elems]
            scored = [(e, s) for e, s in scored if s > 0]
            if scored:
                top = max(s for _, s in scored)
                # Terse captions produce many equal scores (several window
                # slivers all say "a button to close..."), so break ties by
                # spatial agreement with Venus. OmniParser is used to CONFIRM
                # the other model's estimate, not to argue with it.
                if primary.venus_px:
                    vx, vy = primary.venus_px

                    def _tiebreak(e):
                        return ((e["cx"] - vx) ** 2 + (e["cy"] - vy) ** 2) ** 0.5
                else:
                    def _tiebreak(e):
                        return e["bbox_xywh"][2] * e["bbox_xywh"][3]
                tied = [(e, s) for e, s in scored if s >= top - 1e-9]
                tied.sort(key=lambda t: _tiebreak(t[0]))
                best, best_score = tied[0]
                est["omniparser"] = (float(best["cx"]), float(best["cy"]))
                out["omniparser_best_score"] = round(best_score, 2)
                out["omniparser_tied_candidates"] = len(tied)
                out["omniparser_candidates"] = [
                    {"content": e.get("content", ""), "score": round(s, 2),
                     "bbox_xywh": e["bbox_xywh"], "centre": [e["cx"], e["cy"]]}
                    for e, s in sorted(
                        scored, key=lambda t: (-t[1], _tiebreak(t[0])))[:6]]
        except Exception as exc:                   # noqa: BLE001
            out["omniparser_error"] = f"{type(exc).__name__}: {exc}"

    out["estimates"] = {k: [round(v[0], 1), round(v[1], 1)]
                        for k, v in est.items()}
    if len(est) == 2:
        (ax, ay), (bx, by) = est["venus"], est["omniparser"]
        d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        out["agreement_px"] = round(d, 1)
        out["cross_validated"] = bool(d <= agree_px)
        if not primary.found:
            out["consensus"] = [round((ax + bx) / 2, 1), round((ay + by) / 2, 1)]
    return out


if __name__ == "__main__":
    import json as _json
    import sys as _sys

    if len(_sys.argv) < 3:
        print("usage: venus_client.py <png> <label> [auto|venus|ocr|multi]")
        raise SystemExit(2)
    png, lbl = _sys.argv[1], _sys.argv[2]
    mode = _sys.argv[3] if len(_sys.argv) > 3 else "auto"
    if mode == "multi":
        print(_json.dumps(locate_multi(png, lbl), indent=2))
    else:
        print(_json.dumps(locate(png, lbl, prefer=mode).as_dict(), indent=2))
