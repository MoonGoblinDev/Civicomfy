# ================================================
# File: config.py
# ================================================
import os
import folder_paths # Use ComfyUI's folder_paths

# --- Configuration ---
MAX_CONCURRENT_DOWNLOADS = 3
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1MB
DEFAULT_CONNECTIONS = 4
DOWNLOAD_HISTORY_LIMIT = 100
DOWNLOAD_TIMEOUT = 60 # Timeout for individual download chunks/requests (seconds)
HEAD_REQUEST_TIMEOUT = 25 # Timeout for initial HEAD request (seconds)
METADATA_DOWNLOAD_TIMEOUT = 20 # Timeout for downloading thumbnail (seconds)

# --- Paths ---
# The root directory of *this specific plugin/extension*
# Calculated based on the location of this config.py file
PLUGIN_ROOT = os.path.dirname(os.path.realpath(__file__))

# Construct web paths relative to the plugin's root directory
WEB_DIRECTORY = os.path.join(PLUGIN_ROOT, "web")
JAVASCRIPT_PATH = os.path.join(WEB_DIRECTORY, "js")
CSS_PATH = os.path.join(WEB_DIRECTORY, "css")
# Corrected path construction to avoid issues with leading slashes
PLACEHOLDER_IMAGE_PATH = os.path.join(WEB_DIRECTORY, "images", "placeholder.jpeg")

# Get ComfyUI directories using folder_paths
COMFYUI_ROOT_DIR = folder_paths.base_path
MODELS_DIR = folder_paths.models_dir # Base 'models' directory

# --- Model Types ---
# Maps the internal key (lowercase) to a tuple: (display_name, subfolder_name)
# The subfolder_name is relative to the ComfyUI MODELS_DIR.
MODEL_TYPE_DIRS = {
    "checkpoint": ("Checkpoint", "checkpoints"),
    "diffusionmodels": ("Diffusion Models","diffusion_models"),
    "Unet": ("Unet", "Unet"),
    "lora": ("Lora", "loras"),
    "locon": ("LoCon", "loras"), # Often grouped with LORAs
    "lycoris": ("LyCORIS", "loras"), # Sometimes grouped with LORAs
    "vae": ("VAE", "vae"),
    "embedding": ("Embedding", "embeddings"),
    "hypernetwork": ("Hypernetwork", "hypernetworks"),
    "controlnet": ("ControlNet", "controlnet"),
    "upscaler": ("Upscaler", "upscale_models"),
    "motionmodule": ("Motion Module", "motion_models"),
    "poses": ("Poses", "poses"), # Saved inside models/poses
    "wildcards": ("Wildcards", "wildcards"), # Often saved outside models dir, but can be here too
    # Place 'other' in a dedicated subfolder WITHIN the Civicomfy node folder
    # This keeps downloaded files associated with this node separate if type is unknown.
    # The path here is RELATIVE to MODELS_DIR.
    "other": ("Other", os.path.join("custom_nodes", os.path.basename(PLUGIN_ROOT), "other_models"))
}

# Civitai API specific type mapping (for search filters)
# Maps internal key (lowercase) to Civitai API 'types' parameter value
CIVITAI_API_TYPE_MAP = {
    "checkpoint": "Checkpoint",
    "lora": "LORA",
    "locon": "LoCon",
    "lycoris": "LORA", # Civitai might group LyCORIS under LORA search type
    "vae": "VAE",
    "embedding": "TextualInversion",
    "hypernetwork": "Hypernetwork",
    "controlnet": "Controlnet",
    "motionmodule": "MotionModule",
    "poses": "Poses",
    "wildcards": "Wildcards",
    "upscaler": "Upscaler", 
    # "other": None,
}

AVAILABLE_MEILI_BASE_MODELS = [
    "AuraFlow", "CogVideoX", "Flux.1 D", "Flux.1 S", "Hunyuan 1", "Hunyuan Video",
    "Illustrious", "Kolors", "LTXV", "Lumina", "Mochi", "NoobAI", "ODOR", "Other",
    "PixArt E", "PixArt a", "Playground v2", "Pony", "SD 1.4", "SD 1.5",
    "SD 1.5 Hyper", "SD 1.5 LCM", "SD 2.0", "SD 2.0 768", "SD 2.1", "SD 2.1 768",
    "SD 2.1 Unclip", "SD 3", "SD 3.5", "SD 3.5 Large", "SD 3.5 Large Turbo",
    "SD 3.5 Medium", "SDXL 0.9", "SDXL 1.0", "SDXL 1.0 LCM", "SDXL Distilled",
    "SDXL Hyper", "SDXL Lightning", "SDXL Turbo", "SVD", "SVD XT", "Stable Cascade",
    "Wan Video"
]

# --- Filename Suffixes ---
METADATA_SUFFIX = ".cminfo.json"
PREVIEW_SUFFIX = ".preview.jpeg" # Keep as requested, even if source is png/webp

# Ensure 'other' directory exists (using the path relative to MODELS_DIR)
try:
    _other_relative_path = MODEL_TYPE_DIRS["other"][1]
    _other_full_path = os.path.join(MODELS_DIR, _other_relative_path)
    os.makedirs(_other_full_path, exist_ok=True)
    print(f"[Civicomfy Config] Ensured 'other' model directory exists: {_other_full_path}")
except Exception as e:
    print(f"[Civicomfy Config] Warning: Failed to create 'other' model directory: {e}")

# --- Log Initial Paths for Verification ---
print("-" * 30)
print("[Civicomfy Config Initialized]")
print(f"  - Plugin Root: {PLUGIN_ROOT}")
print(f"  - Web Directory: {WEB_DIRECTORY}")
print(f"  - ComfyUI Models Dir: {MODELS_DIR}")
print(f"  - 'Other' Models Subfolder (relative): {MODEL_TYPE_DIRS['other'][1]}")
print("-" * 30)