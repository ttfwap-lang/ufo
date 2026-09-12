# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Constellation Creation Prompter.

This module provides the prompter for Constellation Agent CREATION mode.
"""

from .base_constellation_prompter import BaseConstellationPrompter


class ConstellationCreationPrompter(BaseConstellationPrompter):
    """
    Prompter for Constellation Agent in CREATION mode.

    This prompter is specialized for creating new task constellations
    based on user requests and available device information.
    """

    def __init__(self, prompt_template: str = None, example_prompt_template: str = None, *args, **kwargs):
        super().__init__(prompt_template, example_prompt_template)
        from ufo.galaxy.agents.schema import WeavingMode
        self.weaving_mode = WeavingMode.CREATION
