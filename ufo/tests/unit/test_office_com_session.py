import threading
import time
from types import SimpleNamespace

import pytest

from ufo.automator.app_apis.office_com import OfficeComError, OfficeComSession


class _Receiver:
    def get_object_from_process_name(self):
        if getattr(self.client, "dead", False):
            raise RuntimeError("RPC server unavailable")
        return self.client.docs.get(self.process_name)


def _app(docs=None):
    return SimpleNamespace(docs=docs if docs is not None else {"Report": SimpleNamespace(name="Report")}, dead=False)


def test_runs_on_one_dedicated_thread():
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Report", attach=lambda p: _app())
    ids = {s.call(lambda r: threading.get_ident()) for _ in range(3)}
    assert len(ids) == 1 and threading.get_ident() not in ids


def test_resolves_document_each_call():
    app = _app()
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Report", attach=lambda p: app)
    assert s.call(lambda r: r.com_object.name) == "Report"
    app.docs["Report"] = SimpleNamespace(name="Report v2")
    assert s.call(lambda r: r.com_object.name) == "Report v2"


def test_missing_document_is_a_clear_error():
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Nope", attach=lambda p: _app())
    with pytest.raises(OfficeComError, match="No open X.EXE document"):
        s.call(lambda r: None)


def test_dead_proxy_reattaches():
    apps = [_app(), _app()]
    apps[0].dead = True
    it = iter(apps)
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Report", attach=lambda p: next(it))
    assert s.call(lambda r: r.com_object.name) == "Report"


def test_timeout_errors_without_killing_and_recovers(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil.Process, "kill", lambda self: (_ for _ in ()).throw(AssertionError("must not kill")))
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Report", timeout=0.3, attach=lambda p: _app())
    with pytest.raises(OfficeComError, match="left running"):
        s.call(lambda r: time.sleep(2))
    assert s.call(lambda r: "ok") == "ok"  # fresh worker, not queued behind the stuck one


def test_errors_propagate():
    s = OfficeComSession("X.Application", _Receiver, "X.EXE", "Report", attach=lambda p: _app())
    with pytest.raises(ValueError, match="boom"):
        s.call(lambda r: (_ for _ in ()).throw(ValueError("boom")))
