# ================================================
# File: server/routes/GetStatus.py
# ================================================
from aiohttp import web
import server # ComfyUI server instance
from ...downloader.manager import manager as download_manager

prompt_server = server.PromptServer.instance

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