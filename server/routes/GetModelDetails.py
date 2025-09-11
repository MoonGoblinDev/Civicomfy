# ================================================
# File: server/routes/GetModelDetails.py
# ================================================
import os
import json
import traceback
from aiohttp import web

import server # ComfyUI server instance
from ..utils import get_request_json, get_civitai_model_and_version_details
from ...api.civitai import CivitaiAPI
from ...config import PLACEHOLDER_IMAGE_PATH

prompt_server = server.PromptServer.instance

@prompt_server.routes.post("/civitai/get_model_details")
async def route_get_model_details(request):
    """API Endpoint to fetch model/version details for preview."""
    try:
        data = await get_request_json(request)
        model_url_or_id = data.get("model_url_or_id")
        req_version_id = data.get("model_version_id") # Optional explicit version ID
        api_key = data.get("api_key", "")

        if not model_url_or_id:
            raise web.HTTPBadRequest(reason="Missing 'model_url_or_id'")

        # Instantiate API
        api = CivitaiAPI(api_key or None)

        # Use the helper to get details
        details = await get_civitai_model_and_version_details(api, model_url_or_id, req_version_id)
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
        def _guess_precision(file_dict):
            try:
                name = (file_dict.get('name') or '').lower()
                meta = (file_dict.get('metadata') or {})
                for key in ('precision', 'dtype', 'fp'):
                    val = (meta.get(key) or '').lower()
                    if val:
                        return val
                if 'fp8' in name or 'int8' in name or '8bit' in name or '8-bit' in name:
                    return 'fp8'
                if 'fp16' in name or 'bf16' in name or '16bit' in name or '16-bit' in name:
                    return 'fp16'
                if 'fp32' in name or '32bit' in name or '32-bit' in name:
                    return 'fp32'
            except Exception:
                pass
            return 'N/A'

        file_name = primary_file.get('name', 'N/A')
        file_size_kb = primary_file.get('sizeKB', 0)
        _meta = (primary_file.get('metadata') or {})
        file_format = _meta.get('format', 'N/A') # e.g., SafeTensor, PickleTensor
        file_model_size = _meta.get('size', 'N/A') # e.g., Pruned/Full
        file_precision = _guess_precision(primary_file)

        thumbnail_url = None
        images = version_info.get("images") # Get the images list from the version info
        nsfw_level = None

        # Check if images list exists, is a list, has items, and the first item is valid with a URL
        if images and isinstance(images, list) and len(images) > 0 and \
           isinstance(images[0], dict) and images[0].get("url"):
            # Use the URL of the very first image directly
            first_image = images[0]
            thumbnail_url = first_image["url"]
            try:
                lvl = first_image.get("nsfwLevel")
                nsfw_level = int(lvl) if lvl is not None else None
            except Exception:
                nsfw_level = None
            print(f"[Get Details Route] Using first image URL as thumbnail: {thumbnail_url}")
        else:
            print("[Get Details Route] No valid first image found in version info, falling back to placeholder.")
            # Fallback placeholder logic (remains the same)
            placeholder_filename = os.path.basename(PLACEHOLDER_IMAGE_PATH) if PLACEHOLDER_IMAGE_PATH else "placeholder.jpeg"
            thumbnail_url = f"./{placeholder_filename}" # Relative path for JS to resolve


        # Fallback placeholder if no thumbnail found
        if not thumbnail_url:
             placeholder_filename = os.path.basename(PLACEHOLDER_IMAGE_PATH) if PLACEHOLDER_IMAGE_PATH else "placeholder.jpeg"
             thumbnail_url = f"./{placeholder_filename}" # Relative path for JS

        # Build minimal files listing for selection in UI/clients
        files_list = []
        vfiles = version_info.get("files", []) or []
        if isinstance(vfiles, list):
            for f in vfiles:
                if not isinstance(f, dict):
                    continue
                _fmeta = (f.get("metadata") or {})
                files_list.append({
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "size_kb": f.get("sizeKB"),
                    "format": _fmeta.get("format"),
                    "model_size": _fmeta.get("size"),
                    "precision": _guess_precision(f),
                    "downloadable": bool(f.get("downloadUrl")),
                })

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
                "model_size": file_model_size,
                "precision": file_precision,
            },
            "files": files_list,
            "thumbnail_url": thumbnail_url,
            "nsfw_level": nsfw_level,
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
