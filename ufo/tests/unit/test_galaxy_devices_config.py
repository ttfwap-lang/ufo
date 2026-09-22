"""config/galaxy/devices.yaml lists only real devices, and secrets come from the environment."""
from pathlib import Path

from ufo.galaxy.client.config_loader import ConstellationConfig

DEVICES_YAML = Path(__file__).resolve().parents[2] / "config" / "galaxy" / "devices.yaml"


def _load(monkeypatch, **env):
    for key in ("UFO_DGX_WS_TOKEN", "UFO_WIN_WS_TOKEN", "UFO_GALAXY_AUTO_CONNECT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return ConstellationConfig.from_yaml(str(DEVICES_YAML))


def test_only_real_devices_without_duplicate_endpoints(monkeypatch):
    cfg = _load(monkeypatch)
    assert [d.device_id for d in cfg.devices] == ["windowsagent", "dgx_gx10"]
    bases = [d.server_url.split("?")[0] for d in cfg.devices]
    assert len(set(bases)) == len(bases)


def test_tokens_expand_from_environment(monkeypatch):
    cfg = _load(monkeypatch, UFO_DGX_WS_TOKEN="dgx-secret", UFO_WIN_WS_TOKEN="win-secret")
    urls = {d.device_id: d.server_url for d in cfg.devices}
    assert urls["dgx_gx10"].endswith("token=dgx-secret")
    assert urls["windowsagent"].endswith("token=win-secret")
    assert "secret" not in DEVICES_YAML.read_text(encoding="utf-8")


def test_auto_connect_override(monkeypatch):
    auto = {d.device_id: d.auto_connect for d in _load(monkeypatch).devices}
    assert auto == {"windowsagent": False, "dgx_gx10": True}
    auto = {d.device_id: d.auto_connect for d in _load(monkeypatch, UFO_GALAXY_AUTO_CONNECT="windowsagent").devices}
    assert auto["windowsagent"] is True
