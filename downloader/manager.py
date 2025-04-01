# ComfyUI_Civitai_Downloader/downloader/manager.py
import threading
import time
import datetime
from typing import List, Dict, Any, Optional

# Use typing for Downloader class hint to avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .chunk_downloader import ChunkDownloader

# Import config consts
from ..config import MAX_CONCURRENT_DOWNLOADS, DOWNLOAD_HISTORY_LIMIT, DEFAULT_CONNECTIONS

class DownloadManager:
    """Manages a queue of downloads, running them concurrently."""

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
            # More robust ID generation
            queue_num = sum(1 for item in self.queue if item.get("filename") == download_info.get("filename"))
            download_id = f"dl_{timestamp}_{queue_num}_{download_info.get('filename','file')[:5]}"

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

            # Ensure 'num_connections' exists, provide default if not
            if "num_connections" not in download_info:
                 download_info["num_connections"] = DEFAULT_CONNECTIONS
            # Ensure 'known_size' exists (can be None)
            if "known_size" not in download_info:
                 download_info["known_size"] = None

            self.queue.append(download_info)
            print(f"[Manager] Queued: {download_info.get('filename', 'N/A')} (ID: {download_id}, Size: {download_info.get('known_size', 'Unknown')})")
            return download_id

    def cancel_download(self, download_id: str) -> bool:
        """Requests cancellation of a queued or active download."""
        with self.lock:
            # Check queue first
            for i, item in enumerate(self.queue):
                if item["id"] == download_id:
                    cancelled_info = self.queue.pop(i)
                    cancelled_info["status"] = "cancelled"
                    cancelled_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    cancelled_info["error"] = "Cancelled from queue"
                    self._add_to_history(cancelled_info)
                    print(f"[Manager] Cancelled queued download: {download_id}")
                    return True

            # Check active downloads
            if download_id in self.active_downloads:
                active_info = self.active_downloads[download_id]
                downloader: Optional['ChunkDownloader'] = active_info.get("downloader_instance")

                if downloader:
                    downloader.cancel() # Signal the downloader thread to stop
                    # Status ("cancelled") will be updated by the _download_file_wrapper or downloader.cancel()
                    print(f"[Manager] Cancellation requested for active download: {download_id}")
                    # Don't move to history yet, let the thread finish and update status
                    return True
                else:
                    # Downloader instance not yet created (e.g., status 'starting')
                    # Mark as cancelled, it won't start
                    active_info["status"] = "cancelled"
                    active_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    active_info["error"] = "Cancelled before download started"
                    # The _process_queue will move it later
                    print(f"[Manager] Cancelled download (status: starting): {download_id}")
                    return True

        print(f"[Manager] Could not cancel - ID not found in queue or active: {download_id}")
        return False

    def get_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Returns the current state of the queue, active downloads, and history."""
        with self.lock:
            # Prepare active downloads list, excluding the downloader instance
            active_list = []
            for item_id, item_data in self.active_downloads.items():
                # Create a copy, exclude the actual downloader object
                info_copy = {k: v for k, v in item_data.items() if k != 'downloader_instance'}
                active_list.append(info_copy)

            # Return copies to prevent external modification
            return {
                "queue": [item.copy() for item in self.queue],
                "active": active_list,
                # Return limited history, newest first
                "history": [item.copy() for item in self.history[:DOWNLOAD_HISTORY_LIMIT]]
            }

    def _add_to_history(self, download_info: Dict[str, Any]):
        """Adds a completed/failed/cancelled item to history (internal)."""
        # Ensure sensitive or internal objects are removed
        info_copy = {k: v for k, v in download_info.items() if k != 'downloader_instance'}
        if "end_time" not in info_copy or info_copy["end_time"] is None:
             info_copy["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

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
                    if info["status"] in ["completed", "failed", "cancelled"]
                ]
                for dl_id in finished_ids:
                    finished_info = self.active_downloads.pop(dl_id)
                    # Ensure downloader instance is removed before adding to history
                    finished_info.pop('downloader_instance', None)
                    self._add_to_history(finished_info)
                    print(f"[Manager] Moved '{finished_info.get('filename', dl_id)}' to history (Status: {finished_info['status']})")
                    processed_something = True

                # 2. Start new downloads if slots available and queue has items
                while len(self.active_downloads) < self.max_concurrent and self.queue:
                    download_info = self.queue.pop(0)
                    download_id = download_info["id"]

                     # Double check if cancelled just before starting
                    if download_info["status"] == "cancelled":
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

                # Only update if value is provided
                if status is not None:
                    item["status"] = status
                if progress is not None:
                    # Clamp progress between 0 and 100
                    item["progress"] = max(0.0, min(100.0, progress))
                if speed is not None:
                    item["speed"] = max(0.0, speed) # Speed cannot be negative
                if error is not None:
                    # Update error only if it's new or different? No, allow overwriting.
                    item["error"] = str(error)[:500] # Limit length
                if connection_type is not None and connection_type != "N/A": # Only update if not N/A
                    item["connection_type"] = connection_type

            # else:
            #     # This can happen normally if status update arrives after item moved to history
            #     # print(f"Debug: Attempted to update status for finished/unknown ID: {download_id}. Status was: {status}")
            #     pass

    def _download_file_wrapper(self, download_info: Dict[str, Any]):
        """Wraps the download execution, handles status updates and exceptions."""
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
            # so we might not need to do it *again* here explicitly.
            # However, to be safe, especially catching exceptions *before* the downloader's
            # finally block runs, we perform a final update.
            # Fetch the latest progress from the downloader if available
            final_progress = downloader.downloaded if downloader and downloader.total_size > 0 else 0
            final_progress_percent = (final_progress / downloader.total_size * 100) if downloader and downloader.total_size > 0 else 0
            if final_status == "completed": final_progress_percent = 100.0

            conn_type = downloader.connection_type if downloader else download_info.get("connection_type", "N/A")

            print(f"[Downloader Wrapper {download_id}] Finalizing status: {final_status}, Error: {error_msg}")
            self._update_download_status(
                download_id,
                status=final_status,
                progress=min(100.0, final_progress_percent), # Ensure capped
                speed=0, # Final speed is 0
                error=error_msg,
                connection_type=conn_type # Pass final connection type
            )

            # Detach downloader instance reference? Let _process_queue handle this when moving to history.
            # The lock in _process_queue prevents race conditions here.

            # Trigger ComfyUI refresh? (Still problematic)
            if final_status == "completed":
                 print(f"[Manager] Download {download_id} completed. Manual ComfyUI refresh may be needed to see the model.")

# --- Global Instance ---
manager = DownloadManager(max_concurrent=MAX_CONCURRENT_DOWNLOADS)

# --- Graceful Shutdown ---
def shutdown_manager():
    print("[Manager] Shutdown requested.")
    if manager:
        manager.running = False
        # Cancel any active downloads?
        if manager.lock.acquire(timeout=1.0): # Try to acquire lock
             active_ids = list(manager.active_downloads.keys())
             manager.lock.release()
             print(f"[Manager] Requesting cancellation for {len(active_ids)} active downloads on shutdown...")
             for dl_id in active_ids:
                  try:
                      manager.cancel_download(dl_id)
                  except Exception as e:
                       print(f"Error cancelling {dl_id} during shutdown: {e}")
             # Give threads a moment to react
             time.sleep(0.5)
        else:
            print("[Manager] Could not acquire lock to cancel downloads during shutdown.")

        # Attempt to join thread (best effort)
        try:
            if manager._process_thread.is_alive():
                 manager._process_thread.join(timeout=2.0)
                 if manager._process_thread.is_alive():
                      print("[Manager] Process thread did not exit cleanly.")
        except Exception as e:
            print(f"Error joining manager thread: {e}")
    print("[Manager] Shutdown complete.")

import atexit
atexit.register(shutdown_manager)