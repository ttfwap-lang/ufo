# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
48-Problem Evaluation Test Suite for UFO (Milestone 3).

Contains parameterized test definitions for all 48 evaluation problems across
the 5 evaluation stages:
- Stage R1: Notepad & Text Editing Tasks (10 problems: R1_01 to R1_10)
- Stage R2: Web Browser & Chrome Navigation Tasks (10 problems: R2_01 to R2_10)
- Stage R3: Basic BankFidelity Tasks (10 problems: R3_01 to R3_10)
- Stage R4: Complex BankFidelity Workflows & Reports (10 problems: R4_01 to R4_10)
- Stage R5: Multi-Agent & Cross-App Tasks (8 problems: R5_01 to R5_08)

Total: 48 evaluation problems.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest

from tests.eval_suite.eval_runner import EVAL_STAGES, EvaluationRunner


def _build_schema(stage_id: str, prompt: str) -> Dict[str, Any]:
    """Helper to build schema definition for a test problem."""
    return {
        "type": "object",
        "required": ["stage_id", "task_name", "request"],
        "properties": {
            "stage_id": {"type": "string", "enum": ["R1", "R2", "R3", "R4", "R5"]},
            "task_name": {"type": "string"},
            "request": {"type": "string"},
        },
    }


def _build_verifier_contract(stage_id: str) -> Dict[str, Any]:
    """Helper to build expected verifier contract key specification for a stage."""
    required_keys = ["verified", "stage_id", "dry_run"]
    if stage_id == "R1":
        required_keys.extend(["file_exists", "content_matched"])
    elif stage_id == "R2":
        required_keys.extend(["chrome_process_detected", "trajectory_verified"])
    elif stage_id == "R3":
        required_keys.extend(["process_detected", "trajectory_verified"])
    elif stage_id == "R4":
        required_keys.extend(["process_detected", "report_verified"])
    elif stage_id == "R5":
        required_keys.extend(["file_exists", "content_matched"])

    return {
        "stage_id": stage_id,
        "required_keys": required_keys,
        "contract_verified": True,
    }


