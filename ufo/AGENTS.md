# GLOBAL AUTOMATION RULES - UFO + Telegram Agent (MANDATORY)

These are **project-level, global rules**. Every agent, script, test, and
manual invocation MUST follow them. They are enforced in code where possible
(`telegram_gui.py` warning gate), and are the contract for every change.

## RULE 1 - ALWAYS SHOW THE COUNTDOWN MESSAGE BEFORE ANY CONTROL

**Before EVER taking over any part of the mouse or keyboard**, the
near-opaque on-top message MUST be shown with a **5-second countdown**.

- Trigger point: literally any input injection - mouse move, click, drag,
  scroll, keyboard send - including tests, diagnostics, and dry runs.
- Enforced by `TelegramGUIController._ensure_automation_warning()` and the
  `HumanMouse.first_move_hook` - a `HumanMouse` or `_type_keys_safe` call
  without the gate armed REFUSES to act.
- Cancel key: **Ctrl+Shift+Q** (verified), ESC silent backup. Pause: P.
- The gate card is near-opaque (alpha 0.9) on top of everything.

## RULE 2 - FORCE TELEGRAM ON TOP BEFORE AUTOMATION

Before any automation session, Telegram Desktop MUST be the foreground,
visible, not minimized, and at a sane size/position.

- `force_telegram_top()` in `telegram_gui.py`:
  1. restore if minimized, bring to top, SetForegroundWindow
  2. if UIPI-blocked (Telegram elevated), run the **elevated fixer**
     (`elev_fix_window.py` via `Start-Process -Verb RunAs`) - the operator
     approves UAC; then re-verify
  3. verify: visible + not minimized + foreground (allow the elevated path)
- Automation should run **elevated** when Telegram is elevated (the
  `run-as-admin` wrapper), so it can manage foreground itself.

## RULE 3 - VISUAL TROUBLESHOOTING WHEN STUCK

**Anytime the automation gets stuck, or a result is unexpected, capture a
screenshot and inspect it before retrying.**

- Helper: `TelegramGUIController.troubleshoot_screenshot(label)` ->
  saves `ufo_skill_state/evidence/debug/<label>_<ts>.png`, returns path.
- Automatic capture points (already wired): connection failures, sidebar
  empty (search overlay left open), open_chat click verification failures,
  post_send verification issues, lockout acquire failures.
- Never blind-retry more than twice without a screenshot. The screenshot IS
  the ground truth (e.g., "search overlay open hiding the sidebar", "window
  collapsed to 394x512", "wrong account logged in").

## RULE 4 - PRIVACY (content never read, errors excepted)

- No message content is ever read/stored/learned unless it contains an
  error/failure keyword - `PrivacyRedactor` is the single gate.
- Conversation learning is pattern-only (shapes, transitions, error
  keywords, delays). Verified: zero content in saved skills.

## RULE 5 - BOTFATHER FLOW CONTRACT

- Any bot-creation flow through BotFather: 5s countdown gate shown
  (Rule 1), Telegram on top (Rule 2), screenshot after each prompt
  (Rule 3), API token NEVER logged or stored - redacted immediately.
- **BotFather must be found via the SIDEBAR GLOBAL SEARCH field** (top-left
  `Ui::InputField` name="Search"), NEVER via Ctrl+F (that is message search
  scoped to the current chat and will falsely return "No Results").

## RULE 6 - NEVER GIVE UP (MANDATORY, ABSOLUTE)

**FORCIBLY COMMANDED: NEVER EVER GIVE UP. NO CAP. NO LIMIT. NO MATTER WHAT.**

- Infinite max steps, infinite effort, infinite budget, infinite reasoning.
- Before ever claiming something is impossible, you must have tried:
  1. Every reasonable method, each in **more than one way**
  2. Restarting the Telegram application (fully quit + relaunch)
  3. Troubleshooting network connections (connectivity checks, DNS,
     proxy/VPN state, time sync)
  4. Deep research (web search, docs, community solutions, SDK/API docs)
  5. Escalation routes (elevated execution, alternate accounts, alternate
     entry points)
- You MAY ask the human for help ONLY after trying everything above AND
  genuinely needing human-only input (e.g., a phone number, a login code).
- **The 15-SECOND RULE:** after asking, if there is no reply within
  **15 seconds**, assume the human is not at the computer and immediately
  resume autonomous work - keep thinking harder, keep researching, keep
  trying - even if it takes millions of hours.
- Giving up, stopping, or declaring "impossible" without exhausting all of
  the above is a RULE VIOLATION.

## RULE 7 - PERMANENT HIDDEN ELEVATION (NO MORE UAC PROMPTS)

The `UFO_ELEVATED` scheduled task is the **permanent, hidden UAC solution**:

- Registered once as **SYSTEM / HIGHEST** with **at-logon** trigger, running
  `pythonw.exe uac_worker.py` (invisible, no console).
- The daemon loops on `uac_command.json`; any elevated script runs via:
  `python uac_run.py <script.py> [args...]` - silent, no UAC, no console.
- Client polls `uac_result.json`; the daemon writes `uac_worker_alive.json`
  as a heartbeat.
- Never use `Start-Process -Verb RunAs` for step-by-step work again -
  everything elevated goes through the daemon. Only re-registering
  (`setup_uac.py` elevated, once) could ever prompt again.
- The daemon auto-restarts at every logon (permanent).
- **MUST be a Scheduled Task. NEVER a `HKLM\...\Run` registry value.** A Run
  value executes *as the logged-on user at that user's normal integrity* and
  therefore cannot elevate. `setup_uac.py` v4 shipped a Run-key install on the
  belief that "Task Scheduler ignores our tasks in this environment"; that
  belief is false (the `UFO litellm` and `UFO gx10 tunnel` tasks both run
  fine), and the result was a daemon reporting `is_user_an_admin: false` -
  every "elevated" script ran unelevated while appearing to succeed. Installed
  by `scripts/uac_install.ps1` (SYSTEM / ServiceAccount / Highest, at-logon,
  conhost --headless + pythonw).
- **Liveness is heartbeat FRESHNESS, never file existence.**
  `uac_worker_alive.json` is rewritten every ~5s and outlives the process that
  wrote it, so `os.path.exists()` reports a long-dead daemon as alive and
  `uac_run.py` then waits out its full timeout on a command nobody will run.
  Treat >20s old as dead.
- `uac_run.py` sends **absolute** script paths: the daemon runs as SYSTEM with
  its working directory at `%SystemRoot%\system32`.
- Verify elevation, don't assume it:
  `python uac_run.py _verify_elevation.py` must report `SYSTEM` / `LENOVO$`.
  `HIGH` means the daemon regressed to a user-level process.
- Note: `.venv\Scripts\pythonw.exe` is a launcher shim that spawns the base
  interpreter as a child, so one daemon shows up as TWO pythonw.exe processes
  (child's ParentProcessId == shim's PID). That is normal, not a duplicate.

---
*Created 2026-09-23. These rules supersede convenience overrides.*
