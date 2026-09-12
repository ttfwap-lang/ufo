# Unit tests for Blackboard screenshot memory capping fix

import pytest
from unittest.mock import patch
from ufo.agents.memory.blackboard import Blackboard


def test_blackboard_add_image_capping():
    """Test that add_image accumulates images and screenshots_to_prompt caps output."""
    blackboard = Blackboard()
    
    with patch("ufo.utils.encode_image_from_path", return_value="base64_data_1"):
        blackboard.add_image(screenshot_path="dummy1.png", metadata={"step": "1"})
        
    assert blackboard.screenshots.length == 1
    assert blackboard.screenshots.list_content[0]["image_str"] == ""  # Path doesn't exist, returns ""
    
    with patch("os.path.exists", return_value=True), \
         patch("ufo.utils.encode_image_from_path", return_value="base64_data_1"):
        blackboard.add_image(screenshot_path="fake1.png", metadata={"step": "1"})
        
    # add_image accumulates — capping happens at prompt generation time
    assert blackboard.screenshots.length == 2

    with patch("os.path.exists", return_value=True), \
         patch("ufo.utils.encode_image_from_path", return_value="base64_data_2"):
        blackboard.add_image(screenshot_path="fake2.png", metadata={"step": "2"})
        
    # All 3 images stored in memory
    assert blackboard.screenshots.length == 3
    # But screenshots_to_prompt caps to max_images=1 (most recent)
    prompt = blackboard.screenshots_to_prompt(max_images=1)
    assert len(prompt) == 2  # 1 text + 1 image_url
    assert prompt[1]["image_url"]["url"] == "base64_data_2"


def test_blackboard_to_prompt_capping():
    """Test that blackboard_to_prompt and screenshots_to_prompt cap to max_images=1 by default."""
    blackboard = Blackboard()
    
    with patch("os.path.exists", return_value=True), \
         patch("ufo.utils.encode_image_from_path", side_effect=["img1", "img2", "img3"]):
        blackboard.add_image("img1.png", metadata={"metadata": "meta1"}, max_images=5)
        blackboard.add_image("img2.png", metadata={"metadata": "meta2"}, max_images=5)
        blackboard.add_image("img3.png", metadata={"metadata": "meta3"}, max_images=5)
        
    assert blackboard.screenshots.length == 3
    
    # screenshots_to_prompt default max_images=1 should return only 1 image prompt pair
    prompt_images = blackboard.screenshots_to_prompt()
    assert len(prompt_images) == 2  # 1 text + 1 image_url
    assert "meta3" in prompt_images[0]["text"]
    assert prompt_images[1]["image_url"]["url"] == "img3"
    
    # blackboard_to_prompt default max_images=1
    full_prompt = blackboard.blackboard_to_prompt()
    image_entries = [p for p in full_prompt if p.get("type") == "image_url"]
    assert len(image_entries) == 1
    assert image_entries[0]["image_url"]["url"] == "img3"
