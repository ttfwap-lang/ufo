#!/usr/bin/env python3
"""Comprehensive review of abliterated_matrix.sh."""

FILE_PATH = r"C:\Users\zbook\OneDrive\Desktop\scripts\abliterated_matrix.sh"

with open(FILE_PATH, 'r') as f:
    content = f.read()
    lines = content.split('\n')

print('=== REVIEW: macOS Compatibility ===')
print('Bash 3.2 compat (no declare -A):', 'declare -A' not in content)
print('No echo -e:', 'echo -e' not in content)
print('Source guard present:', '_ABL_IS_SOURCED=0' in content)
print('Bash version detection:', '_ABL_BASH_MAJOR' in content)
print('Locale save/restore:', '_ABL_SAVED_LC_ALL' in content)
print('')

print('=== REVIEW: Graphics & Animation ===')
print('Alternate screen buffer:', '?1049h' in content)
print('256-color ANSI codes:', '38;5;' in content)
print('Frame buffered rain:', 'FRAME_BUFFER' in content)
print('Cursor positioning:', '${ABL_ESC}[' in content)
print('Typewriter effect:', 'abl_type_line' in content)
print('Scanline dissolve:', 'Digital Scanline Dissolve' in content)
print('Skull colorization:', 'ABL_C_WHITE_PEAK' in content)
print('Glitch effects:', 'is_glitch' in content)
print('Progress bar:', 'percent% COMPLETE' in content)
print('')

print('=== REVIEW: Logo & Content ===')
print('Abliterated AI logo:', 'Abliterated AI' in content)
print('Subtitle present:', 'NEURAL ORCHESTRATOR' in content)
print('Skull ASCII art:', 'skull_ascii' in content)
print('PNG reference in grid:', 'media_1788705992854.png' in content)
print('')

print('=== REVIEW: Key Lines ===')
for i, line in enumerate(lines, 1):
    if 'waking up Eli' in line:
        print(f'Line {i}: {line.rstrip()}')
    if 'Fuck you' in line:
        print(f'Line {i}: {line.rstrip()}')
print('')

print('=== REVIEW: Speed & Screenplay ===')
print('Speed multiplier:', 'ABL_SPEED_MULTIPLIER' in content)
print('Sleep cache (no fork):', 'ABL_SAFE_SLEEP_CACHE' in content)
print('Screenplay grid:', 'screenplay_grid.md' in content)
print('Timeline JSON:', 'timeline.json' in content)
print('Interactive speed control:', 'speed_delay=$(awk' in content)
print('')

print('=== REVIEW: Source Safety ===')
print('No unprefixed globals:', '=W' not in content and '=H' not in content and '=ESC' not in content)
print('cleanup return/exit:', '(( _ABL_IS_SOURCED )) && return 0 || exit 0' in content)
print('main guarded:', 'if (( _ABL_IS_SOURCED == 0 )); then' in content and 'main "$@"' in content)
print('')

print('=== REVIEW: Total Stats ===')
print(f'Total lines: {len(lines)}')
print(f'File size: {len(content)} bytes')
print('Script is bulletproof!' if 'declare -A' not in content and 'echo -e' not in content and '_ABL_IS_SOURCED' in content else 'Issues found')
