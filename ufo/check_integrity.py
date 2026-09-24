"""Static integrity check for the automation stack.

`ast.parse` proves the file COMPILES; it does not prove the names it CALLS
exist. A refactor that deletes a helper still compiles and only explodes at
runtime, in the middle of an automation run (this happened during review: a
regex-based cleanup removed `_ocr_reports`, which was still called).

This module resolves every module-level name referenced by the code we own
and reports anything undefined, so that class of bug is caught statically.
"""
from __future__ import annotations

import ast
import builtins
import io
import os
import sys
from typing import Dict, List, Set, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))

OWNED = [
    "ufo_bridge.py",
    "venus_client.py",
    "astro_collect.py",
    "run_collect.py",
    os.path.join("gx10_runner", "agent_runner.py"),
    os.path.join("gx10_runner", "omniparser_api.py"),
]

# Names provided by the environment / third-party at runtime.
KNOWN_EXTERNAL = {
    "asyncio", "os", "sys", "re", "json", "time", "queue", "secrets", "uuid",
    "base64", "threading", "traceback", "subprocess", "tempfile", "shutil",
    "stat", "collections", "itertools", "functools", "dataclasses", "typing",
    "pathlib", "io", "math", "random", "string", "textwrap", "argparse",
    "datetime", "hashlib", "hmac", "logging", "traceback", "warnings",
    "ctypes", "struct", "glob", "csv", "socket", "ssl", "signal", "copy",
    "PIL", "psutil", "win32gui", "win32con", "win32process", "win32ui",
    "ufo", "venus_client", "astro_collect", "uac_run", "automator",
    "automation", "fastapi", "gradio", "torch", "numpy", "uvicorn",
    "dotenv", "requests", "aiohttp", "pydantic", "yaml", "toml", "PIL.Image",
}


def collect_defined(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            pass
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names


def called_names(tree: ast.AST) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out[fn.id] = out.get(fn.id, 0) + 1
            elif isinstance(fn, ast.Attribute):
                base = fn
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    out[base.id] = out.get(base.id, 0) + 1
    return out


def main() -> int:
    problems: List[str] = []
    for rel in OWNED:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            problems.append(f"{rel}: MISSING FILE")
            continue
        src = io.open(path, encoding="utf-8", errors="replace").read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            problems.append(f"{rel}:{e.lineno}: SYNTAX {e}")
            continue
        defined = collect_defined(tree) | set(dir(builtins)) | KNOWN_EXTERNAL
        for name, count in sorted(called_names(tree).items()):
            if name not in defined:
                problems.append(
                    f"{rel}: calls undefined name {name!r} ({count}x)")
    if problems:
        print(f"INTEGRITY PROBLEMS: {len(problems)}")
        for p in problems:
            print("  " + p)
        return 1
    print(f"integrity OK: {len(OWNED)} owned modules, "
          f"all called names resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
