# ComfyUI_Civitai_Downloader/utils/helpers.py
import os
import urllib.parse
from pathlib import Path
import folder_paths # Use ComfyUI's folder_paths

# Import config values needed here
from ..config import MODELS_DIR, MODEL_TYPE_DIRS

def get_model_dir(model_type: str) -> str:
    """
    Get the appropriate absolute directory path for the model type.
    Ensures the directory exists.
    """
    model_type_key = model_type.lower().strip()

    if model_type_key in MODEL_TYPE_DIRS:
        relative_path = MODEL_TYPE_DIRS[model_type_key][1] # Get the subfolder name
        full_path = os.path.join(MODELS_DIR, relative_path)
    else:
        # Default to the 'other' directory if type is unknown
        print(f"Warning: Unknown model type '{model_type}'. Saving to 'other' directory.")
        relative_path = MODEL_TYPE_DIRS['other'][1]
        full_path = os.path.join(MODELS_DIR, relative_path)

    # Ensure the directory exists
    os.makedirs(full_path, exist_ok=True)
    return full_path

def parse_civitai_input(url_or_id: str) -> tuple[int | None, int | None]:
    """
    Parses Civitai URL or ID string.
    Returns: (model_id, version_id) tuple. Both can be None.
    """
    if not url_or_id:
        return None, None

    url_or_id = str(url_or_id).strip()
    model_id: int | None = None
    version_id: int | None = None
    query_params = {}

    # Check if it's just a number (could be model or version ID)
    if url_or_id.isdigit():
        # Ambiguous: could be model or version. Assume model ID for now.
        # The API logic will need to handle fetching based on what's available.
        model_id = int(url_or_id)
        print(f"Parsed input as potential Model ID: {model_id}")
        return model_id, None # Return only model ID if just numbers

    # If not just digits, try parsing as URL
    try:
        parsed_url = urllib.parse.urlparse(url_or_id)
        if not parsed_url.scheme or not parsed_url.netloc:
             # Not a valid URL structure
            print(f"Input '{url_or_id}' is not a valid ID or Civitai URL.")
            return None, None

        if "civitai.com" not in parsed_url.netloc.lower():
            print(f"Input URL '{url_or_id}' is not a Civitai URL.")
            return None, None

        path_parts = [p for p in parsed_url.path.split('/') if p] # Remove empty parts
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Look for modelVersionId in query params FIRST - most reliable
        if 'modelVersionId' in query_params:
            try:
                version_id = int(query_params['modelVersionId'][0])
            except (ValueError, IndexError):
                print(f"Warning: Found modelVersionId in query but couldn't parse: {query_params['modelVersionId']}")
                version_id = None # Reset if parsing failed

        # Look for model ID in path (/models/12345)
        if "models" in path_parts:
            try:
                models_index = path_parts.index("models")
                if models_index + 1 < len(path_parts):
                    model_id_str = path_parts[models_index + 1]
                    # Handle cases like /models/12345/reviews - take only the numerical ID part
                    if model_id_str.isdigit():
                         model_id = int(model_id_str)
            except (ValueError, IndexError):
                 print(f"Warning: Found /models/ in path but couldn't parse ID: {path_parts}")
                 model_id = None # Reset if parsing failed

        # Look for version ID in path (/model-versions/5678) - less common for copy-paste
        elif "model-versions" in path_parts and version_id is None: # Only if not found in query
             try:
                 versions_index = path_parts.index("model-versions")
                 if versions_index + 1 < len(path_parts):
                     version_id_str = path_parts[versions_index + 1]
                     if version_id_str.isdigit():
                           version_id = int(version_id_str)
                           # We don't easily get model_id from this URL structure alone
             except (ValueError, IndexError):
                  print(f"Warning: Found /model-versions/ in path but couldn't parse ID: {path_parts}")
                  version_id = None

    except Exception as e:
        print(f"Error parsing Civitai input '{url_or_id}': {e}")
        return None, None

    print(f"Parsed Civitai input: Model ID = {model_id}, Version ID = {version_id}")
    return model_id, version_id

def sanitize_filename(filename: str, default_filename: str = "downloaded_model") -> str:
    """
    Basic filename sanitization. Replaces invalid characters and ensures it's not empty.
    Does NOT guarantee filesystem compatibility across all OSes but removes common issues.
    """
    if not filename:
        return default_filename

    # Remove or replace potentially problematic characters
    # Keep letters, numbers, spaces, dots, underscores, hyphens
    sanitized = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()

    # Replace multiple spaces with single space
    sanitized = ' '.join(sanitized.split())

    # Prevent names like '.', '..', or starting/ending with '.' or ' '
    sanitized = sanitized.strip('. ')

    # If sanitization results in an empty string, use default
    if not sanitized:
        sanitized = default_filename

    # Optional: Limit length? (e.g., 200 chars)
    # sanitized = sanitized[:200]

    return sanitized

def create_placeholder_image(path: str):
    """Creates a simple placeholder image if Pillow is available."""
    if os.path.exists(path):
        return
    try:
        from PIL import Image
        img = Image.new('RGB', (100, 100), color = (50, 50, 50))
        img.save(path)
        print(f"Created placeholder image: {path}")
    except ImportError:
        print("Pillow not found, cannot create placeholder image. Please install PIL/Pillow.")
    except Exception as e:
        print(f"Error creating placeholder image at {path}: {e}")