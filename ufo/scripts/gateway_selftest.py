"""Assert that every gateway alias serves the model it claims, with real content.

WHY THIS EXISTS
---------------
Two failure modes kept hitting this gateway, and both are SILENT - HTTP 200,
a plausible usage block, no exception anywhere:

  1. WRONG MODEL. llama-server (and vLLM) answer whatever model name a request
     sends. If two deployments share a port, or a swap leaves a squatter on it,
     an alias named `gx10-qwen38-27b` happily returns answers from a different
     checkpoint. Found on 2026-09-27: `gx10-qwen38-27b` was serving
     `qwen35-9b-defiant`, because the 27B container was stopped and SparkDeck
     had refilled :8004.

  2. EMPTY CONTENT. The brain GGUF always emits `reasoning_content` before
     answering and cannot be told to stop. If `max_tokens` does not cover the
     reasoning, `content` comes back as "" with HTTP 200. Any caller that only
     checks the status code thinks it succeeded.

This script catches both, plus missing keys, dead fallbacks, and unreachable
model servers. It is read-only: it never mutates the gateway.

    python scripts/gateway_selftest.py            # check every alias
    python scripts/gateway_selftest.py ufo-model  # check one
    python scripts/gateway_selftest.py --json     # machine-readable

Exit code is 0 only when every alias passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

GATEWAY = os.environ.get("UFO_GATEWAY", "http://127.0.0.1:4000")
KEY = os.environ.get("UFO_GATEWAY_KEY", "sk-local")
CONFIG = Path(__file__).resolve().parent.parent / "litellm_config.yaml"

# Aliases we expect to be broken even though they are configured, with the
# reason. Suppresses noise without hiding a NEW failure.
KNOWN_ISSUES: dict[str, str] = {
    # The 27B is on demand and SparkDeck's controller refills :8004 when it is
    # free, so this alias is answered by the 9B defiant instead. Run
    # `gx10_model_swap.sh 27b` on the box to clear it.
    "gx10-qwen38-27b": ":8004 is held by qwen35-9b-defiant, not the 27B",
    # Tongyi is on demand; the fallback to the brain is what makes this safe.
    "gx10-tongyi-30b": "on demand, not swapped in (fallback to the brain)",
    "ufo-general-model": "on demand, not swapped in (fallback to the brain)",
    # No API keys on this machine.
    "claude-3-7-sonnet": "ANTHROPIC_API_KEY not set",
    "deepseek-r1": "DEEPSEEK_API_KEY not set",
}

# Alias -> model it is KNOWN to be served by something else, with the reason.
# Same purpose as KNOWN_ISSUES: record the standing problem so it does not
# mask a NEW one. Both of these are silent - HTTP 200 every time.
KNOWN_MISMATCH: dict[str, str] = {
    "gx10-qwen38-27b": (
        ":8004 is held by qwen35-9b-defiant (the 27B container is stopped and "
        "SparkDeck's controller refills :8004 whenever it is free). Run "
        "`gx10_model_swap.sh 27b` on the box to evict the squatter."
    ),
    # All five ufo-* entries send "qwen38-27b-turbo" to :8000, which since
    # 2026-09-27 serves the 42B coder. The comment in agents_dgx.yaml still
    # describes the old 35B.
    "ufo-host-model": ':8000 serves qwen3-42b-coder, not the 27B named here',
    "ufo-app-model": ':8000 serves qwen3-42b-coder, not the 27B named here',
    "ufo-model": ':8000 serves qwen3-42b-coder, not the 27B named here',
    "ufo-dgx-model": ':8000 serves qwen3-42b-coder, not the 27B named here',
    "ufo-dgx-app-model": ':8000 serves qwen3-42b-coder, not the 27B named here',
}

# Substring the reply must contain, per alias. Empty means "any non-empty
# reply", which is still the important assertion.
EXPECT: dict[str, str] = {}


def post(url: str, body: dict, timeout: float):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KEY}",
        },
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()), time.perf_counter() - t0


def get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), time.perf_counter() - t0


# api.featherless.ai sits behind Cloudflare, which rejects Python's default
# urllib User-Agent with "error code: 1010". LiteLLM's httpx client gets
# through, which is why the gateway works while a hand-written urllib probe
# looks broken. Send a browser UA so this check can see Featherless too.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def upstream_models(api_base: str, api_key: str, timeout: float) -> list[str]:
    """Model names the deployment behind `api_base` actually advertises."""
    url = api_base.rstrip("/") + "/models"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": BROWSER_UA}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    out = []
    for m in data.get("data", []):
        # OpenAI shape uses "id"; llama.cpp's /v1/models also carries "name".
        out.append(m.get("id") or m.get("name") or "")
    return [n for n in out if n]


def resolve_key(raw: str) -> str:
    """litellm_params uses `os.environ/NAME`; this script needs the value."""
    if raw.startswith("os.environ/"):
        return os.environ.get(raw.split("/", 1)[1], "")
    return raw


def check_deployment(alias: str, params: dict, timeout: float) -> dict:
    """Does the upstream behind this entry serve the model the entry names?

    This is the only way to catch a silently-wrong model. LiteLLM rewrites the
    `model` field in its response back to the requested alias, so a gateway
    call cannot tell you what actually answered. Asking the deployment
    directly can: if the config asks for "qwen38-27b-turbo" and :8004
    advertises only "qwen35-9b-defiant", then every request naming the 27B is
    really being served by the 9B, and llama-server will never complain.

    `status` keeps cases that must not be conflated:
      ok           the deployment serves the model the entry names
      mismatch     it serves something else  <- the silent-wrong-model bug
      unreachable  nothing is listening (an on-demand model not swapped in).
                   Expected for Tongyi; NOT a defect.
      auth         /models refused the credentials - see the key note below
      no-list      no /models endpoint exists to ask
    """
    res: dict = {"alias": alias, "ok": True, "status": "ok", "detail": "",
                 "asked": "", "served": []}
    api_base = params.get("api_base")
    if not api_base:
        res["status"] = "no-list"
        res["ok"] = False
        res["detail"] = "no api_base (reached by provider SDK); cannot verify"
        return res

    asked = str(params.get("model", ""))
    for pfx in ("openai/", "anthropic/", "deepseek/", "hosted_vllm/"):
        if asked.startswith(pfx):
            asked = asked[len(pfx):]
    res["asked"] = asked

    # IMPORTANT: use the entry's OWN key, not the gateway key. Probing
    # Featherless with the local `sk-local` key returns HTTP 401 and makes a
    # perfectly healthy deployment look dead.
    api_key = resolve_key(str(params.get("api_key", KEY)))
    if not api_key:
        res["status"] = "auth"
        res["ok"] = False
        res["detail"] = (
            f"{api_base} needs a key that is not set in this environment, so "
            f"/models cannot be queried. The chat path may still work, because "
            f"LiteLLM resolves the key in its own process."
        )
        return res

    try:
        served = upstream_models(api_base, api_key, timeout)
    except urllib.error.HTTPError as e:
        res["ok"] = False
        res["status"] = "auth" if e.code in (401, 403) else "unreachable"
        res["detail"] = f"cannot list {api_base}/models: HTTP {e.code}"
        return res
    except Exception as e:
        # ConnectionRefused / RemoteDisconnected / timeout all mean the same
        # thing here: nothing is serving that port.
        res["ok"] = False
        res["status"] = "unreachable"
        res["detail"] = f"cannot list {api_base}/models: {type(e).__name__}"
        return res

    res["served"] = served
    if not served:
        res["ok"] = False
        res["status"] = "mismatch"
        res["detail"] = f"{api_base} advertises no models"
        return res

    if asked not in served:
        res["ok"] = False
        res["status"] = "mismatch"
        res["detail"] = (
            f"MISMATCH: config asks for '{asked}' but {api_base} serves only "
            f"{served}. Every call to this alias is answered by a DIFFERENT "
            f"checkpoint, with no error raised."
        )
    return res


def check(alias: str, max_tokens: int, timeout: float) -> dict:
    """One alias. Returns a verdict dict; never raises."""
    res: dict = {
        "alias": alias,
        "ok": False,
        "fallback_used": None,
        "secs": 0.0,
        "detail": "",
    }
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": "Reply with one word: the capital of France."}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    url = f"{GATEWAY}/v1/chat/completions"
    try:
        data, dt = post(url, body, timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            raw = json.loads(raw)["error"]["message"]
        except Exception:
            pass
        res["detail"] = f"HTTP {e.code}: {' '.join(raw.split())[:170]}"
        return res
    except Exception as e:
        res["detail"] = f"{type(e).__name__}: {str(e)[:150]}"
        return res

    res["secs"] = round(dt, 2)
    # LiteLLM records which deployment actually served the request.
    try:
        served = data.get("model")
    except Exception:
        served = None
    res["served_as"] = served

    if "error" in data:
        res["detail"] = f"error in 200 body: {str(data['error'])[:150]}"
        return res

    try:
        choice = data["choices"][0]
    except Exception:
        res["detail"] = f"no choices in body: {str(data)[:150]}"
        return res

    msg = choice.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    finish = choice.get("finish_reason")

    res["content_len"] = len(content)
    res["reasoning_len"] = len(reasoning)
    res["finish_reason"] = finish

    if not content:
        # The empty-content trap. Say WHY so the fix is obvious.
        if finish == "length":
            res["detail"] = (
                f"EMPTY content, finish_reason=length: the whole {max_tokens}-token "
                f"budget went to reasoning ({len(reasoning)} chars). Raise this "
                f"alias's max_tokens."
            )
        else:
            res["detail"] = (
                f"EMPTY content (finish_reason={finish}, reasoning {len(reasoning)} "
                f"chars) - upstream may have returned only reasoning_content"
            )
        return res

    want = EXPECT.get(alias)
    if want and want.lower() not in content.lower():
        res["detail"] = f"reply {content[:60]!r} does not contain {want!r}"
        return res

    res["ok"] = True
    res["detail"] = f"{' '.join(content.split())[:60]!r}"
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("aliases", nargs="*", help="only check these aliases")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    by_name = {m["model_name"]: m for m in cfg["model_list"]}

    aliases = args.aliases or list(by_name)

    # The self-test must not be tripped up by its own generous budget: the
    # point is to detect too-small budgets, so use the CONFIGURED value and
    # additionally probe a deliberately tiny one on the brain.
    results = []
    deployments = []
    for a in aliases:
        if a not in by_name:
            results.append({"alias": a, "ok": False, "detail": "not in litellm_config.yaml",
                            "secs": 0.0, "fallback_used": None})
            continue
        params = by_name[a]["litellm_params"]
        mt = params.get("max_tokens", 512)
        results.append(check(a, mt, args.timeout))
        dep = check_deployment(a, params, min(args.timeout, 60))
        deployments.append(dep)

    # Extra probe: the brain with an intentionally tiny budget must go empty.
    # This documents the trap and fails loudly if it ever stops happening
    # (which would mean thinking became disableable and max_tokens could shrink).
    brain = next((a for a in ("ufo-model", "ufo-host-model") if a in by_name), None)
    tiny = check(brain, 8, args.timeout) if brain else None

    hard = [r for r in results if not r["ok"] and r["alias"] not in KNOWN_ISSUES]
    # ONLY a genuine "mismatch" is a defect. "unreachable" is the normal state
    # of an on-demand model that has not been swapped in, and "auth" means this
    # shell lacks a key LiteLLM may still hold - neither is a wrong-model bug.
    dep_hard = [d for d in deployments
                if d["status"] == "mismatch" and d["alias"] not in KNOWN_MISMATCH]

    if args.json:
        print(json.dumps(
            {"results": results, "deployments": deployments,
             "tiny_budget_probe": tiny,
             "known_issues": KNOWN_ISSUES,
             "known_mismatches": KNOWN_MISMATCH}, indent=2))
        return 1 if (hard or dep_hard) else 0

    print("=" * 104)
    print("PHASE 1 - does each alias return real content through the gateway?")
    print("=" * 104)
    print(f"{'alias':<28}{'ok':<6}{'s':>7}  detail")
    print("-" * 104)
    for r in results:
        known = KNOWN_ISSUES.get(r["alias"])
        mark = "ok" if r["ok"] else ("KNO" if known else "FAIL")
        note = f"  [{known}]" if known and not r["ok"] else ""
        print(f"{r['alias']:<28}{mark:<6}{r['secs']:>7.1f}  {r['detail']}{note}")

    if deployments:
        print()
        print("=" * 104)
        print("PHASE 2 - does each deployment serve the model its alias names?")
        print("=" * 104)
        print(f"{'alias':<28}{'status':<13}{'asked for':<34}actually serving")
        print("-" * 104)
        for d in deployments:
            known = KNOWN_MISMATCH.get(d["alias"])
            if d["ok"]:
                mark = "ok"
            elif d["status"] == "mismatch" and known:
                mark = "KNO"
            elif d["status"] == "mismatch":
                mark = "FAIL"
            else:
                # unreachable / auth / no-list: informational, not a defect
                mark = d["status"]
            served = ", ".join(d["served"][:3]) or "-"
            if len(d["served"]) > 3:
                served += f" (+{len(d['served']) - 3} more)"
            line = f"{d['alias']:<28}{mark:<13}{d['asked']:<34}{served}"
            if not d["ok"]:
                line += f"\n{'':<42}{d['detail']}"
                if known and d["status"] == "mismatch":
                    line += f"\n{'':<42}[known: {known}]"
            print(line)

    if tiny:
        print()
        print("=" * 104)
        print("PHASE 3 - the empty-content trap (tiny budget must go empty)")
        print("=" * 104)
        print(f"{brain} at max_tokens=8: {tiny['detail']}")

    print()
    total_fail = len(hard) + len(dep_hard)
    print(f"{len(results) - len(hard)}/{len(results)} aliases return content; "
          f"{len(deployments) - len(dep_hard)}/{len(deployments)} deployments match "
          f"their name; {total_fail} unexpected failure(s)")
    for r in hard:
        print(f"  UNEXPECTED content: {r['alias']}: {r['detail']}")
    for d in dep_hard:
        print(f"  UNEXPECTED mismatch: {d['alias']}: {d['detail']}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
