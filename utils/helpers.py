# ================================================
# File: utils/helpers.py
# ================================================
import os
import urllib.parse
import re 
from pathlib import Path
from typing import Optional, List, Dict, Any

import folder_paths 

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
        # Ensure the relative path is treated correctly even if it contains os-specific separators internally
        # os.path.join will handle combining MODELS_DIR and the potentially complex relative_path
        full_path = os.path.join(MODELS_DIR, relative_path)
    else:
        # Default to the 'other' directory if type is unknown
        print(f"Warning: Unknown model type '{model_type}'. Saving to 'other' directory.")
        relative_path = MODEL_TYPE_DIRS['other'][1]
        full_path = os.path.join(MODELS_DIR, relative_path)

    # Ensure the directory exists
    try:
        os.makedirs(full_path, exist_ok=True)
    except OSError as e:
         # Handle potential errors like permission denied
         print(f"Error: Could not create directory '{full_path}': {e}")
         # Fallback? Or raise error? For now, just print and return, download will likely fail.
         # Consider falling back to a known-good temp location if MODELS_DIR itself is bad? Complex.
         pass
    return full_path

def parse_civitai_input(url_or_id: str) -> tuple[int | None, int | None]:
    """
    Parses Civitai URL or ID string.
    Returns: (model_id, version_id) tuple. Both can be None.
    Handles URLs like /models/123 and /models/123?modelVersionId=456
    """
    if not url_or_id:
        return None, None

    url_or_id = str(url_or_id).strip()
    model_id: int | None = None
    version_id: int | None = None
    query_params = {}

    # Check if it's just a number (could be model or version ID)
    # Treat digits-only input as MODEL ID primarily, as users often copy just that.
    # Version ID can be specified separately or via full URL query param.
    if url_or_id.isdigit():
        try:
            # Assume it's a Model ID if just digits are provided.
             model_id = int(url_or_id)
             print(f"Parsed input '{url_or_id}' as Model ID.")
             # Don't assume it's a version ID here. Let it be specified if needed.
             return model_id, None
        except (ValueError, TypeError):
              print(f"Warning: Could not parse '{url_or_id}' as a numeric ID.")
              return None, None

    # If not just digits, try parsing as URL
    try:
        parsed_url = urllib.parse.urlparse(url_or_id)

        # Basic check for URL structure and domain
        if not parsed_url.scheme or not parsed_url.netloc:
            # Maybe it's a path like /models/123 without the domain?
            if url_or_id.startswith(("/models/", "/model-versions/")):
                 # Re-parse with a dummy scheme and domain
                 parsed_url = urllib.parse.urlparse("https://civitai.com" + url_or_id)
                 if not parsed_url.path: # If still fails, give up
                      print(f"Input '{url_or_id}' is not a recognizable Civitai path or URL.")
                      return None, None
            else:
                 print(f"Input '{url_or_id}' is not a valid ID or Civitai URL/path.")
                 return None, None

        # Check domain if it was present
        if parsed_url.netloc and "civitai.com" not in parsed_url.netloc.lower():
            print(f"Input URL '{url_or_id}' is not a Civitai URL.")
            return None, None

        # Extract path components and query parameters
        path_parts = [p for p in parsed_url.path.split('/') if p] # Remove empty parts
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # --- Logic ---
        # 1. Check query params for modelVersionId FIRST (most explicit)
        if 'modelVersionId' in query_params:
            try:
                version_id = int(query_params['modelVersionId'][0])
                print(f"Found Version ID {version_id} in query parameters.")
            except (ValueError, IndexError, TypeError):
                print(f"Warning: Found modelVersionId in query but couldn't parse: {query_params.get('modelVersionId')}")
                version_id = None # Reset if parsing failed

        # 2. Check path for /models/ID
        model_id_from_path = None
        if "models" in path_parts:
             try:
                 models_index = path_parts.index("models")
                 if models_index + 1 < len(path_parts):
                     # Take the part right after /models/ and check if it's digits
                     potential_id_str = path_parts[models_index + 1]
                     if potential_id_str.isdigit():
                          model_id_from_path = int(potential_id_str)
                          print(f"Found Model ID {model_id_from_path} in URL path.")
             except (ValueError, IndexError, TypeError):
                  print(f"Warning: Found /models/ in path but couldn't parse ID from {path_parts}")

        # 3. Check path for /model-versions/ID (less common, usually doesn't contain model ID)
        version_id_from_path = None
        if version_id is None and "model-versions" in path_parts: # Only check if not found in query
             try:
                 versions_index = path_parts.index("model-versions")
                 if versions_index + 1 < len(path_parts):
                     potential_id_str = path_parts[versions_index + 1]
                     if potential_id_str.isdigit():
                           version_id_from_path = int(potential_id_str)
                           # Set version_id only if not already set by query param
                           if version_id is None:
                                version_id = version_id_from_path
                                print(f"Found Version ID {version_id} in URL path.")
             except (ValueError, IndexError, TypeError):
                  print(f"Warning: Found /model-versions/ in path but couldn't parse ID from {path_parts}")

        # 4. Assign final model ID (prefer path over digits-only assumption if URL was parsed)
        if model_id_from_path is not None:
             model_id = model_id_from_path
        # If no model ID found yet and input looked like a URL, maybe it was ONLY a version URL?
        elif model_id is None and version_id is not None:
            print("Warning: Found Version ID but no Model ID in the URL. Model info might be incomplete.")
         # Keep the initially parsed model_id if input was digits-only

    except Exception as e:
        print(f"Error parsing Civitai input '{url_or_id}': {e}")
        return None, None

    print(f"Parsed Civitai input: Model ID = {model_id}, Version ID = {version_id}")
    # Return the determined IDs. It's the caller's responsibility to fetch model info if only version ID is present.
    return model_id, version_id

