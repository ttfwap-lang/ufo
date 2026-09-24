"""End-to-end check that the deployed runner's tool loop can see the vision stack.

Runs INSIDE the runner container: exercises the real bridge over the tailnet
with the real token, so this proves the whole chain the agent will use.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BRIDGE = os.environ.get("UFO_BRIDGE_URL", "http://100.113.176.84:9301").rstrip("/")
TOKEN_FILE = os.environ.get("UFO_BRIDGE_TOKEN_FILE", "/app/ufo_bridge_token.txt")


def call(action, params, job_id):
    token = open(TOKEN_FILE).read().strip()
    body = json.dumps({"job_id": job_id, "action": action,
                       "params": params}).encode()
    req = urllib.request.Request(
        BRIDGE + "/jobs", data=body,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        json.loads(r.read().decode())
    import time
    for _ in range(120):
        time.sleep(5)
        rq = urllib.request.Request(
            f"{BRIDGE}/result/{job_id}",
            headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(rq, timeout=30) as r:
            job = json.loads(r.read().decode())
        if job.get("status") in ("done", "error"):
            return job
    return {"status": "timeout"}


print("1) bridge health (includes vision reachability)")
j = call("health", {}, "t-health-1")
print("  ", json.dumps(j.get("result") or j.get("error"))[:300])

print("2) list_actions")
j = call("list_actions", {}, "t-actions-1")
print("  ", json.dumps(j.get("result") or j.get("error"))[:300])

print("3) vision_locate on a TEXT label (no click)")
j = call("vision_locate", {"label": "Write", "prefer": "auto"},
         "t-vision-text-1")
r = j.get("result") or {}
print(f"   status={j.get('status')} found={r.get('found')} "
      f"xy=({r.get('x')},{r.get('y')}) strategy={r.get('strategy')} "
      f"err={j.get('error')}")

print("4) vision_locate on an ICON OCR cannot see (no click)")
j = call("vision_locate",
         {"label": "the microphone voice message button", "prefer": "venus"},
         "t-vision-icon-1")
r = j.get("result") or {}
print(f"   status={j.get('status')} found={r.get('found')} "
      f"xy=({r.get('x')},{r.get('y')}) safe={r.get('safe_to_click')} "
      f"err={j.get('error')}")

print("5) vision_ask (semantic state question)")
j = call("vision_ask",
         {"question": "Which application is in the foreground and which chat "
                      "is open? Answer in one short sentence."},
         "t-vision-ask-1")
r = j.get("result") or {}
print(f"   status={j.get('status')} answer={str(r.get('answer'))[:220]}")
