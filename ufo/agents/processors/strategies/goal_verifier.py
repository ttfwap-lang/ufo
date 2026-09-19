"""
Task-level goal verification.

When the HostAgent declares FINISH, ask the vision model one question: looking
at the current screen, is the user's request actually satisfied? A confident
"no" sends the agent back to work with the verifier's reason on its
blackboard; an unparseable or failed check never blocks FINISH, it is just
reported as unverified.
"""
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

GOAL_VERIFY_MAX_REJECTIONS = int(os.environ.get("UFO_GOAL_VERIFY_MAX_REJECTIONS", "2"))
GOAL_VERIFY_ENABLED = os.environ.get("UFO_GOAL_VERIFY", "1") != "0"

_PROMPT = (
    "You are a strict task-completion checker for a Windows desktop automation agent.\n"
    "Decide whether the USER REQUEST below is fully satisfied by the current state of the "
    "screen in the screenshot. Judge only what is visible or stated in the agent log; do not "
    "assume unseen work happened. If the request asked for information, the agent's final "
    "answer must contain it.\n"
    'Reply with JSON only: {"achieved": true|false, "confidence": 0.0-1.0, '
    '"reason": "<one sentence>", "missing": "<what is still left to do, empty if nothing>"}'
)


@dataclass
class GoalVerdict:
    achieved: Optional[bool]
    confidence: float
    reason: str
    missing: str = ""

    @property
    def rejects(self) -> bool:
        """Only a confident, explicit 'not achieved' is allowed to reopen the task."""
        return self.achieved is False and self.confidence >= 0.6


def build_messages(user_request: str, agent_summary: str, screenshot_url: Optional[str]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"USER REQUEST:\n{user_request}\n\nAGENT'S FINAL SUMMARY:\n{agent_summary or '(none)'}"}
    ]
    if screenshot_url:
        content.append({"type": "image_url", "image_url": {"url": screenshot_url}})
    else:
        content.append({"type": "text", "text": "(No screenshot available; judge from the summary only.)"})
    return [{"role": "system", "content": _PROMPT}, {"role": "user", "content": content}]


def parse_verdict(text: str) -> GoalVerdict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return GoalVerdict(None, 0.0, "Verifier reply had no JSON.")
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return GoalVerdict(None, 0.0, "Verifier reply was not valid JSON.")
    achieved = data.get("achieved")
    if isinstance(achieved, str):
        achieved = {"true": True, "yes": True, "false": False, "no": False}.get(achieved.strip().lower())
    if not isinstance(achieved, bool):
        achieved = None
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return GoalVerdict(achieved, confidence, str(data.get("reason", "")), str(data.get("missing", "") or ""))


async def verify_goal(
    user_request: str,
    agent_summary: str,
    screenshot_url: Optional[str],
    ask_model: Callable[[List[Dict[str, Any]]], Awaitable[str]],
) -> GoalVerdict:
    try:
        reply = await ask_model(build_messages(user_request, agent_summary, screenshot_url))
    except Exception as e:  # the model being down must not block FINISH
        logger.warning(f"Goal verification call failed: {e}")
        return GoalVerdict(None, 0.0, f"Verifier call failed: {e}")
    return parse_verdict(reply)
