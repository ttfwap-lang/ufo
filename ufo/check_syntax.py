import ast
import re

for f in ["ufo_bridge.py", "gx10_runner/agent_runner.py", "astro_collect.py"]:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        print(f"[OK]   {f}")
    except SyntaxError as e:
        print(f"[FAIL] {f}: {e}")

s = open("ufo_bridge.py", encoding="utf-8").read()
print("bridge actions:", sorted(set(re.findall(r'"(\w+)": action_', s))))
r = open("gx10_runner/agent_runner.py", encoding="utf-8").read()
print("runner tools:", sorted(set(re.findall(r'"name": "(\w+)"', r))))
print("runner impls:", sorted(set(re.findall(r"^def tool_(\w+)", r, re.M))))