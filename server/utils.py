# ================================================
# File: server/utils.py
# ================================================
import json
from typing import Any, Dict, Optional
from aiohttp import web

# Import necessary components from our modules
from ..api.civitai import CivitaiAPI
from ..utils.helpers import parse_civitai_input, select_primary_file

async def get_request_json(request):
    """Safely get JSON data from request."""
    try:
        return await request.json()
    except Exception as e:
        print(f"Error parsing request JSON: {e}")
        raise web.HTTPBadRequest(reason=f"Invalid JSON format: {e}")

async def get_civitai_model_and_version_details(api: CivitaiAPI, model_url_or_id: str, req_version_id: Optional[int]) -> Dict[str, Any]:
    """
    Helper to fetch Civitai details.
    Prioritizes fetching model info based on resolved Model ID.
    Fetches specific version info if version ID is provided/resolved, otherwise latest.
    Returns a dict with 'model_info', 'version_info', 'primary_file', and resolved IDs.
    Raises HTTP exceptions on critical failures.
    """
    target_model_id = None
    target_version_id = None
    potential_version_id_from_input = None
    model_info = {}
    version_info_to_use = {} # The version (specific or latest) whose file we'll use
    primary_file = None

    # --- 1. Parse Input to get potential IDs ---
    parsed_model_id, parsed_version_id = parse_civitai_input(model_url_or_id)

    # Determine the initial target model ID (input URL/ID takes precedence)
    target_model_id = parsed_model_id

    # Determine the specific version requested (explicit param > URL param)
    if req_version_id and str(req_version_id).isdigit():
        try:
            potential_version_id_from_input = int(req_version_id)
        except (ValueError, TypeError):
             print(f"[API Helper] Warning: Invalid req_version_id: {req_version_id}. Ignoring.")
    elif parsed_version_id:
        potential_version_id_from_input = parsed_version_id

    # --- 2. Ensure we have a Model ID ---
    # If we only got a version ID from the input (e.g., civitai.com/model-versions/456),
    # we need to fetch that version *first* just to find the model ID.
    if not target_model_id and potential_version_id_from_input:
        print(f"[API Helper] Input requires fetching version {potential_version_id_from_input} first to find model ID.")
        temp_version_info = api.get_model_version_info(potential_version_id_from_input)
        if temp_version_info and "error" not in temp_version_info and temp_version_info.get('modelId'):
            target_model_id = temp_version_info['modelId']
            print(f"[API Helper] Found Model ID {target_model_id} from Version ID {potential_version_id_from_input}.")
            # We might reuse temp_version_info later if this was the specifically requested version
        else:
            err = temp_version_info.get('details', 'Could not find model ID from version') if isinstance(temp_version_info, dict) else 'API error'
            raise web.HTTPNotFound(reason=f"Could not determine Model ID from Version ID {potential_version_id_from_input}", body=json.dumps({"error": f"Version {potential_version_id_from_input} not found or missing modelId", "details": err}))

    # If still no model ID after potential lookup, fail
    if not target_model_id:
        raise web.HTTPBadRequest(reason="Could not determine a valid Model ID from the input.")

    # --- 3. Fetch Core Model Information (Always based on target_model_id) ---
    print(f"[API Helper] Fetching core model info for Model ID: {target_model_id}")
    model_info_result = api.get_model_info(target_model_id)
    if not model_info_result or "error" in model_info_result:
        err_details = model_info_result.get('details', 'Unknown API error') if isinstance(model_info_result, dict) else 'Unknown API error'
        raise web.HTTPNotFound(reason=f"Model {target_model_id} not found or API error", body=json.dumps({"error": f"Model {target_model_id} not found or API error", "details": err_details}))
    model_info = model_info_result # Store the successfully fetched model info

    # --- 4. Determine and Fetch Version Info for File Details ---
    if potential_version_id_from_input:
        # User specified a version explicitly, fetch its details
        print(f"[API Helper] Fetching specific version info for Version ID: {potential_version_id_from_input}")
        target_version_id = potential_version_id_from_input # This is the version we need info for
        # Check if we already fetched this during Model ID lookup
        if 'temp_version_info' in locals() and temp_version_info.get('id') == target_version_id:
             print("[API Helper] Reusing version info fetched earlier.")
             version_info_to_use = temp_version_info
        else:
            version_info_result = api.get_model_version_info(target_version_id)
            if not version_info_result or "error" in version_info_result:
                err_details = version_info_result.get('details', 'Unknown API error') if isinstance(version_info_result, dict) else 'Unknown API error'
                raise web.HTTPNotFound(reason=f"Specified Version {target_version_id} not found or API error", body=json.dumps({"error": f"Version {target_version_id} not found or API error", "details": err_details}))
            version_info_to_use = version_info_result
    else:
        # No specific version requested, find latest/default from model_info
        print(f"[API Helper] Finding latest/default version for Model ID: {target_model_id}")
        versions = model_info.get("modelVersions")
        if not versions or not isinstance(versions, list) or len(versions) == 0:
            raise web.HTTPNotFound(reason=f"Model {target_model_id} has no listed model versions.")

        # Find the 'best' default version (usually first published)
        default_version_summary = next((v for v in versions if v.get('status') == 'Published'), versions[0])
        target_version_id = default_version_summary.get('id')
        if not target_version_id:
            raise web.HTTPNotFound(reason=f"Model {target_model_id}'s latest version has no ID.")

        print(f"[API Helper] Using latest/default Version ID: {target_version_id}. Fetching its full details.")
        # Fetch full details for this latest version
        version_info_result = api.get_model_version_info(target_version_id)
        if not version_info_result or "error" in version_info_result:
             # Log error, but maybe try to proceed with summary data if desperate? Risky.
            err_details = version_info_result.get('details', 'Unknown error getting full version') if isinstance(version_info_result, dict) else 'Error'
            print(f"[API Helper] Warning: Could not fetch full details for latest version {target_version_id}. Details: {err_details}. Falling back to summary.")
            # Use summary data from model_info as fallback - file info might be missing!
            version_info_to_use = default_version_summary
            # Ensure minimal structure for file finding later
            version_info_to_use['files'] = version_info_to_use.get('files', [])
            version_info_to_use['images'] = version_info_to_use.get('images', [])
            version_info_to_use['modelId'] = version_info_to_use.get('modelId', target_model_id) # Ensure modelId is present
            version_info_to_use['model'] = version_info_to_use.get('model', {'name': model_info.get('name', 'Unknown')}) # Add fallback model name

        else:
            version_info_to_use = version_info_result

    # --- 5. Find Primary File from the Determined Version (version_info_to_use) ---
    print(f"[API Helper] Finding primary file for Version ID: {target_version_id}")
    files = version_info_to_use.get("files", [])
    if not isinstance(files, list): files = []

    # Handle fallback downloadUrl at version level if 'files' is empty/missing
    if not files and 'downloadUrl' in version_info_to_use and version_info_to_use['downloadUrl']:
        print("[API Helper] Warning: No 'files' array found, using version-level 'downloadUrl'.")
        files = [{
            "id": None, "name": version_info_to_use.get('name', f"version_{target_version_id}_file"),
            "primary": True, "type": "Model", "sizeKB": version_info_to_use.get('fileSizeKB'),
            "downloadUrl": version_info_to_use['downloadUrl'], "hashes": {}, "metadata": {}
        }]

    if not files:
        raise web.HTTPNotFound(reason=f"Version {target_version_id} (Name: {version_info_to_use.get('name', 'N/A')}) has no files listed.")

    # Use the centralized helper to select the best file
    primary_file = select_primary_file(files)

    if not primary_file:
        raise web.HTTPNotFound(reason=f"Could not find any usable file with a download URL for version {target_version_id}.")

    print(f"[API Helper] Selected file: Name='{primary_file.get('name', 'N/A')}', SizeKB={primary_file.get('sizeKB')}")

    # --- 6. Return Results ---
    return {
        "model_info": model_info,                  # Always the full model info
        "version_info": version_info_to_use,       # Info for the specific/latest version
        "primary_file": primary_file,              # The file from that version
        "target_model_id": target_model_id,        # Resolved model ID
        "target_version_id": target_version_id,    # Resolved version ID (specific or latest)
    }