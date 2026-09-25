#!/usr/bin/env bash
# =============================================================================
# ufo_scan.sh - change detector for a machine another agent is actively editing.
#
# WHY
#   Another agent is working on this same stack. Guessing at state produced
#   three wrong diagnoses in a row (wrong model path, wrong service name,
#   containers that vanished between two commands). The only reliable way to
#   cooperate is to DIFF state over time and report only what moved.
#
# CONTRACT
#   * Prints secrets NEVER. Config values are hashed, keys only.
#   * Read-only. It observes; it never repairs. (ufo_watchdog.sh repairs.)
#   * Output is a CHANGELOG, not a status dump: if nothing changed, it says so
#     in one line.
#
# USAGE
#   ufo_scan.sh snapshot   # capture current state
#   ufo_scan.sh diff       # compare to previous, emit changes, rotate
#   ufo_scan.sh watch      # snapshot+diff in a loop (for the timer)
#   ufo_scan.sh show       # print current state as JSON
# =============================================================================
set -uo pipefail

DIR="$HOME/ufo-watchdog"
SNAP="$DIR/scan.json"
PREV="$DIR/scan.prev.json"
CHANGELOG="$DIR/changes.log"
LATEST="$DIR/CHANGES.md"
mkdir -p "$DIR"

TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
h() { sha256sum "$1" 2>/dev/null | cut -c1-12; }

# --- probes -----------------------------------------------------------------
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-6}" "$1" 2>/dev/null || echo 000; }
model_ids() {
  curl -s --max-time 6 "$1/v1/models" 2>/dev/null \
    | python3 -c 'import json,sys
try: print(",".join(sorted(m.get("id","?") for m in json.load(sys.stdin).get("data",[]))))
except Exception: print("-")' 2>/dev/null || echo "-"
}
# hash a value without revealing it (for .env and tokens)
vhash() { printf '%s' "$1" | sha256sum | cut -c1-8; }

# --- snapshot ---------------------------------------------------------------
snapshot() {
python3 - "$SNAP" <<'PY'
import json, os, subprocess, hashlib, glob, time

def sh(cmd, timeout=25):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception:
        return ""

def sha(path, n=12):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:n]
    except Exception:
        return None

state = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# containers
containers = {}
names = sh("docker ps -a --format '{{.Names}}'").split()
for n in names:
    if not n:
        continue
    containers[n] = {
        "status":   sh("docker inspect -f '{{.State.Status}}' %s" % n),
        "image":    sh("docker inspect -f '{{.Config.Image}}' %s" % n),
        "restarts": sh("docker inspect -f '{{.RestartCount}}' %s" % n),
        "policy":   sh("docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' %s" % n),
        "net":      sh("docker inspect -f '{{.HostConfig.NetworkMode}}' %s" % n),
        "started":  sh("docker inspect -f '{{.State.StartedAt}}' %s" % n)[:19],
        "cmd":      hashlib.sha256(
            sh("docker inspect -f '{{json .Config.Cmd}}' %s" % n).encode()).hexdigest()[:10],
        "mounts":   sorted(sh("docker inspect -f '{{range .Mounts}}{{.Source}}:{{.Destination}},{{end}}' %s" % n).split(","))[:6],
    }
state["containers"] = containers

# endpoints: code + advertised model ids (no payloads)
def code(url):
    return sh("curl -s -o /dev/null -w '%%{http_code}' --max-time 6 %s" % url) or "000"
def ids(url):
    out = sh("curl -s --max-time 6 %s" % url)
    try:
        return ",".join(sorted(m.get("id", "?") for m in json.loads(out).get("data", [])))
    except Exception:
        return "-"
state["endpoints"] = {
    "brain_8000":      {"code": code("http://127.0.0.1:8000/v1/models"), "models": ids("http://127.0.0.1:8000/v1/models")},
    "venus_8002":      {"code": code("http://127.0.0.1:8002/v1/models"), "models": ids("http://127.0.0.1:8002/v1/models")},
    "venus_tailnet":   {"code": code("http://100.67.13.78:8002/v1/models")},
    "omni_7861":       {"code": code("http://127.0.0.1:7861/api/health")},
    "spark_8080":      {"code": code("http://127.0.0.1:8080/v1/models")},
    "bridge_9301":     {"code": code("http://100.113.176.84:9301/health")},
    "small_8005":      {"code": code("http://127.0.0.1:8005/v1/models")},
}

# listening sockets (catches a bind-address change immediately)
listeners = []
for line in sh("ss -ltn").splitlines()[1:]:
    parts = line.split()
    if len(parts) >= 4 and parts[3].rstrip(":").isdigit():
        port = int(parts[3].rstrip(":"))
        if port in (8000, 8001, 8002, 8003, 8005, 7861, 8080, 9301):
            listeners.append("%s:%d" % (parts[3].split(":")[0], port))
