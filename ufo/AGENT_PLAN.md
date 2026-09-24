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

## VISION STACK (2026-09-24, added after the horoscope flow was solved)

### What runs where
| Component | Where | Role |
|---|---|---|
| `qwen-abliterated` (Qwen3.6-35B-A3B) | gx10 :8000 | reasoning + tool calling |
| `ui-venus` (UI-Venus-2-9B) | gx10 :8002 | **UI grounding** (point localisation) |
| OmniParser V2 (YOLO + Florence-2) | gx10 :7861 | **icon detection + captioning**, whole-screen parse |
| WinRT OCR (`ocr_shot.ps1`) | Windows | exact text boxes (pixel-accurate) |
| `ufo_bridge.py` | Windows :9301 | HTTP job API, owns the desktop |
| `agent_runner.py` | gx10 container | Bot API loop, tool calling |

All gx10 services bind `0.0.0.0` so the Windows host can reach them over the
tailnet (Windows is `100.113.176.84`, gx10 is `100.67.13.78` - the
`100.81.31.74` in older notes is not this machine).

### UI-Venus coordinate convention (measured, not guessed)
Venus returns **both axes normalised to 0-1000** relative to the image's own
width and height:

    x_px = x_venus / 1000 * image_width
    y_px = y_venus / 1000 * image_height

Getting this wrong looks like "the model is terrible" (median error 253px).
Corrected, the same model is ~2px. **Always read the size from the file; never
hardcode it** - an early version hardcoded 1438 for a 938px capture and
reported a fake 1.53x error.

### Measured accuracy (bench_venus_final.py, real Telegram captures)
| Benchmark | Ground truth | <=25px | median |
|---|---|---|---|
| text labels, raw Venus | OCR phrase box | 8/12 (67%) | 9.8px |
| text labels, fused | OCR phrase box | **12/12 (100%)** | 0.0px |
| **icon buttons, Venus only** | UIA rect | **4/5 (80%)** | **1.7px** |
| cross-validation Venus vs OmniParser | - | 0.3px agreement on the info-panel icon | |

The icon row is the important one: those controls have **no text**, so OCR
cannot see them at all - that capability is why the vision model is in the loop.

### Locator policy (`venus_client.locate`, prefer="auto")
1. OCR finds the label -> use the OCR phrase box (pixel-exact). Multiple
   matches? Venus picks which instance.
2. OCR finds nothing (icon-only, or the caller described the target) -> use the
   Venus point.
3. `engine="multi"` additionally asks OmniParser and reports `agreement_px` /
   `cross_validated` - two independently trained models agreeing is the
   strongest confidence signal available.

