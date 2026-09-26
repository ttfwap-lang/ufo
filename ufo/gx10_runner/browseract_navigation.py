"""Optional BrowserAct navigation tool for the native gx10 agent loop.

The main UFO desktop path uses the FastMCP executor in
``client/mcp/local_servers/browseract_mcp_server.py``.  The gx10 Telegram
runner is intentionally standalone (it is copied into a small Linux image), so
this module contains the same constrained fixed-argv boundary without pulling
UFO's desktop dependencies into that image.

It is enabled only when ``BROWSERACT_ENABLED=1`` and a BrowserAct CLI is
available.  No model-supplied shell command is accepted.  The supported loop
is ``open -> state -> one mutation -> fresh state``; state tokens and element
indexes are deliberately short-lived. Hosted stealth extraction is opt-in.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit


class BrowserActError(RuntimeError):
    """A safe, user-facing BrowserAct command or policy error."""


_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_INDEX_RE = re.compile(r"^[1-9][0-9]{0,5}$")
_KEYS_RE = re.compile(r"^[A-Za-z0-9_{}+\-.:,/\[\] ]{1,200}$")
_MUTATIONS = frozenset(
    {
        "open",
        "navigate",
        "click",
        "input",
        "select",
        "keys",
        "scroll",
        "scrollintoview",
        "scroll_into_view",
    }
)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled", ""}


def _normalise_action(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _reject_cli_option(value: str, field: str) -> str:
    """Prevent BrowserAct's anywhere-global flag parser seeing model data."""
    if value.startswith("-") or "\x00" in value:
        raise BrowserActError(f"BrowserAct {field} cannot start with an option marker")
    return value


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[truncated; {len(value) - limit} characters omitted]"


def _bounded(value: Any, limit: int) -> Any:
    """Bound nested CLI output before it is returned to the model."""

    if isinstance(value, str):
        return _truncate(_redact_cli_text(value), limit)
    if isinstance(value, list):
        result = []
        remaining = limit
        for item in value:
            if remaining <= 0:
                break
            bounded = _bounded(item, remaining)
            result.append(bounded)
            remaining -= len(str(bounded))
        return result
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        remaining = limit
        for key, item in value.items():
            if remaining <= 0:
                result["_truncated"] = True
                break
            bounded = _bounded(item, remaining)
            result[str(key)] = bounded
            remaining -= len(str(bounded))
        return result
    return value


def _dump(value: Any, limit: int = 30_000) -> str:
    """Serialize a bounded response as compact JSON."""

    bounded = _bounded(value, max(1_000, int(limit)))
    return json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))


def _redact_cli_text(value: str) -> str:
    """Redact credentials if a CLI diagnostic happens to echo them."""

    text = str(value or "")
    for name in (
        "BROWSERACT_API_KEY",
        "BROWSERACT_KEY",
        "FEATHERLESS_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "BOT_TOKEN",
        "UFO_BRIDGE_TOKEN",
    ):
        secret = os.environ.get(name, "").strip()
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(r"(?i)(https?://)[^/\s:@]+:[^@/\s]+@", r"\1***:***@", text)
    return text


def _normalise_domain(value: str) -> str:
    value = str(value or "").strip().lower().rstrip(".")
    if value.startswith("*."):
        value = value[2:]
    return value


def _domain_allowed(hostname: str, allowed_domains: Sequence[str]) -> bool:
    allowed = tuple(_normalise_domain(item) for item in allowed_domains if str(item).strip())
    if not allowed:
        return True
    host = _normalise_domain(hostname)
    return any(host == domain or host.endswith("." + domain) for domain in allowed)


