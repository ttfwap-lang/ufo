import os, re, sys

patterns = [
    re.compile(r'[A-Z]:\\ufo', re.IGNORECASE),
    re.compile(r'[A-Z]:\\bankfidelity', re.IGNORECASE),
    re.compile(r'[A-Z]:/ufo', re.IGNORECASE),
    re.compile(r'[A-Z]:/bankfidelity', re.IGNORECASE),
    re.compile(r'C:\\\\ufo', re.IGNORECASE),
    re.compile(r'C:\\\\bankfidelity', re.IGNORECASE),
]

results = []
skip_ext = {'.pyc', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.db'}
skip_dirs = {'.git', '__pycache__', '.poolside', 'node_modules', 'venv', 'env', 'logs'}

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
    for fname in files:
        fpath = os.path.join(root, fname)
        if os.path.splitext(fname)[1].lower() in skip_ext:
            continue
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    for pat in patterns:
                        if pat.search(line):
                            results.append(f'{fpath}:{i}: {line.strip()[:150]}')
                            break
        except:
            pass

print(f'Total hardcoded path refs: {len(results)}')
for r in results:
    # Sanitize non-ASCII chars
    clean = r.encode('ascii', 'replace').decode('ascii')
    print(clean)
