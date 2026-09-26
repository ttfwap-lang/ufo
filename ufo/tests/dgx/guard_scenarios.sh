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
  inspect) name="${@: -1}"; for p in $FAKE_PODS; do [ "${p%%=*}" = "$name" ] && printf -- '--port\n8000\n--gpu-memory-utilization\n%s\n--max-num-seqs\n4\n' "${p#*=}"; done ;;
esac
D
chmod +x "$T/bin/docker"

setmem() { # setmem <avail_gb> <swap_used_mb> <some> <full>
  printf 'MemTotal: %d kB\nMemAvailable: %d kB\nSwapTotal: 16777216 kB\nSwapFree: %d kB\n' \
    $((121*1048576)) $(($1*1048576)) $((16777216 - $2*1024)) > "$T/proc/meminfo"
  printf 'some avg10=%s avg60=0.00 avg300=0.00 total=0\nfull avg10=%s avg60=0.00 avg300=0.00 total=0\n' "$3" "$4" > "$T/proc/pressure/memory"
}
run() { # run <pods> <cmd...> ; sets OUT, RC
  local pods="$1"; shift
  OUT=$(PATH="$T/bin:$PATH" FAKE_PODS="$pods" GX10_PROC="$T/proc" GX10_LOCK="$T/lock" GX10_LOCK_WAIT=2 bash -c ". '$DGX/gx10_guard.sh'; $*" 2>&1); RC=$?
}
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (want $2 got $3) :: $OUT"; fi; }

setmem 80 0 0.5 0.0
run "" 'guard_acquire qwen-abliterated 0.35';                       check "fresh box, 0.35 fits"                      0 $RC
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.35';          check "0.35 + venus 0.20 = 0.55 <= 0.62"          0 $RC
run "ui-venus=0.26" 'guard_acquire qwen-abliterated 0.56';          check "old rebalance 0.56+0.26 refused"           3 $RC
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.70';          check "SparkDeck 0.70+0.20 refused"               3 $RC
echo "$OUT" | grep -q "REFUSED" && echo "PASS refusal names the reason" || echo "FAIL refusal message :: $OUT"
GX10_FORCE=1 run "ui-venus=0.20" 'GX10_FORCE=1 guard_acquire qwen-abliterated 0.70'; check "GX10_FORCE=1 overrides"    0 $RC

setmem 40 0 0.5 0.0   # only 40 GB free: 0.35*121=42 + 24 reserve = 66 needed
run "" 'guard_acquire qwen-abliterated 0.35';                       check "refused when MemAvailable too low"         3 $RC
run "qwen-abliterated=0.35" 'guard_acquire qwen-abliterated 0.35';  check "replacing own pool credits its memory back" 0 $RC
# credit only applies to the container being replaced: venus's 24 GB is not free
run "ui-venus=0.20" 'guard_acquire qwen-abliterated 0.35';          check "other pool's memory is NOT credited"       3 $RC

setmem 60 0 1.0 0.0;   run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit healthy -> 0" 0 $RC
setmem 60 0 25.0 2.0;  run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit stalls -> 1 (warn)" 1 $RC
setmem 60 0 30.0 15.0; run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit thrash -> 2 (critical)" 2 $RC
setmem 60 6000 1.0 0.0; run "ui-venus=0.20 qwen-abliterated=0.35" 'guard_audit'; check "audit 6 GB swapped -> 2" 2 $RC
setmem 60 0 1.0 0.0;   run "ui-venus=0.26 qwen-abliterated=0.70" 'guard_audit'; check "audit over-budget pools -> 1" 1 $RC

# serialisation: second launcher must wait for the lock, then give up (GX10_LOCK_WAIT=2)
setmem 80 0 0.5 0.0
( exec 9>"$T/lock"; flock 9; sleep 4 ) & sleep 0.5
run "" 'guard_acquire qwen-abliterated 0.35';                       check "concurrent launcher is serialised/refused" 3 $RC
wait
