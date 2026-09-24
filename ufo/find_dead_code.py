"""Find dead code / unused helpers in the files this project owns.

For each module we collect top-level function + class definitions and count how
many times the name is referenced anywhere else in the owned file set. Names
with a single occurrence are defined but never used - i.e. dead code left
behind by refactors (a very common source of "works until someone edits it"
bugs, because the dead copy can drift from the live one).
"""
from __future__ import annotations

import ast
import io
import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))

OWNED = [
    "ufo_bridge.py",
    "venus_client.py",
    "astro_collect.py",
    "astro_final_extract.py",
    "astro_extract.py",
    "astro_report.py",
    "astro_step.py",
    "run_collect.py",
    "review_repo.py",
    os.path.join("gx10_runner", "agent_runner.py"),
    os.path.join("gx10_runner", "omniparser_api.py"),
    os.path.join("automator", "app_apis", "telegram", "telegram_gui.py"),
]


def definitions(path: str) -> List[Tuple[str, int, str]]:
    src = io.open(path, encoding="utf-8", errors="replace").read()
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node.lineno, "function"))
        elif isinstance(node, ast.ClassDef):
            out.append((node.name, node.lineno, "class"))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and not sub.name.startswith("__"):
                    out.append((f"{node.name}.{sub.name}", sub.lineno, "method"))
    return out


def main() -> None:
    texts: Dict[str, str] = {}
    for rel in OWNED:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            texts[rel] = io.open(p, encoding="utf-8", errors="replace").read()
    combined = "\n".join(texts.values())

    unused: List[str] = []
    total = 0
    for rel, text in texts.items():
        for name, lineno, kind in definitions(os.path.join(ROOT, rel)):
            total += 1
            short = name.split(".")[-1]
            # count references outside the definition line itself
            hits = len(re.findall(rf"\b{re.escape(short)}\b", combined))
            self_hits = len(re.findall(rf"\b{re.escape(short)}\b", text))
            if hits <= 1:
                unused.append(f"  {rel}:{lineno}  {kind} {name}  (no references)")
            elif hits == 2 and kind == "function" and self_hits == 1:
                # referenced exactly once and only within its own file
                unused.append(f"  {rel}:{lineno}  {kind} {name}  (only self-ref)")

    print(f"owned modules : {len(texts)}")
    print(f"definitions   : {total}")
    print(f"possibly dead : {len(unused)}")
    for u in unused:
        print(u)


if __name__ == "__main__":
    main()
