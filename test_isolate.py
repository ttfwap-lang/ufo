from pathlib import Path
from ufo.llm.config_helper import set_backend_selection
from ufo.config.config_loader import ConfigLoader, clear_config_cache
import tempfile
import yaml

with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    cfg_dir = base / "config"
    ufo_dir = cfg_dir / "ufo"
    ufo_dir.mkdir(parents=True)
    
    with open(ufo_dir / "system.yaml", "w") as f:
        yaml.safe_dump({"LOG_LEVEL": "INFO"}, f)
        
    ConfigLoader.get_instance(str(cfg_dir))
    
    profile_path = str(base / "custom.yaml")
    with open(profile_path, "w") as f:
        yaml.safe_dump({"HOST_AGENT": {"API_TYPE": "openai", "API_MODEL": "custom"}, "APP_AGENT": {"API_TYPE": "openai"}}, f)
        
    print("setting backend selection")
    set_backend_selection("profile", profile_path=profile_path)
    print("done")
