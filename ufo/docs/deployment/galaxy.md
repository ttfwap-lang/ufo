# Galaxy: Multi-Device Setup

> Grounded in `galaxy/README.md` and `galaxy/client/components/device_registry.py` as they exist in this checkout today. This is a practical setup guide, not a full architecture reference — see `galaxy/README.md` itself and the linked docs under `documents/docs/galaxy/` for the deeper design (Task Constellations, AIP protocol, formal DAG invariants, etc.), which this guide does not restate.

## The three pieces

Galaxy multi-device orchestration is built from three cooperating pieces:

1. **Galaxy server + `ConstellationClient`** — the control-plane side. `ConstellationClient` (`galaxy/client/constellation_client.py`) holds the **device registry**: it tracks which devices are known, their connection state, and their capabilities. The registry implementation itself, `DeviceRegistry` (`galaxy/client/components/device_registry.py`), is a plain in-memory store — `Dict[str, AgentProfile]` keyed by `device_id`, plus a per-device set of active task IDs. There is no persistence layer here; registration state lives only as long as the `ConstellationClient` process does.

2. **Device agents** — one process per machine you want Galaxy to control (Windows, Linux, etc.), each running UFO's own server/client (`ufo.server.app` + `ufo.client.client`) and connecting back to Galaxy over a WebSocket.

3. **Constellation orchestrator** — `ConstellationAgent` (`galaxy/agents/constellation_agent.py`) decomposes a natural-language request into a DAG of `TaskStar` nodes assigned to devices, and `TaskConstellationOrchestrator` (`galaxy/constellation/orchestrator/`) executes that DAG asynchronously, matching tasks to devices via the registry above.

## What a registered device actually looks like

Every device Galaxy knows about is an `AgentProfile` (defined in `galaxy/client/components/types.py`, stored by `DeviceRegistry`):

```python
@dataclass
class AgentProfile:
    device_id: str
    server_url: str
    os: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: DeviceStatus = DeviceStatus.DISCONNECTED
    last_heartbeat: Optional[datetime] = None
    connection_attempts: int = 0
    max_retries: int = 5
    current_task_id: Optional[str] = None
```

`DeviceRegistry` exposes register/lookup/status-transition operations on top of this (`register_device`, `get_device`, `get_all_devices(connected=True)`, `update_device_status`, `set_device_busy`/`set_device_idle`, `get_connected_devices`, `remove_device`, plus `update_device_system_info`/`get_device_system_info` for hardware/OS facts collected automatically at connect time). Task-busy tracking is per-device (`_active_tasks: Dict[str, set]`), so a device only flips back to `IDLE` once every task assigned to it has completed.

This is the "what is a device" model that the plan's Phase 14 (Explicit `DeviceAgent` Interface) needs to reconcile with, rather than duplicate, when it adds a formal `DeviceAgent` ABC at `galaxy/device_agent.py`. As of this writing that ABC does not exist yet — `AgentProfile`/`DeviceRegistry` above is the only device model in the codebase.

## Setup flow (per `galaxy/README.md`)

### 1. Install and environment

```powershell
git clone https://github.com/microsoft/UFO.git
cd UFO
conda create -n ufo3 python=3.10
conda activate ufo3
pip install -r requirements.txt
```

(This is the install flow `galaxy/README.md` documents today — `pip install -r requirements.txt`, not the `uv`-based flow described for the Windows ARM64 path in `docs/deployment/windows-arm64.md`. The two docs describe two different, currently-coexisting install paths; they have not been unified.)

### 2. Configure the `ConstellationAgent`'s own LLM

```powershell
copy config\galaxy\agent.yaml.template config\galaxy\agent.yaml
notepad config\galaxy\agent.yaml
```

`ConstellationAgent` is the orchestrator's own reasoning model (separate from any per-device agent LLM) — configured with the usual `API_TYPE`/`API_BASE`/`API_KEY`/`API_MODEL` block, supporting `openai` or `aoai` (Azure OpenAI) per the template.

### 3. Configure each device agent's LLM

```powershell
copy config\ufo\agents.yaml.template config\ufo\agents.yaml
notepad config\ufo\agents.yaml
```

