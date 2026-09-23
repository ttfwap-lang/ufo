# UFO Agent Pipeline - Master Plan & Handoff Notes
*Created 2026-09-24. The single source of truth for the next session/model.*

## GOAL (user's words)
"Message @ufo_assistant_bot in plain language; it follows the instructions
agentically and intelligently using full AI reasoning." The horoscope request
is the FIRST example: *"get all of tomorrow general daily horoscopes for
tomorrow from @AstrologyScienceBot and message them all back here."*
Data must be fetched by **messaging the bot** via the **ufo/venus desktop
automation** (NOT a web API).

## ARCHITECTURE (approved)
```
User plain language -> @ufo_assistant_bot (DGX runner, Docker, 24/7)
   -> Qwen3.6-35B-A3B-abliterated (local vLLM @ gx10:8000, tool-calling VERIFIED)
   -> agent loop emits tool_calls; executor runs tools; observations looped
   -> final answer back in chat
TOOLS:
  shell      - allowlisted read-only Linux cmds on DGX (existing ALLOWLIST)
  telegram   - send/reply in the bot chat (multi-turn)
  ufo_bridge - Windows ufo/venus: "do X in Telegram Desktop" (horoscope = X)
  web        - urllib/curl fetch
```
Bridge: `ufo_bridge.py` = tiny tailnet HTTP server on Windows (port 9301,
auth token, single worker queue) wrapping the EXISTING automator agent stack.
Two endpoints: `POST /jobs {job_id, goal, app, params}` and `GET /result/{id}`.

## INFRASTRUCTURE - VERIFIED STATE

### Windows (ufo/venus) - automator/app_apis/telegram/
- `telegram_gui.py` TelegramGUIController: connect, force-top (elevated path),
  screenshots, UIA physical-rect clicks, gated typing, focus input, troubleshoot shots
- `telegram_human_mouse.py` humanized mouse - VERIFIED (peak <=8,835px/s, submovements, overshoot)
- `telegram_lockout.py` lockout gate NOW: 8s countdown, cancel = ScrollLock(0x91)/
  F12(0x7B)/ESC, pause = P; burst suppression; foreign-id immunity
  (verified 6/6 for OLD Ctrl+Shift+Q; NEW single-key harness = verify_hotkeys.py, NOT YET RUN)
- `telegram_privacy.py` PrivacyRedactor - 8,169-msg test, ZERO content leaks
- `telegram_skill.py` / `telegram_agent.py` / `telegram_goals.py` / `telegram_memory.py` /
  `telegram_receiver.py` / `telegram_verifier.py` / `telegram_commands.py` - goal agent stack
- `botfather_step.py` - BotFather automation (token recovered via UIA-exact text)
- `astro_step.py` - generalized bot-step tool. Commands (all elevated via uac_run):
  deeplink <domain> | webapp <domain> (https t.me/<d>/app) | reply <text> |
  buttons | clickbtn <text> | grep <needle> | keys <seq> | clickpx <x> <y> |
  paste | shot | windows | topwin (native EnumWindows: pid/class/title/rect -
  THE active-chat verifier) | chats | tree | focusinput | typecmd |
  openchat <name> | searchchat <username> (Rule-5 sidebar search, RELIABLE).
  Screenshots -> astro_state.png. OCR companion: `ocr_shot.ps1 <png>` (WinRT,
  full-screen text; BoundingRects currently 0 - see RECON).
- Elevation: `uac_worker.py` (SYSTEM pythonw daemon, registry Run autostart,
  single-executor via Global\UFO_EXEC_LOCK mutex), `uac_run.py <script> [args]`
  client, `fix_workers.py` + `restart_worker.py` (self-heal). HEARTBEAT
  `uac_worker_alive.json` (SYSTEM). Daemon can't read/write USER clipboard ->
  Set-Clipboard/Get-Clipboard locally around daemon runs.

### DGX (gx10.local, via `ssh -i ~/.ssh/id_ed25519_ufo_agent flak3dd@gx10.local`)
- `gx10_runner/`: Dockerfile, docker-compose.yml, telegram_runner.py - DEPLOYED.
  Container `ufo-tg-runner` UP, RestartCount=0, log "runner up: @ufo_assistant_bot".
  Token in `~/ufo-tg-runner-bootstrap/.env` (BOT_TOKEN + OWNER_CHAT_ID=auto;
  owner claims on first message).
- vLLM `qwen-abliterated` (network=host, port 8000): model id `qwen-abliterated`
  = Qwen3.6-35B-A3B-abliterated-NVFP4-MTP, max_model_len 32768.
  TOOL-CALLING VERIFIED via /v1/chat/completions (finish_reason=tool_calls, correct args).
- `ui-venus` container serves UI-Venus-2-9B (vision/UI model - user may pair for visual steps).
- `abliterated-proxy` = caddy.

