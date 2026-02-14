# ================================================
# File: server/routes/GetModelDirs.py
# ================================================
import os
import json
from aiohttp import web

import server  # ComfyUI server instance
from ...utils.helpers import (
    get_model_dir,
    get_model_folder_paths,
    get_model_type_folder_name,
    sanitize_filename,
)
from ...config import PLUGIN_ROOT
import folder_paths

prompt_server = server.PromptServer.instance

CUSTOM_ROOTS_FILE = os.path.join(PLUGIN_ROOT, "custom_roots.json")
ROOT_SETTINGS_FILE = os.path.join(PLUGIN_ROOT, "root_settings.json")
GLOBAL_ROOT_KEY = "global_default_root"

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

def _load_root_settings():
    try:
        if os.path.exists(ROOT_SETTINGS_FILE):
            with open(ROOT_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"[Civicomfy] Warning: Failed to load root settings: {e}")
    return {}

def _save_root_settings(data):
    try:
        with open(ROOT_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Civicomfy] Error writing root settings file: {e}")
        return False

def get_global_default_root():
    settings = _load_root_settings()
    raw = settings.get(GLOBAL_ROOT_KEY)
    if isinstance(raw, str):
        raw = raw.strip()
        if raw:
            return os.path.abspath(raw)
    return None

def _set_global_default_root(path):
    settings = _load_root_settings()
    if path and str(path).strip():
        settings[GLOBAL_ROOT_KEY] = os.path.abspath(str(path).strip())
    else:
        settings.pop(GLOBAL_ROOT_KEY, None)
    return _save_root_settings(settings)

def _get_global_root_for_type(model_type: str):
    global_root = get_global_default_root()
    if not global_root:
        return None
    model_subfolder = get_model_type_folder_name(model_type)
    return os.path.abspath(os.path.join(global_root, model_subfolder))

def _get_effective_base_dir(model_type: str):
    global_type_root = _get_global_root_for_type(model_type)
    if global_type_root:
        return global_type_root
    return get_model_dir(model_type)

def _get_custom_roots_for_type(model_type: str):
    roots_map = _load_custom_roots()
    model_type_raw = (model_type or '').lower().strip()
    canonical_type = get_model_type_folder_name(model_type_raw)
    custom = []
    for key in [model_type_raw, canonical_type]:
        for p in roots_map.get(key, []):
            ap = os.path.abspath(p)
            if ap not in custom:
                custom.append(ap)
    return custom

def _get_all_roots_for_type(model_type: str):
    model_type = (model_type or '').lower().strip()
    roots = []

    # Prefer global default root for this type when configured
    global_type_root = _get_global_root_for_type(model_type)
    if global_type_root and global_type_root not in roots:
        roots.append(global_type_root)

    # Include all registered paths from ComfyUI (respects extra_model_paths.yaml)
    for p in get_model_folder_paths(model_type):
        if p not in roots:
            roots.append(p)

    # Include plugin custom roots
    for p in _get_custom_roots_for_type(model_type):
        if p not in roots:
            roots.append(p)

    # Ensure at least one sane fallback
    if not roots:
        d = get_model_dir(model_type)
        if d:
            roots.append(os.path.abspath(d))

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
    model_type = request.query.get("type", "checkpoints").lower().strip()
    root = (request.query.get("root") or "").strip()
    try:
        base_dir = os.path.abspath(root) if root else _get_effective_base_dir(model_type)
        os.makedirs(base_dir, exist_ok=True)
        subdirs = _list_subdirs(base_dir)
        global_root = get_global_default_root()
        return web.json_response({
            "model_type": model_type,
            "base_dir": base_dir,
            "subdirs": subdirs,  # relative paths, "" represents the base root
            "global_root": global_root or "",
            "using_global_root": bool(global_root and not root),
        })
    except Exception as e:
        return web.json_response({"error": "Failed to list directories", "details": str(e)}, status=500)

@prompt_server.routes.post("/civitai/create_dir")
async def route_create_model_dir(request):
    """Create a new subdirectory under a model type's base directory."""
    try:
        data = await request.json()
        model_type = (data.get("model_type") or "checkpoints").lower().strip()
        new_dir = (data.get("new_dir") or "").strip()
        if not new_dir:
            return web.json_response({"error": "Missing 'new_dir'"}, status=400)

        # If client provided an explicit root, prefer it
        base_dir = (data.get("root") or "").strip()
        base_dir = os.path.abspath(base_dir) if base_dir else _get_effective_base_dir(model_type)
        os.makedirs(base_dir, exist_ok=True)

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
    model_type = request.query.get("type", "checkpoints").lower().strip()
    roots = _get_all_roots_for_type(model_type)
    global_root = get_global_default_root()
    return web.json_response({
        "model_type": model_type,
        "roots": roots,
        "global_root": global_root or "",
        "effective_root": _get_effective_base_dir(model_type),
    })

@prompt_server.routes.post("/civitai/create_root")
async def route_create_model_root(request):
    """Create a new root directory for a model type and register it in plugin config.
       Note: ComfyUI may require restart to recognize this root globally; the plugin uses it immediately.
    """
    try:
        data = await request.json()
        model_type = (data.get("model_type") or "checkpoints").lower().strip()
        abs_path = os.path.expanduser((data.get("path") or "").strip())
        if not abs_path:
            return web.json_response({"error": "Missing 'path'"}, status=400)
        if not os.path.isabs(abs_path):
            return web.json_response({"error": "Path must be absolute"}, status=400)
        # Normalize to absolute path
        abs_path = os.path.abspath(abs_path)
        # Create directory if missing
        os.makedirs(abs_path, exist_ok=True)

        type_key = get_model_type_folder_name(model_type)
        roots = _load_custom_roots()
        current = roots.get(type_key, [])
        if abs_path not in current:
            current.append(abs_path)
            roots[type_key] = current
            if not _save_custom_roots(roots):
                return web.json_response({"error": "Failed to persist custom root"}, status=500)
        return web.json_response({"success": True, "path": abs_path})
    except Exception as e:
        return web.json_response({"error": "Failed to create root", "details": str(e)}, status=500)

@prompt_server.routes.get("/civitai/global_root")
async def route_get_global_root(request):
    """Return the persisted global download root (if configured)."""
    global_root = get_global_default_root()
    return web.json_response({
        "global_root": global_root or "",
        "enabled": bool(global_root),
    })

@prompt_server.routes.post("/civitai/global_root")
async def route_set_global_root(request):
    """Persist a global download root used as: <global_root>/<model_type_folder>."""
    try:
        data = await request.json()
        path = os.path.expanduser((data.get("path") or "").strip())
        if not path:
            return web.json_response({"error": "Missing 'path'"}, status=400)
        if not os.path.isabs(path):
            return web.json_response({"error": "Path must be absolute"}, status=400)

        abs_path = os.path.abspath(path)
        os.makedirs(abs_path, exist_ok=True)
        if not _set_global_default_root(abs_path):
            return web.json_response({"error": "Failed to persist global root"}, status=500)

        return web.json_response({"success": True, "global_root": abs_path})
    except Exception as e:
        return web.json_response({"error": "Failed to set global root", "details": str(e)}, status=500)

@prompt_server.routes.post("/civitai/global_root/clear")
async def route_clear_global_root(request):
    """Clear the persisted global download root."""
    try:
        if not _set_global_default_root(None):
            return web.json_response({"error": "Failed to clear global root"}, status=500)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": "Failed to clear global root", "details": str(e)}, status=500)
