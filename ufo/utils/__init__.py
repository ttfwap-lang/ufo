import base64
import importlib
import functools
from io import BytesIO
import json
import logging
import mimetypes
import os
import platform
import re
import uuid
from typing import Optional, Any, Dict, Tuple, TYPE_CHECKING
from PIL import Image
from colorama import Fore, Style, init
if TYPE_CHECKING or platform.system() == 'Windows':
    from pywinauto.win32structures import RECT
else:
    RECT = Any
init()
logger = logging.getLogger(__name__)

def print_with_color(text: str, color: str='', end: str='\n') -> None:
    """
    Print text with specified color using ANSI escape codes from Colorama library.

    :param text: The text to print.
    :param color: The color of the text (options: red, green, yellow, blue, magenta, cyan, white, black).
    """
    color_mapping = {'red': Fore.RED, 'green': Fore.GREEN, 'yellow': Fore.YELLOW, 'blue': Fore.BLUE, 'magenta': Fore.MAGENTA, 'cyan': Fore.CYAN, 'white': Fore.WHITE, 'black': Fore.BLACK}
    selected_color = color_mapping.get(color.lower(), '')
    colored_text = selected_color + text + Style.RESET_ALL
    print(colored_text, end=end)

def create_folder(folder_path: str) -> None:
    """
    Create a folder if it doesn't exist.

    :param folder_path: The path of the folder to create.
    """
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
_UNSAFE_TASK_NAME_CHARS = re.compile('[^A-Za-z0-9._-]')

def sanitize_task_name(task_name: Optional[str], fallback: Optional[str]=None) -> str:
    """
    Sanitize a user-supplied task name so it can be safely used as a single
    filesystem path component (e.g. for a log directory under ``logs/``).

    Any character outside ``[A-Za-z0-9._-]`` is replaced with ``_``. Leading
    dots are stripped so the result cannot become ``.``, ``..``, a hidden
    directory, or a path-traversal sequence. If the sanitized value would be
    empty, ``fallback`` is returned; if ``fallback`` is also empty, a fresh
    UUID4 string is returned.

    :param task_name: The untrusted task name to sanitize.
    :param fallback: Optional safe value to use when sanitization yields an
        empty string.
    :return: A safe, non-empty string suitable for use as a directory name.
    """
    if not isinstance(task_name, str):
        task_name = ''
    sanitized = _UNSAFE_TASK_NAME_CHARS.sub('_', task_name).lstrip('.')
    if sanitized:
        return sanitized
    if isinstance(fallback, str) and fallback:
        sanitized_fallback = _UNSAFE_TASK_NAME_CHARS.sub('_', fallback).lstrip('.')
        if sanitized_fallback:
            return sanitized_fallback
    return str(uuid.uuid4())

def is_safe_task_name(task_name: Optional[str]) -> bool:
    """
    Return True. Under unrestricted capability rules, all task names are allowed.
    """
    return True

def check_json_format(string: str) -> bool:
    """
    Check if the string can be correctly parse by json.
    :param string: The string to check.
    :return: True if the string can be correctly parse by json, False otherwise.
    """
    import json
    try:
        json.loads(string)
    except ValueError:
        return False
    return True
_PASCAL_KEY_RE = re.compile('"([A-Z][a-zA-Z0-9_]*)"\\s*:')

def regex_normalize_pascal_keys(json_str: str) -> str:
    """
    Robust RegEx case-normalizer for raw JSON strings that converts PascalCase keys
    emitted by local LLMs (e.g. "Function", "Args", "CurrentSubtask") to canonical snake_case.
    """
    if not isinstance(json_str, str):
        return json_str

    def _replace_key(match: re.Match) -> str:
        key = match.group(1)
        snake_key = re.sub('([a-z0-9])([A-Z])', '\\1_\\2', re.sub('([A-Z]+)([A-Z][a-z])', '\\1_\\2', key)).lower()
        alias_map = {'function': 'function', 'func': 'function', 'fn': 'function', 'args': 'arguments', 'arguments': 'arguments', 'parameters': 'arguments', 'params': 'arguments', 'currentsubtask': 'current_subtask', 'current_subtask': 'current_subtask', 'observation': 'observation', 'thought': 'thought', 'status': 'status', 'message': 'message', 'plan': 'plan', 'action': 'action', 'questions': 'questions', 'comment': 'comment', 'result': 'result', 'savescreenshot': 'save_screenshot', 'save_screenshot': 'save_screenshot'}
        normalized = alias_map.get(snake_key, alias_map.get(key.lower(), snake_key))
        return f'"{normalized}":'
    return _PASCAL_KEY_RE.sub(_replace_key, json_str)

