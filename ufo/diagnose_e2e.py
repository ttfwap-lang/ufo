"""Full E2E diagnostic - exercises every automation layer with explicit results.

Goal: honestly measure what works and where the automation breaks, so we can
critique and harden it. No errors are swallowed.
"""
import sys, asyncio, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import (
    TelegramGUIController, AutonomousTelegramAgent, ExecutionConfig,
    PrivacyRedactor, ConversationLearner, BotSkill, ScreenLockout,
)
from ufo.automation.factory import get_desktop_automation

RESULTS = []

def step(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('| ' + detail) if detail else ''}")

async def main():
    print("=" * 78)
    print("FULL E2E DIAGNOSTIC - Telegram automation layers")
    print("=" * 78)

    # ---- 1. Connect (title-independent) ----
    try:
        desktop = get_desktop_automation("Telegram.exe")
        c = TelegramGUIController(desktop)
        connected = await c.connect()
        step("connect (title-independent)", connected)
        step("window resolved", c.window is not None,
             repr(c.window.name)[:50] if c.window else "NONE")
    except Exception as e:
        traceback.print_exc()
        step("connect", False, str(e))
        return

    # ---- 2. Chat list walk ----
    try:
        cl = await c._find_chat_list()
        step("find chat list (Dialogs::InnerWidget)", cl is not None,
             f"rect={cl.rect if cl else None}")
    except Exception as e:
        traceback.print_exc()
        step("find chat list", False, str(e))

    try:
        chats = await c.get_chats(max_chats=25)
        step("get_chats walk", len(chats) > 0, f"{len(chats)} chats")
        for ch in chats[:5]:
            print("      -", repr(ch.name[:50]))
    except Exception as e:
        traceback.print_exc()
        step("get_chats", False, str(e))

    # ---- 3. Real click navigation ----
    try:
        found = await c._find_chat_by_name("iMe AI")
        step("find 'iMe AI' row via name", found is not None,
             f"rect={found.rect if found else 'NOT FOUND'}")
    except Exception as e:
        traceback.print_exc()
        step("find row", False, str(e))

    try:
        opened = await c.open_chat("iMe AI")
        step("open_chat 'iMe AI' (real click)", opened)
        await asyncio.sleep(1)
        await c._ensure_window_fresh()
        step("window title shows iMe AI",
             c.window and c._title_matches_chat(c.window.name or "", "iMe AI"),
             repr(c.window.name)[:60] if c.window else "none")
    except Exception as e:
        traceback.print_exc()
        step("open_chat", False, str(e))

    # ---- 4. Screenshot capture ----
    try:
        shot = await c.take_screenshot()
        step("screenshot (PrintWindow)", shot is not None and len(shot) > 10000,
             f"{len(shot) if shot else 0} bytes")
    except Exception as e:
        traceback.print_exc()
        step("screenshot", False, str(e))

    # ---- 5. Verification ----
    try:
        agent = AutonomousTelegramAgent(config=ExecutionConfig(min_delay_seconds=0.3, max_delay_seconds=0.5))
        v = await agent.verify_current_state()
        step("verify window present", v.get("success"), v.get("reasoning"))
    except Exception as e:
        traceback.print_exc()
        step("verify", False, str(e))

    # ---- 6. Privacy redactor ----
    r = PrivacyRedactor()
    ok = r.redact("hello there").is_error is False and r.redact("Order failed").is_error is True
    step("privacy redactor (non-error redacted / error read)", ok)

    # ---- 7. Pattern learner ----
    try:
        learner = ConversationLearner()
        skill = BotSkill(skill_name="e2e-demo", bot_name="Demo", chat_name="x")
        sample = [
            {"id": 1, "from": "Me", "from_id": "user1", "text": "/start"},
            {"id": 2, "from": "Bot", "from_id": "9", "text": "Please choose option:"},
            {"id": 3, "from": "Me", "from_id": "user1", "text": "Get Data"},
            {"id": 4, "from": "Bot", "from_id": "9", "text": "Error: not found"},
        ]
        stats = learner.learn_from_messages(sample, skill)
        dump = skill.to_dict()
        leaks = [n for n in ["Get Data", "not found"] if n in str(dump)]
        step("pattern learner (no content leaks)", not leaks, f"transitions={len(stats.get('transitions', {}))}")
    except Exception as e:
        traceback.print_exc()
        step("pattern learner", False, str(e))

    print()
    print("=" * 78)
    ok_count = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"E2E SUMMARY: {ok_count}/{len(RESULTS)} steps passed")
    for name, ok, detail in RESULTS:
        marker = "OK " if ok else "XX "
        print(f"  [{marker}] {name}")
    print("=" * 78)

asyncio.run(main())
