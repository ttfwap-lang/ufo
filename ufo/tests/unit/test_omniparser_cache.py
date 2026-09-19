from PIL import Image

from ufo.automator.ui_control.grounding import omniparser as om
from ufo.llm.grounding_model import omniparser_service as svc


class _CountingService:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def chat_completion(self, *args):
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return (None, '{"type": "icon", "bbox": [0.1, 0.1, 0.2, 0.2], "interactivity": true, "content": "OK"}')


def _img(path, color):
    Image.new("RGB", (40, 40), color).save(path)
    return str(path)


def setup_function(_):
    om._PREDICT_CACHE.clear()


def test_same_pixels_hit_cache(tmp_path):
    s = _CountingService()
    g = om.OmniparserGrounding(service=s)
    a = _img(tmp_path / "a.png", "white")
    b = _img(tmp_path / "b.png", "white")  # different path, identical pixels
    assert g.predict(a) == g.predict(b)
    assert s.calls == 1


def test_changed_pixels_or_params_miss(tmp_path):
    s = _CountingService()
    g = om.OmniparserGrounding(service=s)
    a = _img(tmp_path / "a.png", "white")
    g.predict(a)
    g.predict(_img(tmp_path / "c.png", "black"))
    g.predict(a, box_threshold=0.3)
    assert s.calls == 3


def test_cached_results_are_copies(tmp_path):
    g = om.OmniparserGrounding(service=_CountingService())
    a = _img(tmp_path / "a.png", "white")
    g.predict(a)[0]["content"] = "mutated"
    assert g.predict(a)[0]["content"] == "OK"


def test_failures_are_not_cached(tmp_path):
    bad = _CountingService(fail=True)
    a = _img(tmp_path / "a.png", "white")
    assert om.OmniparserGrounding(service=bad).predict(a) == []
    good = _CountingService()
    assert om.OmniparserGrounding(service=good).predict(a)
    assert good.calls == 1


def test_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(om, "_PREDICT_CACHE_SIZE", 2)
    g = om.OmniparserGrounding(service=_CountingService())
    for i, color in enumerate(["red", "green", "blue"]):
        g.predict(_img(tmp_path / f"{i}.png", color))
    assert len(om._PREDICT_CACHE) == 2


def test_client_shared_per_endpoint(monkeypatch):
    built = []
    monkeypatch.setattr(svc, "Client", lambda endpoint: built.append(endpoint) or object())
    monkeypatch.setattr(svc, "_clients", {})
    assert svc.get_omniparser("http://x:1") is svc.get_omniparser("http://x:1")
    assert svc.get_omniparser("http://y:2") is not svc.get_omniparser("http://x:1")
    assert built == ["http://x:1", "http://y:2"]