state["listeners"] = sorted(set(listeners))

# systemd user units of interest
units = {}
for line in sh("systemctl --user list-units --all --no-legend --plain").splitlines():
    p = line.split()
    if p and (p[0].startswith(("omniparser", "ufo", "qwen", "venus", "spark"))):
        units[p[0]] = {"active": p[2] if len(p) > 2 else "?",
                       "sub": p[3] if len(p) > 3 else "?"}
state["units"] = units

# config files: path -> {mtime, size, sha}. Content never printed.
watch = []
for pat in ("~/.config/systemd/user/*.service",
            "~/ufo-galaxy/*.sh",
            "~/ufo-tg-runner-bootstrap/.env",
            "~/OmniParser/*.py",
            "~/ufo-watchdog/*.sh",
            "~/*.sh"):
    watch += glob.glob(os.path.expanduser(pat))
files = {}
for p in sorted(set(watch)):
    try:
        st = os.stat(p)
        files[p] = {"mtime": int(st.st_mtime), "size": st.st_size, "sha": sha(p)}
    except Exception:
        pass
state["files"] = files

# .env: KEYS only, values hashed. Never emit a secret.
envkeys = {}
envp = os.path.expanduser("~/ufo-tg-runner-bootstrap/.env")
if os.path.exists(envp):
    for line in open(envp, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            envkeys[k.strip()] = hashlib.sha256(v.strip().encode()).hexdigest()[:8]
state["env_keys"] = envkeys

# model inventory
models = {}
base = os.path.expanduser("~/models")
if os.path.isdir(base):
    for entry in sorted(os.listdir(base)):
        p = os.path.join(base, entry)
        try:
            if os.path.isdir(p):
                models[entry] = "dir"
            else:
                models[entry] = "file:%d" % os.path.getsize(p)
        except Exception:
            models[entry] = "?"
state["models"] = models

# git heads
gits = {}
for repo in glob.glob(os.path.expanduser("~/ufo-*")) + glob.glob(os.path.expanduser("~/models")):
    if os.path.isdir(os.path.join(repo, ".git")):
        gits[repo] = {
            "head": sh("git -C %s rev-parse --short HEAD" % repo),
            "dirty": len(sh("git -C %s status --porcelain" % repo).splitlines()),
        }
state["git"] = gits

# resources
state["resources"] = {
    "ram_avail_gb": sh("free -g | awk 'NR==2{print $7}'"),
    "gpu_procs": len([l for l in sh("nvidia-smi --query-compute-apps=pid --format=csv,noheader").splitlines() if l.strip()]),
}

with open(os.sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(state, f, indent=1, sort_keys=True)
print("snapshot -> %s (%d containers, %d files, %d units)"
      % (os.sys.argv[1], len(containers), len(files), len(units)))
PY
}

# --- diff -------------------------------------------------------------------
diff() {
python3 - "$SNAP" "$PREV" "$LATEST" "$CHANGELOG" <<'PY'
import json, os, sys, time

snap_p, prev_p, latest_p, log_p = sys.argv[1:5]

def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

new, old = load(snap_p), load(prev_p)
if new is None:
    print("no snapshot yet"); sys.exit(0)
if old is None:
    with open(latest_p, "w", encoding="utf-8") as f:
        f.write("# Change log\n\nBaseline captured %s. No previous state to compare.\n" % new["ts"])
    print("baseline captured (no previous snapshot)"); sys.exit(0)

lines = []
def add(s): lines.append(s)

# containers
oc, nc = old.get("containers", {}), new.get("containers", {})
for name in sorted(set(oc) | set(nc)):
    if name not in oc:
        add("+ container ADDED   %-24s image=%s" % (name, nc[name].get("image")))
    elif name not in nc:
        add("- container REMOVED %-24s (was %s)" % (name, oc[name].get("image")))
    else:
        o, n = oc[name], nc[name]
        for field, label in (("status", "state"), ("image", "image"), ("policy", "policy"),
                             ("restarts", "restarts"), ("cmd", "cmd-hash"),
                             ("net", "network"), ("started", "started")):
            if str(o.get(field)) != str(n.get(field)):
                add("~ %-24s %-9s %s -> %s" % (name, label, o.get(field), n.get(field)))
        if o.get("mounts") != n.get("mounts"):
            add("~ %-24s mounts     %s" % (name, n.get("mounts")))

# endpoints
for ep in sorted(set(old.get("endpoints", {})) | set(new.get("endpoints", {}))):
    o = old.get("endpoints", {}).get(ep, {})
    n = new.get("endpoints", {}).get(ep, {})
    if o.get("code") != n.get("code"):
        add("~ endpoint %-16s HTTP %s -> %s" % (ep, o.get("code"), n.get("code")))
    if o.get("models") != n.get("models"):
        add("~ endpoint %-16s models  %s -> %s" % (ep, o.get("models"), n.get("models")))

# listeners
if old.get("listeners") != new.get("listeners"):
    add("~ LISTENERS         %s" % ", ".join(new.get("listeners", [])))
    for p in sorted(set(old.get("listeners", [])) - set(new.get("listeners", []))):
        add("  - stopped listening: %s" % p)
    for p in sorted(set(new.get("listeners", [])) - set(old.get("listeners", []))):
        add("  + now listening:     %s" % p)

# units
ou, nu = old.get("units", {}), new.get("units", {})
for u in sorted(set(ou) | set(nu)):
    if u not in ou:
        add("+ unit ADDED    %-34s %s" % (u, nu[u].get("active")))
    elif u not in nu:
        add("- unit REMOVED  %-34s" % u)
    elif ou[u].get("active") != nu[u].get("active"):
        add("~ unit %-32s %s -> %s" % (u, ou[u].get("active"), nu[u].get("active")))

# files
of, nf = old.get("files", {}), new.get("files", {})
for f in sorted(set(of) | set(nf)):
    home = os.path.expanduser("~")
    disp = f.replace(home, "~")
    if f not in of:
        add("+ file ADDED    %s" % disp)
    elif f not in nf:
        add("- file REMOVED  %s" % disp)
    elif of[f].get("sha") != nf[f].get("sha"):
        add("~ file EDITED   %-52s sha %s -> %s" % (disp, of[f].get("sha"), nf[f].get("sha")))

# env keys (values hashed upstream; we only ever print key names)
oe, ne = old.get("env_keys", {}), new.get("env_keys", {})
for k in sorted(set(oe) | set(ne)):
    if k not in oe:
        add("+ env KEY ADDED     %s" % k)
    elif k not in ne:
        add("- env KEY REMOVED   %s" % k)
    elif oe[k] != ne[k]:
        add("~ env VALUE CHANGED %s  (value not shown)" % k)

# models
om, nm = old.get("models", {}), new.get("models", {})
for m in sorted(set(om) | set(nm)):
    if m not in om:
        add("+ model ADDED    %s" % m)
    elif m not in nm:
        add("- model REMOVED  %s" % m)
    elif om[m] != nm[m]:
        add("~ model CHANGED  %s: %s -> %s" % (m, om[m], nm[m]))

# git
og, ng = old.get("git", {}), new.get("git", {})
for r in sorted(set(og) | set(ng)):
    if r not in og:
        add("+ git REPO ADDED   %s" % r)
    elif r not in ng:
        add("- git REPO REMOVED %s" % r)
    else:
        if og[r].get("head") != ng[r].get("head"):
            add("~ git HEAD         %-28s %s -> %s" % (r, og[r].get("head"), ng[r].get("head")))
        if og[r].get("dirty") != ng[r].get("dirty"):
            add("~ git DIRTY FILES  %-28s %s -> %s" % (r, og[r].get("dirty"), ng[r].get("dirty")))

# resources
orw, nrw = old.get("resources", {}), new.get("resources", {})
if orw != nrw:
    add("~ resources        %s -> %s" % (orw, nrw))

stamp = new["ts"]
if not lines:
    body = "# Change log\n\n%s  no changes\n" % stamp
    print("%s  no changes" % stamp)
else:
    body = ("# Change log\n\n## %s  (%d change(s))\n\n%s\n"
            % (stamp, len(lines), "\n".join("- " + l for l in lines)))
    with open(log_p, "a", encoding="utf-8") as f:
        f.write("\n## %s  (%d change(s))\n\n%s\n" % (stamp, len(lines),
                "\n".join("- " + l for l in lines)))
    print("%s  %d change(s)" % (stamp, len(lines)))
    for l in lines:
        print("   " + l)

with open(latest_p, "w", encoding="utf-8") as f:
    f.write(body)
PY
  # rotate: current becomes previous
  [ -f "$SNAP" ] && cp "$SNAP" "$PREV"
}

case "${1:-diff}" in
  snapshot) snapshot ;;
  show)     cat "$SNAP" ;;
  diff)     snapshot >/dev/null; diff ;;
  watch)    while true; do sleep "${2:-120}"; snapshot >/dev/null; diff; done ;;
  *) echo "usage: $0 {snapshot|diff|watch [secs]|show}"; exit 2 ;;
esac
