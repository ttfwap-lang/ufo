"""
Orchestrator Router — Dual-personality execution mode selector.

Routes incoming user requests to either:
  1. Strict DAG Engine (Tickets 1-3) — deterministic, auditable, no exploration
  2. ReAct Exploratory Engine (legacy UFO) — flexible, memory-assisted, interactive

Routing logic:
  - If is_financial_routing=True → ALWAYS DAG (override all flags)
  - If EXECUTION_MODES.STRICT_DETERMINISM=true → DAG
  - If strict=false → ReAct + optional RAG memory + SoM fallback

IMPORTANT: Any DAGNode with is_irrevocable=True permanently bypasses all
exploratory features, even if strict mode is off.

Usage:
    
    from ufo.agents.host_agent.orchestrator_router import OrchestratorRouter

    router = OrchestratorRouter()
    mode = router.resolve_mode(user_intent, is_financial=True)
    # mode == "dag" → use DAG engine
    # mode == "react" → use ReAct engine with optional RAG
"""
import logging
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

def _load_execution_config() -> Dict[str, Any]:
    """Load execution mode config from system.yaml."""
    defaults = {'STRICT_DETERMINISM': True, 'HUMAN_IN_THE_LOOP': False, 'ENABLE_EXPERIENCE_MEMORY': False, 'ENABLE_SET_OF_MARKS': False, 'ENABLE_API_PLUGINS': True}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        em = getattr(cfg.system, 'execution_modes', None)
        if em and isinstance(em, dict):
            defaults['STRICT_DETERMINISM'] = em.get('STRICT_DETERMINISM', True)
            defaults['HUMAN_IN_THE_LOOP'] = em.get('HUMAN_IN_THE_LOOP', False)
        lf = getattr(cfg.system, 'legacy_features', None)
        if lf and isinstance(lf, dict):
            defaults['ENABLE_EXPERIENCE_MEMORY'] = lf.get('ENABLE_EXPERIENCE_MEMORY', False)
            defaults['ENABLE_SET_OF_MARKS'] = lf.get('ENABLE_SET_OF_MARKS', False)
            defaults['ENABLE_API_PLUGINS'] = lf.get('ENABLE_API_PLUGINS', True)
    except Exception:
        pass
    return defaults

class ExecutionMode:
    """Constants for execution modes."""
    DAG = 'dag'
    REACT = 'react'