## RECON: @AstrologyScienceBot - LIVE (2026-09-24 ~02:10)
- Public site astrologyscience.online: "General Horoscopes - daily/weekly/monthly/
  yearly for all signs", 5 languages. No public API found.
- Bot = **Mini App bot**. Chat-native limits PROVEN:
  - /start -> "Welcome! signals from the stars!" + inline buttons **"Open"** and
    **"Gift a Star"** (inline buttons are NOT in the UIA tree - custom drawn).
  - Plain text is IGNORED: sent "General Horoscopes" (2:06 AM) -> NO reply.
  - Registered commands (info panel): Open App / Ask Astrologer / Personal
    Forecasts / General Horoscopes - NOT UIA-exposed, not chat-triggerable.
  - Bot **PUSHES** a daily horoscope image into the chat (evidence in chat:
    message at 1:01 AM = TEXT "General Horoscopes" + image card "Daily Horoscope
    for Aries for 24.09.2026" with Love/Health/Career/Lunar (x/5) scores +
    prose + "Click for details:" - read via OCR, not UIA). Only ONE sign/day
    (the user's selected sign = Aries). All-12-signs + explicit "tomorrow"
    selectors live in the MINI APP ONLY.
- "Open App" (info-panel Button, UIA-exposed) clickbtn -> True but NO webview
  window appeared (checked via topwin). Info-panel route does not launch it.
- Tab+Enter from the input falls to the CHAT LIST (opens a sidebar chat) -
  does NOT reach inline buttons.
- OCR (WinRT, ocr_shot.ps1) = working TEXT vision for the whole screen
  (horoscope images read perfectly) but BoundingRect is 0,0,0,0 for every
  line (no click coords). UIA rects remain the coordinate source.
- WINDOW quirks: geometry changes between runs (force_telegram_top resizes);
  window title = ACTIVE chat (verify via `topwin`); input Edit found LIVE via
  uia_find_rect("Edit","Write a message...") - always correct at click time.
- ELEVATED PITFALL: stray clicks hit the SIDEBAR (opened "Eli 2", a human
  chat, and typed drafts there). ALWAYS verify the active chat by title
  (topwin) before typing; always `^a{DEL}` any draft before typing.
- SIDEBAR SEARCH (Rule-5 path, VERIFIED): Edit("Search") rect (327,167,700,211)
  -> `searchchat <username>` opens the bot reliably (title-verifiable).
- **NEXT:** (a) computed click on the inline "Open" button (bubble directly
  above the input; keyboard row y ~ input_top-35..-60, "Open" = left button),
  (b) fix WinRT OCR to yield real BoundingRects (gives coordinate "vision"),
  (c) fallback: open the bot's t.me Mini App page in Chrome and screenshot-led
  drive (same app UI), (d) midnight push capture as last resort.

## PHASES & STATUS
- [x] P0 root infra (elevation, gates, human mouse, privacy, hotkeys new-set harness written)
- [x] P1b vLLM tool-calling verified on gx10
- [~] P1a bot recon (Mini App confirmed as the only data path; chat push = 1 sign/day;
      remaining: open the webview OR fix OCR coords)
- [ ] P2 ufo_bridge.py (Windows job server)
- [ ] P3 runner agent loop upgrade (tool schema, qwen client, bounded turns, per-chat history)
- [ ] P4 E2E: horoscope request -> 12 horoscopes; then a 2nd unrelated request to prove
      generality (e.g. BTC price summary)
- [ ] P5 harden: auth both ways, timeouts, no content learned, allowlist intact

## OPEN LOOSE ENDS (hygiene)
- Restore/verify active chat = @AstrologyScienceBot before handing back (last action
  left it open; window may have drifted).
- CLEAN stray drafts typed into OTHER chats during tonight's focus chaos:
  "Eli 2" (a human) may carry drafts ("e"/"/ge" leftovers) - open it, focus input,
  keys "^a{DEL}", verify, then return. Check "KK_shop2#" untouched (business chat).

## KEY COMMANDS
```
Windows elevated:  .venv\Scripts\python.exe -X utf8 uac_run.py <script> [args]
Pre-set clipboard: Set-Clipboard -Value "<text>"  (daemon cannot own clipboard)
DGX:   ssh -i "$env:USERPROFILE\.ssh\id_ed25519_ufo_agent" flak3dd@gx10.local "..."
Runner logs:  docker logs --tail 30 ufo-tg-runner
```

## HARD RULES (AGENTS.md 1-7, unchanged)
8s gate before ANY input; cancel ScrollLock/F12/ESC/P; Telegram forced on top;
screenshot-verify when stuck; PrivacyRedactor is the only content gate; token
never logged/stored/echoed; never give up.