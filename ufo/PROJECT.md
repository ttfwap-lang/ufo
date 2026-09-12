# Project: UFO Evaluation Suite Alignment & Codebase Compliance

## Architecture
- Core components:
  - Evaluation Suite Harness: `tests/eval_suite/eval_runner.py` (Source of Truth)
  - Stage Handlers: `tests/eval_suite/stages/stage_r1.py` through `stage_r5.py`
  - Verifier Library: `tests/eval_suite/verifiers.py`
  - Core Modules: `agents/`, `automator/`, `server/`, `aip/`, `model_worker/`, `record_processor/`
  - Test Suite: `tests/test_eval_*.py`, `tests/test_empirical_*.py`, `tests/test_stage_*.py`

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1-01: Verifiers Step Log Deduplication | Fix double-counting in `verify_session_logs()` (`verifiers.py:194`) by deduplicating `glob("*.json")` and `glob("**/*.json")` | M1 | survey (spec_miner_3) |
| 2 | R1-02: Missing Log Dir Trajectory Pass Bug | Fix stage R3/R4/R5 `trajectory_verified` defaulting to `True` when `log_path` is missing/non-existent | M1 | survey (spec_miner_3) |
| 3 | R1-03: Eval Runner Import & Signature Alignment | Verify and align all 8 dependent test modules and 5 stage handlers with `eval_runner.py` signatures | M1 | survey (explorer_1) |
| 4 | R1-04: Async Blocking I/O Fix | Replace synchronous `open()` with non-blocking file access in `eval_runner.py:359` | M1 | survey (explorer_2) |
| 5 | R2-01: Undefined `Any` in basic.py | Add `from typing import Any` in `agents/agent/basic.py:364` | M2 | survey (explorer_2) |
| 6 | R2-02: `custom_worker.py` Undefined Symbols | Restore missing imports (`torch`, `Request`, `load_image_from_base64`, etc.) in `model_worker/custom_worker.py` | M2 | survey (explorer_2) |
| 7 | R2-03: Constructor & Call Arg Mismatches | Fix missing `memory` arg in `blackboard.py:380` and missing `agent_type` in `processing_context.py:194` | M2 | survey (explorer_2) |
| 8 | R2-04: Config Import in record_processor.py | Resolve missing `Config` import in `record_processor/record_processor.py:7` | M2 | survey (explorer_2) |
| 9 | R2-05: Websockets Incompatibility | Update `aip/transport/adapters.py` and `websocket.py` for `websockets` >= 14.0 | M2 | survey (explorer_2) |
| 10 | R2-06: Swallowed Exception in session_manager.py | Remove `return` inside `finally` block in `server/services/session_manager.py:518` | M2 | survey (explorer_2) |
| 11 | R2-07: Subclass Method Signature Incompatibilities | Re-align subclass method overrides in `agents/agent/app_agent.py` to match `AppAgent` supertype contracts | M2 | survey (explorer_2) |
| 12 | R2-08: Bare Exception Handling Clean-up | Replace bare `except:` and unhandled `except Exception:` with specific exceptions and proper logging | M2 | survey (explorer_2) |
| 13 | R3-01: 48 Evaluation Problems Test Coverage | Ensure unit and integration test coverage for all 48 evaluation problems across stages R1–R5 | M3 | survey (spec_miner_3) |
| 14 | R3-02: Edge Case & Trajectory Failure Tests | Generate unit tests for duplicate log deduplication, missing log dir failure behavior, and CRLF normalization | M3 | survey (spec_miner_3) |
| 15 | R3-03: CLI Subprocess Error Formatting Tests | Add unit tests for `EvaluationRunner` CLI execution mode (`--exec-method cli`) error log formatting | M3 | survey (spec_miner_3) |
| 16 | R3-04: E2E Test Suite Validation | Validate end-to-end dry-run and live suite execution against `TEST_INFRA.md` & publish `TEST_READY.md` | E2E Track | dual-track |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Ripple-Effect & Eval Suite Defect Resolution | Fix `verifiers.py` deduplication bug, stage R3/R4/R5 missing log dir bug, async blocking I/O, verify `eval_runner.py` dependent alignments | None | PLANNED |
| M2 | Global Compliance & Static Analysis Sweep | Remediate FATAL (undefined names, missing args, broken imports) and HIGH (return in finally, signature overrides) static analysis errors | M1 | PLANNED |
| M3 | Regression Prevention & 48-Problem Test Coverage | Generate and update unit/integration tests to guarantee coverage for all 48 evaluation problems and edge cases | M1, M2 | PLANNED |
| E2E | E2E Testing & Test Infra Track | Validate complete evaluation suite infrastructure, create test runner contracts, publish `TEST_READY.md` | M1 | PLANNED |

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
