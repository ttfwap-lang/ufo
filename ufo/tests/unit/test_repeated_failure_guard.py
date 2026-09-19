from types import SimpleNamespace

from ufo.agents.processors.strategies.app_agent_processing_strategy import REPEATED_FAILURE_LIMIT, _record_and_check_repeated_failure as check

A = SimpleNamespace(function="execute_command", arguments={"command": "df -h"})
FAIL = [SimpleNamespace(status="ResultStatus.FAILURE")]
OK = [SimpleNamespace(status="success")]


def test_trips_after_limit_identical_failures():
    agent = SimpleNamespace()
    results = [check(agent, [A], FAIL) for _ in range(REPEATED_FAILURE_LIMIT)]
    assert results[-1] and not any(results[:-1])


def test_success_resets_counter():
    agent = SimpleNamespace()
    check(agent, [A], FAIL); check(agent, [A], FAIL)
    check(agent, [A], OK)
    assert not check(agent, [A], FAIL)


def test_different_action_resets_counter():
    agent = SimpleNamespace()
    check(agent, [A], FAIL); check(agent, [A], FAIL)
    other = SimpleNamespace(function="execute_command", arguments={"command": "uptime"})
    assert not check(agent, [other], FAIL)
