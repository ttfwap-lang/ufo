"""
Deterministic, read-only checks of the machine state.

Each check returns a CheckResult whose ``passed`` is True / False when the
state could be read, or None when it could not (inconclusive — never used to
reject a task). Nothing here launches an application or changes anything:
Office is only read through an already-running instance (GetActiveObject).
"""
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".py", ".ini", ".yaml", ".yml"}


@dataclass
class CheckResult:
    name: str
    passed: Optional[bool]
    detail: str

    def __str__(self) -> str:
        state = {True: "PASS", False: "FAIL", None: "N/A"}[self.passed]
        return f"[{state}] {self.name}: {self.detail}"


def _norm(text: str) -> str:
    return " ".join((text or "").replace("﻿", "").split()).lower()


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in _norm(haystack)


# ---------------------------------------------------------------- files

def candidate_dirs() -> List[Path]:
    home = Path.home()
    dirs = [home / "OneDrive" / "Desktop", home / "Desktop", home / "OneDrive" / "Documents",
            home / "Documents", home / "Downloads", home, Path.cwd()]
    seen, out = set(), []
    for d in dirs:
        if d.is_dir() and str(d).lower() not in seen:
            seen.add(str(d).lower())
            out.append(d)
    return out


def find_file(name_or_path: str) -> Optional[Path]:
    p = Path(os.path.expandvars(os.path.expanduser(name_or_path.strip())))
    if p.is_absolute():
        return p if p.is_file() else None
    for d in candidate_dirs():
        if (d / p).is_file():
            return d / p
    return None


def _read_text(path: Path) -> Optional[str]:
    for enc in ("utf-8-sig", "utf-16", "mbcs", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeError, LookupError):
            continue
        except OSError:
            return None
    return None


def check_file(name: str, contains: Optional[str] = None, since: Optional[float] = None) -> CheckResult:
    """File exists (in the path given, or on Desktop/Documents/Downloads/home),
    was written after ``since`` and, for text formats, contains ``contains``."""
    label = f"file '{name}'" + (f" contains '{contains}'" if contains else "")
    path = find_file(name)
    if path is None:
        where = ", ".join(str(d) for d in candidate_dirs()[:4])
        return CheckResult(label, False, f"not found (looked in the given path and {where})")
    if since is not None and path.stat().st_mtime < since - 2:
        return CheckResult(label, False, f"{path} exists but was not written during this task")
    if contains and path.suffix.lower() in TEXT_EXTENSIONS:
        text = _read_text(path)
        if text is None:
            return CheckResult(label, None, f"{path} exists but could not be read")
        if not _contains(text, contains):
            return CheckResult(label, False, f"{path} exists but does not contain the text")
    return CheckResult(label, True, str(path))


# ---------------------------------------------------------------- processes / windows

def running_process_names() -> List[str]:
    import psutil
    names = []
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"]:
                names.append(proc.info["name"])
        except Exception:
            continue
    return names


def check_process(names: Iterable[str], label: str = "") -> CheckResult:
    targets = [n.lower() for n in names]
    try:
        running = {n.lower() for n in running_process_names()}
    except Exception as e:
        return CheckResult(f"{label or targets} running", None, f"could not list processes: {e}")
    hit = [t for t in targets if t in running]
    return CheckResult(f"{label or targets[0]} running", bool(hit), ", ".join(hit) or "not running")


def top_window_titles() -> List[str]:
    import win32gui
    titles: List[str] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t:
                titles.append(t)
        return True

    win32gui.EnumWindows(cb, None)
    return titles


def check_window_title(text: str) -> CheckResult:
    try:
        titles = top_window_titles()
    except Exception as e:
        return CheckResult(f"window titled '{text}'", None, f"could not enumerate windows: {e}")
    hit = [t for t in titles if _contains(t, text)]
    return CheckResult(f"window titled '{text}'", bool(hit), hit[0] if hit else "no matching window")


# ---------------------------------------------------------------- reading app content

def _run_with_timeout(fn: Callable[[], Optional[str]], timeout: float, com: bool = False) -> Optional[str]:
    """Run fn on a helper thread (optionally COM-initialised) with a timeout."""
    box: dict = {}

    def target():
        pythoncom = None
        try:
            if com:
                import pythoncom
                pythoncom.CoInitialize()
            box["value"] = fn()
        except Exception as e:
            box["error"] = e
        finally:
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"read did not finish within {timeout:.0f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _uia_editor_texts(process_names: Iterable[str]) -> List[str]:
    import psutil
    from pywinauto import Desktop

    wanted = {n.lower() for n in process_names}
    texts: List[str] = []
    for win in Desktop(backend="uia").windows():
        try:
            if psutil.Process(win.element_info.process_id).name().lower() not in wanted:
                continue
        except Exception:
            continue
        for ctype in ("Document", "Edit"):
            for ctrl in win.descendants(control_type=ctype):
                text = None
                try:
                    text = ctrl.iface_text.DocumentRange.GetText(-1)
                except Exception:
                    try:
                        text = ctrl.iface_value.CurrentValue
                    except Exception:
                        text = ctrl.window_text()
                if text:
                    texts.append(text)
    return texts


def check_editor_text(text: str, process_names: Iterable[str], label: str = "editor", timeout: float = 15) -> CheckResult:
    """An edit/document control in a window of one of process_names contains text (UI Automation read)."""
    name = f"{label} text contains '{text}'"
    try:
        texts = _run_with_timeout(lambda: _uia_editor_texts(process_names), timeout, com=True)
    except Exception as e:
        return CheckResult(name, None, f"could not read the editor: {e}")
    if not texts:
        return CheckResult(name, None, "no readable text control found")
    return CheckResult(name, any(_contains(t, text) for t in texts), f"read {len(texts)} text control(s)")


OFFICE_PROGIDS = {"word": "Word.Application", "excel": "Excel.Application", "powerpoint": "PowerPoint.Application"}


def _office_text(app: str) -> Optional[str]:
    import win32com.client
    try:
        obj = win32com.client.GetActiveObject(OFFICE_PROGIDS[app])  # never starts Office
    except Exception:
        return None
    parts: List[str] = []
    if app == "word":
        for doc in obj.Documents:
            parts.append(doc.Content.Text)
    elif app == "excel":
        for wb in obj.Workbooks:
            for ws in wb.Worksheets:
                values = ws.UsedRange.Value
                rows = values if isinstance(values, tuple) else ((values,),)
                for row in rows:
                    parts.append(" ".join("" if v is None else str(v) for v in (row if isinstance(row, tuple) else (row,))))
    elif app == "powerpoint":
        for pres in obj.Presentations:
            for slide in pres.Slides:
                for shape in slide.Shapes:
                    if shape.HasTextFrame and shape.TextFrame.HasText:
                        parts.append(shape.TextFrame.TextRange.Text)
    return "\n".join(parts)


def check_office_text(app: str, text: str, timeout: float = 15) -> CheckResult:
    """An open document of a running Word/Excel/PowerPoint contains text."""
    name = f"{app} document contains '{text}'"
    try:
        content = _run_with_timeout(lambda: _office_text(app), timeout, com=True)
    except Exception as e:
        return CheckResult(name, None, f"could not read {app}: {e}")
    if content is None:
        return CheckResult(name, None, f"{app} is not running")
    return CheckResult(name, _contains(content, text), f"read {len(content)} characters")


