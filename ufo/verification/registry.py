"""
Map a user request to deterministic checks.

The request is split into clauses ("open notepad", "type 'hi'", "save it as
a.txt"). Each rule that recognises a clause contributes a check. The outcome:

- any check FAILS            -> not achieved (definitive; confidence 1.0)
- every clause covered and
  every check PASSES         -> achieved (definitive)
- otherwise                  -> inconclusive; the LLM verifier decides, with
                                the check results as evidence.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from ufo.verification import checks
from ufo.verification.checks import CheckResult

RETRY_MARKER = "\n\n[Retry context]"

APP_PROCESSES = {
    "notepad": ["notepad.exe"],
    "word": ["WINWORD.EXE"],
    "excel": ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "paint": ["mspaint.exe"],
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "settings": ["SystemSettings.exe"],
    "vs code": ["Code.exe"],
    "visual studio code": ["Code.exe"],
    "outlook": ["OUTLOOK.EXE", "olk.exe"],
    "teams": ["ms-teams.exe"],
    "terminal": ["WindowsTerminal.exe"],
    "task manager": ["Taskmgr.exe"],
}
OFFICE_APPS = {"word", "excel", "powerpoint"}
EDITOR_APPS = {"notepad"}

_QUOTED = re.compile(r"""(?:(?<=\s)|^|(?<=[:(=]))["“'‘]([^"”'’\n]{1,300})["”'’]""")
_EXTS = r"(?:txt|md|csv|json|html?|xml|log|py|docx?|xlsx?|pptx?|pdf|png|jpe?g|zip)"
_FILENAME = re.compile(r"(?:[A-Za-z]:[\\/])?(?:[\w\-.]+[\\/])*[\w\-.]*[\w\-]\." + _EXTS + r"\b", re.I)
_QUOTED_FILENAME = re.compile(r".*\." + _EXTS + "$", re.I)
_SPLIT = re.compile(r"\s*(?:,|;|\band then\b|\bthen\b|\band\b|\balso\b)\s*", re.I)
_SAVE_VERB = re.compile(r"\b(save|saved|export|create|write|store|name it|call it)\b", re.I)
_TYPE_VERB = re.compile(r"\b(type|write|enter|input|insert|add|put)\b", re.I)
_FILLER = re.compile(r"\b(open|launch|start|run|up|the|a|an|new|app|application|program|window|please|now|for me)\b", re.I)
_OPEN_VERB = re.compile(r"\b(open|launch|start|run)\b", re.I)


def original_request(request: str) -> str:
    """Strip retry context appended by module.attempts."""
    return (request or "").split(RETRY_MARKER, 1)[0].strip()


@dataclass
class PlannedCheck:
    clause: str
    description: str
    run: Callable[[], CheckResult]


@dataclass
class Evaluation:
    results: List[CheckResult] = field(default_factory=list)
    uncovered: List[str] = field(default_factory=list)

    @property
    def failed(self) -> List[CheckResult]:
        return [r for r in self.results if r.passed is False]

    @property
    def achieved(self) -> Optional[bool]:
        if self.failed:
            return False
        if self.results and not self.uncovered and all(r.passed for r in self.results):
            return True
        return None

    def summary(self) -> str:
        lines = [str(r) for r in self.results]
        if self.uncovered:
            lines.append("Not checked automatically: " + "; ".join(self.uncovered))
        return "\n".join(lines)


def _mask_quotes(text: str) -> Tuple[str, List[str]]:
    quoted: List[str] = []

    def sub(m):
        quoted.append(m.group(1))
        return f" \x00{len(quoted) - 1}\x00 "

    return _QUOTED.sub(sub, text), quoted


def _unmask(text: str, quoted: List[str]) -> List[str]:
    return [quoted[int(i)] for i in re.findall(r"\x00(\d+)\x00", text)]


def _soften(result: CheckResult, definitive: bool) -> CheckResult:
    if result.passed is False and not definitive:
        return CheckResult(result.name, None, result.detail + " (may have been closed after use)")
    return result


def _apps_in(text: str) -> List[str]:
    low = text.lower()
    return [app for app in sorted(APP_PROCESSES, key=len, reverse=True) if re.search(rf"\b{re.escape(app)}\b", low)]


def plan_checks(request: str, since: Optional[float] = None) -> Tuple[List[PlannedCheck], List[str]]:
    """Return (checks, uncovered clauses) for a request."""
    request = original_request(request)
    masked, quoted = _mask_quotes(request)
    clauses = [c.strip() for c in _SPLIT.split(masked) if c and c.strip(" .")]
    apps = _apps_in(masked)
    typed = [q for c in clauses if _TYPE_VERB.search(c) for q in _unmask(c, quoted)]

    planned: List[PlannedCheck] = []
    uncovered: List[str] = []
    for clause in clauses:
        readable = re.sub(r"\x00(\d+)\x00", lambda m: repr(quoted[int(m.group(1))]), clause).strip(" .")
        clause_quotes = _unmask(clause, quoted)
        filenames = [f.strip() for f in _FILENAME.findall(re.sub(r"\x00\d+\x00", "", clause))]
        filenames += [q.strip() for q in clause_quotes if _QUOTED_FILENAME.match(q.strip())]
        covered = False

        if filenames and (_SAVE_VERB.search(clause) or re.search(r"\bas\b", clause, re.I)):
            for name in dict.fromkeys(filenames):
                text = next((t for t in typed if not _QUOTED_FILENAME.match(t.strip())), None)
                planned.append(PlannedCheck(readable, f"file {name}", lambda n=name, t=text: checks.check_file(n, t, since)))
            covered = True
        elif _TYPE_VERB.search(clause) and clause_quotes:
            clause_apps = _apps_in(clause) or apps
            app = next((a for a in clause_apps if a in OFFICE_APPS | EDITOR_APPS), None)
            for text in clause_quotes:
                if app in OFFICE_APPS:
                    planned.append(PlannedCheck(readable, f"{app} text", lambda a=app, t=text: checks.check_office_text(a, t)))
                    covered = True
                elif app in EDITOR_APPS:
                    planned.append(PlannedCheck(
                        readable, f"{app} text",
                        lambda a=app, t=text: checks.check_editor_text(t, APP_PROCESSES[a], label=a)))
                    covered = True
        elif _OPEN_VERB.search(clause) and _apps_in(clause):
            # In a multi-step request the app may legitimately be closed by the
            # end (e.g. after saving), so "not running" is only evidence there.
            standalone = len(clauses) == 1
            for app in _apps_in(clause)[:1]:
                planned.append(PlannedCheck(readable, f"{app} running",
                                            lambda a=app, s=standalone: _soften(checks.check_process(APP_PROCESSES[a], label=a), s)))
            # "open X" alone is fully checked; "open X to do Y" is not.
            residual = clause.lower()
            for app in _apps_in(clause):
                residual = residual.replace(app, " ")
            residual = _FILLER.sub(" ", residual)
            covered = not residual.strip(" .!")

        if not covered:
            uncovered.append(readable)
    return planned, uncovered


def evaluate(request: str, since: Optional[float] = None) -> Evaluation:
    planned, uncovered = plan_checks(request, since)
    ev = Evaluation(uncovered=uncovered)
    for p in planned:
        try:
            ev.results.append(p.run())
        except Exception as e:  # a broken probe is inconclusive, never a failure
            ev.results.append(CheckResult(p.description, None, f"check raised {e}"))
    return ev
