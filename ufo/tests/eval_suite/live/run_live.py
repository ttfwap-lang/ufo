"""
Live multi-app showcase runner.

Runs the tasks in tasks.yaml one at a time through `python -m ufo` (the real
desktop agent, retry-until-verified), verifies each result deterministically,
closes only what the task opened, and writes a report.

    python -m ufo.tests.eval_suite.live.run_live --list
    python -m ufo.tests.eval_suite.live.run_live --dry-run
    python -m ufo.tests.eval_suite.live.run_live                # all tasks (drives this desktop!)
    python -m ufo.tests.eval_suite.live.run_live --tasks N1,W1 --keep

Everything is written under Desktop\\ufo_e2e (the sandbox), which must not
exist beforehand and is removed afterwards unless --keep is given.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml

PACKAGE_DIR = Path(__file__).resolve().parents[3]  # .../ufo (the package)
REPO_ROOT = PACKAGE_DIR.parent                      # launch dir for `python -m ufo`
TASKS_FILE = Path(__file__).with_name("tasks.yaml")
OFFICE_PROGIDS = {"winword.exe": "Word.Application", "excel.exe": "Excel.Application", "powerpnt.exe": "PowerPoint.Application"}
NEVER_KILL = {"explorer.exe"}  # the desktop shell hosts File Explorer windows
TASK_TIMEOUT = int(os.environ.get("UFO_LIVE_TASK_TIMEOUT", "1500"))
DGX_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i",
           str(Path.home() / ".ssh" / "id_ed25519_ufo_agent"), "flak3dd@gx10.local"]


def desktop_dir() -> Path:
    home = Path.home()
    for d in (home / "OneDrive" / "Desktop", home / "Desktop"):
        if d.is_dir():
            return d
    return home / "Desktop"


# ---------------------------------------------------------------- tasks

@dataclass
class LiveTask:
    id: str
    title: str
    request: str
    verify: Dict
    apps: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    galaxy: bool = False


def load_tasks(sandbox: Path, path: Path = TASKS_FILE) -> List[LiveTask]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = []
    for raw in data["tasks"]:
        raw = dict(raw)
        raw["request"] = " ".join(raw["request"].split()).replace("{sandbox}", str(sandbox))
        tasks.append(LiveTask(**raw))
    ids = {t.id for t in tasks}
    for t in tasks:
        missing = set(t.depends_on) - ids
        if missing:
            raise ValueError(f"{t.id} depends on unknown task(s) {missing}")
    return tasks


# ---------------------------------------------------------------- verifiers

Verdict = Tuple[Optional[bool], str]


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-16", "mbcs", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeError, LookupError):
            continue
    return ""


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def v_file_text(sandbox: Path, spec: Dict) -> Verdict:
    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    text = _read_text(p)
    if spec.get("normalize_digits"):
        text = re.sub(r"(?<=\d)[,\s.](?=\d{3}\b)", "", text)
    missing = [c for c in spec.get("contains", []) if _norm(c) not in _norm(text)]
    return (not missing), (f"missing {missing}" if missing else f"{p.name} contains all expected text")


def v_file_regex(sandbox: Path, spec: Dict) -> Verdict:
    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    m = re.search(spec["pattern"], _read_text(p))
    return bool(m), (f"found {m.group(0)!r}" if m else "pattern not found")


def v_docx(sandbox: Path, spec: Dict) -> Verdict:
    import docx

    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    doc = docx.Document(str(p))
    paras = doc.paragraphs
    problems = []
    if spec.get("heading"):
        match = [x for x in paras if _norm(spec["heading"]) in _norm(x.text)]
        if not match:
            problems.append(f"no paragraph with heading {spec['heading']!r}")
        elif spec.get("heading_style") and not any(x.style.name == spec["heading_style"] for x in match):
            problems.append(f"heading style is {match[0].style.name!r}, expected {spec['heading_style']!r}")
    if spec.get("paragraph") and not any(_norm(spec["paragraph"]) in _norm(x.text) for x in paras):
        problems.append(f"no paragraph containing {spec['paragraph']!r}")
    if spec.get("bold") and not any(r.bold and spec["bold"] in r.text for x in paras for r in x.runs):
        problems.append(f"{spec['bold']!r} is not bold anywhere")
    return (not problems), ("; ".join(problems) or "document content and formatting as requested")


def v_xlsx(sandbox: Path, spec: Dict) -> Verdict:
    import openpyxl

    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    ws = openpyxl.load_workbook(str(p)).worksheets[0]
    problems = []
    for ref, expected in (spec.get("cells") or {}).items():
        actual = ws[ref].value
        if str(actual).strip().lower() != str(expected).strip().lower():
            problems.append(f"{ref}={actual!r} (expected {expected!r})")
    if spec.get("formula_cell"):
        formula = str(ws[spec["formula_cell"]].value or "").replace(" ", "").upper()
        if not formula.startswith(spec["formula_prefix"].replace(" ", "").upper()):
            problems.append(f"{spec['formula_cell']} formula is {formula!r}")
    if spec.get("min_charts"):
        with zipfile.ZipFile(str(p)) as z:  # openpyxl drops charts on load; count the parts
            charts = [n for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
        if len(charts) < spec["min_charts"]:
            problems.append(f"{len(charts)} chart(s)")
    return (not problems), ("; ".join(problems) or "cells, formula and chart present")


def v_pptx(sandbox: Path, spec: Dict) -> Verdict:
    from pptx import Presentation

    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    prs = Presentation(str(p))
    titles, texts = [], []
    for slide in prs.slides:
        titles.append(slide.shapes.title.text if slide.shapes.title is not None else "")
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    all_text = _norm("\n".join(texts))
    problems = [f"missing title {t!r}" for t in spec.get("titles", []) if not any(_norm(t) == _norm(x) for x in titles)]
    problems += [f"missing text {t!r}" for t in spec.get("text", []) if _norm(t) not in all_text]
    return (not problems), ("; ".join(problems) or f"{len(prs.slides)} slides with expected titles and bullets")


def v_fs(sandbox: Path, spec: Dict) -> Verdict:
    problems = [f"{p} missing" for p in spec.get("exists", []) if not (sandbox / p).exists()]
    problems += [f"{p} still present" for p in spec.get("missing", []) if (sandbox / p).exists()]
    return (not problems), ("; ".join(problems) or "file system matches")


def windows_display_version() -> str:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
        return str(winreg.QueryValueEx(k, "DisplayVersion")[0])


def v_winver(sandbox: Path, spec: Dict) -> Verdict:
    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    expected = windows_display_version()
    ok = expected.lower() in _read_text(p).lower()
    return ok, (f"contains {expected}" if ok else f"does not contain {expected}")


def v_png_not_blank(sandbox: Path, spec: Dict) -> Verdict:
    from PIL import Image

    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    img = Image.open(p).convert("RGB")
    colors = sorted(img.getcolors(maxcolors=1 << 24) or [], reverse=True)
    total = img.width * img.height
    drawn = total - (colors[0][0] if colors else total)
    ok = drawn / total > 0.01
    return ok, f"{drawn / total:.1%} of pixels differ from the background"


def dgx_readings() -> Tuple[str, int]:
    out = subprocess.run(DGX_SSH + ["df -h / | tail -1 | awk '{print $4}'; docker ps -q | wc -l"],
                         capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL).stdout.split()
    return out[0], int(out[1])


def v_dgx_report(sandbox: Path, spec: Dict) -> Verdict:
    p = sandbox / spec["path"]
    if not p.is_file():
        return False, f"{p.name} not found"
    text = _read_text(p)
    avail, containers = dgx_readings()
    size_ok = avail.rstrip("GTMi").split(".")[0] in text
    count_ok = re.search(rf"\b{containers}\b", text) is not None
    detail = f"DGX now: {avail} free, {containers} containers; file: {' '.join(text.split())[:120]!r}"
    return size_ok and count_ok, detail


VERIFIERS: Dict[str, Callable[[Path, Dict], Verdict]] = {
    "file_text": v_file_text, "file_regex": v_file_regex, "docx": v_docx, "xlsx": v_xlsx,
    "pptx": v_pptx, "fs": v_fs, "winver": v_winver, "png_not_blank": v_png_not_blank,
    "dgx_report": v_dgx_report,
}


def verify(task: LiveTask, sandbox: Path) -> Verdict:
    try:
        return VERIFIERS[task.verify["type"]](sandbox, task.verify)
    except Exception as e:  # a crashing verifier is inconclusive, not a pass
        return None, f"verifier error: {e}"


# ---------------------------------------------------------------- cleanup

def process_snapshot(names: List[str]) -> Dict[int, str]:
    import psutil

    wanted = {n.lower() for n in names}
    snap = {}
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "").lower()
        if name in wanted:
            snap[proc.info["pid"]] = name
    return snap


def _close_office(name: str, sandbox: Path, quit_app: bool) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject(OFFICE_PROGIDS[name])
    except Exception:
        return
    try:
        collection = {"winword.exe": "Documents", "excel.exe": "Workbooks", "powerpnt.exe": "Presentations"}[name]
        for doc in list(getattr(app, collection)):
            full = str(getattr(doc, "FullName", "") or "")
            saved_elsewhere = full and os.path.isabs(full) and not full.lower().startswith(str(sandbox).lower())
            if not saved_elsewhere:  # sandbox or never-saved documents created by the task
                doc.Close(False) if name != "powerpnt.exe" else doc.Close()
        if quit_app:
            app.Quit()
    except Exception as e:
        print(f"    cleanup: {name}: {e}")


def _close_explorer_windows(sandbox: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        for w in list(win32com.client.Dispatch("Shell.Application").Windows()):
            try:
                path = str(w.Document.Folder.Self.Path)
            except Exception:
                continue
            if path.lower().startswith(str(sandbox).lower()):
                w.Quit()
    except Exception as e:
        print(f"    cleanup: explorer windows: {e}")


def cleanup(task: LiveTask, before: Dict[int, str], sandbox: Path) -> List[str]:
    """Close what the task opened; never touch processes that existed before it."""
    import psutil
    import win32con
    import win32gui
    import win32process

    closed = []
    after = process_snapshot(task.apps)
    new = {pid: name for pid, name in after.items() if pid not in before}
    for name in {n.lower() for n in task.apps} & set(OFFICE_PROGIDS):
        started_now = name in new.values()
        _close_office(name, sandbox, quit_app=started_now and name not in before.values())
    if "explorer.exe" in {n.lower() for n in task.apps}:
        _close_explorer_windows(sandbox)
    targets = {pid for pid, name in new.items() if name not in NEVER_KILL}

    def post_close(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in targets:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True

    if targets:
        win32gui.EnumWindows(post_close, None)
        time.sleep(3)
        for pid in targets:
            try:
                proc = psutil.Process(pid)
                proc.terminate()  # only instances this task started (e.g. an unsaved-changes prompt)
                closed.append(f"{new[pid]}:{pid}")
            except psutil.NoSuchProcess:
                closed.append(f"{new[pid]}:{pid}")
    return closed


# ---------------------------------------------------------------- running UFO

def ufo_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update({"UFO_DGX_HOST": "127.0.0.1", "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO_ROOT),
                "UFO_MAX_ATTEMPTS": env.get("UFO_MAX_ATTEMPTS", "2")})
    if not env.get("UFO_DGX_WS_TOKEN"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                env["UFO_DGX_WS_TOKEN"] = winreg.QueryValueEx(k, "UFO_DGX_WS_TOKEN")[0]
        except OSError:
            pass
    return env


def python_exe() -> str:
    return str(PACKAGE_DIR / ".venv" / "Scripts" / "python.exe")


class WindowsDevice:
    """Local UFO server + client registered as Galaxy device 'windowsagent' (G1)."""

    def __init__(self, env: Dict[str, str], log_dir: Path):
        self.env = dict(env)
        self.token = secrets.token_hex(24)
        self.env["UFO_WS_TOKEN"] = self.token  # read from the environment, never argv
        self.log_dir = log_dir
        self.procs: List[subprocess.Popen] = []

    def __enter__(self):
        py = python_exe()
        server_log = open(self.log_dir / "windowsagent_server.log", "w", encoding="utf-8")
        client_log = open(self.log_dir / "windowsagent_client.log", "w", encoding="utf-8")
        self.procs.append(subprocess.Popen([py, "-m", "ufo.server.app", "--host", "127.0.0.1", "--port", "5005",
                                            "--platform", "windows"], cwd=REPO_ROOT, env=self.env,
                                           stdout=server_log, stderr=subprocess.STDOUT))
        time.sleep(8)
        self.procs.append(subprocess.Popen([py, "-m", "ufo.client.client", "--ws", "--ws-server",
                                            "ws://127.0.0.1:5005/ws", "--client-id", "windowsagent",
                                            "--platform", "windows"], cwd=REPO_ROOT, env=self.env,
                                           stdout=client_log, stderr=subprocess.STDOUT))
        time.sleep(10)
        return self

    def galaxy_env(self) -> Dict[str, str]:
        env = dict(self.env)
        env.pop("UFO_WS_TOKEN", None)
        env["UFO_WIN_WS_TOKEN"] = self.token
        env["UFO_GALAXY_AUTO_CONNECT"] = "windowsagent"
        return env

    def __exit__(self, *exc):
        for p in reversed(self.procs):
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()


@dataclass
class TaskResult:
    id: str
    title: str
    status: str  # pass | fail | inconclusive | skipped | error
    detail: str
    seconds: float = 0.0
    attempts: List[Dict] = field(default_factory=list)
    log_dir: str = ""
    closed: List[str] = field(default_factory=list)


def run_task(task: LiveTask, sandbox: Path, report_dir: Path, stamp: str) -> TaskResult:
    task_name = f"live_{stamp}_{task.id}"
    env = ufo_env()
    before = process_snapshot(task.apps)
    started = time.time()
    out_path = report_dir / f"{task.id}.out.txt"
    try:
        with open(out_path, "w", encoding="utf-8") as out:
            if task.galaxy:
                with WindowsDevice(env, report_dir) as device:
                    cmd = [python_exe(), "-m", "ufo.galaxy", "--request", task.request, "--task-name", task_name]
                    subprocess.run(cmd, cwd=PACKAGE_DIR, env=device.galaxy_env(), stdout=out,
                                   stderr=subprocess.STDOUT, timeout=TASK_TIMEOUT)
            else:
                cmd = [python_exe(), "-m", "ufo", "-t", task_name, "-r", task.request, "--skip-preflight"]
                subprocess.run(cmd, cwd=REPO_ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=TASK_TIMEOUT)
        ok, detail = verify(task, sandbox)
        status = {True: "pass", False: "fail", None: "inconclusive"}[ok]
    except subprocess.TimeoutExpired:
        status, detail = "error", f"UFO did not finish within {TASK_TIMEOUT}s"
    except Exception as e:
        status, detail = "error", f"runner error: {e}"
    seconds = time.time() - started
    attempts = []
    result_json = REPO_ROOT / "logs" / task_name / "result.json"
    if result_json.is_file():
        attempts = json.loads(result_json.read_text(encoding="utf-8")).get("attempts", [])
    closed = cleanup(task, before, sandbox)
    return TaskResult(task.id, task.title, status, detail, round(seconds, 1), attempts,
                      str(REPO_ROOT / "logs" / task_name), closed)


# ---------------------------------------------------------------- report

def write_report(results: List[TaskResult], report_dir: Path) -> Path:
    (report_dir / "report.json").write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    passed = sum(r.status == "pass" for r in results)
    lines = [f"# UFO live showcase — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"**{passed}/{len(results)} tasks verified.**", "",
             "| Task | Result | Attempts | Time | Verifier detail |", "|---|---|---|---|---|"]
    for r in results:
        attempts = len(r.attempts) or ("—" if r.status in ("skipped",) else 1)
        detail = r.detail.replace("|", "\\|")
        lines.append(f"| {r.id} {r.title} | {r.status.upper()} | {attempts} | {r.seconds:.0f}s | {detail} |")
    path = report_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", help="comma-separated task ids (default: all)")
    parser.add_argument("--list", action="store_true", help="list tasks and exit")
    parser.add_argument("--dry-run", action="store_true", help="validate tasks and print the plan; runs nothing")
    parser.add_argument("--keep", action="store_true", help="keep the sandbox folder afterwards")
    args = parser.parse_args(argv)

    sandbox = desktop_dir() / "ufo_e2e"
    tasks = load_tasks(sandbox)
    if args.tasks:
        wanted = [t.strip().upper() for t in args.tasks.split(",") if t.strip()]
        tasks = [t for t in tasks if t.id.upper() in wanted]
    if args.list or args.dry_run:
        for t in tasks:
            print(f"{t.id:4} {t.title:45} apps={','.join(t.apps)} verify={t.verify['type']}"
                  + (f" after={','.join(t.depends_on)}" if t.depends_on else ""))
            if args.dry_run:
                print(f"     request: {t.request}")
        return 0

    if sandbox.exists():
        print(f"Refusing to run: {sandbox} already exists (remove it or pick another location).")
        return 2
    sandbox.mkdir(parents=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = REPO_ROOT / "logs" / f"live_e2e_{stamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    results: List[TaskResult] = []
    status_by_id: Dict[str, str] = {}
    try:
        for task in tasks:
            blocked = [d for d in task.depends_on if status_by_id.get(d) != "pass"]
            if blocked:
                results.append(TaskResult(task.id, task.title, "skipped", f"depends on {blocked}"))
                status_by_id[task.id] = "skipped"
                continue
            print(f"[{datetime.now():%H:%M:%S}] {task.id} {task.title} ...", flush=True)
            result = run_task(task, sandbox, report_dir, stamp)
            print(f"    -> {result.status.upper()} ({result.seconds:.0f}s): {result.detail}", flush=True)
            results.append(result)
            status_by_id[task.id] = result.status
            write_report(results, report_dir)
    finally:
        report = write_report(results, report_dir)
        if not args.keep:
            shutil.rmtree(sandbox, ignore_errors=True)
        print(f"Report: {report}")
    return 0 if all(r.status == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
