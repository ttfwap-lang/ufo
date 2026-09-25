# UFO supervision & change detection

Two independent systems live here. Keeping them separate is deliberate: the
observer must never be able to take the supervisor down with it.

| Component | Cadence | Role |
|---|---|---|
| `ufo_watchdog.sh` (`ufo-watchdog.timer`) | 2 min | **repairs** the stack |
| `ufo_scan.sh` (`ufo-scan.timer`) | 2 min | **observes** changes, read-only |
| `ufo_tunnel.py` (`ufo-tunnel.service`) | always on | republishes loopback-bound models on the tailnet |
| `bridge_watchdog.ps1` (Windows task) | 2 min | keeps the Windows bridge alive |
| `run_bridge.ps1` (Windows task) | always on | bridge + rotating log + heartbeat |

Windows equivalents: `ufo_scan_win.ps1`, `install_scan_task.ps1`.

## Files

- `state.json` — last health snapshot (machine readable)
- `watchdog.log` — every action, with the reason for it
- `changes.log`, `CHANGES.md` — what changed, and when
- `tunnel.log` — tunnel connections
- `.cooldown_<target>` — repair-backoff timestamps
- `.venus_rebuild_running` — lock so a rebuild is never started twice
- `.previous-stack` — the model stack that was active before we changed it

## Ports

| Port | Meaning |
|---|---|
| 8000 / 8002 / 7861 | model servers, **bound to 127.0.0.1 on gx10** |
| 18000 | tunnel → brain |
| 18002 | tunnel → Venus |
| 18061 | tunnel → OmniParser |
| 9301 | Windows bridge (the agent's only route to the desktop) |

A listener on `0.0.0.0:8002` cannot coexist with one on `127.0.0.1:8002`, so
the tunnel uses different ports rather than trying to rebind the models.

## Rules the watchdog follows

1. **Never touch the firewall before guaranteeing SSH.** It was once enabled
   here with no SSH rule, which cut off LAN access. Tailscale SSH is the
   fallback that saved it, and the watchdog now re-asserts SSH rules on every
   path before it will consider the firewall healthy.
2. **Obey the selected stack.** `~/models/.active-stack` plus
   `~/models/stacks/<name>.env` decide what should run. The watchdog supervises
   only the profiles listed there, and does nothing at all when the stack is
   `off` or `training`. It previously resurrected Venus while another agent had
   deliberately set the stack to `off`.
3. **Repair with a cooldown.** 30 minutes per target, so a permanently broken
   thing cannot be recreated every 2 minutes and thrash the GPU.
4. **Never block.** Repairs are detached. A repair that waits 5 minutes for a
   model to load held the oneshot open long enough that the timer could not
   re-arm, so the watchdog silently stopped running while busiest.
5. **Retry before declaring failure.** A single timeout during a rebuild is not
   evidence of a dead service; acting on it makes the supervisor the cause of
   the outage.
6. **Delete nothing.** Only start, restart, or relaunch one known container.
7. **Log the reason for every action.**

## Verify it is actually working

```sh
~/ufo-watchdog/ufo_watchdog.sh --selftest   # predicate layer
cat ~/ufo-watchdog/state.json               # health now
tail -40 ~/ufo-watchdog/watchdog.log        # what it did and why
cat ~/ufo-watchdog/CHANGES.md               # what changed, incl. other agents
```

The self-test exists because the worst possible bug in a supervisor is a health
predicate that always reports "healthy". That shipped here once: a helper ended
in `echo`, so it returned success for both true and false, every branch took
the healthy path, and the watchdog printed reassuring lines while repairing
nothing.
