#!/usr/bin/env bash
# gx10_apply.sh --dry-run decisions: restart only what differs from the budget.
set -u
DGX="$1"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT; mkdir -p "$T/bin" "$T/proc"
printf 'MemTotal: 126877696 kB\nMemAvailable: %d kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n' $((60*1048576)) > "$T/proc/meminfo"
cat > "$T/bin/docker" <<'D'
#!/usr/bin/env bash
# FAKE_QWEN_ARGS / FAKE_VENUS_ARGS: newline-separated Cmd for the running container of that name
case "$1" in
  ps) [ "${2:-}" = "-a" ] && { echo qwen-abliterated; echo ui-venus; } || { echo qwen-abliterated; echo ui-venus; } ;;
  inspect) n="${@: -1}"
    case "$*" in *Config.Image*) echo img ;; *) [ "$n" = qwen-abliterated ] && printf '%b' "$FAKE_QWEN_ARGS" || printf '%b' "$FAKE_VENUS_ARGS" ;; esac ;;
esac
D
chmod +x "$T/bin/docker"
run() { OUT=$(PATH="$T/bin:$PATH" GX10_PROC="$T/proc" GX10_LOCK="$T/lock" bash "$DGX/gx10_apply.sh" --dry-run 2>&1); }
QOK='--served-model-name\nqwen-abliterated\nqwen38-27b-turbo\n--max-num-seqs\n8\n--gpu-memory-utilization\n0.35\n'
VOK='--max-num-seqs\n8\n--gpu-memory-utilization\n0.20\n'
chk() { if echo "$OUT" | grep -q "$2"; then echo "PASS $1"; else echo "FAIL $1 :: $(echo "$OUT" | sed -n '/3\/5/,/5\/5/p')"; fi; }
chkno() { if echo "$OUT" | grep -q "$2"; then echo "FAIL $1 :: $OUT"; else echo "PASS $1"; fi; }
export FAKE_QWEN_ARGS="$QOK" FAKE_VENUS_ARGS="$VOK"; run
chk   "matching Qwen is not restarted" "already running with the intended settings"
chkno "matching Qwen/Venus: no recreate" "would recreate"
echo "$OUT" | grep -q "APPLY_DONE" && echo "PASS dry-run completes" || echo "FAIL no APPLY_DONE :: $OUT"
export FAKE_QWEN_ARGS='--max-num-seqs\n1\n--gpu-memory-utilization\n0.35\n--served-model-name\nqwen-abliterated\n'; run
chk   "seqs=1 Qwen (old config) is recreated" "would recreate qwen-abliterated"
export FAKE_QWEN_ARGS='--max-num-seqs\n8\n--gpu-memory-utilization\n0.70\n--served-model-name\nqwen-abliterated\nqwen38-27b-turbo\n'; run
chkno "a pool size that differs from the budget does not restart Qwen" "would recreate qwen-abliterated"
export FAKE_VENUS_ARGS='--max-num-seqs\n8\n--gpu-memory-utilization\n0.24\n'; run
chkno "SparkDeck Venus at 0.24 (seqs ok) is not restarted" "would recreate ui-venus"
export FAKE_VENUS_ARGS="$VOK"
export FAKE_QWEN_ARGS="$QOK" FAKE_VENUS_ARGS='--max-num-seqs\n2\n--gpu-memory-utilization\n0.20\n'; run
chk   "seqs=2 Venus is recreated" "would recreate ui-venus"
export FAKE_QWEN_ARGS='--max-num-seqs\n8\n--gpu-memory-utilization\n0.35\n--served-model-name\nqwen-abliterated\n'; export FAKE_VENUS_ARGS="$VOK"; run
chk   "missing legacy alias forces Qwen recreate" "would recreate qwen-abliterated"
