import asyncio
from types import SimpleNamespace

from ufo.agents.processors.strategies.response_checks import app_response_problems, feedback_text

A = lambda f, **args: SimpleNamespace(function=f, arguments=args)
TOOLS = {"click_input", "set_edit_text", "summary"}


def test_valid_reply_has_no_problems():
    assert app_response_problems([A("click_input", id="3")], "CONTINUE", {"3"}, TOOLS) == []


def test_unknown_function_is_flagged_with_valid_names():
    p = app_response_problems([A("OpenApp", name="x")], "CONTINUE", {"3"}, TOOLS)
    assert p and "OpenApp" in p[0] and "click_input" in p[0]


def test_missing_function_without_finish_is_flagged():
    assert app_response_problems([], "CONTINUE", {"3"}, TOOLS)
    assert app_response_problems([A("")], "", {"3"}, TOOLS)


def test_missing_function_with_finish_is_fine():
    assert app_response_problems([], "FINISH", {"3"}, TOOLS) == []


def test_bad_control_id_is_flagged():
    assert "does not exist" in app_response_problems([A("set_edit_text", id="99", text="x")], "CONTINUE", {"3"}, TOOLS)[0]


def test_unknown_tool_list_does_not_block():
    assert app_response_problems([A("anything")], "CONTINUE", set(), set()) == []


def test_feedback_uses_real_newlines():
    text = feedback_text(["a"])
    assert chr(10) + "- a" in text and chr(92) not in text


def test_host_retry_adds_error_feedback(monkeypatch):
    from ufo.agents.processors.strategies import host_agent_processing_strategy as h
    strat = h.HostLLMInteractionStrategy.__new__(h.HostLLMInteractionStrategy)
    import logging
    strat.logger = logging.getLogger("t")
    prompts = []
    replies = iter(["not json", '{"status": "FINISH"}'])

    async def get_response(prompt, *a, **k):
        prompts.append(prompt)
        return SimpleNamespace(responses=[next(replies)], cost=0.0)

    def response_to_dict(text):
        import json
        return json.loads(text)

    agent = SimpleNamespace(get_response=get_response, response_to_dict=response_to_dict)
    monkeypatch.setattr(h.ufo_config.system, "json_parsing_retry", 3, raising=False)
    text, _ = asyncio.run(strat._get_llm_response_with_retry(agent, [{"role": "system", "content": "s"}]))
    assert text == '{"status": "FINISH"}'
    assert len(prompts[0]) == 1 and len(prompts[1]) == 2
    assert "could not be used" in prompts[1][-1]["content"]
