# gx10 capacity, contention and failure behaviour

Analysis and fixes for everything that shares the gx10 (2026-09-26 outage). Status of each
item says what was **verified here** and what is **written but not yet run on the box**.

## What went wrong

The gx10 went "up but dead": ICMP 1 ms, TCP :22 accepts, sshd never sends a banner, tailscale
offline, `gx10.local` unresolvable. That is userspace starvation from memory/swap thrash on the
121 GB unified-memory GB10. Contributing causes, all found in the repo:

| # | Cause | Where |
|---|-------|-------|
| 1 | Four launchers with four different budgets: Qwen 0.35 / 0.56 / 0.68 / 0.70, Venus 0.19 / 0.20 / 0.26. Any two of the larger ones (0.70 + 0.20 = 109 GB) leave nothing for OS, page cache, sshd, tailscaled. | `qwen_run.sh`, `rebalance_models.sh`, SparkDeck, docs |
| 2 | Three controllers act on the same containers/ports (SparkDeck `mm stack`, `ufo_watchdog.sh` every 2 min, our scripts). :8000 has been served by vLLM `qwen-abliterated` *and* llama.cpp `qwen38-27b-turbo`. | `docs`, `ufo_watchdog.sh` |
| 3 | Qwen ran `--max-num-seqs 1`: every user and agent step queued behind the previous one. | `qwen_run.sh` |
| 4 | `gx10_runner/venus_run.sh` bound UI-Venus to `0.0.0.0` (LAN, no auth) and ignored the budget; `ollama.service` bound `0.0.0.0` and kept models loaded 5 min. | repo |
| 5 | OmniParser on the gx10 CPU: 34 s/parse, heaviest process on the box (now runs locally, see `omniparser_placement.md`). | `omniparser.service` |
| 6 | `scripts/*` was gitignored, so none of the above box artifacts were under version control. | `.gitignore` |

Client side, a hung gx10 turned one LLM call into about **21 minutes** of waiting: 120 s timeout used for
connect and read, 5 attempts on timeout (~630 s), then `BACKUP_AGENT` (same host:port) repeated it. The
circuit breaker was per agent type, so HOST/APP/EVALUATION each rediscovered the dead box. The
tunnel and watchers were hard-wired to `gx10.local`, and each `ssh` at a starved sshd leaves an
unauthenticated connection on it (`MaxStartups` 10).

## What changed

