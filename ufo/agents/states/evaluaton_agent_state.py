# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backwards compatible alias for ufo.agents.states.evaluation_agent_state.
"""

from ufo.agents.states.evaluation_agent_state import (
    ContinueEvaluationAgentState,
    ContinueEvaluatonAgentState,
    EvaluationAgentState,
    EvaluationAgentStateManager,
    EvaluationAgentStatus,
    EvaluatonAgentState,
    EvaluatonAgentStatus,
    NoneEvaluationAgentState,
    NoneEvaluatonAgentState,
)

__all__ = [
    "EvaluationAgentStatus",
    "EvaluationAgentStateManager",
    "EvaluationAgentState",
    "ContinueEvaluationAgentState",
    "NoneEvaluationAgentState",
    "EvaluatonAgentStatus",
    "EvaluatonAgentState",
    "ContinueEvaluatonAgentState",
    "NoneEvaluatonAgentState",
]
