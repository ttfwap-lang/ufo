from types import SimpleNamespace

from ufo.agents.processors.strategies.goal_verifier import GoalVerdict
from ufo.module.sessions.session import Session


def _session(results, verdict=None):
    s = Session.__new__(Session)
    s._results = results
    s._host_agent = SimpleNamespace(last_goal_verdict=verdict)
    return s


def test_list_results_do_not_crash_and_evaluation_yes_counts():
    assert _session([{"complete": "yes"}])._task_confirmed_complete()


def test_confident_goal_verdict_counts():
    assert _session([], GoalVerdict(True, 0.9, "ok"))._task_confirmed_complete()


def test_unverified_or_weak_verdict_does_not_count():
    assert not _session([], GoalVerdict(None, 0.0, "?"))._task_confirmed_complete()
    assert not _session([], GoalVerdict(True, 0.3, "meh"))._task_confirmed_complete()
    assert not _session([{"complete": "no"}])._task_confirmed_complete()
