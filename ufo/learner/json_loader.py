# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import json
import logging
from typing import Dict, List

from langchain_core.documents import Document

from . import basic

logger = logging.getLogger(__name__)


class JsonLoader(basic.BasicDocumentLoader):
    """
    Class to load JSON documents.
    """

    def __init__(self, directory: str = None):
        """
        Create a new JSONLoader.
        """

        super().__init__()
        self.extensions = ".json"
        self.directory = directory

    @staticmethod
    def load_json_document(file: str) -> Dict:
        """
        Load the JSON document from the given file path.
        :param file: The file path to load the JSON document from.
        :return: The JSON document.
        """
        with open(file, "r", encoding="utf-8") as f:
            try:
                document = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON file {file}")
                document = {}

        return document

    def construct_document(self):
        """
        Construct a langchain document list.
        Each json file is a document with the following structure:
        {
            "request": "The user request",
            "guidance": ["The step-by-step guidance to fulfill the request"]
        }
        :return: The langchain document list.
        """
        documents = []
        for file in self.load_file_name():

            document = self.load_json_document(file)
            request = document.get("request", "")
            guidance_steps = document.get("guidance", [])
            guidance = "\n".join([step for step in guidance_steps])

            metadata = {"title": request, "summary": request, "text": guidance}
            document = Document(page_content=request, metadata=metadata)

            documents.append(document)
        return documents
