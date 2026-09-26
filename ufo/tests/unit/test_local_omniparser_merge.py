"""Merge rules for the local OmniParser service (icons + OCR text).

Pure geometry, no models. Each case pins a decision that, if wrong, either
double-lists a control (the agent clicks the same thing twice) or silently
loses text (the agent cannot find a label it can see).
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "local_omniparser",
                     "omni_merge.py")
_spec = importlib.util.spec_from_file_location("omni_merge", _PATH)
om = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(om)

W, H = 1000, 1000  # 5% of the image = 50,000 px^2


def test_icon_that_is_just_a_text_region_is_dropped():
    # YOLO boxed the words themselves; the OCR box already covers them.
    els, cap = om.merge([(100, 100, 200, 120)], [((98, 98, 202, 122), "Send")], W, H)
    assert [e["type"] for e in els] == ["text"]
    assert cap == []


def test_button_sized_icon_absorbs_its_label_and_is_not_captioned():
    icon = (100, 100, 260, 160)             # 9,600 px^2, well under 5%
    text = ((120, 110, 240, 150), "Save")
    els, cap = om.merge([icon], [text], W, H)
    assert len(els) == 1                    # not listed twice
    assert els[0]["type"] == "icon" and els[0]["content"] == "Save"
    assert cap == []                        # no GPU time spent captioning it


def test_huge_icon_does_not_swallow_the_labels_inside_it():
    sidebar = (0, 0, 500, 1000)             # 50% of the image
    texts = [((10, 10 + 40 * i, 200, 30 + 40 * i), f"chat {i}") for i in range(2)]
    els, cap = om.merge([sidebar], texts, W, H)
    kinds = sorted(e["type"] for e in els)
    assert kinds == ["icon", "text", "text"]  # every label survives
    assert cap == [0]                          # the container still gets captioned


def test_button_with_too_many_texts_is_not_a_merge():
    icon = (0, 0, 200, 200)                 # 4% - small enough by area
    texts = [((10, 10 + 30 * i, 190, 30 + 30 * i), f"t{i}") for i in range(4)]
    els, _ = om.merge([icon], texts, W, H)
    assert sum(e["type"] == "text" for e in els) == 4  # 4 > MERGE_MAX_TEXTS


def test_plain_icon_with_no_text_is_queued_for_a_caption():
    els, cap = om.merge([(10, 10, 50, 50)], [], W, H)
    assert cap == [0] and els[0]["content"] == ""


def test_every_ocr_box_is_kept_when_there_are_no_icons():
    els, cap = om.merge([], [((0, 0, 50, 10), "a"), ((0, 20, 50, 30), "b")], W, H)
    assert [e["content"] for e in els] == ["a", "b"] and cap == []


def test_degenerate_and_out_of_frame_boxes_are_safe():
    assert om.area((5, 5, 5, 50)) == 0
    assert om.clamp((-10, -10, 2000, 2000), W, H) == (0, 0, W, H)
    els, cap = om.merge([(10, 10, 10, 10)], [], W, H)  # zero-area icon
    assert els == [] and cap == []
