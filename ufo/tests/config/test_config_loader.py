# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Test suite for configuration loading with backward compatibility.

Tests cover:
- Configuration loading from new and legacy paths
- Priority chain (new > legacy > env)
- Conflict detection and warnings
- Configuration merging
- Type-safe and dynamic access
- Environment-specific overrides
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


class TestConfigLoader(unittest.TestCase):
    """Test ConfigLoader class."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        from ufo.config.config_loader import clear_config_cache
        self.addCleanup(clear_config_cache)

        # Change to test directory
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.addCleanup(os.chdir, self.original_cwd)
        
        # Ensure singleton uses test directory
        from ufo.config.config_loader import ConfigLoader, clear_config_cache
        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")

    def create_config_file(self, path: str, content: dict):
        """Helper to create a config file."""
        file_path = Path(self.test_dir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)
        return file_path

    def test_load_new_config_only(self):
        """Test loading from new config path only."""
        # Create new config
        new_config = {
            "HOST_AGENT": {"API_TYPE": "openai", "API_MODEL": "gpt-4o"},
            "MAX_STEP": 50,
        }
        self.create_config_file("config/ufo/test.yaml", new_config)

        # Load config
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")
        config_data = loader._load_with_fallback("ufo")

        # Verify
        self.assertEqual(config_data["MAX_STEP"], 50)
        self.assertEqual(config_data["HOST_AGENT"]["API_TYPE"], "openai")

    def test_deep_merge_configs(self):
        """Test deep merging of nested configurations in config/ufo."""
        # Create base config
        config1 = {
            "HOST_AGENT": {
                "API_TYPE": "aoai",
                "API_KEY": "sk-123",
            }
        }
        self.create_config_file("config/ufo/01_base.yaml", config1)

        # Create overriding config with additional fields
        config2 = {"HOST_AGENT": {"API_TYPE": "openai", "API_MODEL": "gpt-4o"}}
        self.create_config_file("config/ufo/02_override.yaml", config2)

        # Load config
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")
        config_data = loader._load_with_fallback("ufo")

        # Verify deep merge: HOST_AGENT should contain keys from both configs
        self.assertIn("HOST_AGENT", config_data)
        host = config_data["HOST_AGENT"]
        self.assertIn("API_TYPE", host)
        self.assertEqual(host["API_TYPE"], "openai")  # 02_override overrides 01_base
        self.assertIn("API_MODEL", host)  # From 02_override
        self.assertIn("API_KEY", host)  # From 01_base

    def test_multiple_yaml_files_merge(self):
        """Test merging multiple YAML files in same directory."""
        # Create multiple config files
        config1 = {"HOST_AGENT": {"API_TYPE": "openai"}}
        config2 = {"APP_AGENT": {"API_TYPE": "aoai"}}
        config3 = {"MAX_STEP": 50}

        self.create_config_file("config/ufo/agents.yaml", config1)
        self.create_config_file("config/ufo/system.yaml", config3)
        self.create_config_file("config/ufo/backup.yaml", config2)

        # Load config
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")
        config_data = loader._load_with_fallback("ufo")

        # Verify all files merged
        self.assertIn("HOST_AGENT", config_data)
        self.assertIn("APP_AGENT", config_data)
        self.assertEqual(config_data["MAX_STEP"], 50)

    def test_environment_overrides(self):
        """Test environment-specific configuration overrides."""
        # Create base config
        base_config = {"MAX_STEP": 50, "TIMEOUT": 60}
        self.create_config_file("config/ufo/config.yaml", base_config)

        # Create dev override
        dev_config = {"MAX_STEP": 100}  # Override MAX_STEP
        self.create_config_file("config/ufo/config_dev.yaml", dev_config)

        # Load with dev environment
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")
        config_data = loader._load_with_fallback("ufo", env="dev")

        # Verify override: both keys should be present
        self.assertIn("MAX_STEP", config_data)
        self.assertIn("TIMEOUT", config_data)
        self.assertEqual(config_data["MAX_STEP"], 100)
        self.assertEqual(config_data["TIMEOUT"], 60)

    def test_no_config_found_error(self):
        """Test error when no configuration is found."""
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")

        # Should raise FileNotFoundError
        with self.assertRaises(FileNotFoundError) as context:
            loader._load_with_fallback("ufo")

        self.assertIn("No configuration found", str(context.exception))

    def test_yaml_parsing_error_handling(self):
        """Test handling of invalid YAML files."""
        # Create a valid YAML file and an invalid one
        valid_path = Path(self.test_dir) / "config/ufo/valid.yaml"
        valid_path.parent.mkdir(parents=True, exist_ok=True)
        with open(valid_path, "w", encoding="utf-8") as f:
            yaml.dump({"VALID_KEY": "valid_value"}, f)

        invalid_path = Path(self.test_dir) / "config/ufo/invalid.yaml"
        with open(invalid_path, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: content: [")

        # Load should handle error gracefully - skip invalid, load valid
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")
        # Should not crash, just skip invalid file and load valid one
        config_data = loader._load_with_fallback("ufo")
        # Should have loaded the valid file
        self.assertIsInstance(config_data, dict)
        self.assertEqual(config_data.get("VALID_KEY"), "valid_value")

    def test_cache_mechanism(self):
        """Test configuration caching."""
        # Create config
        config = {"MAX_STEP": 50}
        config_path = self.create_config_file("config/ufo/test.yaml", config)

        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")

        # Load twice
        config1 = loader._load_yaml(config_path)
        config2 = loader._load_yaml(config_path)

        # Should return same object from cache
        self.assertIs(config1, config2)

    def test_explicit_env_override(self):
        """Test explicit UFO_* environment variable overrides."""
        self.create_config_file("config/ufo/test.yaml", {"MAX_STEP": 50, "SYSTEM": {"LOG_LEVEL": "INFO"}})

        from ufo.config.config_loader import ConfigLoader

        with patch.dict(os.environ, {"UFO_MAX_STEP": "100", "UFO_SYSTEM__LOG_LEVEL": "DEBUG"}):
            loader = ConfigLoader(base_path=f"{self.test_dir}/config")
            config = loader.load_ufo_config()
            self.assertEqual(config.system.max_step, 100)
            self.assertEqual(config.system.log_level, "DEBUG")

    def test_domain_scoped_env_overrides(self):
        """Test that UFO_ overrides only affect UFO config and GALAXY_ only affects Galaxy config."""
        self.create_config_file("config/ufo/test.yaml", {"MAX_STEP": 50})
        self.create_config_file("config/galaxy/agent.yaml", {
            "CONSTELLATION_AGENT": {"API_TYPE": "azure_ad", "API_MODEL": "gpt-4o"},
            "DEVICE_INFO": "devices.yaml"
        })

        env_patch = {
            "UFO_MAX_STEP": "99",
            "UFO_CUSTOM_KEY": "ufo_val",
            "GALAXY_DEVICE_INFO": "custom_devices.yaml",
            "GALAXY_CUSTOM_KEY": "galaxy_val",
            "UFO_ENV": "production",
        }

        from ufo.config.config_loader import ConfigLoader

        with patch.dict(os.environ, env_patch):
            loader = ConfigLoader(base_path=f"{self.test_dir}/config")
            ufo_cfg = loader.load_ufo_config()
            galaxy_cfg = loader.load_galaxy_config()

            # UFO config checks: UFO_MAX_STEP overrides MAX_STEP, UFO_CUSTOM_KEY sets CUSTOM_KEY
            self.assertEqual(ufo_cfg.system.max_step, 99)
            self.assertEqual(ufo_cfg["CUSTOM_KEY"], "ufo_val")
            self.assertNotIn("GALAXY_DEVICE_INFO", ufo_cfg)
            self.assertNotIn("GALAXY_CUSTOM_KEY", ufo_cfg)
            self.assertNotIn("ENV", ufo_cfg)

            # Galaxy config checks: GALAXY_DEVICE_INFO overrides DEVICE_INFO, GALAXY_CUSTOM_KEY sets CUSTOM_KEY
            self.assertEqual(galaxy_cfg.DEVICE_INFO, "custom_devices.yaml")
            self.assertEqual(galaxy_cfg["CUSTOM_KEY"], "galaxy_val")
            self.assertNotIn("MAX_STEP", galaxy_cfg)

    def test_unrelated_env_not_seeded(self):
        """Test that unrelated environment variables do not leak into config."""
        self.create_config_file("config/ufo/test.yaml", {"MAX_STEP": 50})

        from ufo.config.config_loader import ConfigLoader

        with patch.dict(os.environ, {"UNRELATED_SECRET_KEY": "should_not_be_in_config"}):
            loader = ConfigLoader(base_path=f"{self.test_dir}/config")
            config = loader.load_ufo_config()
            self.assertNotIn("UNRELATED_SECRET_KEY", config)


class TestUFOConfig(unittest.TestCase):
    """Test UFOConfig typed configuration."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        from ufo.config.config_loader import clear_config_cache
        self.addCleanup(clear_config_cache)

        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.addCleanup(os.chdir, self.original_cwd)

    def create_config_file(self, path: str, content: dict):
        """Helper to create a config file."""
        file_path = Path(self.test_dir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)
        return file_path

    def test_typed_access(self):
        """Test type-safe access to configuration."""
        # Create config
        config_data = {
            "HOST_AGENT": {"API_TYPE": "openai", "API_MODEL": "gpt-4o"},
            "APP_AGENT": {"API_TYPE": "aoai", "API_MODEL": "gpt-4"},
            "MAX_STEP": 50,
            "TIMEOUT": 60,
        }
        self.create_config_file("config/ufo/test.yaml", config_data)

        from ufo.config.config_loader import get_ufo_config, clear_config_cache, ConfigLoader

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")
        config = get_ufo_config()

        # Test typed access
        self.assertEqual(config.host_agent.api_type, "openai")
        self.assertEqual(config.app_agent.api_model, "gpt-4")
        self.assertEqual(config.system.max_step, 50)

    def test_dict_access_backward_compatible(self):
        """Test backward-compatible dict-style access."""
        config_data = {
            "HOST_AGENT": {"API_TYPE": "openai"},
            "MAX_STEP": 50,
        }
        self.create_config_file("config/ufo/test.yaml", config_data)

        from ufo.config.config_loader import get_ufo_config, clear_config_cache, ConfigLoader

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")
        config = get_ufo_config()

        # Test dict access
        self.assertEqual(config["MAX_STEP"], 50)
        self.assertEqual(config["HOST_AGENT"]["API_TYPE"], "openai")

    def test_dynamic_field_access(self):
        """Test access to dynamic fields not in schema."""
        config_data = {
            "HOST_AGENT": {"API_TYPE": "openai"},
            "NEW_CUSTOM_FIELD": "custom_value",
            "EXPERIMENTAL_FEATURE": True,
        }
        self.create_config_file("config/ufo/test.yaml", config_data)

        from ufo.config.config_loader import get_ufo_config, clear_config_cache, ConfigLoader

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")
        config = get_ufo_config()

        # Test dynamic access
        self.assertEqual(config.NEW_CUSTOM_FIELD, "custom_value")
        self.assertTrue(config.EXPERIMENTAL_FEATURE)
        self.assertEqual(config["NEW_CUSTOM_FIELD"], "custom_value")

    def test_nested_dynamic_access(self):
        """Test nested dynamic field access."""
        config_data = {"CUSTOM_SECTION": {"nested_field": "nested_value", "count": 42}}
        self.create_config_file("config/ufo/test.yaml", config_data)

        from ufo.config.config_loader import get_ufo_config, clear_config_cache, ConfigLoader

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")
        config = get_ufo_config()

        # Test nested access
        custom = config.CUSTOM_SECTION
        self.assertEqual(custom.nested_field, "nested_value")
        self.assertEqual(custom.count, 42)


