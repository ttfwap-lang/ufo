import os
import pkgutil
import importlib.util
import sys
import platform
from pathlib import Path
current_dir = os.path.dirname(__file__)
WINDOWS_ONLY_SERVERS = {'ui_mcp_server', 'excel_wincom_mcp_server', 'ppt_wincom_mcp_server', 'word_wincom_mcp_server', 'pdf_reader_mcp_server'}

def load_all_servers():
    """
    Lazy load all MCP server modules.
    This function should be called when the servers are actually needed,
    not at module import time, to avoid circular import issues.

    On non-Windows platforms, Windows-specific servers are skipped.
    """
    is_windows = platform.system() == 'Windows'
    # __file__ is <repo_root>/client/mcp/local_servers/__init__.py, and
    # <repo_root> itself IS the "ufo" package (it has __init__.py at its
    # root and every internal module imports itself as ufo.X) — so the
    # package dir is 3 parents up, and the dir that must be on sys.path for
    # "import ufo...." to resolve is one level above that.
    _here = Path(__file__).resolve()
    _ufo_pkg = _here.parents[3]
    _ufo_root = _here.parents[4]
    for p in [str(_ufo_root), str(_ufo_pkg)]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    for finder, name, ispkg in pkgutil.iter_modules([current_dir]):
        if not ispkg:
            if not is_windows and name in WINDOWS_ONLY_SERVERS:
                print(f"Skipping Windows-only server '{name}' on {platform.system()} platform")
                continue
            full_module_name = f'ufo.client.mcp.local_servers.{name}'
            try:
                if full_module_name in sys.modules:
                    continue
                spec = importlib.util.find_spec(full_module_name)
                if not spec:
                    file_path = os.path.join(current_dir, f'{name}.py')
                    if os.path.isfile(file_path):
                        spec = importlib.util.spec_from_file_location(full_module_name, file_path)
                if spec:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[full_module_name] = module
                    if spec.loader:
                        spec.loader.exec_module(module)
                else:
                    print(f'Could not find spec for module {full_module_name}')
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Error loading module '{full_module_name}': {e}")
