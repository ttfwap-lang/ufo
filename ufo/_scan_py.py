r"""Find all remaining hardcoded path references in Python files."""
import pathlib

needle_ufo = chr(67) + chr(58) + chr(92) + chr(117) + chr(102) + chr(111)
needle_bf = chr(67) + chr(58) + chr(92) + chr(98) + chr(97) + chr(110) + chr(107)
needle_py_env = r'C:\ufo\ufo\python_env'
needle_py_env2 = r'C:\Users\lnxzf\Desktop\projects\ufo\ufo\python_env'

root = pathlib.Path('.')
py_files = list(root.rglob('*.py'))
print(f"Scanning {len(py_files)} .py files...")

for p in py_files:
    if p.name.startswith('_fix_') or p.name.startswith('_path_check') or p.name.startswith('_env_check') or p.name.startswith('_search_paths') or p.name.startswith('_read_env') or p.name.startswith('_scan_py'):
        continue
    text = p.read_text(encoding='utf-8', errors='replace')
    cnt_ufo = text.count(needle_ufo)
    cnt_bf = text.count(needle_bf)
    cnt_py = text.count(needle_py_env) + text.count(needle_py_env2)
    if cnt_ufo > 0 or cnt_bf > 0 or cnt_py > 0:
        print(f'{p}: UFO={cnt_ufo}, BF={cnt_bf}, python_env={cnt_py}')
        for i, line in enumerate(text.splitlines(), 1):
            if needle_ufo in line or needle_bf in line or needle_py_env in line or needle_py_env2 in line:
                print(f'  L{i}: {line[:120]}')
