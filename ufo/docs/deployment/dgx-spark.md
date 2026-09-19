# DGX Spark Backend

> Confirmed-today facts about the DGX backend and how UFO connects to it, per the live audit referenced in `docs/plans/E2E_REMEDIATION_PLAN.md` (Phase 0, "DGX Reality Audit — Complete") and the actual contents of `config/ufo/agents_dgx.yaml` / `litellm_config.yaml` in this checkout. Anything not directly confirmed against those files is marked planned/unverified.

## What's actually running on the DGX (gx10)

Confirmed live, per the header comment in `config/ufo/agents_dgx.yaml`:

| Service | Port | Model | Notes |
|---------|------|-------|-------|
| Ollama | `11434` | `gemma4-ufo` | Vision-capable. `gemma4-ufo` is a derived tag of `gemma4:26b` with `num_ctx=8192` baked in server-side via a custom Modelfile (`ollama create gemma4-ufo -f Modelfile`) — required because Ollama's `/v1/chat/completions` endpoint errors on the base model ("Gemma4Assistant requires ctx_other to be set") without a model-level context default. |
| vLLM | `8000` | `qwen-abliterated` | Text-only, no vision. Backing model: `huihui-ai/Huihui-Qwen3.8-27B-abliterated`. Used only for the non-visual `EVALUATION_AGENT` role. |

**`llama-server` is NOT running.** The config file's comment is explicit that `Qwen3-VL-8B` / `Gemma-4-12B` via a dedicated llama-server on ports `8080`/`8081` were considered and **not stood up** — the DGX's 121GB unified memory is already committed to `qwen-abliterated` (~85GB) plus `gemma4-ufo` (~20GB), leaving ~36GB headroom, not enough to safely add two more models. If you see references to `:8080`/`:8081` for DGX elsewhere in the repo (e.g. `scripts/terminal.py`, `litellm_config.yaml`'s non-DGX `ufo-host-model`/`ufo-app-model`/`ufo-model` entries), those are either stale (Phase 1 flags `scripts/terminal.py`'s widget as still hardcoding these ports) or refer to a *local*, non-DGX llama-server setup on `127.0.0.1`, not the DGX box.

**Host addressing:** the DGX is reachable at its stable Tailscale IP `100.111.170.95`, which stays valid across LAN changes — prefer it over the DGX's LAN IP. This is the same IP hardcoded in `litellm_config.yaml` (see below).

## How UFO connects to the DGX today

### 1. `UFO_DGX_HOST` environment variable

Both `config/ufo/agents_dgx.yaml` and the terminal widget derive the DGX host from `UFO_DGX_HOST`. Set it with:

```powershell
[Environment]::SetEnvironmentVariable('UFO_DGX_HOST', '100.111.170.95', 'User')
```

(User scope, not Machine — see `docs/deployment/windows-arm64.md` for why Machine scope is a known, not-yet-fixed issue in `scripts/terminal.py`.) UFO's own `config_loader._expand_env_vars` interpolates this variable *inside* a string value (e.g. `"http://${UFO_DGX_HOST}:11434"`), which is how `agents_dgx.yaml` uses it.

### 2. `config/ufo/agents_dgx.yaml` — confirmed contents

Read directly from the file in this checkout:

```yaml
HOST_AGENT:
  VISUAL_MODE: true
  API_TYPE: ollama
  API_BASE: "http://${UFO_DGX_HOST}:11434"
  API_KEY: "ollama"
  API_MODEL: "gemma4-ufo"

APP_AGENT:
  VISUAL_MODE: true
  API_TYPE: ollama
  API_BASE: "http://${UFO_DGX_HOST}:11434"
  API_KEY: "ollama"
  API_MODEL: "gemma4-ufo"

BACKUP_AGENT:
  VISUAL_MODE: true
  API_TYPE: ollama
  API_BASE: "http://${UFO_DGX_HOST}:11434"
  API_KEY: "ollama"
  API_MODEL: "gemma4-ufo"

EVALUATION_AGENT:
  VISUAL_MODE: false
  API_TYPE: openai
  API_BASE: "http://${UFO_DGX_HOST}:8000/v1"
  API_KEY: "sk-local"
  API_MODEL: "qwen-abliterated"
```

