# ================================================
# File: server/routes/RetryDownload.py
# ================================================
import asyncio
import json
from aiohttp import web

import server # ComfyUI server instance
from ...downloader.manager import manager as download_manager

prompt_server = server.PromptServer.instance

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