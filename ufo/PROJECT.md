# Project: UFO Evaluation Suite Alignment & Codebase Compliance

## Architecture
- Core components:
  - Evaluation Suite Harness: `tests/eval_suite/eval_runner.py` (Source of Truth)
  - Stage Handlers: `tests/eval_suite/stages/stage_r1.py` through `stage_r5.py`
  - Verifier Library: `tests/eval_suite/verifiers.py`
  - Core Modules: `agents/`, `automator/`, `server/`, `aip/`, `model_worker/`, `record_processor/`
  - Test Suite: `tests/test_eval_*.py`, `tests/test_empirical_*.py`, `tests/test_stage_*.py`

## Feature Inventory
| # | Feature | Description | Milestone | Source | Status |
|---|---------|-------------|-----------|--------|--------|
| 1 | R1-01: Verifiers Step Log Deduplication | Fix double-counting in `verify_session_logs()` (`verifiers.py:159-170`) by deduplicating `glob("*.json")` and `glob("**/*.json")` via `seen_paths` set with `p.resolve()` | M1 | survey (spec_miner_3) | ✅ COMPLETED |
| 2 | R1-02: Missing Log Dir Trajectory Pass Bug | Fix stage R3/R4/R5 `trajectory_verified` defaulting to `True` when `log_path` is missing/non-existent. `verify_session_logs` returns `verified: False` when `log_dir is None` or path doesn't exist; stages R3/R4/R5 use `trajectory_ver.get('verified', False)` (default=False) | M1 | survey (spec_miner_3) | ✅ COMPLETED |
| 3 | R1-03: Eval Runner Import & Signature Alignment | Verified and aligned all dependent test modules and 5 stage handlers with `eval_runner.py` signatures — all 164 tests pass | M1 | survey (explorer_1) | ✅ COMPLETED |
| 4 | R1-04: Async Blocking I/O Fix | Replaced synchronous `open()` with non-blocking `asyncio.to_thread()` in `eval_runner.py` (lines 42, 201, 274, 284) | M1 | survey (explorer_2) | ✅ COMPLETED |
| 5 | R2-01: Undefined `Any` in basic.py | Added `Any` to `from typing import Any, Callable, Dict, List, Optional, Set, Type, Union` in `agents/agent/basic.py:9` | M2 | survey (explorer_2) | ✅ COMPLETED |
| 6 | R2-02: `custom_worker.py` Undefined Symbols | `model_worker/` directory is empty — file does not exist in current codebase revision; N/A | M2 | survey (explorer_2) | ⏭️ N/A |
| 7 | R2-03: Constructor & Call Arg Mismatches | Verified `Blackboard.__init__` has `max_images` with default `1` (callable as `Blackboard()`); verified `BasicProcessorContext` instantiation passes `agent_type="basic"` at `processing_context.py:194` | M2 | survey (explorer_2) | ✅ COMPLETED |
| 8 | R2-04: Config Import in record_processor.py | Fixed: `LazyUFOConfig` now imported in `record_processor/record_processor.py:7` (was using undefined name at line 14) | M2 | survey (explorer_2) | ✅ COMPLETED |
| 9 | R2-05: Websockets Incompatibility | Fixed: `Any` added to `from typing import Any, Optional, Union` in `aip/transport/websocket.py:10`; unused `import asyncio` removed; version guards in `adapters.py` handle `websockets` >= 14.0 | M2 | survey (explorer_2) | ✅ COMPLETED |
| 10 | R2-06: Swallowed Exception in session_manager.py | Verified: `_run_session_background` finally block (`server/services/session_manager.py:331`) does NOT contain a `return` statement — already fixed | M2 | survey (explorer_2) | ✅ COMPLETED |
| 11 | R2-07: Subclass Method Signature Incompatibilities | Re-aligned `AppAgent` method overrides in `agents/agent/app_agent.py` to match `BasicAgent` supertype contracts: `context_provision` now uses `*args, **kwargs` in parent abstract method; `build_offline_docs_retriever` and `build_online_search_retriever` signatures updated to match parent's `*args: Any, **kwargs: Any` contract | M2 | survey (explorer_2) | ✅ COMPLETED |
| 12 | R2-08: Bare Exception Handling Clean-up | Searched all source files (`agents/`, `aip/`, `server/`, `record_processor/`, `tests/eval_suite/`) — no bare `except:` patterns found. Broad `except Exception:` blocks are intentional and properly logged with context | M2 | survey (explorer_2) | ✅ COMPLETED |
| 13 | R3-01: 48 Evaluation Problem Test Coverage | 164 unit and integration tests cover all 48 evaluation problems across stages R1–R5 | M3 | survey (spec_miner_3) | ✅ COMPLETED |
| 14 | R3-02: Edge Case & Trajectory Failure Tests | Tests cover duplicate log deduplication, missing log dir failure behavior, CRLF normalization, UTF-8 BOM, empty log directories | M3 | survey (spec_miner_3) | ✅ COMPLETED |
| 15 | R3-03: CLI Subprocess Error Formatting Tests | `tests/test_eval_runner.py::test_eval_runner_cli_exec_method` and stress tests validate CLI execution mode error log formatting | M3 | survey (spec_miner_3) | ✅ COMPLETED |
| 16 | R3-04: E2E Test Suite Validation | Full dry-run (`python -m tests.eval_suite.eval_runner --stage ALL --dry-run`) passes 5/5 stages with exit code 0; full pytest suite passes 164/164 | E2E Track | dual-track | ✅ COMPLETED |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Ripple-Effect & Eval Suite Defect Resolution | Fix `verifiers.py` deduplication bug (R1-01), stage R3/R4/R5 missing log dir bug (R1-02), async blocking I/O (R1-04), verify `eval_runner.py` dependent alignments (R1-03) | None | ✅ COMPLETED |
| M2 | Global Compliance & Static Analysis Sweep | Remediate FATAL (undefined names R2-01/R2-04/R2-05, broken imports R2-02, constructor args R2-03) and HIGH (return in finally R2-06, signature overrides R2-07) static analysis errors; clean up bare excepts (R2-08) | M1 | ✅ COMPLETED |
| M3 | Regression Prevention & 48-Problem Test Coverage | Generate and update unit/integration tests to guarantee coverage for all 48 evaluation problems and edge cases (R3-01 through R3-03) | M1, M2 | ✅ COMPLETED |
| E2E | E2E Testing & Test Infra Track | Validate complete evaluation suite infrastructure, create test runner contracts, publish `TEST_READY.md` (R3-04) | M1, M2, M3 | ✅ COMPLETED |

