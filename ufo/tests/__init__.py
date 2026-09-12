# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
UFO Tests Package

This package contains all tests for the UFO framework.
"""

import sys
from pathlib import Path
root_dir = str(Path(__file__).parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

