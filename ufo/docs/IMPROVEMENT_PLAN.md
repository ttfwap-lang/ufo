# UFO improvement plan (from the 2026-09-27 whole-tree review)

Inputs:
1. **Whole-tree code review** at `6e4ee5c`: 34 verified findings.
   - Read line by line: the Telegram package, `automation/`, the controller hot paths, the root elevation and bridge scripts, `security/`, `server/` and `gx10_runner`.
   - Heuristic sweep only (ruff, grep for eval/exec/shell/secrets/input injection): `galaxy/`, `llm/`, `config/`, `agents/`, `module/`, `prompter/`, `aip/`, `learner/`, `tools/`.
   - Not read: most `.ps1` files and most of `scripts/`.
2. **Repo metrics** (radon, pyflakes, grep).
3. **Full test suite** results.
4. **Incident, 27 Sep 00:26–00:46.** The peer script `ufo_skill_state/fix_all.py` damaged three venvs, the uv cache and 38 untracked source files. It has been repaired and verified; see [[project-venv-corruption-20260927]] in memory.

Every item names **how to verify it**. The standard is the same as for the review fixes: a test that fails on the old code and passes on the new.

---

## Phase 0: security and safety (do first, each is small)

| # | Where | Problem | Fix | Verify |
|---|---|---|---|---|
| 0.1 | `uac_worker.py:87-92` | **Local privilege escalation to SYSTEM.** The SYSTEM daemon runs any `script` written into the user-writable `uac_command.json`, so any user process (including a prompt-injected agent tool) gets SYSTEM with no UAC prompt. | Allowlist of script paths inside the repo, resolved and compared after `realpath`. Move the command file to a directory the user can't write, or sign requests with an HMAC key readable only by SYSTEM. | Test: a script outside the allowlist is refused, and a symlink or `..` escape is refused. |
| 0.2 | `uac_worker.py:91` + `uac_run.py:116` | The heartbeat stops while a job runs, so any job longer than 20 s is reported as "daemon died" (rc=3) and its result is thrown away. | Send heartbeats from a thread, or poll `Popen` in a loop that beats. | Test: a 30 s dummy job returns rc=0 with its output. |
| 0.3 | `client/mcp/local_servers/cli_mcp_server.py:18-90` | The allowlist is dead code: `_is_cli_command_allowed` returns True, and commands run with `shell=True` on LLM-chosen strings. | Enforce `ALLOWED_CLI_COMMANDS` with `shlex` parsing and no shell, and deny by default. | Test: `powershell iwr ... \| iex` is refused, and an allowed command runs. |
| 0.4 | `automator/ui_control/cua_skills.py:159` | PowerShell injection through `Set-Clipboard -Value '{text}'`. An apostrophe also breaks the paste silently. | Pass the text via stdin or a `-EncodedCommand` argument, or use win32clipboard directly. | Test: text containing `'; Remove-Item ...` is set literally. |
| 0.5 | `security/vault_manager.py:69,196` | `_scrub_string` memsets at a fixed CPython offset, which corrupts memory for non-ASCII or one-character strings and overwrites the caller's variable. | Delete it. Hold secrets in a `bytearray` and zero that, or accept that Python `str` values cannot be scrubbed. | Test: storing a non-ASCII password neither crashes nor mutates the caller's string. |
| 0.6 | `gx10_runner/agent_runner.py:80,1064` | Owner claim is first-come (`OWNER_CHAT_ID="auto"`), and group chats can claim it. | Require an explicit owner id, or a one-time pairing code printed on the box, and reject non-private chats. | Test: the first message from a stranger or a group is refused. |
| 0.7 | Rule 1: `telegram_gui.py:1332/420`, `botfather_step.py:100`, `verify_human_mouse.py:27`, `fleet/system_guardian.py:225`, `hardware_mcp_server.py`, `cua_skills.py`, `vault_manager.py:139` | Input goes out before or without the countdown. `_ensure_foreground` taps Alt before the gate, `click_input` bypasses it, a cancelled countdown is ignored, and whole packages have no gate. | Make input go through **one** gate module (the `HumanMouse`/`_type_keys_safe` gate, extracted from the Telegram package). Nothing calls `keybd_event`, `SendInput`, `pyautogui` or `click_input` except through it. | A grep test that fails if any of those calls appears outside the gate module, plus tests that cancel leaves the cursor untouched. |
| 0.8 | `telegram_gui.py:538` / `telegram_human_mouse.py:105` | Cancelling **after** the countdown doesn't stop the mouse, because `_first_move_done` stays True and the next call re-acquires on top of the old lockout. | On cancel: reset the mouse gate, release the lockout, and make every later input raise until re-armed. | Test: cancel mid-run means the next click raises and sends no input. |
| 0.9 | `telegram_gui.py:1325-1339` | The armed warning overlay swallows clicks (no click-through burst on `_warning_lockout`). | Apply the same begin/end click-burst to whichever lockout is active. | Test with a stub lockout: the burst is opened around the click. |
| 0.10 | Rule 5: `botfather_step.py:83-87` | Every step saves a full screenshot, which includes BotFather's token after `/newbot`. | Skip `snap()` after the token step, or blur the token region before saving; `troubleshoot_screenshot` must do the same. | Test: after a simulated token message, no PNG is written. |
| 0.11 | Rule 4: `ufo_bridge.py:334-362,527-633`, `astro_collect.py:230,361` | Chat OCR text and raw screenshots leave the machine (job results, `vision_scan`, `vision_ask`). | Route everything through `PrivacyRedactor` and send only the target region, never the whole chat pane. | Test: a fixture chat screenshot is redacted before it leaves `ufo_bridge`. |
| 0.12 | `galaxy/webui/server.py:60` | The WebUI API key is logged. | Log only a fingerprint. | Test with `caplog`. |
| 0.13 | Repo hygiene (**partly done**) | `.gitignore`'s `models/` hid `galaxy/webui/models` (committed in `77a6a07`). 65 other source files are untracked or ignored, mostly root scripts and `scripts/`, so they have no history and no backup. | Decide per file: commit, move to `scripts/_archive` and commit, or delete. Add a CI check that fails when a `.py` file imported by tracked code isn't tracked. | `git ls-files --others --ignored '*.py'` matches an explicit allowlist. |
| 0.14 | Tooling (**incident**) | `ufo_skill_state/fix_all.py` stripped "unused" imports inside venvs and got dotted imports wrong. uv hard-links venvs to its cache, so the damage spread. | Delete the script, or stop it running. Use **ruff** (`ruff check --select F401 --fix`) scoped to tracked files for import cleanup. Set `UV_LINK_MODE=copy` for these venvs. | `verify_record.py` reports 0 mismatches as a health check in the watchdog. |

