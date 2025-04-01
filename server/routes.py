# ================================================
# File: server/routes.py (Updated)
# ================================================
import server # ComfyUI server instance
import os
import traceback
import urllib.parse # Needed for thumbnail processing
import re # Moved import for thumbnail generation here
from aiohttp import web

# Import necessary components from our modules
from ..downloader.manager import manager as download_manager # Use the global instance
from ..api.civitai import CivitaiAPI
from ..utils.helpers import get_model_dir, parse_civitai_input, sanitize_filename
from ..config import MODEL_TYPE_DIRS, CIVITAI_API_TYPE_MAP

# Get the PromptServer instance
prompt_server = server.PromptServer.instance

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
    try:
        data = await _get_request_json(request)

        model_url_or_id = data.get("model_url_or_id")
        # 'model_type' defines the target directory category (e.g., 'lora', 'checkpoint')
        model_type = data.get("model_type", "checkpoint").lower()
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        custom_filename = data.get("custom_filename", "").strip()
        num_connections = int(data.get("num_connections", 4))
        force_redownload = bool(data.get("force_redownload", False))
        api_key = data.get("api_key", "") # Get API key from frontend settings

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # --- Input Parsing and Info Fetching ---
        print(f"Received download request: {model_url_or_id}, Type: {model_type}, Version: {req_version_id}")
        # Instantiate API with the key from the request (frontend settings)
        api = CivitaiAPI(api_key or None) # Pass None if empty string
        parsed_model_id, parsed_version_id = parse_civitai_input(model_url_or_id)

        # Determine the target version ID (request param > URL param)
        target_version_id = None
        if req_version_id and str(req_version_id).isdigit(): # Check if actually a number
            try:
                target_version_id = int(req_version_id)
            except (ValueError, TypeError):
                 print(f"Warning: Invalid value provided for 'model_version_id': {req_version_id}. Ignoring.")
                 # raise web.HTTPBadRequest(reason=f"Invalid 'model_version_id': {req_version_id}")
        elif parsed_version_id:
            target_version_id = parsed_version_id
        # else: target_version_id remains None, we'll need model_id to find latest

        target_model_id = parsed_model_id

        # --- Get Model/Version Info from Civitai ---
        model_info = None
        version_info = None

        if target_version_id:
            # Fetch version info directly using GET /model-versions/{id}
            print(f"Fetching info for Version ID: {target_version_id}")
            version_info_result = api.get_model_version_info(target_version_id)
            if version_info_result and "error" not in version_info_result:
                version_info = version_info_result
                # Infer model_id from version info if we didn't have it
                if not target_model_id and version_info.get('modelId'):
                     target_model_id = version_info['modelId']
                     print(f"Inferred Model ID {target_model_id} from Version ID {target_version_id}")
            else:
                err_details = version_info_result.get('details') if isinstance(version_info_result, dict) else "Unknown API error"
                status_code = version_info_result.get('status_code', 500) if isinstance(version_info_result, dict) else 500
                raise web.HTTPNotFound(reason=f"Civitai API Error: Version {target_version_id} not found or API error. Details: {err_details}",
                                       body=str({"error": f"Version {target_version_id} not found or API error", "details": err_details}))

        elif target_model_id:
             # Fetch model info (GET /models/{id}) to get the latest version
            print(f"Fetching info for Model ID: {target_model_id} to find latest version.")
            model_info_result = api.get_model_info(target_model_id)
            if model_info_result and "error" not in model_info_result:
                model_info = model_info_result
                versions = model_info.get("modelVersions")
                if versions and isinstance(versions, list) and len(versions) > 0:
                    # Assume first version in list is the latest/default
                    # Find the *best* default version (often marked as 'default' or just the first)
                    default_version_in_list = next((v for v in versions if v.get('status') == 'Published'), versions[0]) # Simplified: take first published
                    version_info = default_version_in_list # This is the partial version info dict
                    target_version_id = version_info.get('id')
                    if not target_version_id:
                         raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but latest version has no ID.")

                    print(f"Using latest/default Version ID {target_version_id} for Model ID {target_model_id}")
                    # Need to re-fetch full version details as model info often lacks file download URLs
                    print(f"Fetching full details for selected Version ID: {target_version_id}")
                    full_version_info_result = api.get_model_version_info(target_version_id)
                    if full_version_info_result and "error" not in full_version_info_result:
                        version_info = full_version_info_result # Overwrite with full details
                    else:
                        err_details = full_version_info_result.get('details') if isinstance(full_version_info_result, dict) else "Unknown API error getting full version"
                        print(f"Warning: Could not fetch full details for version {target_version_id}. Details: {err_details}. Download might fail.")
                        # Keep partial version_info from model listing, MUST check if 'files' exist below now

                else:
                    raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but has no usable model versions listed.")
            else:
                err_details = model_info_result.get('details') if isinstance(model_info_result, dict) else "Unknown API error"
                status_code = model_info_result.get('status_code', 500) if isinstance(model_info_result, dict) else 500
                raise web.HTTPNotFound(reason=f"Civitai API Error: Model {target_model_id} not found or API error. Details: {err_details}",
                                       body=str({"error": f"Model {target_model_id} not found or API error", "details": err_details}))

        else:
             # Neither model ID nor version ID could be determined
            raise web.HTTPBadRequest(reason="Invalid input: Could not determine Model ID or Version ID from input.")

        if not version_info or not target_version_id:
             # This check should be redundant now due to earlier checks, but keep as safety net
             raise web.HTTPInternalServerError(reason="Failed to resolve model version information.")

         # Ensure we have model_info if possible (needed for model name)
        if not model_info and target_model_id:
             print(f"(Re)Fetching model info for ID: {target_model_id}")
             model_info_result = api.get_model_info(target_model_id)
             if model_info_result and "error" not in model_info_result:
                  model_info = model_info_result
             else:
                 print(f"Warning: Failed to fetch model info for {target_model_id}. Model name might be unknown.")
                 model_info = {} # Assign empty dict to avoid None errors later

        # --- Select File and Get Download URL ---
        # CRITICAL: Ensure 'files' key exists and is a list, especially if using partial version info
        files = version_info.get("files", [])
        if not isinstance(files, list):
             print(f"Error: 'files' field is not a list in version info for {target_version_id}: {files}")
             files = [] # Treat as empty if not a list

        if not files:
             details = f"Version ID {target_version_id} ({version_info.get('name', 'N/A')}) has no files listed in API response."
             if 'downloadUrl' in version_info: # Check if maybe the downloadUrl is at the version level (less common now)
                  files = [{"downloadUrl": version_info['downloadUrl'], "name": version_info.get('name'), "primary": True, "type": "Model"}] # Mock a file structure
                  print("Warning: No 'files' array found, using version-level 'downloadUrl'. File details might be incomplete.")
             else:
                  raise web.HTTPNotFound(reason=details)

        # Find primary file or fallback (prefer safetensors)
        primary_file = next((f for f in files if f.get("primary") and f.get('downloadUrl')), None) # Must have downloadUrl
        if not primary_file:
            # Sort by type preference, then maybe size?
            def sort_key(file_obj):
                # Ensure file_obj is a dict and has needed keys
                if not isinstance(file_obj, dict): return 99
                # Ensure必备的 URL is present
                if not file_obj.get('downloadUrl'): return 98

                name_lower = file_obj.get("name","").lower()
                # Handle metadata format variations
                meta = file_obj.get("metadata", {}) or {} # Ensure meta is a dict
                format_type = meta.get("format","").lower() # e.g., "SafeTensor", "PickleTensor"
                size_type = meta.get("size","").lower() # e.g., "full", "pruned"
                # Fallback to file name extension
                is_safetensor = ".safetensors" in name_lower or format_type == "safetensor"
                is_pickle = ".ckpt" in name_lower or ".pt" in name_lower or format_type == "pickletensor"
                is_pruned = size_type == "pruned"

                # More robust sorting: Pruned ST > Full ST > Pruned Pickle > Full Pickle > Others
                if is_safetensor and is_pruned: return 0
                if is_safetensor: return 1 # Any other safetensor
                if is_pickle and is_pruned: return 2
                if is_pickle: return 3 # Any other pickle
                return 5 # Other types last

            # Filter files that DO have a downloadUrl before sorting
            valid_files = [f for f in files if isinstance(f, dict) and f.get("downloadUrl")]
            sorted_files = sorted(valid_files, key=sort_key)
            primary_file = sorted_files[0] if sorted_files else None

        if not primary_file:
            raise web.HTTPNotFound(reason=f"Could not find any file with a valid download URL for version {target_version_id}.")

        # Ensure primary_file is a dictionary before accessing keys
        if not isinstance(primary_file, dict):
            raise web.HTTPInternalServerError(reason=f"Selected file data is invalid for version {target_version_id}.")

        print(f"Selected file to download: Name='{primary_file.get('name', 'N/A')}', Type='{primary_file.get('type', 'N/A')}', SizeKB={primary_file.get('sizeKB')}, Format={primary_file.get('metadata', {}).get('format')}, Size={primary_file.get('metadata', {}).get('size')}")

        file_id = primary_file.get("id") # May not be present, but useful for logging

        # *** Get the download URL directly from the file object ***
        download_url = primary_file.get("downloadUrl")
        if not download_url:
            print(f"Error: Selected file object missing 'downloadUrl': {primary_file}")
            raise web.HTTPInternalServerError(reason="Selected file is missing the download URL in Civitai API response.")

        print(f"Obtained Download URL: {download_url}") # Log the URL we are sending to the downloader

        # --- Determine Filename and Output Path ---
        # Prefer name from 'metadata' if available and more descriptive? Needs careful check.
        api_filename = primary_file.get("name", f"model_{target_model_id}_ver_{target_version_id}_file_{file_id or 'unknown'}")

        if custom_filename:
             # Sanitize custom filename
             base, ext = os.path.splitext(custom_filename)
             sanitized_base = sanitize_filename(base, default_filename="custom_model")
             # Add original extension if custom name lacks one
             if not ext:
                 _, api_ext = os.path.splitext(api_filename)
                 # Use API extension if available, check for common model types
                 valid_extensions = {'.safetensors', '.ckpt', '.pt', '.bin', '.pth', '.onnx', '.yaml', '.vae.pt', '.diffusers'} # Add more as needed
                 if api_ext.lower() in valid_extensions:
                      ext = api_ext
                 else:
                      # Best guess based on preferred formats?
                      meta = primary_file.get("metadata", {}) or {}
                      format_type = meta.get("format","").lower()
                      if format_type == "safetensor":
                           ext = ".safetensors"
                      elif format_type == "pickletensor":
                           ext = ".ckpt"
                      else: # Default assumption if no clues
                          ext = ".safetensors"
                          print(f"Warning: No recognized extension found for '{api_filename}' or custom name. Defaulting to {ext}")
             final_filename = sanitized_base + ext
        else:
             # Sanitize the API filename too, just in case
             final_filename = sanitize_filename(api_filename)
             if final_filename != api_filename:
                 print(f"Sanitized API filename from '{api_filename}' to '{final_filename}'")

        output_dir = get_model_dir(model_type) # Uses user-specified type for directory
        output_path = os.path.join(output_dir, final_filename)

        # --- Check Existing File ---
        # Get size from API response for comparison
        api_size_kb = primary_file.get("sizeKB")
        api_size_bytes = int(api_size_kb * 1024) if api_size_kb else 0

        if os.path.exists(output_path) and not force_redownload:
             local_size = os.path.getsize(output_path)
             # Relax size check slightly (e.g., within 1KB) OR if API size is unknown (0)
             size_matches = api_size_bytes > 0 and abs(api_size_bytes - local_size) <= 1024

             if size_matches:
                 print(f"File already exists and size matches: {output_path}")
                 return web.json_response({
                     "status": "exists",
                     "message": "File already exists with matching size.",
                     "path": output_path,
                     "filename": final_filename,
                 })
             else:
                 # If API size is unknown, we can't be sure. Report mismatch but maybe allow override more easily?
                 # If sizes differ, report mismatch.
                 exist_reason = "size differs" if api_size_bytes > 0 else "local file exists but API size was unknown"
                 print(f"File already exists but {exist_reason}. Path: {output_path}. Local: {local_size} bytes, API: {api_size_bytes} bytes")
                 # Return a distinct status code or message?
                 return web.json_response({
                     "status": "exists_size_mismatch",
                     "message": f"File already exists but {exist_reason}.",
                     "path": output_path,
                     "filename": final_filename,
                     "local_size": local_size,
                     "api_size_kb": api_size_kb,
                 })

        # --- Prepare Download Info and Queue ---
        model_name = model_info.get('name', 'Unknown Model')
        version_name = version_info.get('name', 'Unknown Version')

        # Extract a suitable thumbnail URL
        thumbnail_url = None
        images = version_info.get("images")
        if images and isinstance(images, list) and len(images) > 0:
             # Find first image with a URL, prefer type 'image'
             sorted_images = sorted([img for img in images if img.get("url")], key=lambda x: x.get('index', 0))
             img_data = next((img for img in sorted_images if img.get("type") == "image"), None)
             if not img_data: img_data = next((img for img in sorted_images), None) # Fallback to any image

             if img_data and isinstance(img_data, dict) and img_data.get("url"):
                   base_url = img_data["url"]
                   # Try to get a reasonably sized thumbnail version (e.g., width 256)
                   try:
                       # Basic heuristic: replace width param or append if not present
                       if "/width=" in base_url:
                           thumbnail_url = re.sub(r"/width=\d+", "/width=256", base_url)
                       elif "/blob/" in base_url: # Handle blob URLs that might not have params
                           thumbnail_url = base_url
                       else:
                           separator = "&" if "?" in base_url else "?"
                           thumbnail_url = f"{base_url}{separator}width=256"
                       # Optional: Validate the generated URL? Ping it? Too complex for now.
                   except Exception as thumb_e:
                        print(f"Warning: Failed to generate thumbnail URL from {base_url}: {thumb_e}")
                        thumbnail_url = base_url # Fallback to original
             else:
                  print(f"Warning: No suitable image data found for thumbnail in version {target_version_id}")

        # Ensure size is int or None
        known_size_bytes = api_size_bytes if api_size_bytes > 0 else None

        download_info = {
            "url": download_url,
            "output_path": output_path,
            "model_name": model_name,
            "version_name": version_name,
            "filename": final_filename,
            "model_type": model_type, # The category/directory type used for saving
            "civitai_model_id": target_model_id,
            "civitai_version_id": target_version_id,
            "civitai_file_id": file_id,
            # ---> Pass the size in bytes <---
            "known_size": known_size_bytes,
            "num_connections": num_connections,
            "thumbnail": thumbnail_url, # URL for thumbnail preview
            "api_key": api_key or None
        }

        download_id = download_manager.add_to_queue(download_info)

        return web.json_response({
            "status": "queued",
            "message": f"Download added to queue: '{final_filename}'",
            "download_id": download_id,
            "details": { # Return some details for the UI to display immediately
                "filename": final_filename,
                "model_name": model_name,
                "version_name": version_name,
                "thumbnail": thumbnail_url,
                "path": output_path, # The intended final path
                "size_kb": api_size_kb # Use KB for display consistency
            }
        })

    except web.HTTPError as http_err:
         # Re-raise known HTTP errors (like bad request, not found)
         print(f"HTTP Error in /civitai/download: {http_err.status} {http_err.reason}")
         # Attempt to parse JSON body for details
         body_detail = ""
         try: body_detail = await http_err.text() # Read body if available
         except Exception: pass
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
                "status": "cancelled",
                "message": f"Cancellation requested for download ID: {download_id}.",
                "download_id": download_id
            })
        else:
            # Might be already completed/failed/cancelled and in history, or invalid ID
             # Check history? For now, just return not found if not in queue/active
             raise web.HTTPNotFound(reason=f"Download ID {download_id} not found in active queue or running downloads.")

    except web.HTTPError as http_err:
         body_detail = ""
         try: body_detail = await http_err.text()
         except Exception: pass
         return web.json_response({"error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        print(f"Error cancelling download: {e}")
        return web.json_response({"error": "Internal Server Error", "details": f"Failed to cancel download: {str(e)}", "status_code": 500}, status=500)

@prompt_server.routes.post("/civitai/search")
async def route_search_models(request):
    """API Endpoint for searching models on Civitai."""
    api_key = None
    try:
        data = await _get_request_json(request)

        query = data.get("query", "").strip()
        model_types_keys = data.get("model_types", []) # e.g., ["lora", "checkpoint"]
        sort = data.get("sort", "Highest Rated")
        period = data.get("period", "AllTime")
        limit = int(data.get("limit", 20))
        page = int(data.get("page", 1))
        api_key = data.get("api_key", "")
        nsfw = data.get("nsfw", None) # Expect Boolean or None

        if not query and not model_types_keys: # Allow browsing by type without query
             raise web.HTTPBadRequest(reason="Search requires a query or model type selection.")

        api = CivitaiAPI(api_key or None)

        # Map internal type keys to Civitai API 'types' values
        api_types_filter = []
        if isinstance(model_types_keys, list) and model_types_keys and "any" not in model_types_keys:
            for key in model_types_keys:
                 api_type = CIVITAI_API_TYPE_MAP.get(key.lower())
                 if api_type and api_type not in api_types_filter:
                      api_types_filter.append(api_type)

        print(f"Searching Civitai: query='{query}', types={api_types_filter or 'Any'}, sort={sort}, period={period}, nsfw={nsfw}, limit={limit}, page={page}")
        results = api.search_models(
             query,
             types=api_types_filter or None,
             sort=sort,
             period=period,
             limit=limit,
             page=page,
             nsfw=nsfw
        )

        if results and "error" in results:
             status_code = results.get("status_code", 500)
             reason = f"Civitai API Search Error: {results.get('details', results.get('error', 'Unknown error'))}"
             # Use generic HTTPException to pass status and body
             raise web.HTTPException(reason=reason, status=status_code, body=str(results))

        if results and "items" in results:
              # Process results to add convenience fields like thumbnailUrl
             for item in results.get("items", []):
                 thumbnail = None
                 # Use modelVersions -> images -> url as primary source
                 if item.get("modelVersions"):
                     latest_version = item["modelVersions"][0] # Assume first is latest preview
                     images = latest_version.get("images")
                     if images and isinstance(images, list) and len(images) > 0:
                         sorted_images = sorted([img for img in images if img and img.get("url")], key=lambda x: x.get('index', 0)) # Add check for img being non-null
                         img_data = next((img for img in sorted_images if img.get("type") == "image"), None)
                         if not img_data: img_data = next((img for img in sorted_images), None)

                         if img_data and isinstance(img_data, dict) and img_data.get("url"):
                             base_url = img_data["url"]
                             # Try to create a thumbnail URL (e.g., width 256)
                             try:
                                 if "/width=" in base_url:
                                      thumbnail = re.sub(r"/width=\d+", "/width=256", base_url)
                                 elif "/blob/" in base_url:
                                      thumbnail = base_url
                                 else:
                                      separator = "&" if "?" in base_url else "?"
                                      thumbnail = f"{base_url}{separator}width=256"
                             except Exception as e:
                                 print(f"Warning: Thumbnail generation failed for {base_url}: {e}")
                                 thumbnail = base_url # Fallback
                 item["thumbnailUrl"] = thumbnail # Add to the item dict

             return web.json_response(results)
        else:
             print(f"Warning: Unexpected search result format: {results}")
             return web.json_response({"items": [], "metadata": {}}, status=500)

    except web.HTTPError as http_err:
         body_detail = ""
         try: body_detail = await http_err.text()
         except Exception: pass
         return web.json_response({"error": http_err.reason, "details": body_detail or "No details", "status_code": http_err.status}, status=http_err.status)

    except Exception as e:
        print("--- Unhandled Error in /civitai/search ---")
        traceback.print_exc()
        print("--- End Error ---")
        return web.json_response({"error": "Internal Server Error", "details": f"An unexpected search error occurred: {str(e)}", "status_code": 500}, status=500)

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