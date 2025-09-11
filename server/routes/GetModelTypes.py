# ================================================
# File: server/routes/GetModelTypes.py
# ================================================
import os
from aiohttp import web
import server # ComfyUI server instance
import folder_paths

prompt_server = server.PromptServer.instance

@prompt_server.routes.get("/civitai/model_types")
async def route_get_model_types(request):
    """API Endpoint to get the known model types and their mapping."""
    try:
        # Dynamically list all first-level folders under the main models directory
        models_dir = getattr(folder_paths, 'models_dir', None)
        if not models_dir:
            base = getattr(folder_paths, 'base_path', os.getcwd())
            models_dir = os.path.join(base, 'models')
        if not os.path.isdir(models_dir):
            return web.json_response({})

        entries = {}
        for name in sorted(os.listdir(models_dir)):
            p = os.path.join(models_dir, name)
            if os.path.isdir(p):
                entries[name] = name
        return web.json_response(entries)
    except Exception as e:
        print(f"Error getting model types: {e}")
        return web.json_response({"error": "Internal Server Error", "details": str(e), "status_code": 500}, status=500)
