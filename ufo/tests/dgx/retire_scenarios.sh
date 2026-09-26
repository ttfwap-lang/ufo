#!/usr/bin/env bash
# Scenarios for scripts/dgx/gx10_retire_qwen27b.sh with a stateful fake docker and a real stack dir.
set -u
DGX="$1"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/stacks"; export RUN="$T/running" ALL="$T/all" CALLS="$T/calls"
cat > "$T/bin/docker" <<'D'
#!/usr/bin/env bash
case "$1" in
  ps) if [ "${2:-}" = "-a" ]; then cat "$ALL"; else cat "$RUN"; fi | awk '{print $1}' ;;
  inspect) n="${@: -1}"; awk -v n="$n" '$1==n{print $2}' "$ALL" ;;
  stop) echo "stop $2" >> "$CALLS"; grep -vx "$2 .*" "$RUN" > "$RUN.n"; mv "$RUN.n" "$RUN" ;;
  update) echo "update $*" >> "$CALLS" ;;
esac
D
chmod +x "$T/bin/docker"
reset() {
  printf 'qwen38-27b-turbo ghcr.io/ggml-org/llama.cpp:server-cuda\nqwen-abliterated vllm/vllm-openai:cu130-nightly\nui-venus vllm/vllm-openai:latest\n' > "$ALL"; cp "$ALL" "$RUN"; : > "$CALLS"
  printf 'STACK_PROFILES="qwen38-27b-turbo-q8 ui-venus qwen3-0.6b"\nOTHER=1\n' > "$T/stacks/balanced.env"
  printf "STACK_PROFILES='ui-venus qwen35-9b-defiant-q6'\n" > "$T/stacks/vision.env"
  printf 'STACK_PROFILES=\n' > "$T/stacks/training.env"; rm -f "$T"/stacks/*.bak-retire
}
r() { OUT=$(PATH="$T/bin:$PATH" GX10_STACK_DIR="$T/stacks" bash "$DGX/gx10_retire_qwen27b.sh" "$@" 2>&1); RC=$?; }
ok() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (want [$2] got [$3]) :: $OUT"; fi; }

reset; r --dry-run
ok "dry-run stops nothing" "" "$(cat "$CALLS")"
ok "dry-run leaves stack file alone" 'STACK_PROFILES="qwen38-27b-turbo-q8 ui-venus qwen3-0.6b"' "$(head -1 "$T/stacks/balanced.env")"

reset; r; ok "exit 0" 0 $RC
ok "stops only the llama.cpp 27B" "stop qwen38-27b-turbo" "$(grep '^stop' "$CALLS")"
ok "sets restart=no on it" 1 "$(grep -c 'update --restart=no qwen38-27b-turbo' "$CALLS")"
grep -q "qwen-abliterated\|ui-venus" "$CALLS" && echo "FAIL touched vLLM/Venus :: $(cat $CALLS)" || echo "PASS vLLM Qwen and Venus untouched"
ok "vLLM Qwen still running" 1 "$(grep -c '^qwen-abliterated' "$RUN")"
ok "27B removed from balanced stack, others kept" 'STACK_PROFILES="ui-venus qwen3-0.6b"' "$(head -1 "$T/stacks/balanced.env")"
ok "non-stack lines preserved" 'OTHER=1' "$(sed -n 2p "$T/stacks/balanced.env")"
ok "backup made once" 1 "$(ls "$T"/stacks/*.bak-retire | wc -l)"
ok "unrelated stack untouched" "STACK_PROFILES='ui-venus qwen35-9b-defiant-q6'" "$(cat "$T/stacks/vision.env")"

: > "$CALLS"; r; ok "second run exits 0" 0 $RC
ok "second run stops nothing" "" "$(grep '^stop' "$CALLS")"
ok "backup not overwritten by 2nd run" 'STACK_PROFILES="qwen38-27b-turbo-q8 ui-venus qwen3-0.6b"' "$(head -1 "$T/stacks/balanced.env.bak-retire")"
