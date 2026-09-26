"""Constrained BrowserAct MCP executor for UFO's browser navigation arm.

This server exposes a deliberately small, fixed command surface.  It never
accepts a shell command, arbitrary argv, browser deletion, cookie transfer,
JavaScript evaluation, or proxy configuration.  BrowserAct's indexed state is
returned after each mutating operation, with a state token that prevents a
model from reusing stale element indices.

The server is usable with the normal UFO text/action protocol: FastMCP
schemas are rendered into the Host/App prompt and the model emits a
``browser_action`` function call in the same JSON response as other UFO
actions.  It also works with clients that call the tools directly.
"""

from __future__ import annotations

import atexit
import asyncio
import hmac
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from fastmcp import FastMCP
from pydantic import Field
from typing import Annotated

from ufo.automation.browseract_adapter import (
    BrowserActCLI,
    BrowserActConfig,
    BrowserActError,
    validate_navigation_url,
)
from ufo.client.mcp.mcp_registry import MCPRegistry


_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_INDEX_RE = re.compile(r"^[0-9]{1,6}$")
# These are intentionally not exposed: browser create/delete/update,
# import-profile, eval, cookies, network/HAR, captcha solving, and proxy
# changes all require a separate human-confirmed BrowserAct workflow.


@dataclass
class _Session:
    name: str
    browser_id: str
    state_token: str = ""
    last_used: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock)
    handoff: bool = False


class _Settings:
    """Read BrowserAct settings from UFO config plus process overrides."""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    @classmethod
    def load(cls) -> "_Settings":
        try:
            from ufo.config.config_loader import get_ufo_config

            config = get_ufo_config()
            values = getattr(config.system, "browseract", None)
            if values is None:
                values = getattr(config.system, "BROWSERACT", {})
            if hasattr(values, "to_dict"):
                values = values.to_dict()
            return cls(values if isinstance(values, Mapping) else {})
        except Exception:
            # Loading the optional server must never make unrelated UFO tools
            # unavailable.  Environment variables still provide a usable path.
            return cls({})

    def _value(self, *keys: str, default: Any = None) -> Any:
        for key in keys:
            value = self.values.get(key)
            if value not in (None, ""):
                return value
        return default

    def _env(self, name: str, default: Any = None) -> Any:
        value = os.environ.get(name)
        return default if value is None or value == "" else value

    @property
    def enabled(self) -> bool:
        value = self._env("BROWSERACT_ENABLED", self._value("ENABLED", "enabled", default=True))
        return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}

    def adapter_config(self) -> BrowserActConfig:
        raw = dict(self.values)
        # Environment values take precedence over YAML without requiring a
        # process restart or a rewrite of a user's local config.
        env_map = {
            "CLI_PATH": "BROWSERACT_CLI_PATH",
            "BROWSER_ID": "BROWSERACT_BROWSER_ID",
            "ALLOW_PRIVATE_NETWORKS": "BROWSERACT_ALLOW_PRIVATE_NETWORKS",
            "ALLOW_ABOUT_BLANK": "BROWSERACT_ALLOW_ABOUT_BLANK",
        }
        for key, env_name in env_map.items():
            if os.environ.get(env_name) not in (None, ""):
                raw[key] = os.environ[env_name]
        if os.environ.get("BROWSERACT_COMMAND_TIMEOUT_SECONDS"):
            raw["COMMAND_TIMEOUT_SECONDS"] = os.environ["BROWSERACT_COMMAND_TIMEOUT_SECONDS"]
        if os.environ.get("BROWSERACT_MAX_OUTPUT_CHARS"):
            raw["MAX_OUTPUT_CHARS"] = os.environ["BROWSERACT_MAX_OUTPUT_CHARS"]
        if os.environ.get("BROWSERACT_ALLOWED_DOMAINS"):
            raw["ALLOWED_DOMAINS"] = os.environ["BROWSERACT_ALLOWED_DOMAINS"]
        return BrowserActConfig.from_mapping(raw)

    def _safe_url(self, url: str, *, allow_about_blank: bool = True) -> str:
        adapter = self.adapter_config()
        if self.require_domain_allowlist and not adapter.allowed_domains:
            raise ValueError(
                "BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST is enabled but no domains are configured"
            )
        if self.require_domain_allowlist and str(url or "").strip().lower().startswith("about:blank"):
            raise ValueError("about:blank is disabled when a domain allowlist is required")
        return validate_navigation_url(
            url,
            allowed_domains=adapter.allowed_domains,
            allow_private_networks=adapter.allow_private_networks,
            allow_about_blank=allow_about_blank,
        )

    @property
    def browser_id(self) -> str:
        value = self._env("BROWSERACT_BROWSER_ID", self._value("BROWSER_ID", "browser_id", default=""))
        value = str(value or "").strip()
        if value and "${" in value:
            return ""
        return value

    @property
    def auto_select_single(self) -> bool:
        value = self._env("BROWSERACT_AUTO_SELECT_SINGLE", self._value("AUTO_SELECT_SINGLE_BROWSER", default=True))
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    @property
    def require_domain_allowlist(self) -> bool:
        value = self._env("BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST", self._value("REQUIRE_DOMAIN_ALLOWLIST", default=False))
        return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}

    @property
    def stealth_extract_enabled(self) -> bool:
        value = self._env("BROWSERACT_ALLOW_STEALTH_EXTRACT", self._value("ALLOW_STEALTH_EXTRACT", default=False))
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    @property
    def remote_assist_enabled(self) -> bool:
        value = self._env("BROWSERACT_ALLOW_REMOTE_ASSIST", self._value("ALLOW_REMOTE_ASSIST", default=True))
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    @property
    def max_input_chars(self) -> int:
        try:
            return max(1, min(int(self._env("BROWSERACT_MAX_INPUT_CHARS", self._value("MAX_INPUT_CHARS", default=10_000))), 100_000))
        except (TypeError, ValueError):
            return 10_000

    @property
    def max_state_chars(self) -> int:
        try:
            return max(1_000, min(int(self._env("BROWSERACT_MAX_STATE_CHARS", self._value("MAX_STATE_CHARS", default=30_000))), 200_000))
        except (TypeError, ValueError):
            return 30_000

    @property
    def state_idle_seconds(self) -> float:
        try:
            return max(30.0, min(float(self._env("BROWSERACT_SESSION_IDLE_SECONDS", self._value("SESSION_IDLE_SECONDS", default=900.0))), 86_400.0))
        except (TypeError, ValueError):
            return 900.0


