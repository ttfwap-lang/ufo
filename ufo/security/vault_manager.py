"""
Zero-Trust Auth Vault — Secure credential retrieval and direct-to-OS injection.

When the DAG Engine encounters a 'secure_type' action node (e.g., logging into
a bank portal), the VaultManager retrieves the credential from the encrypted
Windows Credential Manager (via keyring) and injects it directly via PyAutoGUI.

CRITICAL SECURITY PROPERTIES:
  1. The LLM NEVER sees the plaintext password — not in prompts, logs, or DAG state
  2. The credential is typed directly into the OS input field
  3. The Python variable holding the secret is scrubbed from memory after use
  4. All log output uses masked representations only

Credential Storage:
  Credentials are stored in Windows Credential Manager (or platform keyring).
  To store a credential:
      python -c "import keyring; keyring.set_password('BankFidelity_UFO', 'bank_user', 'p@ssw0rd')"

  To retrieve and test:
      python -c "import keyring; print(keyring.get_password('BankFidelity_UFO', 'bank_user'))"

Config in system.yaml:
    SECURITY:
      VAULT:
        ENABLED: true
        SERVICE_NAME: "BankFidelity_UFO"
        TYPE_INTERVAL: 0.02
        SCRUB_MEMORY: true

Usage:
    
    from ufo.security.vault_manager import VaultManager

    vault = VaultManager()
    success = vault.inject_credential(
        username_key="bank_portal_admin",
    )
"""
import ctypes
import logging
import sys
import time
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

def _load_vault_config() -> Dict[str, Any]:
    """Load vault config from system.yaml."""
    defaults = {'ENABLED': True, 'SERVICE_NAME': 'BankFidelity_UFO', 'TYPE_INTERVAL': 0.02, 'SCRUB_MEMORY': True}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        sec = getattr(cfg.system, 'security', None)
        if sec and isinstance(sec, dict):
            vault = sec.get('VAULT', {})
            if isinstance(vault, dict):
                defaults.update({k: v for k, v in vault.items() if v is not None})
    except Exception:
        pass
    return defaults

def _scrub_string(s: str) -> None:
    """
    Attempt to overwrite a string's memory buffer.

    Python strings are immutable, so this is a best-effort defense-in-depth
    measure. The real protection is that we never log/serialize the value.
    """
    try:
        str_buffer = ctypes.cast(id(s) + sys.getsizeof('') - 1, ctypes.POINTER(ctypes.c_char * len(s)))
        ctypes.memset(str_buffer, ord('X'), len(s))
    except Exception:
        pass

class VaultManager:
    """
    Zero-trust credential vault with direct OS injection.

    Retrieves secrets from the platform keyring and types them directly
    into the focused input field. The LLM context never receives the
    plaintext credential.
    """

    def __init__(self, service_name: Optional[str]=None) -> None:
        self._config = _load_vault_config()
        self._service_name = service_name or self._config.get('SERVICE_NAME', 'BankFidelity_UFO')
        self._type_interval = float(self._config.get('TYPE_INTERVAL', 0.02))
        self._scrub_memory = bool(self._config.get('SCRUB_MEMORY', True))
        self._keyring_available = False
        self._pyautogui_available = False
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Verify that keyring and pyautogui are importable."""
        try:
            import keyring
            self._keyring_available = True
        except ImportError:
            logger.warning('[Vault] keyring not installed. Install with: pip install keyring')
        try:
            import pyautogui
            self._pyautogui_available = True
        except ImportError:
            logger.warning('[Vault] pyautogui not installed. Secure injection requires pyautogui.')

    def is_enabled(self) -> bool:
        """Check if the vault is enabled and dependencies are available."""
        return self._config.get('ENABLED', True) and self._keyring_available and self._pyautogui_available

    def inject_credential(self, username_key: str, service_name: Optional[str]=None, press_enter: bool=False, pre_clear: bool=True) -> bool:
        """
        Retrieve a credential from the vault and type it into the active field.

        The credential string NEVER appears in:
          - Logger output (only masked representation)
          - DAG state / ExecutionGraph JSON
          - LLM prompt payload

        :param username_key: The credential key in the keyring.
        :param service_name: Override the default service name.
        :param press_enter: If True, press Enter after typing the credential.
        :param pre_clear: If True, Ctrl+A then Delete before typing (clears field).
        :return: True if injection succeeded.
        """
        if not self.is_enabled():
            logger.error('[Vault] Vault is disabled or dependencies missing.')
            return False
        svc = service_name or self._service_name
        logger.info(f"[Vault] Secure injection requested: service='{svc}', key='{username_key}'")
        import keyring
        import pyautogui
        secret = keyring.get_password(svc, username_key)
        if not secret:
            logger.error(f"[Vault] Credential not found: service='{svc}', key='{username_key}'. Store it with: keyring.set_password('{svc}', '{username_key}', '<value>')")
            return False
        masked = f"{'*' * min(len(secret), 8)}... ({len(secret)} chars)"
        logger.info(f'[Vault] Credential retrieved: {masked}')
        try:
            if pre_clear:
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.05)
                pyautogui.press('delete')
                time.sleep(0.05)
            pyautogui.write(secret, interval=self._type_interval)
            if press_enter:
                time.sleep(0.1)
                pyautogui.press('enter')
            logger.info('[Vault] Secure injection completed successfully.')
            return True
        except Exception as e:
            logger.error(f'[Vault] Injection failed: {e}')
            return False
        finally:
            if self._scrub_memory and secret:
                _scrub_string(secret)
                del secret

    def inject_credential_for_action(self, action: Any, username_key: str) -> bool:
        """
        Process a TaskAction of type 'secure_type'.

        Checks the action type, retrieves the credential, and injects it.
        Bypasses all LLM logging and DAG state recording.

        :param action: A TaskAction (from dag_engine.py) with action_type='secure_type'.
        :param username_key: The credential key.
        :return: True if injection succeeded.
        """
        action_type = getattr(action, 'action_type', None)
        if action_type != 'secure_type':
            logger.debug(f"[Vault] Action type '{action_type}' is not 'secure_type'. Skipping.")
            return False
        return self.inject_credential(username_key)

    def store_credential(self, username_key: str, password: str, service_name: Optional[str]=None) -> bool:
        """
        Store a credential in the platform keyring.

        :param username_key: The credential key.
        :param password: The credential value.
        :param service_name: Override default service name.
        :return: True if stored.
        """
        if not self._keyring_available:
            return False
        import keyring
        svc = service_name or self._service_name
        try:
            keyring.set_password(svc, username_key, password)
            logger.info(f"[Vault] Credential stored: service='{svc}', key='{username_key}'")
            return True
        except Exception as e:
            logger.error(f'[Vault] Failed to store credential: {e}')
            return False
        finally:
            if self._scrub_memory:
                _scrub_string(password)

    def delete_credential(self, username_key: str, service_name: Optional[str]=None) -> bool:
        """Delete a credential from the keyring."""
        if not self._keyring_available:
            return False
        import keyring
        svc = service_name or self._service_name
        try:
            keyring.delete_password(svc, username_key)
            logger.info(f"[Vault] Credential deleted: service='{svc}', key='{username_key}'")
            return True
        except Exception as e:
            logger.error(f'[Vault] Failed to delete credential: {e}')
            return False

    def has_credential(self, username_key: str, service_name: Optional[str]=None) -> bool:
        """Check if a credential exists in the keyring (without retrieving it)."""
        if not self._keyring_available:
            return False
        import keyring
        svc = service_name or self._service_name
        try:
            return keyring.get_password(svc, username_key) is not None
        except Exception:
            return False
