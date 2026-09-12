#!/usr/bin/env python3
"""Fix the skull_ascii array by splitting on literal \\n and making proper array elements."""

FILE_PATH = r"C:\Users\zbook\OneDrive\Desktop\scripts\abliterated_matrix.sh"

with open(FILE_PATH, 'r') as f:
    lines = f.readlines()

# Find the skull_ascii line (line 824, 0-indexed 823)
skull_line = lines[823]

# Extract the content between the first " and last "
start = skull_line.find('"')
end = skull_line.rfind('"')
content = skull_line[start+1:end]

# Split by the literal \n pattern (the pattern is: "\n        ")
import re
# The pattern is: quote, backslash-n, spaces, quote
parts = re.split(r'"\\n\s*"', content)

# Clean up each part
cleaned = []
for p in parts:
    p = p.strip()
    if p:
        cleaned.append(p)

print(f'Found {len(cleaned)} skull lines')
for i, line in enumerate(cleaned[:5]):
    print(f'  Line {i}: {line[:80]}...')

# Build the new array
new_lines = []
new_lines.append('    local skull_ascii=(\n')
for line in cleaned:
    new_lines.append(f'        "{line}"\n')
new_lines.append('    )\n')

# Replace lines 823-825 (0-indexed 822-824)
lines[822:825] = new_lines

with open(FILE_PATH, 'w') as f:
    f.writelines(lines)

print(f'Fixed skull_ascii array. Total lines: {len(lines)}')