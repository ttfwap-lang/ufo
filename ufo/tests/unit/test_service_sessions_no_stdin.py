import pytest

from ufo.module.sessions.linux_session import LinuxSession
from ufo.module.sessions.mobile_session import MobileSession


@pytest.mark.parametrize("cls", [LinuxSession, MobileSession])
def test_second_request_finishes_instead_of_prompting(cls, monkeypatch):
    import ufo.module.interactor as interactor
    monkeypatch.setattr(interactor, "new_request", lambda: (_ for _ in ()).throw(AssertionError("prompted stdin")))
    s = cls.__new__(cls)
    s._init_request = "report uptime"
    s._finish = False
    monkeypatch.setattr(cls, "total_rounds", property(lambda self: 1), raising=False)
    assert s.next_request() == ""
    assert s._finish is True
