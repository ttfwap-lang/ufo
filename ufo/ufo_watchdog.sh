#!/usr/bin/env bash
# =============================================================================
# ufo_watchdog.sh - self-healing supervisor for the UFO stack on gx10.
#
# WHY THIS EXISTS
#   The stack kept dying in ways nothing noticed:
#     * the Windows bridge stopped and its scheduled task never restarted it
#     * Venus was relaunched with --host 127.0.0.1, so the Windows bridge could
#       no longer reach it and every vision call silently degraded
#     * OmniParser fell back to the bare Gradio demo, losing /api/parse
#     * ufw was once enabled with no SSH rule, which cut off LAN access
#   Nothing was watching. This does.
#
# DESIGN RULES (learned the hard way)
#   1. NEVER enable/change a firewall without first guaranteeing SSH access.
#      A watchdog that can lock you out is worse than no watchdog.
#   2. Repair with a COOLDOWN, so a persistently-broken thing does not get
#      recreated every 2 minutes and thrash the GPU.
#   3. Never delete containers or data. Only start / restart / recreate a
#      single known container with a known-good command.
#   4. Every action is logged with a reason, so "why did it restart that?" is
#      always answerable from the log.
#   5. Read-only when healthy. A watchdog that writes on every pass is noise.
#
# Runs from a systemd user timer (2 min) with linger enabled, so it survives
# logout and reboot.
# =============================================================================
set -uo pipefail

LOG_DIR="$HOME/ufo-watchdog"
LOG="$LOG_DIR/watchdog.log"
STATE="$LOG_DIR/state.json"
mkdir -p "$LOG_DIR"

TAILNET_IP="$(tailscale ip -4 2>/dev/null || echo 100.67.13.78)"
WINDOWS_IP="100.113.176.84"
# Tailnet-facing ports are served by ufo-tunnel.service, not by the model
# processes themselves. The models are launched with --host 127.0.0.1 by
# another agent's stack manager; rather than relaunch them (a 17.5 GiB reload
# every round, and an unwinnable fight), the tunnel republishes them.
BRAIN_PUBLIC_PORT=18000
VENUS_PUBLIC_PORT=18002
COOLDOWN_SEC=1800            # 30 min between repair attempts for one target
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log()  { printf '%s  %-7s %s\n' "$STAMP" "$1" "$2" >>"$LOG"; }
ok()   { log INFO  "$1"; }
warn() { log WARN  "$1"; }
err()  { log ERROR "$1"; }
act()  { log ACTION "$1"; }

# Cooldown gate: returns 0 if we are allowed to attempt a repair for $1.
may_repair() {
  local key="$1" now last
  now=$(date +%s)
  last=$(cat "$LOG_DIR/.cooldown_$key" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$COOLDOWN_SEC" ]; then
    return 1
  fi
  echo "$now" >"$LOG_DIR/.cooldown_$key"
  return 0
}

http_ok() { [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-6}" "$1" 2>/dev/null)" = "200" ]; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

# --- stack awareness --------------------------------------------------------
# A second agent owns ~/models and selects what runs via ~/models/.active-stack
# plus ~/models/stacks/<name>.env (STACK_PROFILES). It had set the stack to
# "off" while this watchdog was busy resurrecting ui-venus - the two of us were
# fighting over the same containers.
#
# The rule now: the watchdog ENFORCES THE SELECTED STACK. It never starts a
# model the active stack does not list, and when the stack is "off" or
# "training" it supervises nothing but still reports. That makes it a safety
# net under the other agent's decisions rather than a competitor to them.
STACK_FILE="$HOME/models/.active-stack"
STACK_DIR="$HOME/models/stacks"

active_stack() { tr -d '[:space:]' <"$STACK_FILE" 2>/dev/null || echo unknown; }

stack_profiles() {
  local s; s=$(active_stack)
  case "$s" in
    off|training|unknown|"") echo ""; return ;;
  esac
  local f="$STACK_DIR/$s.env"
  [ -f "$f" ] || { echo ""; return; }
  grep -E '^STACK_PROFILES=' "$f" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'
}

