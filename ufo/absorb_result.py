import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import AutonomousTelegramAgent, ExecutionConfig

agent = AutonomousTelegramAgent(config=ExecutionConfig())
stats = agent.learn_patterns_from_conversation(
    r"C:\Users\lnxzf\Desktop\projects\ufo\result.json",
    skill_name="imported-conversation",
)
print("=== LEARNED (abstract only) ===")
print("messages_scanned :", stats.get("messages_scanned"))
print("user cmd shapes  :", stats.get("command_patterns"))
print("bot resp types   :", stats.get("response_patterns"))
print("error keywords   :", stats.get("error_keywords"))
print("transitions (top):", json.dumps(stats.get("transitions", {}), ensure_ascii=False)[:700])
print("rate limits      :", stats.get("rate_limits"))
print("buttons seen     :", stats.get("button_structures"))
print()
print("recommended delay:", agent.current_skill.learned_facts.get("recommended_delay_between_requests_seconds"))
print()
print("=== PRIVACY VERIFICATION ===")
dump = json.dumps(agent.current_skill.to_dict(), ensure_ascii=False)
probes = [
    ("card bin 419984", "419984"),
    ("card bin 498503", "498503"),
    ("callback b64", "Q0FSRF8"),
    ("card holder", "Ace*****"),
    ("order id text", "Order ID"),
    ("base name", "2026_04_19_US"),
    ("bin 553435", "553435"),
    ("email-ish", "@gmail"),
    ("slashcmd /start", "/start"),
    ("view bins text", "View Bins"),
]
print("Content leak scan of saved skill:")
leaks = []
for label, needle in probes:
    found = needle in dump
    if found:
        leaks.append((label, needle))
    print("  {:20s} ({!r}): {}".format(label, needle, "LEAKED!" if found else "clean"))
print()
print("VERDICT:", "NO CONTENT LEAKS - privacy preserved" if not leaks else "LEAKS FOUND: {}".format(leaks))
