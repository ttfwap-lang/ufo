"""
Debug script to examine the constellation_before and constellation_after fields
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def debug_constellation_fields(log_file_path: str):
    """Debug the constellation fields to see their actual format"""

    print(f"Reading log file: {log_file_path}\n")

    with open(log_file_path, encoding="utf-8") as f:
        lines = f.readlines()

    for line_num, line in enumerate(lines, 1):
        try:
            log_entry = json.loads(line.strip())

            print("=" * 80)
            print(f"LINE {line_num}")
            print("=" * 80)

            # Check constellation_before
            if "constellation_before" in log_entry:
                const_before = log_entry["constellation_before"]
                print("\nconstellation_before:")
                print(f"  Type: {type(const_before)}")
                if const_before:
                    print("  Is None: False")
                    if isinstance(const_before, str):
                        print(f"  Length: {len(const_before)}")
                        print(f"  First 200 chars: {const_before[:200]}")
                        # Try to detect if it's JSON or Python repr
                        if const_before.strip().startswith("{"):
                            print("  Format: Looks like JSON")
                            try:
                                parsed = json.loads(const_before)
                                print("  [OK] Valid JSON")
                            except json.JSONDecodeError as e:
                                print(f"  [FAIL] Invalid JSON: {e}")
                        else:
                            print("  Format: Looks like Python repr/str")
                else:
                    print("  Is None: True")

            # Check constellation_after
            if "constellation_after" in log_entry:
                const_after = log_entry["constellation_after"]
                print("\nconstellation_after:")
                print(f"  Type: {type(const_after)}")
                if const_after:
                    print("  Is None: False")
                    if isinstance(const_after, str):
                        print(f"  Length: {len(const_after)}")
                        print(f"  First 200 chars: {const_after[:200]}")
                        # Try to detect if it's JSON or Python repr
                        if const_after.strip().startswith("{"):
                            print("  Format: Looks like JSON")
                            try:
                                parsed = json.loads(const_after)
                                print("  [OK] Valid JSON")
                            except json.JSONDecodeError as e:
                                print(f"  [FAIL] Invalid JSON: {e}")
                        else:
                            print("  Format: Looks like Python repr/str")
                else:
                    print("  Is None: True")

            print()

        except json.JSONDecodeError as e:
            print(f"Line {line_num}: Failed to parse JSON: {e}\n")


if __name__ == "__main__":
    log_file = project_root / "logs" / "galaxy" / "task_1" / "response.log"
    debug_constellation_fields(str(log_file))
