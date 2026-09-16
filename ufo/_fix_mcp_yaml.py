"""Fix all hardcoded paths in config/ufo/mcp.yaml."""
import pathlib

p = pathlib.Path('config/ufo/mcp.yaml')
text = p.read_text(encoding='utf-8')

old_python = r'C:\ufo\ufo\python_env\python.exe'
# Use %USERPROFILE% env var so it's robust across machines
new_python = r'%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe'
# Actually for YAML config, env var expansion is handled by the config loader,
# so use the expanded form directly for reliability
new_python = r'C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe'

old_bf_cmd = r'C:\bankfidelity\bankfidelity\target\release\dual-core-pdf-pipeline.exe'
new_bf_cmd = r'C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity\target\debug\dual-core-pdf-pipeline.exe'

old_bf_cwd = r'C:\bankfidelity\bankfidelity'
new_bf_cwd = r'C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity'

count_py = text.count(old_python)
count_bf_cmd = text.count(old_bf_cmd)
count_bf_cwd = text.count(old_bf_cwd)
print(f"Python exe refs: {count_py}")
print(f"BF command refs: {count_bf_cmd}")
print(f"BF cwd refs: {count_bf_cwd}")

text = text.replace(old_python, new_python)
text = text.replace(old_bf_cmd, new_bf_cmd)
text = text.replace(old_bf_cwd, new_bf_cwd)

p.write_text(text, encoding='utf-8')
print("All replacements applied.")

# Verify
needle = chr(67) + chr(58) + chr(92) + chr(117) + chr(102) + chr(111)
print(f"Remaining C:\\ufo refs: {text.count(needle)}")
needle_bf = r'C:\bankfidelity\bankfidelity'
print(f"Remaining old BF refs: {text.count(needle_bf)}")
