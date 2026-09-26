#!/usr/bin/env bash
# Scenario driver for scripts/dgx/gx10_guard.sh: fake /proc + fake docker, real bash/awk/flock.
# Usage: guard_scenarios.sh <path-to-scripts/dgx>      Prints one "PASS|FAIL name" line per scenario.
set -u
DGX="$1"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/proc/pressure" "$T/bin"

# fake docker: `docker ps` lists $FAKE_PODS names; `docker inspect -f ... <name>` prints its Cmd lines.
cat > "$T/bin/docker" <<'D'
#!/usr/bin/env bash
case "$1" in
  ps) for p in $FAKE_PODS; do echo "${p%%=*}"; done ;;
  stop) echo "docker $*" >> "$CALLS" ;;
  inspect) name="${@: -1}"; for p in $FAKE_PODS; do [ "${p%%=*}" = "$name" ] && printf -- '--port\n8000\n--gpu-memory-utilization\n%s\n--max-num-seqs\n4\n' "${p#*=}"; done ;;
esac
D
chmod +x "$T/bin/docker"

# fakes that record what the enforcer would do
cat > "$T/bin/curl" <<'C'
#!/usr/bin/env bash
case "$*" in
  *api/ps*) echo '{"models":[{"name":"gemma4-ufo:latest"}]}' ;;
  *) echo "curl $*" >> "$CALLS" ;;
esac
C
cat > "$T/bin/systemctl" <<'C'
#!/usr/bin/env bash
case "$*" in
  *is-active*omniparser*) [ "${FAKE_OMNI:-0}" = 1 ] ;;
  *stop*) echo "systemctl $*" >> "$CALLS" ;;
esac
C
cat > "$T/bin/sudo" <<'C'
#!/usr/bin/env bash
exit 1
C
chmod +x "$T/bin/curl" "$T/bin/systemctl" "$T/bin/sudo"
mkdir -p "$T/proc/sys/vm"; : > "$T/proc/sys/vm/drop_caches"; CALLS="$T/calls"; export CALLS

setmem() { # setmem <avail_gb> <swap_used_mb> <some> <full>
  printf 'MemTotal: %d kB\nMemAvailable: %d kB\nSwapTotal: 16777216 kB\nSwapFree: %d kB\n' \
    $((121*1048576)) $(($1*1048576)) $((16777216 - $2*1024)) > "$T/proc/meminfo"
  printf 'some avg10=%s avg60=0.00 avg300=0.00 total=0\nfull avg10=%s avg60=0.00 avg300=0.00 total=0\n' "$3" "$4" > "$T/proc/pressure/memory"
}
run() { # run <pods> <cmd...> ; sets OUT, RC
  local pods="$1"; shift
  OUT=$(PATH="$T/bin:$PATH" FAKE_PODS="$pods" GX10_PROC="$T/proc" GX10_LOCK="$T/lock" GX10_LOCK_WAIT=2 bash -c "set -euo pipefail; . '$DGX/gx10_guard.sh'; $*" 2>&1); RC=$?
}
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (want $2 got $3) :: $OUT"; fi; }

setmem 80 0 0.5 0.0
run "" 'guard_acquire qwen-abliterated 0.35';                       check "fresh box, 0.35 fits"                      0 $RC
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.35';          check "0.35 + venus 0.20 = 0.55 <= 0.62"          0 $RC
run "ui-venus=0.26" 'guard_acquire qwen-abliterated 0.56';          check "old rebalance 0.56+0.26 refused"           3 $RC
run "ui-venus=0.24 qwen3-0.6b=0.05" 'guard_acquire qwen-abliterated 0.35'; check "box reality 0.24+0.05+0.35=0.64 with 66% free: allowed" 0 $RC
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.70';          check "SparkDeck 0.70+0.20 refused"               3 $RC
echo "$OUT" | grep -q "REFUSED" && echo "PASS refusal names the reason" || echo "FAIL refusal message :: $OUT"
setmem 110 0 0.5 0.0   # enough free memory that only the pool ceiling is in the way
GX10_FORCE=1 run "ui-venus=0.20" 'GX10_FORCE=1 guard_acquire qwen-abliterated 0.70'; check "GX10_FORCE=1 overrides the pool ceiling" 0 $RC
setmem 80 0 0.5 0.0

setmem 40 0 0.5 0.0   # only 40 GB free: 0.35*121=42 + 24 reserve = 66 needed
run "" 'guard_acquire qwen-abliterated 0.35';                       check "refused when MemAvailable too low"         3 $RC
run "qwen-abliterated=0.35" 'guard_acquire qwen-abliterated 0.35';  check "replacing own pool credits its memory back" 0 $RC
# credit only applies to the container being replaced: venus's 24 GB is not free
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.35';          check "other pool's memory is NOT credited"       3 $RC

setmem 60 0 1.0 0.0;   run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit healthy -> 0" 0 $RC
setmem 60 0 25.0 2.0;  run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit stalls -> 1 (warn)" 1 $RC
setmem 60 0 30.0 15.0; run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit thrash -> 2 (critical)" 2 $RC
setmem 60 6000 1.0 0.0; run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit 6 GB in swap but no pressure -> warn (1), not critical" 1 $RC
setmem 60 0 1.0 0.0;   run "ui-venus=0.26 qwen-abliterated=0.70" 'guard_audit'; check "audit over-budget pools -> 1" 1 $RC

