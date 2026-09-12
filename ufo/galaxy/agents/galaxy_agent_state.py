# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backward compatibility module for galaxy_agent_state.
"""

from ufo.galaxy.agents.constellation_agent_states import *
from ufo.galaxy.agents.constellation_agent_states import (    ConstellationAgentStatus as GalaxyAgentStatus,
    ContinueConstellationAgentState as MonitoringGalaxyAgentState,
)
