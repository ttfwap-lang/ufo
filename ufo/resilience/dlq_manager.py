"""
Dead-Letter Queue Manager — Diagnostic snapshot persistence for total failure events.

When all LLM fallback tiers and vision grounding stages are exhausted, this module
captures a comprehensive diagnostic snapshot and persists it to disk for post-mortem
analysis.

Snapshots include:
  - Full DAG state (serialized Pydantic models)
  - Pruned UIA tree hierarchy
  - Base64-compressed pre/post screenshots
  - Full error chain / traceback
  - Agent config at time of failure
  - Timestamp and task metadata

Optional webhook alerting for external monitoring integration.

Usage:
    
    from ufo.resilience.dlq_manager import DeadLetterQueueManager
    dlq = DeadLetterQueueManager()
    snapshot_path = dlq.capture_failure(
        task_id="task_001",
        error_chain="Traceback ...",
        dag_state=graph.model_dump(),
        screenshots={"pre": "path/pre.png", "post": "path/post.png"},
    )
"""
import base64
import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class DeadLetterQueueManager:
    """
    Persists diagnostic snapshots when all fallback mechanisms are exhausted.

    Reads config from system.yaml:
      DLQ:
        ENABLED: true
        SNAPSHOT_DIR: "logs/dlq/snapshots"
        WEBHOOK_URL: ""
        MAX_SNAPSHOTS: 100
    """

    def __init__(self, base_dir: Optional[str]=None) -> None:
        self._enabled: bool = True
        self._snapshot_dir: str = base_dir or 'logs/dlq/snapshots'
        self._webhook_url: str = ''
        self._max_snapshots: int = 100
        self._load_config()

    def _load_config(self) -> None:
        """Load DLQ config from system.yaml."""
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            dlq_cfg = getattr(cfg.system, 'dlq', None)
            if dlq_cfg and isinstance(dlq_cfg, dict):
                self._enabled = dlq_cfg.get('ENABLED', True)
                self._snapshot_dir = dlq_cfg.get('SNAPSHOT_DIR', self._snapshot_dir)
                self._webhook_url = dlq_cfg.get('WEBHOOK_URL', '')
                self._max_snapshots = dlq_cfg.get('MAX_SNAPSHOTS', 100)
        except Exception as e:
            logger.debug(f'Using default DLQ config: {e}')

    def capture_failure(self, task_id: str, error_chain: str='', dag_state: Optional[Dict[str, Any]]=None, uia_tree: Optional[Dict[str, Any]]=None, screenshots: Optional[Dict[str, str]]=None, agent_config: Optional[Dict[str, Any]]=None, metadata: Optional[Dict[str, Any]]=None) -> Optional[str]:
        """
        Capture a comprehensive diagnostic snapshot on total fallback exhaustion.

        :param task_id: Unique task/workflow identifier.
        :param error_chain: Full exception traceback string.
        :param dag_state: Serialized DAG state dict (from ExecutionGraph.model_dump()).
        :param uia_tree: Pruned UIA tree dict (from prune_uia_tree_from_root()).
        :param screenshots: Dict of {"pre": path, "post": path} screenshot paths.
        :param agent_config: Current agent configuration at time of failure.
        :param metadata: Any additional context metadata.
        :return: Path to the saved snapshot file, or None on failure.
        """
        if not self._enabled:
            logger.debug('DLQ is disabled — skipping snapshot capture.')
            return None
        timestamp = int(time.time())
        filename = f'{timestamp}_{task_id}.json'
        snapshot = {'timestamp': timestamp, 'timestamp_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(timestamp)), 'task_id': task_id, 'error_chain': error_chain, 'dag_state': dag_state, 'uia_tree': uia_tree, 'screenshots': {}, 'agent_config': agent_config, 'metadata': metadata or {}, 'system_info': self._collect_system_info()}
        if screenshots:
            for key, path in screenshots.items():
                if path and os.path.exists(path):
                    try:
                        with open(path, 'rb') as f:
                            img_bytes = f.read()
                        snapshot['screenshots'][key] = {'path': path, 'size_bytes': len(img_bytes), 'base64': base64.b64encode(img_bytes).decode('utf-8')}
                    except Exception as e:
                        snapshot['screenshots'][key] = {'path': path, 'error': str(e)}
        snapshot_path = self._save_snapshot(filename, snapshot)
        if snapshot_path:
            logger.warning(f'[DLQ] Diagnostic snapshot saved: {snapshot_path} (task_id={task_id})')
            self._prune_old_snapshots()
            self._trigger_alert(snapshot_path, task_id, error_chain)
        return snapshot_path

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """List all DLQ snapshots with basic metadata."""
        snapshot_dir = Path(self._snapshot_dir)
        if not snapshot_dir.exists():
            return []
        snapshots = []
        for f in sorted(snapshot_dir.glob('*.json'), reverse=True):
            try:
                stat = f.stat()
                snapshots.append({'filename': f.name, 'path': str(f), 'size_bytes': stat.st_size, 'created': time.ctime(stat.st_ctime)})
            except Exception:
                continue
        return snapshots

    def load_snapshot(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load and return a specific DLQ snapshot."""
        path = Path(self._snapshot_dir) / filename
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f'Failed to load DLQ snapshot {filename}: {e}')
            return None

    def _save_snapshot(self, filename: str, snapshot: Dict[str, Any]) -> Optional[str]:
        """Save snapshot to disk."""
        try:
            snapshot_dir = Path(self._snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            filepath = snapshot_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, indent=2, default=str, ensure_ascii=False)
            return str(filepath)
        except Exception as e:
            logger.error(f'[DLQ] Failed to save snapshot: {e}')
            return None

    def _prune_old_snapshots(self) -> None:
        """Remove oldest snapshots if count exceeds MAX_SNAPSHOTS."""
        try:
            snapshot_dir = Path(self._snapshot_dir)
            if not snapshot_dir.exists():
                return
            snapshots = sorted(snapshot_dir.glob('*.json'))
            excess = len(snapshots) - self._max_snapshots
            if excess > 0:
                for old_file in snapshots[:excess]:
                    try:
                        old_file.unlink()
                        logger.info(f'[DLQ] Pruned old snapshot: {old_file.name}')
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f'[DLQ] Snapshot pruning failed: {e}')

    def _trigger_alert(self, snapshot_path: str, task_id: str, error_summary: str) -> None:
        """
        Fire alert webhook if configured. Falls back to logging.

        Webhook receives a POST with JSON payload containing task_id,
        snapshot_path, error summary, and timestamp.
        """
        if not self._webhook_url:
            logger.info(f'[DLQ] No webhook configured — alert logged only. Task: {task_id}')
            return
        payload = {'event': 'dlq_snapshot_created', 'task_id': task_id, 'snapshot_path': snapshot_path, 'error_summary': error_summary[:500] if error_summary else '', 'timestamp': time.time(), 'hostname': os.environ.get('COMPUTERNAME', 'unknown')}
        try:
            import urllib.request
            req = urllib.request.Request(self._webhook_url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f'[DLQ] Alert webhook fired: {resp.status} (task_id={task_id})')
        except Exception as e:
            logger.warning(f'[DLQ] Webhook alert failed: {e}')

    @staticmethod
    def _collect_system_info() -> Dict[str, Any]:
        """Collect basic system info for the snapshot."""
        import platform
        import sys
        return {'python_version': sys.version, 'platform': platform.platform(), 'hostname': os.environ.get('COMPUTERNAME', 'unknown'), 'pid': os.getpid()}
_default_dlq: Optional[DeadLetterQueueManager] = None

def serialize_fatal_failure(graph: Any, failed_node_id: str, screenshot_path: str, pruned_uia_tree: Optional[Dict[str, Any]]=None, exception_trace: str='') -> Optional[str]:
    """
    Module-level convenience function for serializing a fatal DAG failure.

    Takes an ExecutionGraph (from dag_engine.py) directly, extracts its state,
    and delegates to DeadLetterQueueManager.capture_failure().

    :param graph: ExecutionGraph instance (with .model_dump() or .dict()).
    :param failed_node_id: The node_id that triggered the fatal failure.
    :param screenshot_path: Path to the failure-state screenshot.
    :param pruned_uia_tree: Optional pruned UIA tree dict.
    :param exception_trace: Full traceback string.
    :return: Path to the saved snapshot file, or None on failure.
    """
    global _default_dlq
    if _default_dlq is None:
        _default_dlq = DeadLetterQueueManager()
    dag_state = None
    if graph is not None:
        if hasattr(graph, 'model_dump'):
            dag_state = graph.model_dump()
        elif hasattr(graph, 'dict'):
            dag_state = graph.dict()
        elif isinstance(graph, dict):
            dag_state = graph
    workflow_id = 'unknown'
    if hasattr(graph, 'workflow_id'):
        workflow_id = graph.workflow_id
    task_id = f'{workflow_id}_{failed_node_id}'
    return _default_dlq.capture_failure(task_id=task_id, error_chain=exception_trace, dag_state=dag_state, uia_tree=pruned_uia_tree, screenshots={'failure': screenshot_path} if screenshot_path else None, metadata={'failed_node_id': failed_node_id, 'workflow_id': workflow_id})