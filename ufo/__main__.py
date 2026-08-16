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

# Ensure parent repository root (UFO_ROOT) is the sole repo import root in sys.path.
# Pop sys.path[0] if Python initialized it with the package directory itself.
ufo_package_dir = str(Path(__file__).resolve().parent)
if sys.path and sys.path[0] == ufo_package_dir:
    sys.path.pop(0)

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
    switch the in-memory route to cloud config (agents_cloud.yaml) with zero disk writes.
    """
    import urllib.request
    from ufo.config.config_loader import get_ufo_config
    from ufo.llm.config_helper import set_active_agent_route

    try:
        ufo_cfg = get_ufo_config()
        host = ufo_cfg.host_agent
        api_type = getattr(host, "api_type", "")
        api_base = getattr(host, "api_base", "")

        # Only probe local endpoints (cloud APIs don't have /health)
        if (
            api_type != "openai"
            or not api_base
            or ("127.0.0.1" not in api_base and "localhost" not in api_base)
        ):
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

        # Local endpoint is down -- attempt in-memory fallback
        logger.warning(f"AUTO-FALLBACK: Local LLM at {api_base} is unreachable")
        if set_active_agent_route("cloud"):
            logger.warning(
                "AUTO-FALLBACK: Switched active LLM route to Gemini cloud API in memory (zero disk writes)."
            )
        else:
            logger.error(
                "AUTO-FALLBACK: Could not enable in-memory cloud fallback (agents_cloud.yaml missing or invalid). Keeping current configuration."
            )
    except Exception as e:
        logger.warning(f"AUTO-FALLBACK: LLM reachability probe encountered error: {e}")


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
    
    # Phase 4: Start LLM Watchdog Daemon for mid-task crash recovery
    watchdog = None
    try:
        from ufo.utils.llm_resilience import get_watchdog
        watchdog = get_watchdog()
        watchdog.start()
        logger.info("LLM Watchdog daemon started for mid-task resilience")
    except Exception as wd_err:
        logger.warning(f"LLM Watchdog failed to start (non-fatal): {wd_err}")
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
    finally:
        if watchdog:
            watchdog.stop()


if __name__ == "__main__":
    import asyncio
    
    # Global top-level try/except to prevent white-screening and silently swallowing crashes
    try:
        asyncio.run(main())
    except Exception as global_e:
        logging.getLogger("UFO_Global").critical(f"Unhandled Asyncio Loop Crash: {global_e}", exc_info=True)
        sys.exit(1)
