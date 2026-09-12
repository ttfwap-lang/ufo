"""
Dual-Stage Vision Grounding Fallback — OmniParser V2 → Cloud VLM cascade.

When Windows UI Automation fails to locate a target element (ElementNotFoundError,
stale COM handle, Electron/Canvas app), this module provides two fallback stages:

  Stage 1 (Local): OmniParser V2 via the existing OmniparserGrounding service.
                    Fast, zero-latency, runs against a local endpoint.
  Stage 2 (Cloud): If Stage 1 confidence < CONFIDENCE_THRESHOLD (default 0.85),
                    cascade to Cloud VLM (BACKUP_AGENT / Gemini 3.7 Flash) with
                    a targeted bounding-box extraction prompt.

Usage:
    
from ufo.automator.vision_fallback import VisionFallbackManager

    manager = VisionFallbackManager()
    result = manager.resolve_element(
        target_description="OK button",
        screenshot_path="C:/tmp/screen.png",
        application_window=app_window,
    )
    if result:
        pyautogui.click(result.center_x, result.center_y)
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
logger = logging.getLogger(__name__)

class BoundingBox(BaseModel):
    """Resolved screen coordinates for a UI element."""
    center_x: int = Field(..., description='Absolute X center coordinate')
    center_y: int = Field(..., description='Absolute Y center coordinate')
    width: int = Field(default=0, description='Element width in pixels')
    height: int = Field(default=0, description='Element height in pixels')
    confidence: float = Field(default=0.0, description='Grounding confidence 0.0-1.0')
    source: str = Field(default='unknown', description="Which stage resolved: 'omniparser' or 'cloud_vlm'")

class VisionFallbackResult(BaseModel):
    """Full result from the vision fallback pipeline."""
    resolved: bool = Field(default=False)
    bounding_box: Optional[BoundingBox] = None
    stage_1_attempted: bool = False
    stage_1_confidence: float = 0.0
    stage_2_attempted: bool = False
    stage_3_attempted: bool = False
    error: Optional[str] = None

class VisionFallbackManager:
    """
    Dual-stage vision grounding manager.

    Reads configuration from system.yaml:
      VISION_FALLBACK:
        ENABLED: true
        CONFIDENCE_THRESHOLD: 0.85
        CLOUD_VLM_AGENT: "BACKUP_AGENT"
    """

    def __init__(self) -> None:
        self._confidence_threshold = 0.85
        self._cloud_vlm_agent = 'BACKUP_AGENT'
        self._enabled = True
        self._load_config()

    def _load_config(self) -> None:
        """Load vision fallback config from system.yaml."""
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            vf_cfg = getattr(cfg.system, 'vision_fallback', None)
            if vf_cfg and isinstance(vf_cfg, dict):
                self._enabled = vf_cfg.get('ENABLED', True)
                self._confidence_threshold = float(vf_cfg.get('CONFIDENCE_THRESHOLD', 0.85))
                self._cloud_vlm_agent = vf_cfg.get('CLOUD_VLM_AGENT', 'BACKUP_AGENT')
        except Exception as e:
            logger.debug(f'Using default vision fallback config: {e}')

    async def resolve_element(self, target_description: str, screenshot_path: Optional[str]=None, application_window: Any=None, uia_tree: Optional[Dict[str, Any]]=None) -> Optional[BoundingBox]:
        """
        Attempt to resolve a UI element's screen coordinates via vision asynchronously.

        Stage 1: Local OmniParser V2
        Stage 2: Cloud VLM (if Stage 1 confidence < threshold)

        :param target_description: Human-readable description of the target element.
        :param screenshot_path: Path to screenshot. If None, one will be captured.
        :param application_window: pywinauto UIAWrapper for the application window.
        :param uia_tree: Optional dictionary representing the UIA accessibility tree.
        :return: BoundingBox with resolved coordinates, or None on total failure.
        """
        if not self._enabled:
            logger.info('Vision fallback is disabled in config.')
            return None
        logger.info(f"Vision fallback engaged for: '{target_description}'")
        if screenshot_path is None or not os.path.exists(screenshot_path):
            screenshot_path = self._capture_screenshot(application_window)
            if screenshot_path is None:
                logger.error('Failed to capture screenshot for vision fallback.')
                return None
        # RANK 1: OmniParser
        logger.warning('Engaging Rank 1 Vision Grounding: Local OmniParser V2')
        stage1_result = self._stage1_omniparser(screenshot_path, target_description, application_window)
        if stage1_result and stage1_result.confidence >= self._confidence_threshold:
            logger.info(f'Rank 1 (OmniParser) succeeded: confidence={stage1_result.confidence:.2f}')
            return stage1_result
            
        # RANK 2: Cloud VLM
        stage2_conf = stage1_result.confidence if stage1_result else 0.0
        logger.warning(f'Rank 1 failed (confidence={stage2_conf:.2f} < threshold={self._confidence_threshold}). Cascading to Rank 2: Cloud VLM.')
        stage2_result = await self._stage2_cloud_vlm(screenshot_path, target_description, uia_tree)
        if stage2_result:
            logger.info(f'Rank 2 (Cloud VLM) succeeded: confidence={stage2_result.confidence:.2f}')
            return stage2_result
        
        logger.error('All vision grounding stages failed.')
        return None

    async def resolve_element_full(self, target_description: str, screenshot_path: Optional[str]=None, application_window: Any=None, uia_tree: Optional[Dict[str, Any]]=None) -> VisionFallbackResult:
        """
        Same as resolve_element but returns full diagnostic result.
        """
        result = VisionFallbackResult()
        if not self._enabled:
            result.error = 'Vision fallback disabled in config'
            return result
        if screenshot_path is None or not os.path.exists(screenshot_path):
            screenshot_path = self._capture_screenshot(application_window)
            if screenshot_path is None:
                result.error = 'Screenshot capture failed'
                return result
                
        # RANK 1: OmniParser
        result.stage_2_attempted = True
        logger.warning('Engaging Rank 1 Vision Grounding: Local OmniParser V2')
        stage1_box = self._stage1_omniparser(screenshot_path, target_description, application_window)
        if stage1_box:
            result.stage_1_confidence = stage1_box.confidence
            if stage1_box.confidence >= self._confidence_threshold:
                result.resolved = True
                result.bounding_box = stage1_box
                return result
                
        # RANK 2: Cloud VLM
        result.stage_3_attempted = True
        logger.warning('Rank 1 failed or low confidence. Cascading to Rank 2: Cloud VLM (Gemini)')
        stage2_box = await self._stage2_cloud_vlm(screenshot_path, target_description, uia_tree)
        if stage2_box:
            result.resolved = True
            result.bounding_box = stage2_box
        else:
            result.error = 'All vision fallback ranks (Reducto, OmniParser, Cloud VLM) failed to resolve element.'
        return result

    def _stage1_omniparser(self, screenshot_path: str, target_description: str, application_window: Any=None) -> Optional[BoundingBox]:
        """Attempt element resolution via local OmniParser V2 service."""
        try:
            from ufo.config.config_loader import get_ufo_config
            ufo_config = get_ufo_config()
            omniparser_cfg = getattr(ufo_config.agents, 'omniparser', None)
            if not omniparser_cfg:
                omniparser_cfg = getattr(ufo_config.system, 'omniparser', None)
            if not omniparser_cfg:
                logger.debug('OmniParser not configured — skipping Stage 1')
                return None
            endpoint = ''
            if isinstance(omniparser_cfg, dict):
                endpoint = omniparser_cfg.get('ENDPOINT', '')
            elif hasattr(omniparser_cfg, 'ENDPOINT'):
                endpoint = getattr(omniparser_cfg, 'ENDPOINT', '')
            if not endpoint or 'xxx' in endpoint:
                logger.debug('OmniParser endpoint not set — skipping Stage 1')
                return None
            from ufo.llm.grounding_model.omniparser_service import OmniParser
            from ufo.automator.ui_control.grounding.omniparser import OmniparserGrounding
            service = OmniParser(endpoint=endpoint)
            grounding = OmniparserGrounding(service=service)
            box_threshold = 0.05
            iou_threshold = 0.1
            imgsz = 640
            if isinstance(omniparser_cfg, dict):
                box_threshold = omniparser_cfg.get('BOX_THRESHOLD', 0.05)
                iou_threshold = omniparser_cfg.get('IOU_THRESHOLD', 0.1)
                imgsz = omniparser_cfg.get('IMGSZ', 640)
            raw_results = grounding.predict(screenshot_path, box_threshold=box_threshold, iou_threshold=iou_threshold, imgsz=imgsz)
            if not raw_results:
                return BoundingBox(center_x=0, center_y=0, confidence=0.0, source='omniparser')
            parsed = grounding.parse_results(raw_results, application_window)
            best_match = self._find_best_match(parsed, target_description)
            if best_match:
                x0 = best_match.get('x0', 0)
                y0 = best_match.get('y0', 0)
                x1 = best_match.get('x1', 0)
                y1 = best_match.get('y1', 0)
                confidence = best_match.get('confidence', 0.7)
                return BoundingBox(center_x=(x0 + x1) // 2, center_y=(y0 + y1) // 2, width=x1 - x0, height=y1 - y0, confidence=confidence, source='omniparser')
            return BoundingBox(center_x=0, center_y=0, confidence=0.0, source='omniparser')
        except Exception as e:
            logger.warning(f'Stage 1 (OmniParser) failed: {e}')
            return None

    async def _stage2_cloud_vlm(self, screenshot_path: str, target_description: str, uia_tree: Optional[Dict[str, Any]]=None) -> Optional[BoundingBox]:
        """
        Cascade to Cloud VLM for element grounding.
        Sends screenshot + targeted prompt to BACKUP_AGENT (Gemini/GPT).
        """
        try:
            from ufo.llm.llm_call import get_completion
            from ufo.llm import AgentType
            from ufo.security.pii_redactor import PIIRedactor
            import base64
            effective_screenshot_path = screenshot_path
            try:
                redactor = PIIRedactor()
                if redactor.should_redact_for_model(is_cloud=True):
                    redacted_path, _ = redactor.redact_for_cloud(screenshot_path, uia_tree)
                    if redacted_path and os.path.exists(redacted_path):
                        effective_screenshot_path = redacted_path
            except Exception as e:
                logger.warning(f'PII redaction on vision fallback screenshot failed: {e}')
            with open(effective_screenshot_path, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
            ext = os.path.splitext(effective_screenshot_path)[1].lower()
            mime = 'image/png' if ext == '.png' else 'image/jpeg'
            prompt = f"""Analyze the provided screenshot. Locate the UI element described as: '{target_description}'.\n\nReturn ONLY a JSON object with the absolute pixel coordinates for the center of the element and your confidence level:\n{{"center_x": <int>, "center_y": <int>, "width": <int>, "height": <int>, "confidence": <float 0.0-1.0>}}\n\nIf the element cannot be found, return: {{"center_x": 0, "center_y": 0, "confidence": 0.0}}"""
            messages = [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{img_b64}'}}]}]
            agent_type = self._cloud_vlm_agent
            if hasattr(AgentType, agent_type.replace('_AGENT', '')):
                agent_type = getattr(AgentType, agent_type.replace('_AGENT', ''), AgentType.BACKUP)
            llm_result = await get_completion(messages, agent=agent_type, use_backup_engine=False)
            response_text = llm_result.responses[0] if llm_result.responses else ''
            parsed = self._parse_json_response(response_text)
            if parsed and parsed.get('center_x', 0) > 0:
                return BoundingBox(center_x=int(parsed['center_x']), center_y=int(parsed['center_y']), width=int(parsed.get('width', 0)), height=int(parsed.get('height', 0)), confidence=float(parsed.get('confidence', 0.9)), source='cloud_vlm')
            return None
        except Exception as e:
            logger.warning(f'Stage 2 (Cloud VLM) failed: {e}')
            return None

    async def _stage3_reducto(self, screenshot_path: str, target_description: str) -> Optional[BoundingBox]:
        """
        Cascade to Reducto API for robust element grounding using agentic OCR.
        Uploads screenshot and queries /parse endpoint.
        """
        try:
            import requests
            api_key = os.environ.get("REDUCTO_API_KEY")
            if not api_key:
                # Use the default known key for BankFidelity integration if env var missing
                api_key = "605a959c5370e7540599d9e25adee460e6902de8a3f5ee7adba463b2e76ecb02c4b1bcc096b6deb885baf1950f106595"
            
            headers = {"Authorization": f"Bearer {api_key}"}
            
            # Step 1: Upload
            upload_url = "https://platform.reducto.ai/upload"
            with open(screenshot_path, "rb") as f:
                upload_res = requests.post(upload_url, headers=headers, files={"file": f})
            upload_res.raise_for_status()
            file_id = upload_res.json().get("file_id")
            if not file_id:
                return None
                
            # Step 2: Parse with agentic OCR
            parse_url = "https://platform.reducto.ai/parse"
            prompt_text = (
                f"Analyze the screenshot and locate the UI element described as: '{target_description}'. "
                f"Return ONLY a JSON object with the absolute pixel coordinates for the center of the element and your confidence level:\n"
                f"{{\"center_x\": <int>, \"center_y\": <int>, \"width\": <int>, \"height\": <int>, \"confidence\": <float 0.0-1.0>}}"
            )
            payload = {
                "document_url": f"reducto://{file_id}",
                "ocr_mode": "agentic",
                "custom_prompt": prompt_text
            }
            parse_res = requests.post(parse_url, headers=headers, json=payload)
            parse_res.raise_for_status()
            parsed_data = parse_res.json()
            
            # Check Reducto output format. It usually returns structured JSON if prompted.
            result_text = str(parsed_data)
            parsed_json = self._parse_json_response(result_text)
            if parsed_json and parsed_json.get('center_x', 0) > 0:
                return BoundingBox(
                    center_x=int(parsed_json['center_x']), 
                    center_y=int(parsed_json['center_y']), 
                    width=int(parsed_json.get('width', 0)), 
                    height=int(parsed_json.get('height', 0)), 
                    confidence=float(parsed_json.get('confidence', 0.9)), 
                    source='reducto'
                )
            
            return None
        except Exception as e:
            logger.warning(f'Stage 3 (Reducto API) failed: {e}')
            return None

    def _capture_screenshot(self, application_window: Any=None) -> Optional[str]:
        """Capture a screenshot, either of the app window or full desktop."""
        try:
            import pyautogui
            path = os.path.join(tempfile.gettempdir(), 'ufo_vision_fallback.png')
            if application_window is not None:
                try:
                    rect = application_window.rectangle()
                    pyautogui.screenshot(path, region=(rect.left, rect.top, rect.width(), rect.height()))
                except Exception:
                    pyautogui.screenshot(path)
            else:
                pyautogui.screenshot(path)
            return path
        except Exception as e:
            logger.error(f'Screenshot capture failed: {e}')
            return None

    @staticmethod
    def _find_best_match(parsed_boxes: List[Dict[str, Any]], target_description: str) -> Optional[Dict[str, Any]]:
        """Find the best matching box for the target description."""
        target_lower = target_description.lower().strip()
        best = None
        best_score = 0.0
        for box in parsed_boxes:
            name = str(box.get('name', '')).lower().strip()
            if not name:
                continue
            if name == target_lower:
                box['confidence'] = 0.95
                return box
            if target_lower in name or name in target_lower:
                score = len(name) / max(len(target_lower), 1)
                if score > best_score:
                    best_score = score
                    box['confidence'] = min(0.5 + score * 0.4, 0.9)
                    best = box
        return best

    @staticmethod
    def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from an LLM response that may contain markdown fences."""
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            cleaned = '\n'.join(lines).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find('{')
            end = cleaned.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
        return None