# Should the watchdog manage a given service at all?
watches() {
  local profiles; profiles=$(stack_profiles)
  [ -z "$profiles" ] && return 1
  case " $profiles " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# --- probe cache ------------------------------------------------------------
# Every check used to issue its own curl with a 10s timeout, and the state file
# at the end probed the same five endpoints AGAIN. Worst case that exceeded the
# systemd TimeoutStartSec, so systemd killed the watchdog mid-repair - which is
# the worst possible outcome for a repair tool. Probe once, cache, reuse.
declare -A P   # P[name]=true|false
# Retry: a single 6s timeout during a container rebuild or a CPU spike is not
# evidence of failure. Without this, a transient timeout makes the watchdog
# declare a healthy service dead and "repair" it - which is how a supervisor
# becomes the cause of the outage it exists to prevent.
probe() {
  local url="$2" t="${3:-6}" attempt code
  for attempt in 1 2 3; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$t" "$url" 2>/dev/null)
    if [ "$code" = "200" ]; then P["$1"]=true; return; fi
    [ "$attempt" -lt 3 ] && sleep 2
  done
  P["$1"]=false
}
cache_all() {
  probe venus_loopback "http://127.0.0.1:8002/v1/models" 6
  probe venus_tailnet  "http://$TAILNET_IP:$VENUS_PUBLIC_PORT/v1/models" 6
  probe omni           "http://127.0.0.1:7861/api/health" 6
  probe brain          "http://127.0.0.1:8000/v1/models" 6
  probe brain_tailnet  "http://$TAILNET_IP:$BRAIN_PUBLIC_PORT/v1/models" 6
  probe tunnel_up      "http://$TAILNET_IP:$VENUS_PUBLIC_PORT/v1/models" 6
  probe bridge         "http://$WINDOWS_IP:9301/health" 8
}
# y must communicate through its EXIT STATUS, not its stdout.
# The first version ended in `echo`, so the function returned 0 ("success")
# even when the value was false - every `if y ...` branch took the healthy path
# and the watchdog silently stopped repairing anything, while still printing
# reassuring "healthy" lines.
y() { [ "${P[$1]:-false}" = "true" ]; }
j() { if y "$1"; then echo true; else echo false; fi; }   # for JSON output

# ---------------------------------------------------------------------------
# 1. FIREWALL: guarantee SSH FIRST, always, before any other firewall logic.
# ---------------------------------------------------------------------------
check_firewall() {
  if ! command -v ufw >/dev/null; then return; fi
  local active sshok
  active=$(sudo -n ufw status 2>/dev/null | head -1 | grep -q 'Status: active' && echo yes || echo no)
  # SSH reachable on BOTH the LAN and tailnet paths?
  sshok=yes
  timeout 5 bash -c 'cat </dev/null >/dev/tcp/192.168.4.103/22' 2>/dev/null || sshok=no
  timeout 5 bash -c "cat </dev/null >/dev/tcp/$TAILNET_IP/22" 2>/dev/null || sshok=no

  if [ "$active" = yes ] && [ "$sshok" = yes ]; then
    return
  fi
  if [ "$active" = yes ] && [ "$sshok" = no ]; then
    err "ufw is ACTIVE but SSH is unreachable - repairing SSH rules NOW"
    for n in 100.64.0.0/10 192.168.0.0/16 10.0.0.0/8; do
      sudo -n ufw allow from "$n" to any port 22 proto tcp >/dev/null 2>&1
    done
    sudo -n ufw allow OpenSSH >/dev/null 2>&1
    act "restored SSH firewall rules (this is the lockout guard)"
    return
  fi
  # ufw inactive: ports are governed by bind address, not the firewall.
  ok "ufw inactive - ingress governed by service bind addresses"
}

# ---------------------------------------------------------------------------
# 2. VENUS - must be reachable from Windows over the tailnet.
# ---------------------------------------------------------------------------
recreate_venus() {
  # Delegate to the canonical launcher instead of repeating the docker command
  # here. Duplicating it is how the two drift apart: an earlier version of this
  # watchdog carried its own copy, pointed at a model path that does not exist
  # on this host (/home/flak3dd/models/ui-venus), and would have failed while
  # "repairing" a working service. venus_run.sh already documents and pins the
  # GPU-memory ceiling, the 0.0.0.0 bind and the real model path.
  #
  # It is launched DETACHED and this function returns immediately. venus_run.sh
  # waits for the model to answer /v1/models, which takes ~300 s for a 17.5 GiB
  # load. Blocking on that held the oneshot service open for five minutes, and
  # because the timer uses OnUnitActiveSec it could not re-arm until the service
  # went inactive - so the watchdog silently stopped running for exactly as long
  # as it was busiest. A supervisor must never be the thing that stops watching.
  local runner="$HOME/ufo-galaxy/venus_run.sh"
  if [ ! -x "$runner" ]; then
    err "venus_run.sh missing or not executable at $runner - cannot repair venus"
    return
  fi
  if [ -f "$LOG_DIR/.venus_rebuild_running" ]; then
    warn "a venus rebuild is already in flight - not starting another"
    return
  fi
  warn "rebuilding ui-venus via venus_run.sh (detached; ~5 min to load)"
  : >"$LOG_DIR/.venus_rebuild_running"
  setsid nohup bash -c "
    if bash '$runner' >>'$LOG' 2>&1; then
      rm -f '$LOG_DIR/.venus_rebuild_running'
    else
      echo '$(date -u +%Y-%m-%dT%H:%M:%SZ)  ERROR  venus_run.sh FAILED (see this log)' >>'$LOG'
      rm -f '$LOG_DIR/.venus_rebuild_running'
    fi
  " </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
  act "venus rebuild launched in background (watchdog continues immediately)"
}

check_venus() {
  local stack; stack=$(active_stack)
  if ! watches ui-venus; then
    # Not in the active stack (or the stack is off). Do NOT touch it.
    if y venus_loopback; then
      warn "stack='$stack' does not include ui-venus, but it is running - leaving it to the stack manager"
    fi
    return
  fi
  if ! container_running ui-venus; then
    # A detached rebuild may already be under way; do not race it.
    if [ -f "$LOG_DIR/.venus_rebuild_running" ]; then
      ok "ui-venus absent but a rebuild is already in flight - not starting another"
      return
    fi
    warn "ui-venus is not running"
    if may_repair venus; then recreate_venus; else warn "venus repair in cooldown"; fi
    return
  fi
  local started now age
  started=$(docker inspect -f '{{.State.StartedAt}}' ui-venus 2>/dev/null)
  now=$(date +%s); age=$(( now - $(date -d "$started" +%s 2>/dev/null || echo $now) ))

  # PROBE FIRST, judge by the answer rather than by elapsed time.
  # An earlier version checked the age threshold first, so a service that had
  # finished loading but was bound to the wrong interface stayed in the
  # "still loading" branch forever and was never repaired.
  if y venus_loopback; then
    if y venus_tailnet; then
      ok "venus healthy and reachable over the tailnet tunnel (:$VENUS_PUBLIC_PORT)"
    else
      # The model is fine; only the tunnel is missing. Repair the tunnel, NOT
      # the model. Relaunching a 17.5 GiB model to fix a port-forward problem
      # was the wrong repair and cost five minutes every time.
      warn "venus is up but not reachable on :$VENUS_PUBLIC_PORT - the tunnel is the problem, not the model"
      if may_repair tunnel; then
        act "restarting ufo-tunnel.service"
        systemctl --user restart ufo-tunnel.service >/dev/null 2>&1 \
          && act "tunnel restarted" || err "tunnel restart failed"
      else warn "tunnel repair in cooldown"; fi
      probe venus_tailnet "http://$TAILNET_IP:$VENUS_PUBLIC_PORT/v1/models" 6
    fi
    return
  fi

  # Not answering: only then does age become the useful signal.
  if [ "$age" -lt 420 ]; then
    ok "ui-venus still loading (${age}s elapsed)"
    return
  fi
  warn "venus not answering on 127.0.0.1:8002 after ${age}s"
  if [ -f "$LOG_DIR/.venus_rebuild_running" ]; then
    ok "a venus rebuild is in flight - not restarting on top of it"
    return
  fi
  if may_repair venus; then
    act "restarting ui-venus (hung or failed to bind)"
    docker restart ui-venus >/dev/null 2>&1 && act "ui-venus restarted" || err "ui-venus restart failed"
  else warn "venus repair in cooldown"; fi
}

# ---------------------------------------------------------------------------
# 3. OMNIPARSER - must expose the REST API, not just the Gradio page.
# ---------------------------------------------------------------------------
check_omniparser() {
  local active
  active=$(systemctl --user is-active omniparser.service 2>/dev/null)
  if [ "$active" != "active" ]; then
    warn "omniparser.service is '$active'"
    if may_repair omni; then
      systemctl --user restart omniparser.service >/dev/null 2>&1 \
        && act "omniparser.service restarted" || err "omniparser restart failed"
    else warn "omniparser repair in cooldown"; fi
    return
  fi
  if y omni; then
    ok "omniparser REST API healthy"
  else
    warn "omniparser is up but /api/health is missing (bare Gradio demo?)"
    if may_repair omni; then
      act "restarting omniparser to bring back the REST API"
      systemctl --user restart omniparser.service >/dev/null 2>&1 \
        && act "omniparser restarted" || err "omniparser restart failed"
    else warn "omniparser repair in cooldown"; fi
  fi
}

# ---------------------------------------------------------------------------
# 4. BRAIN (Qwen) - must answer and must do tool calls.
# ---------------------------------------------------------------------------
check_brain() {
  local c=qwen38-27b-turbo stack profiles
  stack=$(active_stack); profiles=$(stack_profiles)
  if [ -z "$profiles" ] || ! watches qwen38-27b-turbo-q8; then
    if y brain; then warn "stack='$stack' has no brain profile, but :8000 is answering - leaving it alone"; fi
    return
  fi
  if ! container_running "$c"; then
    warn "$c is not running"
    if may_repair brain; then
      docker start "$c" >/dev/null 2>&1 && act "$c started" || err "$c start failed"
    else warn "brain repair in cooldown"; fi
    return
  fi
  if y brain; then
    ok "brain answering on :8000"
  else
    warn "brain not answering on :8000"
    if may_repair brain; then
      act "restarting $c"
      docker restart "$c" >/dev/null 2>&1 && act "$c restarted" || err "$c restart failed"
    else warn "brain repair in cooldown"; fi
  fi
}

# ---------------------------------------------------------------------------
# 5. AGENT RUNNER + BRIDGE LINK
# ---------------------------------------------------------------------------
check_runner() {
  if ! container_running ufo-tg-runner; then
    warn "ufo-tg-runner is not running"
    if may_repair runner; then
      docker start ufo-tg-runner >/dev/null 2>&1 && act "ufo-tg-runner started" \
        || err "ufo-tg-runner start failed"
    else warn "runner repair in cooldown"; fi
  else
    ok "ufo-tg-runner running"
  fi
}

check_bridge_link() {
  if y bridge; then
    ok "Windows bridge reachable ($WINDOWS_IP:9301)"
  else
    warn "Windows bridge NOT reachable - the agent cannot drive the desktop"
    # The bridge is a Windows scheduled task; we cannot start it from here, but
    # a clear, repeated log line is how a human finds out in seconds.
    err "ACTION NEEDED on Windows: Start-ScheduledTask -TaskName UFO-Bridge-9301"
  fi
}

# ---------------------------------------------------------------------------
# 6. TAILSCALE + DOCKER base services
# ---------------------------------------------------------------------------
check_base() {
  for s in docker tailscaled; do
    local a
    a=$(systemctl is-active "$s" 2>/dev/null)
    [ "$a" = "active" ] || warn "$s is '$a'"
  done
  [ "$(systemctl is-active docker 2>/dev/null)" = "active" ] || {
    warn "docker is down - attempting start"
    sudo -n systemctl start docker >/dev/null 2>&1 && act "docker started" || err "docker start failed (needs sudo)"
  }
  docker ps >/dev/null 2>&1 || err "docker daemon not responding to 'docker ps'"
  local lg; lg=$(loginctl show-user "$(whoami)" -p Linger --value 2>/dev/null)
  [ "$lg" = "yes" ] || warn "linger is '$lg' - services will NOT survive logout/reboot"
  # The tunnel is what makes loopback-bound models reachable from Windows, so
  # its absence is a total vision outage even when every model is healthy.
  local ta; ta=$(systemctl --user is-active ufo-tunnel.service 2>/dev/null)
  if [ "$ta" != "active" ]; then
    warn "ufo-tunnel.service is '$ta' - Windows cannot reach any loopback-bound model"
    if may_repair tunnel; then
      systemctl --user restart ufo-tunnel.service >/dev/null 2>&1 \
        && act "ufo-tunnel.service restarted" || err "tunnel restart failed"
    else warn "tunnel repair in cooldown"; fi
  fi
}

# ---------------------------------------------------------------------------
# self-test: run with --selftest. Guards the predicate layer.
#
# A health-check helper that always reports "healthy" is the most dangerous
# possible bug in a supervisor: it looks perfect and protects nothing. That
# exact bug shipped here once (y() ended in `echo`, so it returned 0 for both
# true and false). These assertions make the failure loud and immediate.
# ---------------------------------------------------------------------------
selftest() {
  local fails=0
  P[probe_true]=true; P[probe_false]=false
  y probe_true  || { echo "  FAIL: y() must succeed for a true value"; fails=$((fails+1)); }
  y probe_false && { echo "  FAIL: y() must FAIL for a false value (this is the bug that disabled all repairs)"; fails=$((fails+1)); }
  [ "$(j probe_true)"  = "true"  ] || { echo "  FAIL: j() true  -> $(j probe_true)"; fails=$((fails+1)); }
  [ "$(j probe_false)" = "false" ] || { echo "  FAIL: j() false -> $(j probe_false)"; fails=$((fails+1)); }
  P[unset_key]=  # absent key must be false, not an error
  y unset_key && { echo "  FAIL: absent key must be false"; fails=$((fails+1)); }
  # stack-awareness predicates
  STACK_FILE=/nonexistent; active_stack() { echo off; }
  watches ui-venus && { echo "  FAIL: watches() must be false when the stack is off"; fails=$((fails+1)); }
  active_stack() { echo balanced; }
  STACK_DIR=/nonexistent
  watches ui-venus && { echo "  FAIL: watches() must be false for a missing stack file"; fails=$((fails+1)); }
  if [ "$fails" -eq 0 ]; then
    echo "selftest: all assertions passed"
    return 0
  fi
  echo "selftest: $fails assertion(s) FAILED"
  return 1
}

if [ "${1:-}" = "--selftest" ]; then selftest; exit $?; fi

# ---------------------------------------------------------------------------
main() {
  cache_all                 # one probe pass, reused by every check
  local stack profiles
  stack=$(active_stack); profiles=$(stack_profiles)
  if [ -z "$profiles" ]; then
    warn "active stack = '$stack' -> supervising NO model containers (stack manager owns them)"
  else
    ok "active stack = '$stack' -> supervising: $profiles"
  fi

  check_base
  check_firewall
  check_venus
  check_omniparser
  check_brain
  check_runner
  check_bridge_link

  # Resolve the booleans into plain scalars BEFORE the heredoc. Reading the
  # associative array through $( ) inside a heredoc runs in a subshell, which
  # is a fragile way to obtain a value you already have.
  local v_loop v_tail v_omni v_brain v_bridge v_btail
  v_loop=$(j venus_loopback); v_tail=$(j venus_tailnet)
  v_omni=$(j omni); v_brain=$(j brain); v_bridge=$(j bridge)
  v_btail=$(j brain_tailnet)

  cat >"$STATE" <<EOF
{
  "checked_at": "$STAMP",
  "tailnet_ip": "$TAILNET_IP",
  "active_stack": "$stack",
  "supervised": "${profiles:-none}",
  "venus_loopback": $v_loop,
  "venus_tailnet":  $v_tail,
  "omniparser_api": $v_omni,
  "brain":          $v_brain,
  "brain_tailnet":  $v_btail,
  "bridge":         $v_bridge
}
EOF
  # keep the log from growing without bound
  if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 20000 ]; then
    tail -5000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  fi
}

main "$@"
