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
            download_id = f"dl_{timestamp}_{len(self.queue)}_{download_info.get('filename','file')[:5]}"

            # Set initial status and info
            download_info["id"] = download_id
            download_info["status"] = "queued"
            download_info["added_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            download_info["progress"] = 0
            download_info["speed"] = 0
            download_info["error"] = None
            download_info["start_time"] = None
            download_info["end_time"] = None

            # Ensure 'num_connections' exists, provide default if not
            if "num_connections" not in download_info:
                 download_info["num_connections"] = DEFAULT_CONNECTIONS

            self.queue.append(download_info)
            print(f"[Manager] Queued: {download_info.get('filename', 'N/A')} (ID: {download_id})")
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
                    # Status will be updated to 'cancelled' by the _download_file_wrapper
                    print(f"[Manager] Cancellation requested for active download: {download_id}")
                    # Don't move to history yet, let the thread finish and update status
                    return True
                else:
                    # Downloader instance not yet created (e.g., status 'starting')
                    # Mark as cancelled, it won't start
                    active_info["status"] = "cancelled"
                    active_info["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    active_info["error"] = "Cancelled before download started"
                    print(f"[Manager] Cancelled download before instance creation: {download_id}")
                    # The _process_queue will move it later
                    return True

        print(f"[Manager] Could not cancel - ID not found in queue or active: {download_id}")
        return False

    def get_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Returns the current state of the queue, active downloads, and history."""
        with self.lock:
            # Prepare active downloads list, excluding the downloader instance
            active_list = []
            for item in self.active_downloads.values():
                # Create a copy, exclude the actual downloader object
                info_copy = {k: v for k, v in item.items() if k != 'downloader_instance'}
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
                # 1. Check for finished/failed active downloads to move to history
                finished_ids = [
                    dl_id for dl_id, info in self.active_downloads.items()
                    if info["status"] in ["completed", "failed", "cancelled"]
                ]
                for dl_id in finished_ids:
                    finished_info = self.active_downloads.pop(dl_id)
                    self._add_to_history(finished_info)
                    print(f"[Manager] Moved '{finished_info.get('filename', dl_id)}' to history (Status: {finished_info['status']})")
                    processed_something = True

                # 2. Start new downloads if slots available and queue has items
                while len(self.active_downloads) < self.max_concurrent and self.queue:
                    download_info = self.queue.pop(0)
                    download_id = download_info["id"]

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
                                error: Optional[str] = None):
        """Safely updates the status fields of an active download (thread-safe)."""
        # Assume lock is already held by caller if necessary, or acquire it if called externally
        # For internal calls from downloader, manager should handle locking when accessing shared state.
        # Let's make this method acquire the lock for safety if called directly.
        with self.lock:
            if download_id in self.active_downloads:
                item = self.active_downloads[download_id]
                if status is not None:
                    item["status"] = status
                if progress is not None:
                    # Clamp progress between 0 and 100
                    item["progress"] = max(0.0, min(100.0, progress))
                if speed is not None:
                    item["speed"] = max(0.0, speed) # Speed cannot be negative
                if error is not None:
                    # Limit error message length?
                    item["error"] = str(error)[:500] # Limit length
            # else:
            #     print(f"Warning: Attempted to update status for unknown/inactive ID: {download_id}")

    def _download_file_wrapper(self, download_info: Dict[str, Any]):
        """Wraps the download execution, handles status updates and exceptions."""
        download_id = download_info["id"]
        filename = download_info.get('filename', download_id)
        success = False
        final_status = "failed" # Default to failed unless success or cancelled
        error_msg = None

        # Lazily import ChunkDownloader here to avoid top-level circular import issues
        from .chunk_downloader import ChunkDownloader

        try:
            # Create downloader instance (now inside the thread)
            downloader = ChunkDownloader(
                url=download_info["url"],
                output_path=download_info["output_path"],
                num_connections=download_info.get("num_connections", DEFAULT_CONNECTIONS),
                manager=self,
                download_id=download_id
            )
             # Store instance reference in the shared dict (use lock)
            with self.lock:
                  if download_id in self.active_downloads: # Check if not cancelled between scheduling and now
                       self.active_downloads[download_id]["downloader_instance"] = downloader
                  else:
                       print(f"[Downloader Wrapper {download_id}] Download was cancelled before instance creation.")
                       # Status already set by cancel_download, just exit thread
                       return

            # Update status to 'downloading' (only if not cancelled)
            if not downloader.is_cancelled:
               self._update_download_status(download_id, status="downloading")
               print(f"[Downloader Wrapper {download_id}] Starting actual download for '{filename}'.")
               success = downloader.download() # THIS IS THE BLOCKING CALL

            # --- Finished downloading (or failed/cancelled) ---
            error_msg = downloader.error # Get error message from downloader

            if downloader.is_cancelled:
                final_status = "cancelled"
                print(f"[Downloader Wrapper {download_id}] Download cancelled for '{filename}'.")
            elif success:
                final_status = "completed"
                print(f"[Downloader Wrapper {download_id}] Download completed successfully for '{filename}'.")
            else:
                final_status = "failed" # Keep default 'failed'
                print(f"[Downloader Wrapper {download_id}] Download failed for '{filename}'. Error: {error_msg}")

        except Exception as e:
            # Catch unexpected errors during instance creation or download call
            import traceback
            print(f"--- Critical Error in Download Wrapper {download_id} ('{filename}') ---")
            traceback.print_exc()
            print("--- End Error ---")
            final_status = "failed"
            error_msg = f"Unexpected wrapper error: {str(e)}"

        finally:
            # --- Final status update ---
            # Calculate final progress (100% if completed, else use last known progress)
            final_progress = 100.0 if final_status == "completed" else download_info.get("progress", 0)
            # Update status, progress, speed (set to 0), and error message
            self._update_download_status(
                download_id,
                status=final_status,
                progress=final_progress,
                speed=0,
                error=error_msg # Update error message based on outcome
            )
            # Detach downloader instance? No, let _process_queue handle cleanup.

            # TODO: Optionally trigger a ComfyUI refresh signal/scan here if download was successful
            if final_status == "completed":
                 # This is tricky. For now, manual refresh in ComfyUI is likely needed.
                 # Could try: folder_paths.add_model_folder_path(...) ? Unreliable.
                 # Could try: Touching a specific file ComfyUI watches? Also unreliable.
                 print(f"[Manager] Download {download_id} completed. Manual ComfyUI refresh may be needed to see the model.")

# --- Global Instance ---
# Instantiate the manager when the module is loaded
manager = DownloadManager(max_concurrent=MAX_CONCURRENT_DOWNLOADS)

# --- Graceful Shutdown (Optional but good practice) ---
def shutdown_manager():
    print("[Manager] Shutdown requested.")
    if manager:
        manager.running = False
        # Give the process thread a moment to finish its current loop
        # Joining might be complex with daemon threads, setting 'running' is usually enough
        # try:
        #     manager._process_thread.join(timeout=2.0)
        # except Exception as e:
        #     print(f"Error joining manager thread: {e}")
    print("[Manager] Shutdown complete.")

# Register cleanup function to run when Python exits
import atexit
atexit.register(shutdown_manager)