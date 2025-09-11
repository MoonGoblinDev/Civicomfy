# ================================================
# File: server/routes/GetModelDirs.py
# ================================================
import os
import json
from aiohttp import web

import server  # ComfyUI server instance
from ...utils.helpers import get_model_dir, sanitize_filename
from ...config import PLUGIN_ROOT
import folder_paths

prompt_server = server.PromptServer.instance

CUSTOM_ROOTS_FILE = os.path.join(PLUGIN_ROOT, "custom_roots.json")

def _load_custom_roots():
    try:
        if os.path.exists(CUSTOM_ROOTS_FILE):
            with open(CUSTOM_ROOTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Normalize values to lists of strings
                    return {k: [str(p) for p in (v or []) if isinstance(p, str)] for k, v in data.items()}
    except Exception as e:
        print(f"[Civicomfy] Warning: Failed to load custom roots: {e}")
    return {}

def _save_custom_roots(data):
    try:
        with open(CUSTOM_ROOTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Civicomfy] Error writing custom roots file: {e}")
        return False

def _get_all_roots_for_type(model_type: str):
    model_type = (model_type or '').lower().strip()
    roots = []
    try:
        # Preferred: ask ComfyUI for all registered directories for this type
        get_fp = getattr(folder_paths, 'get_folder_paths', None)
        if callable(get_fp):
            lst = get_fp(model_type)
            if isinstance(lst, (list, tuple)):
                roots.extend([os.path.abspath(p) for p in lst if isinstance(p, str)])
        else:
            d = folder_paths.get_directory_by_type(model_type)
            if d:
                roots.append(os.path.abspath(d))
    except Exception:
        # Fallback to our main model dir for type
        d = get_model_dir(model_type)
        if d:
            roots.append(os.path.abspath(d))

    custom = _load_custom_roots().get(model_type, [])
    for p in custom:
        ap = os.path.abspath(p)
        if ap not in roots:
            roots.append(ap)
    # Include all immediate subdirectories inside the main ComfyUI models folder
    try:
        models_dir = getattr(folder_paths, 'models_dir', None)
        if not models_dir:
            base = getattr(folder_paths, 'base_path', os.getcwd())
            models_dir = os.path.join(base, 'models')
        if os.path.isdir(models_dir):
            for name in os.listdir(models_dir):
                p = os.path.join(models_dir, name)
                if os.path.isdir(p):
                    ap = os.path.abspath(p)
                    if ap not in roots:
                        roots.append(ap)
    except Exception as e:
        print(f"[Civicomfy] Warning: Failed to enumerate models dir subfolders: {e}")
    return roots

def _list_subdirs(root_dir: str, max_entries: int = 5000):
    """Return a sorted list of relative subdirectory paths under root_dir, including nested."""
    rel_dirs = set()
    root_dir = os.path.abspath(root_dir)
    count = 0
    for current, dirs, _files in os.walk(root_dir):
        # Avoid following symlinks to reduce risk
        abs_current = os.path.abspath(current)
        try:
            rel = os.path.relpath(abs_current, root_dir)
        except Exception:
            continue
        if rel == ".":
            rel = ""  # represent root as empty
        rel_dirs.add(rel)
        count += 1
        if count >= max_entries:
            break
    return sorted(rel_dirs)

@prompt_server.routes.get("/civitai/model_dirs")
async def route_get_model_dirs(request):
    """List the base directory (or provided root) and all subdirectories for a given model type."""
    model_type = request.query.get("type", "checkpoint").lower().strip()
    root = (request.query.get("root") or "").strip()
    try:
        base_dir = root if root else get_model_dir(model_type)
        subdirs = _list_subdirs(base_dir)
        return web.json_response({
            "model_type": model_type,
            "base_dir": base_dir,
            "subdirs": subdirs,  # relative paths, "" represents the base root
        })
    except Exception as e:
        return web.json_response({"error": "Failed to list directories", "details": str(e)}, status=500)

@prompt_server.routes.post("/civitai/create_dir")
async def route_create_model_dir(request):
    """Create a new subdirectory under a model type's base directory."""
    try:
        data = await request.json()
        model_type = (data.get("model_type") or "checkpoint").lower().strip()
        new_dir = (data.get("new_dir") or "").strip()
        if not new_dir:
            return web.json_response({"error": "Missing 'new_dir'"}, status=400)

        # If client provided an explicit root, prefer it
        base_dir = (data.get("root") or "").strip() or get_model_dir(model_type)

        # Normalize and sanitize each part; disallow absolute and traversal
        norm = os.path.normpath(new_dir.replace("\\", "/"))
        parts = [p for p in norm.split("/") if p and p not in (".", "..")]
        safe_parts = [sanitize_filename(p) for p in parts]
        rel_path = os.path.join(*safe_parts) if safe_parts else ""
        if not rel_path:
            return web.json_response({"error": "Invalid folder name"}, status=400)

        abs_path = os.path.abspath(os.path.join(base_dir, rel_path))
        # Ensure it remains inside base_dir
        if os.path.commonpath([abs_path, os.path.abspath(base_dir)]) != os.path.abspath(base_dir):
            return web.json_response({"error": "Invalid path"}, status=400)

        os.makedirs(abs_path, exist_ok=True)
        return web.json_response({
            "success": True,
            "created": rel_path,
            "abs_path": abs_path,
        })
    except Exception as e:
        return web.json_response({"error": "Failed to create directory", "details": str(e)}, status=500)

@prompt_server.routes.post("/civitai/create_model_type")
async def route_create_model_type(request):
    """Create a new first-level folder under the main models directory."""
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        if not name:
            return web.json_response({"error": "Missing 'name'"}, status=400)

        # Sanitize folder name to a single path component
        from ...utils.helpers import sanitize_filename
        safe = sanitize_filename(name)
        if not safe:
            return web.json_response({"error": "Invalid folder name"}, status=400)

        # Resolve models directory
        models_dir = getattr(folder_paths, 'models_dir', None)
        if not models_dir:
            base = getattr(folder_paths, 'base_path', os.getcwd())
            models_dir = os.path.join(base, 'models')

        abs_path = os.path.abspath(os.path.join(models_dir, safe))
        # Ensure it remains inside models_dir
        if os.path.commonpath([abs_path, os.path.abspath(models_dir)]) != os.path.abspath(models_dir):
            return web.json_response({"error": "Invalid path"}, status=400)

        os.makedirs(abs_path, exist_ok=True)
        return web.json_response({"success": True, "name": safe, "path": abs_path})
    except Exception as e:
        return web.json_response({"error": "Failed to create model type folder", "details": str(e)}, status=500)

@prompt_server.routes.get("/civitai/model_roots")
async def route_get_model_roots(request):
    """Return all known root directories for a model type (ComfyUI + plugin custom roots)."""
    model_type = request.query.get("type", "checkpoint").lower().strip()
    roots = _get_all_roots_for_type(model_type)
    return web.json_response({
        "model_type": model_type,
        "roots": roots,
    })

@prompt_server.routes.post("/civitai/create_root")
async def route_create_model_root(request):
    """Create a new root directory for a model type and register it in plugin config.
       Note: ComfyUI may require restart to recognize this root globally; the plugin uses it immediately.
    """
    try:
        data = await request.json()
        model_type = (data.get("model_type") or "checkpoint").lower().strip()
        abs_path = (data.get("path") or "").strip()
        if not abs_path:
            return web.json_response({"error": "Missing 'path'"}, status=400)
        # Normalize to absolute path
        abs_path = os.path.abspath(abs_path)
        # Create directory if missing
        os.makedirs(abs_path, exist_ok=True)
        roots = _load_custom_roots()
        current = roots.get(model_type, [])
        if abs_path not in current:
            current.append(abs_path)
            roots[model_type] = current
            if not _save_custom_roots(roots):
                return web.json_response({"error": "Failed to persist custom root"}, status=500)
        return web.json_response({"success": True, "path": abs_path})
    except Exception as e:
        return web.json_response({"error": "Failed to create root", "details": str(e)}, status=500)
