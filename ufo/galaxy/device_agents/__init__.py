# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Galaxy Device Agents

Client-side processes that run on a physical/remote device (e.g. the DGX
Spark box) and register themselves with a Galaxy constellation server so
that tasks can be routed to them.

Note the distinction from `galaxy.client.components.device_registry`:
- `DeviceRegistry`/`AgentProfile` (in `galaxy.client.components`) are the
  SERVER-SIDE bookkeeping model — the record that exists once a device has
  registered.
- The classes in this package (e.g. `DGXDeviceAgent`) are the CLIENT-SIDE
  process that performs that registration and then executes tasks. They are
  not a competing "what is a device" model; a successful `register()` call
  here is what causes exactly one `AgentProfile` to exist server-side.
"""

from .dgx_device_agent import DGXDeviceAgent

__all__ = ["DGXDeviceAgent"]
