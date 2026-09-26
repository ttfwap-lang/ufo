"""Safe, constrained adapter for the BrowserAct Agent CLI.

BrowserAct is intentionally invoked as a subprocess instead of through a
shell.  The model never supplies a command string: callers pass one of the
small, typed command groups exposed by :mod:`browseract_mcp_server`, and this
module turns those into a fixed argv list.

The CLI is installed separately (``uv tool install browser-act-cli --python
3.12``) because the package requires Python 3.12 while UFO itself supports
Python 3.10+.  ``BROWSERACT_CLI_PATH`` can be used when the tool directory is
not on ``PATH``.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class BrowserActError(RuntimeError):
    """A safe, user-facing BrowserAct command error."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.payload = dict(payload or {})

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable error without exposing process internals."""
        result: dict[str, Any] = {
            "ok": False,
            "error": str(self),
            "error_type": type(self).__name__,
        }
        if self.returncode is not None:
            result["returncode"] = self.returncode
        for key in ("error_code", "error_name", "error_data"):
            if key in self.payload:
                result[key] = self.payload[key]
        return result


class BrowserActNotFoundError(BrowserActError):
    """Raised when the BrowserAct executable cannot be located."""


class BrowserActTimeoutError(BrowserActError):
    """Raised when a BrowserAct command exceeds its configured timeout."""


@dataclass(frozen=True)
class BrowserActConfig:
    """Runtime settings for the low-level adapter.

    Values are intentionally conservative.  The MCP layer can opt into
    private network targets explicitly, but never receives an arbitrary shell
    command or an arbitrary executable argument.
    """

    cli_path: str | None = None
    timeout_seconds: float = 300.0
    max_output_chars: int = 30_000
    allowed_domains: tuple[str, ...] = ()
    allow_private_networks: bool = False
    allow_about_blank: bool = True

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None = None) -> BrowserActConfig:
        """Build settings from a UFO ``BROWSERACT`` mapping.

        Environment variables are deliberately handled by the MCP layer so
        that this class remains easy to test and has no hidden global state.
        """
        raw = dict(values or {})

        def _first(*keys: str, default: Any = None) -> Any:
            for key in keys:
                value = raw.get(key)
                if value not in (None, ""):
                    return value
            return default

        def _placeholder(value: Any) -> Any:
            if isinstance(value, str) and ("${" in value or value.startswith("$")):
                return None
            return value

        domains = _placeholder(_first("ALLOWED_DOMAINS", "allowed_domains", default=())) or ()
        if isinstance(domains, str):
            domains = tuple(item.strip() for item in domains.split(",") if item.strip())
        else:
            domains = tuple(str(item).strip() for item in domains if str(item).strip())

        try:
            timeout = float(_first("COMMAND_TIMEOUT_SECONDS", "command_timeout_seconds", default=300.0))
        except (TypeError, ValueError):
            timeout = 300.0
        try:
            max_output = int(_first("MAX_OUTPUT_CHARS", "max_output_chars", default=30_000))
        except (TypeError, ValueError):
            max_output = 30_000

        def _as_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled", ""}

        return cls(
            cli_path=_placeholder(_first("CLI_PATH", "cli_path", default=None)),
            timeout_seconds=max(1.0, min(timeout, 300.0)),
            max_output_chars=max(1_000, min(max_output, 500_000)),
            allowed_domains=domains,
            allow_private_networks=_as_bool(_first("ALLOW_PRIVATE_NETWORKS", "allow_private_networks"), False),
            allow_about_blank=_as_bool(_first("ALLOW_ABOUT_BLANK", "allow_about_blank"), True),
        )


def _normalise_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if value.startswith("*."):
        value = value[2:]
    return value


def _domain_allowed(hostname: str, allowed_domains: Iterable[str]) -> bool:
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
        ipaddress.ip_address(lowered)
        return _is_private_address(lowered)
    except ValueError:
        pass
    try:
        addresses = socket.getaddrinfo(lowered, None, type=socket.SOCK_STREAM)
    except OSError:
        # DNS failure is handled by the browser.  Do not turn a normal public
        # hostname into a false positive merely because the local resolver is
        # temporarily unavailable.
        return False
    return any(_is_private_address(str(info[4][0])) for info in addresses)


def validate_navigation_url(
    url: str,
    *,
    allowed_domains: Iterable[str] = (),
    allow_private_networks: bool = False,
    allow_about_blank: bool = True,
) -> str:
    """Validate and normalize a URL before handing it to BrowserAct.

    Only ``http`` and ``https`` are accepted by default.  ``about:blank`` is
    useful for a fresh BrowserAct tab and is explicitly opt-out-able.  File,
    data, javascript, and shell-like URLs are never accepted.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("BrowserAct URL must be a non-empty string")
    value = url.strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError("BrowserAct URL contains control characters")
    if allow_about_blank and value.lower() in {"about:blank", "about:blank#"}:
        return "about:blank"

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("BrowserAct navigation allows only http://, https://, or about:blank")
    if not parsed.hostname:
        raise ValueError("BrowserAct URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("BrowserAct URLs must not contain embedded credentials")
    if not _domain_allowed(parsed.hostname, allowed_domains):
        raise ValueError(f"BrowserAct domain is not in the configured allowlist: {parsed.hostname}")
    if not allow_private_networks and _host_has_private_address(parsed.hostname):
        raise ValueError("BrowserAct navigation to private/local network addresses is disabled")
    return value


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[… truncated; {len(value) - limit} characters omitted]"


def _bounded_output(value: Any, limit: int) -> Any:
    """Bound and redact successful CLI payloads before returning them."""
    if isinstance(value, str):
        return _truncate(_redact_cli_text(value), limit)
    if isinstance(value, list):
        result = []
        remaining = limit
        for item in value:
            if remaining <= 0:
                break
            bounded = _bounded_output(item, remaining)
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
            bounded = _bounded_output(item, remaining)
            result[str(key)] = bounded
            remaining -= len(str(bounded))
        return result
    return value


def _redact_cli_text(value: str) -> str:
    """Redact known local credentials if a CLI diagnostic echoes them."""
    text = value
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


def _parse_cli_output(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    stdout = stdout.strip()
    stderr = stderr.strip()
    if stdout:
        try:
            parsed = json.loads(stdout)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"ok": returncode == 0, "items": parsed}
        return {"ok": returncode == 0, "text": stdout}
    if stderr:
        return {"ok": False, "error": stderr}
    return {"ok": returncode == 0, "text": ""}


class BrowserActCLI:
    """Fixed-argv subprocess client for BrowserAct."""

    def __init__(
        self,
        config: BrowserActConfig | None = None,
        *,
        runner: Any = None,
        auto_handshake: bool | None = None,
    ) -> None:
        self.config = config or BrowserActConfig()
        # ``runner`` is injectable for deterministic tests.  It must have the
        # same signature as subprocess.run.  Test doubles do not need to emulate
        # BrowserAct's skill handshake; the real subprocess client performs it
        # lazily before the first stateful command.
        self._runner = runner or subprocess.run
        self.auto_handshake = (
            runner is None if auto_handshake is None else bool(auto_handshake)
        )
        self._handshake_ready = False
        self._handshake_lock = threading.Lock()

    def resolve_executable(self) -> str:
        """Resolve the configured executable or raise a safe setup error."""
        candidate = (self.config.cli_path or "").strip()
        if candidate:
            candidate = os.path.expandvars(os.path.expanduser(candidate))
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
            found = shutil.which(candidate)
            if found:
                return found
            raise BrowserActNotFoundError(
                f"BrowserAct CLI was not found at configured path {candidate!r}. "
                "Install it with 'uv tool install browser-act-cli --python 3.12' "
                "or set BROWSERACT_CLI_PATH."
            )
        found = shutil.which("browser-act") or shutil.which("browser-act.exe")
        if found:
            return found
        raise BrowserActNotFoundError(
            "BrowserAct CLI is not available on PATH. Install it with "
            "'uv tool install browser-act-cli --python 3.12' or set BROWSERACT_CLI_PATH."
        )

    @staticmethod
    def _handshake_exempt(args: Sequence[str]) -> bool:
        if not args:
            return True
        first = str(args[0])
        return first in {"--version", "-v", "--v", "--help", "-h", "get-skills"}

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
            main_payload = self.run(
                ["get-skills", "main"],
                timeout=min(self.config.timeout_seconds, 60.0),
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
            self.run(
                ["get-skills", "core", "--skill-version", skill_version],
                timeout=min(self.config.timeout_seconds, 60.0),
                _skip_handshake=True,
            )
            self._handshake_ready = True

    def _argv(self, args: Sequence[str], session: str | None = None) -> list[str]:
        executable = self.resolve_executable()
        argv = [executable, "--format", "json"]
        if session:
            if not isinstance(session, str) or not session.strip():
                raise ValueError("BrowserAct session must be a non-empty string")
            argv.extend(["--session", session])
        argv.extend(str(arg) for arg in args)
        return argv

    def run(
        self,
        args: Sequence[str],
        *,
        session: str | None = None,
        timeout: float | None = None,
        _skip_handshake: bool = False,
    ) -> dict[str, Any]:
        """Run one fixed BrowserAct command and return parsed JSON/text."""
        if not _skip_handshake and not self._handshake_exempt(args):
            self._ensure_skill_handshake()
        argv = self._argv(args, session=session)
        effective_timeout = min(max(float(timeout or self.config.timeout_seconds), 1.0), 300.0)
        try:
            completed = self._runner(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise BrowserActNotFoundError("BrowserAct executable disappeared before it could be started") from exc
        except subprocess.TimeoutExpired as exc:
            raise BrowserActTimeoutError(
                f"BrowserAct command timed out after {effective_timeout:g}s; the page may have changed, so do not blindly retry mutations"
            ) from exc
        except OSError as exc:
            raise BrowserActError(f"Unable to start BrowserAct: {exc}") from exc

        returncode = int(getattr(completed, "returncode", 1) or 0)
        stdout = _redact_cli_text(str(getattr(completed, "stdout", "") or ""))
        stderr = _redact_cli_text(str(getattr(completed, "stderr", "") or ""))
        payload = _parse_cli_output(stdout, stderr, returncode)
        if returncode != 0 or payload.get("ok") is False:
            detail = str(payload.get("error") or stderr or stdout or "BrowserAct command failed")
            detail = _truncate(detail, min(self.config.max_output_chars, 4_000))
            raise BrowserActError(detail, returncode=returncode, payload=payload)
        return _bounded_output(payload, self.config.max_output_chars)

    def version(self) -> dict[str, Any]:
        """Return a small version/health payload."""
        payload = self.run(["--version"], timeout=min(self.config.timeout_seconds, 15.0))
        if "text" in payload:
            payload["version"] = str(payload["text"]).strip()
        return payload

    def browser_list(self) -> dict[str, Any]:
        return self.run(["browser", "list"])

    def session_list(self) -> dict[str, Any]:
        return self.run(["session", "list"])


__all__ = [
    "BrowserActCLI",
    "BrowserActConfig",
    "BrowserActError",
    "BrowserActNotFoundError",
    "BrowserActTimeoutError",
    "validate_navigation_url",
]
