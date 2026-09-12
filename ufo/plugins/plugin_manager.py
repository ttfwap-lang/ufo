"""
Plugin Manager — Application-specific API execution hooks for GUI bypass.

When LEGACY_FEATURES.ENABLE_API_PLUGINS is true, the AppAgent checks this
registry before attempting GUI automation. If a direct COM/API plugin exists
for the target application (e.g., Word.Application, Excel.Application),
the action is executed via the API — faster, more reliable, and deterministic.

The plugin registry maps process names to MCP server namespaces from
mcp.yaml. This leverages the existing MCP infrastructure rather than
creating a parallel execution path.

IMPORTANT: API plugin execution is ALWAYS preferred over GUI for registered
applications, even in strict mode. GUI is only used as a fallback when
no plugin is registered or the API call fails.

Gated behind: LEGACY_FEATURES.ENABLE_API_PLUGINS in system.yaml

Usage:
    
    from ufo.plugins.plugin_manager import PluginManager

    pm = PluginManager()
    if pm.has_plugin("WINWORD.EXE"):
        result = pm.try_execute(
            process_name="WINWORD.EXE",
            action_type="type",
            payload="Hello World",
            target_control={"name": "Document"},
        )
        if result.success:
            # Skip GUI automation
            ...
"""
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
logger = logging.getLogger(__name__)

class PluginExecutionResult(BaseModel):
    """Result of a plugin API execution attempt."""
    success: bool = Field(default=False)
    plugin_used: str = Field(default='', description='Which MCP server handled it')
    result_data: Optional[str] = Field(None, description='API return value if any')
    error: Optional[str] = Field(None, description='Error message if failed')
    fell_back_to_gui: bool = Field(default=False)

class PluginRegistration(BaseModel):
    """Registration entry mapping a process name to its MCP server."""
    process_name: str = Field(..., description='Process name (e.g., WINWORD.EXE)')
    mcp_namespace: str = Field(..., description='MCP server namespace from mcp.yaml')
    supported_actions: List[str] = Field(default_factory=lambda: ['type', 'click', 'hotkey', 'read'], description='Action types this plugin supports')
    description: str = Field(default='')
_BUILTIN_PLUGINS: List[PluginRegistration] = [PluginRegistration(process_name='WINWORD.EXE', mcp_namespace='server_5_WordCOMExecutor', supported_actions=['type', 'read', 'format', 'save', 'navigate'], description='Microsoft Word COM automation via MCP'), PluginRegistration(process_name='EXCEL.EXE', mcp_namespace='excel_wincom_mcp_server', supported_actions=['type', 'read', 'formula', 'save', 'navigate'], description='Microsoft Excel COM automation via MCP'), PluginRegistration(process_name='POWERPNT.EXE', mcp_namespace='PowerPointCOMExecutor', supported_actions=['type', 'read', 'add_slide', 'save', 'navigate'], description='Microsoft PowerPoint COM automation via MCP')]

