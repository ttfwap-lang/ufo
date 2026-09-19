"""
Dead Letter Queue for terminal LLM-completion failures.

Scoped to the LLM-call failure shape (agent_type/messages/error/model/
circuit_breaker_state) used by ufo.llm.llm_call, as distinct from
ufo.resilience.dlq_manager.DeadLetterQueueManager, which snapshots UI
workflow failures (task_id/dag_state/uia_tree/screenshots). The two are
separate failure domains, not a duplicate of each other; both persist
JSON snapshots to disk with the same prune-oldest-first policy.

Usage:

    from ufo.dlq.dead_letter_queue import record_dlq_event
    record_dlq_event(
        agent_type="HOST_AGENT",
        messages=messages,
        error=exc,
        model="gpt-5.6-terra",
        circuit_breaker_state="OPEN",
        extra_meta={"trigger": "circuit_breaker_open_terminal"},
    )
"""
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """
    Persists JSON snapshots of terminal LLM-call failures.

    Reads config from system.yaml:
      LLM_DLQ:
        ENABLED: true
        SNAPSHOT_DIR: "logs/dlq/llm"
        MAX_SNAPSHOTS: 100

    Does not create ``snapshot_dir`` at construction time — only on the
    first ``record_failure()`` call.
    """

    def __init__(self, snapshot_dir: str = "logs/dlq/llm", max_snapshots: int = 100, enabled: bool = True) -> None:
        self._snapshot_dir = snapshot_dir
        self._max_snapshots = max_snapshots
        self._enabled = enabled

    def record_failure(
        self,
        agent_type: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        error: Optional[BaseException] = None,
        model: str = "unknown",
        circuit_breaker_state: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Record one terminal failure as a JSON snapshot. Returns the snapshot path, or None if disabled/failed."""
        if not self._enabled:
            logger.debug("LLM DLQ is disabled -- skipping snapshot capture.")
            return None
        try:
            snapshot_dir = Path(self._snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.time()
            snapshot = {
                "agent_type": agent_type,
                "model": model,
                "circuit_breaker_state": circuit_breaker_state,
                "error": str(error) if error is not None else "",
                "error_type": type(error).__name__ if error is not None else None,
                "messages": messages or [],
                "extra_meta": extra_meta or {},
                "timestamp": timestamp,
            }
            filename = f"dlq_{int(timestamp * 1000)}_{uuid.uuid4().hex[:8]}.json"
            snapshot_path = snapshot_dir / filename
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
            self._prune(snapshot_dir)
            logger.warning(f"[LLM DLQ] Diagnostic snapshot saved: {snapshot_path} (agent_type={agent_type})")
            return str(snapshot_path)
        except Exception as e:
            logger.warning(f"[LLM DLQ] Failed to record failure snapshot: {e}")
            return None

    def _prune(self, snapshot_dir: Path) -> None:
        try:
            files = sorted(snapshot_dir.glob("dlq_*.json"), key=lambda p: p.stat().st_mtime)
            excess = len(files) - self._max_snapshots
            for old_file in files[:excess]:
                old_file.unlink(missing_ok=True)
                logger.info(f"[LLM DLQ] Pruned old snapshot: {old_file.name}")
        except Exception as e:
            logger.debug(f"[LLM DLQ] Snapshot pruning failed: {e}")

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """List all recorded snapshots (oldest first), each as its decoded JSON dict."""
        snapshot_dir = Path(self._snapshot_dir)
        if not snapshot_dir.exists():
            return []
        results = []
        for path in sorted(snapshot_dir.glob("dlq_*.json"), key=lambda p: p.stat().st_mtime):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
            except Exception as e:
                logger.error(f"Failed to load LLM DLQ snapshot {path}: {e}")
        return results


_default_dlq: Optional[DeadLetterQueue] = None


def get_default_dlq() -> DeadLetterQueue:
    """Lazily construct and cache the process-wide LLM DLQ instance, configured from system.yaml."""
    global _default_dlq
    if _default_dlq is None:
        snapshot_dir = "logs/dlq/llm"
        max_snapshots = 100
        enabled = True
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            dlq_cfg = getattr(cfg.system, "llm_dlq", None) or getattr(cfg.system, "LLM_DLQ", None)
            if dlq_cfg and isinstance(dlq_cfg, dict):
                enabled = dlq_cfg.get("ENABLED", enabled)
                snapshot_dir = dlq_cfg.get("SNAPSHOT_DIR", snapshot_dir)
                max_snapshots = dlq_cfg.get("MAX_SNAPSHOTS", max_snapshots)
        except Exception as e:
            logger.debug(f"Using default LLM DLQ config: {e}")
        _default_dlq = DeadLetterQueue(snapshot_dir=snapshot_dir, max_snapshots=max_snapshots, enabled=enabled)
    return _default_dlq


def record_dlq_event(
    agent_type: str,
    messages: Optional[List[Dict[str, Any]]] = None,
    error: Optional[BaseException] = None,
    model: str = "unknown",
    circuit_breaker_state: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Module-level convenience wrapper around the default DLQ instance, used by ufo.llm.llm_call."""
    return get_default_dlq().record_failure(
        agent_type=agent_type,
        messages=messages,
        error=error,
        model=model,
        circuit_breaker_state=circuit_breaker_state,
        extra_meta=extra_meta,
    )
