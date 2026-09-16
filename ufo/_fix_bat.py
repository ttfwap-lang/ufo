"""Fix all hardcoded paths in ALL .bat files across the project."""
import pathlib

NEW_UFO = r'C:\Users\lnxzf\Desktop\projects\ufo'
NEW_UFO_PKG = r'C:\Users\lnxzf\Desktop\projects\ufo\ufo'
NEW_BF = r'C:\Users\lnxzf\Desktop\projects\bankfidelity\bankfidelity'
NEW_SYS_PY = r'C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe'

OLD_UFO = r'C:\ufo'
OLD_UFO_PKG = r'C:\ufo\ufo'
OLD_BF = r'C:\bankfidelity\bankfidelity'
OLD_PY_ENV = r'\python_env\python.exe'

root = pathlib.Path('.')
bat_files = list(root.rglob('*.bat'))
print(f"Found {len(bat_files)} .bat files total")

total_changes = 0
for p in bat_files:
    text = p.read_text(encoding='utf-8', errors='replace')
    original = text
    
    # Replace python_env\python.exe with system python
    text = text.replace(OLD_PY_ENV, r'\python_env\python.exe')  # protect first
    
    # Fix python_env python refs - replace the whole python_env path
    text = text.replace(r'%UFO_ROOT%\python_env\python.exe', NEW_SYS_PY)
    text = text.replace(r'C:\ufo\ufo\python_env\python.exe', NEW_SYS_PY)
    text = text.replace(r'C:\Users\lnxzf\Desktop\projects\ufo\ufo\python_env\python.exe', NEW_SYS_PY)
    
    # Restore protected ones (those that might need python_env in a different context)
    text = text.replace(r'\python_env\python.exe', OLD_PY_ENV)
    
    # Replace UFO paths (do longest first: C:\ufo\ufo before C:\ufo)
    text = text.replace(OLD_UFO_PKG, NEW_UFO_PKG)
    text = text.replace(OLD_UFO, NEW_UFO)
    
    # Replace BankFidelity paths
    text = text.replace(OLD_BF, NEW_BF)
    
    if text != original:
        changes = sum(1 for a, b in zip(original.splitlines(), text.splitlines()) if a != b)
        p.write_text(text, encoding='utf-8')
        print(f"  {p}: {changes} lines changed")
        total_changes += changes

print(f"\nTotal changes: {total_changes}")

# Verify
needle = chr(67) + chr(58) + chr(92) + chr(117) + chr(102) + chr(111)
needle_bf = chr(67) + chr(58) + chr(92) + chr(98) + chr(97) + chr(110) + chr(107)
remaining = 0
for p in bat_files:
    text = p.read_text(encoding='utf-8', errors='replace')
    cnt = text.count(needle) + text.count(needle_bf)
    if cnt > 0:
        print(f"  REMAINING in {p}: {cnt}")
        remaining += cnt
print(f"Total remaining old path refs: {remaining}")
