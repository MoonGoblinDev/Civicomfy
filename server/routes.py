# ================================================
# File: server/routes.py
# ================================================
# ================================================
# File: server/routes.py (Updated)
# This file needs to pass more info (model_info, version_info, primary_file)
# to the DownloadManager.
# ================================================
import asyncio
from typing import Any, Dict, Optional
import server # ComfyUI server instance
import os
import traceback
import urllib.parse # Needed for thumbnail processing
import re
import math
import json
from aiohttp import web


# Import necessary components from our modules
from ..downloader.manager import manager as download_manager # Use the global instance
from ..api.civitai import CivitaiAPI
from ..utils.helpers import get_model_dir, parse_civitai_input, sanitize_filename
from ..config import MODEL_TYPE_DIRS, CIVITAI_API_TYPE_MAP, PREVIEW_SUFFIX, METADATA_SUFFIX

# Get the PromptServer instance
prompt_server = server.PromptServer.instance

AVAILABLE_MEILI_BASE_MODELS = [
    "AuraFlow", "CogVideoX", "Flux.1 D", "Flux.1 S", "Hunyuan 1", "Hunyuan Video",
    "Illustrious", "Kolors", "LTXV", "Lumina", "Mochi", "NoobAI", "ODOR", "Other",
    "PixArt E", "PixArt a", "Playground v2", "Pony", "SD 1.4", "SD 1.5",
    "SD 1.5 Hyper", "SD 1.5 LCM", "SD 2.0", "SD 2.0 768", "SD 2.1", "SD 2.1 768",
    "SD 2.1 Unclip", "SD 3", "SD 3.5", "SD 3.5 Large", "SD 3.5 Large Turbo",
    "SD 3.5 Medium", "SDXL 0.9", "SDXL 1.0", "SDXL 1.0 LCM", "SDXL Distilled",
    "SDXL Hyper", "SDXL Lightning", "SDXL Turbo", "SVD", "SVD XT", "Stable Cascade",
    "Wan Video"
]

# --- Helper Functions ---

async def _get_request_json(request):
    """Safely get JSON data from request."""
    try:
        return await request.json()
    except Exception as e:
        print(f"Error parsing request JSON: {e}")
        raise web.HTTPBadRequest(reason=f"Invalid JSON format: {e}")

# --- API Endpoints ---

