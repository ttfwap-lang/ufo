"""In-process Windows.Media.Ocr (WinRT) - word boxes in tens of milliseconds.

Replaces spawning `powershell ocr_shot.ps1` per call (0.65-0.74 s each, measured,
almost all of it interpreter + WinRT start-up) with a resident engine. Same
output as that script: WORD-level rectangles, absolute pixels of the image.
Windows only; import fails cleanly elsewhere so callers can fall back.
"""
from __future__ import annotations

import asyncio
import threading
from typing import List, Tuple

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

Word = Tuple[int, int, int, int, str]   # x, y, w, h, text  (same as venus_client.Box)

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            eng = OcrEngine.try_create_from_language(Language("en-US"))
            if eng is None:
                eng = OcrEngine.try_create_from_user_profile_languages()
            if eng is None:
                raise RuntimeError("no WinRT OCR language pack installed")
            _engine = eng
        return _engine


async def _recognize(png: bytes) -> List[List[Word]]:
    """Recognise and return one list of word boxes per OCR line."""
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await _get_engine().recognize_async(bitmap)
    lines: List[List[Word]] = []
    for line in result.lines:
        words: List[Word] = []
        for word in line.words:
            r = word.bounding_rect
            if r.width > 0 and r.height > 0:
                words.append((int(r.x), int(r.y), int(r.width), int(r.height), word.text))
        if words:
            lines.append(words)
    return lines


def ocr_words(png_bytes: bytes) -> List[Word]:
    """Word boxes for an encoded image (PNG/JPEG bytes). Blocking."""
    return [w for line in asyncio.run(_recognize(png_bytes)) for w in line]


def ocr_phrases(png_bytes: bytes, gap_factor: float = 1.5) -> List[Tuple[Tuple[int, int, int, int], str]]:
    """Phrase boxes ((x1, y1, x2, y2), text): each OCR line split where the gap
    between neighbouring words exceeds `gap_factor` x the line's word height.

    A WinRT "line" can span unrelated UI (a sidebar label and a header on the
    same row), and those must stay separate elements to be clickable targets.
    """
    phrases = []
    for line in asyncio.run(_recognize(png_bytes)):
        line = sorted(line, key=lambda w: w[0])
        group = [line[0]]
        for w in line[1:]:
            prev = group[-1]
            if w[0] - (prev[0] + prev[2]) > gap_factor * max(prev[3], w[3]):
                phrases.append(_union(group))
                group = []
            group.append(w)
        phrases.append(_union(group))
    return phrases


def _union(words: List[Word]):
    x1 = min(w[0] for w in words)
    y1 = min(w[1] for w in words)
    x2 = max(w[0] + w[2] for w in words)
    y2 = max(w[1] + w[3] for w in words)
    return (x1, y1, x2, y2), " ".join(w[4] for w in words)
