# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Verification Schema Module for Live Visual Verification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VerificationStatus(str, Enum):
    """Status enum for live action verification."""
    SUCCESS = "success"
    NO_VISIBLE_CHANGE = "no_visible_change"
    UNEXPECTED_STATE = "unexpected_state"
    ERROR_DIALOG_DETECTED = "error_dialog_detected"
    CAPTURE_FAILED = "capture_failed"


@dataclass
class ActionVerificationRequest:
    """Input payload for Live Visual Verification."""
    step_id: int
    subtask: str
    intended_action: str
    target_control_info: Dict[str, Any]
    pre_screenshot_path: str
    post_screenshot_path: str
    expected_outcome: str = ""
    app_process_name: str = ""


@dataclass
class ActionVerificationResult:
    """Output result from Live Visual Verification model."""
    verified: bool
    confidence_score: float
    status: VerificationStatus
    observed_visual_changes: str
    detected_ui_diffs: List[str] = field(default_factory=list)
    failure_reason: Optional[str] = None
    suggested_recovery_action: Optional[str] = None