async def _get_civitai_model_and_version_details(api: CivitaiAPI, model_url_or_id: str, req_version_id: Optional[int]) -> Dict[str, Any]:
    """
    Helper to fetch Civitai details.
    Prioritizes fetching model info based on resolved Model ID.
    Fetches specific version info if version ID is provided/resolved, otherwise latest.
    Returns a dict with 'model_info', 'version_info', 'primary_file', and resolved IDs.
    Raises HTTP exceptions on critical failures.
    """
    target_model_id = None
    target_version_id = None
    potential_version_id_from_input = None
    model_info = {}
    version_info_to_use = {} # The version (specific or latest) whose file we'll use
    primary_file = None

    # --- 1. Parse Input to get potential IDs ---
    parsed_model_id, parsed_version_id = parse_civitai_input(model_url_or_id)

    # Determine the initial target model ID (input URL/ID takes precedence)
    target_model_id = parsed_model_id

    # Determine the specific version requested (explicit param > URL param)
    if req_version_id and str(req_version_id).isdigit():
        try:
            potential_version_id_from_input = int(req_version_id)
        except (ValueError, TypeError):
             print(f"[API Helper] Warning: Invalid req_version_id: {req_version_id}. Ignoring.")
    elif parsed_version_id:
        potential_version_id_from_input = parsed_version_id

    # --- 2. Ensure we have a Model ID ---
    # If we only got a version ID from the input (e.g., civitai.com/model-versions/456),
    # we need to fetch that version *first* just to find the model ID.
    if not target_model_id and potential_version_id_from_input:
        print(f"[API Helper] Input requires fetching version {potential_version_id_from_input} first to find model ID.")
        temp_version_info = api.get_model_version_info(potential_version_id_from_input)
        if temp_version_info and "error" not in temp_version_info and temp_version_info.get('modelId'):
            target_model_id = temp_version_info['modelId']
            print(f"[API Helper] Found Model ID {target_model_id} from Version ID {potential_version_id_from_input}.")
            # We might reuse temp_version_info later if this was the specifically requested version
        else:
            err = temp_version_info.get('details', 'Could not find model ID from version') if isinstance(temp_version_info, dict) else 'API error'
            raise web.HTTPNotFound(reason=f"Could not determine Model ID from Version ID {potential_version_id_from_input}", body=json.dumps({"error": f"Version {potential_version_id_from_input} not found or missing modelId", "details": err}))

    # If still no model ID after potential lookup, fail
    if not target_model_id:
        raise web.HTTPBadRequest(reason="Could not determine a valid Model ID from the input.")

    # --- 3. Fetch Core Model Information (Always based on target_model_id) ---
    print(f"[API Helper] Fetching core model info for Model ID: {target_model_id}")
    model_info_result = api.get_model_info(target_model_id)
    if not model_info_result or "error" in model_info_result:
        err_details = model_info_result.get('details', 'Unknown API error') if isinstance(model_info_result, dict) else 'Unknown API error'
        raise web.HTTPNotFound(reason=f"Model {target_model_id} not found or API error", body=json.dumps({"error": f"Model {target_model_id} not found or API error", "details": err_details}))
    model_info = model_info_result # Store the successfully fetched model info

    # --- 4. Determine and Fetch Version Info for File Details ---
    if potential_version_id_from_input:
        # User specified a version explicitly, fetch its details
        print(f"[API Helper] Fetching specific version info for Version ID: {potential_version_id_from_input}")
        target_version_id = potential_version_id_from_input # This is the version we need info for
        # Check if we already fetched this during Model ID lookup
        if 'temp_version_info' in locals() and temp_version_info.get('id') == target_version_id:
             print("[API Helper] Reusing version info fetched earlier.")
             version_info_to_use = temp_version_info
        else:
            version_info_result = api.get_model_version_info(target_version_id)
            if not version_info_result or "error" in version_info_result:
                err_details = version_info_result.get('details', 'Unknown API error') if isinstance(version_info_result, dict) else 'Unknown API error'
                raise web.HTTPNotFound(reason=f"Specified Version {target_version_id} not found or API error", body=json.dumps({"error": f"Version {target_version_id} not found or API error", "details": err_details}))
            version_info_to_use = version_info_result
    else:
        # No specific version requested, find latest/default from model_info
        print(f"[API Helper] Finding latest/default version for Model ID: {target_model_id}")
        versions = model_info.get("modelVersions")
        if not versions or not isinstance(versions, list) or len(versions) == 0:
            raise web.HTTPNotFound(reason=f"Model {target_model_id} has no listed model versions.")

        # Find the 'best' default version (usually first published)
        default_version_summary = next((v for v in versions if v.get('status') == 'Published'), versions[0])
        target_version_id = default_version_summary.get('id')
        if not target_version_id:
            raise web.HTTPNotFound(reason=f"Model {target_model_id}'s latest version has no ID.")

        print(f"[API Helper] Using latest/default Version ID: {target_version_id}. Fetching its full details.")
        # Fetch full details for this latest version
        version_info_result = api.get_model_version_info(target_version_id)
        if not version_info_result or "error" in version_info_result:
             # Log error, but maybe try to proceed with summary data if desperate? Risky.
            err_details = version_info_result.get('details', 'Unknown error getting full version') if isinstance(version_info_result, dict) else 'Error'
            print(f"[API Helper] Warning: Could not fetch full details for latest version {target_version_id}. Details: {err_details}. Falling back to summary.")
            # Use summary data from model_info as fallback - file info might be missing!
            version_info_to_use = default_version_summary
            # Ensure minimal structure for file finding later
            version_info_to_use['files'] = version_info_to_use.get('files', [])
            version_info_to_use['images'] = version_info_to_use.get('images', [])
            version_info_to_use['modelId'] = version_info_to_use.get('modelId', target_model_id) # Ensure modelId is present
            version_info_to_use['model'] = version_info_to_use.get('model', {'name': model_info.get('name', 'Unknown')}) # Add fallback model name

        else:
            version_info_to_use = version_info_result

    # --- 5. Find Primary File from the Determined Version (version_info_to_use) ---
    print(f"[API Helper] Finding primary file for Version ID: {target_version_id}")
    files = version_info_to_use.get("files", [])
    if not isinstance(files, list): files = []

    # Handle fallback downloadUrl at version level if 'files' is empty/missing
    if not files and 'downloadUrl' in version_info_to_use and version_info_to_use['downloadUrl']:
        print("[API Helper] Warning: No 'files' array found, using version-level 'downloadUrl'.")
        files = [{
            "id": None, "name": version_info_to_use.get('name', f"version_{target_version_id}_file"),
            "primary": True, "type": "Model", "sizeKB": version_info_to_use.get('fileSizeKB'),
            "downloadUrl": version_info_to_use['downloadUrl'], "hashes": {}, "metadata": {}
        }]

    if not files:
        raise web.HTTPNotFound(reason=f"Version {target_version_id} (Name: {version_info_to_use.get('name', 'N/A')}) has no files listed.")

    # Find primary file (using the same sorting logic as before)
    primary_file = next((f for f in files if isinstance(f, dict) and f.get("primary") and f.get('downloadUrl')), None)
    if not primary_file:
        def sort_key(file_obj): # Identical sort key logic
             if not isinstance(file_obj, dict): return 99
             if not file_obj.get('downloadUrl'): return 98
             name_lower = file_obj.get("name","").lower(); meta = file_obj.get("metadata", {}) or {}; format_type = meta.get("format","").lower(); size_type = meta.get("size","").lower()
             is_safetensor = ".safetensors" in name_lower or format_type == "safetensor"; is_pickle = ".ckpt" in name_lower or ".pt" in name_lower or format_type == "pickletensor"; is_pruned = size_type == "pruned"
             if is_safetensor and is_pruned: return 0;  # type: ignore
             if is_safetensor: return 1; # type: ignore
             if is_pickle and is_pruned: return 2; # type: ignore
             if is_pickle: return 3; # type: ignore
             if file_obj.get("type") == "Model": return 4; # type: ignore
             if file_obj.get("type") == "Pruned Model": return 5; # type: ignore
             return 10 # type: ignore
        valid_files = [f for f in files if isinstance(f, dict) and f.get("downloadUrl")]
        sorted_files = sorted(valid_files, key=sort_key)
        primary_file = sorted_files[0] if sorted_files else None

    if not primary_file or not isinstance(primary_file, dict) or not primary_file.get('downloadUrl'):
        raise web.HTTPNotFound(reason=f"Could not find any usable file with a download URL for version {target_version_id}.")

    print(f"[API Helper] Selected file: Name='{primary_file.get('name', 'N/A')}', SizeKB={primary_file.get('sizeKB')}")

    # --- 6. Return Results ---
    return {
        "model_info": model_info,                  # Always the full model info
        "version_info": version_info_to_use,       # Info for the specific/latest version
        "primary_file": primary_file,              # The file from that version
        "target_model_id": target_model_id,        # Resolved model ID
        "target_version_id": target_version_id,    # Resolved version ID (specific or latest)
    }
