# ComfyUI_Civitai_Downloader/server/routes.py
import server # ComfyUI server instance
import os
import traceback
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
    try:
        data = await _get_request_json(request)

        model_url_or_id = data.get("model_url_or_id")
        # 'model_type' defines the target directory category (e.g., 'lora', 'checkpoint')
        model_type = data.get("model_type", "checkpoint").lower()
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        custom_filename = data.get("custom_filename", "").strip()
        num_connections = int(data.get("num_connections", 4))
        force_redownload = bool(data.get("force_redownload", False))
        api_key = data.get("api_key", "") # TODO: Load preferred API key from a config file?

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # --- Input Parsing and Info Fetching ---
        print(f"Received download request: {model_url_or_id}, Type: {model_type}, Version: {req_version_id}")
        api = CivitaiAPI(api_key)
        parsed_model_id, parsed_version_id = parse_civitai_input(model_url_or_id)

        # Determine the target version ID (request param > URL param)
        target_version_id = None
        if req_version_id:
            try:
                target_version_id = int(req_version_id)
            except ValueError:
                 raise web.HTTPBadRequest(reason=f"Invalid 'model_version_id': {req_version_id}")
        elif parsed_version_id:
            target_version_id = parsed_version_id
        # else: target_version_id remains None, we'll need model_id to find latest

        target_model_id = parsed_model_id

        # --- Get Model/Version Info from Civitai ---
        model_info = None
        version_info = None

        if target_version_id:
            # Fetch version info directly
            print(f"Fetching info for explicitly provided/parsed Version ID: {target_version_id}")
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
             # Fetch model info to get the latest version
            print(f"Fetching info for Model ID: {target_model_id} to find latest version.")
            model_info_result = api.get_model_info(target_model_id)
            if model_info_result and "error" not in model_info_result:
                model_info = model_info_result
                versions = model_info.get("modelVersions")
                if versions and isinstance(versions, list) and len(versions) > 0:
                    # Assume first version in list is the latest/default
                    version_info = versions[0]
                    target_version_id = version_info.get('id')
                    print(f"Using latest Version ID {target_version_id} for Model ID {target_model_id}")
                else:
                    raise web.HTTPNotFound(reason=f"Model {target_model_id} found, but has no downloadable versions.")
            else:
                err_details = model_info_result.get('details') if isinstance(model_info_result, dict) else "Unknown API error"
                status_code = model_info_result.get('status_code', 500) if isinstance(model_info_result, dict) else 500
                raise web.HTTPNotFound(reason=f"Civitai API Error: Model {target_model_id} not found or API error. Details: {err_details}",
                                       body=str({"error": f"Model {target_model_id} not found or API error", "details": err_details}))

        else:
             # Neither model ID nor version ID could be determined
            raise web.HTTPBadRequest(reason="Invalid input: Could not determine Model ID or Version ID from input.")

        if not version_info or not target_version_id:
             raise web.HTTPInternalServerError(reason="Failed to resolve model version information.") # Should not happen

         # Get full model info if we only fetched version info initially
        if not model_info and target_model_id:
             model_info_result = api.get_model_info(target_model_id)
             if model_info_result and "error" not in model_info_result:
                  model_info = model_info_result
             # else: model_info might remain None, handle cases below

        # --- Select File and Get Download URL ---
        files = version_info.get("files", [])
        if not files:
             raise web.HTTPNotFound(reason=f"No files found for version ID {target_version_id}.")

        # Find primary file or fallback (prefer safetensors)
        primary_file = next((f for f in files if f.get("primary")), None)
        if not primary_file:
            safetensor_file = next((f for f in files if f.get("name", "").lower().endswith(".safetensors")), None)
            primary_file = safetensor_file if safetensor_file else files[0]
        print(f"Selected file to download: {primary_file.get('name', 'N/A')}")

        file_id = primary_file.get("id")
        file_type_for_url = primary_file.get("type") # API param 'type' e.g. 'Model'

        # Get the actual download URL (handles redirects)
        download_url = api.get_download_url(target_version_id, file_id=file_id, file_type=file_type_for_url)
        if not download_url:
            raise web.HTTPInternalServerError(reason="Failed to retrieve download URL from Civitai API.")

        # --- Determine Filename and Output Path ---
        api_filename = primary_file.get("name", f"model_{target_model_id}_ver_{target_version_id}")

        if custom_filename:
             # Sanitize custom filename
             base, ext = os.path.splitext(custom_filename)
             sanitized_base = sanitize_filename(base, default_filename="custom_model")
              # Add original extension if custom name lacks one
             if not ext:
                 _, api_ext = os.path.splitext(api_filename)
                 if api_ext:
                      ext = api_ext
                 else:
                      # Best guess if API also has no extension? Risky. Log warning.
                      ext = ".safetensors" # Default assumption
                      print(f"Warning: Neither custom filename nor API filename had an extension. Defaulting to {ext}")
             final_filename = sanitized_base + ext
        else:
             # Sanitize the API filename too, just in case
             final_filename = sanitize_filename(api_filename)
             if final_filename != api_filename:
                 print(f"Sanitized API filename from '{api_filename}' to '{final_filename}'")

        output_dir = get_model_dir(model_type) # Uses user-specified type for directory
        output_path = os.path.join(output_dir, final_filename)

        # Check existence before queuing
        if os.path.exists(output_path) and not force_redownload:
            # Check size if possible?
            api_size_bytes = int(primary_file.get("sizeKB", 0) * 1024)
            local_size = os.path.getsize(output_path)
            if api_size_bytes > 0 and api_size_bytes == local_size:
                 print(f"File already exists and size matches: {output_path}")
                 return web.json_response({
                     "status": "exists",
                     "message": "File already exists with matching size.",
                     "path": output_path,
                     "filename": final_filename,
                 })
            else:
                 print(f"File already exists but size differs or API size unknown. Path: {output_path}. Local: {local_size}, API: {api_size_bytes}")
                 # Still return exists, but maybe UI can show the size difference?
                 return web.json_response({
                     "status": "exists_size_mismatch",
                     "message": "File already exists but size differs or API size is unavailable.",
                     "path": output_path,
                     "filename": final_filename,
                     "local_size": local_size,
                     "api_size_kb": primary_file.get("sizeKB"), # Send original KB value
                 })

        # --- Prepare Download Info and Queue ---
        model_name = model_info.get('name') if model_info else 'Unknown Model'
        version_name = version_info.get('name', 'Unknown Version')

        # Extract a suitable thumbnail URL
        thumbnail_url = None
        images = version_info.get("images")
        if images and isinstance(images, list) and len(images) > 0:
             # Find first image with a URL, prefer type 'image'
             img_data = next((img for img in images if img.get("url") and img.get("type") == "image"), None)
             if not img_data: # Fallback to any image url
                  img_data = next((img for img in images if img.get("url")), None)
             if img_data:
                   # Try to get a reasonably sized thumbnail version
                   # Common Civitai pattern: replace width parameter
                   base_url = img_data["url"]
                   if img_data.get("width") and img_data.get("width") > 200:
                       try:
                           parsed_thumb = urllib.parse.urlparse(base_url)
                           qs = urllib.parse.parse_qs(parsed_thumb.query)
                           qs['width'] = ['200'] # Modify width
                           qs['height'] = ['auto'] # Adjust height maybe? or keep auto
                           new_query = urllib.parse.urlencode(qs, doseq=True)
                           thumbnail_url = urllib.parse.urlunparse(parsed_thumb._replace(query=new_query))
                       except Exception:
                            thumbnail_url = base_url # Fallback to original if parsing fails
                   else:
                        thumbnail_url = base_url # Use original if already small

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
            "file_size": int(primary_file.get("sizeKB", 0) * 1024), # Size in bytes
            "num_connections": num_connections,
            "thumbnail": thumbnail_url # URL for thumbnail preview
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
                "size_kb": primary_file.get("sizeKB")
            }
        })

    except web.HTTPError as http_err:
         # Re-raise known HTTP errors (like bad request, not found)
         print(f"HTTP Error in /civitai/download: {http_err.status} {http_err.reason}")
         raise http_err
    except Exception as e:
        print("--- Unhandled Error in /civitai/download ---")
        traceback.print_exc()
        print("--- End Error ---")
        # Return a generic 500 Internal Server Error for unexpected issues
        raise web.HTTPInternalServerError(reason=f"An unexpected error occurred: {str(e)}")