class OrchestratorRouter:
    """
    Routes user requests to the appropriate execution engine.

    Enforces the hierarchy:
      1. is_financial / is_irrevocable → ALWAYS DAG
      2. STRICT_DETERMINISM → DAG
      3. Otherwise → ReAct (with optional RAG/SoM/Plugin)
    """

    def __init__(self) -> None:
        self._config = _load_execution_config()

    @property
    def is_strict(self) -> bool:
        """Check if strict determinism is enabled."""
        return self._config.get('STRICT_DETERMINISM', True)

    @property
    def human_in_the_loop(self) -> bool:
        """Check if HITL is enabled for fatal failures."""
        return self._config.get('HUMAN_IN_THE_LOOP', False)

    def resolve_mode(self, user_intent: str='', is_financial_routing: bool=False, is_irrevocable: bool=False) -> str:
        """
        Determine the execution mode for a given request.

        :param user_intent: The user's task description.
        :param is_financial_routing: Whether this is a financial/high-stakes task.
        :param is_irrevocable: Whether the current operation is irrevocable.
        :return: ExecutionMode.DAG or ExecutionMode.REACT
        """
        if is_financial_routing or is_irrevocable:
            logger.info(f'[Router] Forced DAG mode: financial={is_financial_routing}, irrevocable={is_irrevocable}')
            return ExecutionMode.DAG
        if self.is_strict:
            logger.info('[Router] Strict determinism enabled → DAG mode.')
            return ExecutionMode.DAG
        logger.info('[Router] Strict mode disabled → ReAct exploratory mode.')
        return ExecutionMode.REACT

    def get_active_features(self) -> Dict[str, bool]:
        """
        Get which optional features are active for the current mode.

        In strict mode, only API plugins are active.
        In react mode, all enabled features are active.
        """
        if self.is_strict:
            return {'experience_memory': False, 'set_of_marks': False, 'api_plugins': self._config.get('ENABLE_API_PLUGINS', True), 'human_in_the_loop': self._config.get('HUMAN_IN_THE_LOOP', False)}
        return {'experience_memory': self._config.get('ENABLE_EXPERIENCE_MEMORY', False), 'set_of_marks': self._config.get('ENABLE_SET_OF_MARKS', False), 'api_plugins': self._config.get('ENABLE_API_PLUGINS', True), 'human_in_the_loop': self._config.get('HUMAN_IN_THE_LOOP', False)}

    def execute_with_routing(self, user_intent: str, is_financial_routing: bool=False, dag_engine: Any=None, react_engine: Any=None) -> Dict[str, Any]:
        """
        Route and execute a user request through the appropriate engine.

        :param user_intent: The user's task description.
        :param is_financial_routing: High-stakes flag.
        :param dag_engine: The DAG engine instance (from dag_engine.py).
        :param react_engine: The ReAct engine instance (legacy UFO).
        :return: Execution result dict.
        """
        mode = self.resolve_mode(user_intent, is_financial_routing)
        if mode == ExecutionMode.DAG:
            return self._execute_dag(user_intent, dag_engine)
        else:
            return self._execute_react(user_intent, react_engine)

    def _execute_dag(self, user_intent: str, dag_engine: Any=None) -> Dict[str, Any]:
        """Execute via strict DAG engine."""
        logger.info(f"[DAG] Executing: '{user_intent[:80]}...'")
        if dag_engine is None:
            logger.warning('[DAG] No DAG engine provided — returning stub result.')
            return {'mode': ExecutionMode.DAG, 'status': 'no_engine', 'intent': user_intent}
        return {'mode': ExecutionMode.DAG, 'status': 'routed', 'intent': user_intent, 'engine': dag_engine}

    def _execute_react(self, user_intent: str, react_engine: Any=None) -> Dict[str, Any]:
        """Execute via ReAct exploratory engine with optional memory."""
        logger.info(f"[ReAct] Executing: '{user_intent[:80]}...'")
        features = self.get_active_features()
        prior_knowledge = None
        if features['experience_memory']:
            try:
                from ufo.memory.rag_experience import ExperienceMemory
                memory = ExperienceMemory()
                if memory.is_available():
                    prior_knowledge = memory.recall_similar_task(user_intent)
                    if prior_knowledge:
                        logger.info('[ReAct] Experience memory matched — injecting prior knowledge.')
            except Exception as e:
                logger.debug(f'[ReAct] Memory recall failed: {e}')
        result = {'mode': ExecutionMode.REACT, 'status': 'routed', 'intent': user_intent, 'prior_knowledge': prior_knowledge, 'active_features': features}
        if react_engine is not None:
            result['engine'] = react_engine
        return result

    def handle_fatal_failure(self, task_id: str, error_trace: str, dag_state: Optional[Dict[str, Any]]=None, screenshot_path: Optional[str]=None) -> str:
        """
        Handle a fatal failure based on HITL config.

        If HUMAN_IN_THE_LOOP is true: prompt the operator via terminal.
        Otherwise: serialize to DLQ silently.

        :param task_id: The failed task ID.
        :param error_trace: Full traceback string.
        :param dag_state: Serialized DAG state.
        :param screenshot_path: Path to failure screenshot.
        :return: "resumed", "aborted", or "dlq_captured"
        """
        if self.human_in_the_loop:
            return self._prompt_operator(task_id, error_trace)
        else:
            return self._serialize_to_dlq(task_id, error_trace, dag_state, screenshot_path)

    def _prompt_operator(self, task_id: str, error_trace: str) -> str:
        """Interactive CLI prompt for human-in-the-loop recovery."""
        logger.critical(f"[HITL] Fatal failure in task '{task_id}'. Awaiting operator input.")
        print(f"\n{'=' * 60}")
        print(f'[UFO] FATAL FAILURE — Task: {task_id}')
        print(f"{'=' * 60}")
        print(f'Error: {error_trace[:500]}')
        print(f"{'=' * 60}")
        try:
            response = input("[UFO] Execution blocked. Provide guidance (or 'abort'): ").strip()
            if response.lower() == 'abort':
                logger.info('[HITL] Operator chose to abort.')
                return 'aborted'
            else:
                logger.info(f"[HITL] Operator guidance: '{response[:100]}'")
                return 'resumed'
        except (EOFError, KeyboardInterrupt):
            logger.info('[HITL] Operator input interrupted — aborting.')
            return 'aborted'

    @staticmethod
    def _serialize_to_dlq(task_id: str, error_trace: str, dag_state: Optional[Dict[str, Any]], screenshot_path: Optional[str]) -> str:
        """Serialize failure to DLQ silently."""
        try:
            from ufo.resilience.dlq_manager import DeadLetterQueueManager
            dlq = DeadLetterQueueManager()
            path = dlq.capture_failure(task_id=task_id, error_chain=error_trace, dag_state=dag_state, screenshots={'failure': screenshot_path} if screenshot_path else None)
            if path:
                return 'dlq_captured'
        except Exception as e:
            logger.error(f'DLQ serialization failed: {e}')
        return 'dlq_failed'