# --- NEW API ENDPOINT ---
@prompt_server.routes.post("/civitai/get_model_details")
async def route_get_model_details(request):
    """API Endpoint to fetch model/version details for preview."""
    try:
        data = await _get_request_json(request)
        model_url_or_id = data.get("model_url_or_id")
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        api_key = data.get("api_key", "")

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # Instantiate API
        api = CivitaiAPI(api_key or None)

        # Use the helper to get details
        details = await _get_civitai_model_and_version_details(api, model_url_or_id, req_version_id)
        model_info = details['model_info']
        version_info = details['version_info']
        primary_file = details['primary_file']
        target_model_id = details['target_model_id']
        target_version_id = details['target_version_id']

        # --- Extract Data for Frontend Preview ---
        model_name = model_info.get('name')
        creator_username = model_info.get('creator', {}).get('username', 'Unknown Creator')
        model_type = model_info.get('type', 'Unknown') # Checkpoint, LORA etc.

        stats = model_info.get('stats', version_info.get('stats', {})) # Ensure stats is a dict
        download_count = stats.get('downloadCount', 0)
        likes_count = stats.get('thumbsUpCount', 0)
        dislikes_count = stats.get('thumbsDownCount', 0)
        buzz_count = stats.get('tippedAmountCount', 0)
        

        # Get description from model_info (version description might be update notes)
        # Handle potential None value for description
        description_html = model_info.get('description')
        if description_html is None:
            description_html = "<p><em>No description provided.</em></p>"
        else:
            # Basic sanitization/check (could be more robust if needed)
            if not isinstance(description_html, str):
                 description_html = "<p><em>Invalid description format.</em></p>"
            elif not description_html.strip():
                 description_html = "<p><em>Description is empty.</em></p>"
        
        version_description_html = version_info.get('description')
        if version_description_html is None:
            version_description_html = "<p><em>No description provided.</em></p>"
        else:
            # Basic sanitization/check (could be more robust if needed)
            if not isinstance(version_description_html, str):
                 version_description_html = "<p><em>Invalid description format.</em></p>"
            elif not version_description_html.strip():
                 version_description_html = "<p><em>Description is empty.</em></p>"

        # File details
        file_name = primary_file.get('name', 'N/A')
        file_size_kb = primary_file.get('sizeKB', 0)
        file_format = primary_file.get('metadata', {}).get('format', 'N/A') # e.g., SafeTensor, PickleTensor

        thumbnail_url = None
        images = version_info.get("images") # Get the images list from the version info

        # Check if images list exists, is a list, has items, and the first item is valid with a URL
        if images and isinstance(images, list) and len(images) > 0 and \
           isinstance(images[0], dict) and images[0].get("url"):
            # Use the URL of the very first image directly
            thumbnail_url = images[0]["url"]
            print(f"[Get Details Route] Using first image URL as thumbnail: {thumbnail_url}")
        else:
            print("[Get Details Route] No valid first image found in version info, falling back to placeholder.")
            # Fallback placeholder logic (remains the same)
            placeholder_filename = os.path.basename(PLACEHOLDER_IMAGE_PATH) if PLACEHOLDER_IMAGE_PATH else "placeholder.png"
            thumbnail_url = f"./{placeholder_filename}" # Relative path for JS to resolve


        # Fallback placeholder if no thumbnail found
        if not thumbnail_url:
            # Construct the absolute path to the placeholder served by ComfyUI
            # Note: This assumes the placeholder is served relative to the extension's web directory
            # We need the URL path, not the file system path here.
            # Placeholder URL should be relative to the extension root served at /extensions/Civicomfy/
            # The JS already uses `./placeholder.png` which means `/extensions/Civicomfy/placeholder.png`
            # Python doesn't know the final URL, so we send a conventional relative path. The JS knows how to resolve it.
            # Let's send the filename and let JS handle the path if needed, OR send the known JS relative path.
             # Check if the constant PLACEHOLDER_IMAGE_PATH is defined and not empty
             placeholder_filename = os.path.basename(PLACEHOLDER_IMAGE_PATH) if PLACEHOLDER_IMAGE_PATH else "placeholder.png"
             # The JS knows `./placeholder.png` resolves correctly from its context.
             thumbnail_url = f"./{placeholder_filename}" # Relative path for JS

        # --- Return curated data ---
        return web.json_response({
            "success": True,
            "model_id": target_model_id,
            "version_id": target_version_id,
            "model_name": model_name,
            "version_name": version_info.get('name', 'Unknown Version'),
            "creator_username": creator_username,
            "model_type": model_type,
            "description_html": description_html, # Send raw HTML (frontend should handle display safely)
            "version_description_html": version_description_html,
            "stats": {
                "downloads": download_count,
                "likes": likes_count,
                "dislikes": dislikes_count,
                "buzz": buzz_count,
            },
            "file_info": {
                "name": file_name,
                "size_kb": file_size_kb,
                "format": file_format,
            },
            "thumbnail_url": thumbnail_url,
            # Optionally include basic version info like baseModel
            "base_model": version_info.get("baseModel", "N/A"),
            # You could add tags here too if desired: model_info.get('tags', [])
        })

    except web.HTTPError as http_err:
        # Consistent error handling (copied from route_download_model)
        print(f"[Server GetDetails] HTTP Error: {http_err.status} {http_err.reason}")
        body_detail = ""
        try:
            body_detail = await http_err.text() if hasattr(http_err, 'text') else http_err.body.decode('utf-8', errors='ignore') if http_err.body else ""
            if body_detail.startswith('{') and body_detail.endswith('}'): body_detail = json.loads(body_detail)
        except Exception: pass
        return web.json_response({"success": False, "error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        # Consistent error handling (copied from route_download_model)
        print("--- Unhandled Error in /civitai/get_model_details ---")
        traceback.print_exc()
        print("--- End Error ---")
        return web.json_response({"success": False, "error": "Internal Server Error", "details": f"An unexpected error occurred: {str(e)}", "status_code": 500}, status=500)

@prompt_server.routes.post("/civitai/download")
async def route_download_model(request):
    """API Endpoint to initiate a download."""
    api_key = None # Define outside try block
    model_info = None # Define here for broader scope
    version_info = None
    primary_file = None
    target_model_id = None
    target_version_id = None
    try:
        data = await _get_request_json(request)

        model_url_or_id = data.get("model_url_or_id")
        # 'model_type' defines the target directory category (e.g., 'lora', 'checkpoint')
        model_type_key = data.get("model_type", "checkpoint").lower() # Internal key for saving dir
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        custom_filename = data.get("custom_filename", "").strip()
        num_connections = int(data.get("num_connections", 4))
        force_redownload = bool(data.get("force_redownload", False))
        api_key = data.get("api_key", "") # Get API key from frontend settings

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # --- Input Parsing and Info Fetching ---
        print(f"[Server Download] Request: {model_url_or_id}, TypeKey: {model_type_key}, Version: {req_version_id}")
        # Instantiate API with the key from the request (frontend settings)
        api = CivitaiAPI(api_key or None) # Pass None if empty string
        parsed_model_id, parsed_version_id = parse_civitai_input(model_url_or_id)

        # Determine the target version ID (request param > URL param)
        target_version_id = None
        if req_version_id and str(req_version_id).isdigit(): # Check if actually a number
            try:
                target_version_id = int(req_version_id)
            except (ValueError, TypeError):
                 print(f"[Server Download] Warning: Invalid value provided for 'model_version_id': {req_version_id}. Ignoring.")
                 # Continue, will try to find latest if no version ID parsed from URL either
        elif parsed_version_id:
            target_version_id = parsed_version_id
        # else: target_version_id remains None, we'll need model_id to find latest

        target_model_id = parsed_model_id

        # --- Get Model/Version Info from Civitai ---
        # Store results in broader scope vars 'model_info' and 'version_info'
        if target_version_id:
            # Fetch version info directly using GET /model-versions/{id}
            print(f"[Server Download] Fetching info for Version ID: {target_version_id}")
            version_info_result = api.get_model_version_info(target_version_id)
            if version_info_result and "error" not in version_info_result:
                version_info = version_info_result # Assign to broader scope variable
                # Infer model_id from version info if we didn't have it
                if not target_model_id and version_info.get('modelId'):
                     target_model_id = version_info['modelId']
                     print(f"[Server Download] Inferred Model ID {target_model_id} from Version ID {target_version_id}")
                     # Fetch model info as well for completeness if we only had version ID initially
                     model_info_result = api.get_model_info(target_model_id)
                     if model_info_result and "error" not in model_info_result:
                         model_info = model_info_result
                     else:
                         print(f"[Server Download] Warning: Could not fetch model info ({target_model_id}) after inferring from version.")
                         model_info = {} # Use empty dict as placeholder
            else:
                # Handle API error or not found for version ID
                err_details = version_info_result.get('details') if isinstance(version_info_result, dict) else "Unknown API error"
                status_code = version_info_result.get('status_code', 500) if isinstance(version_info_result, dict) else 500
                raise web.HTTPNotFound(reason=f"Civitai API Error: Version {target_version_id} not found or API error. Details: {err_details}",
                                       body=json.dumps({"error": f"Version {target_version_id} not found or API error", "details": err_details}))

        elif target_model_id:
             # Fetch model info (GET /models/{id}) to get the latest version
            print(f"[Server Download] Fetching info for Model ID: {target_model_id} to find latest version.")
            model_info_result = api.get_model_info(target_model_id)
            if model_info_result and "error" not in model_info_result:
                model_info = model_info_result # Assign to broader scope variable
                versions = model_info.get("modelVersions")
                if versions and isinstance(versions, list) and len(versions) > 0:
                    # Find the *best* default version (often marked as 'default' or just the first 'Published')
                    default_version_in_list = next((v for v in versions if v.get('status') == 'Published'), versions[0])
                    if not default_version_in_list: # Should not happen if versions exist, but safety check
                         raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but has no published versions listed.")

                    partial_version_info = default_version_in_list # This is the partial version info dict from the list
                    target_version_id = partial_version_info.get('id')
                    if not target_version_id:
                         raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but latest version has no ID.")

                    print(f"[Server Download] Using latest/default Version ID {target_version_id} for Model ID {target_model_id}")
                    # Need to re-fetch full version details as model info often lacks file download URLs or full metadata
                    print(f"[Server Download] Fetching full details for selected Version ID: {target_version_id}")
                    full_version_info_result = api.get_model_version_info(target_version_id)
                    if full_version_info_result and "error" not in full_version_info_result:
                        version_info = full_version_info_result # Overwrite with full details
                    else:
                        # Log error but proceed with partial data if possible (will likely fail later if files missing)
                        err_details = full_version_info_result.get('details') if isinstance(full_version_info_result, dict) else "Unknown error getting full version"
                        print(f"[Server Download] Warning: Could not fetch full details for version {target_version_id}. Details: {err_details}. Download might fail if file info is missing.")
                        version_info = partial_version_info # Use the partial info from the model list

                else:
                    raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but has no usable model versions listed.")
            else:
                # Handle API error or not found for model ID
                err_details = model_info_result.get('details') if isinstance(model_info_result, dict) else "Unknown API error"
                status_code = model_info_result.get('status_code', 500) if isinstance(model_info_result, dict) else 500
                raise web.HTTPNotFound(reason=f"Civitai API Error: Model {target_model_id} not found or API error. Details: {err_details}",
                                       body=json.dumps({"error": f"Model {target_model_id} not found or API error", "details": err_details}))

        else:
             # Neither model ID nor version ID could be determined
            raise web.HTTPBadRequest(reason="Invalid input: Could not determine Model ID or Version ID from input.")

        # --- Sanity Checks After Fetching ---
        if not target_model_id:
             # This case implies we started with only a version ID and failed to infer the model ID
             raise web.HTTPInternalServerError(reason="Failed to determine the parent Model ID for the requested version.")
        if not target_version_id or not version_info:
             # This implies we started with a model ID but failed to find/fetch a valid version
             raise web.HTTPInternalServerError(reason="Failed to resolve valid model version information.")
        # Ensure model_info exists, even if empty (e.g., if started with only version_id and model fetch failed)
        if model_info is None: model_info = {}

        # --- Select File and Get Download URL ---
        files = version_info.get("files", [])
        if not isinstance(files, list):
             print(f"[Server Download] Error: 'files' field is not a list in version info for {target_version_id}: {files}")
             files = [] # Treat as empty if not a list

        # Check for fallback downloadUrl at version level (less common now)
        if not files and 'downloadUrl' in version_info and version_info['downloadUrl']:
            print("[Server Download] Warning: No 'files' array found, attempting to use version-level 'downloadUrl'. File details will be incomplete.")
            # Mock a file structure for consistency downstream
            files = [{
                "id": None, # No file ID available
                "name": version_info.get('name', f"version_{target_version_id}_file"), # Use version name as fallback
                "primary": True,
                "type": "Model", # Default type
                "sizeKB": version_info.get('fileSizeKB'), # Try to get size if available at version level
                "downloadUrl": version_info['downloadUrl'],
                "hashes": {}, # No hashes available
                "metadata": {} # No metadata available
            }]

        if not files:
             raise web.HTTPNotFound(reason=f"Version ID {target_version_id} ({version_info.get('name', 'N/A')}) has no files listed in API response.")

        # Find primary file or fallback (prefer safetensors with valid URL)
        primary_file = next((f for f in files if isinstance(f, dict) and f.get("primary") and f.get('downloadUrl')), None)

        if not primary_file:
            # Sort by type preference (safetensors > pickle), then maybe size?
            def sort_key(file_obj):
                if not isinstance(file_obj, dict): return 99
                if not file_obj.get('downloadUrl'): return 98 # Deprioritize files without URL

                name_lower = file_obj.get("name","").lower()
                meta = file_obj.get("metadata", {}) or {}
                format_type = meta.get("format","").lower()
                size_type = meta.get("size","").lower()
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
            sorted_files = sorted(valid_files, key=sort_key)
            primary_file = sorted_files[0] if sorted_files else None # Assign to broader scope var

        if not primary_file:
            raise web.HTTPNotFound(reason=f"Could not find any file with a valid download URL for version {target_version_id}.")

        # Ensure primary_file is a valid dictionary before accessing keys
        if not isinstance(primary_file, dict) or not primary_file.get('downloadUrl'):
            print(f"[Server Download] Error: Selected primary file data is invalid or missing URL: {primary_file}")
            raise web.HTTPInternalServerError(reason=f"Selected file data is invalid for version {target_version_id}.")

        print(f"[Server Download] Selected file: Name='{primary_file.get('name', 'N/A')}', Type='{primary_file.get('type', 'N/A')}', SizeKB={primary_file.get('sizeKB')}, Format={primary_file.get('metadata', {}).get('format')}, Size={primary_file.get('metadata', {}).get('size')}")

        file_id = primary_file.get("id") # May not be present, but useful for logging/metadata

        # *** Get the download URL directly from the file object ***
        download_url = primary_file.get("downloadUrl")
        print(f"[Server Download] Using Download URL: {download_url}")

        # --- Determine Filename and Output Path ---
        api_filename = primary_file.get("name", f"model_{target_model_id}_ver_{target_version_id}_file_{file_id or 'unknown'}")

        if custom_filename:
             # Sanitize custom filename carefully
             base, ext = os.path.splitext(custom_filename)
             sanitized_base = sanitize_filename(base, default_filename=f"model_{target_model_id}_custom")

             # Add original extension if custom name lacks one, or ensure it's valid
             if not ext:
                 _, api_ext = os.path.splitext(api_filename)
                 # Use API extension if available and seems valid, otherwise guess
                 valid_extensions = {'.safetensors', '.ckpt', '.pt', '.bin', '.pth', '.onnx', '.yaml', '.vae.pt', '.diffusers', '.json', '.txt', '.zip', '.csv', 'yaml'} # Added common text/archive types
                 if api_ext and api_ext.lower() in valid_extensions:
                      ext = api_ext
                 else:
                      # Best guess based on preferred formats
                      primary_file_meta = primary_file.get("metadata", {}) or {}
                      format_type = primary_file_meta.get("format","").lower()
                      if format_type == "safetensor": ext = ".safetensors"
                      elif format_type == "pickletensor": ext = ".ckpt"
                      else: ext = ".safetensors" # Default assumption
                      print(f"[Server Download] Warning: Custom filename lacked extension, defaulting to '{ext}' based on API info or guess.")
             elif ext.lower() not in valid_extensions:
                  print(f"[Server Download] Warning: Custom filename has unusual extension '{ext}'. Proceeding, but ensure it's correct.")

             final_filename = sanitized_base + ext
        else:
             # Sanitize the API filename too, just in case
             final_filename = sanitize_filename(api_filename)
             if final_filename != api_filename:
                 print(f"[Server Download] Sanitized API filename from '{api_filename}' to '{final_filename}'")

        # Get the target directory based on the user's selected 'model_type_key'
        output_dir = get_model_dir(model_type_key)
        output_path = os.path.join(output_dir, final_filename)

        # Construct corresponding metadata/preview paths
        base_name, _ = os.path.splitext(final_filename)
        meta_filename = base_name + METADATA_SUFFIX
        preview_filename = base_name + PREVIEW_SUFFIX
        meta_path = os.path.join(output_dir, meta_filename)
        preview_path = os.path.join(output_dir, preview_filename)

        # --- Check Existing File ---
        # Get size from API response for comparison
        api_size_kb = primary_file.get("sizeKB")
        api_size_bytes = int(api_size_kb * 1024) if api_size_kb and isinstance(api_size_kb, (int, float)) else 0

        file_exists = os.path.exists(output_path)
        metadata_exists = os.path.exists(meta_path)
        preview_exists = os.path.exists(preview_path)

        if file_exists and not force_redownload:
             local_size = os.path.getsize(output_path)
             # Relax size check slightly (e.g., within 1KB) OR if API size is unknown (0)
             size_matches = api_size_bytes > 0 and abs(api_size_bytes - local_size) <= 1024

             if size_matches:
                 print(f"[Server Download] File already exists and size matches: {output_path}")
                 # If primary file exists and matches size, check if metadata/preview are missing and offer to fetch *only* those?
                 # For now, just report exists. Enhancement: could add a button/option to "Fetch Metadata/Preview Only".
                 if not metadata_exists:
                     print(f"[Server Download] Info: Main file exists, but metadata file {meta_filename} is missing.")
                 if not preview_exists:
                      print(f"[Server Download] Info: Main file exists, but preview file {preview_filename} is missing.")

                 return web.json_response({
                     "status": "exists",
                     "message": "File already exists with matching size.",
                     "path": output_path,
                     "filename": final_filename,
                 })
             else:
                 # If sizes differ, report mismatch.
                 exist_reason = f"size differs (Local: {local_size} bytes, API: {api_size_bytes} bytes)" if api_size_bytes > 0 else "local file exists but API size was unknown"
                 print(f"[Server Download] File already exists but {exist_reason}. Path: {output_path}.")
                 # Return a distinct status code or message?
                 return web.json_response({
                     "status": "exists_size_mismatch",
                     "message": f"File already exists but {exist_reason}. Use 'Force Re-download' to overwrite.",
                     "path": output_path,
                     "filename": final_filename,
                     "local_size": local_size,
                     "api_size_kb": api_size_kb,
                 }, status=409) # Use 409 Conflict status

        # If force_redownload is true, log it
        if file_exists and force_redownload:
             print(f"[Server Download] Force Re-download enabled. Will overwrite existing file: {output_path}")

        # --- Prepare Download Info and Queue ---
        model_name = model_info.get('name', version_info['model']['name'])
        version_name = version_info.get('name', 'Unknown Version')

        # Extract a suitable thumbnail URL (ensure it's done robustly)
        thumbnail_url = None
        images = version_info.get("images")
        if images and isinstance(images, list) and len(images) > 0:
             # Ensure images are dictionaries with URLs
             valid_images = [img for img in images if isinstance(img, dict) and img.get("url")]
             # Sort by index if available, falling back to 0
             sorted_images = sorted(valid_images, key=lambda x: x.get('index', 0))
            # Try to find first image of type 'image' with explicit width (often better quality previews)
             img_data = next((img for img in sorted_images if img.get("type") == "image" and "/width=" in img["url"]), None)
             # Fallback 1: Any image of type 'image'
             if not img_data: img_data = next((img for img in sorted_images if img.get("type") == "image"), None)
             # Fallback 2: Any image at all
             if not img_data: img_data = next((img for img in sorted_images), None)

             if img_data and img_data.get("url"):
                   base_url = img_data["url"]
                   # Try to get a reasonably sized thumbnail version (e.g., width 256-450)
                   try:
                       # Basic heuristic: replace width param or append if not present/blob
                       if "/width=" in base_url:
                           thumbnail_url = re.sub(r"/width=\d+", "/width=256", base_url)
                       elif "/blob/" in base_url: # Handle blob URLs that might not have params
                           thumbnail_url = base_url
                       else:
                           separator = "&" if "?" in base_url else "?"
                           thumbnail_url = f"{base_url}{separator}width=256"
                       print(f"[Server Download] Generated thumbnail URL for UI: {thumbnail_url}")
                   except Exception as thumb_e:
                        print(f"[Server Download] Warning: Failed to generate specific thumbnail URL from {base_url}: {thumb_e}")
                        thumbnail_url = base_url # Fallback to original URL found
             else:
                  print(f"[Server Download] Warning: No image with a valid URL found for thumbnail in version {target_version_id}")

        # Ensure size is int or None
        known_size_bytes = api_size_bytes if api_size_bytes > 0 else None

        # --- Prepare full download_info dict ---
        # Pass all necessary info for download, metadata, and preview saving
        download_info = {
            # Core download params
            "url": download_url,
            "output_path": output_path,
            "num_connections": num_connections,
            "known_size": known_size_bytes,
            "api_key": api_key or None, # Pass API key for download auth if needed
            # UI Display Info
            "filename": final_filename,
            "model_name": model_name,
            "version_name": version_name,
            "thumbnail": thumbnail_url, # URL for UI thumbnail preview
            "model_type": model_type_key, # The category/directory key used for saving
            # Metadata for .cminfo.json and preview saving
            "civitai_model_id": target_model_id,
            "civitai_version_id": target_version_id,
            "civitai_file_id": file_id,
            # ---> Pass the full API response dicts <---
            "civitai_model_info": model_info,
            "civitai_version_info": version_info,
            "civitai_primary_file": primary_file, # Pass the selected file object
        }

        download_id = download_manager.add_to_queue(download_info)

        # Return queued status and essential details for the UI
        return web.json_response({
            "status": "queued",
            "message": f"Download added to queue: '{final_filename}'",
            "download_id": download_id,
            "details": {
                "filename": final_filename,
                "model_name": model_name,
                "version_name": version_name,
                "thumbnail": thumbnail_url,
                "path": output_path, # The intended final path
                "size_kb": api_size_kb if api_size_kb else None # Use KB for display consistency
            }
        })

    except web.HTTPError as http_err:
         # Re-raise known HTTP errors (like bad request, not found, conflict)
         print(f"[Server Download] HTTP Error: {http_err.status} {http_err.reason}")
         # Attempt to parse JSON body for details
         body_detail = ""
         try:
             # Use await text() for aiohttp Response exceptions
             body_detail = await http_err.text() if hasattr(http_err, 'text') else http_err.body.decode('utf-8', errors='ignore') if http_err.body else ""
             # Try parsing as JSON if text looks like it
             if body_detail.startswith('{') and body_detail.endswith('}'):
                  body_detail = json.loads(body_detail) # Return parsed dict
         except Exception: pass # Ignore parsing errors, just use the raw text
         # Return JSON response for frontend handling
         return web.json_response({"error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        print("--- Unhandled Error in /civitai/download ---")
        traceback.print_exc()
        print("--- End Error ---")
        # Return a generic 500 Internal Server Error for unexpected issues
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected error occurred: {str(e)}", "status_code": 500}, status=500)

# --- Other routes remain the same ---

@prompt_server.routes.get("/civitai/status")
async def route_get_status(request):
    """API Endpoint to get the status of downloads."""
    try:
        status = download_manager.get_status()
        return web.json_response(status)
    except Exception as e:
        print(f"Error getting download status: {e}")
        # Format error response consistently
        return web.json_response({"error": "Internal Server Error", "details": f"Failed to get status: {str(e)}", "status_code": 500}, status=500)

@prompt_server.routes.post("/civitai/cancel")
async def route_cancel_download(request):
    """API Endpoint to cancel a download."""
    try:
        data = await _get_request_json(request)
        download_id = data.get("download_id")
        if not download_id:
            print("not download id " + download_id)
            raise web.HTTPBadRequest(reason="Missing 'download_id'")

        success = download_manager.cancel_download(download_id)
        if success:
            return web.json_response({
                "status": "cancelled", # Or "cancellation_requested" ?
                "message": f"Cancellation requested for download ID: {download_id}.",
                "download_id": download_id
            })
        else:
            # Might be already completed/failed/cancelled and in history, or invalid ID
            raise web.HTTPNotFound(reason=f"Download ID {download_id} not found in active queue or running downloads.")

    except web.HTTPError as http_err:
         # Consistent error handling
         body_detail = ""
         try:
              body_detail = await http_err.text() if hasattr(http_err, 'text') else http_err.body.decode('utf-8', errors='ignore') if http_err.body else ""
              if body_detail.startswith('{') and body_detail.endswith('}'): body_detail = json.loads(body_detail)
         except Exception: pass
         return web.json_response({"error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        print(f"Error cancelling download: {e}")
        return web.json_response({"error": "Internal Server Error", "details": f"Failed to cancel download: {str(e)}", "status_code": 500}, status=500)

@prompt_server.routes.post("/civitai/search")
async def route_search_models(request):
    """API Endpoint for searching models using Civitai's Meilisearch."""
    api_key = None # Meili might not use the standard key
    try:
        data = await _get_request_json(request)

        query = data.get("query", "").strip()
        model_type_keys = data.get("model_types", []) # e.g., ["lora", "checkpoint"] (frontend internal keys)
        base_model_filters = data.get("base_models", []) # e.g., ["SD 1.5", "Pony"]
        sort = data.get("sort", "Most Downloaded") # Frontend display value
        # Make period optional or remove if not supported by Meili sort directly
        # period = data.get("period", "AllTime")
        limit = int(data.get("limit", 20))
        page = int(data.get("page", 1))
        api_key = data.get("api_key", "") # Keep for potential future use or different endpoints
        nsfw = data.get("nsfw", None) # Expect Boolean or None

        if not query and not model_type_keys and not base_model_filters:
             raise web.HTTPBadRequest(reason="Search requires a query or at least one filter (type or base model).")

        # Instantiate API - API key might not be needed for Meili public search
        api = CivitaiAPI(api_key or None)

        # --- Prepare Filters for Meili API call ---

        # 1. Map internal type keys to Civitai API 'type' names (used in Meili filter)
        # This assumes Meili filters on the uppercase names like "LORA", "Checkpoint"
        api_types_filter = []
        if isinstance(model_type_keys, list) and model_type_keys and "any" not in model_type_keys:
            for key in model_type_keys:
                # Map key.lower() for robustness - use the existing map from config
                # CIVITAI_API_TYPE_MAP maps internal key -> Civitai API type name (e.g. 'lora' -> 'LORA')
                api_type = CIVITAI_API_TYPE_MAP.get(key.lower())
                # Ensure we handle cases where the map might return None or duplicate types
                if api_type and api_type not in api_types_filter:
                    api_types_filter.append(api_type)

        # 2. Base Model Filters (assume frontend sends exact names like "SD 1.5")
        valid_base_models = []
        if isinstance(base_model_filters, list) and base_model_filters:
             # Optional: Validate against known list?
             valid_base_models = [bm for bm in base_model_filters if isinstance(bm, str) and bm]
             # Example validation (optional):
             # valid_base_models = [bm for bm in base_model_filters if bm in AVAILABLE_MEILI_BASE_MODELS]
             # if len(valid_base_models) != len(base_model_filters):
             #     print("Warning: Some provided base model filters were invalid.")

        # --- Call the New API Method ---
        print(f"[Server Search] Meili: query='{query if query else '<none>'}', types={api_types_filter or 'Any'}, baseModels={valid_base_models or 'Any'}, sort={sort}, nsfw={nsfw}, limit={limit}, page={page}")

        # Call the new search method
        meili_results = api.search_models_meili(
             query=query or None, # Meili handles empty query if filters exist
             types=api_types_filter or None,
             base_models=valid_base_models or None,
             sort=sort, # Pass the frontend value, mapping happens inside search_models_meili
             limit=limit,
             page=page,
             nsfw=nsfw
        )

        # Handle API error response from CivitaiAPI helper
        if meili_results and isinstance(meili_results, dict) and "error" in meili_results:
             status_code = meili_results.get("status_code", 500) or 500
             reason = f"Civitai API Meili Search Error: {meili_results.get('details', meili_results.get('error', 'Unknown error'))}"
             raise web.HTTPException(reason=reason, status=status_code, body=json.dumps(meili_results))

        # --- Process Meili Response for Frontend ---
        if meili_results and isinstance(meili_results, dict) and "hits" in meili_results:
              processed_items = []
              image_base_url = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7QA" # Base URL for images

              for hit in meili_results.get("hits", []):
                   if not isinstance(hit, dict): continue # Skip invalid hits

                   thumbnail_url = None
                   # Get thumbnail from images array (prefer first image)
                   images = hit.get("images")
                   if images and isinstance(images, list) and len(images) > 0:
                       first_image = images[0]
                       # Ensure first image is a dict with a 'url' field
                       if isinstance(first_image, dict) and first_image.get("url"):
                           image_id = first_image["url"]
                           # Construct URL with a default width (e.g., 256 or 450)
                           thumbnail_url = f"{image_base_url}/{image_id}/width=256" # Adjust width as needed

                   # Extract latest version info (Meili response includes 'version' object for the primary version)
                   latest_version_info = hit.get("version", {}) or {} # Ensure it's a dict

                   # Prepare item structure for frontend (can pass raw hit + extras, or build a specific structure)
                   # Let's pass the raw `hit` and add the `thumbnailUrl` and potentially other processed fields.
                   hit['thumbnailUrl'] = thumbnail_url # Add processed thumbnail URL directly to the hit object

                   # Optional: Add more processed fields if needed, e.g., formatted stats
                   # hit['processedStats'] = { ... }

                   processed_items.append(hit)

              # --- Calculate Pagination Info ---
              total_hits = meili_results.get("estimatedTotalHits", 0)
              current_page = page # Use the requested page number
              total_pages = math.ceil(total_hits / limit) if limit > 0 else 0

              # --- Return Structure for Frontend ---
              response_data = {
                  "items": processed_items, # The array of processed hits
                  "metadata": {
                      "totalItems": total_hits,
                      "currentPage": current_page,
                      "pageSize": limit, # The limit used for the request
                      "totalPages": total_pages,
                      # Meili provides offset, limit, processingTimeMs which could also be passed if useful
                      "meiliProcessingTimeMs": meili_results.get("processingTimeMs"),
                      "meiliOffset": meili_results.get("offset"),
                  }
              }
              return web.json_response(response_data)
        else:
             # Handle unexpected format from API or empty results
             print(f"[Server Search] Warning: Unexpected Meili search result format or empty hits: {meili_results}")
             return web.json_response({"items": [], "metadata": {"totalItems": 0, "currentPage": page, "pageSize": limit, "totalPages": 0}}, status=500)

    # --- Keep existing error handlers ---
    except web.HTTPError as http_err:
         # ... (keep existing HTTP error handling) ...
         body_detail = ""
         try:
              body_detail = await http_err.text() if hasattr(http_err, 'text') else http_err.body.decode('utf-8', errors='ignore') if http_err.body else ""
              if body_detail.startswith('{') and body_detail.endswith('}'): body_detail = json.loads(body_detail)
         except Exception: pass
         return web.json_response({"error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        # ... (keep existing generic error handling) ...
        print("--- Unhandled Error in /civitai/search ---")
        traceback.print_exc()
        print("--- End Error ---")
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected search error occurred: {str(e)}", "status_code": 500}, status=500)

# Also add the endpoint to get base models (if needed by frontend dropdown)
@prompt_server.routes.get("/civitai/base_models")
async def route_get_base_models(request):
    """API Endpoint to get the known base model types for filtering."""
    try:
        # Return the hardcoded list for now
        # In future, this *could* fetch dynamically if Civitai provides an endpoint
        return web.json_response({"base_models": AVAILABLE_MEILI_BASE_MODELS})
    except Exception as e:
        print(f"Error getting base model types: {e}")
        return web.json_response({"error": "Internal Server Error", "details": str(e), "status_code": 500}, status=500)

@prompt_server.routes.get("/civitai/model_types")
async def route_get_model_types(request):
    """API Endpoint to get the known model types and their mapping."""
    try:
        # Return a simpler map for the frontend: { internal_key: display_name }
        types_map = {key: data[0] for key, data in MODEL_TYPE_DIRS.items()}
        return web.json_response(types_map)
    except Exception as e:
        print(f"Error getting model types: {e}")
        return web.json_response({"error": "Internal Server Error", "details": str(e), "status_code": 500}, status=500)

print("[Civicomfy] Server routes registered.")

@prompt_server.routes.post("/civitai/retry")
async def route_retry_download(request):
    """API Endpoint to retry a failed/cancelled download."""
    if not download_manager:
        return web.json_response({"error": "Download Manager not initialized"}, status=500)

    try:
        data = await request.json()
        download_id = data.get("download_id")

        if not download_id:
            return web.json_response({"error": "Missing 'download_id'", "details": "The request body must contain the 'download_id' of the item to retry."}, status=400)

        print(f"[API Route /civitai/retry] Received retry request for ID: {download_id}")
        # Call manager method (which handles locking)
        result = await asyncio.to_thread(download_manager.retry_download, download_id) # Run sync manager method in thread

        status_code = 200 if result.get("success") else 404 if "not found" in result.get("error", "").lower() else 400
        return web.json_response(result, status=status_code)

    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    except Exception as e:
        import traceback
        print(f"Error handling /civitai/retry request for ID '{data.get('download_id', 'N/A')}': {e}")
        # traceback.print_exc() # Uncomment for detailed logs
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected error occurred: {str(e)}"}, status=500)

@prompt_server.routes.post("/civitai/open_path")
async def route_open_path(request):
    """API Endpoint to open the containing folder of a completed download."""
    if not download_manager:
        return web.json_response({"error": "Download Manager not initialized"}, status=500)

    try:
        data = await request.json()
        download_id = data.get("download_id")

        if not download_id:
            return web.json_response({"error": "Missing 'download_id'", "details": "The request body must contain the 'download_id' of the completed item."}, status=400)

        print(f"[API Route /civitai/open_path] Received open path request for ID: {download_id}")
        # Call manager method in thread
        result = await asyncio.to_thread(download_manager.open_containing_folder, download_id)

        status_code = 200 if result.get("success") else 404 if "not found" in result.get("error", "").lower() else 400 # Use 400 for OS error, security etc
        # Check for specific errors to return better codes
        if not result.get("success"):
             error_lower = result.get("error", "").lower()
             if "directory does not exist" in error_lower or "id not found" in error_lower:
                 status_code = 404
             elif "cannot open path" in error_lower or "unsupported os" in error_lower or "failed to open" in error_lower or "xdg-open" in error_lower:
                 status_code = 501 # Not Implemented / Failed on server side
             elif "must be 'completed'" in error_lower:
                  status_code = 409 # Conflict - wrong state
             else:
                 status_code = 400 # Bad Request / general failure

        # Prevent sensitive path info leakage in error messages by default
        if not result.get("success") and "error" in result and status_code != 200:
             print(f"[API Route /civitai/open_path] Error for ID {download_id}: {result['error']}") # Log full error on server
             # Optionally sanitize error sent to client
             # if "Directory:" in result["error"] or "Path:" in result["error"]:
             #    result["error"] = "Server failed to open the specified directory."

        return web.json_response(result, status=status_code)

    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    except Exception as e:
        import traceback
        print(f"Error handling /civitai/open_path request for ID '{data.get('download_id', 'N/A')}': {e}")
        # traceback.print_exc()
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected error occurred: {str(e)}"}, status=500)
    
@prompt_server.routes.post("/civitai/clear_history")
async def route_clear_history(request):
    """API Endpoint to clear the download history."""
    if not download_manager:
        return web.json_response({"error": "Download Manager not initialized"}, status=500)

    try:
        # No request body needed for this action
        print(f"[API Route /civitai/clear_history] Received clear history request.")

        # Call manager method in thread
        result = await asyncio.to_thread(download_manager.clear_history)

        status_code = 200 if result.get("success") else 500 # Use 500 for internal clear error
        return web.json_response(result, status=status_code)

    except Exception as e:
        import traceback
        print(f"Error handling /civitai/clear_history request: {e}")
        # traceback.print_exc() # Uncomment for detailed logs
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected error occurred: {str(e)}"}, status=500)