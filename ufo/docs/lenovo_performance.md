# Lenovo (21XJ002YAU) performance pass - 2026-09-26

Core Ultra 9 386H (16 threads), 31.5 GB, RTX PRO 1000 Blackwell 8 GB, NVMe, Windows 11 26200.
Scope: the Lenovo only (gx10 is handled separately). Every change below has a
before/after; hypotheses that measurement did not support are recorded too.

## Changed, and measured

| Change | Before | After | Where |
|---|---|---|---|
| OCR: resident WinRT engine instead of spawning `powershell ocr_shot.ps1` per call | 650-740 ms | **136-153 ms** round trip (76 ms in-process); output identical for 229/231 words, the other 2 were the old path corrupting `•` into `\x07` | `local_omniparser/winrt_ocr.py`, `/api/ocr`, `venus_client.ocr_words` |
| OmniParser full parse (icons + OCR + captions), EasyOCR -> WinRT | 1.73-1.96 s | **0.91 s** (was ~34 s on gx10 CPU) | `local_omniparser/service.py` |
| Three separate copies of "spawn PowerShell, regex the output" (venus_client, bridge, astro_collect) | 3 implementations | 1: `venus_client.ocr_words` (service first, PowerShell fallback) | |
| Watcher cycle wall time (every 2 min) | watchdog 5.2 s, scan 8.3 s | **~1.7 s, ~2.2 s** | `scripts/fastwin.ps1` |

Watcher root cause: `Get-ScheduledTask`+`Get-ScheduledTaskInfo` cost 6.2 s and
`Get-NetTCPConnection` 1.28 s per use; `schtasks /query` (125 ms) and .NET
`GetActiveTcpListeners` (30 ms) / `netstat -ano` (26 ms) return the same facts.
CPU-seconds per cycle did **not** drop (~1.8 s), because that is Windows
PowerShell 5.1's own start-up; the win is shorter wake windows, not less CPU.

Bugs found on the way (all fixed, with tests):
- The old OCR path turned `•` into a BEL control character.
- `venus_client` cached *empty* OCR results, which defeated the bridge's retry-on-empty.
- Bridge health check still defaulted Venus to unreachable `:8002` (tunnel is `:18002`).
- My own patch wrote a form-feed into a dot-source path; the scan then reported a false
  "bridge not listening" (corrected in `changes.log`). `test_powershell_script_hygiene.py`
  now catches control characters, missing dot-sourced helpers and parse errors, and the
  scripts throw instead of continuing when the helper fails to load.

## Measured and NOT a problem (do not "fix")

- **Power plan.** The third-party "Advanced SystemCare" plan has CPU min state 100% on AC and
  battery, no core parking. Hypothesis: that wastes power. A/B/A/B test on a copy of the plan
  with min 5%: package power 22 / 32.5 W vs 28 / 26.2 W, wake-up ramp 78-99 ms vs 86-87 ms,
  parse latency 457-536 ms vs 457-508 ms - all within noise. The CPU is busy with real work,
  so the floor never binds. Plan left unchanged; the test copy was deleted.
- `git status` 0.08 s, repo 73 MB pack: healthy. Disk 0.6% busy, 501 GB free. Memory 9.7 GB
  available, pagefile ~unused. Storage caches (%TEMP% 15 GB, pip 3.9 GB, npm 2.8 GB) are
  tidiness, not speed.
- `WorkloadsSessionHost` x8 (2.7 GB): Windows 11's Copilot+ on-device AI stack (Phi Silica,
  semantic search, Click to Do) on the NPU. ~0 CPU. Memory only.

## Open: needs a decision or a manual step

1. **Windows Search indexer: steady 4-11% of the machine (~1 core), not decaying** (30 s windows:
   4.2, 4.2, 5.6, 10.7%). Cause: `C:\Users\` is indexed and `Desktop\projects\ufo` is not
   excluded, so heartbeat.json (30 s), uac_worker_alive.json (seconds), scan/watchdog files
   (2 min) and two venvs keep it re-indexing. Fix, once, by hand: Settings > Privacy & security >
   Searching Windows > Advanced indexing options > Modify > uncheck `Desktop\projects\ufo`
   (or Settings > Searching Windows > Exclude folders > add it). Programmatic edits of the index
   rules were blocked by the auto-mode classifier, so this was left to the user.
   Other projects churn too (`bankfidelity`, ...).
2. Antigravity "autopilot" extension `service.exe` polls every 0.5 s: ~1.8% of the machine
   continuously. Presumably wanted (auto-accept); flagging its cost only.
3. IDEs: `idea64` (3.5 GB, ~4% CPU) and Antigravity (12 processes, 1.5 GB, ~3.8%).
4. Exposed on all interfaces: AnyDesk :7070 (auto-start service), Intel LMS :16993,
   SmartConnect, and the bridge :9301 (token-protected, by design).
5. Third-party start-up/service bloat that showed no measurable CPU but exists: IObit Advanced
   SystemCare + Driver Booster (4 scheduled tasks, service, Run key), Omnissa Horizon client
   (6 services) and WorkspaceONE telemetry, Lenovo Vantage telemetry tasks, GoogleDriveFS,
   OneDrive, Edge/Chrome auto-launch. Not disabled: no measured cost, and some may be needed.
6. The machine was found **unplugged at 10% battery**; it will shut down mid-run if left so.

## Follow-up: a frozen OmniParser, and what was ruled out (same day)

The local OmniParser stopped answering `/api/health` for >60 s while alive and listening
(2 sockets in CloseWait, working set 22 MB, log silent). A `py-spy dump` showed every thread
idle and it answered again straight afterwards, so the cause was not found. Measured and
**ruled out**: working-set trim (forcing it to 3 MB costs +1.3 s once, then nothing);
process priority (BelowNormal, the Task Scheduler default, vs Normal: 417-432 ms either way
even with 32 busy processes on 16 threads). Left unchanged.

What the incident did expose: "restart if dead" cannot heal "alive but frozen".
`bridge_watchdog.ps1` now probes `/api/health` (2 tries, 10 s each, ignoring the first 120 s
of a process's life) and restarts the task when it fails. Fault-injected with
`local_omniparser/fault_inject_freeze.ps1`: the frozen process was detected and killed
within ~2 min and a new one served again (normal restart 23 s; one cold start took ~5 min,
imports 117 s + model load 188 s, with the machine under heavy load - not reproduced).

Also found the same hour: the `run_bridge.ps1` wrapper for the bridge had been killed
(bridge alive, heartbeat 1,177 s stale), so the watchdog could only warn. Cause unknown
(another session's cleanup is possible). Restored by restarting the bridge; the watchdog
still cannot recreate a missing wrapper without interrupting a possibly busy bridge.
