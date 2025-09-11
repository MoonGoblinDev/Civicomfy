# ================================================
# File: __init__.py
# ================================================

import os

# Define paths relative to this __init__.py file
EXTENSION_ROOT = os.path.dirname(os.path.realpath(__file__))
WEB_PATH = os.path.join(EXTENSION_ROOT, "web")
JS_PATH = os.path.join(WEB_PATH, "js")
# CSS_PATH definition removed as it was unused and pointed to a non-existent directory.
JS_FILENAME = "civitaiDownloader.js"
CSS_FILENAME = "civitaiDownloader.css"
JS_FILE_PATH = os.path.join(JS_PATH, JS_FILENAME)
CSS_FILE_PATH = os.path.join(JS_PATH, CSS_FILENAME) 

# --- Import Core Components ---
# Import configurations and utility functions first
# Ensure config and helpers don't have side effects unsuitable for just checking files
try:
    from .config import WEB_DIRECTORY as config_WEB_DIRECTORY
    # Import downloader manager (creates the instance)
    from .downloader import manager as download_manager
    # Import server routes (registers the routes)
    from .server import routes
    imports_successful = True
    print("[Civicomfy] Core modules imported successfully.")
except ImportError as e:
    imports_successful = False
    print("*"*80)
    print(f"[Civicomfy] ERROR: Failed to import core modules: {e}")
    print("Please ensure the file structure is correct and all required files exist.")
    print("Extension will likely not function correctly.")
    print("*"*80)
except Exception as e:
    imports_successful = False
    # Catch other potential init errors during import
    import traceback
    print("*"*80)
    print(f"[Civicomfy] ERROR: An unexpected error occurred during module import:")
    traceback.print_exc()
    print("Extension will likely not function correctly.")
    print("*"*80)

# --- Check for Frontend Files ---
frontend_files_ok = True
if not os.path.exists(CSS_FILE_PATH):
    print("*"*80)
    print(f"[Civicomfy] WARNING: Frontend CSS file not found!")
    print(f"                         Expected at: {CSS_FILE_PATH}")
    print("                         The downloader UI may not display correctly.")
    print(f"                         Please ensure '{CSS_FILENAME}' is placed in the '{os.path.basename(JS_PATH)}' directory inside 'web'.") # Corrected path hint
    print("*"*80)
    frontend_files_ok = False

if not os.path.exists(JS_FILE_PATH):
    print("*"*80)
    print(f"[Civicomfy] WARNING: Frontend JavaScript file not found!")
    print(f"                         Expected at: {JS_FILE_PATH}")
    print("                         The downloader UI functionality will be missing.")
    print(f"                         Please ensure '{JS_FILENAME}' is placed in the '{os.path.basename(JS_PATH)}' directory inside 'web'.") # Corrected path hint
    print("*"*80)
    frontend_files_ok = False

# --- ComfyUI Registration ---
if imports_successful:
    # Standard ComfyUI extension variables
    # No custom nodes defined in this extension
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

    # Define the web directory for ComfyUI to serve
    # The key is the path component in the URL: /extensions/Civicomfy/...
    # The value is the directory path relative to this __init__.py file
    WEB_DIRECTORY = "./web" # This tells ComfyUI to serve the ./web folder relative to this file

    # --- Startup Messages ---
    print("-" * 30)
    print("--- Civicomfy Custom Extension Loaded ---")
    print(f"- Serving frontend files from: {os.path.abspath(WEB_PATH)} (Relative: {WEB_DIRECTORY})")
    # Download manager and routes are initialized/registered upon import
    print(f"- Download Manager Initialized: {'Yes' if 'download_manager' in locals() else 'No! Import failed.'}")
    print(f"- API Endpoints Registered: {'Yes' if 'routes' in locals() else 'No! Import failed.'}")
    if frontend_files_ok:
         print("- Frontend files found.")
    else:
         print("- WARNING: Frontend files missing (see warnings above). UI may not work.")
    print("- Look for 'Civicomfy' button in the ComfyUI menu.")
    print("-" * 30)

    # Ensure default model-type directories exist at startup
    try:
        from .utils.helpers import get_model_dir
        from .config import MODEL_TYPE_DIRS
        created = []
        for key in MODEL_TYPE_DIRS.keys():
            path = get_model_dir(key)
            created.append((key, path))
        print("[Civicomfy] Verified model type directories:")
        for k, p in created:
            print(f"  - {k}: {p}")
    except Exception as e:
        print(f"[Civicomfy] Warning: Failed ensuring model directories at startup: {e}")

else:
    # If imports failed, don't register anything with ComfyUI
    print("[Civicomfy] Initialization failed due to import errors. Extension inactive.")
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
    WEB_DIRECTORY = None # Do not serve web directory if backend failed
