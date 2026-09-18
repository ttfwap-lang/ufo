import argparse
import asyncio
import logging
import sys
import urllib.error
import urllib.request
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

warnings.filterwarnings('ignore', category=PendingDeprecationWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning, module='websockets.*')
warnings.filterwarnings('ignore', message='.*authlib.*')
warnings.filterwarnings('ignore', message='.*multipart.*')
ufo_package_dir = str(Path(__file__).resolve().parent)
if sys.path and sys.path[0] == ufo_package_dir:
    sys.path.pop(0)
UFO_ROOT = str(Path(__file__).resolve().parent.parent)
if UFO_ROOT not in sys.path:
    sys.path.insert(0, UFO_ROOT)

def parse_args(args_list: Optional[list]=None) -> argparse.Namespace:
    """Parse CLI arguments for UFO."""
    parser = argparse.ArgumentParser(description='Microsoft UFO Agent CLI')
    parser.add_argument('--task', '-t', help='The name of current task.', type=str, default=None)
    parser.add_argument('--mode', '-m', help="mode of the task. Default is 'normal', it can be set to 'follower' if you want to run the follower agent. Also, it can be set to 'batch_normal' if you want to run the batch normal agent, 'operator' if you want to run the OpenAi Operator agent separately.", default='normal')
    parser.add_argument('--plan', '-p', help='The path of the plan file or folder. It is only required for the follower mode and batch_normal mode.', type=str, default='')
    parser.add_argument('--request', '-r', help='The description of the request, optional. If not provided, UFO will ask the user to input the request.', type=str, default='')
    parser.add_argument('--log-level', help='Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Use OFF to disable logs.', type=str, default='WARNING')
    parser.add_argument('--skip-preflight', help='Skip pre-flight environment checks (desktop context, screenshot, RAM).', action='store_true', default=False)
    parser.add_argument('positional_request', nargs='*', help='Positional task prompt (e.g. `python -m ufo open notepad`)', default=None)
    return parser.parse_args(args_list)

def _run_preflight_checks(logger: logging.Logger) -> None:
    """
    Run lightweight pre-flight environment checks before session creation.
    Logs warnings for degraded conditions but does not block execution.
    """
    import platform
    if platform.system() == 'Windows':
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd == 0:
                logger.warning('PRE-FLIGHT: GetForegroundWindow() returned 0. Screenshots will fail. Run from a desktop shell, not an IDE terminal.')
        except Exception as e:
            logger.warning(f'PRE-FLIGHT: Win32 desktop check failed: {e}')
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(0, 0, 100, 100))
        if img is None or img.size[0] <= 0:
            logger.warning('PRE-FLIGHT: Screen capture returned empty image')
    except Exception as e:
        logger.warning(f'PRE-FLIGHT: Screen capture test failed: {e}')
    try:
        import psutil
        avail_gb = psutil.virtual_memory().available / 1024 ** 3
        if avail_gb < 2.0:
            logger.warning(f'PRE-FLIGHT: Only {avail_gb:.1f} GB RAM available. Performance may be degraded.')
    except ImportError:
        pass

