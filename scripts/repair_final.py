#!/usr/bin/env python3
"""Comprehensive line-by-line repair of abliterated_matrix.sh."""

import re

FILE_PATH = r"C:\Users\zbook\OneDrive\Desktop\scripts\abliterated_matrix.sh"

def repair():
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Track all fixes applied
    fixes = []

    def fix(line, idx):
        original = line

        # Fix ABL_ABL_ABL_ -> ABL_
        if 'ABL_ABL_ABL_' in line:
            line = line.replace('ABL_ABL_ABL_', 'ABL_')
            fixes.append(f"Line {idx}: ABL_ABL_ABL_ -> ABL_")

        # Fix ABL_ABL_ -> ABL_ (but not ABL_ABL_C_ which might be intentional? No, it's not)
        if 'ABL_ABL_' in line:
            line = line.replace('ABL_ABL_', 'ABL_')
            fixes.append(f"Line {idx}: ABL_ABL_ -> ABL_")

        # Fix abl_abl_abl_ -> abl_
        if 'abl_abl_abl_' in line:
            line = line.replace('abl_abl_abl_', 'abl_')
            fixes.append(f"Line {idx}: abl_abl_abl_ -> abl_")

        # Fix abl_abl_ -> abl_
        if 'abl_abl_' in line:
            line = line.replace('abl_abl_', 'abl_')
            fixes.append(f"Line {idx}: abl_abl_ -> abl_")

        return line

    # First pass: fix prefixes
    for i, line in enumerate(lines, 1):
        lines[i-1] = fix(line, i)

    # Second pass: fix specific issues
    for i, line in enumerate(lines, 1):
        # Fix show_help double quote
        if line.count('"') > 2 and 'Usage:' in line:
            lines[i-1] = line.replace('"Usage: $0 [OPTIONS]""', '"Usage: $0 [OPTIONS]"')
            fixes.append(f"Line {i}: Fixed double quote in show_help")

        # Fix show_help return/exit
        if line.strip() == 'exit 0' and i+1 <= len(lines) and lines[i].strip() == '}':
            lines[i-1] = '    (( _ABL_IS_SOURCED )) && return 0 || exit 0\n'
            fixes.append(f"Line {i}: show_help exit -> return/exit")

        # Fix W and H references
        if '$W' in lines[i-1] or '${W}' in lines[i-1] or ' W' in lines[i-1] or ' W;' in lines[i-1]:
            old = lines[i-1]
            lines[i-1] = lines[i-1].replace('$W', '$ABL_W')
            lines[i-1] = lines[i-1].replace('${W}', '${ABL_W}')
            lines[i-1] = lines[i-1].replace(' W;', ' ABL_W;')
            lines[i-1] = lines[i-1].replace(' W,', ' ABL_W,')
            lines[i-1] = lines[i-1].replace(' W)', ' ABL_W)')
            lines[i-1] = lines[i-1].replace('(W', '(ABL_W')
            lines[i-1] = lines[i-1].replace(' W>', ' ABL_W>')
            lines[i-1] = lines[i-1].replace('>W', '>ABL_W')
            lines[i-1] = lines[i-1].replace(' W<', ' ABL_W<')
            lines[i-1] = lines[i-1].replace('<W', '<ABL_W')
            lines[i-1] = lines[i-1].replace(' W=', ' ABL_W=')
            lines[i-1] = lines[i-1].replace('=W', '=ABL_W')
            if old != lines[i-1]:
                fixes.append(f"Line {i}: Fixed W -> ABL_W")

        if '$H' in lines[i-1] or '${H}' in lines[i-1] or ' H' in lines[i-1]:
            old = lines[i-1]
            lines[i-1] = lines[i-1].replace('$H', '$ABL_H')
            lines[i-1] = lines[i-1].replace('${H}', '${ABL_H}')
            lines[i-1] = lines[i-1].replace(' H;', ' ABL_H;')
            lines[i-1] = lines[i-1].replace(' H,', ' ABL_H,')
            lines[i-1] = lines[i-1].replace(' H)', ' ABL_H)')
            lines[i-1] = lines[i-1].replace('(H', '(ABL_H')
            lines[i-1] = lines[i-1].replace(' H>', ' ABL_H>')
            lines[i-1] = lines[i-1].replace('>H', '>ABL_H')
            lines[i-1] = lines[i-1].replace(' H<', ' ABL_H<')
            lines[i-1] = lines[i-1].replace('<H', '<ABL_H')
            lines[i-1] = lines[i-1].replace(' H=', ' ABL_H=')
            lines[i-1] = lines[i-1].replace('=H', '=ABL_H')
            if old != lines[i-1]:
                fixes.append(f"Line {i}: Fixed H -> ABL_H")

        # Fix ESC
        if '${ESC}' in lines[i-1]:
            lines[i-1] = lines[i-1].replace('${ESC}[', '${ABL_ESC}[')
            fixes.append(f"Line {i}: Fixed ${ESC} -> ${ABL_ESC}")

        # Fix color variables
        color_fixes = [
            ('$C_RESET', '$ABL_C_RESET'),
            ('$C_BOLD', '$ABL_C_BOLD'),
            ('$C_DIM', '$ABL_C_DIM'),
            ('$C_WHITE_PEAK', '$ABL_C_WHITE_PEAK'),
            ('$C_WHITE', '$ABL_C_WHITE'),
            ('$C_GREEN_NEON', '$ABL_C_GREEN_NEON'),
            ('$C_GREEN_BRIGHT', '$ABL_C_GREEN_BRIGHT'),
            ('$C_GREEN_MID', '$ABL_C_GREEN_MID'),
            ('$C_GREEN_DARK', '$ABL_C_GREEN_DARK'),
            ('$C_GREEN_MUTED', '$ABL_C_GREEN_MUTED'),
            ('$C_CYAN', '$ABL_C_CYAN'),
            ('$C_RED', '$ABL_C_RED'),
            ('$C_MAGENTA', '$ABL_C_MAGENTA'),
            ('$C_YELLOW', '$ABL_C_YELLOW'),
        ]
        for old, new in color_fixes:
            if old in lines[i-1] and new not in lines[i-1]:
                lines[i-1] = lines[i-1].replace(old, new)
                fixes.append(f"Line {i}: {old} -> {new}")

        # Fix unprefixed variable assignments
        var_fixes = [
            ('SPEED_MULTIPLIER=', 'ABL_SPEED_MULTIPLIER='),
            ('GENERATE_GRID=', 'ABL_GENERATE_GRID='),
            ('ARTIFACT_ROOT=', 'ABL_ARTIFACT_ROOT='),
            ('COLUMNS_INITIALIZED=', 'ABL_COLUMNS_INITIALIZED='),
            ('CURRENT_SEC=', 'ABL_CURRENT_SEC='),
            ('NUM_KATAKANA=', 'ABL_NUM_KATAKANA='),
            ('NUM_ASCII=', 'ABL_NUM_ASCII='),
            ('GLYPHS_KATAKANA=', 'ABL_GLYPHS_KATAKANA='),
            ('GLYPHS_ASCII=', 'ABL_GLYPHS_ASCII='),
            ('USE_KATAKANA=', 'ABL_USE_KATAKANA='),
        ]
        for old, new in var_fixes:
            if old in lines[i-1] and new not in lines[i-1]:
                lines[i-1] = lines[i-1].replace(old, new)
                fixes.append(f"Line {i}: {old} -> {new}")

        # Fix function calls
        func_fixes = [
            ('cleanup()', 'abl_cleanup()'),
            ('cleanup ;', 'abl_cleanup ;'),
            ('safe_sleep ', 'abl_safe_sleep '),
            ('write_centered', 'abl_write_centered'),
            ('advance_timeline', 'abl_advance_timeline'),
            ('post_execution_artifacts', 'abl_post_execution_artifacts'),
            ('parse_args', 'abl_parse_args'),
            ('run_matrix_rain', 'abl_run_matrix_rain'),
        ]
        for old, new in func_fixes:
            if old in lines[i-1] and new not in lines[i-1]:
                lines[i-1] = lines[i-1].replace(old, new)
                fixes.append(f"Line {i}: {old} -> {new}")

        # Fix show_help function name
        if line.strip().startswith('show_help()'):
            lines[i-1] = lines[i-1].replace('show_help()', 'abl_show_help()')
            fixes.append(f"Line {i}: show_help() -> abl_show_help()")

    # Third pass: fix specific known issues
    for i, line in enumerate(lines, 1):
        # Fix skull backslash issue (I-29)
        if '${line//\\@/' in line:
            lines[i-1] = line.replace('${line//\\@/${ABL_C_WHITE_PEAK}@${ABL_C_GREEN_DARK}}',
                                      '${line//@/${ABL_C_WHITE_PEAK}@${ABL_C_GREEN_DARK}}')
            fixes.append(f"Line {i}: Fixed skull \\@ backslash")
        if '${c_line//\\%/' in line:
            lines[i-1] = line.replace('${c_line//\\%/${ABL_C_GREEN_BRIGHT}%${ABL_C_GREEN_DARK}}',
                                      '${c_line//%/${ABL_C_GREEN_BRIGHT}%${ABL_C_GREEN_DARK}}')
            fixes.append(f"Line {i}: Fixed skull \\% backslash")
        if '${c_line//\\#/' in line:
            lines[i-1] = line.replace('${c_line//\\#/${ABL_C_GREEN_MID}#${ABL_C_GREEN_DARK}}',
                                      '${c_line//#/${ABL_C_GREEN_MID}#${ABL_C_GREEN_DARK}}')
            fixes.append(f"Line {i}: Fixed skull \\# backslash")
        if '${c_line//\\*/' in line:
            lines[i-1] = line.replace('${c_line//\\*/${ABL_C_RED}*${ABL_C_GREEN_DARK}}',
                                      '${c_line//*/${ABL_C_RED}*${ABL_C_GREEN_DARK}}')
            fixes.append(f"Line {i}: Fixed skull \\* backslash")
        if '${c_line//\\=/' in line:
            lines[i-1] = line.replace('${c_line//\\=/${ABL_C_GREEN_NEON}=${ABL_C_GREEN_DARK}}',
                                      '${c_line//=/${ABL_C_GREEN_NEON}=${ABL_C_GREEN_DARK}}')
            fixes.append(f"Line {i}: Fixed skull \\= backslash")

        # Fix echo -e to printf (I-10)
        if 'echo -e "$grid"' in line:
            lines[i-1] = line.replace('echo -e "$grid"', 'printf "%b\\n" "$grid"')
            fixes.append(f"Line {i}: echo -e -> printf")

        # Fix division by zero (I-18)
        if 'active_count * 100 / W' in line:
            lines[i-1] = line.replace('active_count * 100 / W',
                                      'active_count * 100 / ABL_W')
            fixes.append(f"Line {i}: Fixed division by zero guard")

    # Fourth pass: specific pattern fixes
    for i, line in enumerate(lines, 1):
        # Fix running=1 dead code (I-33)
        if 'local running=1' in line and 'while (( running ));' in lines[i]:
            lines[i-1] = ''  # Remove the line
            fixes.append(f"Line {i}: Removed dead running=1 variable")

        # Fix while (( running )) to while :
        if 'while (( running ));' in line:
            lines[i-1] = line.replace('while (( running ));', 'while :;')
            fixes.append(f"Line {i}: while (( running )) -> while :")

        # Fix force_reinit in abl_run_matrix_rain
        if 'abl_run_matrix_rain()' in line and 'force_reinit' not in line:
            lines[i-1] = line.replace('local interactive="$3"',
                                      'local interactive="$3"\n    local force_reinit="${4:-0}"')
            fixes.append(f"Line {i}: Added force_reinit parameter")

        # Fix COLUMNS_INITIALIZED reset
        if '(( COLUMNS_INITIALIZED != 1 ))' in line and 'force_reinit' not in line:
            lines[i-1] = line.replace('(( COLUMNS_INITIALIZED != 1 ))',
                                      '(( force_reinit )) && ABL_COLUMNS_INITIALIZED=0\n    (( ABL_COLUMNS_INITIALIZED != 1 ))')
            fixes.append(f"Line {i}: Added force_reinit check")

    # Write back
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    print(f'Repair complete. Total lines: {len(lines)}')
    print(f'Fixes applied: {len(fixes)}')
    for fix in fixes[:50]:
        print(f'  {fix}')
    if len(fixes) > 50:
        print(f'  ... and {len(fixes)-50} more')

    # Verify no triple/double prefixes remain
    content = ''.join(lines)
    issues = []
    for i, line in enumerate(lines, 1):
        if 'ABL_ABL_ABL_' in line:
            issues.append(f'Line {i}: ABL_ABL_ABL_ prefix remains')
        if 'abl_abl_abl_' in line:
            issues.append(f'Line {i}: abl_abl_abl_ prefix remains')
        if 'ABL_ABL_' in line:
            issues.append(f'Line {i}: ABL_ABL_ prefix remains')
        if 'abl_abl_' in line:
            issues.append(f'Line {i}: abl_abl_ prefix remains')

    if issues:
        print('\nREMAINING PREFIX ISSUES:')
        for issue in issues[:20]:
            print(f'  {issue}')
    else:
        print('\nNo prefix issues found!')

if __name__ == '__main__':
    repair()
