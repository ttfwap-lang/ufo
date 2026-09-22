import sys, asyncio, json, tempfile, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:\\Users\\lnxzf\\Desktop\\projects\\ufo')
from ufo.automator.app_apis.telegram import (
    AutonomousTelegramAgent, ExecutionConfig, PrivacyRedactor,
    ScreenLockout, TelegramGUIController,
)
from ufo.automation.factory import get_desktop_automation

print('=' * 72)
print('FINAL VALIDATION: A (Windows E2E) + B (conversation learn) + Privacy')
print('=' * 72)

# ---------- PRIVACY ----------
print()
print('--- PRIVACY: PrivacyRedactor ---')
r = PrivacyRedactor()
cases = [
    ('normal message content', False),
    ('Sorry, the request failed, please retry', True),
    ('\u4f59\u989d\u4e0d\u8db3\uff0c\u8bf7\u5145\u503c', True),
    ('cannot process your order', True),
]
all_ok = True
for text, expect in cases:
    res = r.redact(text)
    ok = res.is_error == expect
    all_ok = all_ok and ok
    status = 'READ' if res.is_error else 'REDACTED'
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + status.ljust(8) + ' len=' + str(len(res.safe_text)))
assert all_ok

# ---------- B: pattern learner ----------
print()
print('--- B: learn_patterns_from_conversation (pattern-only) ---')
synthetic = {'name': 'DemoBot', 'type': 'bot_chat', 'id': 555, 'messages': [
    {'id': 1, 'from': 'Me', 'from_id': 'user1', 'text': '/start'},
    {'id': 2, 'from': 'DemoBot', 'from_id': '555', 'text': 'Please choose option:'},
    {'id': 3, 'from': 'Me', 'from_id': 'user1', 'text': 'Get Report'},
    {'id': 4, 'from': 'DemoBot', 'from_id': '555', 'text': 'Please enter the ID:'},
    {'id': 5, 'from': 'Me', 'from_id': 'user1', 'text': '111\n222\n333'},
    {'id': 6, 'from': 'DemoBot', 'from_id': '555', 'text': 'Error: record not found'},
    {'id': 7, 'from': 'Me', 'from_id': 'user1', 'text': '/start'},
    {'id': 8, 'from': 'DemoBot', 'from_id': '555', 'text': 'Please wait, previous request not returned'},
]}
path = os.path.join(tempfile.gettempdir(), 'demo_convo.json')
with open(path, 'w', encoding='utf-8') as f:
    json.dump(synthetic, f)
agent = AutonomousTelegramAgent(config=ExecutionConfig(min_delay_seconds=0.3, max_delay_seconds=0.5))
stats = agent.learn_patterns_from_conversation(path, skill_name='demo-patterns')
print('  transitions:', len(stats.get('transitions', {})))
print('  error keywords:', stats.get('error_keywords'))
print('  delay learned:', agent.current_skill.learned_facts.get('recommended_delay_between_requests_seconds'))
dump = json.dumps(agent.current_skill.to_dict(), ensure_ascii=False)
leaks = [n for n in ['Get Report', '111', 'record not found'] if n in dump]
print('  CONTENT LEAKS:', leaks if leaks else 'NONE - privacy verified')
os.remove(path)

# ---------- A: Windows E2E ----------
print()
print('--- A: Windows E2E (live) ---')

async def e2e():
    desktop = get_desktop_automation('Telegram.exe')
    c = TelegramGUIController(desktop)
    conn = await c.connect()
    print('  1. Title-independent connect:', conn)
    chats = await c.get_chats(max_chats=8)
    print('  2. Real sidebar list walk:', len(chats), 'chats (preview redacted:', str(chats[0].last_message_preview), ')')
    opened = await c.open_chat('Saved Messages')
    print('  3. Real chat-row click navigation:', opened)

asyncio.run(e2e())

# ---------- Lockout hotkeys ----------
print()
print('--- Lockout (configurable hotkeys) ---')
lock = ScreenLockout(stop_key=0x1B, pause_key=0x50, stop_key_label='ESC', pause_key_label='P')
print('  Default: stop=ESC(0x1B) pause=P(0x50) | labels: ' + lock._stop_label + '/' + lock._pause_label)
lock2 = ScreenLockout(stop_key=0x70, pause_key=0x71, stop_key_label='F1', pause_key_label='F2')
print('  Custom : stop=F1(0x70) pause=F2(0x71) | labels: ' + lock2._stop_label + '/' + lock2._pause_label)

print()
print('=' * 72)
print('ALL DONE: A DONE  B DONE  PRIVACY DONE')
print('=' * 72)