def _probe_health_sync(health_url: str, timeout: float) -> bool:
    """Blocking HTTP GET, meant to be run off the event loop via asyncio.to_thread."""
    try:
        req = urllib.request.Request(health_url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

async def _ensure_llm_reachable(logger: logging.Logger) -> None:
    """
    Probe the configured LLM endpoint. If unreachable (local stack down),
    switch the in-memory route to cloud config (agents_cloud.yaml) with zero disk writes.
    This is a process-local override that never touches persisted user intent.
    """

    from ufo.llm.config_helper import BackendProfileError, resolve_backend_profile, set_process_override
    from ufo.llm.endpoint import is_local_endpoint
    try:
        try:
            prof = resolve_backend_profile()
        except BackendProfileError as e:
            logger.warning(f'AUTO-FALLBACK: Profile resolution failed: {e}')
            return
        if not prof:
            return
        host = prof.get('HOST_AGENT', {})
        api_type = host.get('API_TYPE', '')
        api_base = host.get('API_BASE', '')
        api_key = host.get('API_KEY', '')
        # 'ollama' added alongside 'openai': the DGX profile's HOST_AGENT now
        # serves via Ollama, not a generic OpenAI-compatible llama-server, and
        # this probe was silently skipping it entirely (api_type != 'openai'
        # returned early), so a DGX-down condition never triggered fallback.
        if api_type not in ('openai', 'ollama') or not api_base:
            return
        if not is_local_endpoint(api_base=api_base, api_key=api_key, api_type=api_type):
            return
        health_path = '/api/tags' if api_type == 'ollama' else '/health'
        health_url = f"{api_base.rstrip('/')}{health_path}"
        # Run the blocking urllib call in a worker thread: this coroutine runs
        # inside async main() before any other work has started, and a slow/
        # unreachable host would otherwise stall the event loop itself for up
        # to the full timeout rather than just delaying this one startup step.
        if await asyncio.to_thread(_probe_health_sync, health_url, 5.0):
            logger.info(f'AUTO-FALLBACK: Local LLM at {api_base} is healthy')
            return
        logger.warning(f'AUTO-FALLBACK: Local LLM at {api_base} is unreachable')
        if set_process_override('cloud'):
            logger.warning('AUTO-FALLBACK: Switched active LLM route to Claude/OpenAI cloud API in memory (zero disk writes).')
        else:
            logger.error('AUTO-FALLBACK: Could not enable in-memory cloud fallback (agents_cloud.yaml missing or invalid). Keeping current configuration.')
    except Exception as e:
        logger.warning(f'AUTO-FALLBACK: LLM reachability probe encountered error: {e}')

async def main(parsed_args: Optional[argparse.Namespace]=None):
    """
    Main function to run the UFO system.

    To use normal mode, run the following command:
        pass
    python -m ufo -t task_name

    To use follower mode that follows a plan file or folder, run the following command:
        pass
    python -m ufo -t task_name -m follower -p path_to_plan_file_or_folder

    To use batch mode that follows a plan file or folder, run the following command:
        pass
    python -m ufo -t task_name -m batch_normal -p path_to_plan_file_or_folder
    """
    from ufo.ufo_logging.setup import setup_logger
    if parsed_args is None:
        parsed_args = parse_args()
    if not parsed_args.task:
        parsed_args.task = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    if getattr(parsed_args, 'positional_request', None):
        joined_req = ' '.join(parsed_args.positional_request).strip()
        if joined_req and (not parsed_args.request):
            parsed_args.request = joined_req
    skip_preflight = getattr(parsed_args, 'skip_preflight', False)
    setup_logger(parsed_args.log_level)
    logger = logging.getLogger('UFO_Main')
    if not skip_preflight:
        _run_preflight_checks(logger)
    await _ensure_llm_reachable(logger)
    watchdog = None
    try:
        from ufo.utils.llm_resilience import get_watchdog
        watchdog = get_watchdog()
        watchdog.start()
        logger.info('LLM Watchdog daemon started for mid-task resilience')
    except Exception as wd_err:
        logger.warning(f'LLM Watchdog failed to start (non-fatal): {wd_err}')
    try:
        from pathlib import Path

        from ufo.module.session_pool import SessionFactory, SessionPool
        from ufo.utils.ipc import UfoTaskResult

        sessions = SessionFactory().create_session(task=parsed_args.task, mode=parsed_args.mode, plan=parsed_args.plan, request=parsed_args.request)
        clients = SessionPool(sessions)
        await clients.run_all()

        output_str = "Completed"
        if sessions and sessions[0].is_error():
            res = UfoTaskResult(status="error", task_id=parsed_args.task, error_type="Crash", error_message="Session ended in error state (check output.md or logs for details)", traceback="")
        else:
            if sessions and sessions[0].results:
                try:
                    last_res = sessions[0].results[-1].get('result', '')
                    output_str = str(last_res)
                except Exception:
                    pass
            res = UfoTaskResult(status="success", task_id=parsed_args.task, output=output_str)
        log_dir = Path("logs") / parsed_args.task
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "result.json", "w", encoding="utf-8") as f:
            f.write(res.model_dump_json())

    except Exception as e:
        logger.critical(f'FATAL SYSTEM CRASH: {e}', exc_info=True)
        import traceback
        from pathlib import Path

        from ufo.utils.ipc import UfoTaskResult

        res = UfoTaskResult(
            status="error",
            task_id=parsed_args.task,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc()
        )
        log_dir = Path("logs") / parsed_args.task
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "result.json", "w", encoding="utf-8") as f:
            f.write(res.model_dump_json())
        sys.exit(1)
    finally:
        if watchdog:
            watchdog.stop()
if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except SystemExit as sys_exit:
        if sys_exit.code == 0:
            sys.exit(0)
        else:
            global_e = sys_exit
            logging.getLogger('UFO_Global').critical(f'Unhandled Asyncio Loop Crash: {global_e}', exc_info=True)
            import argparse
            import sys
            import traceback
            from pathlib import Path

            from ufo.utils.ipc import UfoTaskResult
            # Fallback to sys.argv if parsed_args is not available here
            task_id = "unknown_crash"
            for i, arg in enumerate(sys.argv):
                if arg in ('--task', '-t') and i + 1 < len(sys.argv):
                    task_id = sys.argv[i + 1]
                    break
            res = UfoTaskResult(
                status="error",
                task_id=task_id,
                error_type=type(global_e).__name__,
                error_message=str(global_e),
                traceback=traceback.format_exc()
            )
            log_dir = Path("logs") / task_id
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "result.json", "w", encoding="utf-8") as f:
                f.write(res.model_dump_json())
            sys.exit(sys_exit.code)
    except BaseException as global_e:
        logging.getLogger('UFO_Global').critical(f'Unhandled Asyncio Loop Crash: {global_e}', exc_info=True)
        import argparse
        import sys
        import traceback
        from pathlib import Path

        from ufo.utils.ipc import UfoTaskResult
        # Fallback to sys.argv if parsed_args is not available here
        task_id = "unknown_crash"
        for i, arg in enumerate(sys.argv):
            if arg in ('--task', '-t') and i + 1 < len(sys.argv):
                task_id = sys.argv[i + 1]
                break
        res = UfoTaskResult(
            status="error",
            task_id=task_id,
            error_type=type(global_e).__name__,
            error_message=str(global_e),
            traceback=traceback.format_exc()
        )
        log_dir = Path("logs") / task_id
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "result.json", "w", encoding="utf-8") as f:
            f.write(res.model_dump_json())
        sys.exit(1)
