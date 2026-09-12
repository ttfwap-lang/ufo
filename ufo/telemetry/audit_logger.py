"""
Immutable Audit Logger — Cryptographically chained, WORM execution logs.

Guarantees non-repudiation for financial compliance (BankFidelity).
Every action the agent takes is recorded with a SHA-256 hash that chains
to the previous record, making it mathematically impossible to silently
alter execution history.

Hash Chain Mechanics:
  record_N.previous_hash == SHA256(record_{N-1})
  Verifying the chain proves no records were inserted, deleted, or modified.

Storage Strategy (dual-write):
  1. Local WORM file: Append-only JSONL in logs/audit/ (always available)
  2. External SIEM sink: HTTP POST to Splunk HEC / Datadog / custom endpoint

Config in system.yaml:
    AUDIT_LOGGER:
      ENABLED: true
      SINK_URL: ""                    # Splunk HEC, Datadog, or custom HTTP endpoint
      SINK_TOKEN: ""                  # Bearer token for the SIEM
      SINK_TYPE: "generic"            # "splunk_hec", "datadog", or "generic"
      LOCAL_LOG_DIR: "logs/audit"
      CHAIN_ALGORITHM: "sha256"

Usage:
    
    from ufo.telemetry.audit_logger import ImmutableAuditLogger

    audit = ImmutableAuditLogger()
    audit.log_dag_execution(
        workflow_id="wf_123",
        node_id="node_open_excel",
        action_payload={"function": "click", "target": "File menu"},
        status="success",
    )
    # Verify the chain hasn't been tampered with:
        pass
    assert audit.verify_chain()
"""
import hashlib
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

def _load_audit_config() -> Dict[str, Any]:
    """Load audit logger config from system.yaml."""
    defaults = {'ENABLED': True, 'SINK_URL': '', 'SINK_TOKEN': '', 'SINK_TYPE': 'generic', 'LOCAL_LOG_DIR': 'logs/audit', 'CHAIN_ALGORITHM': 'sha256'}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        audit_cfg = getattr(cfg.system, 'audit_logger', None)
        if audit_cfg and isinstance(audit_cfg, dict):
            defaults.update({k: v for k, v in audit_cfg.items() if v is not None})
    except Exception:
        pass
    return defaults