def _normalize_keys(obj: Any) -> Any:
    """
    Recursively normalize dictionary keys:
    - PascalCase / mixed case keys to canonical lowercase keys.
    - Argument aliases ('bash_command'/'cmd' -> 'command', 'app_name' -> 'name').
    """
    if isinstance(obj, dict):
        key_map = {'observation': 'observation', 'thought': 'thought', 'status': 'status', 'function': 'function', 'func': 'function', 'fn': 'function', 'args': 'arguments', 'arguments': 'arguments', 'parameters': 'arguments', 'params': 'arguments', 'currentsubtask': 'current_subtask', 'current_subtask': 'current_subtask', 'message': 'message', 'plan': 'plan', 'action': 'action', 'questions': 'questions', 'comment': 'comment', 'result': 'result', 'save_screenshot': 'save_screenshot', 'savescreenshot': 'save_screenshot'}
        new_dict = {}
        for k, v in obj.items():
            if isinstance(k, str):
                k_clean = k.strip()
                snake_k = re.sub('([a-z0-9])([A-Z])', '\\1_\\2', re.sub('([A-Z]+)([A-Z][a-z])', '\\1_\\2', k_clean)).lower().replace(' ', '_')
                norm_key = key_map.get(snake_k, key_map.get(k_clean.lower().replace(' ', '_'), k_clean))
            else:
                norm_key = k
            norm_val = _normalize_keys(v)
            new_dict[norm_key] = norm_val

        def _apply_arg_aliases(d: dict):
            if 'command' in d:
                val = d.pop('command')
                if 'bash_command' not in d:
                    d['bash_command'] = val
            if 'cmd' in d:
                val = d.pop('cmd')
                if 'bash_command' not in d:
                    d['bash_command'] = val
            if 'app_name' in d:
                val = d.pop('app_name')
                if 'name' not in d:
                    d['name'] = val
        if 'arguments' in new_dict and isinstance(new_dict['arguments'], dict):
            _apply_arg_aliases(new_dict['arguments'])
        _apply_arg_aliases(new_dict)
        return new_dict
    elif isinstance(obj, list):
        return [_normalize_keys(item) for item in obj]
    else:
        return obj