# ---- floor (5%) / target (10%) at launch. 0.35 pool = 42 GB of 121.
setmem 55 0 0.5 0.0; run "" 'guard_acquire qwen-abliterated 0.35';  check "13 GB (10.7%) free after: ok, no warning" 0 $RC
echo "$OUT" | grep -q WARNING && echo "FAIL no warning expected :: $OUT" || echo "PASS no warning at >= target"
setmem 50 0 0.5 0.0; run "" 'guard_acquire qwen-abliterated 0.35';  check "8 GB (6.6%) free after: allowed (encouraged, not forced)" 0 $RC
echo "$OUT" | grep -q "under the 10% target" && echo "PASS warns when under target" || echo "FAIL warning missing :: $OUT"
run "" 'GX10_STRICT=1 guard_acquire qwen-abliterated 0.35';         check "GX10_STRICT=1 refuses under target" 3 $RC
setmem 46 0 0.5 0.0; run "" 'guard_acquire qwen-abliterated 0.35';  check "4 GB (3.3%) free after: refused (under 5% floor)" 3 $RC
run "" 'GX10_FORCE=1 guard_acquire qwen-abliterated 0.35';          check "floor is not bypassable by GX10_FORCE" 3 $RC
setmem 11 0 0.5 0.0; run "" 'guard_audit';                           check "audit 9.1% free -> warn (1)" 1 $RC
setmem 5 0 0.5 0.0;  run "" 'guard_audit';                           check "audit 4.1% free -> critical (2)" 2 $RC

# ---- enforcer (gx10_memguard.sh): tiers and what each does
mg() { : > "$CALLS"; OUT=$(PATH="$T/bin:$PATH" FAKE_PODS="${FAKE_PODS:-}" FAKE_OMNI="${FAKE_OMNI:-0}" GX10_PROC="$T/proc"   GX10_MEMGUARD_LOG="$T/mg.log" GX10_MEMGUARD_STATE="$T/mg.state" SHED_CONTAINERS="${SHED:-}" bash "$DGX/gx10_memguard.sh" "$@" 2>&1); RC=$?; }
called() { grep -q "$1" "$CALLS"; }
rm -f "$T/mg.state"
setmem 60 0 0.5 0.0; mg;                                            check "memguard: 49.6% free -> ok (0)" 0 $RC
[ ! -s "$CALLS" ] && echo "PASS memguard: ok tier does nothing" || echo "FAIL ok tier acted :: $(cat $CALLS)"
setmem 11 0 0.5 0.0; FAKE_OMNI=1 mg;                                check "memguard: 9.1% free -> low (1)" 1 $RC
echo "$OUT" | grep -q "unload Ollama model gemma4-ufo:latest" && echo "PASS memguard: unloads Ollama" || echo "FAIL no ollama unload :: $OUT"
called '"keep_alive":0' && echo "PASS memguard: sends keep_alive 0" || echo "FAIL keep_alive call missing"
called "systemctl --user stop omniparser" && echo "PASS memguard: stops CPU OmniParser" || echo "FAIL omniparser not stopped"
[ "$(cat "$T/proc/sys/vm/drop_caches")" = "1" ] && echo "PASS memguard: drops clean page cache" || echo "FAIL drop_caches not written"
called "docker stop" && echo "FAIL low tier must not stop containers" || echo "PASS memguard: low tier stops no container"
setmem 5 0 0.5 0.0; FAKE_PODS="ui-venus=0.20" SHED="" mg;           check "memguard: 4.1% free -> floor (2)" 2 $RC
called "docker stop" && echo "FAIL nothing listed in SHED_CONTAINERS" || echo "PASS memguard: floor never stops an unlisted model"
rm -f "$T/mg.state"; FAKE_PODS="ui-venus=0.20" SHED="qwen3-0.6b ui-venus" mg
called "docker stop ui-venus" && echo "PASS memguard: floor sheds the listed container that is running" || echo "FAIL shed missing :: $(cat $CALLS)"
FAKE_PODS="ui-venus=0.20" SHED="qwen3-0.6b ui-venus" mg
called "docker stop" && echo "FAIL second pass inside 120 s must not stop again" || echo "PASS memguard: shedding is rate-limited"
rm -f "$T/mg.state"; FAKE_PODS="ui-venus=0.20" SHED="ui-venus" mg --dry-run
called "docker stop" && echo "FAIL --dry-run acted" || echo "PASS memguard: --dry-run changes nothing"

# ---- per-box overrides: gx10_budget.local.env wins over the shipped budget
LD="$(mktemp -d)"; cp "$DGX/gx10_guard.sh" "$DGX/gx10_budget.env" "$LD/"
v=$(bash -c ". '$LD/gx10_guard.sh'; echo \$QWEN_SEQS"); check "shipped budget: QWEN_SEQS=8" 8 "$v"
echo 'QWEN_SEQS="${QWEN_SEQS:-3}"' > "$LD/gx10_budget.local.env"   # same ${VAR:-x} form as the budget
v=$(bash -c ". '$LD/gx10_guard.sh'; echo \$QWEN_SEQS"); check "local override wins: QWEN_SEQS=3" 3 "$v"
v=$(QWEN_SEQS=5 bash -c ". '$LD/gx10_guard.sh'; echo \$QWEN_SEQS"); check "environment beats both: QWEN_SEQS=5" 5 "$v"
rm -rf "$LD"

# serialisation: second launcher must wait for the lock, then give up (GX10_LOCK_WAIT=2)
setmem 80 0 0.5 0.0
( exec 9>"$T/lock"; flock 9; sleep 4 ) & sleep 0.5
run "" 'guard_acquire qwen-abliterated 0.35';                       check "concurrent launcher is serialised/refused" 3 $RC
wait
