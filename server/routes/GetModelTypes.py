# ================================================
# File: server/routes/GetModelTypes.py
# ================================================
from aiohttp import web
import server # ComfyUI server instance
from ...config import MODEL_TYPE_DIRS

prompt_server = server.PromptServer.instance

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