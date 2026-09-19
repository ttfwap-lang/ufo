import sys, types
from unittest.mock import MagicMock
import importlib.abc, importlib.machinery

sys.path.insert(0, r'C:\Users\lnxzf\Desktop\projects\ufo')

# List of top-level third-party packages we allow to be auto-mocked when
# missing, so that unrelated heavy/optional deps don't block collection of
# tests targeting ufo.module/ufo.agents/ufo.prompter logic.
_AUTO_MOCK_PREFIXES = (
    "langchain", "chromadb", "gradio_client", "html2text", "pyautogui",
    "easyocr", "paddleocr", "paddle", "paddlepaddle", "pywinauto",
    "comtypes", "uiautomation", "pytesseract", "keyboard", "mss",
    "pynput", "cv2", "fastmcp", "art", "google", "vertexai",
    "anthropic", "openai", "playwright", "selenium", "torch",
    "torchvision", "transformers", "onnxruntime", "supervision",
)


class _AutoMockFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_module(self, fullname, path=None):
        top = fullname.split(".")[0]
        if any(top == p or top.startswith(p) for p in _AUTO_MOCK_PREFIXES):
            return self
        return None

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        mod = types.ModuleType(fullname)
        mod.__path__ = []  # pretend it's a package so submodule imports work
        mock = MagicMock()
        mod.__getattr__ = lambda name: getattr(mock, name)
        sys.modules[fullname] = mod
        return mod

    def find_spec(self, fullname, path, target=None):
        top = fullname.split(".")[0]
        if top in _AUTO_MOCK_PREFIXES:
            return importlib.machinery.ModuleSpec(fullname, self)
        return None

    def create_module(self, spec):
        return self.load_module(spec.name)

    def exec_module(self, module):
        pass


sys.meta_path.insert(0, _AutoMockFinder())

import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
