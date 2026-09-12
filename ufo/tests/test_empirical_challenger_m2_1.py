# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Empirical Challenger Test Suite for Milestone 2 (M2).
Adversarially tests and validates:
1. Polymorphic signature calls on AppAgent, HostAgent, OpenAIOperatorAgent via BasicAgent reference.
2. BasicProcessorContext instantiation without arguments (BasicProcessorContext()).
3. record_processor.py config loading & KeyError vulnerability detection.
4. Static compliance remediations across agents, model_worker, blackboard, transport, and session_manager.
"""

import ast
import sys
import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List

from ufo.agents.agent.basic import BasicAgent, AgentRegistry
from ufo.agents.agent.app_agent import AppAgent, OpenAIOperatorAgent
from ufo.agents.agent.host_agent import HostAgent
from ufo.agents.processors.context.processing_context import BasicProcessorContext, ProcessingContext
from ufo.config.config_loader import get_ufo_config
from ufo.config.config_schemas import UFOConfig


# Real prompt paths relative to working directory C:\ufo\ufo
VALID_MAIN_PROMPT = "prompts/share/base/app_agent.yaml"
VALID_EXAMPLE_PROMPT = "prompts/examples/{mode}/app_agent_example.yaml"
VALID_HOST_MAIN_PROMPT = "prompts/share/base/host_agent.yaml"
VALID_HOST_EXAMPLE_PROMPT = "prompts/examples/{mode}/host_agent_example.yaml"
VALID_API_PROMPT = "prompts/share/base/api.yaml"


def create_test_host_agent() -> HostAgent:
    return HostAgent(
        name="test_host",
        is_visual=True,
        main_prompt=VALID_HOST_MAIN_PROMPT,
        example_prompt=VALID_HOST_EXAMPLE_PROMPT,
        api_prompt=VALID_API_PROMPT,
    )


# ============================================================================
# 1. Polymorphic Signature Calls Tests
# ============================================================================

def test_polymorphic_agent_instantiation_and_registry():
    """Verify that AppAgent, HostAgent, and OpenAIOperatorAgent register properly with AgentRegistry."""
    registered = AgentRegistry.list_agents()
    assert "appagent" in registered
    assert "hostagent" in registered
    assert "operator" in registered
    assert registered["appagent"] == AppAgent
    assert registered["hostagent"] == HostAgent
    assert registered["operator"] == OpenAIOperatorAgent


def test_polymorphic_print_response():
    """Verify print_response polymorphic calls via BasicAgent references."""
    with patch("ufo.agents.presenters.PresenterFactory.create_presenter") as mock_presenter_factory:
        mock_presenter = MagicMock()
        mock_presenter_factory.return_value = mock_presenter

        # AppAgent via BasicAgent reference
        app_agent: BasicAgent = AppAgent(
            name="test_app",
            process_name="notepad.exe",
            app_root_name="Notepad",
            is_visual=True,
            main_prompt=VALID_MAIN_PROMPT,
            example_prompt=VALID_EXAMPLE_PROMPT,
        )
        mock_response = MagicMock()
        app_agent.print_response(mock_response)
        mock_presenter.present_app_agent_response.assert_called_with(mock_response, print_action=True)

        # HostAgent via BasicAgent reference
        host_agent: BasicAgent = create_test_host_agent()
        host_agent.print_response(mock_response)
        assert mock_presenter.present_host_agent_response.called

        # OpenAIOperatorAgent via BasicAgent reference
        op_agent: BasicAgent = OpenAIOperatorAgent(
            name="test_op",
            process_name="notepad.exe",
            app_root_name="Notepad"
        )
        op_agent.print_response()
        op_agent.print_response(mock_response)


def test_polymorphic_get_prompter():
    """Verify get_prompter polymorphic calls via BasicAgent references."""
    with patch("ufo.agents.presenters.PresenterFactory.create_presenter"):
        # BasicAgent reference pointing to AppAgent
        app_agent: BasicAgent = AppAgent(
            name="test_app",
            process_name="notepad.exe",
            app_root_name="Notepad",
            is_visual=True,
            main_prompt=VALID_MAIN_PROMPT,
            example_prompt=VALID_EXAMPLE_PROMPT,
        )
        prompter = app_agent.get_prompter(is_visual=True, main_prompt=VALID_MAIN_PROMPT, example_prompt=VALID_EXAMPLE_PROMPT)
        assert prompter is not None

        # BasicAgent reference pointing to HostAgent
        host_agent: BasicAgent = create_test_host_agent()
        host_prompter = host_agent.get_prompter(
            is_visual=True, main_prompt=VALID_HOST_MAIN_PROMPT, example_prompt=VALID_HOST_EXAMPLE_PROMPT, api_prompt=VALID_API_PROMPT
        )
        assert host_prompter is not None

        # BasicAgent reference pointing to OpenAIOperatorAgent
        op_agent: BasicAgent = OpenAIOperatorAgent(
            name="test_op",
            process_name="notepad.exe",
            app_root_name="Notepad"
        )
        op_prompter = op_agent.get_prompter(main_prompt=VALID_MAIN_PROMPT, example_prompt=VALID_EXAMPLE_PROMPT)
        assert op_prompter is not None


def test_polymorphic_process_confirmation():
    """Verify process_confirmation calls across all agent subtypes via BasicAgent reference."""
    with patch("ufo.agents.presenters.PresenterFactory.create_presenter"):
        app_agent: BasicAgent = AppAgent(
            name="test_app",
            process_name="notepad.exe",
            app_root_name="Notepad",
            is_visual=True,
            main_prompt=VALID_MAIN_PROMPT,
            example_prompt=VALID_EXAMPLE_PROMPT,
        )
        app_agent.processor = MagicMock()

        host_agent: BasicAgent = create_test_host_agent()
        host_agent.processor = MagicMock()

        op_agent: BasicAgent = OpenAIOperatorAgent(
            name="test_op",
            process_name="notepad.exe",
            app_root_name="Notepad"
        )
        op_agent.processor = MagicMock()

        with patch("ufo.module.interactor.question_asker", return_value="yes"):
            app_agent.process_confirmation()
            host_agent.process_confirmation()
            op_agent.process_confirmation()


def test_polymorphic_retriever_methods():
    """Verify retriever builder method calls on AppAgent and HostAgent."""
    with patch("ufo.agents.presenters.PresenterFactory.create_presenter"):
        app_agent: BasicAgent = AppAgent(
            name="test_app",
            process_name="notepad.exe",
            app_root_name="Notepad",
            is_visual=True,
            main_prompt=VALID_MAIN_PROMPT,
            example_prompt=VALID_EXAMPLE_PROMPT,
        )
        host_agent: BasicAgent = create_test_host_agent()

        # BasicAgent default implementations raise NotImplementedError for non-overridden retriever calls on HostAgent
        with pytest.raises(NotImplementedError):
            host_agent.build_offline_docs_retriever()
        with pytest.raises(NotImplementedError):
            host_agent.build_online_search_retriever()
        with pytest.raises(NotImplementedError):
            host_agent.build_experience_retriever()
        with pytest.raises(NotImplementedError):
            host_agent.build_human_demonstration_retriever()

        # AppAgent overrides retriever methods
        app_agent.build_offline_docs_retriever()
        app_agent.build_online_search_retriever(request="search query", top_k=3)
        app_agent.build_experience_retriever(db_path="exp.db")
        app_agent.build_human_demonstration_retriever(db_path="demo.db")


def test_polymorphic_status_manager_and_default_state():
    """Verify status_manager and default_state properties across agent subtypes."""
    with patch("ufo.agents.presenters.PresenterFactory.create_presenter"):
        app_agent: BasicAgent = AppAgent(
            name="test_app",
            process_name="notepad.exe",
            app_root_name="Notepad",
            is_visual=True,
            main_prompt=VALID_MAIN_PROMPT,
            example_prompt=VALID_EXAMPLE_PROMPT,
        )
        host_agent: BasicAgent = create_test_host_agent()
        op_agent: BasicAgent = OpenAIOperatorAgent(
            name="test_op",
            process_name="notepad.exe",
            app_root_name="Notepad"
        )

        assert app_agent.status_manager is not None
        assert host_agent.status_manager is not None
        assert op_agent.status_manager is not None

        assert app_agent.default_state is not None
        assert host_agent.default_state is not None
        assert op_agent.default_state is not None


# ============================================================================
# 2. BasicProcessorContext Default Instantiation Tests
# ============================================================================

def test_basic_processor_context_no_args():
    """Verify BasicProcessorContext can be instantiated with ZERO arguments."""
    context = BasicProcessorContext()
    assert context.agent_type == "basic"
    assert context.session_step == 0
    assert context.round_step == 0
    assert context.round_num == 0
    assert context.cost == 0.0
    assert context.status is None
    assert context.action == []
    assert context.action_representation == ""
    assert context.results == ""
    assert context.function_call is None
    assert context.arguments == {}
    assert context.action_type == ""


def test_basic_processor_context_with_args():
    """Verify BasicProcessorContext can be instantiated with explicit arguments."""
    context = BasicProcessorContext(
        agent_type="appagent",
        session_step=10,
        cost=1.25,
        action=[{"command": "click"}],
        action_type="ui_action"
    )
    assert context.agent_type == "appagent"
    assert context.session_step == 10
    assert context.cost == 1.25
    assert context.action == [{"command": "click"}]
    assert context.action_type == "ui_action"


def test_processing_context_post_init():
    """Verify ProcessingContext.__post_init__ uses BasicProcessorContext() correctly."""
    mock_global = MagicMock()
    p_context = ProcessingContext(global_context=mock_global, local_context=None)
    assert p_context.global_context == mock_global
    assert p_context.local_context is not None
    assert p_context.local_context.agent_type == "basic"


# ============================================================================
# 3. record_processor Config Loading Tests & Defect Detection
# ============================================================================

def test_record_processor_config_loader():
    """Verify record_processor.py config loader behavior."""
    config = get_ufo_config()
    assert isinstance(config, UFOConfig)

    # Valid config accesses
    assert "APP_AGENT" in config
    assert "VISUAL_MODE" in config["APP_AGENT"]
    assert "DEMONSTRATION_PROMPT" in config
    assert "RAG_DEMONSTRATION_COMPLETION_N" in config
    assert "DEMONSTRATION_SAVED_PATH" in config

    # Empirical test for R2-04 regression: record_processor.py line 49 accesses APPAGENT_EXAMPLE_PROMPT
    # get_ufo_config() uses UFOConfig which delegates dict lookup to _raw.
    # In modern config, APPAGENT_EXAMPLE_PROMPT and API_PROMPT are absent from top-level _raw dictionary!
    with pytest.raises(KeyError, match="APPAGENT_EXAMPLE_PROMPT"):
        _ = config["APPAGENT_EXAMPLE_PROMPT"]

    with pytest.raises(KeyError, match="API_PROMPT"):
        _ = config["API_PROMPT"]


def test_import_record_processor_module():
    """Verify record_processor module import behavior."""
    with patch("sys.argv", ["record_processor"]):
        import ufo.record_processor.record_processor as rp
        assert hasattr(rp, "configs")
        assert hasattr(rp, "main")
        assert isinstance(rp.configs, UFOConfig)


# ============================================================================
# 4. Static Compliance Remediations (R2-01 to R2-08) Verification Tests
# ============================================================================

def test_r2_01_typing_any_in_basic():
    """Verify Any is imported and usable in agents/agent/basic.py."""
    import ufo.agents.agent.basic as basic_mod
    assert hasattr(basic_mod, "Any")
    assert basic_mod.Any is Any


def test_r2_02_custom_worker_structure():
    """Verify model_worker/custom_worker.py AST contains FastAPI app instantiation and worker variable."""
    import pathlib
    worker_file = pathlib.Path("model_worker/custom_worker.py")
    assert worker_file.exists()
    
    code = worker_file.read_text(encoding="utf-8")
    tree = ast.parse(code)
    
    # Check that app = FastAPI() and worker = None are present in the AST
    assign_targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assign_targets.append(target.id)

    assert "app" in assign_targets
    assert "worker" in assign_targets


def test_r2_03_blackboard_add_data_signature():
    """Verify blackboard.py add_data call compatibility."""
    from ufo.agents.memory.blackboard import Blackboard
    bb = Blackboard()
    # add_data requires (data_dict, memory_obj)
    bb.add_data({"key1": "val1"}, bb.requests)
    assert len(bb.requests._content) == 1


def test_r2_05_websockets_adapter_open_check():
    """Verify aip/transport/adapters.py handles websockets modern ClientConnection object."""
    from ufo.aip.transport.adapters import WebSocketsLibAdapter
    
    mock_ws = MagicMock()

    # Mock legacy websocket object with .closed attribute
    mock_ws.closed = False
    del mock_ws.state
    adapter = WebSocketsLibAdapter(mock_ws)
    assert adapter.is_open() is True

    mock_ws.closed = True
    assert adapter.is_open() is False

    # Mock modern websocket object with .state attribute
    mock_ws_modern = MagicMock()
    from websockets.protocol import State
    mock_ws_modern.state = State.OPEN
    adapter_modern = WebSocketsLibAdapter(mock_ws_modern)
    assert adapter_modern.is_open() is True

    mock_ws_modern.state = State.CLOSED
    assert adapter_modern.is_open() is False


def test_r2_06_session_manager_finally_block():
    """Verify server/services/session_manager.py finally block does NOT contain a return statement."""
    import pathlib
    sm_file = pathlib.Path("server/services/session_manager.py")
    assert sm_file.exists()

    code = sm_file.read_text(encoding="utf-8")
    tree = ast.parse(code)

    # Check all Try nodes to ensure no Return statement exists inside any finalbody
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for final_stmt in node.finalbody:
                for sub_node in ast.walk(final_stmt):
                    assert not isinstance(sub_node, ast.Return), (
                        "B012 flaw detected: 'return' statement inside finally block in session_manager.py!"
                    )
