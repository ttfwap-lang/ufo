# Windows ARM64 Setup

> **Target flow, not yet buildable end-to-end.** This describes the setup UFO is meant to have once Phase 3 (Packaging & Dependency Hygiene) and Phase 4 (Security & Secrets Hardening) of `docs/plans/E2E_REMEDIATION_PLAN.md` land. As of 2026-09-18: `pyproject.toml` exists but `uv lock` is currently failing (dependency conflicts in the `core` extra — pydantic/structlog/opentelemetry/dependency-injector), and `install.ps1` **does not exist yet**. Nothing below is a script you can run today; it's the target sequence, marked step by step as confirmed-today vs. planned.

## Why this doc exists

UFO's CI plan (`docs/status.md`, Phase 6) calls for a self-hosted `[self-hosted, windows, arm64]` GitHub Actions runner. That runner isn't provisioned yet either. This guide is written from the same "no aspirational claims" discipline as the rest of `docs/` — every step below is tagged.

## Intended flow, step by step

### 1. `install.ps1` — **TODO, not yet built**

The plan calls for a single PowerShell bootstrap script at the repo root. It does not exist today (confirmed: no `install.ps1` anywhere in the tree at time of writing). Once built, it is expected to wrap steps 2-6 below into one command. Until then, run those steps by hand.

### 2. Create a virtual environment — planned, depends on Phase 3

```powershell
cd C:\path\to\ufo
python -m venv .venv
.venv\Scripts\Activate.ps1
```

This part works today with any checkout — venv creation itself has no dependency on the unfinished phases. It's listed here because `install.ps1` is expected to do it automatically.

### 3. Install dependencies with `uv sync --all-extras` — **blocked today**

```powershell
uv sync --all-extras
```

Per `docs/status.md` (Phase 3: 🔄 In Progress), `uv lock` currently fails on this repo due to dependency conflicts in the `core` extra. Do not expect this command to succeed on a fresh Windows ARM64 box until Phase 3 is resolved. `pyproject.toml`'s optional-dependency groups (`core`, `windows`, `native-win32`, `dgx`, `galaxy`, `eval`, `all`) are defined per the plan's Section 3.1, but the lockfile they resolve against isn't green yet.

The `windows` extra (`playwright>=1.48`) and `native-win32` extra (`pywinauto`, `uiautomation`, `comtypes`, `pywin32`) are both required on a Windows automation box — `native-win32` is not legacy-only despite the older naming; Phase 2 (Hybrid Playwright + UIA) still depends on it.

### 4. Install Playwright browser binaries — planned, depends on step 3

```powershell
playwright install
```

Only runs once `uv sync --all-extras` above actually succeeds and pulls in the `windows` extra. Not independently verified on ARM64 at time of writing — Playwright's ARM64 Windows browser binary support should be confirmed on first real run, not assumed.

### 5. Point at the DGX backend — `UFO_DGX_HOST`, User-scope

```powershell
[Environment]::SetEnvironmentVariable('UFO_DGX_HOST', '100.111.170.95', 'User')
```

This is a **security-hardening requirement from Phase 4**, not just a convenience: `scripts/terminal.py` today sets this same variable at **`'Machine'` scope** (lines 413 and 539, confirmed in the plan's Phase 4.1 table), which requires Administrator rights. The target fix is `'User'` scope, no admin required. That fix has not landed in `scripts/terminal.py` yet — if you run the terminal widget today, expect it to still try for Machine scope. Setting the User-scope variable yourself, as above, is a safe workaround in the meantime and will keep working once the fix lands.

Restart the shell (or `refreshenv`) after setting a new-process environment variable so `UFO_DGX_HOST` is visible to subsequent commands.

See `docs/deployment/dgx-spark.md` for what this variable actually points at and how it's consumed by `config/ufo/agents_dgx.yaml`.

### 6. API keys — `.env` and keyring, not HKLM

Planned module: `config/secrets.py` (Phase 4.4), providing `get_secret()`/`set_secret()` backed by the `keyring` package with a `.env`/`os.getenv()` fallback. **This module does not exist yet** — `config/` today only has `config_loader.py` and `config_schemas.py`. Until it lands:

- Do **not** rely on the HKLM registry read that `scripts/terminal.py` currently does for `GEMINI_API_KEY` (lines 502, 970) — that's flagged in the plan as a hardening item to remove, not a pattern to depend on.
- In the interim, a project-root `.env` file (loaded via `python-dotenv`, already a planned `core` dependency) is the safe, no-admin way to supply API keys:

```
# .env (not committed)
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Once `config/secrets.py` lands, the intended lookup order is: OS keyring (`ufo/<service>` namespace) → `.env`/process env (`KEY`) → prefixed env (`UFO_<SERVICE>_<KEY>`).

### 7. Verify the install — `ufo-terminal --selftest`

```powershell
ufo-terminal --selftest
```

This is the console-script entry point the plan defines in `pyproject.toml` (`ufo-terminal = "terminal.__main__:main"`, Phase 3.1) and the verification step the plan's own Phase 3 checklist requires ("`ufo-terminal --selftest` runs from a fresh venv"). Two things block this from working today:

- The `terminal/` package doesn't exist yet as a distinct package — `scripts/terminal.py` (1,188 lines) has not been split into `terminal/__main__.py` + friends (Phase 3.3, not started).
- `--selftest` itself is a planned flag ("exercises all menus without external deps", Phase 3 verification list) — confirm it's implemented in whatever `terminal/__main__.py` ships before trusting this command's exit code.

Until then, the closest today-equivalent is running `python scripts/terminal.py` directly and manually walking its menus — no automated selftest exists yet.

## Summary table

| Step | Status today |
|------|---------------|
| `install.ps1` bootstrap script | **Not built** |
| venv creation | Works, unrelated to blocked phases |
| `uv sync --all-extras` | **Blocked** — `uv lock` conflicts unresolved (Phase 3) |
| `playwright install` | Depends on the above; not independently verified on ARM64 |
| `UFO_DGX_HOST` at User scope | Works if you set it by hand; `scripts/terminal.py` itself still writes Machine-scope (Phase 4, not fixed) |
| `.env`/keyring secrets | `.env` works today; `config/secrets.py` keyring module **not built** |
| `ufo-terminal --selftest` | **Not built** — `terminal/` package and `--selftest` flag both pending (Phase 3) |

Once Phase 3 and Phase 4 both land, this document's steps should require no manual workarounds. Until then, treat every unchecked step above as a known gap, not a mistake in your setup.
