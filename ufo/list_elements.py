"""List OmniParser elements in a region of a capture (diagnostic helper)."""
import sys

import venus_client as vc

path = sys.argv[1]
min_x = int(sys.argv[2]) if len(sys.argv) > 2 else 0
min_y = int(sys.argv[3]) if len(sys.argv) > 3 else 0

els = vc.omniparser_elements(path)
print(f"{len(els)} elements in {path}")
for e in els:
    b = e["bbox_xywh"]
    if b[0] >= min_x and b[1] >= min_y:
        print(f"  id={str(e['id']):>3} xywh={str(b):22} "
              f"centre=({e['cx']},{e['cy']}) {e['content'][:64]!r}")