class BrowserActSessionManager:
    """Own BrowserAct session names, state tokens, and mutation sequencing."""

    def __init__(self, settings: _Settings | None = None, cli: BrowserActCLI | None = None) -> None:
        self.settings = settings or _Settings.load()
        self.cli = cli or BrowserActCLI(self.settings.adapter_config())
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _new_name() -> str:
        return f"ufo-ba-{os.getpid()}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _validate_session_name(session: str) -> str:
        if not isinstance(session, str) or not _SESSION_RE.fullmatch(session):
            raise BrowserActError("Invalid BrowserAct session handle; use the handle returned by browser_action(open)")
        return session

    @staticmethod
    def _new_token() -> str:
        return uuid.uuid4().hex

    def _check_enabled(self) -> None:
        if not self.settings.enabled:
            raise BrowserActError("BrowserAct is disabled by UFO configuration (BROWSERACT.ENABLED=false)")

    def _cleanup_expired(self) -> None:
        cutoff = time.monotonic() - self.settings.state_idle_seconds
        with self._lock:
            expired = [
                name
                for name, record in self._sessions.items()
                if record.last_used < cutoff and not record.handoff
            ]
        for name in expired:
            try:
                self.close(name)
            except Exception:
                logger.debug("BrowserAct idle cleanup failed for %s", name, exc_info=True)

    def _get(self, session: str) -> _Session:
        self._check_enabled()
        self._cleanup_expired()
        name = self._validate_session_name(session)
        with self._lock:
            record = self._sessions.get(name)
            if record is None:
                raise BrowserActError(f"Unknown BrowserAct session {name!r}; open a new session first")
            if record.handoff:
                raise BrowserActError(f"BrowserAct session {name!r} is in remote-assist handoff; wait for the human to finish")
            record.last_used = time.monotonic()
            return record

    def _put_state(self, record: _Session, payload: Mapping[str, Any]) -> Dict[str, Any]:
        token = self._new_token()
        record.state_token = token
        # BrowserAct's JSON wrapper uses a ``state`` member.  Expose that
        # member directly so the model sees the same indexed snapshot the CLI
        # documents, rather than an extra protocol layer it might mistake for
        # a page element.
        state_value: Any = payload.get("state", payload)
        if isinstance(state_value, Mapping):
            # Keep useful top-level metadata when the CLI provides it, but do
            # not nest the state object under another state key.
            state = self._bounded(dict(state_value), self.settings.max_state_chars)
        else:
            state = self._bounded(state_value, self.settings.max_state_chars)
        return {
            "ok": True,
            "session": record.name,
            "state_token": token,
            "state": state,
        }

    @staticmethod
    def _bounded(value: Any, limit: int) -> Any:
        """Bound nested CLI output before it reaches model memory/logs."""
        if isinstance(value, str):
            if len(value) <= limit:
                return value
            return value[:limit] + f"\n[… state truncated; {len(value) - limit} characters omitted]"
        if isinstance(value, list):
            result = []
            remaining = limit
            for item in value:
                if remaining <= 0:
                    break
                bounded = BrowserActSessionManager._bounded(item, remaining)
                result.append(bounded)
                remaining -= len(str(bounded))
            return result
        if isinstance(value, dict):
            result_dict: Dict[str, Any] = {}
            remaining = limit
            for key, item in value.items():
                if remaining <= 0:
                    result_dict["_truncated"] = True
                    break
                bounded = BrowserActSessionManager._bounded(item, remaining)
                result_dict[str(key)] = bounded
                remaining -= len(str(bounded))
            return result_dict
        return value

    def _resolve_browser_id(self, requested: str | None) -> str:
        configured = str(self.settings.browser_id or "").strip()
        requested_value = str(requested or "").strip()
        if configured:
            if requested_value and requested_value != configured:
                raise BrowserActError(
                    "The requested BrowserAct browser does not match the operator-configured BROWSERACT_BROWSER_ID"
                )
            return self._safe_cli_value(configured, "browser ID")
        if requested_value:
            raise BrowserActError(
                "Browser selection is operator-controlled; set BROWSERACT_BROWSER_ID"
            )
        listing = self.cli.browser_list()
        browsers = listing.get("browsers") if isinstance(listing, Mapping) else None
        if not isinstance(browsers, list):
            browsers = []
        if len(browsers) == 1 and self.settings.auto_select_single:
            browser_id = str(browsers[0].get("id", "")).strip()
            if browser_id:
                return self._safe_cli_value(browser_id, "browser ID")
        if not browsers:
            raise BrowserActError(
                "No BrowserAct browser is configured. Run 'browser-act browser list', "
                "create/choose a browser in BrowserAct, and set BROWSERACT_BROWSER_ID."
            )
        raise BrowserActError("Multiple BrowserAct browsers are available; pass browser_id explicitly or set BROWSERACT_BROWSER_ID")

    def _state_call(self, record: _Session) -> Dict[str, Any]:
        # Invalidate before the read: a timeout/error must not leave an old
        # index/token usable for a subsequent mutation.
        record.state_token = ""
        result = self.cli.run(["state"], session=record.name)
        return self._put_state(record, result)

    def _require_fresh_token(self, record: _Session, token: str | None) -> None:
        if not token:
            raise BrowserActError("A current state_token is required for a BrowserAct mutation; call browser_action(action='state') first")
        if not record.state_token or not hmac.compare_digest(str(token), record.state_token):
            raise BrowserActError("Stale or invalid BrowserAct state_token; call browser_action(action='state') again before mutating the page")

    def _mutate(self, record: _Session, args: list[str], *, refresh: bool = True) -> Dict[str, Any]:
        # Invalidate before the subprocess starts.  A timeout can leave the
        # remote page in an unknown state, and retrying a click would be unsafe.
        record.state_token = ""
        result = self.cli.run(args, session=record.name)
        response: Dict[str, Any] = {"ok": True, "session": record.name, "action_result": self._bounded(result, self.settings.max_state_chars)}
        if refresh:
            try:
                response.update(self._state_call(record))
            except BrowserActError as state_error:
                response["ok"] = False
                response["error"] = f"BrowserAct action completed, but fresh state could not be read: {state_error}"
                response["action_result"] = self._bounded(result, self.settings.max_state_chars)
        else:
            response["state_token"] = None
            response["state"] = None
        return response

    def open(self, *, url: str, browser_id: str | None = None, headed: bool = False) -> Dict[str, Any]:
        self._check_enabled()
        adapter = self.settings.adapter_config()
        safe_url = self.settings._safe_url(url, allow_about_blank=adapter.allow_about_blank)
        selected = self._resolve_browser_id(browser_id)
        name = self._new_name()
        args = ["browser", "open", selected, safe_url]
        if headed:
            args.append("--headed")
        record = _Session(name=name, browser_id=selected)
        with self._lock:
            self._sessions[name] = record
        try:
            result = self.cli.run(args, session=name)
        except Exception:
            # Reconcile an ambiguous open.  Retain the local handle when the
            # close itself is uncertain so shutdown can retry cleanup.
            try:
                self.cli.run(["session", "close", name], timeout=min(adapter.timeout_seconds, 15.0))
            except BrowserActError as close_error:
                detail = str(close_error).lower()
                if not any(marker in detail for marker in ("not found", "not_found", "already closed", "does not exist", "404")):
                    raise
            with self._lock:
                self._sessions.pop(name, None)
            raise
        try:
            response = self._state_call(record)
        except Exception:
            self.close(name)
            raise
        response["browser_id"] = selected
        response["open_result"] = self._bounded(result, self.settings.max_state_chars)
        return response

    def state(self, session: str) -> Dict[str, Any]:
        record = self._get(session)
        with record.lock:
            return self._state_call(record)

    def navigate(self, session: str, *, state_token: str, url: str) -> Dict[str, Any]:
        record = self._get(session)
        safe_url = self.settings._safe_url(url, allow_about_blank=self.settings.adapter_config().allow_about_blank)
        with record.lock:
            self._require_fresh_token(record, state_token)
            return self._mutate(record, ["navigate", safe_url])

    def click(self, session: str, *, state_token: str, index: int | None = None, selector: str | None = None) -> Dict[str, Any]:
        record = self._get(session)
        args = self._target_args("click", index, selector)
        with record.lock:
            self._require_fresh_token(record, state_token)
            return self._mutate(record, args)

    def input(self, session: str, *, state_token: str, text: str, index: int | None = None, selector: str | None = None, mode: str = "fill") -> Dict[str, Any]:
        record = self._get(session)
        value = self._safe_cli_value(text, "input text")
        if not value:
            raise BrowserActError("BrowserAct input text must not be empty")
        if len(value) > self.settings.max_input_chars:
            raise BrowserActError(f"BrowserAct input exceeds the configured limit of {self.settings.max_input_chars} characters")
        mode = str(mode or "fill").lower()
        if mode not in {"fill", "append"}:
            raise BrowserActError("BrowserAct input mode must be 'fill' or 'append'")
        with record.lock:
            self._require_fresh_token(record, state_token)
            if index is not None:
                args = ["input", str(index), value, "--mode", mode]
            elif selector:
                args = [
                    "input",
                    "--selector",
                    self._safe_cli_value(selector, "selector"),
                    "--text",
                    value,
                    "--mode",
                    mode,
                ]
            else:
                raise BrowserActError("BrowserAct input requires index or selector")
            return self._mutate(record, args)

    def select(self, session: str, *, state_token: str, option: str, index: int | None = None, selector: str | None = None) -> Dict[str, Any]:
        record = self._get(session)
        option = self._safe_cli_value(option, "select option")
        if not option.strip():
            raise BrowserActError("BrowserAct select option must not be empty")
        with record.lock:
            self._require_fresh_token(record, state_token)
            args = self._target_args("select", index, selector, option=str(option))
            return self._mutate(record, args)

    def keys(self, session: str, *, state_token: str, keys: str) -> Dict[str, Any]:
        record = self._get(session)
        value = self._safe_cli_value(keys, "keys").strip()
        if not value:
            raise BrowserActError("BrowserAct keys must not be empty")
        with record.lock:
            self._require_fresh_token(record, state_token)
            return self._mutate(record, ["keys", value])

    def scroll(self, session: str, *, state_token: str, direction: str, amount: int | None = None) -> Dict[str, Any]:
        record = self._get(session)
        direction = str(direction or "").lower()
        if direction not in {"up", "down"}:
            raise BrowserActError("BrowserAct scroll direction must be 'up' or 'down'")
        with record.lock:
            self._require_fresh_token(record, state_token)
            args = ["scroll", direction]
            if amount is not None:
                args.extend(["--amount", str(max(1, min(int(amount), 20_000)))])
            return self._mutate(record, args)

    def scroll_into_view(self, session: str, *, state_token: str, selector: str) -> Dict[str, Any]:
        record = self._get(session)
        if not str(selector or "").strip():
            raise BrowserActError("BrowserAct scrollintoview requires a selector")
        with record.lock:
            self._require_fresh_token(record, state_token)
            return self._mutate(record, ["scrollintoview", "--selector", selector])

    def wait(self, session: str, *, state_token: str | None = None, selector: str | None = None, timeout_ms: int | None = None) -> Dict[str, Any]:
        record = self._get(session)
        with record.lock:
            if selector:
                if state_token:
                    self._require_fresh_token(record, state_token)
                args = ["wait", "selector", "--selector", selector, "--state", "visible", "--timeout", str(max(100, min(int(timeout_ms or 10_000), 120_000)))]
            else:
                args = ["wait", "stable", "--timeout", str(max(100, min(int(timeout_ms or 30_000), 120_000)))]
            # Waiting is a read/settle operation; it can be used after a
            # mutation but does not need a state token.
            return self._mutate(record, args, refresh=True)

    def get(self, session: str, *, kind: str, index: int | None = None, selector: str | None = None) -> Dict[str, Any]:
        record = self._get(session)
        kind = str(kind or "").lower()
        if kind not in {"title", "markdown", "text", "value", "html"}:
            raise BrowserActError("BrowserAct get kind must be title, markdown, text, value, or html")
        if kind == "title" and (index is not None or selector):
            raise BrowserActError("BrowserAct get title does not accept an index or selector")
        if kind == "markdown" and selector:
            raise BrowserActError("BrowserAct get markdown does not accept a selector")
        if selector:
            selector = self._safe_cli_value(selector, "selector")
        args = ["get", kind]
        if kind in {"markdown", "text", "value", "html"} and index is not None:
            args.append(str(index))
        elif kind in {"text", "value", "html"} and selector:
            args.extend(["--selector", selector])
        elif kind in {"text", "value"}:
            raise BrowserActError(f"BrowserAct get {kind} requires an index or selector")
        with record.lock:
            result = self.cli.run(args, session=record.name)
        return {"ok": True, "session": record.name, "kind": kind, "result": self._bounded(result, self.settings.max_state_chars)}

    def screenshot(self, session: str, *, full: bool = False) -> Dict[str, Any]:
        record = self._get(session)
        args = ["screenshot"]
        if full:
            args.append("--full")
        with record.lock:
            result = self.cli.run(args, session=record.name)
        return {"ok": True, "session": record.name, "screenshot": self._bounded(result, self.settings.max_state_chars)}

    def close(self, session: str) -> Dict[str, Any]:
        self._check_enabled()
        name = self._validate_session_name(session)
        with self._lock:
            record = self._sessions.get(name)
        if record is None:
            return {"ok": True, "session": name, "already_closed": True}
        try:
            result = self.cli.run(["session", "close", name], timeout=min(self.settings.adapter_config().timeout_seconds, 15.0))
        except BrowserActError as exc:
            detail = str(exc)
            already_closed = any(
                marker in detail.lower()
                for marker in ("not found", "not_found", "already closed", "does not exist", "unknown session", "404")
            )
            if already_closed:
                with self._lock:
                    self._sessions.pop(name, None)
                return {"ok": True, "session": name, "already_closed": True}
            # Retain ownership when the remote state is ambiguous.
            return {"ok": False, "session": name, "error": detail}
        with self._lock:
            self._sessions.pop(name, None)
        return {"ok": True, "session": name, "close_result": self._bounded(result, 4_000)}

    def remote_assist(self, session: str, *, objective: str, confirm: bool) -> Dict[str, Any]:
        if not self.settings.remote_assist_enabled:
            raise BrowserActError("BrowserAct remote-assist is disabled by configuration")
        if not confirm:
            raise BrowserActError("Remote assist requires confirm=true and explicit human approval")
        record = self._get(session)
        objective = self._safe_cli_value(objective, "remote-assist objective").strip()
        if not objective:
            raise BrowserActError("Remote assist requires a non-empty objective")
        with record.lock:
            result = self.cli.run(["remote-assist", "--objective", objective], session=record.name)
            record.handoff = True
        return {"ok": True, "session": record.name, "handoff": True, "result": self._bounded(result, self.settings.max_state_chars)}

    def stealth_extract(self, *, url: str, content_type: str = "markdown", timeout_seconds: int = 60) -> Dict[str, Any]:
        if not self.settings.stealth_extract_enabled:
            raise BrowserActError("BrowserAct stealth extraction is disabled by configuration")
        safe_url = self.settings._safe_url(url, allow_about_blank=False)
        content_type = str(content_type or "markdown").lower()
        if content_type not in {"markdown", "html"}:
            raise BrowserActError("BrowserAct content_type must be markdown or html")
        args = ["stealth-extract", safe_url, "--content-type", content_type, "--timeout", str(max(5, min(int(timeout_seconds), 180)))]
        return {"ok": True, "url": safe_url, "content_type": content_type, "result": self._bounded(self.cli.run(args), self.settings.max_state_chars)}

    def browser_list(self) -> Dict[str, Any]:
        self._check_enabled()
        return self.cli.browser_list()

    def diagnostics(self) -> Dict[str, Any]:
        self._check_enabled()
        result: Dict[str, Any] = {"ok": True, "enabled": True}
        try:
            result["version"] = self.cli.version()
        except BrowserActError as exc:
            result["version_error"] = str(exc)
        try:
            result["browsers"] = self.cli.browser_list()
        except BrowserActError as exc:
            result["browsers_error"] = str(exc)
        try:
            result["sessions"] = self.cli.session_list()
        except BrowserActError as exc:
            result["sessions_error"] = str(exc)
        return result

    @staticmethod
    def _safe_cli_value(value: Any, field: str) -> str:
        text = str(value or "")
        if text.startswith("-") or "\x00" in text:
            raise BrowserActError(f"BrowserAct {field} cannot start with an option marker")
        return text

    @staticmethod
    def _target_args(command: str, index: int | None, selector: str | None, *, option: str | None = None) -> list[str]:
        if index is not None:
            if not _INDEX_RE.fullmatch(str(index)):
                raise BrowserActError("BrowserAct element index must be a positive integer from the current state")
            if int(index) < 1:
                raise BrowserActError("BrowserAct element index must be greater than zero")
            args = [command, str(index)]
            if option is not None:
                args.append(str(option))
            return args
        if selector and str(selector).strip():
            args = [command, "--selector", BrowserActSessionManager._safe_cli_value(selector, "selector")]
            if option is not None:
                # Select uses --option; click/hover do not take an option.
                if command == "select":
                    args.extend(["--option", str(option)])
            return args
        raise BrowserActError(f"BrowserAct {command} requires an element index or selector")

    def close_all(self) -> None:
        with self._lock:
            names = list(self._sessions)
        for name in names:
            try:
                self.close(name)
            except Exception:
                logger.debug("BrowserAct cleanup failed for %s", name, exc_info=True)


