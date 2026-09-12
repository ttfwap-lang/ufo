# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backward compatibility shim module for galaxy_agent_states.
"""

from ufo.galaxy.agents.constellation_agent_states import *
from ufo.galaxy.agents.constellation_agent_states import (    ConstellationAgentStatus as GalaxyAgentStatus,
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

