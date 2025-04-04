# ================================================
# File: server/routes.py
# ================================================
# ================================================
# File: server/routes.py (Updated)
# This file needs to pass more info (model_info, version_info, primary_file)
# to the DownloadManager.
# ================================================
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