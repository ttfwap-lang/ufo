"""
Retry-until-verified.

A request runs as one session; if the session ends without a verified
success (error, step limit, or a negative goal verdict), a new session is
started *sequentially* on the same desktop with the original request plus a
narrative of what the previous attempt already did and why it was judged
incomplete, so the next attempt continues instead of redoing (and
duplicating) completed work. Attempts are logged as ``{task}``,
``{task}_try2``, ...
"""
import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable, List, Optional

from ufo.verification.registry import RETRY_MARKER, original_request

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = max(1, int(os.environ.get("UFO_MAX_ATTEMPTS", "2")))
NARRATIVE_STEPS = 15
_FAILED_STATUSES = {"CONTINUE", "PENDING", "ASSIGN", "ERROR", "FAIL"}


@dataclass
class AttemptOutcome:
    task: str
    success: bool
    reason: str
    log_path: str = ""


def assess(session, task: str) -> AttemptOutcome:
    """Decide whether a finished session verifiably completed its request."""
    log_path = getattr(session, "log_path", "") or ""
    if session.is_error():
        return AttemptOutcome(task, False, "the session ended in an error state", log_path)
    host = getattr(session, "host_agent", None)
    verdict = getattr(host, "last_goal_verdict", None)
    if verdict is not None and verdict.achieved is False:
        missing = f" Still missing: {verdict.missing}" if verdict.missing else ""
        return AttemptOutcome(task, False, f"{verdict.reason}{missing}", log_path)
    status = str(getattr(host, "status", "") or "").upper()
    if verdict is None and status in _FAILED_STATUSES:
        return AttemptOutcome(task, False, f"it stopped before finishing (last status {status})", log_path)
    reason = verdict.reason if verdict is not None else "finished (not independently verified)"
    return AttemptOutcome(task, True, reason, log_path)


def _short(value, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def behaviour_narrative(log_path: str, max_steps: int = NARRATIVE_STEPS) -> str:
    """Summarise an attempt's response.log as 'agent: action -> outcome' lines."""
    path = os.path.join(log_path or "", "response.log")
    lines: List[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            records = [json.loads(line) for line in f if line.strip().startswith("{")]
    except (OSError, ValueError) as e:
        logger.info(f"No usable response.log at {path}: {e}")
        return ""
    for rec in records:
        agent = rec.get("agent_name") or rec.get("agent_type") or "agent"
        actions = rec.get("action") if isinstance(rec.get("action"), list) else []
        for act in actions:
            if not isinstance(act, dict) or not act.get("function"):
                continue
            res = act.get("result") if isinstance(act.get("result"), dict) else {}
            outcome = res.get("status") or ""
            if res.get("error"):
                outcome = f"{outcome} ({_short(res['error'], 80)})"
            call = act.get("action_string") or f"{act['function']}({act.get('arguments', {})})"
            lines.append(f"- {agent}: {_short(call)} -> {outcome or 'no result'}")
        if not actions and rec.get("function_call"):
            lines.append(f"- {agent}: {_short(rec['function_call'])}")
    return "\n".join(lines[-max_steps:])


def build_retry_request(request: str, previous: AttemptOutcome) -> str:
    narrative = behaviour_narrative(previous.log_path) or "- (no actions were recorded)"
    return (
        f"{original_request(request)}{RETRY_MARKER}\n"
        "A previous attempt at this request did not complete it.\n"
        f"Why it was judged incomplete: {previous.reason}\n"
        f"What it already did (most recent last):\n{narrative}\n"
        "Continue from the current screen state. Do not repeat steps that already succeeded "
        "(do not re-type text that is already there, re-create files that already exist, or "
        "re-open apps that are already open); do only what is still missing."
    )


async def run_until_verified(
    task: str,
    request: str,
    run_attempt: Callable[[str, str], Awaitable[object]],
    max_attempts: Optional[int] = None,
) -> List[AttemptOutcome]:
    """Run attempts one after another until one is verified or the budget is spent.

    ``run_attempt(task_name, request)`` must run a session to completion and
    return it. Returns the outcome of every attempt, in order.
    """
    budget = max_attempts or MAX_ATTEMPTS
    outcomes: List[AttemptOutcome] = []
    current = request
    for i in range(1, budget + 1):
        name = task if i == 1 else f"{task}_try{i}"
        session = await run_attempt(name, current)
        outcome = assess(session, name)
        outcomes.append(outcome)
        logger.info(f"Attempt {i}/{budget} ({name}): success={outcome.success} - {outcome.reason}")
        if outcome.success:
            break
        if i < budget:
            current = build_retry_request(request, outcome)
    return outcomes


def outcomes_as_dicts(outcomes: List[AttemptOutcome]) -> List[dict]:
    return [asdict(o) for o in outcomes]