# Updated sanitize_filename to be more restrictive
def sanitize_filename(filename: str, default_filename: str = "downloaded_model") -> str:
    """
    Stricter filename sanitization. Replaces invalid characters, trims whitespace,
    handles reserved names (Windows), and ensures it's not empty.
    Aims for better cross-OS compatibility.
    """
    if not filename:
        return default_filename

    # Decode if bytes
    if isinstance(filename, bytes):
        try:
            filename = filename.decode('utf-8')
        except UnicodeDecodeError:
            # If decode fails, fall back to a safe default representation or hex
            # For simplicity, just use default for now if decoding problematic bytes
            return default_filename + "_decode_error"

    # Remove characters invalid for Windows/Linux/MacOS filenames
    # Invalid Chars: < > : " / \ | ? * and control characters (0-31)
    # Also replace NULL character just in case.
    sanitized = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', filename)

    # Replace sequences of multiple underscores or spaces introduced by replacement
    sanitized = re.sub(r'[_ ]{2,}', '_', sanitized)

    # Remove leading/trailing whitespace, dots, underscores
    sanitized = sanitized.strip('. _')

    # Windows Reserved Names (case-insensitive)
    reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
     # Check base name without extension
    base_name, ext = os.path.splitext(sanitized)
    if base_name.upper() in reserved_names:
         sanitized = f"_{base_name}_{ext}" # Prepend underscore

    # Prevent names that are just '.' or '..' (though stripping dots should handle this)
    if sanitized == '.' or sanitized == '..':
        sanitized = default_filename + "_invalid_name"

     # If sanitization results in an empty string (unlikely now), use default
    if not sanitized:
        sanitized = default_filename

    # Optional: Limit overall length (e.g., 200 chars), considering path limits
    # Be careful as some systems have path limits, not just filename limits
    max_len = 200 # A reasonable limit for the filename itself
    if len(sanitized) > max_len:
         name_part, ext_part = os.path.splitext(sanitized)
         # Truncate the name part, ensuring total length is within max_len
         allowed_name_len = max_len - len(ext_part)
         if allowed_name_len <= 0: # Handle case where extension itself is too long
              sanitized = sanitized[:max_len] # Truncate forcefully
         else:
              sanitized = name_part[:allowed_name_len] + ext_part
         print(f"Warning: Sanitized filename truncated to {max_len} characters.")

    return sanitized
    
def select_primary_file(files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Selects the best file from a list of files based on a heuristic.
    Prefers primary, then safetensors, then pruned, etc.
    Returns the selected file dictionary or None.
    """
    if not files or not isinstance(files, list):
        return None

    # First, try to find a file explicitly marked as "primary" with a valid download URL
    primary_marked_file = next((f for f in files if isinstance(f, dict) and f.get("primary") and f.get('downloadUrl')), None)
    if primary_marked_file:
        return primary_marked_file

    # If no primary file is marked, sort all available files using a heuristic
    def sort_key(file_obj):
        if not isinstance(file_obj, dict): return 99
        if not file_obj.get('downloadUrl'): return 98 # Deprioritize files without URL

        name_lower = file_obj.get("name", "").lower()
        meta = file_obj.get("metadata", {}) or {}
        format_type = meta.get("format", "").lower()
        size_type = meta.get("size", "").lower()
        
        # Fallback to file extension if format metadata missing
        is_safetensor = ".safetensors" in name_lower or format_type == "safetensor"
        is_pickle = ".ckpt" in name_lower or ".pt" in name_lower or format_type == "pickletensor"
        is_pruned = size_type == "pruned"

        if is_safetensor and is_pruned: return 0
        if is_safetensor: return 1
        if is_pickle and is_pruned: return 2
        if is_pickle: return 3
        # Prioritize model files over others like VAEs if type is available
        if file_obj.get("type") == "Model": return 4
        if file_obj.get("type") == "Pruned Model": return 5
        return 10 # Other types last

    valid_files = [f for f in files if isinstance(f, dict) and f.get("downloadUrl")]
    if not valid_files:
        return None
        
    sorted_files = sorted(valid_files, key=sort_key)
    return sorted_files[0]