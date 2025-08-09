# ================================================
# File: server/routes/OpenPath.py
# ================================================
import asyncio
import json
from aiohttp import web

import server # ComfyUI server instance
from ...downloader.manager import manager as download_manager

prompt_server = server.PromptServer.instance

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