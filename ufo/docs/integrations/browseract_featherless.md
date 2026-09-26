# BrowserAct + Featherless browser navigation

UFO now has a dedicated browser navigation path that combines:

- **BrowserAct Agent CLI** — a real, isolated Chromium browser with compact
  indexed state (`state -> click 3 / input 2`).
- **Featherless OpenAI-compatible chat completions** — the LLM used by the
  selected UFO Host/App profile.
- **FastMCP** — the same tool registry and result path used by the rest of
  UFO, so no new command dispatcher is required.

The main UFO action protocol is intentionally used here. FastMCP renders the
`browser_action` schema into the agent prompt, the model emits the usual UFO
JSON action, and `CommandRouter` invokes the BrowserAct executor. This avoids
mixing BrowserAct's ephemeral element indexes with native Chrome/UIA control
IDs.

## 1. Install the BrowserAct CLI

BrowserAct is a separate Python 3.12 tool. Do not add it to UFO's main Python
environment: its current package has a FastAPI dependency that conflicts with
UFO's pinned FastMCP stack.

```powershell
uv tool install 'browser-act-cli==1.4.2' --python 3.12
browser-act --version
```

If `browser-act` is not on `PATH`, set an absolute executable path:

```powershell
$env:BROWSERACT_CLI_PATH = "$env:USERPROFILE\.local\bin\browser-act.exe"
```

A BrowserAct browser identity is separate from the BrowserAct CLI. List the
identities and choose one explicitly, or set `BROWSERACT_BROWSER_ID`:

```powershell
browser-act browser list
```

The UFO wrapper does not create, delete, import, or reconfigure browsers. Those
are sensitive lifecycle operations and remain an explicit BrowserAct/operator
workflow. On first real CLI use, the constrained wrapper performs
BrowserAct's fixed `get-skills main`/`get-skills core` compatibility handshake;
it does not expose the skill or command surface to the model. If a pinned CLI
requires an explicit skill version, set `BROWSERACT_SKILL_VERSION`.

## 2. Configure secrets locally

Use a local environment file or secret manager. Never put keys in YAML, MCP
arguments, prompts, logs, or command lines:

```text
FEATHERLESS_API_KEY=<your-featherless-key>
BROWSERACT_CLI_PATH=<optional-absolute-browser-act-executable>
BROWSERACT_BROWSER_ID=<optional-configured-browser-id>
# Only needed for BrowserAct-hosted stealth/remote features.
BROWSERACT_API_KEY=<your-browseract-key>
```

`ufo.env` is ignored by the repository. A checked-in `.env.example` is provided
for documentation only. If a key has been pasted into a chat, terminal
transcript, or log, revoke it and create a replacement before using the route.

## 3. Select the Featherless profile

The dedicated profile is non-visual because BrowserAct supplies page state as
text and does not need the desktop screenshot/UIA stream:

```powershell
python scripts/switch_backend.py featherless
python scripts/switch_backend.py status
```

The profile is stored as an explicit backend selection in
`config/ufo/backend_state.json`; it does not silently replace the existing DGX
route. Switch back with:

```powershell
python scripts/switch_backend.py dgx
```

The profile uses:

```yaml
API_TYPE: openai
API_BASE: https://api.featherless.ai/v1
API_MODEL: DavidAU/Qwen3.5-27B-Claude-4.6-OS-INSTRUCT
JSON_SCHEMA: false
USE_RESPONSES: false
```

`API_TYPE` remains `openai` because Featherless is OpenAI-compatible and UFO's
existing provider adapter already handles custom base URLs. The checked-in
profile uses `DavidAU/Qwen3.5-27B-Claude-4.6-OS-INSTRUCT` for Host planning,
`Qwen/Qwen3.8-Flash-Next` for App/native tool calls, and
`DavidAU/Qwen3.5-9B-Claude-4.6-OS-HERETIC-UNCENSORED-INSTRUCT` for backup and
evaluation. Set `UFO_HOST_AGENT__API_MODEL` / `UFO_APP_AGENT__API_MODEL` if a
different Featherless model is preferred; the selected model must support the
required chat-completions format and native tool calling where applicable.

## 4. Agent loop

The MCP executor exposes one constrained `browser_action` tool. The safe loop
is:

```text
open -> state -> one mutation -> fresh state -> ... -> close
```

Example arguments for the model:

