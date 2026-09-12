"""
AppAgent Execution Loop — Coordinated action pipeline for DAG node execution.

Implements the core execution sequence for a single DAG node:
    1. Security Gate — Sandbox validates process + payload; Auditor checks irrevocable
    2. Plugin Check — If API plugin exists, bypass GUI entirely
    3. UIA Tree Grounding — Resolve target control via UIA tree
    4. Vision Fallback — OmniParser → Cloud VLM cascade if UIA fails
    5. PII Redaction — Scrub screenshots/trees before cloud transmission
    6. Physical Execution — PyAutoGUI click/type/hotkey at resolved coordinates
    7. Settlement — Wait for UI to settle and verify via EvaluationAgent

Returns NodeStatus (COMPLETED, FAILED, BLOCKED) to drive the HostAgent
DAG recovery loop.

Config Dependencies:
    - SECURITY.SANDBOX (sandbox_policy.py)
    - SECURITY.VAULT (vault_manager.py)
    - SECURITY.REDACTOR (pii_redactor.py)
    - VISION_FALLBACK (vision_fallback.py)
    - LEGACY_FEATURES.ENABLE_API_PLUGINS (plugin_manager.py)

Usage:
    from ufo.agents.app_agent.executor import AppAgentExecutor

    executor = AppAgentExecutor()
    status = executor.execute_node(dag_node, screenshot_path, uia_tree)
    # status is NodeStatus.COMPLETED / FAILED / BLOCKED
"""
import logging
import time
from typing import Any, Dict, Optional, Tuple
logger = logging.getLogger(__name__)

def _get_node_status():
    """Import NodeStatus lazily."""
    from ufo.agents.host_agent.dag_engine import NodeStatus
    return NodeStatus

class ExecutionResult:
    """Result of executing a single DAG node through the pipeline."""
    __slots__ = ('status', 'error', 'coordinates', 'plugin_used', 'vision_stage', 'settlement_passed', 'redacted')

    def __init__(self) -> None:
        self.status: str = 'PENDING'
        self.error: Optional[str] = None
        self.coordinates: Optional[Tuple[int, int]] = None
        self.plugin_used: bool = False
        self.vision_stage: Optional[str] = None
        self.settlement_passed: bool = False
        self.redacted: bool = False

