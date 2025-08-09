# ================================================
# File: server/routes/CancelDownload.py
# ================================================
import json
from aiohttp import web
import server # ComfyUI server instance
from ..utils import get_request_json
from ...downloader.manager import manager as download_manager

prompt_server = server.PromptServer.instance

@prompt_server.routes.post("/civitai/cancel")
async def route_cancel_download(request):
    """API Endpoint to cancel a download."""
    try:
        data = await get_request_json(request)
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