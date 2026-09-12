"""
Telemetry Viewer — Endpoint logic for reconstructing DLQ screenshots and fleet metrics.

Provides utility functions and a FastAPI router for:
  - Decoding Base64 screenshots from DLQ snapshots into viewable images
  - Aggregating fleet-wide telemetry (cost, token usage, error rates)
  - Generating timeline views of workflow execution history

Used by the Control Plane API server (api_server.py) as an included router,
or standalone for debugging.

Usage:
    # As a FastAPI router:
        pass
    from ufo.ops.telemetry_viewer import router
    app.include_router(router)

    # Standalone utility:
        pass
    from ufo.ops.telemetry_viewer import decode_snapshot_screenshot
    png_bytes = decode_snapshot_screenshot("1234_task_001.json", key="post")
"""
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/telemetry', tags=['telemetry'])

def decode_snapshot_screenshot(snapshot_filename: str, key: str='post', snapshot_dir: Optional[str]=None) -> Optional[bytes]:
    """
    Load a DLQ snapshot file and decode a Base64 screenshot.

    :param snapshot_filename: The snapshot JSON filename.
    :param key: Which screenshot to decode: "pre", "post", or "current".
    :param snapshot_dir: Override snapshot directory.
    :return: Raw PNG/JPEG bytes, or None if not found.
    """
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager(base_dir=snapshot_dir)
        snapshot = dlq.load_snapshot(snapshot_filename)
        if not snapshot:
            return None
        screenshots = snapshot.get('screenshots', {})
        screen_entry = screenshots.get(key, {})
        if isinstance(screen_entry, dict) and 'base64' in screen_entry:
            return base64.b64decode(screen_entry['base64'])
        return None
    except Exception as e:
        logger.error(f'[TelemetryViewer] Screenshot decode failed: {e}')
        return None

def save_decoded_screenshot(snapshot_filename: str, key: str='post', output_path: Optional[str]=None, snapshot_dir: Optional[str]=None) -> Optional[str]:
    """
    Decode a Base64 screenshot from a DLQ snapshot and save to disk.

    :param snapshot_filename: The snapshot JSON filename.
    :param key: Which screenshot to decode.
    :param output_path: Where to save. Auto-generated if None.
    :param snapshot_dir: Override snapshot directory.
    :return: Path to saved image, or None.
    """
    img_bytes = decode_snapshot_screenshot(snapshot_filename, key, snapshot_dir)
    if not img_bytes:
        return None
    if output_path is None:
        base = snapshot_filename.replace('.json', '')
        output_path = f'logs/dlq/decoded/{base}_{key}.png'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(img_bytes)
    logger.info(f'[TelemetryViewer] Screenshot saved: {output_path}')
    return output_path

@router.get('/snapshots')
async def list_dlq_snapshots(limit: int=Query(default=50, le=200)):
    """List all available DLQ snapshots with metadata."""
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager()
        snapshots = dlq.list_snapshots()
        return {'total': len(snapshots), 'snapshots': snapshots[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/snapshots/{filename}/screenshot')
async def serve_snapshot_screenshot(filename: str, key: str=Query(default='post', description='Screenshot key: pre, post, current')):
    """Decode and serve a DLQ snapshot screenshot as a PNG image."""
    img_bytes = decode_snapshot_screenshot(filename, key)
    if img_bytes is None:
        raise HTTPException(status_code=404, detail=f"Screenshot '{key}' not found in snapshot '{filename}'")
    return Response(content=img_bytes, media_type='image/png')

@router.get('/snapshots/{filename}/detail')
async def get_snapshot_detail(filename: str):
    """Get full snapshot detail (with Base64 stripped for readability)."""
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager()
        snapshot = dlq.load_snapshot(filename)
        if not snapshot:
            raise HTTPException(status_code=404, detail='Snapshot not found')
        if 'screenshots' in snapshot:
            for k, v in snapshot['screenshots'].items():
                if isinstance(v, dict) and 'base64' in v:
                    b64_len = len(v['base64'])
                    v['base64'] = f'[{b64_len} chars — use /screenshot endpoint]'
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/costs/summary')
async def get_cost_summary():
    """Get current cost tracking summary."""
    try:
        from ufo.telemetry.cost_tracker import CostTracker
        tracker = CostTracker.get_instance()
        return tracker.get_daily_summary()
    except Exception as e:
        return {'error': str(e)}

@router.get('/costs/history')
async def get_cost_history(days: int=Query(default=7, le=30)):
    """Get historical cost data."""
    try:
        from ufo.telemetry.cost_tracker import CostTracker
        tracker = CostTracker.get_instance()
        log_dir = Path('logs/telemetry')
        if not log_dir.exists():
            return {'days': [], 'total_usd': 0.0}
        history = []
        for log_file in sorted(log_dir.glob('costs_*.json'), reverse=True)[:days]:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    day_data = json.load(f)
                    history.append({'date': log_file.stem.replace('costs_', ''), 'data': day_data})
            except Exception:
                continue
        return {'days': history, 'total_usd': sum((d['data'].get('spent_today_usd', 0.0) for d in history))}
    except Exception as e:
        return {'error': str(e)}

def get_fleet_metrics() -> Dict[str, Any]:
    """
    Aggregate fleet-wide metrics for dashboard display.

    Collects data from:
      - Redis (worker heartbeats, queue depths)
      - CostTracker (token usage, budget status)
      - DLQ (failure counts)
    """
    metrics = {'timestamp': time.time(), 'fleet': {}, 'costs': {}, 'dlq': {}, 'queues': {}}
    try:
        import redis
        r = redis.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
        r.ping()
        workers = r.hgetall('ufo:fleet:heartbeats')
        now = int(time.time())
        alive = sum((1 for _, t in workers.items() if now - int(t) <= 30))
        metrics['fleet'] = {'total_workers': len(workers), 'alive_workers': alive, 'dead_workers': len(workers) - alive}
        metrics['queues'] = {'global_pending': r.llen('ufo:queue:bankfidelity_tasks'), 'dlq_depth': r.llen('ufo:queue:dlq'), 'hitl_pending': r.llen('ufo:hitl:pending_reviews')}
    except Exception:
        metrics['fleet'] = {'error': 'Redis unavailable'}
    try:
        from ufo.telemetry.cost_tracker import CostTracker
        tracker = CostTracker.get_instance()
        metrics['costs'] = tracker.get_daily_summary()
    except Exception:
        metrics['costs'] = {'error': 'Cost tracker unavailable'}
    try:
        from ufo.resilience.dlq_manager import DeadLetterQueueManager
        dlq = DeadLetterQueueManager()
        snapshots = dlq.list_snapshots()
        metrics['dlq'] = {'file_snapshots': len(snapshots)}
    except Exception:
        pass
    return metrics

@router.get('/metrics')
async def serve_fleet_metrics():
    """Get aggregated fleet metrics for dashboard."""
    return get_fleet_metrics()