```json
{
  "function": "browser_action",
  "arguments": {
    "action": "open",
    "url": "https://example.com",
    "browser_id": "<browser-id>"
  }
}
```

Then call `state`, use the returned `session` and `state_token`, and perform
one mutation such as:

```json
{
  "function": "browser_action",
  "arguments": {
    "action": "click",
    "session": "ufo-ba-...",
    "state_token": "fresh-token",
    "index": 3
  }
}
```

The result includes a new token and fresh indexed state. Old indexes are
invalid after navigation or DOM changes. UFO's App Agent also limits a single
response to one BrowserAct mutation; ordinary UIA multi-action behavior is
unchanged.

## Optional gx10 native-tool runner

The standalone DGX Telegram runner has a separate native OpenAI-compatible
loop. It uses the same provider aliases and BrowserAct state contract, but it
is not part of the Windows UFO/FastMCP process:

```text
LLM_BASE_URL=https://api.featherless.ai/v1
LLM_MODEL=Qwen/Qwen3.8-Flash-Next
FEATHERLESS_API_KEY=<your-featherless-key>
BROWSERACT_ENABLED=1
BROWSERACT_BROWSER_ID=<configured-browser-id>
INSTALL_BROWSERACT=1
```

Build or recreate the runner with `INSTALL_BROWSERACT=1` so the Python 3.12
`browser-act-cli` is included in `Dockerfile.agent`. The compose service passes
`LLM_*`, `FEATHERLESS_API_KEY`, and `BROWSERACT_*` variables from its `.env`;
the runner never prints those secrets. `BROWSERACT_CLI_PATH` can be used when
the executable is mounted or installed outside `/usr/local/bin`. The native
loop also permits at most one BrowserAct page mutation in each model response
and closes its owned session during shutdown.

The image does not install a local Chrome binary. Use a configured hosted
BrowserAct identity (normally `stealth`) or provide/mount a separately managed
Chrome installation and explicitly approve a local browser type; do not assume
`chrome`/`chrome-direct` works in the slim image.

The existing DGX vLLM route remains the default. To keep BrowserAct optional in
an image, leave `INSTALL_BROWSERACT=0` and `BROWSERACT_ENABLED=0`; set both to
`1` when the navigation arm is ready.

The wrapper intentionally does not expose:

- arbitrary shell commands or arbitrary BrowserAct argv;
- browser create/delete/update or profile import;
- proxy changes or CAPTCHA solving;
- cookies, network/HAR capture, or `eval`;
- retries after a mutation timeout (the page may have changed anyway).

For a high-risk deployment, set `BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST=1` and
provide `BROWSERACT_ALLOWED_DOMAINS`; this prevents an empty allowlist from
becoming an unrestricted model-controlled navigation target. URL checks cover
initial destinations and the native runner's optional web fetch also validates
redirects; network-level egress restrictions are still recommended.

`remote_assist` requires `confirm=true`; it returns a BrowserAct handoff URL
and puts that session into a lockdown state until the operator completes the
handoff. `stealth_extract` is disabled by default; when explicitly enabled it
is read-only and requires BrowserAct's own hosted capabilities/API key.

## Troubleshooting

1. `BrowserAct CLI is not available`: install the Python 3.12 tool and verify
   `browser-act --version` in the same user environment that starts UFO.
2. `No BrowserAct browser is configured`: run `browser-act browser list`, then
   set the operator-controlled `BROWSERACT_BROWSER_ID` (or leave it empty
   only when exactly one browser is configured).
3. `Stale or invalid state_token`: call `state` again; never reuse an index
   from an earlier observation.
4. `state` or mutation timeout: inspect the returned error and BrowserAct
   diagnostics. Do not blindly repeat a click/input.
5. `FEATHERLESS_API_KEY` missing or rejected: the Featherless backend refuses
   selection rather than starting with an unresolved key. A `403` from the
   model-discovery probe means the key is invalid/revoked or lacks access;
   rotate it and verify the account can use the selected model IDs.

## References

- [BrowserAct Agent CLI](https://docs.browseract.com/agent-cli/introduction)
- [BrowserAct command reference](https://docs.browseract.com/agent-cli/command-reference)
- [Featherless OpenAI compatibility](https://featherless.ai/docs/api-overview-and-common-options)
- [Featherless tool calling](https://featherless.ai/docs/tool-calling)
