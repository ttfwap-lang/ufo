import sys
from pathlib import Path

# Fix sys.path for test discovery so c:\ufo is at sys.path[0]
# Prevents tests/config and tests/aip from shadowing root packages config and aip
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if sys.path[0] != root_dir:
    if root_dir in sys.path:
        sys.path.remove(root_dir)
    sys.path.insert(0, root_dir)
