# ================================================
# File: downloader/manager.py
# ================================================
import threading
import time
import datetime
import os
import json
import requests
from typing import List, Dict, Any, Optional

# Use typing for Downloader class hint to avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .chunk_downloader import ChunkDownloader

# Import config consts
from ..config import (
    MAX_CONCURRENT_DOWNLOADS, DOWNLOAD_HISTORY_LIMIT, DEFAULT_CONNECTIONS,
    METADATA_SUFFIX, PREVIEW_SUFFIX, METADATA_DOWNLOAD_TIMEOUT
)

class DownloadManager:
    """Manages a queue of downloads, running them concurrently and saving metadata."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_DOWNLOADS):
        self.queue: List[Dict[str, Any]] = []
        self.active_downloads: Dict[str, Dict[str, Any]] = {} # {download_id: download_info}
        self.history: List[Dict[str, Any]] = []
        self.lock: threading.Lock = threading.Lock()
        self.max_concurrent: int = max(1, max_concurrent)
        self.running: bool = True
        self._process_thread: threading.Thread = threading.Thread(target=self._process_queue, daemon=True)
        print(f"Civitai Download Manager starting (Max Concurrent: {self.max_concurrent}).")
        self._process_thread.start()

    def add_to_queue(self, download_info: Dict[str, Any]) -> str:
        """Adds a download task to the queue."""
        with self.lock:
            # Generate a unique ID
            timestamp = int(time.time() * 1000)
            # More robust ID generation (simple counter + filename hint)
            file_hint = os.path.basename(download_info.get('output_path', 'file'))[:10]
            unique_num = sum(1 for item in self.queue if file_hint in item.get("id", ""))
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
            download_info["connection_type"] = "N/A" # Initialize connection type

            # Ensure common optional fields exist (even if None) - simplifies access later
            if "num_connections" not in download_info:
                 download_info["num_connections"] = DEFAULT_CONNECTIONS
            if "known_size" not in download_info:
                 download_info["known_size"] = None
            if "api_key" not in download_info:
                 download_info["api_key"] = None
            if "thumbnail" not in download_info:
                 download_info["thumbnail"] = None
            # Ensure metadata dicts exist
            if "civitai_model_info" not in download_info:
                 download_info["civitai_model_info"] = {}
            if "civitai_version_info" not in download_info:
                 download_info["civitai_version_info"] = {}
            if "civitai_primary_file" not in download_info:
                 download_info["civitai_primary_file"] = {}

            self.queue.append(download_info)
            print(f"[Manager] Queued: {download_info.get('filename', 'N/A')} (ID: {download_id}, Size: {download_info.get('known_size', 'Unknown')})")
            return download_id

    def cancel_download(self, download_id: str) -> bool:
            """Requests cancellation of a queued or active download."""
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

    def get_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Returns the current state of the queue, active downloads, and history."""
        with self.lock:
            # Prepare active downloads list, excluding the downloader instance and potentially large metadata
            active_list = []
            for item_id, item_data in self.active_downloads.items():
                # Create a copy, exclude internal objects and large API data
                info_copy = {
                    k: v for k, v in item_data.items()
                    if k not in ['downloader_instance', 'civitai_model_info', 'civitai_version_info', 'civitai_primary_file']
                }
                 # Optionally add back only essential fields if needed by UI later (e.g., thumbnail)
                # info_copy['thumbnail'] = item_data.get('thumbnail') # Already done by default
                active_list.append(info_copy)

            # Prepare history list similarly
            history_list = []
            for item_data in self.history[:DOWNLOAD_HISTORY_LIMIT]:
                info_copy = {
                    k: v for k, v in item_data.items()
                    if k not in ['downloader_instance', 'civitai_model_info', 'civitai_version_info', 'civitai_primary_file']
                }
                history_list.append(info_copy)

            # Return copies to prevent external modification
            return {
                "queue": [item.copy() for item in self.queue],
                "active": active_list,
                "history": history_list # Use the filtered list
            }

    def _add_to_history(self, download_info: Dict[str, Any]):
        """Adds a completed/failed/cancelled item to history (internal)."""
        # Ensure sensitive or internal objects are removed
        info_copy = {
            k: v for k, v in download_info.items()
             if k not in ['downloader_instance', 'civitai_model_info', 'civitai_version_info', 'civitai_primary_file', 'api_key'] # Also strip API key
        }
        if "end_time" not in info_copy or info_copy["end_time"] is None:
             info_copy["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Provide default status if missing (shouldn't happen often)
        if "status" not in info_copy:
             info_copy["status"] = "unknown"

        self.history.insert(0, info_copy) # Prepend to keep newest first
        # Trim history if it exceeds the limit
        if len(self.history) > DOWNLOAD_HISTORY_LIMIT + 50: # Keep some buffer
             self.history = self.history[:DOWNLOAD_HISTORY_LIMIT]

    def _process_queue(self):
        """Internal thread function to manage downloads."""
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
                        self._add_to_history(finished_info)
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

    def _update_download_status(self, download_id: str, status: Optional[str] = None,
                                progress: Optional[float] = None, speed: Optional[float] = None,
                                error: Optional[str] = None, connection_type: Optional[str] = None): # Added connection_type
        """Safely updates the status fields of an active download (thread-safe)."""
        # Using lock here ensures atomicity when updating multiple fields from potentially different threads
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

                # Optional: Log when an update actually happens
                #print(f"DEBUG - Updated status for {download_id}: Status={status}, Progress={progress}, Speed={speed}, Conn={connection_type}, Error={error}")


    def _save_civitai_metadata(self, download_info: Dict[str, Any]):
        """Saves the .cminfo.json file."""
        output_path = download_info.get('output_path')
        model_info = download_info.get('civitai_model_info', {})
        version_info = download_info.get('civitai_version_info', {})
        primary_file = download_info.get('civitai_primary_file', {})
        download_id = download_info.get('id', 'unknown')

        #if not output_path or not model_info or not version_info:
         #   print(f"[Manager Meta {download_id}] Skipping metadata save: Missing output path or API info.")
          #  return

        try:
            # --- Construct metadata dictionary ---
            file_meta = primary_file.get('metadata', {}) or {} # Ensure dict

            # Safely get creator info
            creator_info = model_info.get('creator', {}) or {}

            # Safely get stats
            model_stats = model_info.get('stats', {}) or {}
            version_stats = version_info.get('stats', {}) or {}

            metadata = {
                "ModelId": model_info.get('id', version_info['modelId']) ,
                "ModelName": model_info.get('name', version_info['model']['name']),
                "ModelDescription": model_info.get('description'), # Can be None/null
                 "CreatorUsername": creator_info.get('username'), # Added creator username
                "Nsfw": model_info.get('nsfw', version_info['model']['nsfw']),
                "Poi": model_info.get('poi', version_info['model']['poi']), # Added PersonOfInterest flag
                "AllowNoCredit": model_info.get('allowNoCredit', True),
                "AllowCommercialUse": model_info.get('allowCommercialUse', 'Unknown'),
                "AllowDerivatives": model_info.get('allowDerivatives', True),
                "AllowDifferentLicense": model_info.get('allowDifferentLicense', True),
                "Tags": model_info.get('tags', []), # Should be list
                "ModelType": model_info.get('type'), # e.g., "LORA", "Checkpoint"
                "VersionId": version_info.get('id'),
                "VersionName": version_info.get('name'),
                "VersionDescription": version_info.get('description'), # Can be None/null
                "BaseModel": version_info.get('baseModel'), # e.g., "SD 1.5", "Pony"
                "BaseModelType": version_info.get('baseModelType'), # Added since API v2 - 'Standard','Pony' etc
                "EarlyAccessDeadline": version_info.get('earlyAccessDeadline'), # Added
                "VersionPublishedAt": version_info.get('publishedAt'), # Added publish date
                 "VersionUpdatedAt": version_info.get('updatedAt'), # Added update date
                 "VersionStatus": version_info.get('status'), # 'Published', 'Scheduled', 'Draft'
                 "IsPrimaryFile": primary_file.get('primary', False), # Added primary file flag
                 "PrimaryFileId": primary_file.get('id'), # Added primary file ID
                 "PrimaryFileName": primary_file.get('name'), # Added primary file name
                "FileMetadata": {
                    "fp": file_meta.get('fp'),
                    "size": file_meta.get('size'),
                    "format": file_meta.get('format', 'Unknown')
                },
                "ImportedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "Hashes": primary_file.get('hashes', {}), # Already an object {"SHA256": ...}
                "TrainedWords": version_info.get('trainedWords', []), # Should be list
                "Stats": { # Combine stats, prioritizing potentially more accurate version stats if available
                    "downloadCount": version_stats.get('downloadCount', model_stats.get('downloadCount', 0)),
                    "rating": version_stats.get('rating', model_stats.get('rating', 0)),
                    "ratingCount": version_stats.get('ratingCount', model_stats.get('ratingCount', 0)),
                    "favoriteCount": version_stats.get('favoriteCount', model_stats.get('favoriteCount', 0)), # Model-level has favoriteCount
                    "commentCount": version_stats.get('commentCount', model_stats.get('commentCount', 0)), # Model-level has commentCount
                    "thumbsUpCount": version_stats.get('thumbsUpCount', 0), # Only seems to be on version stats
                 },
                 "DownloadUrlUsed": download_info.get('url'), # Log the actual download URL used
                # Note: UserTitle seems specific to certain clients, not standard API. Thumbnail URL saved separately.
            }

            # --- Determine filename and path ---
            base, _ = os.path.splitext(output_path)
            meta_filename = base + METADATA_SUFFIX
            meta_path = os.path.join(os.path.dirname(output_path), meta_filename)

            # --- Write JSON file ---
            print(f"[Manager Meta {download_id}] Saving metadata to: {meta_path}")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            print(f"[Manager Meta {download_id}] Metadata saved successfully.")

        except Exception as e:
            print(f"[Manager Meta {download_id}] Error saving metadata file {meta_path}: {e}")
            # Log traceback for debugging if needed
            # import traceback
            # traceback.print_exc()

    def _download_and_save_preview(self, download_info: Dict[str, Any]):
        """Downloads and saves the .preview.jpeg file."""
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

        # --- Determine filename and path ---
        base, _ = os.path.splitext(output_path)
        preview_filename = base + PREVIEW_SUFFIX
        preview_path = os.path.join(os.path.dirname(output_path), preview_filename)

        print(f"[Manager Preview {download_id}] Downloading thumbnail from {thumbnail_url} to {preview_path}")

        response = None # Define outside try
        try:
            headers = {}
            if api_key:
                 headers["Authorization"] = f"Bearer {api_key}"

            response = requests.get(
                thumbnail_url,
                stream=True,
                headers=headers,
                timeout=METADATA_DOWNLOAD_TIMEOUT, # Use specific timeout for metadata
                allow_redirects=True
            )
            response.raise_for_status()

            # Optional: Check content type
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                 print(f"[Manager Preview {download_id}] Warning: Thumbnail URL returned non-image content type '{content_type}'. Skipping save.")
                 return

            with open(preview_path, 'wb') as f:
                 for chunk in response.iter_content(chunk_size=8192): # Read in 8KB chunks
                     if chunk:
                         f.write(chunk)

            print(f"[Manager Preview {download_id}] Thumbnail downloaded successfully.")

        except requests.exceptions.RequestException as e:
             error_msg = f"Error downloading thumbnail {thumbnail_url}: {e}"
             # Check for specific status codes if response exists
             if hasattr(e, 'response') and e.response is not None:
                  status_code = e.response.status_code
                  error_msg += f" (Status: {status_code})"
                  if status_code == 404: error_msg += " - Not Found"
                  elif status_code == 401: error_msg += " - Unauthorized?"
                  elif status_code == 403: error_msg += " - Forbidden?"
             print(f"[Manager Preview {download_id}] {error_msg}")
        except Exception as e:
            print(f"[Manager Preview {download_id}] Error saving thumbnail {preview_path}: {e}")
        finally:
            if response:
                response.close()

    def _download_file_wrapper(self, download_info: Dict[str, Any]):
        """Wraps the download execution, handles status updates, exceptions, and metadata saving."""
        download_id = download_info["id"]
        filename = download_info.get('filename', download_id)
        # Use lazy import inside thread to potentially avoid main thread import issues
        from .chunk_downloader import ChunkDownloader
        downloader = None # Define outside try
        success = False
        final_status = "failed" # Default to failed
        error_msg = None

        try:
            # --- Create downloader instance ---
            print(f"[Downloader Wrapper {download_id}] Preparing download for '{filename}'.")
            downloader = ChunkDownloader(
                url=download_info["url"],
                output_path=download_info["output_path"],
                num_connections=download_info.get("num_connections", DEFAULT_CONNECTIONS),
                manager=self,
                download_id=download_id,
                api_key=download_info.get("api_key"), # Pass API key
                known_size=download_info.get("known_size") # Pass known size
            )

            # --- Store instance reference ---
            # Check if cancelled *before* storing instance and starting download
            with self.lock:
                  if download_id not in self.active_downloads or self.active_downloads[download_id]["status"] == "cancelled":
                       print(f"[Downloader Wrapper {download_id}] Download was cancelled before instance could be fully linked/started.")
                       # Status should already be 'cancelled', just ensure history cleanup happens
                       self._update_download_status(download_id, status="cancelled", error="Cancelled before start")
                       return # Exit thread

                  self.active_downloads[download_id]["downloader_instance"] = downloader

            # --- Start Download (Blocking Call) ---
            # Update status to 'downloading'
            self._update_download_status(download_id, status="downloading")
            print(f"[Downloader Wrapper {download_id}] Starting download process for '{filename}'.")
            success = downloader.download() # THE BLOCKING CALL

            # --- Post Download ---
            error_msg = downloader.error # Get error message after download attempt

            if success:
                final_status = "completed"
                print(f"[Downloader Wrapper {download_id}] Download completed successfully for '{filename}'.")
                # --- Save Metadata and Preview on SUCCESS ---
                try:
                    self._save_civitai_metadata(download_info)
                    self._download_and_save_preview(download_info)
                except Exception as meta_err:
                     # Log error but don't fail the overall download status
                     print(f"[Downloader Wrapper {download_id}] Error during post-download metadata/preview saving: {meta_err}")
                     # Optionally append to the main error message?
                     # error_msg = (error_msg + "; " if error_msg else "") + f"Metadata/Preview Save Error: {meta_err}"

            elif downloader.is_cancelled:
                final_status = "cancelled"
                error_msg = downloader.error or "Download cancelled" # Use specific error if available
                print(f"[Downloader Wrapper {download_id}] Download cancelled for '{filename}'. Reason: {error_msg}")
            else:
                # It failed, but wasn't explicitly cancelled
                final_status = "failed"
                error_msg = downloader.error or "Download failed with unknown error" # Ensure error msg exists
                print(f"[Downloader Wrapper {download_id}] Download failed for '{filename}'. Error: {error_msg}")

        except Exception as e:
            # Catch unexpected errors during instance creation or the download call itself
            import traceback
            print(f"--- Critical Error in Download Wrapper {download_id} ('{filename}') ---")
            traceback.print_exc()
            print("--- End Error ---")
            final_status = "failed"
            error_msg = f"Unexpected wrapper error: {str(e)}"
            # If downloader exists, try to signal cancel just in case it helps cleanup
            if downloader and not downloader.is_cancelled:
                try:
                    downloader.cancel()
                except: pass # Ignore errors during cleanup cancel

        finally:
            # --- Final Status Update ---
            # The downloader itself now calls _update_download_status in its finally block,
            # so this section *mainly* ensures the final state is recorded correctly,
            # especially if errors occurred *outside* the downloader.download() call.

            # Fetch the latest progress and connection type from the downloader if it exists
            final_progress_percent = 0
            conn_type = download_info.get("connection_type", "N/A") # Default from info

            if downloader:
                 conn_type = downloader.connection_type # Get final type from downloader
                 if downloader.total_size and downloader.total_size > 0:
                      final_progress_percent = (downloader.downloaded / downloader.total_size * 100)
                 # Ensure 100% on success, regardless of tiny calculation variations
                 if final_status == "completed":
                      final_progress_percent = 100.0
                 final_progress_percent = min(100.0, max(0.0, final_progress_percent)) # Clamp 0-100

            print(f"[Downloader Wrapper {download_id}] Finalizing status: {final_status}, Error: {error_msg}")
            self._update_download_status(
                download_id,
                status=final_status,
                progress=final_progress_percent,
                speed=0, # Final speed is 0
                error=error_msg, # Use the determined error message
                connection_type=conn_type # Pass final connection type from downloader
            )

            # --- Trigger ComfyUI Refresh (Attempt) ---
            # This still might not work reliably or be desired by all users.
            # Consider making this a configurable option.
            if final_status == "completed":
                 print(f"[Manager] Download {download_id} completed ('{filename}'). Manual ComfyUI refresh may be needed for model list.")
                 # Potential (often ineffective) ways to trigger refresh:
                 # try:
                 #     import nodes
                 #     nodes.refresh_custom_node_list() # May not update model lists
                 #     print("[Manager] Attempted ComfyUI node list refresh.")
                 # except Exception as refresh_err:
                 #     print(f"[Manager] Failed to trigger ComfyUI node refresh: {refresh_err}")
                 # try:
                 #      # Triggering API endpoints? Unreliable.
                 #      # requests.post(f"{server.PromptServer.instance.address}/refresh") # Example, endpoint might not exist
                 # except: pass

# --- Global Instance ---
manager = DownloadManager(max_concurrent=MAX_CONCURRENT_DOWNLOADS)

# --- Graceful Shutdown ---
def shutdown_manager():
    print("[Manager] Shutdown requested.")
    if manager:
        manager.running = False
        # Attempt to acquire lock for cancellation (with timeout)
        if manager.lock.acquire(timeout=1.0):
             try:
                 active_ids = list(manager.active_downloads.keys())
                 queue_ids = [item['id'] for item in manager.queue]
             finally:
                 manager.lock.release()

             print(f"[Manager] Requesting cancellation for {len(active_ids)} active and {len(queue_ids)} queued downloads on shutdown...")
             all_ids_to_cancel = active_ids + queue_ids
             for dl_id in all_ids_to_cancel:
                  try:
                      # Reuse cancel_download which handles both active and queued
                      manager.cancel_download(dl_id)
                  except Exception as e:
                       print(f"Error cancelling {dl_id} during shutdown: {e}")
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

# Register the shutdown function to be called when Python exits
import atexit
atexit.register(shutdown_manager)