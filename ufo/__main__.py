# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import argparse
import shutil
import sys
import logging
import urllib.request
import urllib.error
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

# Suppress known benign third-party library deprecation warnings
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.*")
warnings.filterwarnings("ignore", message=".*authlib.*")
warnings.filterwarnings("ignore", message=".*multipart.*")

# Ensure project root is in sys.path for direct script execution and prevent shadowing stdlib logging
ufo_dir = str(Path(__file__).resolve().parent)
if ufo_dir not in sys.path:
    sys.path.insert(0, ufo_dir)

UFO_ROOT = str(Path(__file__).resolve().parent.parent)
if UFO_ROOT not in sys.path:
    sys.path.insert(0, UFO_ROOT)


def parse_args(args_list: Optional[list] = None) -> argparse.Namespace:
    """Parse CLI arguments for UFO."""
    parser = argparse.ArgumentParser(description="Microsoft UFO Agent CLI")
    parser.add_argument(
        "--task",
        "-t",
        help="The name of current task.",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--mode",
        "-m",
        help="mode of the task. Default is 'normal', it can be set to 'follower' if you want to run the follower agent. Also, it can be set to 'batch_normal' if you want to run the batch normal agent, 'operator' if you want to run the OpenAi Operator agent separately.",
        default="normal",
    )
    parser.add_argument(
        "--plan",
        "-p",
        help="The path of the plan file or folder. It is only required for the follower mode and batch_normal mode.",
        type=str,
        default="",
    )
    parser.add_argument(
        "--request",
        "-r",
        help="The description of the request, optional. If not provided, UFO will ask the user to input the request.",
        type=str,
        default="",
    )
    parser.add_argument(
        "--log-level",
        help="Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Use OFF to disable logs.",
        type=str,
        default="WARNING",
    )
    parser.add_argument(
        "--skip-preflight",
        help="Skip pre-flight environment checks (desktop context, screenshot, RAM).",
        action="store_true",
        default=False,
    )
    return parser.parse_args(args_list)


def _run_preflight_checks(logger: logging.Logger) -> None:
    """
    Run lightweight pre-flight environment checks before session creation.
    Logs warnings for degraded conditions but does not block execution.
    """
    import platform

    # Check 1: Desktop context (Windows only)
    if platform.system() == "Windows":
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd == 0:
                logger.warning(
                    "PRE-FLIGHT: GetForegroundWindow() returned 0. "
                    "Screenshots will fail. Run from a desktop shell, not an IDE terminal."
                )
        except Exception as e:
            logger.warning(f"PRE-FLIGHT: Win32 desktop check failed: {e}")

    # Check 2: Screenshot capture
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(0, 0, 100, 100))
        if img is None or img.size[0] <= 0:
            logger.warning("PRE-FLIGHT: Screen capture returned empty image")
    except Exception as e:
        logger.warning(f"PRE-FLIGHT: Screen capture test failed: {e}")

    # Check 3: Available RAM
    try:
        import psutil
        avail_gb = psutil.virtual_memory().available / (1024 ** 3)
        if avail_gb < 2.0:
            logger.warning(f"PRE-FLIGHT: Only {avail_gb:.1f} GB RAM available. Performance may be degraded.")
    except ImportError:
        pass  # psutil optional


def _ensure_llm_reachable(logger: logging.Logger) -> None:
    """
    Probe the configured LLM endpoint. If unreachable (local stack down),
    automatically fall back to the cloud config (agents_cloud.yaml).
    """
    try:
        import yaml
    except ImportError:
        logger.warning("AUTO-FALLBACK: PyYAML not available, skipping LLM probe")
        return

    ufo_path = Path(__file__).resolve().parent
    agents_path = ufo_path / "config" / "ufo" / "agents.yaml"
    agents_cloud = ufo_path / "config" / "ufo" / "agents_cloud.yaml"

    if not agents_path.exists():
        return

    with open(agents_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return

    host = data.get("HOST_AGENT", {})
    api_type = host.get("API_TYPE", "")
    api_base = host.get("API_BASE", "")

    # Only probe local endpoints (cloud APIs don't have /health)
    if api_type != "openai" or "127.0.0.1" not in api_base:
        return

    # Probe the local endpoint
    health_url = f"{api_base.rstrip('/')}/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                logger.info(f"AUTO-FALLBACK: Local LLM at {api_base} is healthy")
                return
    except Exception:
        pass

    # Local endpoint is down -- attempt fallback
    logger.warning(f"AUTO-FALLBACK: Local LLM at {api_base} is unreachable")

    if not agents_cloud.exists():
        logger.error(
            "AUTO-FALLBACK: Cannot fall back to cloud -- agents_cloud.yaml not found. "
            "Start the local stack with 'python scripts/launch_servers.py' or create agents_cloud.yaml."
        )
        return

    # Atomic swap: backup current, copy cloud config
    backup_path = agents_path.with_suffix(".yaml.bak")
    shutil.copy2(agents_path, backup_path)
    shutil.copy2(agents_cloud, agents_path)
    logger.warning(
        "AUTO-FALLBACK: Switched to Gemini cloud API (agents_cloud.yaml). "
        "Original config backed up to agents.yaml.bak. "
        "Restart local stack and run 'python scripts/switch_backend.py local' to revert."
    )


async def main(parsed_args: Optional[argparse.Namespace] = None):
    """
    Main function to run the UFO system.

    To use normal mode, run the following command:
    python -m ufo -t task_name

    To use follower mode that follows a plan file or folder, run the following command:
    python -m ufo -t task_name -m follower -p path_to_plan_file_or_folder

    To use batch mode that follows a plan file or folder, run the following command:
    python -m ufo -t task_name -m batch_normal -p path_to_plan_file_or_folder
    """
    
    # Phase 1: Robust Telemetry Setup
    from ufo.ufo_logging.setup import setup_logger
    
    if parsed_args is None:
        parsed_args = parse_args()

    if not parsed_args.task:
        parsed_args.task = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    skip_preflight = getattr(parsed_args, 'skip_preflight', False)

    setup_logger(parsed_args.log_level)
    logger = logging.getLogger("UFO_Main")
    
    # Phase 2: Pre-flight environment checks
    if not skip_preflight:
        _run_preflight_checks(logger)
    
    # Phase 3: Auto-fallback LLM backend routing
    _ensure_llm_reachable(logger)
    
    try:
        from ufo.module.session_pool import SessionFactory, SessionPool

        sessions = SessionFactory().create_session(
            task=parsed_args.task,
            mode=parsed_args.mode,
            plan=parsed_args.plan,
            request=parsed_args.request,
        )

        clients = SessionPool(sessions)
        await clients.run_all()
        
    except Exception as e:
        logger.critical(f"FATAL SYSTEM CRASH: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    
    # Global top-level try/except to prevent white-screening and silently swallowing crashes
    try:
        asyncio.run(main())
    except Exception as global_e:
        logging.getLogger("UFO_Global").critical(f"Unhandled Asyncio Loop Crash: {global_e}", exc_info=True)
        sys.exit(1)