## Phase 1: regressions introduced by recent commits

| # | Where | Problem | Verify |
|---|---|---|---|
| 1.1 | `controller.py:117` (f6f1b20) | `atomic_execution` now raises instead of returning `'An error occurred'`. Every caller that branches on that string is dead: the vision fallback in `click_input`, the pyautogui fallback in `keyboard_input`, and `ControlCommand.execute`. | Test: `ElementNotEnabled` on click reaches the vision fallback. |
| 1.2 | `playwright_adapter.py:191` (f6f1b20) | `close()` calls `.stop()` on the context manager, which has no such method, so the driver process leaks. | Test with a stub: `close()` calls `Playwright.stop()` once. |
| 1.3 | `telegram_gui.py:591` (5876f2f) | The elevated-fixer path resolves to a file that doesn't exist, and it still uses `-Verb RunAs` (Rule 7). | Route through `uac_run.py`; test the path resolves. |
| 1.4 | `telegram_gui.py:1492-1500` (5876f2f) | `search_chats` builds `ChatItem` with fields it doesn't have, so it always returns `[]`. | Test with a fake UIA list. |

## Phase 2: Telegram runner correctness

| # | Where | Problem |
|---|---|---|
| 2.1 | `ufo_bridge.py:297-320` | `collect_horoscope` runs the collector in session 0 (it can't see the desktop) and accepts stale PNGs from earlier days. It should check file times and fail loudly. |
| 2.2 | `telegram_goals.py:204` | Resume re-sends up to 9 messages, because progress is only checkpointed every 10. Persist after every send. |
| 2.3 | `telegram_goals.py:234` | A cancel during rate-limit sleep is recorded as "completed". |
| 2.4 | `telegram_receiver.py:240-252` | `TypeTextCommand` types free text as key syntax, uses Ctrl+F search (Rule 5) and always reports success. Use `_type_text_safe` and `_open_chat_by_keyboard`. |
| 2.5 | `telegram_receiver.py:328` | Multi-line send ignores `chat_name`, so the text goes to the wrong chat. |
| 2.6 | `telegram_gui.py:864`, `:1576` | The typing fallback ignores `literal`, and multi-line send ignores Enter results. |
| 2.7 | `telegram_verifier.py:122/395` | `changed` is always True, so a frozen UI after a send is never detected. |
| 2.8 | `botfather_step.py:52-78` | Clipboard ctypes calls have no `restype`, which truncates 64-bit pointers. |
| 2.9 | `ufo_bridge.py:459/483` | `vision_locate` with click plus a supplied screenshot crashes (`c=None`). |
| 2.10 | `telegram_lockout.py:128` | `async acquire` blocks the event loop with `time.sleep` for 8–13 s. |
| 2.11 | `telegram_human_mouse.py:355` | Multi-monitor: coordinates are normalised to the primary monitor only (no `MOUSEEVENTF_VIRTUALDESK`). |
| 2.12 | `telegram_lockout.py` | A second ScreenLockout can't register the cancel hotkeys while the warning lockout holds them. One lockout owner per process. |

## Phase 3: structure and maintainability

Current metrics: 717 tracked `.py` files, 124k lines. Only one undefined name (harmless). 910 pyflakes issues: 574 unused imports, 212 f-strings without placeholders, 124 unused variables.

1. **Split the complexity hotspots.** 46 functions have cyclomatic complexity of 21 or more. The worst:
   - `llm_call.get_completions` (66)
   - `browseract_navigation._execute_locked` (52)
   - `astro_step.main` (45)
   - `GalaxyTrajectory.to_markdown` (43)
   - `ContinueConstellationAgentState.handle` (39)
   - `AppLLMInteractionStrategy.execute` (33)
   - `set_edit_text` (30)

   Start with `get_completions`, which is on every LLM call: extract the retry, fallback, refusal-rotation and cost-accounting stages. Characterisation tests go first.
2. **Lowest-maintainability files** (radon rank C): `app_agent_processing_strategy.py`, `telegram_gui.py` (1,432 lines), `screenshot.py`, `agent_runner.py`, `browseract_navigation.py`, `browseract_mcp_server.py`, `task_constellation.py`. Split `telegram_gui.py` into window/focus, typing/gate, chat navigation and screenshots.
3. **One endpoints module.** The Venus and OmniParser defaults are repeated in 5–10 files. There are 70 hard-coded `C:\Users\lnxzf` paths in 39 files, and the tailnet IPs appear in 13 files. Add `ufo/endpoints.py` (env → config → default) and replace the literals. This must be done with **ruff and tests**, not a regex script (that is how the incident happened).
4. **51 loose scripts in the repo root.** Move them to `tools/` (kept) or `scripts/_archive` (history). Keep the root for entry points.
5. **Config sprawl.** There are seven `agents*.yaml` profiles plus `profiles/`. Consolidate into one schema-validated file with named profiles, and `switch_backend.py` selects between them.
6. **Lint.** `ruff check --fix` on tracked files only, one rule family per commit (F401, F541, F841), with tests run after each.

## Phase 4: tests and operations

1. **Test suite.** See "Test results" below. Fix or quarantine the hanging observer test: it blocks the whole run under `--timeout`. Mark live tests (Venus, OmniParser, DGX) with a `live` marker so the default run is hermetic. The eval-suite unit tests launch Notepad, Chrome and BankFidelity; gate them behind a marker (see the no-popups memory).
2. **CI gate.** On every commit run:
   - compile all `.py` files, **including untracked ones**;
   - `scan_staged.py` (the pre-commit hook already exists);
   - the unit suite;
   - `test_powershell_script_hygiene.py`;
   - a Rule 1 grep test (item 0.7).
3. **`ufo_watchdog.sh:186-217`.** The `.venus_rebuild_running` sentinel needs an age or PID check, or one killed rebuild disables repair forever.
4. **`fleet/distributed_lock.release_all`** also needs to release plain local locks (`lifecycle.py:259`).
5. **OmniParser freeze.** The root cause is still unknown (the watchdog now heals it). Capture a `py-spy dump` automatically before the watchdog restarts it.
6. **Operator steps (need you):** push `main`; exclude `Desktop\projects\ufo` from Windows Search; rotate the leaked OpenRouter and Qwen keys (see `KEY_ROTATION.md`); give the `ufo_helper_bot` token.

## Working agreement (to stop repeating today's incidents)
- **One agent per area.** Two sessions editing the same files produced most of this week's regressions.
- **No hand-rolled mass rewriters.** Use ruff, and scope it to `git ls-files`, never to a directory walk.
- **Every fix ships with a test that fails on the old code.** Reviewing our own commits found real regressions twice (8417eb5 → d25a309, and f6f1b20 → items 1.1 and 1.2).

## Test results (27 Sep, on the restored venv)

- **The full suite never completes.** `tests/unit/galaxy/session/test_observers_refactored.py` hangs: two of its tests exceed the 90 s timeout, and pytest-timeout then kills the whole run.
  - Two attempts stopped at 67%.
  - A third run excluding that file was cut short because the `.venv` was deleted by another agent mid-run (01:56).
  - **The last third of the suite is therefore unmeasured.**
- **Galaxy, constellation, orchestrator and DAG tests** (73 files, excluding the hanging file): **500 passed, 1 failed, 6 skipped**.
  - The 1 failure is `test_modular_observers::test_progress_observer_task_event_handling`, which already failed before this week's changes.
- **Fixed during this review:**
  - 4 `test_device_manager_assign_task` failures. The cause was 5876f2f: `ExecutionResult.is_successful` read `.value` on string statuses.
  - `test_real_time_dag_updates`. It had encoded the old bug (completing a SUCCESS_ONLY dependent of a failed task). Fixing that exposed a **hang**: a dependent blocked by a failed prerequisite never became terminal, so `while not constellation.is_complete()` could never exit. Such dependents are now cancelled transitively (`TaskConstellation._propagate_outcome`), and COMPLETION_ONLY dependents still run.
- **Need gx10 or live services** (not run on the default path): `test_venus_grounding_live` (2), `test_omniparser_hybrid_live`, `test_dgx_model_audit`. Mark these `live` (Phase 4.1).
