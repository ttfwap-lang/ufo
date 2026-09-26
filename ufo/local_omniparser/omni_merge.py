"""Merge YOLO icon boxes with OCR text boxes. Pure Python: no torch, no models.

Kept separate from service.py so the decisions can be unit-tested without
loading a GPU model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

Box = Tuple[int, int, int, int]

# An icon box swallows the OCR text inside it (its content becomes that text)
# only if it is button-sized. A sidebar-sized "icon" containing thirty labels
# must not swallow them all.
MERGE_MAX_AREA_FRAC = 0.05
MERGE_MAX_TEXTS = 3
# Fraction of a box that must lie inside another for "is inside".
INSIDE = 0.8


def area(b: Box) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def inter(a: Box, b: Box) -> int:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def clamp(b: Box, w: int, h: int) -> Box:
    return (max(0, b[0]), max(0, b[1]), min(w, b[2]), min(h, b[3]))


def merge(icons: Sequence[Box], texts: Sequence[Tuple[Box, str]],
          w: int, h: int) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Return (elements, indices needing a caption).

    Rules, in order, per icon box:
      1. >=80% of the icon lies inside one OCR box: it is the text itself
         detected twice - drop the icon.
      2. Otherwise, if it is button-sized and holds 1-3 OCR boxes, keep the icon
         with content = that text and drop those OCR boxes (no double listing).
      3. Otherwise keep it as an icon to be captioned.
    Every OCR box not absorbed becomes a text element.
    """
    elements: List[Dict[str, Any]] = []
    absorbed = set()
    to_caption: List[int] = []
    for b in icons:
        a = area(b)
        if a == 0 or any(inter(b, tb) >= INSIDE * a for tb, _ in texts):
            continue
        inside = [i for i, (tb, _) in enumerate(texts)
                  if area(tb) and inter(b, tb) >= INSIDE * area(tb)]
        content = ""
        if inside and len(inside) <= MERGE_MAX_TEXTS and a <= MERGE_MAX_AREA_FRAC * w * h:
            content = " ".join(texts[i][1] for i in inside)
            absorbed.update(inside)
        elements.append({"type": "icon", "box": b, "content": content})
        if not content:
            to_caption.append(len(elements) - 1)
    for i, (tb, text) in enumerate(texts):
        if i not in absorbed:
            elements.append({"type": "text", "box": tb, "content": text})
    return elements, to_caption
