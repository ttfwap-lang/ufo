"""
EvaluationAgent State Verifier — Hybrid structural UI settlement + Cloud VLM diffing.

Solves the "infinite pixel-polling" problem by using structural UIA checks
(COM element count stability, foreground HWND validation, control enablement)
instead of pixel convergence. Enforces a strict 5.0-second hard timeout.

After settlement, optionally sends pre/post screenshots to a Cloud VLM
for semantic visual diffing to confirm the action actually achieved
the intended result.

Architecture:
  1. Structural Settlement: Monitor UIA descendants count for stability
     (5 consecutive identical counts at 100ms intervals = settled).
  2. Foreground HWND Check: Verify the expected window is still foreground.
  3. Control Enablement Check: Verify the target control is enabled post-action.
  4. Hard Timeout: Absolute 5.0s ceiling — returns regardless of stability.
  5. Visual Diff (optional): Send pre/post screenshots to Cloud VLM for
     semantic comparison to verify intent fulfillment.

Usage:
    pass
    
from ufo.agents.evaluation_agent.state_verifier import StateVerifier

    verifier = StateVerifier()

    # Wait for UI to settle after an action
    settled = verifier.wait_for_settlement(app_window)

    # Verify the action achieved its intent
    result = verifier.verify_action_success(
        node=dag_node,
        pre_screenshot="C:/tmp/pre.png",
        post_screenshot="C:/tmp/post.png",
        user_intent="Click the Save button",
    )
"""
import base64
import json
import logging
import os
import platform
import time
from typing import Any, Optional
from pydantic import BaseModel, Field
logger = logging.getLogger(__name__)

class SettlementResult(BaseModel):
    """Result of a UI settlement check."""
    settled: bool = Field(default=False, description='Whether the UI reached structural stability')
    elapsed_seconds: float = Field(default=0.0, description='Time spent waiting for settlement')
    stable_iterations: int = Field(default=0, description='Number of consecutive stable checks')
    final_control_count: int = Field(default=0, description='UIA descendants count at conclusion')
    timed_out: bool = Field(default=False, description='Whether the hard timeout was hit')
    foreground_valid: bool = Field(default=True, description='Whether foreground HWND matched')
    control_enabled: bool = Field(default=True, description='Whether target control was enabled')

class VerificationResult(BaseModel):
    """Result of a post-action visual verification."""
    success: bool = Field(default=False, description='Whether the action achieved the intent')
    observed_state: str = Field(default='', description='Description of the observed post-action state')
    confidence: float = Field(default=0.0, description='VLM confidence in the assessment')
    error_reason: str = Field(default='', description='Error description if verification failed')
    source: str = Field(default='structural', description='Verification method: structural, cloud_vlm')
_DEFAULT_HARD_TIMEOUT = 5.0
_DEFAULT_CHECK_INTERVAL = 0.1
_DEFAULT_STABLE_THRESHOLD = 5
_DEFAULT_CHECK_FOREGROUND = True
_DEFAULT_CHECK_ENABLED = True