Strict label matching is deliberate: a false match is far worse than a miss,
because a miss defers to the vision model while a false match clicks the wrong
control (this bit us - a loose matcher let the description "the back arrow
navigation button" snap onto the OCR word "e").

### Safety
- Vision clicks are **refused** if the point lands in the window chrome
  (`_point_is_safe`). Before this guard existed, a mis-grounded click hit the
  window CLOSE button and killed Telegram. The E2E test asserts the guard
  fires.
- All input still goes through the gated controller (8s countdown, Rule 1/2).

### Memory rebalance (the GB10 has 121.7 GB unified, all of it contested)
Qwen 0.68 reserved ~65 GB of KV cache it could never use while Venus was
starved and OmniParser could not allocate at all (CUDA OOM, only 1 GB free):

| Pool | Before | After |
|---|---|---|
| Qwen | 0.68, `--max-num-seqs 1` | 0.56, `--max-num-seqs 8` |
| Venus | 0.19, localhost-only, 2 seqs | 0.26, `0.0.0.0`, 8 seqs, 16k |
| OmniParser | could not start | CUDA, REST API + UI, one model copy |

`rebalance_models.sh` performs it. Qwen's binding constraint was concurrency,
not memory.

### OmniParser REST API
`POST /api/parse {"image_b64": ...}` -> every element with
`bbox_xywh` + `bbox_xyxy` + `cx/cy` + a caption (150 elements on a Telegram
window in ~7s). The library emits **xywh**; returning it as xyxy silently
moves every point, so both forms are exposed with explicit names.

## KNOWN BLOCKER: Mini App consent sheet
Telegram now shows a modal before the first Mini App launch:

> "By launching this mini app, you agree to the Terms of Service for Mini
> Apps."

It replaces the whole layout, so every coordinate target is wrong while it is
up - which looks exactly like "the click silently does nothing". The collector
**detects** it (`detect_miniapp_consent`) and aborts with a precise message.
It will not click the accept button unless run with `--accept-miniapp-tos`,
because accepting a Terms of Service on the user's account is the user's
decision, not an automation default.

## RECON: @AstrologyScienceBot - SOLVED FLOW (2026-09-24 ~05:00)
### The working recipe (no visual model, no web API)
1. Open the bot chat (`tg://resolve?domain=AstrologyScienceBot`) and verify the
   ACTIVE CHAT via the window title (`topwin`).
2. Click the **info-panel command link "General Horoscopes"** (bitmap 1085,955).
   This opens the **Mini App webview in-pane** (NOT a separate window, NOT a
   WebView2 child - no CDP/debug port exists for it).
3. Main menu: "Your zodiac sign: X" + **"Change Sign"** (bitmap 940,607).
4. Sign grid (4 rows x 3 cols, bitmap centres):
   Aries(803,464) Taurus(948,464) Gemini(1092,464) / Cancer(806,512) Leo(949,512)
   Virgo(1092,513) / Libra(805,558) Scorpio(949,560) Sagittarius(1091,560) /
   Capricorn(805,607) Aquarius(948,607) Pisces(1092,605)
5. **"For Tomorrow"** (bitmap 954,371) -> the bot **posts that sign's horoscope
   card into the chat** ("Daily Horoscope <Sign> 24.09.2026" + prose + Love/
   Health/Career/Lunar (x/5) + "Click for details:"). App view closes after.
6. OCR the card. Repeat for all 12 signs.
   -> `astro_collect.py [signs...]` automates this; evidence in
   `astro_horoscope_<sign>.png`.
### Caveats
- The card header shows the GENERATION date (24.09.2026) even for the
  "For Tomorrow" option - bot-side labelling quirk, not a wrong pick.
- "For the Week / Month / Year / Today (Channel)" are also in the menu.

### Coordinate model (what made clicks work)
- **OCR word rects are real** (`OcrWord.BoundingRect`); only LINE rects are
  (0,0,0,0) - ocr_shot.ps1 now emits WORD-level rects. This is our "vision".
- Screen is **125% DPI**: the capture bitmap = logical window * 1.25.
  `physical = bitmap + physical_window_origin` (e.g. (63,50) for a window at
  logical (50,40)). `clickphys` takes PHYSICAL coords; `clickocr <text>`
  converts automatically.

### Windows/elevation lessons (cost hours - do not repeat)
- The automation stack runs as **LENOVO\\lnxzf, session 1, NOT elevated**.
  A Telegram launched ELEVATED (High) is UIPI-blocked: SetWindowPos -> "Access
  is denied", SW_RESTORE silently no-ops, all screen captures fail.
  **Rule: Telegram must run at NORMAL (medium) integrity.**
- Do NOT launch Telegram via `runas /trustlevel:0x20000` (Basic User): that
  trust level **kills the Qt accessibility bridge** (UIA tree empty:
  `buttons: 0`). Launch via the user's Explorer instead:
  `Start-Process explorer.exe "<Telegram.exe>"` -> medium integrity, full
  token, UIA works.
- Telegram keeps a **minimized ghost window** (rect -32000/-25600) plus a
  `Qt51519TrayIconMessageWindowClass` tray helper. `_find_telegram_window` now
  SCORES candidates (QWindowIcon +500, Tray -500, non-minimized +100, on-screen
  +30) and `take_screenshot` self-heals by restoring + clamping into the work
  area before one retry.
- `fit_tg_dpi.ps1` = window to logical (50,40,1200,840); `restart_tg_medium.ps1`
  = relaunch at medium integrity; `prep_screen.ps1` = minimize the IDEs that
  cover Telegram. Anything painted over Telegram poisons the screen-region
  capture - always `prep_screen` before evidence shots.

### Dead ends (do not retry)
- WebView2 CDP for the Mini App: Telegram renders the webview in-process, no
  msedgewebview2 child, the BrowserAdditionalBrowserArguments policy has no
  effect, nothing listens on 9222. Not needed - OCR + click works.
- Inline "Open"/"Gift a Star" buttons in the welcome message: not UIA-exposed,
  not reliably clickable. The INFO-PANEL command links are the entry point.
- Plain text ("General Horoscopes", "/start", ...) is ignored by the bot.
- The bot pushes only ONE sign/day (the selected sign) around 01:00.

## RECON (earlier findings, still true)
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