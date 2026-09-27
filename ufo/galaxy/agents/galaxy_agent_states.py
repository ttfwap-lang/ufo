# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backward compatibility shim module for galaxy_agent_states.
"""

from ufo.galaxy.agents.constellation_agent_states import *  # noqa: F401,F403
# Backward-compat aliases (Galaxy* -> Constellation*). This module is a compat
# shim; the noqa keeps ruff's F401 autofix from stripping these deliberate
# re-exports (it did strip them once - restored 2026-09-27).
from ufo.galaxy.agents.constellation_agent_states import (  # noqa: F401
    ConstellationAgentStatus as GalaxyAgentStatus,
    ConstellationAgentState as GalaxyAgentState,
    ConstellationAgentStateManager as GalaxyAgentStateManager,
    StartConstellationAgentState as StartGalaxyAgentState,
    StartConstellationAgentState as CreatingGalaxyAgentState,
    ContinueConstellationAgentState as ContinueGalaxyAgentState,
    ContinueConstellationAgentState as MonitoringGalaxyAgentState,
    ContinueConstellationAgentState as MonitorGalaxyAgentState,
    FinishConstellationAgentState as FinishGalaxyAgentState,
    FinishConstellationAgentState as FinishedGalaxyAgentState,
    FailConstellationAgentState as FailGalaxyAgentState,
    FailConstellationAgentState as FailedGalaxyAgentState,
)

