"""
UFO Fleet Control Plane — FastAPI application for operator monitoring and HITL triage.

Provides a centralized, secure API for human operators to:
  - View fleet status and worker health
  - Fetch and inspect DLQ snapshots (including decoded screenshots)
  - Issue HITL resolutions (APPROVE / ABORT / MANUAL_REWIRE) to paused agents
  - Monitor cost telemetry and token usage
  - Submit new workflows to the distributed queue

Endpoints:
  GET  /api/fleet/status              — Fleet worker health overview
  GET  /api/dlq/pending               — List all DLQ snapshots
  GET  /api/dlq/snapshot/{id}         — Get a specific DLQ snapshot detail
  GET  /api/telemetry/screenshot/{id} — Decode Base64 screenshot as PNG
  POST /api/hitl/resolve              — Send human decision to a paused agent
  POST /api/fleet/submit              — Submit a new workflow to the queue
  GET  /api/telemetry/costs           — Current cost/token usage summary
  GET  /health                        — Liveness probe

Deployment:
    uvicorn ufo.ops.api_server:app --host 0.0.0.0 --port 8800

Config in system.yaml:
    CONTROL_PLANE:
      ENABLED: false
      HOST: "0.0.0.0"
      PORT: 8800
      API_KEY: ""                 # If set, required in X-API-Key header
      REDIS_URL: "redis://127.0.0.1:6379/0"
"""
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from ufo.ops.telemetry_viewer import router as telemetry_router
logger = logging.getLogger(__name__)

def _load_ops_config() -> Dict[str, Any]:
    """Load control plane config from system.yaml."""
    defaults = {'ENABLED': False, 'HOST': '0.0.0.0', 'PORT': 8800, 'API_KEY': '', 'REDIS_URL': 'redis://127.0.0.1:6379/0'}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        cp = getattr(cfg.system, 'control_plane', None)
        if cp and isinstance(cp, dict):
            defaults.update({k: v for k, v in cp.items() if v is not None})
    except Exception:
        pass
    return defaults
_config = _load_ops_config()
_redis_client = None

def _get_redis():
    """Lazy Redis connection."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(_config.get('REDIS_URL', 'redis://127.0.0.1:6379/0'), decode_responses=True, socket_connect_timeout=5)
            _redis_client.ping()
        except Exception as e:
            logger.warning(f'[ControlPlane] Redis unavailable: {e}')
            _redis_client = None
    return _redis_client

def _verify_api_key(x_api_key: Optional[str]=Header(None)) -> None:
    """Verify API key if configured."""
    required = _config.get('API_KEY', '')
    if required and x_api_key != required:
        raise HTTPException(status_code=401, detail='Invalid or missing API key.')

class HumanResolution(BaseModel):
    """Operator's decision for a paused workflow."""
    workflow_id: str = Field(..., description='The workflow to resolve')
    decision: str = Field(..., description='APPROVE, ABORT, or MANUAL_REWIRE')
    override_payload: Optional[str] = Field(None, description='Optional replacement instructions for MANUAL_REWIRE')
    operator_id: str = Field(..., description='Who is making this decision')
    reason: str = Field(default='', description="Operator's rationale")

class WorkflowSubmission(BaseModel):
    """New workflow submission."""
    instructions: str = Field(..., description='Task instructions')
    is_irrevocable: bool = Field(default=False)
    priority: str = Field(default='normal')
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StatusResponse(BaseModel):
    """Standard API response."""
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None
app = FastAPI(title='UFO Fleet Control Plane', description='Operator monitoring, HITL triage, and fleet management API.', version='1.0.0')
app.include_router(telemetry_router)

@app.get('/health')
async def health_check():
    """Liveness probe."""
    redis_ok = False
    try:
        r = _get_redis()
        if r:
            r.ping()
            redis_ok = True
    except Exception:
        pass
    return {'status': 'healthy', 'redis_connected': redis_ok, 'timestamp': time.time()}

@app.get('/api/fleet/status')
async def get_fleet_status():
    """Get health status of all fleet workers."""
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Redis not available')
    try:
        hb_key = 'ufo:fleet:heartbeats'
        workers = r.hgetall(hb_key)
        now = int(time.time())
        timeout = 30
        worker_list = []
        for worker_id, last_beat_str in workers.items():
            last_beat = int(last_beat_str)
            silence = now - last_beat
            proc_queue = f'ufo:queue:processing:{worker_id}'
            active = r.llen(proc_queue)
            worker_list.append({'worker_id': worker_id, 'last_heartbeat': last_beat, 'silence_seconds': silence, 'alive': silence <= timeout, 'active_tasks': active})
        global_queue = r.llen('ufo:queue:bankfidelity_tasks')
        dlq_depth = r.llen('ufo:queue:dlq')
        return {'workers': worker_list, 'total_workers': len(worker_list), 'alive': sum((1 for w in worker_list if w['alive'])), 'dead': sum((1 for w in worker_list if not w['alive'])), 'global_queue_depth': global_queue, 'dlq_depth': dlq_depth}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/api/dlq/pending')