`HOST_AGENT`, `APP_AGENT`, and `BACKUP_AGENT` all route to Ollama (`:11434`, `gemma4-ufo`); `EVALUATION_AGENT` routes to vLLM (`:8000`, `qwen-abliterated`) via the OpenAI-compatible API type. This matches the plan's own note (Phase 1 audit) that this file was "already fixed" and needs no further port rewriting.

To use this config from the terminal widget: `Terminal → AI Backend → Switch to DGX` (it will prompt for the host IP).

### 3. `litellm_config.yaml` — confirmed contents

Two DGX-specific routes are defined, confirmed from the file:

```yaml
  - model_name: "ufo-dgx-model"
    litellm_params:
      model: "openai/qwen-abliterated"
      api_base: "http://100.111.170.95:8000/v1"
      api_key: "sk-local"

  - model_name: "ufo-dgx-app-model"
    litellm_params:
      model: "openai/gemma4-ufo"
      api_base: "http://100.111.170.95:11434/v1"
      api_key: "ollama"
```

**Note the difference from `agents_dgx.yaml`:** these two entries hardcode the Tailscale IP (`100.111.170.95`) literally rather than referencing `UFO_DGX_HOST`. The file's own comment explains why — LiteLLM's `os.environ/VAR` substitution replaces an entire field value; it cannot interpolate a variable into the middle of a string the way UFO's own `config_loader._expand_env_vars` does. So `api_base` here must be kept in sync by hand if the DGX's address ever changes. The plan (Phase 4.3 / Phase 11 verification) treats this as either something a future config-generation layer under `config/container.py` should render at deploy time, or an explicitly accepted, documented exception — as of this writing it is still just the accepted exception, not yet generated.

Router-level fallback chains are also defined for both DGX routes, falling back to each other and then to `claude-3-7-sonnet` and the Featherless-hosted Qwen models:

```yaml
router_settings:
  fallbacks:
    - {"ufo-dgx-model": ["ufo-dgx-app-model", "claude-3-7-sonnet", "featherless-qwen-primary", "featherless-qwen-secondary", "featherless-qwen-tertiary"]}
    - {"ufo-dgx-app-model": ["ufo-dgx-model", "claude-3-7-sonnet", "featherless-qwen-primary", "featherless-qwen-secondary", "featherless-qwen-tertiary"]}
```

The plan's changelog (Correction/fix log referenced from `docs/status.md`, "Fixed Since Last Update") notes these DGX fallback chains were previously self-referencing and have since been corrected — the version above is the fixed one.

## Quick verification checklist

- [ ] `UFO_DGX_HOST` is set (User scope) to `100.111.170.95` or your DGX's current LAN IP
- [ ] `curl http://$UFO_DGX_HOST:11434/api/tags` (or equivalent) returns `gemma4-ufo` in the Ollama model list
- [ ] `curl http://$UFO_DGX_HOST:8000/v1/models` returns `qwen-abliterated` from vLLM
- [ ] You are **not** trying to reach anything on `:8080`/`:8081` on the DGX — nothing is listening there
- [ ] If you changed the DGX's IP, you updated both `agents_dgx.yaml` (automatic, via `UFO_DGX_HOST`) **and** `litellm_config.yaml`'s two literal `100.111.170.95` occurrences (manual, until Phase 11's config container generates this)

## What this doc does not cover

CI runners for DGX integration testing (`[self-hosted, linux, dgx]`) are defined in `.github/workflows/ci.yml` per `docs/status.md` but not provisioned — that's a CI/CD concern (Phase 6), out of scope here. The Linux-session `NotImplementedError` gap that blocks the DGX golden-path E2E test (Phase 5/Phase 10 dependency) is also out of scope for this connectivity guide.