## Interface Contracts
### `tests/eval_suite/eval_runner.py` ↔ `tests/eval_suite/stages/*.py`
- `get_stage_config() -> Dict[str, Any]` must return dictionary containing:
  - `id`: `str` ("R1".."R5")
  - `name`: `str`
  - `target_app`: `str`
  - `request`: `str`
  - `default_request`: `str`
  - `pre_cleanup`: `Callable[[], None]`
  - `verifier`: `Callable[[Path, bool], Dict[str, Any]]`
- `verifier_fn(task_log_dir: Optional[Path], dry_run: bool) -> Dict[str, Any]` must return dict containing:
  - `verified`: `bool`
  - `details`: `Dict[str, Any]`

### `tests/eval_suite/verifiers.py`
- `verify_session_logs(log_path: Optional[Path], expected_patterns: List[str]) -> Dict[str, Any]`
  - Deduplicates JSON log paths.
  - Returns `verified`: `False` if `log_path` is `None` or does not exist.

## Code Layout
- `tests/eval_suite/eval_runner.py`: Evaluation suite harness.
- `tests/eval_suite/verifiers.py`: Shared verification helpers.
- `tests/eval_suite/stages/stage_r1.py` .. `stage_r5.py`: Stage verifiers and configs.
- `agents/agent/basic.py`, `app_agent.py`: Agent base classes and implementations.
- `model_worker/custom_worker.py`: Custom LLM worker API service.
- `agents/memory/blackboard.py`: Agent blackboard memory storage.
- `agents/processors/context/processing_context.py`: Context processing logic.
- `server/services/session_manager.py`: Server session orchestration.
- `aip/transport/`: Network transport adapters.
- `record_processor/`: Record processing utilities.
- `tests/`: Pytest suite.
