r"""Comprehensive scan for ALL remaining old path references."""
import pathlib

root = pathlib.Path('.')

# Build search needles using chr() to avoid unicode escapes
ufo = chr(67) + chr(58) + chr(92) + chr(117) + chr(102) + chr(111)  # C:\ufo
bf = chr(67) + chr(58) + chr(92) + chr(98) + chr(97) + chr(110) + chr(107) + chr(102) + chr(105) + chr(100) + chr(101) + chr(108) + chr(105) + chr(116) + chr(121)  # C:\bankfidelity
py_env = r'python_env\python.exe'
py_env2 = r'python_env/python.exe'

needles = [ufo, bf, py_env, py_env2]
extensions = ['*.py', '*.yaml', '*.yml', '*.json', '*.ps1', '*.bat', '*.toml', '*.cfg', '*.ini', '*.md', '*.rst', '*.txt']

skip_patterns = ['_scan_all', '_fix_', '_path_check', '_env_check', '_search_paths', '_read_env',
                 '.venv_e2e', 'node_modules', '__pycache__']

found = 0
for ext in extensions:
    for p in root.rglob(ext):
        if any(s in str(p) for s in skip_patterns):
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        for needle in needles:
            cnt = text.count(needle)
            if cnt > 0:
                found += 1
                # Show first few matching lines
                matching = [f'  L{i}: {line[:110]}' for i, line in enumerate(text.splitlines(), 1) if needle in line]
                print(f'{p}: [{needle}] x{cnt} -- {len(matching)} lines')
                for m in matching[:3]:
                    print(m)

print(f"\nTotal files with remaining refs: {found}")