def _is_private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _host_has_private_address(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return True
    try:
        return _is_private_address(lowered)
    except ValueError:
        pass
    try:
        addresses = socket.getaddrinfo(lowered, None, type=socket.SOCK_STREAM)
    except OSError:
        # A DNS failure is handled by BrowserAct itself.  Do not turn a normal
        # public hostname into a false positive merely because DNS is down.
        return False
    return any(_is_private_address(str(info[4][0])) for info in addresses)


def is_mutation(action: str) -> bool:
    """Return whether an action changes browser/page state.

    ``open`` is included because it creates a session and navigates a page.
    State, get, wait, diagnostics, and close remain read/settle operations.
    """

    return _normalise_action(action) in _MUTATIONS


class BrowserActNavigator:
    """One isolated BrowserAct session with ephemeral state-token checks."""

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        browser_id: str = "",
        timeout_seconds: float = 300.0,
        runner: Callable[..., Any] | None = None,
        allow_private_networks: bool = False,
        allowed_domains: Sequence[str] | str | None = None,
        require_domain_allowlist: bool = False,
        allow_about_blank: bool = True,
        max_input_chars: int = 10_000,
        max_output_chars: int = 30_000,
        max_state_chars: int = 30_000,
        auto_select_single: bool = True,
        allow_stealth_extract: bool = False,
        allow_requested_browser: bool = False,
        auto_handshake: bool | None = None,
    ) -> None:
        configured_cli = os.environ.get("BROWSERACT_CLI_PATH") or os.environ.get("BROWSERACT_CLI")
        self.cli_path = str(cli_path or configured_cli or "browser-act")
        self.browser_id = str(
            browser_id or os.environ.get("BROWSERACT_BROWSER_ID", "")
        ).strip()
        if "${" in self.browser_id:
            self.browser_id = ""
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout = 300.0
        self.timeout_seconds = max(30.0, min(timeout, 300.0))
        self._runner = runner or subprocess.run
        self.allow_private_networks = _as_bool(allow_private_networks, False)
        if isinstance(allowed_domains, str):
            self.allowed_domains = tuple(
                item.strip() for item in allowed_domains.split(",") if item.strip()
            )
        else:
            self.allowed_domains = tuple(
                str(item).strip() for item in (allowed_domains or ()) if str(item).strip()
            )
        self.require_domain_allowlist = _as_bool(require_domain_allowlist, False)
        self.allow_about_blank = _as_bool(allow_about_blank, True)
        try:
            input_limit = int(max_input_chars)
        except (TypeError, ValueError):
            input_limit = 10_000
        try:
            output_limit = int(max_output_chars)
        except (TypeError, ValueError):
            output_limit = 30_000
        try:
            state_limit = int(max_state_chars)
        except (TypeError, ValueError):
            state_limit = 30_000
        self.max_input_chars = max(1, min(input_limit, 100_000))
        self.max_output_chars = max(1_000, min(output_limit, 500_000))
        self.max_state_chars = max(1_000, min(state_limit, 500_000))
        self.auto_select_single = _as_bool(auto_select_single, True)
        self.allow_stealth_extract = _as_bool(allow_stealth_extract, False)
        self.allow_requested_browser = _as_bool(
            allow_requested_browser,
            _as_bool(os.environ.get("BROWSERACT_ALLOW_REQUESTED_BROWSER"), False),
        )
        self._lock = threading.RLock()
        self.auto_handshake = (
            runner is None if auto_handshake is None else bool(auto_handshake)
        )
        self._handshake_ready = False
        self._handshake_lock = threading.Lock()
        self.session: str | None = None
        self.browser: str | None = None
        self.state_token: str | None = None

    # ------------------------------------------------------------------
    # Process and policy boundary
    # ------------------------------------------------------------------
    def _executable(self) -> str:
        candidate = os.path.expandvars(os.path.expanduser(self.cli_path))
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
        found = shutil.which(candidate)
        if found:
            return found
        for default in ("browser-act", "browser-act.exe"):
            found = shutil.which(default)
            if found:
                return found
        raise BrowserActError(
            "BrowserAct CLI is unavailable; install browser-act-cli in the runner image "
            "or set BROWSERACT_CLI_PATH."
        )

    @staticmethod
    def _handshake_exempt(args: Sequence[str]) -> bool:
        if not args:
            return True
        return str(args[0]) in {
            "--version",
            "-v",
            "--v",
            "--help",
            "-h",
            "get-skills",
        }

    def _ensure_skill_handshake(self) -> None:
        if not self.auto_handshake or self._handshake_ready:
            return
        if os.environ.get("BROWSERACT_DISABLE_SKILL_HANDSHAKE_GATE", "").strip() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            self._handshake_ready = True
            return
        with self._handshake_lock:
            if self._handshake_ready:
                return
            main_payload = self._run(
                ["get-skills", "main"],
                timeout=min(self.timeout_seconds, 60.0),
                _skip_handshake=True,
            )
            content = str(main_payload.get("content", ""))
            match = re.search(r"version:\s*[\"']?([0-9]+(?:\.[0-9]+)+)", content)
            skill_version = match.group(1) if match else os.environ.get(
                "BROWSERACT_SKILL_VERSION", ""
            ).strip()
            if not skill_version:
                raise BrowserActError(
                    "BrowserAct skill version could not be discovered; set BROWSERACT_SKILL_VERSION"
                )
            self._run(
                ["get-skills", "core", "--skill-version", skill_version],
                timeout=min(self.timeout_seconds, 60.0),
                _skip_handshake=True,
            )
            self._handshake_ready = True

    def _run(
        self,
        args: Sequence[str],
        session: str | None = None,
        *,
        timeout: float | None = None,
        _skip_handshake: bool = False,
    ) -> dict[str, Any]:
        if not _skip_handshake and not self._handshake_exempt(args):
            self._ensure_skill_handshake()
        argv = [self._executable(), "--format", "json"]
        if session:
            argv.extend(["--session", str(session)])
        argv.extend(str(arg) for arg in args)
        try:
            completed = self._runner(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, min(float(timeout or self.timeout_seconds), 300.0)),
                shell=False,
            )
        except FileNotFoundError as exc:
            raise BrowserActError("BrowserAct executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise BrowserActError(
                "BrowserAct command timed out; do not blindly retry a mutation"
            ) from exc
        except OSError as exc:
            raise BrowserActError(f"BrowserAct could not start: {exc}") from exc

        # A small convenience for deterministic test/integration runners that
        # return a parsed mapping directly instead of CompletedProcess.
        if isinstance(completed, Mapping):
            payload: Any = dict(completed)
            returncode = 0
            stdout = stderr = ""
        else:
            stdout = _redact_cli_text(str(getattr(completed, "stdout", "") or ""))
            stderr = _redact_cli_text(str(getattr(completed, "stderr", "") or ""))
            try:
                returncode = int(getattr(completed, "returncode", 0) or 0)
            except (TypeError, ValueError):
                returncode = 0
            try:
                payload = json.loads(stdout) if stdout else {"ok": returncode == 0, "error": stderr}
            except (TypeError, ValueError):
                payload = {"ok": returncode == 0, "text": stdout or stderr}
        payload = (
            {"ok": returncode == 0, "result": payload}
            if not isinstance(payload, Mapping)
            else dict(payload)
        )
        if returncode != 0 or payload.get("ok") is False or payload.get("success") is False:
            detail = str(payload.get("error") or stderr or stdout or "BrowserAct command failed")
            raise BrowserActError(_truncate(_redact_cli_text(detail), 4_000))
        return _bounded(dict(payload), self.max_output_chars)

    @staticmethod
    def _validate_session(value: str) -> str:
        if not isinstance(value, str) or not _SESSION_RE.fullmatch(value):
            raise BrowserActError("Invalid BrowserAct session handle")
        return value

    def _require_active_session(self, requested: Any = None) -> str:
        if not self.session:
            raise BrowserActError("No BrowserAct session is open; call action='open' first")
        if requested not in (None, ""):
            requested_name = self._validate_session(str(requested))
            if requested_name != self.session:
                raise BrowserActError("The supplied BrowserAct session is not owned by this navigator")
        return self.session

    def _validate_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value or any(ord(char) < 32 for char in value):
            raise BrowserActError("BrowserAct URL is empty or contains control characters")
        if self.allow_about_blank and value.lower() in {"about:blank", "about:blank#"}:
            if self.require_domain_allowlist:
                raise BrowserActError("about:blank is disabled when a domain allowlist is required")
            return "about:blank"
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
        except ValueError as exc:
            raise BrowserActError("Invalid BrowserAct URL") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise BrowserActError("BrowserAct navigation only accepts http/https URLs")
        if parsed.username or parsed.password:
            raise BrowserActError("BrowserAct URLs cannot contain credentials")
        if self.require_domain_allowlist and not self.allowed_domains:
            raise BrowserActError(
                "BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST is enabled but no domains are configured"
            )
        if not _domain_allowed(hostname, self.allowed_domains):
            raise BrowserActError(f"BrowserAct domain is not in the configured allowlist: {hostname}")
        if not self.allow_private_networks and _host_has_private_address(hostname):
            raise BrowserActError("Private/local BrowserAct targets are disabled")
        return value

    @staticmethod
    def _validate_index(value: Any) -> str:
        if isinstance(value, bool):
            raise BrowserActError("BrowserAct element index must be a positive integer")
        text = str(value)
        if not _INDEX_RE.fullmatch(text):
            raise BrowserActError("BrowserAct element index must be a positive integer from the current state")
        return text

    @staticmethod
    def _validate_selector(value: Any) -> str:
        selector = str(value or "").strip()
        if not selector or len(selector) > 500 or any(ord(char) < 32 for char in selector):
            raise BrowserActError("BrowserAct selector must be a non-empty short CSS selector")
        return _reject_cli_option(selector, "selector")

    def _validate_text(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            raise BrowserActError("BrowserAct input text must not be empty")
        if len(text) > self.max_input_chars:
            raise BrowserActError(
                f"BrowserAct input exceeds the configured limit of {self.max_input_chars} characters"
            )
        if "\x00" in text:
            raise BrowserActError("BrowserAct input contains an invalid null byte")
        return _reject_cli_option(text, "input text")

    @staticmethod
    def _validate_option(value: Any) -> str:
        option = str(value or "").strip()
        if not option or len(option) > 500 or "\x00" in option:
            raise BrowserActError("BrowserAct select option must be a non-empty short value")
        return _reject_cli_option(option, "select option")

    @staticmethod
    def _validate_keys(value: Any) -> str:
        keys = str(value or "").strip()
        if not _KEYS_RE.fullmatch(keys):
            raise BrowserActError("BrowserAct keys contain unsupported characters")
        return _reject_cli_option(keys, "keys")

    @staticmethod
    def _validate_direction(value: Any) -> str:
        direction = str(value or "").strip().lower()
        if direction not in {"up", "down"}:
            raise BrowserActError("BrowserAct scroll direction must be 'up' or 'down'")
        return direction

    @staticmethod
    def _validate_amount(value: Any) -> int:
        if isinstance(value, bool):
            raise BrowserActError("BrowserAct scroll amount must be a positive integer")
        try:
            amount = int(value)
        except (TypeError, ValueError) as exc:
            raise BrowserActError("BrowserAct scroll amount must be a positive integer") from exc
        if amount < 1 or amount > 20_000:
            raise BrowserActError("BrowserAct scroll amount must be between 1 and 20000")
        return amount

    def _new_token(self) -> str:
        return uuid.uuid4().hex

    def _state_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        value = payload.get("state", payload)
        return {
            "ok": True,
            "session": self.session,
            "state_token": self.state_token,
            "state": _bounded(value, self.max_state_chars),
        }

    def _refresh_locked(self) -> dict[str, Any]:
        if not self.session:
            raise BrowserActError("No BrowserAct session is open")
        # A failed/ambiguous state read invalidates the previous observation;
        # only a successful read mints a replacement token.
        self.state_token = None
        payload = self._run(["state"], self.session)
        self.state_token = self._new_token()
        return self._state_payload(payload)

    def _require_token(self, token: Any) -> None:
        if not token or not self.state_token or not hmac.compare_digest(str(token), self.state_token):
            raise BrowserActError("Stale or missing BrowserAct state_token; call state again")

    def _browser(self, requested: Any = None) -> str:
        configured = str(self.browser_id or "").strip()
        requested_value = str(requested or "").strip()
        if configured:
            if requested_value and requested_value != configured:
                raise BrowserActError(
                    "The requested BrowserAct browser does not match the operator-configured BROWSERACT_BROWSER_ID"
                )
            if len(configured) > 200 or any(ord(char) < 32 for char in configured):
                raise BrowserActError("Invalid BrowserAct browser ID")
            return _reject_cli_option(configured, "browser ID")
        if requested_value and not self.allow_requested_browser:
            raise BrowserActError(
                "Browser selection is operator-controlled; set BROWSERACT_BROWSER_ID"
            )
        if requested_value:
            return _reject_cli_option(requested_value, "browser ID")
        listing = self._run(["browser", "list"])
        raw = listing.get("browsers")
        if not isinstance(raw, list):
            raw = listing.get("items") if isinstance(listing.get("items"), list) else []
        browsers = [item for item in raw if isinstance(item, Mapping)]
        if len(browsers) == 1 and self.auto_select_single:
            browser_id = str(browsers[0].get("id", "")).strip()
            if browser_id:
                return _reject_cli_option(browser_id, "browser ID")
        if not browsers:
            raise BrowserActError(
                "No BrowserAct browser is configured; set BROWSERACT_BROWSER_ID"
            )
        raise BrowserActError(
            "Multiple BrowserAct browsers exist; pass browser_id explicitly or set BROWSERACT_BROWSER_ID"
        )

    def _target_args(
        self,
        command: str,
        index: Any = None,
        selector: Any = None,
        *,
        option: str | None = None,
    ) -> list[str]:
        if index is not None:
            args = [command, self._validate_index(index)]
            if option is not None:
                args.append(option)
            return args
        if selector not in (None, ""):
            args = [command, "--selector", self._validate_selector(selector)]
            if option is not None and command == "select":
                args.extend(["--option", option])
            return args
        raise BrowserActError(f"BrowserAct {command} requires an element index or selector")

    def _mutate_locked(self, args: list[str], state_token: Any) -> dict[str, Any]:
        self._require_token(state_token)
        # Invalidate before starting the subprocess.  A timeout can leave the
        # remote page changed, so a blind retry would be unsafe.
        self.state_token = None
        action_result = self._run(args, self.session)
        try:
            response = self._refresh_locked()
        except BrowserActError as exc:
            return {
                "ok": False,
                "session": self.session,
                "state_token": None,
                "error": f"BrowserAct action completed, but fresh state could not be read: {exc}",
                "action_result": _bounded(action_result, self.max_state_chars),
            }
        response["action_result"] = _bounded(action_result, self.max_state_chars)
        return response

    # ------------------------------------------------------------------
    # Constrained action surface
    # ------------------------------------------------------------------
    def _execute_locked(self, args: Mapping[str, Any]) -> str:
        action = _normalise_action(args.get("action"))
        if action == "diagnostics":
            result: dict[str, Any] = {"ok": True, "enabled": True}
            try:
                result["version"] = self._run(["--version"])
            except BrowserActError as exc:
                result["version_error"] = str(exc)
            try:
                result["browsers"] = self._run(["browser", "list"])
            except BrowserActError as exc:
                result["browsers_error"] = str(exc)
            return _dump(result, self.max_output_chars)
        if action in {"list_browsers", "browsers"}:
            return _dump(self._run(["browser", "list"]), self.max_output_chars)
        if action == "stealth_extract":
            if not self.allow_stealth_extract:
                raise BrowserActError("BrowserAct stealth extraction is disabled")
            url = self._validate_url(str(args.get("url", "")))
            content_type = str(
                args.get("content_type", args.get("kind", "markdown"))
            ).lower()
            if content_type not in {"markdown", "html"}:
                raise BrowserActError("BrowserAct content_type must be markdown or html")
            try:
                timeout = max(5, min(int(args.get("timeout_seconds", 60)), 180))
            except (TypeError, ValueError) as exc:
                raise BrowserActError("Invalid BrowserAct stealth extraction timeout") from exc
            result = self._run(
                [
                    "stealth-extract",
                    url,
                    "--content-type",
                    content_type,
                    "--timeout",
                    str(timeout),
                ],
                timeout=min(timeout + 60, 300),
            )
            return _dump({"ok": True, "url": url, "result": result}, self.max_output_chars)

        if action == "open":
            if self.session:
                raise BrowserActError("A BrowserAct session is already open; close it before opening another")
            url = self._validate_url(str(args.get("url", "")))
            browser = self._browser(args.get("browser_id"))
            name = f"ufo-gx10-{os.getpid()}-{uuid.uuid4().hex[:10]}"
            # Claim the generated handle before starting the subprocess.  If
            # the CLI times out after creating the remote session, cleanup can
            # still attempt to close it instead of orphaning it.
            self.session, self.browser = name, browser
            try:
                open_result = self._run(
                    ["browser", "open", browser, url],
                    name,
                    timeout=max(self.timeout_seconds, 300),
                )
                response = self._refresh_locked()
            except Exception:
                cleanup_succeeded = False
                try:
                    self._run(
                        ["session", "close", name],
                        timeout=min(self.timeout_seconds, 15.0),
                    )
                    cleanup_succeeded = True
                except Exception:
                    pass
                if cleanup_succeeded:
                    self.session = self.browser = self.state_token = None
                else:
                    # Keep the handle so the task shutdown path can make one
                    # explicit cleanup attempt instead of orphaning it.
                    self.state_token = None
                raise
            response["browser_id"] = browser
            response["open_result"] = _bounded(open_result, self.max_state_chars)
            return _dump(response, self.max_output_chars)

        if not self.session:
            raise BrowserActError("No BrowserAct session is open; call action='open' first")
        requested_session = args.get("session")
        if action == "state":
            self._require_active_session(requested_session)
            return _dump(self._refresh_locked(), self.max_output_chars)
        if action == "close":
            self._require_active_session(requested_session)
            name = self.session
            try:
                close_result = self._run(
                    ["session", "close", name], timeout=min(self.timeout_seconds, 15.0)
                )
            except BrowserActError as exc:
                detail = str(exc)
                already_closed = any(
                    marker in detail.lower()
                    for marker in ("not found", "not_found", "already closed", "does not exist", "unknown session", "404")
                )
                if already_closed:
                    self.session = self.browser = self.state_token = None
                    return _dump(
                        {"ok": True, "session": name, "already_closed": True},
                        self.max_output_chars,
                    )
                # Keep ownership on an ambiguous/auth/network failure so the
                # caller can inspect diagnostics or retry cleanup safely.
                return _dump(
                    {"ok": False, "session": name, "error": detail},
                    self.max_output_chars,
                )
            self.session = self.browser = self.state_token = None
            return _dump({"ok": True, "session": name, "close_result": close_result}, self.max_output_chars)
        if action in {"get", "get_markdown"}:
            self._require_active_session(requested_session)
            kind = "markdown" if action == "get_markdown" else str(args.get("kind", "markdown")).lower()
            if kind not in {"title", "markdown", "text", "value", "html"}:
                raise BrowserActError("Unsupported BrowserAct get kind")
            if kind == "title" and (
                args.get("index") is not None or args.get("selector") not in (None, "")
            ):
                raise BrowserActError("BrowserAct get title does not accept an index or selector")
            if kind == "markdown" and args.get("selector") not in (None, ""):
                raise BrowserActError("BrowserAct get markdown does not accept a selector")
            argv = ["get", kind]
            if kind in {"markdown", "html", "text", "value"}:
                if args.get("index") is not None:
                    argv.append(self._validate_index(args.get("index")))
                elif args.get("selector") not in (None, ""):
                    argv.extend(["--selector", self._validate_selector(args.get("selector"))])
                elif kind in {"text", "value"}:
                    raise BrowserActError(f"BrowserAct get {kind} requires an index or selector")
            return _dump(
                {
                    "ok": True,
                    "session": self.session,
                    "kind": kind,
                    "result": self._run(argv, self.session),
                },
                self.max_output_chars,
            )
        if action == "screenshot":
            self._require_active_session(requested_session)
            if args.get("path"):
                raise BrowserActError("BrowserAct screenshot paths are controlled by the runner")
            argv = ["screenshot"]
            if _as_bool(args.get("full"), False):
                argv.append("--full")
            return _dump(
                {"ok": True, "session": self.session, "result": self._run(argv, self.session)},
                self.max_output_chars,
            )
        if action == "wait":
            self._require_active_session(requested_session)
            selector = args.get("selector")
            if args.get("state_token"):
                self._require_token(args.get("state_token"))
            try:
                timeout_ms = max(100, min(int(args.get("timeout_ms", 10_000)), 120_000))
            except (TypeError, ValueError) as exc:
                raise BrowserActError("Invalid BrowserAct wait timeout") from exc
            if selector not in (None, ""):
                argv = [
                    "wait",
                    "selector",
                    "--selector",
                    self._validate_selector(selector),
                    "--state",
                    "visible",
                    "--timeout",
                    str(timeout_ms),
                ]
            else:
                argv = ["wait", "stable", "--timeout", str(timeout_ms)]
            self.state_token = None
            action_result = self._run(
                argv,
                self.session,
                timeout=min(timeout_ms / 1000 + 30, 300),
            )
            try:
                response = self._refresh_locked()
            except BrowserActError as exc:
                return _dump(
                    {
                        "ok": False,
                        "session": self.session,
                        "state_token": None,
                        "error": f"BrowserAct wait completed, but fresh state could not be read: {exc}",
                        "action_result": _bounded(action_result, self.max_state_chars),
                    },
                    self.max_output_chars,
                )
            response["action_result"] = _bounded(action_result, self.max_state_chars)
            return _dump(response, self.max_output_chars)

        self._require_active_session(requested_session)
        if action in _MUTATIONS:
            # Check freshness before validating or constructing any target
            # argv.  A stale observation must never be usable merely because
            # its index/selector happens to be syntactically valid.
            self._require_token(args.get("state_token"))
        if action == "navigate":
            argv = ["navigate", self._validate_url(str(args.get("url", "")))]
        elif action == "click":
            argv = self._target_args("click", args.get("index"), args.get("selector"))
        elif action == "input":
            value = self._validate_text(args.get("text"))
            mode = str(args.get("mode", "fill")).lower()
            if mode not in {"fill", "append"}:
                raise BrowserActError("BrowserAct input mode must be 'fill' or 'append'")
            if args.get("index") is not None:
                argv = ["input", self._validate_index(args.get("index")), value, "--mode", mode]
            elif args.get("selector") not in (None, ""):
                argv = [
                    "input",
                    "--selector",
                    self._validate_selector(args.get("selector")),
                    "--text",
                    value,
                    "--mode",
                    mode,
                ]
            else:
                raise BrowserActError("BrowserAct input requires an element index or selector")
        elif action == "select":
            option = self._validate_option(args.get("option"))
            argv = self._target_args(
                "select", args.get("index"), args.get("selector"), option=option
            )
        elif action == "keys":
            argv = ["keys", self._validate_keys(args.get("keys"))]
        elif action == "scroll":
            argv = ["scroll", self._validate_direction(args.get("direction"))]
            if args.get("amount") is not None:
                argv.extend(["--amount", str(self._validate_amount(args.get("amount")))])
        elif action in {"scrollintoview", "scroll_into_view"}:
            argv = ["scrollintoview", "--selector", self._validate_selector(args.get("selector"))]
        else:
            raise BrowserActError(f"Unsupported BrowserAct action: {action}")
        return _dump(self._mutate_locked(argv, args.get("state_token")), self.max_output_chars)

    def execute(self, args: Mapping[str, Any]) -> str:
        """Execute one BrowserAct operation and return bounded JSON text."""

        if not isinstance(args, Mapping):
            raise BrowserActError("BrowserAct arguments must be a JSON object")
        with self._lock:
            return self._execute_locked(args)

    def close(self) -> str:
        """Close the owned session, if any; safe to call during shutdown."""

        with self._lock:
            if not self.session:
                return _dump({"ok": True, "already_closed": True}, self.max_output_chars)
            return self._execute_locked({"action": "close", "session": self.session})


__all__ = ["BrowserActError", "BrowserActNavigator", "is_mutation"]