class StateVerifier:
    """
    Hybrid structural UI settlement and Cloud VLM visual diffing.

    Reads config from system.yaml:
      UI_SETTLEMENT:
        HARD_TIMEOUT_SECONDS: 5.0
        PIXEL_CONVERGENCE_THRESHOLD: 5
        CHECK_FOREGROUND_HWND: true
        CHECK_CONTROL_ENABLED: true
    """

    def __init__(self) -> None:
        self._hard_timeout: float = _DEFAULT_HARD_TIMEOUT
        self._check_interval: float = _DEFAULT_CHECK_INTERVAL
        self._stable_threshold: int = _DEFAULT_STABLE_THRESHOLD
        self._check_foreground: bool = _DEFAULT_CHECK_FOREGROUND
        self._check_enabled: bool = _DEFAULT_CHECK_ENABLED
        self._load_config()

    def _load_config(self) -> None:
        """Load UI settlement config from system.yaml."""
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            us_cfg = getattr(cfg.system, 'ui_settlement', None)
            if us_cfg and isinstance(us_cfg, dict):
                self._hard_timeout = float(us_cfg.get('HARD_TIMEOUT_SECONDS', _DEFAULT_HARD_TIMEOUT))
                self._stable_threshold = int(us_cfg.get('PIXEL_CONVERGENCE_THRESHOLD', _DEFAULT_STABLE_THRESHOLD))
                self._check_foreground = bool(us_cfg.get('CHECK_FOREGROUND_HWND', _DEFAULT_CHECK_FOREGROUND))
                self._check_enabled = bool(us_cfg.get('CHECK_CONTROL_ENABLED', _DEFAULT_CHECK_ENABLED))
        except Exception as e:
            logger.debug(f'Using default UI settlement config: {e}')

    def wait_for_settlement(self, app_window: Any, target_control: Any=None, timeout: Optional[float]=None) -> SettlementResult:
        """
        Wait for the UI to settle after an action by checking structural stability.

        Uses UIA descendants count (COM element tree size) instead of pixel polling.
        This avoids infinite loops caused by blinking cursors, CSS animations,
        loading spinners, and other visual noise.

        :param app_window: The pywinauto UIAWrapper for the application window.
        :param target_control: Optional specific control to check enablement on.
        :param timeout: Override the hard timeout (default from config).
        :return: SettlementResult with detailed diagnostics.
        """
        hard_timeout = timeout or self._hard_timeout
        start_time = time.monotonic()
        last_control_count = -1
        stable_iterations = 0
        final_count = 0
        foreground_valid = True
        control_enabled = True
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= hard_timeout:
                logger.warning(f'UI settlement timed out after {elapsed:.1f}s ({stable_iterations}/{self._stable_threshold} stable checks). Forcing evaluation.')
                return SettlementResult(settled=False, elapsed_seconds=elapsed, stable_iterations=stable_iterations, final_control_count=final_count, timed_out=True, foreground_valid=foreground_valid, control_enabled=control_enabled)
            try:
                current_count = self._count_descendants_safe(app_window)
                final_count = current_count
                if current_count == last_control_count:
                    stable_iterations += 1
                else:
                    stable_iterations = 0
                    last_control_count = current_count
            except Exception as e:
                logger.debug(f'UIA query error during settlement: {e}')
                stable_iterations = 0
            if self._check_foreground and stable_iterations >= self._stable_threshold:
                foreground_valid = self._verify_foreground(app_window)
                if not foreground_valid:
                    logger.warning('Foreground HWND mismatch — window may have lost focus.')
            if self._check_enabled and target_control and (stable_iterations >= self._stable_threshold):
                control_enabled = self._verify_control_enabled(target_control)
                if not control_enabled:
                    logger.warning('Target control is disabled post-action.')
            if stable_iterations >= self._stable_threshold:
                elapsed = time.monotonic() - start_time
                logger.debug(f'UI structurally settled after {elapsed:.2f}s ({final_count} controls, {stable_iterations} stable checks).')
                return SettlementResult(settled=True, elapsed_seconds=elapsed, stable_iterations=stable_iterations, final_control_count=final_count, timed_out=False, foreground_valid=foreground_valid, control_enabled=control_enabled)
            time.sleep(self._check_interval)

    def verify_action_success(self, node: Any, pre_screenshot: str, post_screenshot: str, user_intent: str) -> VerificationResult:
        """
        Compare pre/post screenshots via Cloud VLM to verify intent fulfillment.

        Routes to BACKUP_AGENT (Gemini 3.7 Flash or equivalent Cloud VLM)
        for semantic visual diffing. Local models are too weak for logical
        state comparison.

        :param node: The DAGNode that was executed.
        :param pre_screenshot: Path to screenshot captured before the action.
        :param post_screenshot: Path to screenshot captured after the action.
        :param user_intent: The original user intent string.
        :return: VerificationResult with success flag + reasoning.
        """
        if not os.path.exists(pre_screenshot):
            return VerificationResult(success=False, error_reason=f'Pre-action screenshot not found: {pre_screenshot}')
        if not os.path.exists(post_screenshot):
            return VerificationResult(success=False, error_reason=f'Post-action screenshot not found: {post_screenshot}')
        action_type = getattr(getattr(node, 'action', None), 'action_type', 'unknown')
        target_app = getattr(getattr(node, 'action', None), 'target_app', 'unknown')
        node_desc = getattr(node, 'description', '')
        prompt = f'''You are the UFO Evaluation Agent. Your job is to verify whether a UI automation action was successful by comparing pre-action and post-action screenshots.\n\nUSER INTENT: "{user_intent}"\nACTION TAKEN: {action_type} on {target_app}\nNODE DESCRIPTION: "{node_desc}"\n\nThe FIRST image is the PRE-action state. The SECOND image is the POST-action state.\n\nCompare these two screenshots and determine:\n1. Did the UI state change in a way consistent with the action?\n2. Does the change fulfill the user's intent?\n3. Are there any error dialogs, crashes, or unexpected states?\n\nRespond with ONLY a JSON object:\n{{"success": <bool>, "observed_state": "<description>", "confidence": <float 0.0-1.0>, "error_reason": "<empty if success>"}}'''
        try:
            from ufo.llm.llm_call import get_completion
            from ufo.llm import AgentType
            pre_b64 = self._encode_screenshot(pre_screenshot)
            post_b64 = self._encode_screenshot(post_screenshot)
            if not pre_b64 or not post_b64:
                return VerificationResult(success=False, error_reason='Failed to encode screenshots for VLM comparison.')
            pre_ext = os.path.splitext(pre_screenshot)[1].lower()
            post_ext = os.path.splitext(post_screenshot)[1].lower()
            pre_mime = 'image/png' if pre_ext == '.png' else 'image/jpeg'
            post_mime = 'image/png' if post_ext == '.png' else 'image/jpeg'
            messages = [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': f'data:{pre_mime};base64,{pre_b64}'}}, {'type': 'image_url', 'image_url': {'url': f'data:{post_mime};base64,{post_b64}'}}]}]
            try:
                response_text, _cost = get_completion(messages, agent=AgentType.EVALUATION, use_backup_engine=True)
            except (ValueError, AttributeError):
                response_text, _cost = get_completion(messages, agent=AgentType.BACKUP, use_backup_engine=False)
            return self._parse_verification_response(response_text)
        except Exception as e:
            logger.error(f'Visual diff verification failed: {e}')
            return VerificationResult(success=False, observed_state='Unknown', error_reason=str(e), source='cloud_vlm')

    def quick_verify(self, app_window: Any, expected_change: str='any', pre_control_count: Optional[int]=None) -> VerificationResult:
        """
        Quick structural verification without Cloud VLM.

        Checks whether the UIA tree changed (element count delta) to confirm
        the action had some effect. Useful for fast local-only verification.

        :param app_window: The app window UIAWrapper.
        :param expected_change: "increase", "decrease", "any", or "none".
        :param pre_control_count: UIA descendants count before the action.
        :return: VerificationResult based on structural change.
        """
        post_count = self._count_descendants_safe(app_window)
        if pre_control_count is None:
            return VerificationResult(success=post_count > 0, observed_state=f'Post-action control count: {post_count}', confidence=0.5, source='structural')
        delta = post_count - pre_control_count
        if expected_change == 'increase':
            success = delta > 0
        elif expected_change == 'decrease':
            success = delta < 0
        elif expected_change == 'none':
            success = delta == 0
        else:
            success = delta != 0
        return VerificationResult(success=success, observed_state=f'Control count: {pre_control_count} → {post_count} (delta={delta:+d})', confidence=0.7 if success else 0.3, source='structural')

    @staticmethod
    def _count_descendants_safe(app_window: Any, max_depth: int=15) -> int:
        """Count UIA descendants safely, handling COM errors."""
        try:
            return len(app_window.descendants())
        except Exception:
            count = 0
            try:
                for child in app_window.children():
                    count += 1
            except Exception:
                pass
            return count

    @staticmethod
    def _verify_foreground(app_window: Any) -> bool:
        """Check if the app window is still the foreground window."""
        if platform.system() != 'Windows':
            return True
        try:
            import ctypes
            foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
            window_handle = int(app_window.handle)
            return foreground_hwnd == window_handle
        except Exception:
            return True

    @staticmethod
    def _verify_control_enabled(control: Any) -> bool:
        """Check if a specific control is enabled."""
        try:
            return control.is_enabled()
        except Exception:
            return True

    @staticmethod
    def _encode_screenshot(path: str) -> Optional[str]:
        """Read a screenshot and return base64-encoded string."""
        try:
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.warning(f'Failed to encode screenshot {path}: {e}')
            return None

    @staticmethod
    def _parse_verification_response(text: str) -> VerificationResult:
        """Parse Cloud VLM JSON response into VerificationResult."""
        if not text:
            return VerificationResult(success=False, error_reason='Empty response from VLM.', source='cloud_vlm')
        cleaned = text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            cleaned = '\n'.join(lines).strip()
        try:
            parsed = json.loads(cleaned)
            return VerificationResult(success=bool(parsed.get('success', False)), observed_state=str(parsed.get('observed_state', '')), confidence=float(parsed.get('confidence', 0.0)), error_reason=str(parsed.get('error_reason', '')), source='cloud_vlm')
        except json.JSONDecodeError:
            start = cleaned.find('{')
            end = cleaned.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(cleaned[start:end])
                    return VerificationResult(success=bool(parsed.get('success', False)), observed_state=str(parsed.get('observed_state', '')), confidence=float(parsed.get('confidence', 0.0)), error_reason=str(parsed.get('error_reason', '')), source='cloud_vlm')
                except json.JSONDecodeError:
                    pass
            return VerificationResult(success=False, error_reason=f'Failed to parse VLM response: {text[:200]}', source='cloud_vlm')