"""
Cloud PII Redactor — Regex UIA scrubbing and screenshot blurring for data sovereignty.

Before any screenshot or UIA tree is sent to Layer 2/3 Cloud models (OpenAI, Google),
this module:
  1. Scans UIA tree text nodes for PII patterns (account numbers, SSNs, currency amounts)
  2. Replaces matched text with [REDACTED] markers
  3. Uses the redacted nodes' bounding boxes to apply Gaussian blur on the screenshot

Layer 1 (local) models do NOT get redacted data — they see everything for maximum
grounding accuracy, since data never leaves the machine.

PII Patterns Detected:
  - Currency amounts: $10,000.00, $1,450,000.00
  - Social Security Numbers: 123-45-6789
  - Account numbers: Account #123456789, Acc: 987654321
  - Credit card numbers: 4111-1111-1111-1111
  - Phone numbers: (555) 123-4567
  - Email addresses: user@bank.com
  - Routing numbers: ABA 123456789
  - Date of birth patterns: DOB: 01/15/1990

Config in system.yaml:
    SECURITY:
      REDACTOR:
        ENABLED: true
        REDACT_FOR_CLOUD_ONLY: true
        BLUR_KERNEL_SIZE: 51
        REDACTION_MARKER: "[REDACTED]"
        CUSTOM_PATTERNS: []

Usage:
    
    from ufo.security.pii_redactor import PIIRedactor

    redactor = PIIRedactor()

    # Redact UIA tree text
    clean_tree = redactor.redact_uia_tree(uia_tree)

    # Redact screenshot (blurs areas matching redacted tree nodes)
    redacted_path = redactor.redact_screenshot("screen.png", clean_tree)
"""
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
logger = logging.getLogger(__name__)
_BUILTIN_PATTERNS = [re.compile('\\$\\s*\\d{1,3}(?:,\\d{3})*(?:\\.\\d{1,2})?', re.IGNORECASE), re.compile('(?:USD|EUR|GBP|AUD)\\s*\\d{1,3}(?:,\\d{3})*(?:\\.\\d{1,2})?', re.IGNORECASE), re.compile('\\b\\d{3}-\\d{2}-\\d{4}\\b'), re.compile('\\b(?:Account|Acc|Acct)[\\s:#\\-]*\\d{4,12}\\b', re.IGNORECASE), re.compile('\\b(?:\\d{4}[-\\s]?){3}\\d{4}\\b'), re.compile('\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b'), re.compile('\\b[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}\\b'), re.compile('\\b(?:ABA|Routing|RTN)[\\s:#\\-]*\\d{9}\\b', re.IGNORECASE), re.compile('\\b(?:DOB|Birth\\s*Date|Date\\s*of\\s*Birth)[\\s:]*\\d{1,2}[/\\-]\\d{1,2}[/\\-]\\d{2,4}\\b', re.IGNORECASE), re.compile('\\b(?:Balance|Available|Current|Pending)[\\s:]*\\$?\\s*\\d{1,3}(?:,\\d{3})*(?:\\.\\d{1,2})?\\b', re.IGNORECASE)]

def _load_redactor_config() -> Dict[str, Any]:
    """Load redactor config from system.yaml."""
    defaults = {'ENABLED': True, 'REDACT_FOR_CLOUD_ONLY': True, 'BLUR_KERNEL_SIZE': 51, 'REDACTION_MARKER': '[REDACTED]', 'CUSTOM_PATTERNS': []}
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        sec = getattr(cfg.system, 'security', None)
        if sec and isinstance(sec, dict):
            redactor = sec.get('REDACTOR', {})
            if isinstance(redactor, dict):
                defaults.update({k: v for k, v in redactor.items() if v is not None})
    except Exception:
        pass
    return defaults

