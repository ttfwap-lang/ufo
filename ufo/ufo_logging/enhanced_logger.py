# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Enhanced Logger Module — JSONL Event Streaming and Markdown Trajectory Renderer.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class EnhancedActionLogRecord:
    """Comprehensive E2E Action Log Record for UFO."""
    session_id: str
    timestamp_utc: str
    round_index: int
    step_index: int
    agent_name: str
    agent_type: str

    user_request: str
    subtask: str
    application_name: str
    process_id: int
    window_title: str

    observation: str
    thought: str
    plan: List[str]
    selected_action_name: str
    action_parameters: Dict[str, Any]

    target_control: Dict[str, Any]

    pre_action_screenshot_path: str
    post_action_screenshot_path: str
    annotated_screenshot_path: str
    clean_screenshot_path: str

    ui_state_diff: Dict[str, Any]

    verification_passed: bool
    verification_confidence: float
    verification_status: str
    verification_observed_changes: str

    execution_duration_ms: float
    llm_cost_usd: float
    error_stacktrace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class JSONLEventStreamWriter:
    """
    Streams EnhancedActionLogRecord events to events.jsonl and renders trajectory.md.
    """

    def __init__(self, log_dir: str) -> None:
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.events_file_path = os.path.join(self.log_dir, "events.jsonl")
        self.trajectory_file_path = os.path.join(self.log_dir, "trajectory.md")
        self.records: List[EnhancedActionLogRecord] = []

    def write_event(self, record: EnhancedActionLogRecord) -> None:
        """Append log record to events.jsonl and render trajectory markdown."""
        self.records.append(record)
        with open(self.events_file_path, "a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")
        self.render_trajectory_markdown()

    def render_trajectory_markdown(self) -> None:
        """Render markdown trajectory report."""
        if not self.records:
            return

        lines = [
            "# UFO Execution Trajectory Report",
            "",
            f"**Session ID**: `{self.records[0].session_id}`  ",
            f"**User Request**: {self.records[0].user_request}  ",
            f"**Total Steps**: {len(self.records)}  ",
            f"**Generated**: {datetime.now(timezone.utc).isoformat()}  ",
            "",
            "---",
            "",
            "## Summary Metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total Steps | {len(self.records)} |",
            f"| Verified Passed | {sum(1 for r in self.records if r.verification_passed)} / {len(self.records)} |",
            f"| Total LLM Cost | ${sum(r.llm_cost_usd for r in self.records):.4f} |",
            f"| Total Execution Time | {sum(r.execution_duration_ms for r in self.records) / 1000.0:.2f}s |",
            "",
            "---",
            "",
            "## Step Trajectory",
            "",
        ]

        for r in self.records:
            badge = "✅ PASSED" if r.verification_passed else "❌ FAILED"
            lines.extend([
                f"### Step {r.step_index + 1}: {r.selected_action_name} ({badge})",
                "",
                f"- **Subtask**: {r.subtask}",
                f"- **Application**: `{r.application_name}`",
                f"- **Thought**: {r.thought}",
                f"- **Action Params**: `{json.dumps(r.action_parameters)}`",
                f"- **Verification Confidence**: `{r.verification_confidence:.2f}` ({r.verification_status})",
                f"- **Observed Changes**: {r.verification_observed_changes}",
                "",
                "| Pre-Action Screenshot | Post-Action Screenshot | Annotated Screenshot |",
                "|---|---|---|",
                f"| ![{os.path.basename(r.pre_action_screenshot_path)}]({r.pre_action_screenshot_path}) | ![{os.path.basename(r.post_action_screenshot_path)}]({r.post_action_screenshot_path}) | ![{os.path.basename(r.annotated_screenshot_path)}]({r.annotated_screenshot_path}) |",
                "",
                "---",
                "",
            ])

        with open(self.trajectory_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