### Client (verified by tests; `tests/unit/test_endpoint_health.py`)
- `llm/endpoint_health.py`, wired into `llm/llm_call.py` and `llm/openai.py`:
  - **Endpoint gate** keyed by host:port, shared by all agents. After a failure a 3 s liveness probe runs; no answer opens the gate and every call fails instantly with `EndpointDown` (not retryable) for 15 s, doubling to 120 s. Measured against a hung fake server: first failure ~3.7 s, further calls (any agent) < 0.5 s, and the same-endpoint BACKUP is not tried.
  - **Timeouts get one retry**, not four (`_stop_on_repeated_timeout`).
  - **In-flight cap per local endpoint** (`UFO_LLM_MAX_INFLIGHT`, default 4): surplus callers queue on the client instead of timing out in the server's queue and being retried on top of it.
  - **Served-model discovery**: on a 404 the client asks `/v1/models` and uses the one unambiguous served name, and remembers it. `agents_dgx.yaml` says `qwen38-27b-turbo`, the vLLM launcher says `qwen-abliterated`; either now works.
  - **Keep-alive** 300 s (httpx default 5 s re-handshook through the SSH tunnel on every step), pool 400 → 64, split 10 s connect timeout that actually takes effect (the SDK's own `timeout=` used to override it).
- `scripts/gx10_host.ps1` + `gx10_tunnel_keepalive.ps1`: tunnel picks the first address that shows an SSH banner (`gx10.local`, then `gx10-lan`/`gx10-tailscale` from `~/.ssh/config`); a wedged box is reported as `wedged` and left alone rather than ssh'd at. Verified live: during the outage it correctly reported `192.168.4.103=wedged`, and when the box returned `gx10.local` stayed wedged while the LAN address answered.

### Box (guard verified in WSL with fake `/proc` + docker; units/sysctl **not yet run on the box**)
- `scripts/dgx/gx10_budget.env`: the only place sizes live. Qwen 0.35 (seqs 4), Venus 0.20 (seqs 4), pool ceiling 0.62 (75 GB).
- **Free-memory policy: 5% floor (enforced), 10% target (encouraged)** - `FREE_FLOOR_PCT` / `FREE_TARGET_PCT`:
  - launch (`gx10_guard.sh`): a launch that would leave < 5% free is refused, not bypassable even with `GX10_FORCE`; < 10% warns (`GX10_STRICT=1` refuses); `--audit` warns < 10%, critical < 5%.
  - runtime (`gx10_memguard.sh`, systemd timer every 30 s): < 10% releases cheap reclaimable memory (unload Ollama models, drop clean page cache, stop CPU OmniParser); < 5% additionally stops one container per 2 min from `SHED_CONTAINERS` (empty by default: no model is stopped unless you name it). earlyoom acts at the same 5% floor as the last line. Nothing is killed while free memory is above 5%.
- `scripts/dgx/gx10_guard.sh`: launch lock + refusal if pools exceed the ceiling or MemAvailable is short; runs *before* the old container is removed so a refused launch never kills a working model. `--audit` reports pools, free %, swap and kernel memory pressure (PSI; `full avg10 > 10%` = thrashing). 37 scenarios pass (guard, floor/target, enforcer tiers), including 0.56+0.26 and 0.70+0.20 being refused.
- `qwen_run.sh` / `venus_run.sh` use it; Qwen also answers to `qwen38-27b-turbo` (`QWEN_ALIASES`). `gx10_runner/venus_run.sh` and `rebalance_models.sh` are now thin, budget-driven forwards.
- `protect_ssh.sh`: OOM shield for sshd/tailscaled/dockerd/containerd, `vm.min_free_kbytes` 2 GB, `vm.swappiness` 10, earlyoom at the 5% floor if installed. `--dry-run` / `--status`.
- `ollama.service`: 127.0.0.1, keep-alive 2 m, one loaded model. `ufo-galaxy.target`: no longer wants OmniParser.

## One Qwen, concurrent, and what "max efficiency" means here
- **Retired: the llama.cpp Qwen3.8-27B Q8 (`qwen38-27b-turbo`)** via `gx10_retire_qwen27b.sh` (stops it, `--restart=no`, removes its profile from SparkDeck stacks, backups kept). It is dense (all ~27 GB of weights read per token, ~10 tok/s at the GB10's ~273 GB/s), holds ~30 GB and its slots split one context. **Kept: vLLM Qwen3.6-35B-A3B** (3B active parameters, NVFP4 + MTP speculative decoding, continuous batching). It answers to `qwen38-27b-turbo` too, so no client changes.
- **Concurrency:** `QWEN_SEQS` 1 -> 8, `VENUS_SEQS` 2 -> 8 (same memory pools: hybrid-attention KV is small). Client cap `UFO_LLM_MAX_INFLIGHT` 4 per process.
- **Efficiency knobs that are opt-in, not default (cannot be validated while the box is down):** `VENUS_QUANT=fp8` (halves Venus weight reads, frees ~9 GB; run `bench_venus*.py` first, it can move click coordinates), `QWEN_EXTRA_ARGS` (e.g. `--async-scheduling`; an unsupported flag stops the container starting). Measure before/after with a load test; the gains stated here are from the arithmetic, not measurements.
- Auxiliary Qwens (`qwen35-9b-defiant-q6`, `qwen3-0.6b`) are the first things `gx10_memguard.sh` sheds at the 5% floor.

## To apply on the box (needs a healthy sshd; restarts the model containers)
**Automatic:** `powershell -File scripts\gx10_apply.ps1` waits for a usable sshd, ships `scripts/dgx`, and runs `gx10_apply.sh` detached on the box (retire the 27B, install, memguard timer, recreate Qwen/Venus only if their flags differ, protect_ssh if passwordless sudo). Logs: `%LOCALAPPDATA%\ufo\gx10_apply.log` and `~/ufo-galaxy/logs/apply.log`.

Manual equivalent:
```
scp scripts/dgx/* flak3dd@<gx10>:~/ufo-galaxy/dgx-new/ && ssh flak3dd@<gx10> 'bash ~/ufo-galaxy/dgx-new/install.sh'
ssh flak3dd@<gx10> 'bash ~/ufo-galaxy/gx10_guard.sh --audit'
sudo bash protect_ssh.sh --dry-run     # then without --dry-run
ssh flak3dd@<gx10> 'bash ~/ufo-galaxy/qwen_run.sh && bash ~/ufo-galaxy/venus_run.sh'   # interrupts current users
```
If SparkDeck owns the containers it will still reset them; put the same numbers in its profiles (or point it at
`/srv/models/gx10_budget.env`). The guard protects only launches that go through our scripts; `--audit` (or the
watchdog calling it) is how a SparkDeck launch that blows the budget gets noticed.

## Not measured
Throughput gain from `QWEN_SEQS` 1 → 4 and whether 0.35/0.20 fits on the current model builds are expectations
from the memory arithmetic, not measurements; the box was unreachable. Run `--audit` and a load test after applying.

## Measured after applying (2026-09-26, through the SSH tunnel from the Windows PC)
- `:8000` serves `qwen-abliterated` and `qwen38-27b-turbo` (the alias works); `:8002` serves `ui-venus`. llama.cpp 27B is stopped and out of the `balanced`/`full` stacks.
- Single stream ~83 tok/s (the dense 27B was estimated at ~10). 8 concurrent short requests finished in 1.8 s wall, ~480-500 tok/s aggregate, on three runs. 4 concurrent varied 150-310 tok/s (warm-up noise).
- Memory after the apply: pools 0.60 (Qwen 0.35 + Venus 0.20 + 0.6B 0.05), 39 GB available (~32% free), memory pressure 0.00%, swap down from 8 GB to 7 GB and stuck there (cold pages).
- **One 82 s stall** on the first request of one test run (3 tok/s), not reproduced in the other runs. Most likely swapped-out pages of the model process being touched. If it recurs, `sudo swapoff -a && sudo swapon -a` returns the swap to RAM (~7 GB, there is room).
- Installed and active: memguard timer, OOM shield for sshd/tailscaled/dockerd/containerd, `vm.swappiness=10`, `vm.min_free_kbytes` 2 GB. **Not installed: earlyoom** (`sudo apt-get install -y earlyoom` then re-run `protect_ssh.sh`); without it the kill layer at the 5% floor does not exist and only memguard's release/shed steps enforce it.
- Still running and not touched: `qwen35-9b-defiant` (llama.cpp) and `qwen3-0.6b` (vLLM 0.05).
- Venus was restarted once by something other than `gx10_apply.sh` after the stack files were edited (SparkDeck re-syncing its stacks is the likely cause; not confirmed).
