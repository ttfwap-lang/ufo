# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for EvaluationAgent and EvaluationAgentState state transition logic.
"""

from ufo.agents.agent.evaluation_agent import EvaluationAgent
from ufo.agents.states.evaluation_agent_state import (
    ContinueEvaluationAgentState,
    EvaluationAgentStateManager,
    NoneEvaluationAgentState,
)


def test_evaluation_agent_instantiation():
    """Test that EvaluationAgent can be instantiated without errors."""
    agent = EvaluationAgent("eva_agent", True, "", "")
    assert agent is not None
    assert isinstance(agent.default_state, ContinueEvaluationAgentState)


def test_evaluation_agent_state_transition():
    """Test that agent.default_state.next_state(agent) executes cleanly without AttributeError."""
    agent = EvaluationAgent("eva_agent", True, "", "")
    agent.status = "CONTINUE"
    next_state = agent.default_state.next_state(agent)
    assert isinstance(next_state, ContinueEvaluationAgentState)


def test_evaluation_agent_state_manager_none_state():
    """Test that EvaluationAgentStateManager.none_state returns NoneEvaluationAgentState without throwing attribute errors."""
    manager = EvaluationAgentStateManager()
    none_state = manager.none_state
    assert isinstance(none_state, NoneEvaluationAgentState)