# One manager per Python process.  FastMCP may instantiate a factory more than
# once while a session is being initialized; keeping this at module scope
# prevents accidental session-name collisions.
_MANAGER: BrowserActSessionManager | None = None
_MANAGER_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def get_manager() -> BrowserActSessionManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = BrowserActSessionManager()
            atexit.register(_MANAGER.close_all)
        return _MANAGER


async def _call(method: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run a synchronous manager method without blocking FastMCP's loop."""
    manager = get_manager()
    try:
        return await asyncio.to_thread(getattr(manager, method), *args, **kwargs)
    except BrowserActError as exc:
        return exc.as_dict()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "error_type": "ValueError"}
    except Exception as exc:
        return {"ok": False, "error": f"BrowserAct executor failed: {exc}", "error_type": type(exc).__name__}


@MCPRegistry.register_factory_decorator("BrowserActExecutor")
@MCPRegistry.register_factory_decorator("browseract_mcp_server")
def create_browseract_mcp_server(*args: Any, **kwargs: Any) -> FastMCP:
    """Create the BrowserAct MCP server and its constrained tool surface."""
    mcp = FastMCP(
        "UFO BrowserAct Executor",
        instructions=(
            "Use browser_action with open -> state -> one mutation -> fresh state. "
            "The state_token and element indexes are ephemeral; never reuse indexes "
            "from an earlier observation."
        ),
    )

    @mcp.tool()
    async def browser_action(
        action: Annotated[str, Field(description="One of: diagnostics, list_browsers, open, state, navigate, click, input, select, keys, scroll, scrollintoview, wait, get, screenshot, close, remote_assist, stealth_extract.")],
        url: Annotated[Optional[str], Field(description="HTTP(S) URL for open/navigate/stealth_extract.")] = None,
        browser_id: Annotated[Optional[str], Field(description="Optional browser ID; when configured by the operator it must match BROWSERACT_BROWSER_ID.")] = None,
        session: Annotated[Optional[str], Field(description="Session handle returned by a prior open/state result.")] = None,
        state_token: Annotated[Optional[str], Field(description="Current token returned by the latest state observation; required for mutations.")] = None,
        index: Annotated[Optional[int], Field(description="Element index from the latest state output.")] = None,
        selector: Annotated[Optional[str], Field(description="Optional CSS selector instead of an index.")] = None,
        text: Annotated[Optional[str], Field(description="Text for input.")] = None,
        option: Annotated[Optional[str], Field(description="Visible option for select.")] = None,
        keys: Annotated[Optional[str], Field(description="BrowserAct key combination for keys, e.g. Enter.")] = None,
        direction: Annotated[Optional[str], Field(description="Scroll direction: up or down.")] = None,
        amount: Annotated[Optional[int], Field(description="Scroll amount in pixels.")] = None,
        kind: Annotated[Optional[str], Field(description="For get: title, markdown, text, value, or html.")] = None,
        full: Annotated[bool, Field(description="Capture a full-page screenshot.")] = False,
        headed: Annotated[bool, Field(description="Open BrowserAct with a visible browser (requires operator-approved local browser configuration).")] = False,
        mode: Annotated[str, Field(description="Input mode: fill (default) or append.")] = "fill",
        timeout_ms: Annotated[Optional[int], Field(description="Wait timeout in milliseconds.")] = None,
        timeout_seconds: Annotated[Optional[int], Field(description="Stealth extraction timeout in seconds.")] = 60,
        confirm: Annotated[bool, Field(description="Required true for remote_assist; never inferred by the model.")] = False,
    ) -> Dict[str, Any]:
        """Execute one constrained BrowserAct operation.

        The normal sequence is::

            browser_action(action="open", url="https://example.com")
            browser_action(action="state", session=...)
            browser_action(action="click", session=..., state_token=..., index=...)
            browser_action(action="state", session=...)

        Mutating operations automatically request a fresh state and return a
        new token.  At most one mutation should be planned per UFO turn.
        """
        action_name = str(action or "").strip().lower().replace("-", "_")
        if action_name == "diagnostics":
            return await _call("diagnostics")
        if action_name in {"list_browsers", "browsers"}:
            return await _call("browser_list")
        if action_name == "open":
            if not url:
                return {"ok": False, "error": "browser_action(open) requires url"}
            return await _call("open", url=url, browser_id=browser_id, headed=bool(headed))
        if action_name == "state":
            if not session:
                return {"ok": False, "error": "browser_action(state) requires session"}
            return await _call("state", session)
        if action_name == "navigate":
            if not session or not url or not state_token:
                return {"ok": False, "error": "browser_action(navigate) requires session, state_token, and url"}
            return await _call("navigate", session, state_token=state_token, url=url)
        if action_name == "click":
            if not session or not state_token:
                return {"ok": False, "error": "browser_action(click) requires session and state_token"}
            return await _call("click", session, state_token=state_token, index=index, selector=selector)
        if action_name == "input":
            if not session or not state_token or text is None:
                return {"ok": False, "error": "browser_action(input) requires session, state_token, and text"}
            return await _call("input", session, state_token=state_token, text=text, index=index, selector=selector, mode=mode)
        if action_name == "select":
            if not session or not state_token or option is None:
                return {"ok": False, "error": "browser_action(select) requires session, state_token, and option"}
            return await _call("select", session, state_token=state_token, option=option, index=index, selector=selector)
        if action_name == "keys":
            if not session or not state_token or not keys:
                return {"ok": False, "error": "browser_action(keys) requires session, state_token, and keys"}
            return await _call("keys", session, state_token=state_token, keys=keys)
        if action_name == "scroll":
            if not session or not state_token or not direction:
                return {"ok": False, "error": "browser_action(scroll) requires session, state_token, and direction"}
            return await _call("scroll", session, state_token=state_token, direction=direction, amount=amount)
        if action_name == "scrollintoview":
            if not session or not state_token or not selector:
                return {"ok": False, "error": "browser_action(scrollintoview) requires session, state_token, and selector"}
            return await _call("scroll_into_view", session, state_token=state_token, selector=selector)
        if action_name == "wait":
            if not session:
                return {"ok": False, "error": "browser_action(wait) requires session"}
            return await _call("wait", session, state_token=state_token, selector=selector, timeout_ms=timeout_ms)
        if action_name == "get":
            if not session or not kind:
                return {"ok": False, "error": "browser_action(get) requires session and kind"}
            return await _call("get", session, kind=kind, index=index, selector=selector)
        if action_name == "screenshot":
            if not session:
                return {"ok": False, "error": "browser_action(screenshot) requires session"}
            return await _call("screenshot", session, full=bool(full))
        if action_name == "close":
            if not session:
                return {"ok": False, "error": "browser_action(close) requires session"}
            return await _call("close", session)
        if action_name == "remote_assist":
            if not session:
                return {"ok": False, "error": "browser_action(remote_assist) requires session"}
            return await _call("remote_assist", session, objective=text or option or "", confirm=bool(confirm))
        if action_name == "stealth_extract":
            if not url:
                return {"ok": False, "error": "browser_action(stealth_extract) requires url"}
            return await _call("stealth_extract", url=url, content_type=kind or "markdown", timeout_seconds=timeout_seconds or 60)
        return {"ok": False, "error": f"Unsupported BrowserAct action: {action}"}

    @mcp.tool()
    async def browseract_open(
        url: Annotated[str, Field(description="HTTP(S) URL to open.")],
        browser_id: Annotated[Optional[str], Field(description="BrowserAct browser ID.")] = None,
        headed: Annotated[bool, Field(description="Use a visible browser.")] = False,
    ) -> Dict[str, Any]:
        """Open a new BrowserAct session and return its first indexed state."""
        return await _call("open", url=url, browser_id=browser_id, headed=headed)

    @mcp.tool()
    async def browseract_state(
        session: Annotated[str, Field(description="Session handle returned by browseract_open.")],
    ) -> Dict[str, Any]:
        """Read fresh compact BrowserAct state and issue a new state token."""
        return await _call("state", session)

    @mcp.tool()
    async def browseract_click(
        session: Annotated[str, Field(description="Current BrowserAct session handle.")],
        state_token: Annotated[str, Field(description="Token from the latest state observation.")],
        index: Annotated[Optional[int], Field(description="Current indexed element.")] = None,
        selector: Annotated[Optional[str], Field(description="Optional CSS selector.")] = None,
    ) -> Dict[str, Any]:
        """Click one current-state element and return fresh state."""
        return await _call("click", session, state_token=state_token, index=index, selector=selector)

    @mcp.tool()
    async def browseract_input(
        session: Annotated[str, Field(description="Current BrowserAct session handle.")],
        state_token: Annotated[str, Field(description="Token from the latest state observation.")],
        text: Annotated[str, Field(description="Text to enter.")],
        index: Annotated[Optional[int], Field(description="Current indexed input element.")] = None,
        selector: Annotated[Optional[str], Field(description="Optional CSS selector.")] = None,
        mode: Annotated[str, Field(description="fill or append")] = "fill",
    ) -> Dict[str, Any]:
        """Enter text into one current-state field and return fresh state."""
        return await _call("input", session, state_token=state_token, text=text, index=index, selector=selector, mode=mode)

    @mcp.tool()
    async def browseract_get_markdown(
        session: Annotated[str, Field(description="Current BrowserAct session handle.")],
    ) -> Dict[str, Any]:
        """Return bounded rendered Markdown for the current page."""
        return await _call("get", session, kind="markdown")

    @mcp.tool()
    async def browseract_close(
        session: Annotated[str, Field(description="Session handle to close.")],
    ) -> Dict[str, Any]:
        """Close a BrowserAct session owned by this UFO process."""
        return await _call("close", session)

    @mcp.tool()
    async def browseract_diagnostics() -> Dict[str, Any]:
        """Report CLI availability, configured browsers, and active sessions without mutating anything."""
        return await _call("diagnostics")

    @mcp.tool()
    async def browseract_browser_list() -> Dict[str, Any]:
        """List BrowserAct browser identities so the operator can select one explicitly."""
        return await _call("browser_list")

    return mcp


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    create_browseract_mcp_server().run()


__all__ = [
    "BrowserActSessionManager",
    "create_browseract_mcp_server",
    "get_manager",
]
