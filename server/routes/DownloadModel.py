# ================================================
# File: server/routes/DownloadModel.py
# ================================================
import os
import json
import traceback
import re
from aiohttp import web

import server # ComfyUI server instance
from ..utils import get_request_json
from ...downloader.manager import manager as download_manager
from ...api.civitai import CivitaiAPI
from ...utils.helpers import get_model_dir, parse_civitai_input, sanitize_filename, select_primary_file
from ...config import METADATA_SUFFIX, PREVIEW_SUFFIX

prompt_server = server.PromptServer.instance

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
        data = await get_request_json(request)

        model_url_or_id = data.get("model_url_or_id")
        # 'model_type' defines the target directory category (e.g., 'lora', 'checkpoint')
        model_type_value = data.get("model_type", "checkpoint")  # Use as-is; may be a literal folder name
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        explicit_save_root = (data.get("save_root") or "").strip()
        custom_filename_input = data.get("custom_filename", "").strip()
        selected_subdir = (data.get("subdir") or "").strip()
        # Optional file selection overrides
        req_file_id = data.get("file_id")
        req_file_name_contains = data.get("file_name_contains", "").strip()
        num_connections = int(data.get("num_connections", 4))
        force_redownload = bool(data.get("force_redownload", False))
        api_key = data.get("api_key", "") # Get API key from frontend settings

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # --- Input Parsing and Info Fetching ---
        print(f"[Server Download] Request: {model_url_or_id}, SaveType: {model_type_value}, Version: {req_version_id}")
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

        # If a specific file was requested by ID, honor it first
        primary_file = None
        if req_file_id is not None:
            try:
                # IDs in API are ints; accept stringified ints too
                req_file_id_int = int(str(req_file_id).strip())
                primary_file = next((f for f in files if isinstance(f, dict) and f.get("id") == req_file_id_int and f.get('downloadUrl')), None)
                if not primary_file:
                    raise web.HTTPNotFound(reason=f"File with id {req_file_id_int} not found or not downloadable in version {target_version_id}.")
            except ValueError:
                raise web.HTTPBadRequest(reason=f"Invalid 'file_id' value: {req_file_id}")

        # If not selected by ID, try selecting by partial name match (e.g., 'fp16', 'fp8')
        if primary_file is None and req_file_name_contains:
            needle = req_file_name_contains.lower()
            def name_matches(f):
                if not isinstance(f, dict):
                    return False
                name = (f.get("name") or "").lower()
                meta = (f.get("metadata") or {})
                fmt = (meta.get("format") or "").lower()
                size_tag = (meta.get("size") or "").lower()
                return (needle in name) or (needle in fmt) or (needle in size_tag)
            candidates = [f for f in files if f.get('downloadUrl') and name_matches(f)]
            primary_file = candidates[0] if candidates else None

        # If still not selected, fall back to heuristic helper
        if primary_file is None:
            primary_file = select_primary_file(files)

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

        # Defaults
        final_filename = sanitize_filename(api_filename)
        sub_path = ""

        # Subdir: only use the selected existing subdir coming from UI
        if selected_subdir:
            norm_sub = os.path.normpath(selected_subdir.replace('\\', '/'))
            parts = [p for p in norm_sub.split('/') if p and p not in ('.', '..')]
            if parts:
                sub_path = os.path.join(*[sanitize_filename(p) for p in parts])

        # Filename: ignore any path separators in custom name; treat as base name only
        if custom_filename_input:
            safe_name = sanitize_filename(custom_filename_input)
            base, ext = os.path.splitext(safe_name)
            if not ext:
                _, api_ext = os.path.splitext(api_filename)
                ext = api_ext or ".safetensors"
            final_filename = base + ext

        # Get the target base directory for the selected model type, allow explicit root
        if explicit_save_root:
            # Validate the explicit root belongs to known roots for this type (ComfyUI or plugin)
            try:
                from ..routes.GetModelDirs import _get_all_roots_for_type
                known_roots = _get_all_roots_for_type(model_type_value)
                if os.path.abspath(explicit_save_root) in [os.path.abspath(p) for p in known_roots]:
                    base_output_dir = explicit_save_root
                else:
                    print(f"[Server Download] Warning: Provided save_root not in known roots for type '{model_type_value}': {explicit_save_root}")
                    base_output_dir = get_model_dir(model_type_value)
            except Exception as e:
                print(f"[Server Download] Warning: Failed validating explicit save_root: {e}")
                base_output_dir = get_model_dir(model_type_value)
        else:
            base_output_dir = get_model_dir(model_type_value)
        output_dir = os.path.join(base_output_dir, sub_path) if sub_path else base_output_dir
        # Ensure directory exists (including subdirectories)
        try:
            os.makedirs(output_dir, exist_ok=True)
            print(f"[Server Download] Ensured output directory exists: {output_dir}")
        except OSError as e:
            raise web.HTTPInternalServerError(reason=f"Could not create subdirectory: {e}")
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

        # Extract a suitable thumbnail URL (ensure it's done robustly) and nsfw level for it
        thumbnail_url = None
        thumbnail_nsfw_level = None
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
                   try:
                       lvl = img_data.get("nsfwLevel")
                       thumbnail_nsfw_level = int(lvl) if lvl is not None else None
                   except Exception:
                       thumbnail_nsfw_level = None
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
        # Derive extra display attributes for UI/history
        def _guess_precision_name(fobj):
            try:
                nm = (fobj.get('name') or '').lower()
                meta = (fobj.get('metadata') or {})
                for key in ('precision', 'dtype', 'fp'):
                    val = (meta.get(key) or '').lower()
                    if val:
                        return val
                if 'fp8' in nm or 'int8' in nm or '8bit' in nm or '8-bit' in nm:
                    return 'fp8'
                if 'fp16' in nm or 'bf16' in nm or '16bit' in nm or '16-bit' in nm:
                    return 'fp16'
                if 'fp32' in nm or '32bit' in nm or '32-bit' in nm:
                    return 'fp32'
            except Exception:
                pass
            return None

        primary_meta = (primary_file.get('metadata') or {})
        ui_file_precision = _guess_precision_name(primary_file)
        ui_file_model_size = primary_meta.get('size')  # e.g., Pruned/Full
        ui_file_format = primary_meta.get('format')
        # Pass all necessary info for download, metadata, and preview saving
        download_info = {
            # Core download params
            "url": download_url,
            "output_path": output_path,
            "num_connections": num_connections,
            "known_size": known_size_bytes,
            "api_key": api_key or None, # Pass API key for download auth if needed
            # Retry/context fields
            "model_url_or_id": model_url_or_id,
            "model_version_id": req_version_id,
            "custom_filename": custom_filename_input,
            "force_redownload": force_redownload,
            # UI Display Info
            "filename": final_filename,
            "model_name": model_name,
            "version_name": version_name,
            "thumbnail": thumbnail_url, # URL for UI thumbnail preview
            "thumbnail_nsfw_level": thumbnail_nsfw_level,
            "model_type": model_type_value, # The category/directory key or literal folder used for saving
            # Extra file attributes for UI lists
            "file_precision": ui_file_precision,
            "file_model_size": ui_file_model_size,
            "file_format": ui_file_format,
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
                "thumbnail_nsfw_level": thumbnail_nsfw_level,
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
             # Try parsing as JSON if it looks like it
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
