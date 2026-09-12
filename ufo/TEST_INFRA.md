# E2E Test Infra: UFO Evaluation Suite Alignment & Compliance

## Test Philosophy
- Opaque-box, requirement-driven testing based on `ORIGINAL_REQUEST.md`.
- Verifies Ripple-Effect Resolution, Global Compliance Sweep, and Regression Prevention across all 48 evaluation problems.

## Feature Inventory & Test Coverage Goals
| # | Feature Area | Description | Target Tests |
|---|--------------|-------------|--------------|
| 1 | Stage R1 (Notepad) | Notepad launch, text input, desktop save, verification, stale file cleanup, UTF-8 BOM, dry-run | 10 unit/integration tests |
| 2 | Stage R2 (Chrome) | Chrome launch, multi-URL navigation, pre-warming, log pattern matching, missing log dir failure, dry-run | 10 unit/integration tests |
| 3 | Stage R3 (Basic BankFidelity) | BankFidelity binary locate, launch, UI check, process check, trajectory matching, log dir pass bug fix, dry-run | 10 unit/integration tests |
| 4 | Stage R4 (Complex BankFidelity) | 30-day date filter, CSV export verification, fallback filename check, missing CSV failure, dry-run | 10 unit/integration tests |
| 5 | Stage R5 (Multi-Agent HostAgent) | Multi-agent balance extraction, Notepad summary creation, keyword verification, log verification, dry-run | 10 unit/integration tests |
| 6 | Harness & Static Compliance | `EvaluationRunner` CLI args, report timestamp collision prevention, error log formatting, static analysis sweep | 10 unit/integration tests |

## Test Architecture
- Test Runner: `pytest`
- Execution Command: `python -m pytest tests/test_eval_suite.py tests/test_eval_runner.py tests/test_eval_runner_empirical.py tests/test_eval_runner_empirical_2.py tests/test_eval_suite_stress.py tests/test_stage_r1_r2.py tests/test_r1_notepad_empirical.py tests/test_empirical_harness.py tests/test_empirical_verification.py tests/test_empirical_challenger_m1_2.py -v`
- Dry-Run Runner: `python -m tests.eval_suite.eval_runner --stage ALL --dry-run`
- Pass Criteria: Exit code 0, 100% test pass rate, clean report artifacts in `logs/eval_suite/`.