@prompt_server.routes.get("/civitai/status")
async def route_get_status(request):
    """API Endpoint to get the status of downloads."""
    try:
        status = download_manager.get_status()
        # Ensure status is JSON serializable (manager should handle this)
        return web.json_response(status)
    except Exception as e:
        print(f"Error getting download status: {e}")
        raise web.HTTPInternalServerError(reason=f"Failed to get status: {str(e)}")

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
            raise web.HTTPNotFound(reason=f"Download {download_id} not found in active queue or running downloads.")

    except web.HTTPError as http_err:
         raise http_err
    except Exception as e:
        print(f"Error cancelling download: {e}")
        raise web.HTTPInternalServerError(reason=f"Failed to cancel download: {str(e)}")

@prompt_server.routes.post("/civitai/search")
async def route_search_models(request):
    """API Endpoint for searching models on Civitai."""
    try:
        data = await _get_request_json(request)

        query = data.get("query", "").strip()
        # Expecting internal keys (lowercase) from frontend
        model_types_keys = data.get("model_types", []) # e.g., ["lora", "checkpoint"]
        sort = data.get("sort", "Highest Rated")
        period = data.get("period", "AllTime")
        limit = int(data.get("limit", 20))
        page = int(data.get("page", 1))
        api_key = data.get("api_key", "") # TODO: Use configured key?

        if not query:
            raise web.HTTPBadRequest(reason="Missing 'query' parameter")

        api = CivitaiAPI(api_key)

        # Map internal type keys to Civitai API 'types' values
        api_types_filter = []
        if isinstance(model_types_keys, list) and model_types_keys and "any" not in model_types_keys:
            for key in model_types_keys:
                 api_type = CIVITAI_API_TYPE_MAP.get(key.lower())
                 if api_type and api_type not in api_types_filter: # Avoid duplicates
                      api_types_filter.append(api_type)
        # If empty list or contains "any", don't pass 'types' param to API (search all)

        print(f"Searching Civitai: query='{query}', types={api_types_filter or 'Any'}, limit={limit}, page={page}")
        results = api.search_models(query, types=api_types_filter or None, sort=sort, period=period, limit=limit, page=page)

        if results and "error" in results:
             # Forward API error response
             status_code = results.get("status_code", 500)
             reason = f"Civitai API Search Error: {results.get('details', results.get('error'))}"
             # Use appropriate HTTP status code from API response if available
             if status_code == 400: raise web.HTTPBadRequest(reason=reason, body=str(results))
             if status_code == 401: raise web.HTTPUnauthorized(reason=reason, body=str(results))
             if status_code == 404: raise web.HTTPNotFound(reason=reason, body=str(results))
             raise web.HTTPInternalServerError(reason=reason, body=str(results)) # Default for other errors

        if results and "items" in results:
             # Add processed thumbnail URL for convenience
             for item in results.get("items", []):
                 thumbnail = None
                 if item.get("modelVersions"):
                     latest_version = item["modelVersions"][0]
                     images = latest_version.get("images")
                     if images and isinstance(images, list) and len(images) > 0:
                         img_data = next((img for img in images if img.get("url") and img.get("type") == "image"), None)
                         if not img_data: img_data = next((img for img in images if img.get("url")), None)
                         if img_data:
                             base_url = img_data["url"]
                             # Simple width replacement for thumbnail
                             try: thumbnail = base_url.replace("/width=auto", "/width=200", 1)
                             except: thumbnail = base_url
                 item["thumbnailUrl"] = thumbnail # Add to the item dict

             return web.json_response(results)
        else:
             # Handle unexpected response format from API wrapper
             print(f"Warning: Unexpected search result format: {results}")
             return web.json_response({"items": [], "metadata": {}}, status=500)

    except web.HTTPError as http_err:
        raise http_err
    except Exception as e:
        print("--- Unhandled Error in /civitai/search ---")
        traceback.print_exc()
        print("--- End Error ---")
        raise web.HTTPInternalServerError(reason=f"An unexpected search error occurred: {str(e)}")

@prompt_server.routes.get("/civitai/model_types")
async def route_get_model_types(request):
    """API Endpoint to get the known model types and their mapping."""
    try:
        # Return a simpler map for the frontend: { internal_key: display_name }
        types_map = {key: data[0] for key, data in MODEL_TYPE_DIRS.items()}
        return web.json_response(types_map)
    except Exception as e:
        print(f"Error getting model types: {e}")
        raise web.HTTPInternalServerError(reason=str(e))

print("[Civitai Downloader] Server routes registered.")