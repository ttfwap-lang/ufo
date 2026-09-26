# UFO Repository: Improvement Plan (2026-09-26)

## Repo State
- 8 commits ahead of origin (latest: d25a309)
- 1249 files changed from upstream/main (260k insertions)
- 717 Python files, ~124k lines
- 910 lint issues (574 unused imports)
- 46 high-complexity functions (worst: get_completions at 66)
- 70 hard-coded paths across 39 files
- 163+ tests pass individually; suite hangs on network-dependent tests

## Test Suite Hang
tests/clients/test_constellation_client.py connects to real devices at 192.168.1.100-102 and hangs indefinitely. Also likely tests/integration/ and tests/e2e_test.py. These need exclusion markers.

## Critical Bugs (fix first)

### 1. ExecutionResult.is_successful always False (galaxy/core/types.py:119)
- self.status in ["completed", "success"] compares enum to string -> always False
- Breaks: get_statistics(), get_parallelism_metrics(), any success-dependent logic
- Fix: self.status.value in ["completed", "success"]

### 2. Hardcoded credentials in ufo.env
- FEATHERLESS_API_KEY, FLAK3DD_PASSWORD, NICK_PASSWORD in plaintext
- Must be moved to environment variables only

### 3. task_constellation.py has Union imported twice (line 10)
- from typing import ..., Union, Union -> artifact of bad refactoring

### 4. callable used instead of Callable in message_processor.py
- Optional[callable] and handler: callable -> callable is built-in, not typing construct

### 5. Duplicate description setter in TaskStar (task_star.py:108-150)
- Two @description.setter definitions -> Python silently uses the second

### 6. Unawaited asyncio tasks in device_manager.py (line 358)
- asyncio.create_task(...) return value never stored -> tasks can be GC'd

### 7. Resource leak in heartbeat_manager.py
- _heartbeat_loop exits without removing itself from _heartbeat_tasks

### 8. _init_context in galaxy_session.py crashes if client is None (line 184)

### 9. DragCommand.execute broken conditional (controller.py:932)
- Operator precedence bug: end_y = path[i+1].get('y', 0) if i+1 < len(path) else path[i]
- When i+1 >= len(path), path[i+1] raises IndexError AND end_y gets a dict

### 10. search_chats always returns empty (telegram_gui.py:1447-1460)
- Calls _open_chat_by_keyboard but returns []

## High Priority

### 11. _literal_keys brace escaping bug (telegram_gui.py:742-752)
- } in _SEND_KEYS_SYNTAX produces {}} instead of }}

### 12. Playwright resource leak (controller.py:38-40, playwright_adapter.py)
- sync_playwright().start() creates instance never closed

### 13. atomic_execution silently swallows all exceptions (controller.py:99-103)
- Returns traceback string, callers use fragile string matching

### 14. force_telegram_top hardcoded paths (telegram_gui.py:576-591)
- Paths specific to one user's machine

### 15. _focus_via_minimize_restore always returns True (telegram_gui.py:433-442)
### 16. _focus_via_appactivate always returns True (telegram_gui.py:444-462)

### 17. begin_input_burst defined twice (telegram_lockout.py)
- Lines 211-215 (first) vs 647-649 (second) -> second overrides first

### 18. _get_playwright_cdp_page resource leak (controller.py)

## Medium Priority

### 19. import uuid inline in orchestrator.py (line 444)
### 20. import datetime inline in connection_manager.py (line 120)
### 21. Lowercase generic types in annotations
### 22. modify_constellation_with_llm does nothing (orchestrator.py:550)
### 23. DesktopPhotographer dead relay code with hardcoded URL
### 24. Busy-wait loops in telegram_lockout.py
### 25. _pywinauto_configured module-level global race condition

## Execution Order
1. Fix critical bugs (items 1-10) -- small edits, high impact
2. Fix high priority (items 11-18) -- small edits, medium impact
3. Fix medium priority (items 19-25) -- code cleanup, consistency
4. Address test suite hang
5. Remove hardcoded credentials from ufo.env
6. Address 910 lint issues (mostly unused imports)
7. Refactor high-complexity functions
8. Extract hardcoded paths to config
