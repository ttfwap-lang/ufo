"""
Set-of-Marks (SoM) Visual Annotator — Numbered bounding box overlay for VLM grounding.

When pywinauto fails AND OmniParser fails, this optional layer draws numbered
red bounding boxes over all actionable elements from the pruned UIA tree,
allowing a Cloud VLM (GPT-4 Vision / Gemini) to simply output a number
to select a control.

Gated behind: LEGACY_FEATURES.ENABLE_SET_OF_MARKS in system.yaml

Usage:
    from ufo.automator.som_annotator import SoMAnnotator


    annotator = SoMAnnotator()
    if annotator.is_enabled():
        annotated_path, element_map = annotator.generate(
            screenshot_path="C:/tmp/screen.png",
            uia_tree=pruned_tree,
        )
        # Send annotated_path to VLM, get number back, look up element_map[number]
"""
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
logger = logging.getLogger(__name__)

def _load_som_config() -> Dict[str, Any]:
    """Load SoM config from system.yaml."""
    defaults = {'ENABLED': False}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        lf = getattr(cfg.system, 'legacy_features', None)
        if lf and isinstance(lf, dict):
            defaults['ENABLED'] = lf.get('ENABLE_SET_OF_MARKS', False)
    except Exception:
        pass
    return defaults
_ACTIONABLE_LEAVES = {'Button', 'Edit', 'MenuItem', 'TabItem', 'ListItem', 'Hyperlink', 'CheckBox', 'RadioButton', 'ComboBox', 'TreeItem', 'Spinner', 'Text'}

def _flatten_tree(node: Optional[Dict[str, Any]], result: Optional[List[Dict[str, Any]]]=None) -> List[Dict[str, Any]]:
    """
    Flatten a pruned UIA tree dict into a list of actionable leaf elements
    with valid bounding boxes.
    """
    if result is None:
        result = []
    if node is None:
        return result
    bbox = node.get('bounding_box', [0, 0, 0, 0])
    control_type = node.get('control_type', '')
    has_valid_bbox = len(bbox) >= 4 and bbox[2] > bbox[0] and (bbox[3] > bbox[1])
    if control_type in _ACTIONABLE_LEAVES and has_valid_bbox:
        result.append(node)
    for child in node.get('children', []):
        _flatten_tree(child, result)
    return result

class SoMAnnotator:
    """
    Draws numbered red bounding boxes on screenshots for VLM grounding.

    Uses PIL (Pillow) for drawing — no cv2 dependency required.
    Falls back to cv2 if PIL is unavailable.
    """

    def __init__(self) -> None:
        self._config = _load_som_config()

    def is_enabled(self) -> bool:
        """Check if SoM annotation is enabled in config."""
        return self._config.get('ENABLED', False)

    def generate(self, screenshot_path: str, uia_tree: Optional[Dict[str, Any]]=None, elements: Optional[List[Dict[str, Any]]]=None) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        """
        Generate a Set-of-Marks annotated screenshot.

        Takes a clean screenshot and either a pruned UIA tree dict or a
        pre-flattened list of elements. Draws numbered red bounding boxes
        around each actionable element.

        :param screenshot_path: Path to the clean screenshot.
        :param uia_tree: Pruned UIA tree dict (from ui_pruner).
        :param elements: Pre-flattened list of element dicts (alternative to uia_tree).
        :return: Tuple of (annotated_image_path, element_map).
                 element_map maps index → element dict for VLM number lookup.
        """
        if elements is not None:
            leaves = elements
        elif uia_tree is not None:
            leaves = _flatten_tree(uia_tree)
        else:
            logger.warning('SoM: No UIA tree or elements provided.')
            return (screenshot_path, {})
        if not leaves:
            logger.warning('SoM: No actionable elements found to annotate.')
            return (screenshot_path, {})
        element_map: Dict[int, Dict[str, Any]] = {}
        for idx, elem in enumerate(leaves):
            element_map[idx] = elem
        annotated_path = self._draw_annotations(screenshot_path, element_map)
        logger.info(f'SoM generated: {len(leaves)} marked elements → {annotated_path}')
        return (annotated_path, element_map)

    def generate_prompt_context(self, element_map: Dict[int, Dict[str, Any]]) -> str:
        """
        Generate a text description of the SoM element map for the VLM prompt.

        Example:
            [0] Button "OK" at [100,200,150,230]
            [1] Edit "Username" at [110,205,145,225]
        """
        lines = []
        for idx, elem in sorted(element_map.items()):
            name = elem.get('name', '')
            ctype = elem.get('control_type', '')
            bbox = elem.get('bounding_box', [])
            aid = elem.get('automation_id', '')
            name_part = f' "{name}"' if name else ''
            aid_part = f' #{aid}' if aid else ''
            bbox_part = f' at {bbox}' if bbox else ''
            lines.append(f'[{idx}] {ctype}{name_part}{aid_part}{bbox_part}')
        return '\n'.join(lines)

    @staticmethod
    def _draw_annotations(screenshot_path: str, element_map: Dict[int, Dict[str, Any]]) -> str:
        """Draw numbered red bounding boxes on the screenshot."""
        annotated_path = screenshot_path.replace('.png', '_som.png')
        if annotated_path == screenshot_path:
            base, ext = os.path.splitext(screenshot_path)
            annotated_path = f'{base}_som{ext}'
        try:
            return SoMAnnotator._draw_with_pillow(screenshot_path, element_map, annotated_path)
        except ImportError:
            logger.warning('Pillow not available. Trying cv2 for SoM drawing.')
            try:
                return SoMAnnotator._draw_with_cv2(screenshot_path, element_map, annotated_path)
            except ImportError:
                logger.error('Neither Pillow nor cv2 available. Cannot generate SoM annotation.')
                return screenshot_path

    @staticmethod
    def _draw_with_pillow(screenshot_path: str, element_map: Dict[int, Dict[str, Any]], output_path: str) -> str:
        """Draw SoM annotations using Pillow."""
        from PIL import Image, ImageDraw, ImageFont
        image = Image.open(screenshot_path)
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype('arial.ttf', 14)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 14)
            except (IOError, OSError):
                font = ImageFont.load_default()
        for idx, elem in element_map.items():
            bbox = elem.get('bounding_box', [0, 0, 0, 0])
            if len(bbox) < 4:
                continue
            left, top, right, bottom = (bbox[0], bbox[1], bbox[2], bbox[3])
            draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=2)
            label = str(idx)
            label_x = left + 2
            label_y = top + 2
            text_bbox = draw.textbbox((label_x, label_y), label, font=font)
            draw.rectangle([text_bbox[0] - 1, text_bbox[1] - 1, text_bbox[2] + 1, text_bbox[3] + 1], fill=(255, 255, 255))
            draw.text((label_x, label_y), label, fill=(255, 0, 0), font=font)
        image.save(output_path)
        return output_path

    @staticmethod
    def _draw_with_cv2(screenshot_path: str, element_map: Dict[int, Dict[str, Any]], output_path: str) -> str:
        """Draw SoM annotations using OpenCV (cv2)."""
        import cv2
        image = cv2.imread(screenshot_path)
        if image is None:
            raise ValueError(f'cv2 could not read: {screenshot_path}')
        for idx, elem in element_map.items():
            bbox = elem.get('bounding_box', [0, 0, 0, 0])
            if len(bbox) < 4:
                continue
            left, top, right, bottom = (bbox[0], bbox[1], bbox[2], bbox[3])
            cv2.rectangle(image, (left, top), (right, bottom), (0, 0, 255), 2)
            cv2.putText(image, str(idx), (left + 5, top + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.imwrite(output_path, image)
        return output_path