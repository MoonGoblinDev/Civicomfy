# ================================================
# File: server/routes/ClearHistory.py
# ================================================
import asyncio
from aiohttp import web

import server # ComfyUI server instance
from ...downloader.manager import manager as download_manager

prompt_server = server.PromptServer.instance

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