# Define all 48 evaluation problems across the 5 evaluation stages
EVAL_48_PROBLEMS: List[Dict[str, Any]] = [
    # --- Stage R1: Notepad & Text Editing (10 problems) ---
    {
        "id": "R1_01",
        "stage_id": "R1",
        "name": "R1-01: Notepad Save Text to Desktop",
        "prompt": "Open Notepad, type 'Hello from UFO 5-Stage Evaluation Suite!', and save the file to the Desktop as ufo_test.txt.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_02",
        "stage_id": "R1",
        "name": "R1-02: Save Meeting Notes to Desktop",
        "prompt": "Open Notepad, type 'Meeting notes: Review Q3 roadmap and budget.', and save as meeting_notes.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_03",
        "stage_id": "R1",
        "name": "R1-03: Create TODO List in Notepad",
        "prompt": "Open Notepad, create a new document with text 'TODO list: 1. Code review 2. Deploy release', and save as todo.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_04",
        "stage_id": "R1",
        "name": "R1-04: Log Error Entry in Notepad",
        "prompt": "Open Notepad, paste log entry 'SYS_ERR_2026: Database connection timeout', and save as error_log.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_05",
        "stage_id": "R1",
        "name": "R1-05: Document Project Architecture",
        "prompt": "Open Notepad, write 'Project Alpha Architecture Document v1.0', and save as project_alpha.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_06",
        "stage_id": "R1",
        "name": "R1-06: Create Config Settings File",
        "prompt": "Open Notepad, type 'Configuration settings: host=localhost port=8080', and save as config_sample.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_07",
        "stage_id": "R1",
        "name": "R1-07: Draft Email Response in Notepad",
        "prompt": "Open Notepad, enter 'Drafting email response regarding contract terms', and save as email_draft.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_08",
        "stage_id": "R1",
        "name": "R1-08: Save Audit Summary to Desktop",
        "prompt": "Open Notepad, append summary 'Audit complete: all checks passed with zero findings', and save as audit_summary.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_09",
        "stage_id": "R1",
        "name": "R1-09: Save Backup Verification Log",
        "prompt": "Open Notepad, type 'Backup verification log: hash matches checksum 0xA4F2', and save as backup_log.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },
    {
        "id": "R1_10",
        "stage_id": "R1",
        "name": "R1-10: Record Benchmark Results",
        "prompt": "Open Notepad, record status 'System benchmark result: 4500 ops/sec', and save as benchmark_res.txt on Desktop.",
        "target_app": "Notepad",
        "schema": _build_schema("R1", "Open Notepad..."),
        "verifier_contract": _build_verifier_contract("R1"),
    },

    # --- Stage R2: Chrome Navigation (10 problems) ---
    {
        "id": "R2_01",
        "stage_id": "R2",
        "name": "R2-01: Example to Wikipedia Navigation",
        "prompt": "Open Google Chrome, navigate to https://www.example.com, and then navigate to https://www.wikipedia.org.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_02",
        "stage_id": "R2",
        "name": "R2-02: Search Python Docs in Chrome",
        "prompt": "Open Google Chrome, search for 'python documentation', and navigate to https://docs.python.org.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_03",
        "stage_id": "R2",
        "name": "R2-03: Inspect GitHub Repositories",
        "prompt": "Open Google Chrome, navigate to https://github.com, and inspect top repositories.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_04",
        "stage_id": "R2",
        "name": "R2-04: HackerNews Refresh Page",
        "prompt": "Open Google Chrome, open https://news.ycombinator.com, and refresh the front page.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_05",
        "stage_id": "R2",
        "name": "R2-05: Search Windows UI Automation on Bing",
        "prompt": "Open Google Chrome, navigate to https://bing.com, search 'Windows UI Automation', and open first result.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_06",
        "stage_id": "R2",
        "name": "R2-06: Browse arXiv LLM Papers",
        "prompt": "Open Google Chrome, navigate to https://arxiv.org, search 'LLM Agent Evaluation', and open paper page.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_07",
        "stage_id": "R2",
        "name": "R2-07: Search PyPI Package Pytest",
        "prompt": "Open Google Chrome, navigate to https://pypi.org, search package 'pytest', and check package details.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_08",
        "stage_id": "R2",
        "name": "R2-08: Search StackOverflow Answers",
        "prompt": "Open Google Chrome, open https://stackoverflow.com, search 'asyncio process wait_for', and read accepted answer.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_09",
        "stage_id": "R2",
        "name": "R2-09: Verify W3C HTML5 Documentation",
        "prompt": "Open Google Chrome, navigate to https://w3.org, verify HTML5 standard documentation page.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },
    {
        "id": "R2_10",
        "stage_id": "R2",
        "name": "R2-10: Browse Azure Cloud Documentation",
        "prompt": "Open Google Chrome, navigate to https://microsoft.com, browse to Azure documentation page.",
        "target_app": "Google Chrome",
        "schema": _build_schema("R2", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R2"),
    },

    # --- Stage R3: Basic BankFidelity Task (10 problems) ---
    {
        "id": "R3_01",
        "stage_id": "R3",
        "name": "R3-01: Launch BankFidelity and Verify UI",
        "prompt": "Open BankFidelity desktop application (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe) and verify basic UI elements.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_02",
        "stage_id": "R3",
        "name": "R3-02: Check Account Summary Tab",
        "prompt": "Open BankFidelity desktop application and click on Account Summary tab.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_03",
        "stage_id": "R3",
        "name": "R3-03: Verify Connection Status Indicator",
        "prompt": "Open BankFidelity application, check connection status indicator, and verify active profile.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_04",
        "stage_id": "R3",
        "name": "R3-04: Verify Navigation Sidebar Items",
        "prompt": "Launch BankFidelity desktop app and verify window title and navigation sidebar items.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_05",
        "stage_id": "R3",
        "name": "R3-05: Check Balance Display Widget",
        "prompt": "Open BankFidelity, check balance display widget, and verify currency display formatting.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_06",
        "stage_id": "R3",
        "name": "R3-06: Verify Settings Theme Toggle",
        "prompt": "Launch BankFidelity app, open Settings menu, and verify theme toggle control.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_07",
        "stage_id": "R3",
        "name": "R3-07: Check Notifications Panel Alerts",
        "prompt": "Open BankFidelity desktop app, check notifications panel, and verify zero unread alerts.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_08",
        "stage_id": "R3",
        "name": "R3-08: Verify Help & About Version Info",
        "prompt": "Launch BankFidelity, click Help & About menu option, and verify version number.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_09",
        "stage_id": "R3",
        "name": "R3-09: Verify User Profile Username",
        "prompt": "Open BankFidelity desktop app, navigate to User Profile screen, and verify username.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },
    {
        "id": "R3_10",
        "stage_id": "R3",
        "name": "R3-10: Refresh Data UI Indicator Check",
        "prompt": "Launch BankFidelity, click Refresh Data button, and verify UI loading indicator completes.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R3", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R3"),
    },

    # --- Stage R4: Complex BankFidelity Task (10 problems) ---
    {
        "id": "R4_01",
        "stage_id": "R4",
        "name": "R4-01: Filter Transactions and Export CSV",
        "prompt": "Open BankFidelity (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe), navigate to transaction history, filter transactions for the last 30 days, and export the report.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_02",
        "stage_id": "R4",
        "name": "R4-02: Export Monthly PDF Statement",
        "prompt": "Open BankFidelity, navigate to Statements section, select current month PDF, and export statement.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_03",
        "stage_id": "R4",
        "name": "R4-03: Simulate Transfer Funds Flow",
        "prompt": "Open BankFidelity, open Transfer Funds menu, select checking account, fill recipient details, and simulate transfer.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_04",
        "stage_id": "R4",
        "name": "R4-04: Analytics Dashboard Q1 Chart Export",
        "prompt": "Launch BankFidelity, open Analytics dashboard, set date range to Q1 2026, and export breakdown chart data.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_05",
        "stage_id": "R4",
        "name": "R4-05: Filter Vendor Payments CSV Export",
        "prompt": "Open BankFidelity, filter transactions by category 'Vendor Payments', select CSV format, and export file to Desktop.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_06",
        "stage_id": "R4",
        "name": "R4-06: Export Security Audit Log CSV",
        "prompt": "Open BankFidelity, navigate to Account Audit Log, filter events by 'Security', and export CSV report.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_07",
        "stage_id": "R4",
        "name": "R4-07: Generate Tax 1099 Summary Export",
        "prompt": "Launch BankFidelity, open Tax Documents module, generate 1099 summary form, and save export report.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_08",
        "stage_id": "R4",
        "name": "R4-08: Pause Recurring Schedule Status Export",
        "prompt": "Open BankFidelity, navigate to Recurring Payments list, pause active schedule #1042, and export schedule status.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_09",
        "stage_id": "R4",
        "name": "R4-09: Portfolio Holdings Valuation Export",
        "prompt": "Launch BankFidelity, open Portfolio Holdings tab, calculate total valuation, and export asset summary CSV.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },
    {
        "id": "R4_10",
        "stage_id": "R4",
        "name": "R4-10: Wire Transfer Search Record Export",
        "prompt": "Open BankFidelity, navigate to Wire Transfers, search confirmation code 'WT-9982', and export transaction record.",
        "target_app": "BankFidelity",
        "schema": _build_schema("R4", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R4"),
    },

    # --- Stage R5: Multi-Agent Task (8 problems) ---
    {
        "id": "R5_01",
        "stage_id": "R5",
        "name": "R5-01: Balance to Notepad Summary Report",
        "prompt": "Open BankFidelity (located at C:\\bankfidelity\\bankfidelity\\BankFidelity_Stable.exe) to retrieve current account balance, then open Notepad and save a summary report containing the account balance.",
        "target_app": "Multi-App (BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_02",
        "stage_id": "R5",
        "name": "R5-02: Format Transaction List to Text File",
        "prompt": "Open BankFidelity to query latest transaction list, open Notepad, format transaction list into text summary, and save as account_summary.txt on Desktop.",
        "target_app": "Multi-App (BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_03",
        "stage_id": "R5",
        "name": "R5-03: BankFidelity Balance + Chrome Spending Benchmark",
        "prompt": "Open BankFidelity to get monthly spending total, launch Google Chrome, search spending benchmark online, and record comparison in Notepad as spending_analysis.txt.",
        "target_app": "Multi-App (BankFidelity + Chrome + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_04",
        "stage_id": "R5",
        "name": "R5-04: Chrome Download Rates to BankFidelity & Notepad",
        "prompt": "Open Google Chrome, download latest financial rates table, open BankFidelity to apply rates, and document result in Notepad as rates_update.txt.",
        "target_app": "Multi-App (Chrome + BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Open Chrome..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_05",
        "stage_id": "R5",
        "name": "R5-05: Account Alert Escalation Memo",
        "prompt": "Open BankFidelity to retrieve account alert status, open Notepad, draft escalation memo for flagged alert, and save as alert_memo.txt on Desktop.",
        "target_app": "Multi-App (BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_06",
        "stage_id": "R5",
        "name": "R5-06: Statement Metadata Reconciliation Checklist",
        "prompt": "Launch BankFidelity to export monthly statement metadata, open Notepad, create reconciliation checklist, and save as recon_check.txt on Desktop.",
        "target_app": "Multi-App (BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Launch BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_07",
        "stage_id": "R5",
        "name": "R5-07: Active Cards Count Security Audit Entry",
        "prompt": "Open BankFidelity, retrieve active card numbers count, open Notepad, construct security audit entry, and save as audit_card.txt on Desktop.",
        "target_app": "Multi-App (BankFidelity + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
    {
        "id": "R5_08",
        "stage_id": "R5",
        "name": "R5-08: FX Rates Cross-Check Report",
        "prompt": "Open BankFidelity to fetch multi-currency exchange rates, open Chrome to cross-check rates on market page, and compile final report in Notepad as FX_Report.txt on Desktop.",
        "target_app": "Multi-App (BankFidelity + Chrome + Notepad)",
        "schema": _build_schema("R5", "Open BankFidelity..."),
        "verifier_contract": _build_verifier_contract("R5"),
    },
]


def test_48_problems_count_and_distribution():
    """Verify total problem count is 48 with correct stage distribution."""
    assert len(EVAL_48_PROBLEMS) == 48

    stage_counts = {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0}
    for problem in EVAL_48_PROBLEMS:
        stage_counts[problem["stage_id"]] += 1

    assert stage_counts["R1"] == 10
    assert stage_counts["R2"] == 10
    assert stage_counts["R3"] == 10
    assert stage_counts["R4"] == 10
    assert stage_counts["R5"] == 8


@pytest.mark.parametrize("problem", EVAL_48_PROBLEMS, ids=[p["id"] for p in EVAL_48_PROBLEMS])
def test_problem_definition_schema_and_bindings(problem: Dict[str, Any]):
    """Verify problem definition integrity, schema structure, and stage bindings."""
    assert problem["id"] is not None and len(problem["id"]) > 0
    assert problem["stage_id"] in ["R1", "R2", "R3", "R4", "R5"]
    assert problem["stage_id"] in EVAL_STAGES
    assert len(problem["name"]) > 0
    assert len(problem["prompt"]) > 0
    assert len(problem["target_app"]) > 0

    schema = problem["schema"]
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert "required" in schema
    assert "stage_id" in schema["required"]

    contract = problem["verifier_contract"]
    assert isinstance(contract, dict)
    assert contract.get("stage_id") == problem["stage_id"]
    assert "required_keys" in contract
    assert len(contract["required_keys"]) >= 3


@pytest.mark.parametrize("problem", EVAL_48_PROBLEMS, ids=[p["id"] for p in EVAL_48_PROBLEMS])
def test_problem_dry_run_execution(problem: Dict[str, Any]):
    """Verify dry-run execution for each of the 48 problems via EvaluationRunner."""
    runner = EvaluationRunner(dry_run=True)
    res = asyncio.run(
        runner.run_stage(
            stage_id=problem["stage_id"],
            request_override=problem["prompt"],
            task_name_override=f"test_dry_{problem['id']}",
        )
    )
    assert res["stage_id"] == problem["stage_id"]
    assert res["status"].startswith("SUCCESS")
    assert res["request"] == problem["prompt"]
    assert isinstance(res["verification"], dict)
    assert res["verification"].get("dry_run") is True
    assert res["verification"].get("verified") is True


@pytest.mark.parametrize("problem", EVAL_48_PROBLEMS, ids=[p["id"] for p in EVAL_48_PROBLEMS])
def test_problem_verifier_contract(problem: Dict[str, Any]):
    """Verify stage verifier contracts return all required keys for each problem in dry_run mode."""
    stage_meta = EVAL_STAGES[problem["stage_id"]]
    verifier_fn = stage_meta.get("verifier")
    assert callable(verifier_fn)

    res = verifier_fn(dry_run=True)
    contract_keys = problem["verifier_contract"]["required_keys"]
    for key in contract_keys:
        assert key in res, f"Problem {problem['id']} verifier output missing required key '{key}'"
