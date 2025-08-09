# ================================================
# File: server/routes/GetBaseModels.py
# ================================================
from aiohttp import web
import server # ComfyUI server instance
from ...config import AVAILABLE_MEILI_BASE_MODELS

prompt_server = server.PromptServer.instance

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