"""
UI-Venus grounding: natural-language element description -> point in a screenshot.

Two calls per lookup:
1. locate: UI-Venus returns a point in 0-1000 normalized coordinates, or [-1,-1].
2. confirm: a crop around that point with the point circled is shown back to the
   model with a yes/no question. The locator alone will happily point at a
   plausible-looking wrong element for things that aren't on screen; the
   confirm step rejects those.

Prompt and coordinate parsing follow inclusionAI/UI-Venus models/grounding/ui_venus2_gd.py.
"""
import base64
import hashlib
import io
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

LOCATE_PROMPT = (
    "Output the center point of the position corresponding to the following instruction: \n"
    "{instruction}. \n\n"
    "The output should just be the coordinates of a point, in the format [x,y]. "
    "Additionally, if the task is infeasible (e.g., the task is not related to the image), "
    "the output should be [-1,-1]."
)
CONFIRM_PROMPT = (
    "The red circle marks a point on a UI element. Is the element under the red circle "
    "'{instruction}'? Answer with only yes or no."
)
_CROP_RADIUS = 110
_CACHE_SIZE = 128


@dataclass
class GroundingResult:
    fx: float  # fraction of image width, 0-1
    fy: float  # fraction of image height, 0-1
    raw: str
    confirmed: bool


def extract_point(text: str) -> Optional[Tuple[float, float]]:
    """Parse UI-Venus output into a 0-1000 point; None when infeasible or unparseable."""
    text = (text or "").strip()
    m = re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)
    if m:
        x1, y1, x2, y2 = (float(g) for g in m.groups())
        return None if (x1 < 0 or y1 < 0) else ((x1 + x2) / 2, (y1 + y2) / 2)
    m = re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]\s*,\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)
    if m:
        x1, y1, x2, y2 = (float(g) for g in m.groups())
        return None if (x1 < 0 or y1 < 0) else ((x1 + x2) / 2, (y1 + y2) / 2)
    m = re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        return None if (x < 0 or y < 0) else (x, y)
    return None


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def confirmation_crop(img: Image.Image, fx: float, fy: float, radius: int = _CROP_RADIUS) -> Image.Image:
    """Crop around the point and circle it, as shown to the model in the confirm step."""
    w, h = img.size
    x, y = int(fx * w), int(fy * h)
    left, top = max(0, x - radius), max(0, y - radius)
    crop = img.crop((left, top, min(w, x + radius), min(h, y + radius))).copy()
    cx, cy = x - left, y - top
    ImageDraw.Draw(crop).ellipse((cx - 7, cy - 7, cx + 7, cy + 7), outline=(255, 0, 0), width=3)
    return crop


class VenusGrounder:
    def __init__(self, endpoint: str, model: str = "ui-venus", api_key: str = "sk-local", timeout: float = 60.0, client: Any = None):
        if client is None:
            from openai import OpenAI
            client = OpenAI(base_url=endpoint, api_key=api_key, timeout=timeout)
        self.client = client
        self.model = model
        self._cache: "OrderedDict[tuple, Optional[GroundingResult]]" = OrderedDict()

    def _ask(self, img: Image.Image, text: str, max_tokens: int) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _png_b64(img)}},
                {"type": "text", "text": text},
            ]}],
        )
        return r.choices[0].message.content or ""

    def locate(self, image_path: str, description: str, confirm: bool = True) -> Optional[GroundingResult]:
        """Return the confirmed point for `description`, or None if not found/not confirmed."""
        with open(image_path, "rb") as f:
            data = f.read()
        key = (hashlib.sha256(data).hexdigest(), description.strip().lower(), confirm)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        img = Image.open(io.BytesIO(data)).convert("RGB")
        raw = self._ask(img, LOCATE_PROMPT.format(instruction=description), 64)
        point = extract_point(raw)
        result: Optional[GroundingResult] = None
        if point is not None:
            fx, fy = min(max(point[0] / 1000.0, 0.0), 1.0), min(max(point[1] / 1000.0, 0.0), 1.0)
            confirmed = True
            if confirm:
                answer = self._ask(confirmation_crop(img, fx, fy), CONFIRM_PROMPT.format(instruction=description), 5)
                confirmed = answer.strip().lower().startswith("yes")
                if not confirmed:
                    logger.info(f"UI-Venus located '{description}' at ({fx:.3f},{fy:.3f}) but did not confirm it; rejecting.")
            result = GroundingResult(fx, fy, raw, confirmed) if confirmed else None
        self._cache[key] = result
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return result


_grounder: Optional[VenusGrounder] = None


def get_grounder(config: Optional[Dict[str, Any]]) -> Optional[VenusGrounder]:
    """Shared grounder built from the GROUNDING_MODEL config block, or None if disabled."""
    global _grounder
    if not config or not config.get("ENABLED") or not config.get("ENDPOINT"):
        return None
    if _grounder is None:
        _grounder = VenusGrounder(config["ENDPOINT"], model=config.get("MODEL", "ui-venus"), api_key=config.get("API_KEY", "sk-local"))
    return _grounder
