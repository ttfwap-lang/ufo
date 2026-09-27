# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import base64
import json
import threading
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ufo.llm.base import BaseService

_clients: Dict[str, "OmniParser"] = {}
_clients_lock = threading.Lock()


def get_omniparser(endpoint: str) -> "OmniParser":
    """Shared OmniParser client per endpoint.

    Building a client performs a network handshake, and agents rebuild their
    strategies every step, so reuse one client for the whole process.
    """
    with _clients_lock:
        client = _clients.get(endpoint)
        if client is None:
            client = OmniParser(endpoint)
            _clients[endpoint] = client
        return client


def _load_gradio_client():
    """Import gradio_client lazily.

    The UFO host (Windows) does not need - and often does not have - the
    gradio_client package: it talks to the OmniParser service over plain HTTP
    against ``POST /api/parse`` (see gx10_runner/omniparser_api.py). Importing
    it at module scope used to raise ImportError on the automation host, which
    broke the whole vision-fallback chain at import time.
    """
    from gradio_client import Client, handle_file  # noqa: PLC0415

    return Client, handle_file


class OmniParser(BaseService):
    """
    The parser for the OmniParser.

    Two transports are supported, in order of preference:

    1. **REST** (``POST <endpoint>/api/parse``) - the purpose-built wrapper
       deployed by ``gx10_runner/deploy_omniparser.sh``. It returns clean JSON
       with ABSOLUTE PIXEL boxes and needs no extra Python package on the
       caller. This is the normal path.
    2. **gradio** - the stock ``gradio_demo.py`` UI, used only if the REST
       endpoint is absent. Requires ``gradio_client`` to be installed.

    Both are normalised to the same output: a list of per-element dicts whose
    ``bbox`` is ``[x0, y0, x1, y1]`` as FRACTIONS of the image, which is what
    ``OmniparserGrounding._calculate_absolute_coordinates`` consumes.
    """

    def __init__(self, endpoint: str):
        """
        Initialize the OmniParser service.
        :param endpoint: The endpoint address of the OmniParser service.
        """
        self.endpoint = endpoint.rstrip("/")
        self._rest_available: Optional[bool] = None
        self._gradio_client: Any = None
        self._handle_file: Any = None

    # -- REST transport -----------------------------------------------------
    def _rest_parse(
        self,
        image_path: str,
        box_threshold: float,
        iou_threshold: float,
        use_paddleocr: bool,
        imgsz: int,
    ) -> List[Dict[str, Any]]:
        """POST /api/parse and normalise the response to fractional bboxes."""
        with open(image_path, "rb") as handle:
            b64 = base64.b64encode(handle.read()).decode("ascii")

        payload = {
            "image_b64": b64,
            "box_threshold": box_threshold,
            "iou_threshold": iou_threshold,
            "use_paddleocr": use_paddleocr,
            "imgsz": imgsz,
        }
        request = urllib.request.Request(
            self.endpoint + "/api/parse",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))

        width = float(data.get("width") or 0) or 1.0
        height = float(data.get("height") or 0) or 1.0

        elements: List[Dict[str, Any]] = []
        for raw in data.get("elements") or []:
            box = raw.get("bbox_xyxy")
            if not box or len(box) != 4:
                box = raw.get("bbox_xywh")
                if not box or len(box) != 4:
                    continue
                x, y, w, h = box
                box = [x, y, x + w, y + h]
            x0, y0, x1, y1 = (float(v) for v in box)
            content = raw.get("content") or ""
            elements.append(
                {
                    "id": raw.get("id"),
                    # fractions of the image, matching the legacy gradio output
                    "bbox": [
                        x0 / width,
                        y0 / height,
                        x1 / width,
                        y1 / height,
                    ],
                    "bbox_xyxy": [x0, y0, x1, y1],
                    "content": content,
                    "name": content,
                    "interactivity": True,
                }
            )
        return elements

    def _probe_rest(self) -> bool:
        """One-shot check for the REST endpoint, cached for the client's life."""
        if self._rest_available is not None:
            return self._rest_available
        try:
            request = urllib.request.Request(self.endpoint + "/api/health")
            with urllib.request.urlopen(request, timeout=10) as response:
                self._rest_available = 200 <= response.status < 300
        except Exception:  # noqa: BLE001 - any failure means "not available"
            self._rest_available = False
        return self._rest_available

    # -- gradio transport ---------------------------------------------------
    def _ensure_gradio(self):
        if self._gradio_client is None:
            Client, handle_file = _load_gradio_client()
            self._gradio_client = Client(self.endpoint)
            self._handle_file = handle_file

    def _gradio_predict(
        self, image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name
    ) -> Tuple[Any, str]:
        self._ensure_gradio()
        return self._gradio_client.predict(
            image_input=self._handle_file(filepath_or_url=image_path),
            box_threshold=box_threshold,
            iou_threshold=iou_threshold,
            use_paddleocr=use_paddleocr,
            imgsz=imgsz,
            api_name=api_name,
        )

    # -- public API ---------------------------------------------------------
    def chat_completion(
        self,
        image_path: str,
        box_threshold: float = 0.05,
        iou_threshold: float = 0.1,
        use_paddleocr: bool = True,
        imgsz: int = 640,
        api_name: str = "/process",
    ):
        """
        Get the parsed elements for an image.

        Returns a list of per-element dicts (fractional ``bbox``). If the REST
        endpoint is unavailable the stock gradio UI is used instead, and the
        legacy ``(image, markdown)`` tuple is returned for the caller to parse.
        """
        if self._probe_rest():
            try:
                return self._rest_parse(
                    image_path, box_threshold, iou_threshold, use_paddleocr, imgsz
                )
            except Exception:  # noqa: BLE001
                # Server may have restarted; re-probe and fall through to gradio.
                self._rest_available = None
                if self._probe_rest():
                    return self._rest_parse(
                        image_path, box_threshold, iou_threshold, use_paddleocr, imgsz
                    )
                raise

        try:
            return self._gradio_predict(
                image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name
            )
        except Exception:
            # The server may have restarted since this client connected.
            self._gradio_client = None
            return self._gradio_predict(
                image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name
            )
