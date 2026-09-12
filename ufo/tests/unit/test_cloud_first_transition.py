"""
Test Suite for UFO Cloud-First Transition, System Guardian,
Continuous Learner, and UI-TARS Visual Computer Use Bridge.
"""

import os
import sys
import json
import tempfile
import pytest
from pathlib import Path

# Ensure repo root is on sys.path
UFO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(UFO_ROOT) not in sys.path:
    sys.path.insert(0, str(UFO_ROOT))

import yaml
from ufo.config.config_loader import get_ufo_config
from ufo.automator.ui_tars_bridge import UITarsBridge
from ufo.fleet.system_guardian import SystemGuardian
from ufo.learner.continuous_learner import ContinuousLearner


class TestCloudFirstTransition:
    """Validate that agent routing is cloud-first non-Gemini."""

    def test_agents_yaml_has_claude_primary(self):
        config_path = UFO_ROOT / "config" / "ufo" / "agents.yaml"
        assert config_path.exists(), "agents.yaml must exist"
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        host_agent = config.get("HOST_AGENT", {})
        app_agent = config.get("APP_AGENT", {})
        backup_agent = config.get("BACKUP_AGENT", {})
        eval_agent = config.get("EVALUATION_AGENT", {})

        # Primary agents must be Claude 3.7 Sonnet (Anthropic API / LiteLLM)
        assert "claude-3-7-sonnet" in host_agent.get("API_MODEL", "").lower(), "HOST_AGENT must use claude-3-7-sonnet"
        assert "claude-3-7-sonnet" in app_agent.get("API_MODEL", "").lower(), "APP_AGENT must use claude-3-7-sonnet"
        
        # Verify no Gemini models in primary host/app
        assert "gemini" not in host_agent.get("API_MODEL", "").lower()
        assert "gemini" not in app_agent.get("API_MODEL", "").lower()

        # Backup is OpenAI GPT-4o
        assert "gpt-4o" in backup_agent.get("API_MODEL", "").lower()

        # Evaluation is DeepSeek Reasoner
        assert "deepseek" in eval_agent.get("API_MODEL", "").lower()

    def test_litellm_config_models(self):
        litellm_path = UFO_ROOT / "litellm_config.yaml"
        assert litellm_path.exists(), "litellm_config.yaml must exist"
        
        content = litellm_path.read_text(encoding="utf-8")
        assert "claude-3-7-sonnet" in content
        assert "deepseek-r1" in content


class TestUITarsBridge:
    """Validate UI-TARS action token parser and coordinate translation."""

    def setup_method(self):
        self.bridge = UITarsBridge(screen_width=1920, screen_height=1080)

    def test_parse_click_action(self):
        action_text = "click(start_box='(500, 500)')"
        actions = self.bridge.parse_action_string(action_text)
        assert len(actions) == 1
        act = actions[0]
        assert act["action"] == "click"
        # 500 / 1000 * 1920 = 960, 500 / 1000 * 1080 = 540
        assert act["x"] == 960
        assert act["y"] == 540
        assert act["button"] == "left"

    def test_parse_right_click_and_double_click(self):
        r_text = "right_click(start_box='(100, 200)')"
        r_actions = self.bridge.parse_action_string(r_text)
        assert r_actions[0]["action"] == "right_click"
        assert r_actions[0]["button"] == "right"

        d_text = "double_click(start_box='(300, 400)')"
        d_actions = self.bridge.parse_action_string(d_text)
        assert d_actions[0]["action"] == "double_click"

    def test_parse_type_and_hotkey(self):
        type_text = "type(content='Hello World')"
        t_actions = self.bridge.parse_action_string(type_text)
        assert t_actions[0]["action"] == "type"
        assert t_actions[0]["text"] == "Hello World"

        hotkey_text = "hotkey(key='ctrl+c')"
        h_actions = self.bridge.parse_action_string(hotkey_text)
        assert h_actions[0]["action"] == "hotkey"
        assert h_actions[0]["key"] == "ctrl+c"

    def test_parse_drag_action(self):
        drag_text = "drag(start_box='(100, 100)', end_box='(500, 500)')"
        d_actions = self.bridge.parse_action_string(drag_text)
        assert d_actions[0]["action"] == "drag"
        assert d_actions[0]["start_x"] == int(100 / 1000 * 1920)
        assert d_actions[0]["end_x"] == int(500 / 1000 * 1920)

    def test_parse_compound_actions(self):
        text = "click(start_box='(200, 300)'); type(content='BankFidelity'); hotkey(key='enter')"
        actions = self.bridge.parse_action_string(text)
        assert len(actions) == 3
        assert actions[0]["action"] == "click"
        assert actions[1]["action"] == "type"
        assert actions[2]["action"] == "hotkey"


