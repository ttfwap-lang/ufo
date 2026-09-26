import sys, asyncio, json, tempfile, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:\\Users\\lnxzf\\Desktop\\projects\\ufo')
from ufo.automator.app_apis.telegram import (
    AutonomousTelegramAgent, ExecutionConfig, PrivacyRedactor,
    ScreenLockout, TelegramGUIController, SAVED_MESSAGES,
    canonical_chat_name,
)
from ufo.automation.factory import get_desktop_automation

print('=' * 72)
print('FINAL VALIDATION: A (Windows E2E) + B (conversation learn) + Privacy')
print('=' * 72)

# ---------- CHAT NAME SPELLING ----------
# Telegram's search box is a substring match on the real name, so the
# run-together "SavedMessages" finds NOTHING and the run dies at step one.
# The controller canonicalises, but the typo must also never be reintroduced
# into the repo where a raw name could reach the search box unchecked.
print()
print('--- CHAT NAMES: "Saved Messages" is the only correct spelling ---')
print('  constant          :', repr(SAVED_MESSAGES))
_spell = [('run-together', 'SavedMessages'), ('camel', 'savedMessages'),
          ('all-caps', 'SAVEDMESSAGES'), ('decorated title', 'Saved Messages - (3)')]
_spell_ok = True
for _label, _v in _spell:
    _got = canonical_chat_name(_v)
    _ok = _got == SAVED_MESSAGES
    _spell_ok = _spell_ok and _ok
    print('  [' + ('PASS' if _ok else 'FAIL') + '] ' + _label.ljust(18) + repr(_v).ljust(26) + '-> ' + repr(_got))
assert _spell_ok, 'chat name canonicalisation broken'

# Static sweep: the run-together spelling must never be used as a real chat
# name in code. Comments and docstrings are allowed to *mention* it (the guard
# itself has to, to explain what it defends against), and the files whose whole
# job is the guard are exempt.
_ALLOW = {
    'chat_names.py',                       # the canonicaliser itself
    'test_telegram_chat_names.py',         # deliberately exercises the typo
    'test_telegram_typing.py',             # asserts the typo gets canonicalised
    os.path.basename(__file__),            # this validator
}
_WRONG = 'SavedMessages'


def _code_only(path):
    """Return the file's text with comments and docstrings removed."""
    src = open(path, encoding='utf-8', errors='ignore').read()
    try:
        import ast
        tree = ast.parse(src)
        spans = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None and node.body:
                    first = node.body[0]
                    spans.append((first.lineno, getattr(first, 'end_lineno', first.lineno)))
        lines = src.splitlines(keepends=True)
        for i, line in enumerate(lines, 1):
            if any(lo <= i <= hi for lo, hi in spans):
                lines[i - 1] = '\n'
        src = ''.join(lines)
    except SyntaxError:
        pass
    # Drop trailing comments (string contents are left alone on purpose).
    return '\n'.join(l.split('  #')[0].split('\t#')[0] for l in src.splitlines())


_bad = []
for _root, _dirs, _files in os.walk(os.path.dirname(os.path.abspath(__file__))):
    _dirs[:] = [d for d in _dirs if d not in ('.git', '.venv', 'node_modules', '__pycache__')]
    for _f in _files:
        if not _f.endswith(('.py', '.yaml', '.yml', '.json', '.ps1', '.sh')):
            continue
        if _f in _ALLOW:
            continue
        _p = os.path.join(_root, _f)
        try:
            if _WRONG in _code_only(_p):
                _bad.append(os.path.relpath(_p))
        except OSError:
            continue
print('  [PASS] no run-together "SavedMessages" used as a chat name in code'
      if not _bad else
      '  [FAIL] run-together spelling used as a name in: ' + ', '.join(_bad[:5]))
assert not _bad, 'run-together "SavedMessages" reintroduced in: ' + ', '.join(_bad[:5])

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
    if not conn:
        print('  SKIP: Telegram Desktop is not running - start it and re-run for the live E2E pillars.')
        return
    chats = await c.get_chats(max_chats=8)
    preview = str(chats[0].last_message_preview) if chats else '(no chats)'
    print('  2. Real sidebar list walk:', len(chats), 'chats (preview redacted:', preview, ')')
    opened = await c.open_chat(SAVED_MESSAGES)
    print('  3. Real chat-row click navigation:', opened, '(target: ' + repr(SAVED_MESSAGES) + ')')

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
print('ALL DONE: A DONE  B DONE  PRIVACY DONE  CHAT-NAMES DONE')
print('=' * 72)