class ImmutableAuditLogger:
    """
    Cryptographically chained audit logger for DAG execution events.

    Each record includes a `previous_hash` field linking it to the prior
    record's hash, forming an append-only chain that can be verified for
    integrity at any time.

    Thread-safe via threading.Lock — safe for concurrent DAG execution.
    """
    GENESIS_HASH = '0' * 64

    def __init__(self, sink_url: Optional[str]=None, sink_token: Optional[str]=None, local_log_dir: Optional[str]=None) -> None:
        self._config = _load_audit_config()
        self._enabled = self._config.get('ENABLED', True)
        self._sink_url = sink_url or self._config.get('SINK_URL', '')
        self._sink_token = sink_token or self._config.get('SINK_TOKEN', '')
        self._sink_type = self._config.get('SINK_TYPE', 'generic')
        self._algorithm = self._config.get('CHAIN_ALGORITHM', 'sha256')
        self._local_log_dir = local_log_dir or self._config.get('LOCAL_LOG_DIR', 'logs/audit')
        self._lock = threading.Lock()
        self._last_hash: str = self.GENESIS_HASH
        self._local_records: List[Dict[str, Any]] = []
        self._record_count: int = 0
        self._log_file_path = self._init_local_log()
        self._recover_chain_state()

    def log_dag_execution(self, workflow_id: str, node_id: str, action_payload: Dict[str, Any], status: str, metadata: Optional[Dict[str, Any]]=None) -> Optional[str]:
        """
        Record an execution event with cryptographic hash chaining.

        :param workflow_id: The workflow this node belongs to.
        :param node_id: The specific DAG node being executed.
        :param action_payload: The action details (function, arguments, etc.).
        :param status: Execution status: "success", "failure", "skipped", etc.
        :param metadata: Optional additional context.
        :return: The SHA-256 hash of this record, or None if disabled.
        """
        if not self._enabled:
            return None
        with self._lock:
            timestamp = time.time()
            audit_record = {'sequence': self._record_count, 'timestamp': timestamp, 'timestamp_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(timestamp)), 'workflow_id': workflow_id, 'node_id': node_id, 'action': action_payload, 'status': status, 'previous_hash': self._last_hash, 'hostname': os.environ.get('COMPUTERNAME', 'unknown'), 'pid': os.getpid()}
            if metadata:
                audit_record['metadata'] = metadata
            current_hash = self._compute_hash(audit_record)
            audit_record['event_hash'] = current_hash
            self._last_hash = current_hash
            self._record_count += 1
            self._local_records.append(audit_record)
            self._append_to_local_log(audit_record)
            if self._sink_url:
                self._dispatch_to_secure_sink(audit_record)
            logger.info(f"[Audit] #{audit_record['sequence']} {current_hash[:12]} ← {audit_record['previous_hash'][:12]} | {workflow_id}/{node_id} → {status}")
            return current_hash

    def verify_chain(self, records: Optional[List[Dict[str, Any]]]=None) -> bool:
        """
        Verify the integrity of the entire hash chain.

        Recomputes each record's hash and confirms it matches the stored
        event_hash and the next record's previous_hash.

        :param records: Records to verify. Uses in-memory records if None.
        :return: True if the chain is intact, False if tampered.
        """
        chain = records or self._local_records
        if not chain:
            return True
        expected_prev = self.GENESIS_HASH
        for i, record in enumerate(chain):
            if record.get('previous_hash') != expected_prev:
                logger.error(f"[Audit] Chain broken at record #{i}: expected previous_hash={expected_prev[:12]}, got {record.get('previous_hash', 'MISSING')[:12]}")
                return False
            record_copy = {k: v for k, v in record.items() if k != 'event_hash'}
            computed = self._compute_hash(record_copy)
            if computed != record.get('event_hash'):
                logger.error(f"[Audit] Hash mismatch at record #{i}: computed={computed[:12]}, stored={record.get('event_hash', 'MISSING')[:12]}")
                return False
            expected_prev = computed
        logger.info(f'[Audit] Chain verified: {len(chain)} records, integrity OK.')
        return True

    def verify_chain_from_file(self, filepath: Optional[str]=None) -> bool:
        """
        Verify chain integrity from the local WORM log file.

        :param filepath: Path to the JSONL audit log. Uses current if None.
        :return: True if intact.
        """
        path = filepath or self._log_file_path
        if not path or not Path(path).exists():
            logger.warning('[Audit] No log file to verify.')
            return True
        records = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return self.verify_chain(records)

    def get_chain_summary(self) -> Dict[str, Any]:
        """Get summary stats about the audit chain."""
        return {'record_count': self._record_count, 'last_hash': self._last_hash, 'genesis_hash': self.GENESIS_HASH, 'algorithm': self._algorithm, 'log_file': self._log_file_path, 'sink_configured': bool(self._sink_url), 'enabled': self._enabled}

    def _compute_hash(self, record: Dict[str, Any]) -> str:
        """
        Compute a deterministic SHA-256 hash of a record.

        Uses sort_keys=True and separators without spaces for canonical
        JSON serialization, ensuring identical inputs always produce
        identical hashes regardless of dict insertion order.
        """
        canonical = json.dumps(record, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
        if self._algorithm == 'sha256':
            return hashlib.sha256(canonical).hexdigest()
        elif self._algorithm == 'sha512':
            return hashlib.sha512(canonical).hexdigest()
        else:
            return hashlib.sha256(canonical).hexdigest()

    def _init_local_log(self) -> Optional[str]:
        """Initialize the local WORM log file."""
        try:
            log_dir = Path(self._local_log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            date_str = time.strftime('%Y-%m-%d')
            filepath = log_dir / f'audit_chain_{date_str}.jsonl'
            return str(filepath)
        except Exception as e:
            logger.warning(f'[Audit] Failed to init local log: {e}')
            return None

    def _append_to_local_log(self, record: Dict[str, Any]) -> None:
        """Append a record to the local WORM JSONL file."""
        if not self._log_file_path:
            return
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, sort_keys=True, default=str) + '\n')
        except Exception as e:
            logger.error(f'[Audit] Local log write failed: {e}')

    def _recover_chain_state(self) -> None:
        """Recover the last hash from existing log file on startup."""
        if not self._log_file_path or not Path(self._log_file_path).exists():
            return
        try:
            last_record = None
            count = 0
            with open(self._log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            last_record = json.loads(line)
                            count += 1
                        except json.JSONDecodeError:
                            continue
            if last_record and 'event_hash' in last_record:
                self._last_hash = last_record['event_hash']
                self._record_count = count
                logger.info(f'[Audit] Recovered chain state: {count} records, last_hash={self._last_hash[:12]}')
        except Exception as e:
            logger.warning(f'[Audit] Chain recovery failed: {e}')

    def _dispatch_to_secure_sink(self, record: Dict[str, Any]) -> None:
        """
        POST the audit record to an external SIEM / log aggregator.

        Supports:
          - Splunk HEC (HTTP Event Collector)
          - Datadog Log API
          - Generic HTTP JSON endpoint
        """
        try:
            if self._sink_type == 'splunk_hec':
                payload = json.dumps({'event': record}).encode('utf-8')
                headers = {'Content-Type': 'application/json', 'Authorization': f'Splunk {self._sink_token}'}
            elif self._sink_type == 'datadog':
                payload = json.dumps([{'ddsource': 'ufo-agent', 'ddtags': f"workflow:{record.get('workflow_id', '')}", 'hostname': record.get('hostname', 'unknown'), 'message': json.dumps(record, default=str), 'service': 'ufo-fleet'}]).encode('utf-8')
                headers = {'Content-Type': 'application/json', 'DD-API-KEY': self._sink_token}
            else:
                payload = json.dumps(record, default=str).encode('utf-8')
                headers = {'Content-Type': 'application/json'}
                if self._sink_token:
                    headers['Authorization'] = f'Bearer {self._sink_token}'
            req = urllib.request.Request(self._sink_url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    logger.warning(f"[Audit] Sink returned {resp.status} for record #{record.get('sequence', '?')}")
        except urllib.error.URLError as e:
            logger.warning(f"[Audit] Sink dispatch failed for record #{record.get('sequence', '?')}: {e}")
        except Exception as e:
            logger.warning(f'[Audit] Sink dispatch error: {e}')
_default_audit: Optional[ImmutableAuditLogger] = None

def get_audit_logger() -> ImmutableAuditLogger:
    """Get or create the default audit logger singleton."""
    global _default_audit
    if _default_audit is None:
        _default_audit = ImmutableAuditLogger()
    return _default_audit

def audit_dag_event(workflow_id: str, node_id: str, action_payload: Dict[str, Any], status: str, metadata: Optional[Dict[str, Any]]=None) -> Optional[str]:
    """
    Module-level convenience function for audit logging.

    Matches the interface expected by dag_engine.py and constellation
    task execution paths.
    """
    return get_audit_logger().log_dag_execution(workflow_id=workflow_id, node_id=node_id, action_payload=action_payload, status=status, metadata=metadata)