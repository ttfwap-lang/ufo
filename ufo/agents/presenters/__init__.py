# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Presenters module for agent response display.

This module provides a clean separation between business logic and presentation logic,
allowing for flexible output formatting and easy extension to new output formats.
"""

from .base_presenter import BasePresenter
from .presenter_factory import PresenterFactory
from .rich_presenter import RichPresenter

__all__ = [
    "BasePresenter",
    "RichPresenter",
    "PresenterFactory",
]