class PluginManager:
    """
    Registry and dispatcher for application-specific API execution plugins.

    Maps process names to MCP server namespaces. When a match is found,
    the action is dispatched to the MCP server instead of GUI automation.
    """

    def __init__(self) -> None:
        self._enabled: bool = True
        self._registry: Dict[str, PluginRegistration] = {}
        self._load_config()
        self._register_builtins()

    def _load_config(self) -> None:
        """Load plugin config from system.yaml."""
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            lf = getattr(cfg.system, 'legacy_features', None)
            if lf and isinstance(lf, dict):
                self._enabled = lf.get('ENABLE_API_PLUGINS', True)
        except Exception:
            pass

    def _register_builtins(self) -> None:
        """Register built-in plugins from the static registry."""
        if not self._enabled:
            return
        for plugin in _BUILTIN_PLUGINS:
            self._registry[plugin.process_name.upper()] = plugin

    def is_enabled(self) -> bool:
        """Check if plugin execution is enabled."""
        return self._enabled

    def has_plugin(self, process_name: str) -> bool:
        """Check if a plugin is registered for the given process."""
        if not self._enabled:
            return False
        return process_name.upper() in self._registry

    def get_plugin(self, process_name: str) -> Optional[PluginRegistration]:
        """Get the plugin registration for a process."""
        return self._registry.get(process_name.upper())

    def register(self, plugin: PluginRegistration) -> None:
        """Register a new plugin at runtime."""
        self._registry[plugin.process_name.upper()] = plugin
        logger.info(f'Registered plugin: {plugin.process_name} → {plugin.mcp_namespace}')

    def list_plugins(self) -> List[PluginRegistration]:
        """List all registered plugins."""
        return list(self._registry.values())

    def try_execute(self, process_name: str, action_type: str, payload: Optional[str]=None, target_control: Optional[Dict[str, Any]]=None) -> PluginExecutionResult:
        """
        Attempt to execute an action via API plugin instead of GUI.

        :param process_name: Target process (e.g., "WINWORD.EXE").
        :param action_type: Action type (click, type, hotkey, etc.).
        :param payload: Text or key sequence payload.
        :param target_control: UIA control selector dict.
        :return: PluginExecutionResult.
        """
        if not self._enabled:
            return PluginExecutionResult(success=False, error='API plugins disabled in config.', fell_back_to_gui=True)
        plugin = self.get_plugin(process_name)
        if plugin is None:
            return PluginExecutionResult(success=False, error=f'No plugin registered for {process_name}.', fell_back_to_gui=True)
        if action_type not in plugin.supported_actions:
            logger.debug(f"Plugin {plugin.mcp_namespace} doesn't support action '{action_type}'. Falling back to GUI.")
            return PluginExecutionResult(success=False, plugin_used=plugin.mcp_namespace, error=f"Action '{action_type}' not supported by plugin.", fell_back_to_gui=True)
        try:
            result = self._dispatch_to_mcp(plugin, action_type, payload, target_control)
            return result
        except Exception as e:
            logger.warning(f'Plugin execution failed for {process_name}: {e}. Falling back to GUI.')
            return PluginExecutionResult(success=False, plugin_used=plugin.mcp_namespace, error=str(e), fell_back_to_gui=True)

    def _dispatch_to_mcp(self, plugin: PluginRegistration, action_type: str, payload: Optional[str], target_control: Optional[Dict[str, Any]]) -> PluginExecutionResult:
        """
        Dispatch an action to the MCP server for API execution.

        This integrates with the existing MCP client infrastructure
        rather than creating a parallel execution path.
        """
        try:
            from ufo.client.mcp.mcp_client_manager import MCPClientManager
            manager = MCPClientManager.get_instance()
            client = manager.get_client(plugin.mcp_namespace)
            if client is None:
                return PluginExecutionResult(success=False, plugin_used=plugin.mcp_namespace, error=f"MCP client '{plugin.mcp_namespace}' not available.", fell_back_to_gui=True)
            tool_name = self._map_action_to_tool(plugin, action_type)
            tool_args = {'action_type': action_type, 'payload': payload or ''}
            if target_control:
                tool_args['target'] = target_control
            result = client.call_tool(tool_name, tool_args)
            logger.info(f'Plugin execution succeeded: {plugin.process_name} → {plugin.mcp_namespace}.{tool_name}')
            return PluginExecutionResult(success=True, plugin_used=plugin.mcp_namespace, result_data=str(result) if result else None)
        except ImportError:
            return PluginExecutionResult(success=False, plugin_used=plugin.mcp_namespace, error='MCP client infrastructure not available.', fell_back_to_gui=True)
        except Exception as e:
            return PluginExecutionResult(success=False, plugin_used=plugin.mcp_namespace, error=f'MCP dispatch failed: {e}', fell_back_to_gui=True)

    @staticmethod
    def _map_action_to_tool(plugin: PluginRegistration, action_type: str) -> str:
        """Map an action type to the corresponding MCP tool name."""
        action_tool_map = {'type': 'insert_text', 'read': 'read_content', 'format': 'format_text', 'save': 'save_document', 'navigate': 'navigate_to', 'formula': 'set_cell_formula', 'add_slide': 'add_slide', 'click': 'click_element', 'hotkey': 'send_hotkey'}
        return action_tool_map.get(action_type, action_type)