async def get_pending_dlq_tasks(limit: int=Query(default=50, le=200)):
    """Fetch all workflows currently in the DLQ."""
    r = _get_redis()
    tasks = []
    if r:
        try:
            raw_tasks = r.lrange('ufo:queue:dlq', 0, limit - 1)
            for i, raw in enumerate(raw_tasks):
                try:
                    tasks.append({'index': i, 'data': json.loads(raw)})
                except json.JSONDecodeError:
                    tasks.append({'index': i, 'data': raw})
        except Exception as e:
            logger.warning(f'[ControlPlane] Redis DLQ read failed: {e}')
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager()
        file_snapshots = dlq.list_snapshots()
        for snap in file_snapshots[:limit]:
            tasks.append({'index': len(tasks), 'source': 'file', 'data': snap})
    except Exception:
        pass
    return {'pending_count': len(tasks), 'tasks': tasks}

@app.get('/api/dlq/snapshot/{snapshot_id}')
async def get_dlq_snapshot(snapshot_id: str):
    """Get detailed DLQ snapshot by filename or ID."""
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager()
        snapshot = dlq.load_snapshot(snapshot_id)
        if snapshot:
            if 'screenshots' in snapshot:
                for key, val in snapshot['screenshots'].items():
                    if isinstance(val, dict) and 'base64' in val:
                        val['base64'] = f"[{len(val['base64'])} chars — use /api/telemetry/screenshot/{snapshot_id}?key={key}]"
            return snapshot
    except Exception:
        pass
    r = _get_redis()
    if r:
        try:
            raw = r.get(f'ufo:snapshot:{snapshot_id}')
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

@app.post('/api/hitl/resolve')
async def resolve_workflow(resolution: HumanResolution):
    """
    Receive a human operator's decision and dispatch it to the paused
    agent via Redis Pub/Sub.

    Valid decisions:
      - APPROVE: Resume DAG execution
      - ABORT: Terminate the workflow, move to DLQ
      - MANUAL_REWIRE: Replace the current DAG node with override_payload
    """
    valid_decisions = {'APPROVE', 'ABORT', 'MANUAL_REWIRE'}
    if resolution.decision not in valid_decisions:
        raise HTTPException(status_code=400, detail=f'Invalid decision. Must be one of: {valid_decisions}')
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Redis not available')
    logger.info(f"[HITL] Operator '{resolution.operator_id}' issued {resolution.decision} for workflow '{resolution.workflow_id}'")
    channel = f'ufo:hitl:response:{resolution.workflow_id}'
    payload = resolution.model_dump_json()
    try:
        published = r.publish(channel, payload)
        if published == 0:
            fallback_key = f'ufo:hitl:pending:{resolution.workflow_id}'
            r.setex(fallback_key, 900, payload)
            logger.warning(f"[HITL] No active listener for '{resolution.workflow_id}'. Resolution stored in fallback key (15 min TTL).")
            return StatusResponse(status='pending', message='Agent not currently listening. Resolution stored for pickup.')
        audit_key = f'ufo:hitl:audit:{resolution.workflow_id}'
        audit_entry = {'operator_id': resolution.operator_id, 'decision': resolution.decision, 'timestamp': time.time(), 'reason': resolution.reason}
        r.lpush(audit_key, json.dumps(audit_entry))
        r.expire(audit_key, 86400 * 7)
        return StatusResponse(status='success', message=f"Resolution '{resolution.decision}' dispatched to agent.", data={'subscribers_notified': published})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/fleet/submit')
async def submit_workflow(submission: WorkflowSubmission):
    """Submit a new workflow to the distributed fleet queue."""
    r = _get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Redis not available')
    try:
        task = {'workflow_id': f'wf_{int(time.time())}', 'instructions': submission.instructions, 'is_irrevocable': submission.is_irrevocable, 'priority': submission.priority, 'metadata': submission.metadata, 'submitted_at': time.time(), 'submitted_by': 'control_plane'}
        r.lpush('ufo:queue:bankfidelity_tasks', json.dumps(task))
        return StatusResponse(status='success', message=f"Workflow '{task['workflow_id']}' submitted.", data={'workflow_id': task['workflow_id']})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def run_server(host: str=None, port: int=None) -> None:
    """Start the control plane server."""
    import uvicorn
    h = host or _config.get('HOST', '0.0.0.0')
    p = port or int(_config.get('PORT', 8800))
    logger.info(f'[ControlPlane] Starting on {h}:{p}')
    uvicorn.run(app, host=h, port=p, log_level='info')
if __name__ == '__main__':
    run_server()