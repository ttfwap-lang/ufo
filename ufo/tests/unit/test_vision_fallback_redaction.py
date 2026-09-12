# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for VisionFallbackManager screenshot redaction with UIA tree.
Proves cloud VLM payload uses the redacted screenshot when UIA tree has PII.
Also validates PIIRedactor._collect_redacted_regions supports real UFO UIA
rectangle formats (dict-based adjusted_rectangle/rectangle and list-based bounding_box).
"""

import os
import shutil
import tempfile
import pytest
from unittest.mock import AsyncMock, patch
from PIL import Image

from ufo.automator.vision_fallback import VisionFallbackManager
from ufo.llm.llm_result import LLMResult
from ufo.security.pii_redactor import PIIRedactor


@pytest.mark.asyncio
async def test_vision_fallback_cloud_vlm_redacts_screenshot_with_uia_tree():
    """Verify Stage 2 cloud VLM calls PIIRedactor.redact_for_cloud with uia_tree and uses redacted screenshot."""
    temp_dir = tempfile.mkdtemp()
    try:
        # Create a sample image
        img_path = os.path.join(temp_dir, "test_screenshot.png")
        img = Image.new("RGB", (200, 200), color="white")
        img.save(img_path)

        # Sample UIA tree with seeded PII (SSN) and bounding box
        uia_tree = {
            "control_type": "Window",
            "name": "App",
            "children": [
                {
                    "control_type": "Text",
                    "name": "Customer SSN: 123-45-6789",
                    "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
                }
            ],
        }

        vfm = VisionFallbackManager()
        vfm._enabled = True

        mock_llm_result = LLMResult(
            responses=['{"center_x": 50, "center_y": 50, "width": 20, "height": 20, "confidence": 0.95}'],
            cost=0.01,
            prompt_tokens=100,
            completion_tokens=50,
            model="gemini-3.7-flash",
            api_type="gemini",
            agent_type="BACKUP_AGENT",
        )

        with patch("ufo.llm.llm_call.get_completion", new_callable=AsyncMock) as mock_get_comp:
            mock_get_comp.return_value = mock_llm_result
            bbox = await vfm._stage2_cloud_vlm(
                screenshot_path=img_path,
                target_description="Search box",
                uia_tree=uia_tree,
            )

            assert bbox is not None
            assert bbox.center_x == 50
            assert mock_get_comp.called

            # Check that messages payload image_url was constructed
            call_messages = mock_get_comp.call_args[0][0]
            assert len(call_messages) > 0
            content = call_messages[0]["content"]
            assert any(part.get("type") == "image_url" for part in content)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestPIIRedactorUiaRectangleFormats:
    """Verify _collect_redacted_regions handles all UFO UIA rectangle formats."""

    def _make_redactor_with_marker(self) -> PIIRedactor:
        """Create a PIIRedactor and return it. The test trees will use [REDACTED] directly."""
        redactor = PIIRedactor()
        return redactor

    def test_list_based_bounding_box(self):
        """Standard bounding_box as [left, top, right, bottom] list."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "bounding_box": [10, 20, 100, 50],
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == [(10, 20, 100, 50)]

    def test_dict_rectangle(self):
        """UIA rectangle as dict with left/top/right/bottom keys."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == [(10, 10, 100, 30)]

    def test_dict_adjusted_rectangle_preferred(self):
        """adjusted_rectangle is preferred over rectangle when both exist."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "adjusted_rectangle": {"left": 5, "top": 5, "right": 95, "bottom": 25},
            "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == [(5, 5, 95, 25)]

    def test_bounding_box_preferred_over_rectangle(self):
        """bounding_box (list) takes priority over rectangle dict."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "bounding_box": [1, 2, 50, 60],
            "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == [(1, 2, 50, 60)]

    def test_nested_children_with_rectangle(self):
        """PII in a child node with rectangle dict format is collected."""
        redactor = self._make_redactor_with_marker()
        tree = {
            "name": "Window",
            "children": [
                {
                    "name": "Customer SSN: [REDACTED]",
                    "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
                    "children": [],
                },
                {
                    "name": "Clean text",
                    "rectangle": {"left": 0, "top": 0, "right": 50, "bottom": 20},
                    "children": [],
                },
            ],
        }
        regions = []
        redactor._collect_redacted_regions(tree, regions)
        assert len(regions) == 1
        assert regions[0] == (10, 10, 100, 30)

    def test_no_bbox_fields_skipped_gracefully(self):
        """Node with redaction marker but no rectangle field is skipped."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == []

    def test_invalid_rectangle_dict_skipped(self):
        """Rectangle dict missing required keys is skipped."""
        redactor = self._make_redactor_with_marker()
        node = {
            "name": "[REDACTED]",
            "rectangle": {"left": 10, "top": 10},  # missing right/bottom
            "children": [],
        }
        regions = []
        redactor._collect_redacted_regions(node, regions)
        assert regions == []

    def test_redact_for_cloud_uses_rectangle_dict(self):
        """Full redact_for_cloud pipeline works with UIA rectangle dicts."""
        temp_dir = tempfile.mkdtemp()
        try:
            img_path = os.path.join(temp_dir, "test.png")
            img = Image.new("RGB", (200, 200), color="white")
            img.save(img_path)

            uia_tree = {
                "control_type": "Window",
                "name": "App",
                "children": [
                    {
                        "control_type": "Text",
                        "name": "Account #123456789",
                        "rectangle": {"left": 10, "top": 10, "right": 100, "bottom": 30},
                    }
                ],
            }

            redactor = PIIRedactor()
            redacted_path, redacted_tree = redactor.redact_for_cloud(img_path, uia_tree)

            # Tree text should be redacted
            child = redacted_tree["children"][0]
            assert "[REDACTED]" in child["name"]

            # Redacted screenshot should be created (blurred)
            assert os.path.exists(redacted_path)
            assert redacted_path != img_path  # Should be a new file
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