class TestSystemGuardian:
    """Validate 24/7 staying alive guardian diagnostic routines."""

    def test_guardian_diagnostics(self):
        guardian = SystemGuardian(ufo_root=str(UFO_ROOT))
        
        # Test clean stale temp files
        cleaned = guardian.scrub_stale_temp_files(max_age_hours=24.0)
        assert isinstance(cleaned, int)

        # Test port collisions check
        conflicts = guardian.check_and_resolve_port_conflicts()
        assert isinstance(conflicts, list)

        # Test hung applications inspection
        hung = guardian.repair_hung_applications()
        assert isinstance(hung, list)

        # Test desktop focus check and recovery
        focus_status = guardian.verify_and_restore_desktop_focus()
        assert isinstance(focus_status, dict)
        assert "foreground_hwnd" in focus_status

        # Test full single sweep
        sweep = guardian.run_single_sweep()
        assert isinstance(sweep, dict)
        assert "timestamp" in sweep


class TestContinuousLearner:
    """Validate experience harvesting, recipe saving, and querying."""

    def test_learner_harvest_and_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            learner = ContinuousLearner(ufo_root=str(tmp_root))

            # Simulate a successful session log directory
            task_log_dir = tmp_root / "logs" / "session_2026_test"
            task_log_dir.mkdir(parents=True, exist_ok=True)

            # Create result.json and step_1.json for the session
            result_data = {
                "status": "success",
                "output": "Successfully typed BankFidelity in Notepad",
                "application": "Notepad"
            }
            (task_log_dir / "result.json").write_text(json.dumps(result_data), encoding="utf-8")

            action_data = {
                "step": 1,
                "application": "Notepad",
                "request": "Open Notepad and type BankFidelity",
                "sub_actions": [
                    {"action": "click", "control_label": "Text Editor", "value": ""},
                    {"action": "type", "control_label": "Text Editor", "value": "BankFidelity"}
                ],
                "status": "success"
            }
            (task_log_dir / "step_1.json").write_text(json.dumps(action_data), encoding="utf-8")

            # Run harvest
            stats = learner.harvest_all_logs()
            assert stats["processed"] >= 1
            assert stats["successful"] >= 1

            # Query recipes
            recipes = learner.find_recipes_for_task("Open Notepad and type BankFidelity", app_name="Notepad")
            assert len(recipes) >= 1
            assert recipes[0]["app"] == "Notepad"
            assert len(recipes[0]["steps"]) == 2


class TestMCPLocalServers:
    """Validate that local MCP server factories create instances and export valid tools."""

    @pytest.mark.asyncio
    async def test_file_system_mcp_server(self):
        from ufo.client.mcp.local_servers.file_system_mcp_server import create_file_system_mcp_server
        server = create_file_system_mcp_server()
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "read_file" in names
        assert "write_file" in names
        assert "list_directory" in names
        assert "grep_files" in names

    @pytest.mark.asyncio
    async def test_web_research_mcp_server(self):
        from ufo.client.mcp.local_servers.web_research_mcp_server import create_web_research_mcp_server
        server = create_web_research_mcp_server()
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "fetch_url" in names
        assert "search_web" in names

    @pytest.mark.asyncio
    async def test_ui_tars_mcp_server(self):
        from ufo.client.mcp.local_servers.ui_tars_mcp_server import create_ui_tars_mcp_server
        server = create_ui_tars_mcp_server()
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "visual_coordinate_click" in names
        assert "visual_type_text" in names
        assert "execute_visual_action_token" in names

    @pytest.mark.asyncio
    async def test_cli_mcp_server(self):
        from ufo.client.mcp.local_servers.cli_mcp_server import create_cli_mcp_server
        server = create_cli_mcp_server()
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "run_shell" in names
        assert "execute_command" in names

    @pytest.mark.asyncio
    async def test_pdf_reader_mcp_server(self):
        from ufo.client.mcp.local_servers.pdf_reader_mcp_server import create_pdf_reader_mcp_server
        server = create_pdf_reader_mcp_server()
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "extract_pdf_text" in names
        assert "list_pdfs_in_directory" in names
