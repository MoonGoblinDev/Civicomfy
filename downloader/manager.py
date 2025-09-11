# ================================================
# File: downloader/manager.py
# ================================================
import threading
import time
import datetime
import os
import json                     
import requests
import subprocess
import platform
import sys
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .chunk_downloader import ChunkDownloader

from ..config import (
    MAX_CONCURRENT_DOWNLOADS, DOWNLOAD_HISTORY_LIMIT, DEFAULT_CONNECTIONS,
    METADATA_SUFFIX, PREVIEW_SUFFIX, METADATA_DOWNLOAD_TIMEOUT, PLUGIN_ROOT 
)
try:
    from folder_paths import get_directory_by_type, get_valid_path, base_path
    COMFY_PATHS_AVAILABLE = True
except ImportError:
    print("[Civicomfy Manager] Warning: ComfyUI folder_paths not available. Path validation/opening might be limited.")
    COMFY_PATHS_AVAILABLE = False
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# --- Define History File Path ---
# Place it in the root of the extension directory
HISTORY_FILE_PATH = os.path.join(PLUGIN_ROOT, "download_history.json")

class DownloadManager:
    """Manages a queue of downloads, running them concurrently and saving metadata."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_DOWNLOADS):
        self.queue: List[Dict[str, Any]] = []
        self.active_downloads: Dict[str, Dict[str, Any]] = {} # {download_id: download_info}
        # History now stores more complete dictionaries for retry functionality
        self.history: List[Dict[str, Any]] = []
        self.lock: threading.Lock = threading.Lock()
        self.max_concurrent: int = max(1, max_concurrent)
        self.running: bool = True
        self._load_history_from_file()
        self._process_thread: threading.Thread = threading.Thread(target=self._process_queue, daemon=True)
        print(f"Civitai Download Manager starting (Max Concurrent: {self.max_concurrent}).")
        self._process_thread.start()

    # --- add_to_queue remains largely the same, ensuring all necessary fields are initialized ---
    def add_to_queue(self, download_info: Dict[str, Any]) -> str:
        """Adds a download task to the queue."""
        with self.lock:
            # Generate a unique ID
            timestamp = int(time.time() * 1000)
            file_hint = os.path.basename(download_info.get('output_path', 'file'))[:10]
            unique_num = sum(1 for item in self.queue if file_hint in item.get("id", "") or any(file_hint in h.get("id","") for h in self.history)) # Check history too
            download_id = f"dl_{timestamp}_{unique_num}_{file_hint}"

            # Set initial status and info
            download_info["id"] = download_id
            download_info["status"] = "queued"
            download_info["added_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            download_info["progress"] = 0
            download_info["speed"] = 0
            download_info["error"] = None
            download_info["start_time"] = None
            download_info["end_time"] = None
            download_info["connection_type"] = "N/A"

            # --- Ensure all fields potentially needed for retry exist ---
            # (Most were likely already filled by the calling route, but double-check)
            required_for_retry = [
                'url', 'output_path', 'num_connections', 'api_key', 'known_size',
                'civitai_model_info', 'civitai_version_info', 'civitai_primary_file',
                'thumbnail', 'filename', 'model_url_or_id', 'model_version_id', 'model_type',
                'custom_filename', 'force_redownload' # Add force_redownload too
            ]
            for key in required_for_retry:
                if key not in download_info:
                    # Add default or None if missing. More robust handling might be needed
                    # depending on how routes.py prepares the dict.
                    if key in ['civitai_model_info', 'civitai_version_info', 'civitai_primary_file']:
                        download_info[key] = {}
                    elif key == 'num_connections':
                        download_info[key] = DEFAULT_CONNECTIONS
                    elif key == 'force_redownload':
                        download_info[key] = False # Default for new downloads
                    else:
                        download_info[key] = None
                    print(f"[Manager Warning] Queued item '{download_id}' missing '{key}', added default.")

            self.queue.append(download_info)
            print(f"[Manager] Queued: {download_info.get('filename', 'N/A')} (ID: {download_id}, Size: {download_info.get('known_size', 'Unknown')})")
            return download_id

    # --- cancel_download remains the same ---
    def cancel_download(self, download_id: str) -> bool:
        """Requests cancellation of a queued or active download."""
        # ... (no changes needed here) ...
        print(f"[Manager] Received cancellation request for: {download_id}") # Moved print earlier
        downloader_to_cancel: Optional['ChunkDownloader'] = None
        found_in_active = False

        with self.lock:
            # 1. Check queue first (can be fully handled under lock)
            for i, item in enumerate(self.queue):
                if item["id"] == download_id:
                    cancelled_info = self.queue.pop(i)
                    cancelled_info["status"] = "cancelled"
                    cancelled_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    cancelled_info["error"] = "Cancelled from queue"
                    self._add_to_history(cancelled_info) # _add_to_history is safe under lock
                    print(f"[Manager] Cancelled queued download: {download_id}")
                    return True # Cancelled from queue, we are done

            # 2. Check active downloads - Find the instance *under lock*
            if download_id in self.active_downloads:
                found_in_active = True
                active_info = self.active_downloads[download_id]
                downloader_to_cancel = active_info.get("downloader_instance")
                current_status = active_info.get("status")

                # If downloader instance doesn't exist yet (status 'starting')
                # or if already terminal, handle it here under lock
                if not downloader_to_cancel and current_status == "starting":
                    print(f"[Manager] Marking 'starting' download as cancelled: {download_id}")
                    # Mark as cancelled, it won't start or will be caught by wrapper
                    active_info["status"] = "cancelled"
                    if not active_info.get("end_time"):
                        active_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    active_info["error"] = "Cancelled before download thread fully started"
                    # Don't assign downloader_to_cancel, let process_queue clean it up
                    downloader_to_cancel = None # Explicitly clear
                    # Indicate we handled it (or attempted to)
                    return True # Exit, processed within lock
                elif current_status in ["completed", "failed", "cancelled"]:
                    print(f"[Manager] Download {download_id} is already in terminal state '{current_status}'. Cannot cancel.")
                    # Indicate we don't need to proceed further outside the lock
                    downloader_to_cancel = None # Explicitly clear
                    return False # Already finished/cancelled

                # If we found an instance and it's potentially running,
                # store it to call cancel *after* releasing the lock.
                print(f"[Manager] Found active downloader instance for {download_id}. Will signal outside lock.")

            # Lock is released automatically here when exiting 'with'

        # 3. Signal the downloader instance *outside* the lock
        if downloader_to_cancel:
            try:
                # Check if already cancelled (to avoid duplicate logs/actions) - This check is thread-safe
                if not downloader_to_cancel.is_cancelled:
                    print(f"[Manager] Calling downloader.cancel() for {download_id}")
                    downloader_to_cancel.cancel() # This can now call _update_download_status safely
                    print(f"[Manager] Signalled downloader.cancel() for {download_id}")
                    # Let the download thread's final status update handle moving to history
                    return True # Signal sent
                else:
                    print(f"[Manager] Active download {download_id} was already cancelling.")
                    return True # Already in cancelling state is considered a success here
            except Exception as e:
                print(f"[Manager] Error calling downloader.cancel() for {download_id}: {e}")
                # Update status to failed maybe? Or just log.
                # Use _update_download_status directly here as we are outside the lock
                self._update_download_status(download_id, status="failed", error=f"Error during cancel signaling: {e}")
                return False # Failed to signal

        # 4. Handle cases where it wasn't in queue and wasn't running/starting
        if not found_in_active:
            print(f"[Manager] Could not cancel - ID not found in queue or active: {download_id}")
            return False # Not found

        # It was found in active but was already terminal or couldn't be signalled
        # Return value determined above
        return False # Should have returned True earlier if successful

    # --- get_status remains the same (still strips data for UI) ---
    def get_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Returns the current state of the queue, active downloads, and history.
           Strips sensitive/large data for UI efficiency."""
        with self.lock:
            # Fields to exclude when sending status to UI
            exclude_fields_for_ui = [
                'downloader_instance', 'civitai_model_info', 'civitai_version_info',
                'api_key', # Don't send API key to frontend status
                # Large potentially redundant fields:
                'url', 'output_path', 'custom_filename', 'model_url_or_id',
                # Keep 'thumbnail', 'filename', 'model_name', 'version_name' etc for display
            ]

            # Prepare active downloads list
            active_list = [
                {k: v for k, v in item_data.items() if k not in exclude_fields_for_ui}
                for item_id, item_data in self.active_downloads.items()
            ]

            # Prepare history list similarly
            history_list = [
                {k: v for k, v in item_data.items() if k not in exclude_fields_for_ui}
                for item_data in self.history[:DOWNLOAD_HISTORY_LIMIT]
            ]

            # Return copies
            return {
                "queue": [
                    {k:v for k,v in item.items() if k not in exclude_fields_for_ui}
                    for item in self.queue
                ],
                "active": active_list,
                "history": history_list,
            }

    def _load_history_from_file(self):
        """Loads download history from the JSON file."""
        # No lock needed here as it's called during __init__ before the thread starts
        if not os.path.exists(HISTORY_FILE_PATH):
            print(f"[Manager] History file not found ({HISTORY_FILE_PATH}). Starting with empty history.")
            self.history = []
            return

        try:
            with open(HISTORY_FILE_PATH, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)

            if isinstance(loaded_data, list):
                # Basic validation: Ensure items have IDs (optional but good)
                validated_history = [item for item in loaded_data if isinstance(item, dict) and 'id' in item]
                invalid_count = len(loaded_data) - len(validated_history)
                if invalid_count > 0:
                    print(f"[Manager Warning] {invalid_count} items removed from loaded history due to missing 'id'.")

                # Ensure history limit
                self.history = validated_history[:DOWNLOAD_HISTORY_LIMIT]
                print(f"[Manager] Successfully loaded {len(self.history)} items from {HISTORY_FILE_PATH}.")
            else:
                print(f"[Manager Warning] History file ({HISTORY_FILE_PATH}) contained invalid data (not a list). Starting fresh.")
                self.history = []
                # Optionally try to delete the corrupted file?
                # try: os.remove(HISTORY_FILE_PATH) except Exception: pass

        except json.JSONDecodeError as e:
             print(f"[Manager Error] Failed to parse history file ({HISTORY_FILE_PATH}): {e}. Starting fresh.")
             self.history = []
             # Optionally try to delete the corrupted file?
        except Exception as e:
            print(f"[Manager Error] Failed to read history file ({HISTORY_FILE_PATH}): {e}. Starting fresh.")
            self.history = []

    # --- Save History Method ---
    def _save_history_to_file(self):
        """Saves the current in-memory history list to the JSON file."""
        # Assumes self.lock is HELD when this is called
        history_to_save = self.history[:DOWNLOAD_HISTORY_LIMIT] # Ensure limit before saving

        try:
            # Ensure directory exists (should already, but belt-and-suspenders)
            os.makedirs(os.path.dirname(HISTORY_FILE_PATH), exist_ok=True)

            # Write atomically (write to temp then rename) to reduce corruption risk
            temp_file_path = HISTORY_FILE_PATH + ".tmp"
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(history_to_save, f, indent=2, ensure_ascii=False) # Pretty print

            os.replace(temp_file_path, HISTORY_FILE_PATH) # Atomic rename/replace
            # print(f"[Manager] Saved {len(history_to_save)} items to history file.") # Can be noisy

        except Exception as e:
             # Log error, but don't crash the manager
             print(f"[Manager Error] Failed to save history file ({HISTORY_FILE_PATH}): {e}")
             # Attempt to remove temp file if it exists
             if os.path.exists(temp_file_path):
                  try: os.remove(temp_file_path)
                  except Exception: pass

    # --- Updated _add_to_history Method ---
    def _add_to_history(self, download_info: Dict[str, Any]):
        """Adds a completed/failed/cancelled item to history (internal).
           Stores most original parameters needed for potential retry.
           NOW ALSO TRIGGERS SAVING HISTORY TO FILE."""
        # --- (Keep existing logic to prepare info_copy) ---
        info_copy = {
            k: v for k, v in download_info.items()
            if k not in ['downloader_instance']
        }
        if "end_time" not in info_copy or info_copy["end_time"] is None:
             info_copy["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if "status" not in info_copy:
             info_copy["status"] = "unknown"
        if info_copy["status"] != "completed" and not info_copy.get("error"):
            info_copy["error"] = f"Finished with status '{info_copy['status']}' but no error recorded."

        # --- Update in-memory history ---
        self.history.insert(0, info_copy) # Prepend
        # Trim in-memory list (save will also respect limit)
        if len(self.history) > DOWNLOAD_HISTORY_LIMIT:
            self.history = self.history[:DOWNLOAD_HISTORY_LIMIT]

        # --- Trigger Save to File (still under lock) ---
        self._save_history_to_file() # <--- Added call

    # --- Updated clear_history Method ---
    def clear_history(self) -> Dict[str, Any]:
        """Clears the download history (in-memory and the JSON file)."""
        cleared_count = 0
        file_deleted = False
        error_msg = None

        try:
            with self.lock:
                cleared_count = len(self.history)
                if cleared_count > 0:
                    print(f"[Manager] Clearing {cleared_count} items from in-memory history.")
                    self.history = [] # Clear memory list first

                    # Attempt to delete the history file
                    if os.path.exists(HISTORY_FILE_PATH):
                        try:
                            os.remove(HISTORY_FILE_PATH)
                            file_deleted = True
                            print(f"[Manager] Deleted history file: {HISTORY_FILE_PATH}")
                        except OSError as e:
                            error_msg = f"Failed to delete history file {HISTORY_FILE_PATH}: {e}"
                            print(f"[Manager Error] {error_msg}")
                    else:
                        print(f"[Manager] History file ({HISTORY_FILE_PATH}) did not exist, nothing to delete.")
                        file_deleted = True # Consider success if file wasn't there anyway

                else:
                    print("[Manager] History clear request received, but history was already empty.")
                    # Should we still check/delete the file just in case? Yes.
                    if os.path.exists(HISTORY_FILE_PATH):
                        try:
                            os.remove(HISTORY_FILE_PATH)
                            file_deleted = True
                            print(f"[Manager] Deleted potentially orphaned history file: {HISTORY_FILE_PATH}")
                        except OSError as e:
                             error_msg = f"Failed to delete potentially orphaned history file {HISTORY_FILE_PATH}: {e}"
                             print(f"[Manager Error] {error_msg}")
                    else:
                        file_deleted = True # Success if clear requested and neither memory/file had anything

            if error_msg:
                 return {"success": False, "error": f"History cleared from memory, but could not delete file: {error_msg}"}
            elif cleared_count > 0:
                 return {"success": True, "message": f"Cleared {cleared_count} history items (memory and file)."}
            else:
                 # If count was 0 but file deletion was attempted/succeeded
                 return {"success": True, "message": "History was already empty."}

        except Exception as e:
            print(f"[Manager] Critical error during clear_history: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"Failed to clear history due to unexpected error: {e}"}
        
    # --- _process_queue remains the same ---
    def _process_queue(self):
        """Internal thread function to manage downloads."""
        # ... (no changes needed here) ...
        print("[Manager] Process queue thread started.")
        while self.running:
            processed_something = False
            with self.lock:
                # 1. Check for finished/failed/cancelled active downloads to move to history
                finished_ids = [
                    dl_id for dl_id, info in self.active_downloads.items()
                    if info.get("status") in ["completed", "failed", "cancelled"] # Use .get() for safety
                ]
                for dl_id in finished_ids:
                    # Check if still in active_downloads before popping (might have been removed by another thread edge case?)
                    if dl_id in self.active_downloads:
                        finished_info = self.active_downloads.pop(dl_id)
                        self._add_to_history(finished_info) # Will now store more data
                        print(f"[Manager] Moved '{finished_info.get('filename', dl_id)}' to history (Status: {finished_info['status']})")
                        processed_something = True
                    else:
                         print(f"[Manager] Warning: Item {dl_id} intended for history was already removed from active list.")

                # 2. Start new downloads if slots available and queue has items
                while len(self.active_downloads) < self.max_concurrent and self.queue:
                    download_info = self.queue.pop(0)
                    download_id = download_info["id"]

                     # Double check if cancelled just before starting
                    if download_info["status"] == "cancelled":
                        # Ensure it has an end time before adding to history
                        if not download_info.get("end_time"):
                             download_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        self._add_to_history(download_info)
                        print(f"[Manager] Skipping cancelled item from queue: {download_id}")
                        processed_something = True
                        continue

                    # Update status to 'starting'
                    download_info["status"] = "starting"
                    download_info["start_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    download_info["downloader_instance"] = None # Placeholder

                    # Add to active downloads BEFORE starting thread
                    self.active_downloads[download_id] = download_info

                    # Start download in a separate thread
                    thread = threading.Thread(
                        target=self._download_file_wrapper,
                        args=(download_info,),
                        daemon=True # Ensure thread exits if main program exits
                    )
                    thread.start()
                    print(f"[Manager] Starting download thread for: {download_info.get('filename', 'N/A')} ({download_id})")
                    processed_something = True

            # Sleep only if nothing was processed to avoid busy-waiting
            if not processed_something:
                time.sleep(0.5) # Small delay before checking again

        print("[Manager] Process queue thread stopped.")

   # --- _update_download_status remains the same ---
    def _update_download_status(self, download_id: str, status: Optional[str] = None,
                                progress: Optional[float] = None, speed: Optional[float] = None,
                                error: Optional[str] = None, connection_type: Optional[str] = None):
        """Safely updates the status fields of an active download (thread-safe)."""
        # ... (no changes needed here) ...
        with self.lock:
            if download_id in self.active_downloads:
                item = self.active_downloads[download_id]
                updated = False # Track if any field was actually updated
                # Only update if value is provided
                if status is not None and item.get("status") != status:
                    item["status"] = status
                    updated = True
                    # If status becomes terminal, record end time
                    if status in ["completed", "failed", "cancelled"] and not item.get("end_time"):
                        item["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if progress is not None:
                    # Clamp progress between 0 and 100
                    clamped_progress = max(0.0, min(100.0, progress))
                    # Only update if different enough to avoid excessive updates
                    if abs(item.get("progress", 0) - clamped_progress) > 0.01:
                         item["progress"] = clamped_progress
                         updated = True
                if speed is not None:
                    clamped_speed = max(0.0, speed) # Speed cannot be negative
                    if item.get("speed") != clamped_speed: # Update if different
                         item["speed"] = clamped_speed
                         updated = True
                if error is not None and item.get("error") != error:
                    # Update error only if it's new or different
                    item["error"] = str(error)[:500] # Limit length
                    updated = True
                if connection_type is not None and connection_type != "N/A" and item.get("connection_type") != connection_type: # Only update if not N/A and different
                    item["connection_type"] = connection_type
                    updated = True

    # --- _save_civitai_metadata remains the same ---
    def _save_civitai_metadata(self, download_info: Dict[str, Any]):
        """Saves the .cminfo.json file."""
        # ... (no changes needed here) ...
        output_path = download_info.get('output_path')
        model_info = download_info.get('civitai_model_info', {})
        version_info = download_info.get('civitai_version_info', {})
        primary_file = download_info.get('civitai_primary_file', {})
        download_id = download_info.get('id', 'unknown')

        try:
            file_meta = primary_file.get('metadata', {}) or {} # Ensure dict
            creator_info = model_info.get('creator', {}) or {}
            model_stats = model_info.get('stats', {}) or {}
            version_stats = version_info.get('stats', {}) or {}

            metadata = {
                "ModelId": model_info.get('id', version_info.get('modelId')) , # Use .get() on version info too
                "ModelName": model_info.get('name', version_info.get('model',{}).get('name')), # Nested .get()
                "ModelDescription": model_info.get('description'),
                "CreatorUsername": creator_info.get('username'),
                "Nsfw": model_info.get('nsfw', version_info.get('model',{}).get('nsfw')),
                "Poi": model_info.get('poi', version_info.get('model',{}).get('poi')),
                "AllowNoCredit": model_info.get('allowNoCredit', True),
                "AllowCommercialUse": str(model_info.get('allowCommercialUse', 'Unknown')), # Ensure string
                "AllowDerivatives": model_info.get('allowDerivatives', True),
                "AllowDifferentLicense": model_info.get('allowDifferentLicense', True),
                "Tags": model_info.get('tags', []),
                "ModelType": model_info.get('type'),
                "VersionId": version_info.get('id'),
                "VersionName": version_info.get('name'),
                "VersionDescription": version_info.get('description'),
                "BaseModel": version_info.get('baseModel'),
                "BaseModelType": version_info.get('baseModelType'),
                "EarlyAccessDeadline": version_info.get('earlyAccessDeadline'),
                "VersionPublishedAt": version_info.get('publishedAt'),
                "VersionUpdatedAt": version_info.get('updatedAt'),
                "VersionStatus": version_info.get('status'),
                "IsPrimaryFile": primary_file.get('primary', False),
                "PrimaryFileId": primary_file.get('id'),
                "PrimaryFileName": primary_file.get('name'),
                "FileMetadata": {
                    "fp": file_meta.get('fp'),
                    "size": file_meta.get('size'),
                    "format": file_meta.get('format', 'Unknown')
                },
                "ImportedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "Hashes": primary_file.get('hashes', {}),
                "TrainedWords": version_info.get('trainedWords', []),
                "Stats": {
                    "downloadCount": version_stats.get('downloadCount', model_stats.get('downloadCount', 0)),
                    "rating": version_stats.get('rating', model_stats.get('rating', 0)),
                    "ratingCount": version_stats.get('ratingCount', model_stats.get('ratingCount', 0)),
                    "favoriteCount": version_stats.get('favoriteCount', model_stats.get('favoriteCount', 0)), # Correct source needed? Check API docs
                    "commentCount": version_stats.get('commentCount', model_stats.get('commentCount', 0)), # Correct source needed? Check API docs
                    "thumbsUpCount": version_stats.get('thumbsUpCount', 0),
                 },
                 "DownloadUrlUsed": download_info.get('url'),
            }

            base, _ = os.path.splitext(output_path)
            meta_filename = base + METADATA_SUFFIX
            meta_path = os.path.join(os.path.dirname(output_path), meta_filename)

            print(f"[Manager Meta {download_id}] Saving metadata to: {meta_path}")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"[Manager Meta {download_id}] Metadata saved successfully.")

        except Exception as e:
            import traceback
            print(f"[Manager Meta {download_id}] Error saving metadata file {meta_path}: {e}")
            # traceback.print_exc() # Uncomment for full trace

    # --- _download_and_save_preview remains the same ---
    def _download_and_save_preview(self, download_info: Dict[str, Any]):
        """Downloads and saves the .preview.jpeg file."""
        # ... (no changes needed here) ...
        output_path = download_info.get('output_path')
        thumbnail_url = download_info.get('thumbnail')
        api_key = download_info.get('api_key')
        download_id = download_info.get('id', 'unknown')

        if not output_path:
             print(f"[Manager Preview {download_id}] Skipping preview download: Missing output path.")
             return
        if not thumbnail_url:
             print(f"[Manager Preview {download_id}] Skipping preview download: No thumbnail URL provided.")
            # Optionally try to find one in version_info images again? Might be redundant.
             version_info = download_info.get('civitai_version_info', {})
             if version_info and isinstance(version_info.get('images'), list) and version_info['images']:
                  sorted_images = sorted([img for img in version_info['images'] if img and img.get("url")], key=lambda x: x.get('index', 0))
                  img_data = next((img for img in sorted_images if img.get("type") == "image" and "/width=" in img.get("url","")), None) # Prefer image type with width param
                  if not img_data: img_data = next((img for img in sorted_images if img.get("type") == "image"), None) # Fallback to any image type
                  if not img_data: img_data = next((img for img in sorted_images), None) # Fallback to any image at all
                  if img_data and img_data.get('url'):
                       thumbnail_url = img_data['url']
                       # Attempt to get a reasonable size (e.g. ~450px width)
                       if "/width=" in thumbnail_url:
                            thumbnail_url = thumbnail_url.split("/width=")[0] + "/width=450"
                       elif "/blob/" not in thumbnail_url: # Avoid adding params to blob URLs
                           separator = "&" if "?" in thumbnail_url else "?"
                           thumbnail_url += f"{separator}width=450"
                       print(f"[Manager Preview {download_id}] Found alternative thumbnail URL: {thumbnail_url}")
                  else:
                      print(f"[Manager Preview {download_id}] Still no thumbnail URL found in version info.")
                      return # Exit if still no URL
             else:
                 return # Exit if no URL and no version info to search

        base, _ = os.path.splitext(output_path)
        preview_filename = base + PREVIEW_SUFFIX
        preview_path = os.path.join(os.path.dirname(output_path), preview_filename)

        print(f"[Manager Preview {download_id}] Downloading thumbnail from {thumbnail_url} to {preview_path}")
        response = None
        try:
            headers = {}
            if api_key: headers["Authorization"] = f"Bearer {api_key}"
            response = requests.get(thumbnail_url, stream=True, headers=headers, timeout=METADATA_DOWNLOAD_TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                 print(f"[Manager Preview {download_id}] Warning: Thumbnail URL returned non-image content type '{content_type}'. Skipping save.")
                 return
            with open(preview_path, 'wb') as f:
                 for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
            print(f"[Manager Preview {download_id}] Thumbnail downloaded successfully.")
        except requests.exceptions.RequestException as e:
             error_msg = f"Error downloading thumbnail {thumbnail_url}: {e}"
             if hasattr(e, 'response') and e.response is not None: error_msg += f" (Status: {e.response.status_code})"
             print(f"[Manager Preview {download_id}] {error_msg}")
        except Exception as e: print(f"[Manager Preview {download_id}] Error saving thumbnail {preview_path}: {e}")
        finally:
            if response: response.close()

    # --- _download_file_wrapper remains the same ---
    def _download_file_wrapper(self, download_info: Dict[str, Any]):
        """Wraps the download execution, handles status updates, exceptions, and metadata saving."""
        # ... (no changes needed here) ...
        download_id = download_info["id"]
        filename = download_info.get('filename', download_id)
        from .chunk_downloader import ChunkDownloader
        downloader = None
        success = False
        final_status = "failed"
        error_msg = None

        try:
            print(f"[Downloader Wrapper {download_id}] Preparing download for '{filename}'.")
            downloader = ChunkDownloader(
                url=download_info["url"],
                output_path=download_info["output_path"],
                num_connections=download_info.get("num_connections", DEFAULT_CONNECTIONS),
                manager=self,
                download_id=download_id,
                api_key=download_info.get("api_key"),
                known_size=download_info.get("known_size")
            )

            with self.lock:
                  if download_id not in self.active_downloads or self.active_downloads[download_id]["status"] == "cancelled":
                       print(f"[Downloader Wrapper {download_id}] Download was cancelled before instance could be fully linked/started.")
                       self._update_download_status(download_id, status="cancelled", error="Cancelled before start")
                       return

                  self.active_downloads[download_id]["downloader_instance"] = downloader

            self._update_download_status(download_id, status="downloading")
            print(f"[Downloader Wrapper {download_id}] Starting download process for '{filename}'.")
            success = downloader.download() # Blocking call

            error_msg = downloader.error

            if success:
                final_status = "completed"
                print(f"[Downloader Wrapper {download_id}] Download completed successfully for '{filename}'.")
                try:
                    self._save_civitai_metadata(download_info)
                    self._download_and_save_preview(download_info)
                except Exception as meta_err:
                     print(f"[Downloader Wrapper {download_id}] Error during post-download metadata/preview saving: {meta_err}")

            elif downloader.is_cancelled:
                final_status = "cancelled"
                error_msg = downloader.error or "Download cancelled"
                print(f"[Downloader Wrapper {download_id}] Download cancelled for '{filename}'. Reason: {error_msg}")
            else:
                final_status = "failed"
                error_msg = downloader.error or "Download failed with unknown error"
                print(f"[Downloader Wrapper {download_id}] Download failed for '{filename}'. Error: {error_msg}")

        except Exception as e:
            import traceback
            print(f"--- Critical Error in Download Wrapper {download_id} ('{filename}') ---")
            traceback.print_exc()
            print("--- End Error ---")
            final_status = "failed"
            error_msg = f"Unexpected wrapper error: {str(e)}"
            if downloader and not downloader.is_cancelled:
                try: downloader.cancel()
                except: pass

        finally:
            final_progress_percent = 0
            conn_type = download_info.get("connection_type", "N/A")

            if downloader:
                 conn_type = downloader.connection_type
                 if downloader.total_size and downloader.total_size > 0:
                      final_progress_percent = (downloader.downloaded / downloader.total_size * 100)
                 if final_status == "completed": final_progress_percent = 100.0
                 final_progress_percent = min(100.0, max(0.0, final_progress_percent))

            print(f"[Downloader Wrapper {download_id}] Finalizing status: {final_status}, Error: {error_msg}")
            self._update_download_status(
                download_id, status=final_status, progress=final_progress_percent,
                speed=0, error=error_msg, connection_type=conn_type
            )
            if final_status == "completed":
                 print(f"[Manager] Download {download_id} completed ('{filename}'). Manual ComfyUI refresh may be needed for model list.")

    # --- NEW: Retry Download Method ---
    def retry_download(self, original_download_id: str) -> Dict[str, Any]:
        """Finds a failed/cancelled download in history and re-queues it."""
        with self.lock:
            # Find the original download info in history
            original_info = next((item for item in self.history if item.get("id") == original_download_id), None)

            if not original_info:
                return {"success": False, "error": f"Original download ID '{original_download_id}' not found in history."}

            original_status = original_info.get("status")
            if original_status not in ["failed", "cancelled"]:
                return {"success": False, "error": f"Cannot retry download with status '{original_status}'. Only 'failed' or 'cancelled' are retryable."}

            # --- Prepare the new download info dictionary ---
            # Make a deep copy to avoid modifying the history item directly
            try:
                retry_info = json.loads(json.dumps(original_info))
                print(retry_info)
            except Exception as e:
                 return {"success": False, "error": f"Failed to copy original download data: {e}"}

            # Remove fields specific to the *previous* attempt
            retry_info.pop("id", None) # Will get a new ID
            retry_info.pop("status", None)
            retry_info.pop("progress", None)
            retry_info.pop("speed", None)
            retry_info.pop("error", None)
            retry_info.pop("start_time", None)
            retry_info.pop("end_time", None)
            retry_info.pop("added_time", None)
            retry_info.pop("connection_type", None)
            retry_info.pop("downloader_instance", None) 
            # --- Crucially: Set force_redownload to True for retry ---
            # This ensures it overwrites the potentially corrupted/partial file from the previous attempt.
            retry_info["force_redownload"] = True

            # --- Validate required fields for queuing (redundant check, but safe) ---
            required_for_retry = [
                'url', 'output_path', 'num_connections', 'api_key', 'known_size',
                'civitai_model_info', 'civitai_version_info', 'civitai_primary_file',
                'thumbnail', 'filename', 'model_url_or_id', 'model_version_id', 'model_type',
                'custom_filename', 'force_redownload'
            ]
            missing_keys = [key for key in required_for_retry if key not in retry_info or retry_info[key] is None and key != 'api_key' and key != 'custom_filename'] # Allow api_key/custom_filename to be None
            #if missing_keys:
            #    return {"success": False, "error": f"Cannot retry: Original download data is missing required fields: {', '.join(missing_keys)}"}

        # --- Add the prepared info to the queue (outside the lock for add_to_queue's own lock) ---
        # Note: add_to_queue acquires its own lock internally
        try:
            new_download_id = self.add_to_queue(retry_info)
            if new_download_id: # Check if add_to_queue returned a valid ID (indicating success)
                with self.lock:
                    original_len = len(self.history)
                    # Filter out the item matching the original ID
                    self.history = [item for item in self.history if item.get("id") != original_download_id]
                    items_removed = original_len - len(self.history)

                    if items_removed == 1:
                        print(f"[Manager] Successfully removed original download '{original_download_id}' from history.")
                        return {
                            "success": True,
                            "message": f"Retry initiated. New download queued. Original removed from history.",
                            "new_download_id": new_download_id
                        }

            else:
                # Should have been caught by the except block, but as a failsafe
                print(f"[Manager] Retry queueing failed for '{original_download_id}' for an unknown reason (no ID returned).")
                return {"success": False, "error": "Failed to queue retry (unknown internal error)."}
        
        except Exception as e:
             print(f"[Manager] Error requeuing download for retry (Original ID: {original_download_id}): {e}")
             return {"success": False, "error": f"Failed to queue retry: {e}"}

    # --- NEW: Open Containing Folder Method ---
    def open_containing_folder(self, download_id: str) -> Dict[str, Any]:
        """Opens the directory containing the specified completed download file."""
        file_path = None
        with self.lock:
            # Check history first (most likely location for completed items)
            item_info = next((item for item in self.history if item.get("id") == download_id), None)
            # Fallback to active (less likely, but possible if called very quickly after completion)
            if not item_info and download_id in self.active_downloads:
                 item_info = self.active_downloads.get(download_id)

            if not item_info:
                 return {"success": False, "error": "Download ID not found."}

            if item_info.get("status") != "completed":
                 return {"success": False, "error": f"Cannot open path for download with status '{item_info.get('status')}'. Must be 'completed'."}

            file_path = item_info.get("output_path") # Get the full path to the file

        # --- Perform file operations outside the lock ---
        if not file_path:
            return {"success": False, "error": "Output path not found for this download."}

        # --- Security Check: Ensure the path is within expected ComfyUI directories ---
        # (This is a basic check, might need refinement based on your setup)
        is_safe_path = False
        try:
            # Get the absolute path
            abs_file_path = os.path.abspath(file_path)
            folder_path = os.path.dirname(abs_file_path)

            # Option 1: Check against ComfyUI's known directories (preferred)
            if COMFY_PATHS_AVAILABLE:
                 # Check if the folder is within any known model type directory
                 known_types = [
                     "checkpoints", "loras", "vae", "embeddings", "hypernetworks",
                     "controlnet", "upscale_models", "clip_vision", "gligen", "configs",
                     "unet", "diffusers", "motion_models", "poses", "wildcards"
                 ]
                 known_dirs = [os.path.abspath(get_directory_by_type(t)) for t in known_types if get_directory_by_type(t)]
                 # Also allow output and input directories
                 if get_directory_by_type("output"): known_dirs.append(os.path.abspath(get_directory_by_type("output")))
                 if get_directory_by_type("input"): known_dirs.append(os.path.abspath(get_directory_by_type("input")))
                 # Add the plugin's own 'other_models' directory as safe
                 known_dirs.append(os.path.abspath(os.path.join(PLUGIN_ROOT, "other_models")))
                 # Add plugin-managed custom roots as safe
                 try:
                     import json as _json
                     _roots_file = os.path.join(PLUGIN_ROOT, "custom_roots.json")
                     if os.path.exists(_roots_file):
                         with open(_roots_file, 'r', encoding='utf-8') as _f:
                             _data = _json.load(_f)
                             if isinstance(_data, dict):
                                 for _lst in _data.values():
                                     if isinstance(_lst, list):
                                         for _p in _lst:
                                             if isinstance(_p, str):
                                                 known_dirs.append(os.path.abspath(_p))
                 except Exception as _e:
                     print(f"[Manager OpenPath] Warning: Failed to load custom roots: {_e}")
                 # Include all first-level subdirectories under models_dir as safe
                 try:
                     models_dir = getattr(__import__('folder_paths'), 'folder_paths').models_dir
                 except Exception:
                     models_dir = None
                 try:
                     if models_dir and os.path.isdir(models_dir):
                         for _name in os.listdir(models_dir):
                             _p = os.path.join(models_dir, _name)
                             if os.path.isdir(_p):
                                 known_dirs.append(os.path.abspath(_p))
                 except Exception as _e2:
                     print(f"[Manager OpenPath] Warning: Failed enumerating models_dir subfolders: {_e2}")

                 for known_dir in known_dirs:
                      if os.path.commonpath([known_dir, folder_path]) == known_dir:
                           is_safe_path = True
                           break
            else:
                 # Option 2: Fallback - Check if path is within the ComfyUI base directory
                 comfy_base = os.path.abspath(base_path)
                 if os.path.commonpath([comfy_base, folder_path]) == comfy_base:
                      is_safe_path = True
                      #print(f"[Manager OpenPath Warning] ComfyUI paths unavailable. Using base path check for {folder_path}")

            if not is_safe_path:
                  print(f"[Manager OpenPath Denied] Path '{folder_path}' is outside known safe ComfyUI directories.")
                  return {"success": False, "error": "Cannot open path: Directory is outside allowed locations."}

            # --- Open the directory ---
            if not os.path.exists(folder_path):
                 return {"success": False, "error": f"Directory does not exist: {folder_path}"}
            if not os.path.isdir(folder_path):
                 return {"success": False, "error": f"Path is not a directory: {folder_path}"}

            try:
                 system = platform.system()
                 print(f"[Manager OpenPath] Attempting to open folder '{folder_path}' on {system}...")
                 if system == "Windows":
                      # Use startfile for better handling of spaces etc.
                      os.startfile(folder_path)
                 elif system == "Darwin": # macOS
                      subprocess.check_call(["open", folder_path])
                 elif system == "Linux":
                      # Use xdg-open, handle potential errors if command not found
                      try:
                            subprocess.check_call(["xdg-open", folder_path])
                      except FileNotFoundError:
                            # Fallback for headless systems or if xdg-open isn't installed
                           print(f"[Manager OpenPath] 'xdg-open' not found. Cannot automatically open folder on this Linux system.")
                           return {"success": False, "error": "'xdg-open' command not found. Cannot open folder."}
                 else:
                      print(f"[Manager OpenPath] Unsupported operating system: {system}. Cannot open folder.")
                      return {"success": False, "error": f"Unsupported OS ({system}) for opening folder."}

                 print(f"[Manager OpenPath] Successfully requested folder opening for '{folder_path}'.")
                 return {"success": True, "message": f"Opened directory: {folder_path}"}

            except Exception as e:
                 print(f"[Manager OpenPath] Failed to open directory '{folder_path}': {e}")
                 return {"success": False, "error": f"Failed to open directory: {e}"}

        except Exception as path_err:
            # Catch errors during path validation itself
            print(f"[Manager OpenPath] Error during path validation/retrieval for {download_id}: {path_err}")
            return {"success": False, "error": f"Error processing path: {path_err}"}

# --- Global Instance ---
manager = DownloadManager(max_concurrent=MAX_CONCURRENT_DOWNLOADS)

# --- Graceful Shutdown ---
# (shutdown_manager remains the same)
def shutdown_manager():
    # ... (no changes) ...
    print("[Manager] Shutdown requested.")
    if manager:
        manager.running = False
        acquired_lock = False
        try: acquired_lock = manager.lock.acquire(timeout=1.0)
        except RuntimeError: pass # Lock might not be initialised if init failed

        if acquired_lock:
             try:
                 active_ids = list(manager.active_downloads.keys())
                 queue_ids = [item['id'] for item in manager.queue]
                 print(f"[Manager] Requesting cancellation for {len(active_ids)} active and {len(queue_ids)} queued downloads on shutdown...")
                 all_ids_to_cancel = active_ids + queue_ids
                 manager.lock.release() # Release lock BEFORE calling cancel_download

                 for dl_id in all_ids_to_cancel:
                      try:
                          # Reuse cancel_download which handles both active and queued safely
                          manager.cancel_download(dl_id)
                      except Exception as e:
                           print(f"Error cancelling {dl_id} during shutdown: {e}")
             except Exception as e:
                 print(f"[Manager] Error accessing lists during shutdown (after lock acquired): {e}")
                 try: manager.lock.release() # Ensure release on error
                 except RuntimeError: pass
             # Give threads/tasks a brief moment to react
             time.sleep(0.5)
        else:
            print("[Manager] Warning: Could not acquire lock to cancel downloads during shutdown.")

        # Attempt to join the manager's process thread (best effort)
        try:
            if manager._process_thread and manager._process_thread.is_alive():
                 manager._process_thread.join(timeout=2.0)
                 if manager._process_thread.is_alive():
                      print("[Manager] Warning: Process thread did not exit cleanly within timeout.")
        except Exception as e:
            print(f"[Manager] Error joining manager thread during shutdown: {e}")
    print("[Manager] Shutdown complete.")

import atexit
atexit.register(shutdown_manager)
