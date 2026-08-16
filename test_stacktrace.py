import traceback
import sys
import threading
import time
import os
import tempfile
import yaml
from pathlib import Path
from ufo.llm.config_helper import set_backend_selection
from ufo.config.config_loader import ConfigLoader

td = tempfile.TemporaryDirectory()
base = Path(td.name)
cfg_dir = base / 'config'
ufo_dir = cfg_dir / 'ufo'
ufo_dir.mkdir(parents=True)
(ufo_dir / 'system.yaml').write_text('LOG_LEVEL: INFO')
ConfigLoader.get_instance(str(cfg_dir))
profile_path = str(base / 'custom.yaml')
Path(profile_path).write_text('HOST_AGENT:\n  API_TYPE: openai\n  API_MODEL: custom\nAPP_AGENT:\n  API_TYPE: openai\n')

def t():
    set_backend_selection('profile', profile_path=profile_path)

th = threading.Thread(target=t)
th.start()
th.join(2)

if th.is_alive():
    print("Hung!")
    for tid, frame in sys._current_frames().items():
        print(f"Thread {tid}:")
        traceback.print_stack(frame)
    os._exit(1)
else:
    print("Did not hang")
