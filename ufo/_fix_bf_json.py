"""Fix BankFidelity JSON config paths."""
import pathlib

p = pathlib.Path('client/mcp/configs/bankfidelity.json')
text = p.read_text(encoding='utf-8')

old_cmd = r'C:\bankfidelity\bankfidelity\target\release\dual-core-pdf-pipeline.exe'
new_cmd = r'C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity\target\debug\dual-core-pdf-pipeline.exe'
old_cwd = r'C:\bankfidelity\bankfidelity'
new_cwd = r'C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity'

count_cmd = text.count(old_cmd)
count_cwd = text.count(old_cwd)
print(f"Command refs: {count_cmd}")
print(f"CWD refs: {count_cwd}")

text = text.replace(old_cmd, new_cmd)
text = text.replace(old_cwd, new_cwd)
p.write_text(text, encoding='utf-8')
print("All replacements applied.")
