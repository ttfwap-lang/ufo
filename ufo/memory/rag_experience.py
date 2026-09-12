"""
RAG Experience Memory — ChromaDB-backed vector recall of past successful workflows.

When enabled (LEGACY_FEATURES.ENABLE_EXPERIENCE_MEMORY), the HostAgent checks a
local ChromaDB instance before planning a new task to see if a similar task was
successfully completed in the past. If a match is found within the similarity
threshold, the prior DAG plan is injected as context to accelerate planning.

IMPORTANT: This feature is DISABLED when EXECUTION_MODES.STRICT_DETERMINISM is true
or when the current DAG node has is_irrevocable=True.

Gated behind: LEGACY_FEATURES.ENABLE_EXPERIENCE_MEMORY in system.yaml

Usage:
    from ufo.memory.rag_experience import ExperienceMemory


    memory = ExperienceMemory()
    if memory.is_enabled():
        past_plan = memory.recall_similar_task("Open Word and format the header")
        if past_plan:
            # Inject into DAG engine or ReAct planner
            ...

        # After successful execution, save for future recall
        memory.save_successful_run(
            user_intent="Open Word and format the header",
            completed_dag_json=graph.model_dump_json(),
        )
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

def _load_memory_config() -> Dict[str, Any]:
    """Load experience memory config from system.yaml."""
    defaults = {'ENABLED': False, 'DB_PATH': 'memory/chroma_db', 'SIMILARITY_THRESHOLD': 0.3, 'STRICT_MODE': True}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        em_cfg = getattr(cfg.system, 'execution_modes', None)
        if em_cfg and isinstance(em_cfg, dict):
            defaults['STRICT_MODE'] = em_cfg.get('STRICT_DETERMINISM', True)
        lf_cfg = getattr(cfg.system, 'legacy_features', None)
        if lf_cfg and isinstance(lf_cfg, dict):
            defaults['ENABLED'] = lf_cfg.get('ENABLE_EXPERIENCE_MEMORY', False)
            defaults['DB_PATH'] = lf_cfg.get('EXPERIENCE_DB_PATH', 'memory/chroma_db')
            defaults['SIMILARITY_THRESHOLD'] = float(lf_cfg.get('SOM_SIMILARITY_THRESHOLD', 0.3))
    except Exception:
        pass
    return defaults

class ExperienceMemory:
    """
    ChromaDB-backed vector experience recall.

    Stores successful DAG executions as documents in a local vector database.
    On new task requests, queries the DB for similar past workflows to
    bootstrap the planner.

    Self-disables when:
      - LEGACY_FEATURES.ENABLE_EXPERIENCE_MEMORY is false
      - EXECUTION_MODES.STRICT_DETERMINISM is true
      - chromadb package is not installed
    """

    def __init__(self, db_path: Optional[str]=None) -> None:
        self._config = _load_memory_config()
        self._db_path = db_path or self._config['DB_PATH']
        self._threshold = self._config['SIMILARITY_THRESHOLD']
        self._client = None
        self._collection = None
        self._available = False
        self._init_db()

    def _init_db(self) -> None:
        """Initialize ChromaDB client lazily."""
        if not self.is_enabled():
            return
        try:
            import chromadb
            os.makedirs(self._db_path, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._db_path)
            self._collection = self._client.get_or_create_collection('ufo_trajectories', metadata={'description': 'Past successful UFO workflow trajectories'})
            self._available = True
            logger.info(f'Experience memory initialized: {self._db_path} ({self._collection.count()} stored trajectories)')
        except ImportError:
            logger.info('chromadb not installed — experience memory disabled. Install with: pip install chromadb')
            self._available = False
        except Exception as e:
            logger.warning(f'Experience memory initialization failed: {e}')
            self._available = False

    def is_enabled(self) -> bool:
        """Check if experience memory is enabled and not blocked by strict mode."""
        if self._config.get('STRICT_MODE', True):
            return False
        return self._config.get('ENABLED', False)

    def is_available(self) -> bool:
        """Check if the DB is actually initialized and queryable."""
        return self._available and self._collection is not None

    def recall_similar_task(self, user_intent: str, n_results: int=1) -> Optional[str]:
        """
        Query the vector DB for past successful workflows matching the intent.

        :param user_intent: The user's task description.
        :param n_results: Number of results to return.
        :return: The past DAG JSON string if a match is found, else None.
        """
        if not self.is_available():
            return None
        try:
            results = self._collection.query(query_texts=[user_intent], n_results=n_results)
            if not results or not results.get('distances'):
                return None
            distances = results['distances'][0]
            documents = results['documents'][0]
            if distances and distances[0] < self._threshold:
                logger.info(f'Experience memory matched: distance={distances[0]:.3f} (threshold={self._threshold})')
                return documents[0] if documents else None
            logger.debug(f'No close match found: best distance={distances[0]:.3f} > threshold={self._threshold}')
            return None
        except Exception as e:
            logger.warning(f'Experience memory query failed: {e}')
            return None

    def recall_top_k(self, user_intent: str, k: int=5) -> List[Dict[str, Any]]:
        """
        Return top-k similar past workflows with distances.

        :param user_intent: The user's task description.
        :param k: Number of results.
        :return: List of dicts with 'document', 'distance', 'metadata'.
        """
        if not self.is_available():
            return []
        try:
            results = self._collection.query(query_texts=[user_intent], n_results=k)
            entries = []
            if results and results.get('documents'):
                for i, doc in enumerate(results['documents'][0]):
                    entries.append({'document': doc, 'distance': results['distances'][0][i] if results.get('distances') else None, 'metadata': results['metadatas'][0][i] if results.get('metadatas') else {}})
            return entries
        except Exception as e:
            logger.warning(f'Experience memory top-k query failed: {e}')
            return []

    def save_successful_run(self, user_intent: str, completed_dag_json: str, metadata: Optional[Dict[str, Any]]=None) -> bool:
        """
        Save a successfully completed DAG execution for future recall.

        :param user_intent: The user's original task description.
        :param completed_dag_json: Serialized DAG JSON string.
        :param metadata: Optional extra metadata to store.
        :return: True if saved successfully.
        """
        if not self.is_available():
            return False
        try:
            doc_id = f'exp_{abs(hash(user_intent))}_{int(time.time())}'
            meta = {'status': 'success', 'timestamp': int(time.time()), 'intent_preview': user_intent[:200]}
            if metadata:
                meta.update(metadata)
            self._collection.add(documents=[completed_dag_json], metadatas=[meta], ids=[doc_id])
            logger.info(f"Experience saved: '{user_intent[:50]}...' (id={doc_id}, total={self._collection.count()})")
            return True
        except Exception as e:
            logger.warning(f'Experience memory save failed: {e}')
            return False

    def count(self) -> int:
        """Return the number of stored trajectories."""
        if not self.is_available():
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self) -> bool:
        """Clear all stored trajectories."""
        if not self.is_available() or self._client is None:
            return False
        try:
            self._client.delete_collection('ufo_trajectories')
            self._collection = self._client.get_or_create_collection('ufo_trajectories', metadata={'description': 'Past successful UFO workflow trajectories'})
            logger.info('Experience memory cleared.')
            return True
        except Exception as e:
            logger.warning(f'Experience memory clear failed: {e}')
            return False