class PIIRedactor:
    """
    Scrubs PII from UIA trees and screenshots before cloud transmission.

    Only redacts data sent to Layer 2/3 (cloud) models. Local Layer 1
    models see unredacted data for maximum grounding accuracy.
    """

    def __init__(self) -> None:
        self._config = _load_redactor_config()
        self._marker = self._config.get('REDACTION_MARKER', '[REDACTED]')
        self._blur_kernel = self._config.get('BLUR_KERNEL_SIZE', 51)
        self._patterns: List[re.Pattern] = list(_BUILTIN_PATTERNS)
        custom = self._config.get('CUSTOM_PATTERNS', [])
        if custom:
            for pat_str in custom:
                try:
                    self._patterns.append(re.compile(pat_str, re.IGNORECASE))
                except re.error as e:
                    logger.warning(f"[Redactor] Invalid custom pattern '{pat_str}': {e}")
        if self._blur_kernel % 2 == 0:
            self._blur_kernel += 1

    def is_enabled(self) -> bool:
        """Check if redaction is enabled."""
        return self._config.get('ENABLED', True)

    def should_redact_for_model(self, is_cloud: bool) -> bool:
        """
        Check if redaction should be applied for the given model layer.

        If REDACT_FOR_CLOUD_ONLY is true, only redact for cloud models.
        If false, redact for all models.
        """
        if not self.is_enabled():
            return False
        if self._config.get('REDACT_FOR_CLOUD_ONLY', True):
            return is_cloud
        return True

    def redact_uia_tree(self, node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Recursively scrub PII from UIA tree text nodes.

        Replaces matched PII in 'name', 'value', and 'text' fields
        with the redaction marker.

        :param node: UIA tree dict (from ui_pruner).
        :return: The same dict with PII replaced (mutated in-place).
        """
        if not node or not self.is_enabled():
            return node
        self._redact_node(node)
        return node

    def _redact_node(self, node: Dict[str, Any]) -> int:
        """Redact a single node and its children. Returns count of redactions."""
        count = 0
        for field in ('name', 'value', 'text', 'help_text'):
            original = node.get(field, '')
            if original and isinstance(original, str):
                redacted = self._redact_text(original)
                if redacted != original:
                    node[field] = redacted
                    count += 1
        for child in node.get('children', []):
            count += self._redact_node(child)
        return count

    def _redact_text(self, text: str) -> str:
        """Apply all PII patterns to a text string."""
        result = text
        for pattern in self._patterns:
            result = pattern.sub(self._marker, result)
        return result

    def redact_string(self, text: str) -> str:
        """
        Public API for redacting a single string.

        Useful for scrubbing log messages or prompt text.
        """
        if not text or not self.is_enabled():
            return text
        return self._redact_text(text)

    def redact_screenshot(self, screenshot_path: str, uia_tree: Optional[Dict[str, Any]]=None) -> str:
        """
        Blur PII regions on a screenshot using redacted UIA tree bounding boxes.

        Finds all tree nodes marked as [REDACTED] and applies Gaussian blur
        to their bounding box regions on the screenshot.

        :param screenshot_path: Path to the original screenshot.
        :param uia_tree: Pre-redacted UIA tree (with [REDACTED] markers).
        :return: Path to the redacted screenshot.
        """
        if not self.is_enabled() or not os.path.exists(screenshot_path):
            return screenshot_path
        blur_regions = []
        if uia_tree:
            self._collect_redacted_regions(uia_tree, blur_regions)
        if not blur_regions:
            logger.debug('[Redactor] No PII regions to blur in screenshot.')
            return screenshot_path
        base, ext = os.path.splitext(screenshot_path)
        redacted_path = f'{base}_redacted{ext}'
        try:
            return self._blur_with_pillow(screenshot_path, blur_regions, redacted_path)
        except ImportError:
            try:
                return self._blur_with_cv2(screenshot_path, blur_regions, redacted_path)
            except ImportError:
                logger.warning('[Redactor] Neither Pillow nor cv2 available for screenshot blur.')
                return screenshot_path

    def _collect_redacted_regions(self, node: Dict[str, Any], regions: List[Tuple[int, int, int, int]]) -> None:
        """Collect bounding boxes of nodes containing the redaction marker.

        Supports three rectangle formats found in UFO UIA trees:
          - bounding_box: [left, top, right, bottom]  (list of 4+ ints)
          - adjusted_rectangle / rectangle: {left, top, right, bottom}  (dict)
        """
        marker = self._marker
        for field in ('name', 'value', 'text'):
            if marker in str(node.get(field, '')):
                bbox = self._extract_bbox(node)
                if bbox:
                    regions.append(bbox)
                break
        for child in node.get('children', []):
            self._collect_redacted_regions(child, regions)

    @staticmethod
    def _extract_bbox(node: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
        """Extract a (left, top, right, bottom) tuple from a UIA node.

        Checks bounding_box (list), adjusted_rectangle (dict), rectangle (dict).
        Returns None if no valid bbox is found.
        """
        bbox = node.get('bounding_box')
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            left, top, right, bottom = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
            if right > left and bottom > top:
                return (left, top, right, bottom)
        for key in ('adjusted_rectangle', 'rectangle'):
            rect = node.get(key)
            if isinstance(rect, dict):
                try:
                    left = int(rect['left'])
                    top = int(rect['top'])
                    right = int(rect['right'])
                    bottom = int(rect['bottom'])
                    if right > left and bottom > top:
                        return (left, top, right, bottom)
                except (KeyError, TypeError, ValueError):
                    continue
        return None

    def _blur_with_pillow(self, src_path: str, regions: List[Tuple[int, int, int, int]], dst_path: str) -> str:
        """Apply Gaussian blur to regions using Pillow."""
        from PIL import Image, ImageFilter
        image = Image.open(src_path)
        for left, top, right, bottom in regions:
            left = max(0, left)
            top = max(0, top)
            right = min(image.width, right)
            bottom = min(image.height, bottom)
            if right <= left or bottom <= top:
                continue
            roi = image.crop((left, top, right, bottom))
            blurred = roi.filter(ImageFilter.GaussianBlur(radius=self._blur_kernel // 2))
            image.paste(blurred, (left, top))
        image.save(dst_path)
        logger.info(f'[Redactor] Screenshot PII obfuscated: {len(regions)} regions blurred → {dst_path}')
        return dst_path

    def _blur_with_cv2(self, src_path: str, regions: List[Tuple[int, int, int, int]], dst_path: str) -> str:
        """Apply Gaussian blur to regions using OpenCV."""
        import cv2
        image = cv2.imread(src_path)
        if image is None:
            logger.error(f'[Redactor] cv2 could not read: {src_path}')
            return src_path
        h, w = image.shape[:2]
        for left, top, right, bottom in regions:
            left = max(0, left)
            top = max(0, top)
            right = min(w, right)
            bottom = min(h, bottom)
            if right <= left or bottom <= top:
                continue
            roi = image[top:bottom, left:right]
            if roi.size > 0:
                blurred = cv2.GaussianBlur(roi, (self._blur_kernel, self._blur_kernel), 0)
                image[top:bottom, left:right] = blurred
        cv2.imwrite(dst_path, image)
        logger.info(f'[Redactor] Screenshot PII obfuscated: {len(regions)} regions blurred → {dst_path}')
        return dst_path

    def redact_for_cloud(self, screenshot_path: str, uia_tree: Optional[Dict[str, Any]]=None) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        One-shot redaction for cloud transmission.

        Returns both the redacted screenshot path and the scrubbed UIA tree.
        """
        redacted_tree = None
        if uia_tree:
            import copy
            redacted_tree = copy.deepcopy(uia_tree)
            self.redact_uia_tree(redacted_tree)
        redacted_screenshot = self.redact_screenshot(screenshot_path, redacted_tree)
        return (redacted_screenshot, redacted_tree)

    def count_pii_matches(self, text: str) -> int:
        """Count the number of PII matches in a text string."""
        count = 0
        for pattern in self._patterns:
            count += len(pattern.findall(text))
        return count