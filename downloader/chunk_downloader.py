# ================================================
# File: downloader/chunk_downloader.py (Updated)
# ================================================
import requests
import threading
import time
import shutil
from pathlib import Path
import os
from typing import Optional, Dict, Tuple # Added Tuple

# Import manager type hint without circular dependency during type checking
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .manager import DownloadManager

# Import config values
from ..config import DEFAULT_CHUNK_SIZE

class ChunkDownloader:
    """Handles downloading files in chunks using multiple connections."""
    # How often to yield status updates (seconds)
    STATUS_UPDATE_INTERVAL = 0.5

    def __init__(self, url: str, output_path: str, num_connections: int = 4,
                 chunk_size: int = DEFAULT_CHUNK_SIZE, manager: 'DownloadManager' = None,
                 download_id: str = None, api_key: Optional[str] = None): # Added api_key
        self.url: str = url
        self.output_path: Path = Path(output_path)
        self.temp_dir: Path = self.output_path.parent / f".{self.output_path.name}.parts_{download_id or int(time.time())}"
        self.num_connections: int = max(1, num_connections) # Ensure at least 1
        self.chunk_size: int = chunk_size # Chunk size for reading response content
        self.manager: 'DownloadManager' = manager
        self.download_id: str = download_id
        self.api_key: Optional[str] = api_key # Store API key

        self.total_size: int = 0
        self.downloaded: int = 0
        self.threads: list[threading.Thread] = []
        self.lock: threading.Lock = threading.Lock()
        self.cancel_event: threading.Event = threading.Event() # Use Event for cancellation signal
        self.error: Optional[str] = None
        self.part_files: list[Path] = []

        self._start_time: float = 0
        self._last_update_time: float = 0
        self._last_downloaded_bytes: int = 0
        self._speed: float = 0

    def _get_request_headers(self, range_header: bool = False) -> Dict[str, str]:
        """Constructs headers, adding Authorization if api_key exists."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            # print(f"[Downloader {self.download_id}] Using API Key for download request.") # Optional: Verbose log
        if range_header: # Placeholder, range is added specifically where needed
            pass
        # Add other headers if needed, e.g., User-Agent?
        # headers["User-Agent"] = "ComfyUI-Civitai-Downloader/1.0"
        return headers

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self):
        """Signal the download to cancel."""
        if not self.is_cancelled:
            print(f"[Downloader {self.download_id or 'N/A'}] Cancellation requested.")
            self.cancel_event.set()
            self.error = "Download cancelled by user" # Set an error message

    def _cleanup_temp(self, success: bool):
        """Remove temporary directory and potentially the output file."""
        if self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                # print(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                print(f"Warning: Could not remove temp directory {self.temp_dir}: {e}")

        # Remove the main output file if download failed or was cancelled
        if not success and self.output_path.exists():
             try:
                  self.output_path.unlink()
                  print(f"Removed incomplete/failed output file: {self.output_path}")
             except Exception as e:
                  print(f"Warning: Could not remove incomplete output file {self.output_path}: {e}")

    def get_file_info(self) -> Tuple[int, bool]:
        """Get the size of the file and check for range support."""
        try:
            request_headers = self._get_request_headers()
            # Add range header specifically for this check
            request_headers['Range'] = 'bytes=0-0'

            # Use HEAD request with a Range header to check for range support more reliably
            response = requests.head(self.url, allow_redirects=True, timeout=20, headers=request_headers)
            response.raise_for_status()

            # Follow redirects if needed (requests.head handles this automatically if allow_redirects=True)
            self.url = response.url # Update URL to the final destination after redirects

            size = int(response.headers.get('content-length', 0))
            # Check if 'bytes' is explicitly in accept-ranges OR if content-range is returned for 0-0 request
            accept_ranges = response.headers.get('accept-ranges', 'none').lower() == 'bytes'
            content_range = response.headers.get('content-range', None)
            range_supported = accept_ranges or (content_range is not None and content_range.startswith('bytes'))

            if size <= 0:
                 print(f"[Downloader {self.download_id}] Warning: Reported file size is 0 or missing from HEAD request for {self.url}")
                 # Optionally try GET request to double check size? For now, trust HEAD.

            print(f"[Downloader {self.download_id}] File Info - Size: {size}, Range Support: {range_supported}, Final URL: {self.url}")
            return size, range_supported

        except requests.exceptions.RequestException as e:
            self.error = f"Failed to get file info: {e}"
             # Check for 401/403 specifically
            if hasattr(e, 'response') and e.response is not None:
                 if e.response.status_code == 401:
                     self.error += " (Unauthorized - Check API Key?)"
                 elif e.response.status_code == 403:
                     self.error += " (Forbidden - Permissions Issue?)"
            print(f"[Downloader Error {self.download_id}] {self.error}")
            return 0, False
        except Exception as e:
             self.error = f"Unexpected error getting file info: {e}"
             print(f"[Downloader Error {self.download_id}] {self.error}")
             return 0, False

    def _update_progress(self, chunk_len: int):
        """Thread-safe update of download progress and speed calculation."""
        with self.lock:
            self.downloaded += chunk_len
            current_time = time.monotonic() # Use monotonic clock for measuring intervals
            time_diff = current_time - self._last_update_time

            # Update speed and notify manager periodically
            if time_diff >= self.STATUS_UPDATE_INTERVAL or self.downloaded == self.total_size: # Update on completion too
                bytes_diff = self.downloaded - self._last_downloaded_bytes
                self._speed = bytes_diff / time_diff if time_diff > 0 else 0

                self._last_update_time = current_time
                self._last_downloaded_bytes = self.downloaded

                if self.manager and self.download_id:
                    progress = (self.downloaded / self.total_size) * 100 if self.total_size > 0 else 0
                    # Use manager's method to update status safely
                    self.manager._update_download_status(
                        self.download_id,
                        progress=min(progress, 100.0), # Cap progress at 100
                        speed=self._speed
                    )

    def download_segment(self, segment_index: int, start_byte: int, end_byte: int):
        """Downloads a specific segment of the file."""
        part_file_path = self.temp_dir / f"part_{segment_index}"
        request_headers = self._get_request_headers() # Get base headers (incl auth)
        request_headers['Range'] = f'bytes={start_byte}-{end_byte}' # Add range
        retries = 3
        current_try = 0
        segment_url = self.url # Use the potentially redirected URL obtained from get_file_info

        while current_try < retries and not self.is_cancelled:
            response = None # Define outside try block
            try:
                # print(f"Thread {segment_index}: Requesting range {start_byte}-{end_byte} from {segment_url}")
                response = requests.get(segment_url, headers=request_headers, stream=True, timeout=60) # Longer timeout for active download
                response.raise_for_status()

                bytes_written_this_segment = 0
                with open(part_file_path, 'wb') as f:
                    for chunk in response.iter_content(self.chunk_size):
                        if self.is_cancelled:
                            # print(f"Thread {segment_index}: Cancellation detected.")
                            return # Exit thread gracefully

                        if chunk:
                            bytes_written = f.write(chunk)
                            bytes_written_this_segment += bytes_written
                            self._update_progress(bytes_written)

                # Verify segment size after download completes
                expected_size = (end_byte - start_byte) + 1
                if bytes_written_this_segment != expected_size:
                   # This might happen with flaky connections, retry
                   response.close() # Close connection before retry
                   raise ValueError(f"Size mismatch. Expected {expected_size}, got {bytes_written_this_segment}")

                # print(f"Thread {segment_index}: Finished range {start_byte}-{end_byte}")
                return # Success for this segment

            except (requests.exceptions.RequestException, ValueError) as e: # Catch connection errors and value errors (size mismatch)
                current_try += 1
                error_msg_detail = f"{e}"
                # Check for 401/403 specifically in RequestException
                if isinstance(e, requests.exceptions.RequestException) and hasattr(e, 'response') and e.response is not None:
                     if e.response.status_code == 401: error_msg_detail += " (Unauthorized)"
                     elif e.response.status_code == 403: error_msg_detail += " (Forbidden)"

                error_msg = f"Segment {segment_index} failed (Try {current_try}/{retries}): {error_msg_detail}"
                print(f"Warning: [Downloader {self.download_id}] {error_msg}")

                if current_try >= retries:
                    self.error = error_msg # Set final error
                    self.cancel() # Signal other threads to stop if one fails critically
                    print(f"Error: [Downloader {self.download_id}] Segment {segment_index} giving up.")
                    return
                # Exponential backoff before retry
                time.sleep(min(2 ** current_try, 10)) # Sleep max 10s between retries

            except Exception as e: # Catch other errors
                 self.error = f"Segment {segment_index} critical error: {e}"
                 print(f"Error: [Downloader {self.download_id}] {self.error}")
                 self.cancel() # Signal cancellation on critical error
                 return
            finally:
                 # Ensure response is closed
                 if response:
                     response.close()

    def merge_parts(self) -> bool:
        """Merges all downloaded part files into the final output file."""
        print(f"[Downloader {self.download_id}] Merging {len(self.part_files)} parts for {self.output_path.name}...")
        if not self.part_files:
             self.error = "No part files found to merge."
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             return False
        try:
             # Sort part files numerically by index from filename
             # Assuming format "part_{index}"
             sorted_part_files = sorted(self.part_files, key=lambda p: int(p.name.split('_')[-1]))

             with open(self.output_path, 'wb') as outfile:
                  for part_file in sorted_part_files:
                      if not part_file.exists():
                          # If a part is missing, check if cancelled
                          if self.is_cancelled:
                               self.error = self.error or "Cancelled during download, merge aborted."
                               print(f"Warning: [Downloader {self.download_id}] Merge aborted, part missing due to cancellation: {part_file}")
                               return False
                          else:
                               raise FileNotFoundError(f"Merge failed, missing part file: {part_file}")

                      with open(part_file, 'rb') as infile:
                          # Read/write in chunks to handle large files efficiently
                          while True:
                              data = infile.read(1024 * 1024) # Read 1MB chunks
                              if not data:
                                  break
                              outfile.write(data)
             print(f"[Downloader {self.download_id}] Merging complete.")
             # Optional: Verify final file size after merge
             final_size = self.output_path.stat().st_size
             if final_size != self.total_size:
                  # This is more serious than a warning if merge succeeded otherwise
                  self.error = f"Merged size ({final_size}) differs from expected ({self.total_size}). File may be corrupt."
                  print(f"Error: [Downloader {self.download_id}] {self.error}")
                  self._cleanup_temp(success=False) # Treat size mismatch after merge as failure
                  return False
                 # print(f"Warning: [Downloader {self.download_id}] Final merged size ({final_size}) differs slightly from expected ({self.total_size}).")
             return True

        except Exception as e:
            self.error = f"Failed to merge parts: {e}"
            print(f"Error: [Downloader {self.download_id}] {self.error}")
            # If merge fails, the output file might be corrupt
            self._cleanup_temp(success=False) # Cleanup already handles removing failed output
            return False

    def fallback_download(self) -> bool:
         """Fallback to standard single-connection download."""
         print(f"[Downloader {self.download_id}] Using standard single-connection download for {self.output_path.name}...")
         self._start_time = time.monotonic()
         self._last_update_time = self._start_time
         self._last_downloaded_bytes = 0
         self.downloaded = 0
         response = None # Define outside try

         try:
             request_headers = self._get_request_headers() # Include auth header if needed
             response = requests.get(self.url, stream=True, timeout=60, allow_redirects=True, headers=request_headers)
             response.raise_for_status()

              # Update URL after potential redirects
             self.url = response.url

             # Update size if not already known or was 0
             if self.total_size <= 0:
                 self.total_size = int(response.headers.get('content-length', 0))
                 if self.total_size <= 0:
                      print(f"Warning: [Downloader {self.download_id}] Fallback download also reports size 0 or missing. Proceeding anyway.")
                 else:
                      print(f"[Downloader {self.download_id}] Obtained file size via fallback GET: {self.total_size}")

             with open(self.output_path, 'wb') as f:
                 for chunk in response.iter_content(self.chunk_size):
                     if self.is_cancelled:
                          print(f"[Downloader {self.download_id}] Fallback download cancelled.")
                          self._cleanup_temp(success=False)
                          return False

                     if chunk:
                         bytes_written = f.write(chunk)
                         self._update_progress(bytes_written) # Update progress/speed

             # Final check after download completes
             if self.total_size > 0 and self.downloaded != self.total_size:
                 self.error = f"Fallback download size mismatch. Expected {self.total_size}, got {self.downloaded}."
                 print(f"Warning: [Downloader {self.download_id}] {self.error}")
                 # Treat size mismatch as failure for fallback too? Yes, seems safer.
                 self._cleanup_temp(success=False)
                 return False
                 # Don't automatically fail, but log warning.

             print(f"[Downloader {self.download_id}] Fallback download completed.")
             return True

         except requests.exceptions.RequestException as e:
             error_msg_detail = f"{e}"
             if hasattr(e, 'response') and e.response is not None:
                  if e.response.status_code == 401: error_msg_detail += " (Unauthorized - Check API Key?)"
                  elif e.response.status_code == 403: error_msg_detail += " (Forbidden - Permissions Issue?)"
             self.error = f"Fallback download failed: {error_msg_detail}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False
         except Exception as e:
             self.error = f"Fallback download failed with unexpected error: {e}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False
         finally:
             if response:
                 response.close()

    def download(self) -> bool:
        """Starts the multi-threaded or fallback download process."""
        self._start_time = time.monotonic()
        # Make sure temp dir doesn't exist from a previous failed run
        if self.temp_dir.exists():
            print(f"Warning: Removing leftover temp directory: {self.temp_dir}")
            try:
                 shutil.rmtree(self.temp_dir)
            except Exception as e:
                 self.error = f"Failed to clean up previous temp directory: {e}"
                 print(f"Error: [Downloader {self.download_id}] {self.error}")
                 return False # Abort if cleanup fails

        self.total_size, supports_ranges = self.get_file_info()

        if self.error: # If get_file_info already failed
            self._cleanup_temp(success=False) # Cleanup ensures no partial output file remains
            return False
        if self.total_size <= 0:
            print(f"[Downloader {self.download_id}] File size is 0 or unavailable from HEAD request. Attempting fallback download.")
            # Fallback might still work if server didn't report size correctly in HEAD
            # Or if HEAD failed due to auth but GET works differently (less common)
            success = self.fallback_download()
            # Fallback handles its own cleanup on error, but call again just in case
            self._cleanup_temp(success=success)
            return success

        # Decide whether to use multi-connection based on range support AND file size threshold?
        # Downloading very small files with multiple connections can be slower.
        MIN_SIZE_FOR_MULTI_MB = 50 # Example: Only use multi-connection for files > 50MB
        use_multi_connection = (supports_ranges and
                               self.num_connections > 1 and
                               self.total_size > MIN_SIZE_FOR_MULTI_MB * 1024 * 1024)

        if not use_multi_connection:
             reason = "Range requests not supported" if not supports_ranges else \
                      "Single connection selected" if self.num_connections <= 1 else \
                      f"File size <= {MIN_SIZE_FOR_MULTI_MB}MB"
             print(f"[Downloader {self.download_id}] ({reason}). Using fallback single-connection download.")
             success = self.fallback_download()
             self._cleanup_temp(success=success)
             return success

        # --- Proceed with Multi-Connection Download ---
        print(f"[Downloader {self.download_id}] Starting multi-connection download for {self.output_path.name} "
              f"({self.total_size / (1024 * 1024):.2f} MB) using {self.num_connections} connections.")

        # Ensure temp directory exists and is clean (double check)
        try:
            if self.temp_dir.exists(): # Should have been removed earlier, but check again
                 shutil.rmtree(self.temp_dir)
            self.temp_dir.mkdir(parents=True)
        except Exception as e:
            self.error = f"Failed to create temp directory {self.temp_dir}: {e}"
            print(f"Error: [Downloader {self.download_id}] {self.error}")
            return False

        self.part_files = [] # Reset list of parts for this download attempt

        # --- Calculate segments ---
        # Prevent zero division if total_size is tiny but multi-connection was chosen (shouldn't happen with threshold)
        if self.num_connections == 0: self.num_connections = 1 # Safety
        segment_size = self.total_size // self.num_connections
        if segment_size == 0 and self.total_size > 0 : # Handle case where size < connections
             segment_size = self.total_size # Effectively becomes single segment download

        segments = []
        current_byte = 0
        for i in range(self.num_connections):
            if current_byte >= self.total_size: break # Stop if we've covered the whole file size

            start_byte = current_byte
            # Calculate end_byte carefully to avoid exceeding total_size
            end_byte = min(current_byte + segment_size - 1, self.total_size - 1)

            # Ensure last segment covers the exact end, handling remainders
            if i == self.num_connections - 1:
                 end_byte = self.total_size - 1

            # Only create segment if start <= end and end is valid
            if start_byte <= end_byte < self.total_size:
                 segments.append((i, start_byte, end_byte))
                 # Add part file path to the list expected for merging
                 self.part_files.append(self.temp_dir / f"part_{i}")
            else:
                 # This might happen if calculation is slightly off or size is very small
                 print(f"Warning: [Downloader {self.download_id}] Skipping invalid segment calculation for i={i}, start={start_byte}, end={end_byte}")
                 break # Stop creating segments if calculation goes wrong

            current_byte = end_byte + 1 # Start of next segment

        if not segments:
             self.error = "No valid download segments calculated."
             print(f"Error: [Downloader {self.download_id}] {self.error}. Total Size: {self.total_size}, Connections: {self.num_connections}")
             self._cleanup_temp(success=False)
             return False

        # --- Create and start download threads ---
        self.threads = []
        for index, start, end in segments:
            if self.is_cancelled: break # Check before starting new threads
            thread = threading.Thread(target=self.download_segment, args=(index, start, end), daemon=True)
            self.threads.append(thread)
            thread.start()

        # --- Wait for threads to complete ---
        start_wait_time = time.monotonic()
        JOIN_TIMEOUT_PER_THREAD = 120 # Max seconds to wait for a thread after loop finishes (generous)
        active_threads = list(self.threads)

        try:
            while active_threads:
                if self.is_cancelled:
                    print(f"[Downloader {self.download_id}] Cancellation detected, signalling threads to stop...")
                    # Threads check self.is_cancelled internally. No forceful join needed for daemon threads.
                    break # Exit waiting loop

                # Check thread status with a timeout
                # Check frequently initially, then less often?
                check_interval = 0.2
                time.sleep(check_interval)

                active_threads = [t for t in active_threads if t.is_alive()]

                # Optional: Timeout logic for hung threads? Complex. For now, rely on request timeouts.

        except KeyboardInterrupt:
             print(f"[Downloader {self.download_id}] Interrupted! Signalling cancellation.")
             self.cancel()
             # Give threads a moment to potentially react
             time.sleep(1)
             # Fall through to checks below

        # --- Post-Download Checks ---
        # Re-check cancellation status after wait loop
        if self.is_cancelled:
            print(f"[Downloader {self.download_id}] Download stopped due to cancellation.")
            # Error message should already be set by cancel() or a failing thread
            self.error = self.error or "Download cancelled"
            self._cleanup_temp(success=False)
            return False

        # Check if any thread set a global error
        if self.error:
            print(f"[Downloader {self.download_id}] Download stopped due to error in a thread: {self.error}")
            self._cleanup_temp(success=False)
            return False

        # Final size check after all threads *should* have finished
        if self.downloaded != self.total_size:
             # This IS an error condition if cancellation/other errors didn't occur
             self.error = f"Final downloaded bytes ({self.downloaded}) does not match expected total size ({self.total_size})."
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False

        # -------- Merge the parts --------
        merge_success = self.merge_parts()
        # merge_parts sets self.error and handles cleanup on its own failure
        # _cleanup_temp only needs to remove the temp folder if merge succeeded
        if merge_success:
             self._cleanup_temp(success=True) # Clean up only temp folder
             print(f"[Downloader {self.download_id}] Successfully downloaded and merged: {self.output_path}")
        else:
             # Error already set by merge_parts if it failed
             print(f"Error: [Downloader {self.download_id}] Merge process failed.")

        # Return final success state
        return merge_success