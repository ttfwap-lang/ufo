"""Tests for the fixed-argv BrowserAct adapter."""

from __future__ import annotations

import subprocess
import sys

import pytest
from ufo.automation.browseract_adapter import (
    BrowserActCLI,
    BrowserActConfig,
    BrowserActError,
    BrowserActTimeoutError,
    validate_navigation_url,
)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_builds_fixed_argv_and_never_uses_shell():
    seen = {}

    def runner(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _Completed(stdout='{"ok": true, "state": "ready"}')

    cli = BrowserActCLI(BrowserActConfig(cli_path=sys.executable), runner=runner)
    result = cli.run(["input", "2", "hello & goodbye"], session="ufo-test")

    assert result["state"] == "ready"
    assert seen["argv"] == [
        sys.executable,
        "--format",
        "json",
        "--session",
        "ufo-test",
        "input",
        "2",
        "hello & goodbye",
    ]
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["timeout"] > 0


def test_real_boundary_performs_fixed_skill_handshake_before_state():
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        if "get-skills" in argv and "main" in argv:
            return _Completed(stdout='{"ok":true,"content":"metadata:\\n  version: \\"2.0.2\\""}')
        if "get-skills" in argv and "core" in argv:
            return _Completed(stdout='{"ok":true}')
        return _Completed(stdout='{"ok":true,"state":"ready"}')

    cli = BrowserActCLI(BrowserActConfig(cli_path=sys.executable), runner=runner, auto_handshake=True)
    assert cli.run(["state"])["state"] == "ready"
    assert "get-skills" in calls[0]
    assert "get-skills" in calls[1]
    assert calls[2][-1] == "state"


def test_run_reports_nonzero_json_error():
    def runner(argv, **kwargs):
        return _Completed(returncode=1, stdout='{"ok": false, "error": "bad page"}')

    cli = BrowserActCLI(BrowserActConfig(cli_path=sys.executable), runner=runner)
    with pytest.raises(BrowserActError, match="bad page"):
        cli.run(["state"])


def test_run_turns_timeout_into_action_safe_error():
    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    cli = BrowserActCLI(BrowserActConfig(cli_path=sys.executable), runner=runner)
    with pytest.raises(BrowserActTimeoutError, match="do not blindly retry"):
        cli.run(["click", "1"])


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///tmp/a", "data:text/html,x"])
def test_navigation_rejects_non_web_schemes(url):
    with pytest.raises(ValueError):
        validate_navigation_url(url)


def test_navigation_rejects_private_targets_by_default():
    with pytest.raises(ValueError, match="private/local"):
        validate_navigation_url("http://127.0.0.1:8000")


def test_navigation_allows_private_targets_when_explicitly_enabled():
    assert validate_navigation_url("http://127.0.0.1:8000", allow_private_networks=True) == "http://127.0.0.1:8000"


def test_domain_allowlist_is_suffix_aware():
    assert validate_navigation_url("https://docs.example.com", allowed_domains=["example.com"])
    with pytest.raises(ValueError, match="allowlist"):
        validate_navigation_url("https://example.org", allowed_domains=["example.com"])


def test_boolean_strings_are_not_truthy_by_accident():
    config = BrowserActConfig.from_mapping({"ALLOW_PRIVATE_NETWORKS": "false", "ALLOW_ABOUT_BLANK": "0"})
    assert config.allow_private_networks is False
    assert config.allow_about_blank is False