class TestGalaxyConfig(unittest.TestCase):
    """Test GalaxyConfig configuration."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        from ufo.config.config_loader import clear_config_cache
        self.addCleanup(clear_config_cache)

        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.addCleanup(os.chdir, self.original_cwd)

    def create_config_file(self, path: str, content: dict):
        """Helper to create a config file."""
        file_path = Path(self.test_dir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)
        return file_path

    def test_galaxy_config_loading(self):
        """Test Galaxy configuration loading."""
        config_data = {
            "CONSTELLATION_AGENT": {
                "API_TYPE": "azure_ad",
                "API_MODEL": "gpt-4o",
            },
            "DEVICE_INFO": "config/galaxy/devices.yaml",
        }
        self.create_config_file("config/galaxy/agent.yaml", config_data)

        from ufo.config.config_loader import get_galaxy_config, clear_config_cache, ConfigLoader

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")
        config = get_galaxy_config()

        # Test typed access
        self.assertEqual(config.constellation_agent.api_type, "azure_ad")
        self.assertEqual(config.constellation_agent.api_model, "gpt-4o")

        # Test dynamic access
        self.assertEqual(config.DEVICE_INFO, "config/galaxy/devices.yaml")

    def test_galaxy_no_legacy_fallback(self):
        """Test that Galaxy has no legacy path fallback."""
        # Galaxy should only check config/galaxy/, not galaxy/config/
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader(base_path=f"{self.test_dir}/config")

        # Should raise error if no config found
        with self.assertRaises(FileNotFoundError):
            loader._load_with_fallback("galaxy")


class TestAPIBaseTransformations(unittest.TestCase):
    """Test API base URL transformations for different API types."""

    def test_aoai_api_base_transformation(self):
        """Test Azure OpenAI API base transformation."""
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader()
        config = {
            "HOST_AGENT": {
                "API_TYPE": "aoai",
                "API_BASE": "https://test.openai.azure.com",
                "API_DEPLOYMENT_ID": "gpt-4-deployment",
                "API_VERSION": "2024-02-15-preview",
            }
        }

        loader._apply_legacy_transforms(config)

        # Should have deployment URL constructed
        expected_base = (
            "https://test.openai.azure.com/openai/deployments/"
            "gpt-4-deployment/chat/completions?api-version=2024-02-15-preview"
        )
        self.assertEqual(config["HOST_AGENT"]["API_BASE"], expected_base)
        self.assertEqual(config["HOST_AGENT"]["API_MODEL"], "gpt-4-deployment")

    def test_openai_api_base_default(self):
        """Test OpenAI API base default value."""
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader()
        config = {"HOST_AGENT": {"API_TYPE": "openai"}}

        loader._apply_legacy_transforms(config)

        # Should have default OpenAI base
        self.assertEqual(
            config["HOST_AGENT"]["API_BASE"],
            "https://api.openai.com/v1/chat/completions",
        )

    def test_control_backend_list_conversion(self):
        """Test CONTROL_BACKEND string to list conversion."""
        from ufo.config.config_loader import ConfigLoader

        loader = ConfigLoader()
        config = {"CONTROL_BACKEND": "uia"}

        loader._apply_legacy_transforms(config)

        # Should be converted to list
        self.assertEqual(config["CONTROL_BACKEND"], ["uia"])


class TestConfigCaching(unittest.TestCase):
    """Test configuration caching mechanisms."""

    def setUp(self):
        """Set up test environment."""
        import tempfile, shutil, os
        from pathlib import Path
        import yaml
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        from ufo.config.config_loader import clear_config_cache
        self.addCleanup(clear_config_cache)

        # Change to test directory
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.addCleanup(os.chdir, self.original_cwd)
        
        # Ensure singleton uses test directory
        from ufo.config.config_loader import ConfigLoader, clear_config_cache
        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")

    def create_config_file(self, path: str, content: dict):
        """Helper to create a config file."""
        import yaml
        from pathlib import Path
        file_path = Path(self.test_dir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)
        return file_path

    def test_global_config_cache(self):
        """Test global configuration caching."""
        from ufo.config.config_loader import (
            get_ufo_config,
            clear_config_cache,
            _global_ufo_config,
            ConfigLoader,
        )

        # Create config
        self.create_config_file("config/ufo/test.yaml", {"MAX_STEP": 50})

        # Clear cache
        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")

        # First load
        config1 = get_ufo_config()

        # Second load should return same instance
        config2 = get_ufo_config()

        self.assertIs(config1, config2)

    def test_cache_reload(self):
        """Test configuration reload functionality."""
        from ufo.config.config_loader import get_ufo_config, clear_config_cache, ConfigLoader

        # Create config
        self.create_config_file("config/ufo/test.yaml", {"MAX_STEP": 50})

        clear_config_cache()
        ConfigLoader.get_instance(base_path=f"{self.test_dir}/config")

        # Load once
        config1 = get_ufo_config()

        # Force reload
        config2 = get_ufo_config(reload=True)

        # Should be different instances after reload
        self.assertIsNot(config1, config2)


class TestCloudFailoverRouting(unittest.TestCase):
    """Test validated in-memory cloud failover routing."""

    def tearDown(self):
        """Reset agent route after test."""
        from ufo.llm.config_helper import set_active_agent_route
        set_active_agent_route(None)

    def test_valid_cloud_route_activation(self):
        """Test activating cloud route when agents_cloud.yaml is valid."""
        from ufo.llm.config_helper import (
            set_active_agent_route,
            get_active_agent_route,
            get_agent_config,
        )
        from ufo.llm import AgentType

        success = set_active_agent_route("cloud")
        self.assertTrue(success)
        self.assertEqual(get_active_agent_route(), "cloud")

        host_cfg = get_agent_config(AgentType.HOST)
        self.assertIn("API_TYPE", host_cfg)
        self.assertEqual(host_cfg.get("API_TYPE"), "openai")

    def test_reset_route_to_default(self):
        """Test resetting route to None."""
        from ufo.llm.config_helper import set_active_agent_route, get_active_agent_route

        set_active_agent_route("cloud")
        set_active_agent_route(None)
        self.assertIsNone(get_active_agent_route())


if __name__ == "__main__":
    unittest.main()

