# Unit tests for ReceiverManager property mutation fix

import pytest
from unittest.mock import MagicMock
from ufo.automator.puppeteer import ReceiverManager, ReceiverBasic


def test_receiver_manager_receiver_list_property():
    """Test that receiver_list property returns _receiver_list without raising AttributeError on mutation."""
    manager = ReceiverManager()
    assert isinstance(manager.receiver_list, list)
    assert manager.receiver_list == []


def test_create_ui_control_receiver_mutation():
    """Test that create_ui_control_receiver mutates _receiver_list without AttributeError."""
    manager = ReceiverManager()
    
    mock_receiver = MagicMock()
    mock_receiver.type_name = "UIControl"
    mock_receiver.self_command_mapping.return_value = {}

    mock_factory = MagicMock()
    mock_factory.create_receiver.return_value = mock_receiver
    
    manager._receiver_factory_registry = {
        "UIControl": {
            "factory": mock_factory,
            "is_api": False,
        }
    }
    
    # Run create_ui_control_receiver
    result = manager.create_ui_control_receiver(control=MagicMock(), application=MagicMock())
    
    assert result == mock_receiver
    assert len(manager.receiver_list) == 1
    assert manager.receiver_list[0] == mock_receiver