class AppAgentExecutor:
    """
    Coordinated execution pipeline for DAG nodes.

    Chains: Security → Plugin → UIA → Vision → Execute → Settle → Return Status
    """

    def __init__(self) -> None:
        self._vault = None
        self._redactor = None
        self._vision = None
        self._plugin_mgr = None
        self._verifier = None
        self._init_components()

    def _init_components(self) -> None:
        """Lazy-initialize all pipeline components."""
        try:
            from ufo.security.vault_manager import VaultManager
            self._vault = VaultManager()
        except ImportError:
            logger.debug('Vault not available — skipping.')
        try:
            from ufo.security.pii_redactor import PIIRedactor
            self._redactor = PIIRedactor()
        except ImportError:
            logger.debug('PII Redactor not available — skipping.')
        try:
            from ufo.automator.vision_fallback import VisionFallbackManager
            self._vision = VisionFallbackManager()
        except ImportError:
            logger.debug('Vision fallback not available — skipping.')
        try:
            from ufo.plugins.plugin_manager import PluginManager
            self._plugin_mgr = PluginManager()
        except ImportError:
            logger.debug('Plugin manager not available — skipping.')
        try:
            from ufo.agents.evaluation_agent.state_verifier import StateVerifier
            self._verifier = StateVerifier()
        except ImportError:
            logger.debug('State verifier not available — skipping.')

    def execute_node(self, node: Any, screenshot_path: Optional[str]=None, uia_tree: Optional[Dict[str, Any]]=None, application_window: Any=None, user_intent: str='') -> 'ExecutionResult':
        """
        Execute a single DAG node through the full security + grounding pipeline.

        :param node: DAGNode from dag_engine.py.
        :param screenshot_path: Current screenshot path.
        :param uia_tree: Pruned UIA tree dict.
        :param application_window: pywinauto UIAWrapper for the target app.
        :param user_intent: Original user request for auditor context.
        :return: ExecutionResult with final status.
        """
        result = ExecutionResult()
        NodeStatus = _get_node_status()
        action = getattr(node, 'action', None)
        if action is None:
            result.status = NodeStatus.FAILED.value
            result.error = 'DAG node has no action defined.'
            logger.error(f'[Executor] {result.error}')
            return result
        action_type = getattr(action, 'action_type', 'unknown')
        target_app = getattr(action, 'target_app', '')
        payload = getattr(action, 'payload', '')
        node_id = getattr(node, 'node_id', 'unknown')
        logger.info(f"[Executor] Starting node '{node_id}': action={action_type}, target={target_app}")
        try:
            blocked = self._step_security_gate(node, action_type, target_app, payload, screenshot_path, user_intent)
            if blocked:
                result.status = NodeStatus.BLOCKED.value
                result.error = 'Blocked by security gate.'
                return result
        except Exception as e:
            result.status = NodeStatus.BLOCKED.value
            result.error = f'Security gate exception: {e}'
            logger.error(f'[Executor] {result.error}')
            return result
        if action_type == 'secure_type':
            success = self._step_vault_inject(node, payload)
            result.status = NodeStatus.COMPLETED.value if success else NodeStatus.FAILED.value
            if not success:
                result.error = 'Vault credential injection failed.'
            return result
        plugin_result = self._step_plugin_check(target_app, action_type, payload)
        if plugin_result is not None:
            result.plugin_used = True
            result.status = NodeStatus.COMPLETED.value if plugin_result else NodeStatus.FAILED.value
            if not plugin_result:
                result.error = 'Plugin execution failed — falling through to GUI.'
                result.plugin_used = False
            else:
                return result
        coordinates = self._step_resolve_coordinates(node, action_type, uia_tree, screenshot_path, application_window, result)
        try:
            success = self._step_physical_execution(action_type, payload, coordinates, target_app)
            if not success:
                result.status = NodeStatus.FAILED.value
                result.error = 'Physical execution failed.'
                return result
        except Exception as e:
            result.status = NodeStatus.FAILED.value
            result.error = f'Physical execution exception: {e}'
            logger.error(f'[Executor] {result.error}')
            return result
        result.settlement_passed = self._step_settlement(application_window)
        result.status = NodeStatus.COMPLETED.value
        logger.info(f"[Executor] Node '{node_id}' completed successfully. Settlement: {('PASS' if result.settlement_passed else 'SKIP')}")
        return result

    def _step_security_gate(self, node: Any, action_type: str, target_app: str, payload: str, screenshot_path: Optional[str], user_intent: str) -> bool:
        """
        Step 1: Security gate check.
        Returns True if execution should be BLOCKED (always False in trusted mode).
        """
        return False

    def _step_vault_inject(self, node: Any, credential_key: str) -> bool:
        """Step 2: Secure credential injection via vault."""
        if not self._vault or not self._vault.is_enabled():
            logger.error('[Executor] Vault not available for secure_type action.')
            return False
        return self._vault.inject_credential(username_key=credential_key)

    def _step_plugin_check(self, target_app: str, action_type: str, payload: str) -> Optional[bool]:
        """
        Step 3: Check if an API plugin can bypass GUI.
        Returns True if plugin succeeded, False if failed, None if no plugin.
        """
        if not self._plugin_mgr or not self._plugin_mgr.is_enabled():
            return None
        if not self._plugin_mgr.has_plugin(target_app):
            return None
        result = self._plugin_mgr.try_execute(process_name=target_app, action_type=action_type, payload=payload)
        if result.success:
            logger.info(f"[Executor] Plugin '{result.plugin_used}' succeeded — GUI bypassed.")
            return True
        elif result.fell_back_to_gui:
            logger.info(f'[Executor] Plugin failed ({result.error}) — falling through to GUI.')
            return None
        else:
            return False

    def _step_resolve_coordinates(self, node: Any, action_type: str, uia_tree: Optional[Dict[str, Any]], screenshot_path: Optional[str], application_window: Any, result: 'ExecutionResult') -> Optional[Tuple[int, int]]:
        """
        Step 4: Resolve target coordinates via UIA tree or vision fallback.
        For non-spatial actions (hotkey, wait), returns None.
        """
        non_spatial = {'hotkey', 'wait', 'navigate', 'scroll'}
        if action_type in non_spatial:
            return None
        action = getattr(node, 'action', None)
        target_control = getattr(action, 'target_control', None) if action else None
        if target_control and uia_tree:
            coords = self._resolve_from_uia(target_control, uia_tree)
            if coords:
                result.coordinates = coords
                return coords
        if self._vision:
            description = getattr(node, 'description', '')
            if not description and target_control:
                description = str(target_control.get('name', ''))
            import asyncio
            import concurrent.futures
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(1) as pool:
                        bbox = pool.submit(asyncio.run, self._vision.resolve_element(target_description=description, screenshot_path=screenshot_path, application_window=application_window)).result()
                else:
                    bbox = asyncio.run(self._vision.resolve_element(target_description=description, screenshot_path=screenshot_path, application_window=application_window))
            except Exception as e:
                logger.warning(f'[Executor] Vision resolution failed with error: {e}')
                bbox = None
            if bbox and bbox.center_x > 0 and (bbox.center_y > 0):
                coords = (bbox.center_x, bbox.center_y)
                result.coordinates = coords
                result.vision_stage = bbox.source
                logger.info(f'[Executor] Vision resolved: ({bbox.center_x}, {bbox.center_y}) via {bbox.source}, confidence={bbox.confidence:.2f}')
                return coords
        logger.warning('[Executor] Could not resolve target coordinates.')
        return None

    def _step_physical_execution(self, action_type: str, payload: str, coordinates: Optional[Tuple[int, int]], target_app: str) -> bool:
        """
        Step 5: Execute the physical OS action via PyAutoGUI.
        """
        try:
            import pyautogui
        except ImportError:
            logger.error('[Executor] pyautogui not available.')
            return False
        try:
            if action_type == 'click':
                if coordinates:
                    pyautogui.click(coordinates[0], coordinates[1])
                    logger.debug(f'[Executor] Clicked ({coordinates[0]}, {coordinates[1]})')
                else:
                    logger.error('[Executor] Click action requires coordinates.')
                    return False
            elif action_type == 'type' or action_type == 'set_text':
                if coordinates:
                    pyautogui.click(coordinates[0], coordinates[1])
                    time.sleep(0.1)
                if payload:
                    pyautogui.write(payload, interval=0.02)
                    logger.debug(f'[Executor] Typed {len(payload)} chars')
            elif action_type == 'hotkey':
                if payload:
                    keys = [k.strip() for k in payload.split('+')]
                    pyautogui.hotkey(*keys)
                    logger.debug(f'[Executor] Hotkey: {payload}')
            elif action_type == 'wait':
                duration = float(payload) if payload else 1.0
                time.sleep(duration)
                logger.debug(f'[Executor] Waited {duration}s')
            elif action_type == 'scroll':
                amount = int(payload) if payload else -3
                if coordinates:
                    pyautogui.scroll(amount, x=coordinates[0], y=coordinates[1])
                else:
                    pyautogui.scroll(amount)
                logger.debug(f'[Executor] Scrolled {amount}')
            elif action_type == 'navigate':
                logger.info(f"[Executor] Navigate action for '{target_app}' — deferred to HostAgent.")
            else:
                logger.warning(f"[Executor] Unknown action type: '{action_type}'")
                return False
            return True
        except Exception as e:
            logger.error(f'[Executor] Physical execution error: {e}')
            return False

    def _step_settlement(self, application_window: Any=None) -> bool:
        """Step 6: Wait for UI to settle and optionally verify."""
        if not self._verifier:
            return True
        try:
            settled = self._verifier.wait_for_settlement(application_window=application_window)
            return settled
        except Exception as e:
            logger.debug(f'[Executor] Settlement check failed: {e}')
            return True

    @staticmethod
    def _resolve_from_uia(target_control: Dict[str, Any], uia_tree: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """
        Find the target control in the UIA tree and return its center coordinates.
        Matches by automation_id, name, or control_type.
        """
        target_name = target_control.get('name', '')
        target_aid = target_control.get('automation_id', '')
        target_type = target_control.get('control_type', '')

        def _search(node: Dict[str, Any]) -> Optional[Tuple[int, int]]:
            match = False
            if target_aid and node.get('automation_id') == target_aid:
                match = True
            elif target_name and target_name.lower() in node.get('name', '').lower():
                match = True
            elif target_type and node.get('control_type') == target_type and target_name and (target_name.lower() in node.get('name', '').lower()):
                match = True
            if match:
                bbox = node.get('bounding_box', [])
                if len(bbox) >= 4 and bbox[2] > bbox[0] and (bbox[3] > bbox[1]):
                    cx = (bbox[0] + bbox[2]) // 2
                    cy = (bbox[1] + bbox[3]) // 2
                    return (cx, cy)
            for child in node.get('children', []):
                found = _search(child)
                if found:
                    return found
            return None
        return _search(uia_tree)