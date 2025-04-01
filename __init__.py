# ComfyUI_Civitai_Downloader/__init__.py

import os

# Define paths relative to this __init__.py file
EXTENSION_ROOT = os.path.dirname(os.path.realpath(__file__))
WEB_PATH = os.path.join(EXTENSION_ROOT, "web")
JS_PATH = os.path.join(WEB_PATH, "js")
CSS_PATH = os.path.join(JS_PATH, "css")
JS_FILENAME = "civitaiDownloader.js"
CSS_FILENAME = "civitaiDownloader.css"
JS_FILE_PATH = os.path.join(JS_PATH, JS_FILENAME)
CSS_FILE_PATH = os.path.join(JS_PATH, CSS_FILENAME)

# --- Import Core Components ---
# Import configurations and utility functions first
# Ensure config and helpers don't have side effects unsuitable for just checking files
try:
    from .config import WEB_DIRECTORY as config_WEB_DIRECTORY, PLACEHOLDER_IMAGE_PATH
    from .utils.helpers import create_placeholder_image
    # Import downloader manager (creates the instance)
    from .downloader import manager as download_manager
    # Import server routes (registers the routes)
    from .server import routes
    imports_successful = True
    print("[Civitai Downloader] Core modules imported successfully.")
except ImportError as e:
    imports_successful = False
    print("*"*80)
    print(f"[Civitai Downloader] ERROR: Failed to import core modules: {e}")
    print("Please ensure the file structure is correct and all required files exist.")
    print("Extension will likely not function correctly.")
    print("*"*80)
except Exception as e:
    imports_successful = False
    # Catch other potential init errors during import
    import traceback
    print("*"*80)
    print(f"[Civitai Downloader] ERROR: An unexpected error occurred during module import:")
    traceback.print_exc()
    print("Extension will likely not function correctly.")
    print("*"*80)

# --- Check for Frontend Files ---
frontend_files_ok = True
if not os.path.exists(CSS_FILE_PATH):
    print("*"*80)
    print(f"[Civitai Downloader] WARNING: Frontend CSS file not found!")
    print(f"                         Expected at: {CSS_FILE_PATH}")
    print("                         The downloader UI may not display correctly.")
    print("                         Please ensure 'civitaiDownloader.css' is placed in the 'web/css' directory.")
    print("*"*80)
    frontend_files_ok = False

if not os.path.exists(JS_FILE_PATH):
    print("*"*80)
    print(f"[Civitai Downloader] WARNING: Frontend JavaScript file not found!")
    print(f"                         Expected at: {JS_FILE_PATH}")
    print("                         The downloader UI functionality will be missing.")
    print("                         Please ensure 'civitaiDownloader.js' is placed in the 'web/js' directory.")
    print("*"*80)
    frontend_files_ok = False

# --- ComfyUI Registration ---
if imports_successful:
    # Standard ComfyUI extension variables
    # No custom nodes defined in this extension
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

    # Define the web directory for ComfyUI to serve
    # The key is the path component in the URL: /extensions/ComfyUI_Civitai_Downloader/...
    # The value is the directory path relative to this __init__.py file
    WEB_DIRECTORY = "./web" # This tells ComfyUI to serve the ./web folder relative to this file

    # --- Startup Messages ---
    print("-" * 30)
    print("--- Civitai Downloader Custom Extension Loaded ---")
    print(f"- Serving frontend files from: {os.path.abspath(WEB_PATH)} (Relative: {WEB_DIRECTORY})")
    # Download manager and routes are initialized/registered upon import
    print(f"- Download Manager Initialized: {'Yes' if 'download_manager' in locals() else 'No! Import failed.'}")
    print(f"- API Endpoints Registered: {'Yes' if 'routes' in locals() else 'No! Import failed.'}")
    if frontend_files_ok:
         print("- Frontend files found.")
    else:
         print("- WARNING: Frontend files missing (see warnings above). UI may not work.")
    print("- Look for 'Civitai Downloader' button in the ComfyUI menu.")
    print("-" * 30)

    # Create placeholder image if needed (can run even if other things failed)
    try:
        create_placeholder_image(PLACEHOLDER_IMAGE_PATH)
    except NameError:
        # Handle case where PLACEHOLDER_IMAGE_PATH itself failed to import
        print("[Civitai Downloader] Warning: Could not create placeholder image due to failed config import.")
    except Exception as e:
        print(f"[Civitai Downloader] Error trying to create placeholder image: {e}")

else:
    # If imports failed, don't register anything with ComfyUI
    print("[Civitai Downloader] Initialization failed due to import errors. Extension inactive.")
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
    WEB_DIRECTORY = None # Do not serve web directory if backend failed