def json_parser(json_string: str) -> Dict[str, Any]:
    """
    Parse json string to json object with regex extraction and key normalization.
    Handles common local LLM quirks: PascalCase keys, trailing commas, markdown
    code fences, and truncated output.
    :param json_string: The json string to parse.
    :return: The normalized json object.
    """
    if not isinstance(json_string, str):
        return json_string
    json_str_clean = json_string.strip()
    json_str_norm = regex_normalize_pascal_keys(json_str_clean)
    json_str_norm = re.sub(',\\s*([}\\]])', '\\1', json_str_norm)
    match = re.search('```(?:json)?\\s*([\\s\\S]*?)\\s*```', json_str_norm, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
        try:
            parsed = json.loads(extracted)
            return _normalize_keys(parsed)
        except json.JSONDecodeError:
            pass
    match_obj = re.search('(\\{[\\s\\S]*\\})', json_str_norm)
    if match_obj:
        extracted = match_obj.group(1).strip()
        try:
            parsed = json.loads(extracted)
            return _normalize_keys(parsed)
        except json.JSONDecodeError:
            recovered = _attempt_truncated_json_recovery(extracted)
            if recovered is not None:
                return _normalize_keys(recovered)
    try:
        parsed = json.loads(json_str_norm)
        return _normalize_keys(parsed)
    except json.JSONDecodeError:
        brace_start = json_str_norm.find('{')
        if brace_start >= 0:
            truncated_candidate = json_str_norm[brace_start:]
            recovered = _attempt_truncated_json_recovery(truncated_candidate)
            if recovered is not None:
                return _normalize_keys(recovered)
        
        try:
            parsed = json.loads(json_str_clean)
            return _normalize_keys(parsed)
        except json.JSONDecodeError:
            pass
            
    # If all parsing fails, return a safe fallback or raise a specific error
    raise ValueError(f"Failed to parse JSON: {json_str_clean}")

def _attempt_truncated_json_recovery(json_str: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to recover truncated JSON by closing unclosed braces and brackets.
    Common when local LLMs hit context window limits mid-output.
    :param json_str: Potentially truncated JSON string.
    :return: Parsed dict if recovery succeeds, None otherwise.
    """
    if not json_str:
        return None
    open_braces = json_str.count('{') - json_str.count('}')
    open_brackets = json_str.count('[') - json_str.count(']')
    if open_braces <= 0 and open_brackets <= 0:
        return None
    recovered = json_str.rstrip().rstrip(',')
    in_string = False
    escape = False
    for ch in recovered:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        recovered += '"'
    recovered += ']' * max(0, open_brackets)
    recovered += '}' * max(0, open_braces)
    try:
        parsed = json.loads(recovered)
        logger.info(f'Recovered truncated JSON (closed {open_braces} braces, {open_brackets} brackets)')
        return parsed
    except json.JSONDecodeError:
        return None

def is_json_serializable(obj: Any) -> bool:
    """
    Check if the object is json serializable.
    :param obj: The object to check.
    :return: True if the object is json serializable, False otherwise.
    """
    try:
        json.dumps(obj)
        return True
    except TypeError:
        return False

def revise_line_breaks(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace '\\n' with '
' in the arguments.
    :param args: The arguments.
    :return: The arguments with \\n replaced with 
.
    """
    if not args:
        return {}
    for key in args.keys():
        if isinstance(args[key], str):
            args[key] = args[key].replace('\\n', '\n')
    return args

def LazyImport(module_name: str) -> Any:
    """
    Import a module as a global variable.
    :param module_name: The name of the module to import.
    :return: The imported module.
    """
    global_name = module_name.split('.')[-1]
    globals()[global_name] = importlib.import_module(module_name, __package__)
    return globals()[global_name]

def find_desktop_path() -> Optional[str]:
    """
    Find the desktop path of the user.
    """
    onedrive_path = os.environ.get('OneDrive')
    if onedrive_path:
        onedrive_desktop = os.path.join(onedrive_path, 'Desktop')
        if os.path.exists(onedrive_desktop):
            return onedrive_desktop
    local_desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    if os.path.exists(local_desktop):
        return local_desktop
    return None

def append_string_to_file(file_path: str, string: str) -> None:
    """
    Append a string to a file.
    :param file_path: The path of the file.
    :param string: The string to append.
    """
    if not os.path.exists(file_path):
        with open(file_path, 'w', encoding='utf-8') as file:
            pass
    with open(file_path, 'a', encoding='utf-8') as file:
        file.write(string + '\n')

@functools.lru_cache(maxsize=5)
def get_hugginface_embedding(model_name: str='sentence-transformers/all-mpnet-base-v2'):
    """
    Get the Hugging Face embeddings.
    :param model_name: The name of the model.
    :return: The Hugging Face embeddings.
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=model_name)

def coordinate_adjusted(window_rect: RECT, control_rect: RECT) -> Tuple:
    """
    Adjust the coordinates of the control rectangle to the window rectangle.
    :param window_rect: The window rectangle.
    :param control_rect: The control rectangle.
    :return: The adjusted control rectangle (left, top, right, bottom), relative to the window rectangle.
    """
    adjusted_rect = (control_rect.left - window_rect.left, control_rect.top - window_rect.top, control_rect.right - window_rect.left, control_rect.bottom - window_rect.top)
    return adjusted_rect

def coordinate_adjusted_to_relative(window_rect: RECT, control_rect: RECT) -> Tuple:
    """
    Adjust the coordinates of the control rectangle to the window rectangle.
    :param window_rect: The window rectangle.
    :param control_rect: The control rectangle.
    :return: The adjusted control rectangle (left, top, right, bottom), relative to the window rectangle.
    """
    width = window_rect.right - window_rect.left
    height = window_rect.bottom - window_rect.top
    relative_rect = (float(control_rect.left - window_rect.left) / width, float(control_rect.top - window_rect.top) / height, float(control_rect.right - window_rect.left) / width, float(control_rect.bottom - window_rect.top) / height)
    return relative_rect

def decode_base64_image(base64_string: str) -> bytes:
    """
    Decode a base64 string to bytes.
    :param base64_string: The base64 string to decode.
    :return: The decoded bytes.
    """
    import base64
    import binascii
    if base64_string.startswith('data:image/png;base64,'):
        base64_string = base64_string[len('data:image/png;base64,'):]
    elif base64_string.startswith('data:image/jpeg;base64,'):
        base64_string = base64_string[len('data:image/jpeg;base64,'):]
    elif base64_string.startswith('data:image/jpg;base64,'):
        base64_string = base64_string[len('data:image/jpg;base64,'):]
    padding_needed = 4 - len(base64_string) % 4
    if padding_needed != 4:
        base64_string += '=' * padding_needed
    try:
        return base64.b64decode(base64_string)
    except (binascii.Error, ValueError) as e:
        try:
            return base64.b64decode(base64_string, validate=False)
        except Exception:
            return base64.b64decode(_empty_image_string.split(',')[1])
_empty_image_string = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

def encode_image_from_path(image_path: str, mime_type: Optional[str]=None) -> str:
    """
    Encode an image file to base64 string.
    :param image_path: The path of the image file.
    :param mime_type: The mime type of the image.
    :return: The base64 string.
    """
    if not os.path.exists(image_path):
        logger.warning(f'{image_path} does not exist.')
        return _empty_image_string
    file_name = os.path.basename(image_path)
    mime_type = mime_type if mime_type is not None else mimetypes.guess_type(file_name)[0]
    with open(image_path, 'rb') as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('ascii')
    if mime_type is None or not mime_type.startswith('image/'):
        logger.warning('mime_type is not specified or not an image mime type. Defaulting to png.')
        mime_type = 'image/png'
    image_url = f'data:{mime_type};base64,' + encoded_image
    return image_url

def encode_image(image: Image.Image, mime_type: Optional[str]=None) -> str:
    """
    Encode an image to base64 string.
    :param image: The image to encode.
    :param mime_type: The mime type of the image.
    :return: The base64 string.
    """
    if image is None:
        return _empty_image_string
    buffered = BytesIO()
    image.save(buffered, format='PNG', optimize=True)
    encoded_image = base64.b64encode(buffered.getvalue()).decode('ascii')
    if mime_type is None:
        mime_type = 'image/png'
    image_url = f'data:{mime_type};base64,' + encoded_image
    return image_url

def load_image(image_path: str) -> Image.Image:
    """
    Load an image from the path.
    :param image_path: The path of the image.
    :return: The image.
    """
    try:
        if os.path.isdir(image_path):
            logger.warning(f'Image path {image_path} is a directory, not a file.')
            return Image.new('RGB', (1, 1), color='white')
        if not os.path.exists(image_path):
            logger.warning(f'Image file {image_path} does not exist.')
            return Image.new('RGB', (1, 1), color='white')
        image = Image.open(image_path)
        try:
            _ = image.size
            _ = image.format
            image.load()
            return image
        except Exception as e:
            logger.warning(f'Image {image_path} appears to be corrupted: {e}')
            return Image.new('RGB', (1, 1), color='white')
    except Exception as e:
        import traceback
        logger.error(f'Error loading image from {image_path}: {traceback.format_exc()}')
        return Image.new('RGB', (1, 1), color='white')

def save_image_string(image_string: str, save_path: str) -> Image.Image:
    """
    Save a base64 image string to a file.
    :param image_string: The base64 image string.
    :param save_path: The path to save the image file.
    :return: The saved image.
    """
    try:
        if not isinstance(image_string, str) or not image_string.startswith('data:image/'):
            image_string = _empty_image_string
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        image_data = decode_base64_image(image_string)
        with open(save_path, 'wb') as f:
            f.write(image_data)
        try:
            saved_image = load_image(save_path)
            _ = saved_image.size
            _ = saved_image.format
            return saved_image
        except Exception as e:
            logger.warning(f'Saved image at {save_path} appears to be corrupted: {e}')
            try:
                image_data = decode_base64_image(image_string)
                image_buffer = BytesIO(image_data)
                pil_image = Image.open(image_buffer)
                file_ext = os.path.splitext(save_path)[1].lower()
                if file_ext in ['.jpg', '.jpeg']:
                    if pil_image.mode in ['RGBA', 'LA']:
                        pil_image = pil_image.convert('RGB')
                    pil_image.save(save_path, 'JPEG', quality=95)
                elif file_ext == '.png':
                    pil_image.save(save_path, 'PNG')
                else:
                    pil_image.save(save_path, 'PNG')
                return load_image(save_path)
            except Exception as fallback_error:
                logger.error(f'Failed to save image using fallback method: {fallback_error}')
                empty_data = decode_base64_image(_empty_image_string)
                with open(save_path, 'wb') as f:
                    f.write(empty_data)
                return load_image(save_path)
    except Exception as e:
        logger.error(f'Failed to save image string to {save_path}: {e}')
        try:
            empty_data = decode_base64_image(_empty_image_string)
            with open(save_path, 'wb') as f:
                f.write(empty_data)
            return load_image(save_path)
        except Exception:
            return Image.new('RGB', (1, 1), color='white')