Each device that will run UFO's `HOST_AGENT`/`APP_AGENT` needs its own LLM config here — this is the same shape of file as `config/ufo/agents_dgx.yaml` (see `docs/deployment/dgx-spark.md`), just pointed at whatever backend that device should use.

### 4. Configure the device pool

```powershell
copy config\galaxy\devices.yaml.template config\galaxy\devices.yaml
notepad config\galaxy\devices.yaml
```

Each entry declares `device_id`, `server_url` (the device's WebSocket endpoint), `os`, `capabilities` (a flat list of tags like `"excel"`, `"web_browsing"`, `"log_analysis"`), and free-form `metadata`. Per `galaxy/README.md`'s own warning, **`device_id` must exactly match the device's `--client-id` flag** and **`server_url` must exactly match the server's actual WebSocket URL** — a mismatch here means Galaxy silently cannot reach that device, not an error at startup.

### 5. Start device agents (one per machine)

Windows device:

```powershell
# Terminal 1 — server
python -m ufo.server.app --port 5000

# Terminal 2 — client
python -m ufo.client.client --ws --ws-server ws://localhost:5000/ws --client-id windows_device_1 --platform windows
```

Linux device:

```bash
# Terminal 1 — server
python -m ufo.server.app --port 5001

# Terminal 2 — client
python -m ufo.client.client --ws --ws-server ws://localhost:5001/ws --client-id linux_device_1 --platform linux

# Terminal 3 — HTTP MCP server for Linux-specific tools
python -m ufo.client.mcp.http_servers.linux_mcp_server
```

The `--platform` flag is required and must match the device's actual OS — `galaxy/README.md` flags this explicitly as a common setup mistake.

### 6. Launch the Galaxy client

Three modes, per `galaxy/README.md`:

```powershell
# Interactive WebUI (recommended) — http://localhost:8000, auto-picks next free port
python -m galaxy --webui

# Interactive terminal
python -m galaxy --interactive

# One-shot request
python -m galaxy --request "Extract data from Excel on Windows, process with Python on Linux, and generate visualization report"
```

Or embed it programmatically via `GalaxyClient` (`galaxy/galaxy_client.py`):

```python
from galaxy.galaxy_client import GalaxyClient

async def main():
    client = GalaxyClient(session_name="data_pipeline")
    await client.initialize()
    result = await client.process_request("...")
    await client.shutdown()
```

## Core component map (for orientation, not exhaustive)

| Component | Location | Role |
|-----------|----------|------|
| `GalaxyClient` | `galaxy/galaxy_client.py` | Session management, top-level entry point |
| `ConstellationClient` | `galaxy/client/constellation_client.py` | Device registry ownership, connection lifecycle |
| `DeviceRegistry` | `galaxy/client/components/device_registry.py` | In-memory device/`AgentProfile` store (see above) |
| `ConstellationAgent` | `galaxy/agents/constellation_agent.py` | DAG synthesis and evolution from natural-language requests |
| `TaskConstellationOrchestrator` | `galaxy/constellation/orchestrator/` | Async DAG execution, safety invariants |
| `TaskConstellation` | `galaxy/constellation/task_constellation.py` | DAG data structure and validation |

## Known open gaps (do not assume these are done)

- **`DeviceAgent` protocol (Phase 14):** not yet implemented. Today's device model is `AgentProfile`/`DeviceRegistry` as described above; a formal ABC reconciling with it is still planned.
- **`DGXDeviceAgent` (Phase 8):** per `docs/status.md`, still ⏳ Pending — a DGX device agent for Galaxy is planned but not built. `docs/deployment/dgx-spark.md` covers UFO's *direct* connection to the DGX (via `agents_dgx.yaml`/`litellm_config.yaml`), which is separate from, and does not require, Galaxy's device-agent abstraction.
- **Webui consumers:** `galaxy/webui/frontend/src/components/constellation/*.tsx` renders device/constellation data on the wire today. Any future change to what a "device" or "capability" looks like (e.g. from Phase 14's protocol work) needs a corresponding webui check — this guide does not cover the webui's own setup.
