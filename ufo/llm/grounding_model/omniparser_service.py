# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import threading
from typing import Dict

from gradio_client import Client, handle_file
from ufo.llm.base import BaseService

_clients: Dict[str, "OmniParser"] = {}
_clients_lock = threading.Lock()


def get_omniparser(endpoint: str) -> "OmniParser":
    """Shared OmniParser client per endpoint.

    Building a gradio Client performs a network handshake, and agents rebuild
    their strategies every step, so reuse one client for the whole process.
    """
    with _clients_lock:
        client = _clients.get(endpoint)
        if client is None:
            client = OmniParser(endpoint)
            _clients[endpoint] = client
        return client


class OmniParser(BaseService):
    """
    The parser for the OmniParser.
    """

    def __init__(self, endpoint: str):
        """
        Initialize the OmniParser service.
        :param endpoint: The endpoint address of the OmniParser service.
        """
        self.endpoint = endpoint
        self.client = Client(endpoint)

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
        Get the chat completion from the OmniParser service.
        :param text: The input text.
        :return: The chat completion.
        """
        try:
            return self._predict(image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name)
        except Exception:
            # The server may have restarted since this client connected; reconnect once.
            self.client = Client(self.endpoint)
            return self._predict(image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name)

    def _predict(self, image_path, box_threshold, iou_threshold, use_paddleocr, imgsz, api_name):
        return self.client.predict(
            image_input=handle_file(filepath_or_url=image_path),
            box_threshold=box_threshold,
            iou_threshold=iou_threshold,
            use_paddleocr=use_paddleocr,
            imgsz=imgsz,
            api_name=api_name,
        )
