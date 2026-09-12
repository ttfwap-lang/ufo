# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Constellation Editing Prompter.

This module provides the prompter for Constellation Agent EDITING mode.
"""

from .base_constellation_prompter import BaseConstellationPrompter


class ConstellationEditingPrompter(BaseConstellationPrompter):
    """
    Prompter for Constellation Agent in EDITING mode.

    This prompter is specialized for editing existing task constellations
    based on user requests and current constellation state.
    """

    def __init__(self, prompt_template: str = None, example_prompt_template: str = None, *args, **kwargs):
        super().__init__(prompt_template, example_prompt_template)
        from ufo.galaxy.agents.schema import WeavingMode
        self.weaving_mode = WeavingMode.EDITING
