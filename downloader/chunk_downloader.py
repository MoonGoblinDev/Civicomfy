# ================================================
# File: downloader/chunk_downloader.py (Updated)
# ================================================
import requests
import threading
import time
import shutil
from pathlib import Path
import os
from typing import Optional, Dict, Tuple, Union # Added Union

# Import manager type hint without circular dependency during type checking
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .manager import DownloadManager

# Import config values
from ..config import DEFAULT_CHUNK_SIZE

class ChunkDownloader:
    """Handles downloading files in chunks using multiple connections or fallback."""
    # How often to yield status updates (seconds)
    STATUS_UPDATE_INTERVAL = 0.5
    # Timeout for the initial HEAD request to check range support
    HEAD_REQUEST_TIMEOUT = 25 # Increased slightly from 20

    def __init__(self, url: str, output_path: str, num_connections: int = 4,
                 chunk_size: int = DEFAULT_CHUNK_SIZE, manager: 'DownloadManager' = None,
                 download_id: str = None, api_key: Optional[str] = None,
                 known_size: Optional[int] = None): # Added known_size
        self.initial_url: str = url # Store the original URL
        self.url: str = url # This will be updated after redirects
        self.output_path: Path = Path(output_path)
        self.temp_dir: Path = self.output_path.parent / f".{self.output_path.name}.parts_{download_id or int(time.time())}"
        self.num_connections: int = max(1, num_connections) # Ensure at least 1
        self.chunk_size: int = chunk_size # Chunk size for reading response content
        self.manager: 'DownloadManager' = manager
        self.download_id: str = download_id
        self.api_key: Optional[str] = api_key # Store API key
        self.known_size: Optional[int] = known_size if known_size and known_size > 0 else None # Store known size if valid

        self.total_size: int = self.known_size or 0 # Initialize with known size
        self.downloaded: int = 0
        self.threads: list[threading.Thread] = []
        self.lock: threading.Lock = threading.Lock()
        self.cancel_event: threading.Event = threading.Event() # Use Event for cancellation signal
        self.error: Optional[str] = None
        self.part_files: list[Path] = []
        self.connection_type: str = "N/A" # Added: "Single", "Multi (n)", "N/A"

        self._start_time: float = 0
        self._last_update_time: float = 0
        self._last_downloaded_bytes: int = 0
        self._speed: float = 0

    def _get_request_headers(self, add_range: Optional[str] = None) -> Dict[str, str]:
        """Constructs headers, adding Authorization and optional Range."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if add_range:
             headers['Range'] = add_range
        # headers["User-Agent"] = "ComfyUI-Civitai-Downloader/1.0" # Optional
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
            # Update final status via manager
            if self.manager and self.download_id:
                self.manager._update_download_status(self.download_id, status="cancelled", error=self.error)

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

    def _get_range_support_and_url(self) -> Tuple[str, bool]:
        """
        Attempts to get the final URL and check for range support using HEAD.
        Handles errors gracefully by returning the original URL and assuming no range support.
        Returns: (final_url: str, supports_ranges: bool)
        """
        final_url = self.initial_url # Start with original
        supports_ranges = False
        try:
            # Use HEAD request with a Range header to check support reliably
            # Only use base headers, range will be added if needed later
            request_headers = self._get_request_headers()

            print(f"[Downloader {self.download_id}] Checking range support/redirects for: {self.initial_url} (Timeout: {self.HEAD_REQUEST_TIMEOUT}s)")
            response = requests.head(
                self.initial_url,
                allow_redirects=True, # Follow redirects
                timeout=self.HEAD_REQUEST_TIMEOUT,
                headers=request_headers
            )
            response.raise_for_status()

            # Update URL to the final destination after redirects
            final_url = response.url
            self.url = final_url # Update the main URL used by other methods

            # Check for range support (Accept-Ranges header)
            accept_ranges = response.headers.get('accept-ranges', 'none').lower()
            supports_ranges = accept_ranges == 'bytes'

            # Optionally get size from HEAD as a fallback if known_size wasn't provided
            if self.total_size <= 0:
                 head_size = int(response.headers.get('content-length', 0))
                 if head_size > 0:
                     self.total_size = head_size
                     print(f"[Downloader {self.download_id}] Got file size from HEAD: {self.total_size} bytes")
                 else:
                      # This is not an error, fallback will try GET
                      print(f"[Downloader {self.download_id}] Warning: File size not available from HEAD request for {final_url}")

            print(f"[Downloader {self.download_id}] HEAD Check OK - Final URL: {final_url}, Range Support: {supports_ranges}")
            return final_url, supports_ranges

        except requests.exceptions.Timeout as e:
             self.error = f"HEAD request timed out ({self.HEAD_REQUEST_TIMEOUT}s) checking range support: {e}"
             print(f"Warning: [Downloader {self.download_id}] {self.error}. Proceeding with Single connection.")
             return self.initial_url, False # Assume no range support on timeout
        except requests.exceptions.RequestException as e:
             # Log specific HTTP errors if possible
             http_error_details = ""
             if hasattr(e, 'response') and e.response is not None:
                  status_code = e.response.status_code
                  http_error_details = f" (Status Code: {status_code})"
                  # if status_code == 401: http_error_details += " - Unauthorized?"
                  # elif status_code == 403: http_error_details += " - Forbidden?"
             #self.error = f"HEAD request failed checking range support: {e}{http_error_details}"
             print(f"Warning: [Downloader {self.download_id}] {self.error}. Proceeding with Single connection.")
             return self.initial_url, False # Assume no range support on other errors
        except Exception as e: # Catch any other unexpected errors
             self.error = f"Unexpected error during HEAD request: {e}"
             print(f"Warning: [Downloader {self.download_id}] {self.error}. Proceeding with Single connection.")
             return self.initial_url, False

    def _update_progress(self, chunk_len: int):
        """Thread-safe update of download progress and speed calculation."""
        with self.lock:
            self.downloaded += chunk_len
            current_time = time.monotonic() # Use monotonic clock for measuring intervals
            time_diff = current_time - self._last_update_time

            # Update speed and notify manager periodically
            if time_diff >= self.STATUS_UPDATE_INTERVAL or self.downloaded == self.total_size: # Update on completion too
                # Ensure total_size is positive to avoid division by zero
                if self.total_size > 0:
                    progress = min((self.downloaded / self.total_size) * 100, 100.0) # Cap progress at 100
                else:
                    progress = 0 # Can't calculate progress if size is unknown

                # Calculate speed only if time has passed
                if time_diff > 0:
                    bytes_diff = self.downloaded - self._last_downloaded_bytes
                    self._speed = bytes_diff / time_diff
                # else: self._speed remains the same

                self._last_update_time = current_time
                self._last_downloaded_bytes = self.downloaded

                if self.manager and self.download_id:
                    # Use manager's method to update status safely
                    # Note: connection_type is updated only once when strategy is decided
                    self.manager._update_download_status(
                        self.download_id,
                        progress=progress,
                        speed=self._speed
                        # connection_type is not updated here
                    )

    def download_segment(self, segment_index: int, start_byte: int, end_byte: int):
        """Downloads a specific segment of the file."""
        part_file_path = self.temp_dir / f"part_{segment_index}"
        # Use self.url which might have been updated by _get_range_support_and_url
        segment_url = self.url
        request_headers = self._get_request_headers(add_range=f'bytes={start_byte}-{end_byte}') # Add range
        retries = 3
        current_try = 0

        while current_try < retries and not self.is_cancelled:
            response = None # Define outside try block
            try:
                # print(f"Thread {segment_index}: Requesting range {start_byte}-{end_byte} from {segment_url}")
                response = requests.get(segment_url, headers=request_headers, stream=True, timeout=60) # Longer timeout for active download
                response.raise_for_status()

                # Check Content-Range header if returned (optional verification)
                # content_range = response.headers.get('Content-Range')
                # print(f"Thread {segment_index}: Response headers: {response.headers}")

                bytes_written_this_segment = 0
                with open(part_file_path, 'wb') as f:
                    for chunk in response.iter_content(self.chunk_size):
                        if self.is_cancelled:
                            # print(f"Thread {segment_index}: Cancellation detected.")
                            return # Exit thread gracefully

                        if chunk:
                            bytes_written = f.write(chunk)
                            bytes_written_this_segment += bytes_written
                            self._update_progress(bytes_written) # Updates global downloaded count

                # Verify segment size after download completes
                expected_size = (end_byte - start_byte) + 1
                if bytes_written_this_segment != expected_size:
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
                     elif response and response.status_code == 416: # Range Not Satisfiable
                           error_msg_detail += " (Range Not Satisfiable - Server Issue?)"
                           # No point retrying 416 usually
                           self.error = f"Segment {segment_index} failed: {error_msg_detail}"
                           self.cancel()
                           return

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
             if self.is_cancelled:
                  self.error = self.error or "Cancelled before any parts downloaded."
             else:
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
                               # This shouldn't happen if threads finished correctly without errors/cancellation
                               raise FileNotFoundError(f"Merge failed, missing part file: {part_file}. This should not happen.")

                      with open(part_file, 'rb') as infile:
                          # Read/write in chunks to handle large files efficiently
                          shutil.copyfileobj(infile, outfile, length=1024*1024) # Use shutil helper

             print(f"[Downloader {self.download_id}] Merging complete.")
             # Optional: Verify final file size after merge
             final_size = self.output_path.stat().st_size
             # Tolerate tiny difference (e.g. 1 byte) which might happen rarely
             if self.total_size > 0 and abs(final_size - self.total_size) > 1:
                  self.error = f"Merged size ({final_size}) differs significantly from expected ({self.total_size}). File may be corrupt."
                  print(f"Error: [Downloader {self.download_id}] {self.error}")
                  # Don't cleanup yet, merge_parts caller should handle based on return value
                  return False
                 # print(f"Warning: [Downloader {self.download_id}] Final merged size ({final_size}) differs slightly from expected ({self.total_size}).")
             return True

        except Exception as e:
            self.error = f"Failed to merge parts: {e}"
            print(f"Error: [Downloader {self.download_id}] {self.error}")
            # merge_parts caller handles cleanup
            return False

    def fallback_download(self) -> bool:
         """Fallback to standard single-connection download."""
         # Ensure connection type is marked as Single and status updated
         self.connection_type = "Single"
         if self.manager and self.download_id:
              self.manager._update_download_status(self.download_id, connection_type=self.connection_type)

         print(f"[Downloader {self.download_id}] Using standard single-connection download for {self.output_path.name}...")
         self._start_time = self._start_time or time.monotonic() # Keep original start time if already set
         self._last_update_time = self._start_time
         self._last_downloaded_bytes = 0
         self.downloaded = 0 # Reset progress for this method
         response = None # Define outside try

         try:
             # Use self.url (possibly updated by HEAD request)
             fallback_url = self.url
             request_headers = self._get_request_headers() # Include auth header if needed

             response = requests.get(fallback_url, stream=True, timeout=60, allow_redirects=True, headers=request_headers)
             response.raise_for_status()

              # Update URL again after potential redirects during GET
             final_get_url = response.url
             if final_get_url != fallback_url:
                 print(f"[Downloader {self.download_id}] URL redirected during GET to: {final_get_url}")
                 self.url = final_get_url # Ensure self.url is the absolute final one

             # Get/Confirm size if not already known or was 0
             if self.total_size <= 0:
                 get_size = int(response.headers.get('content-length', 0))
                 if get_size > 0:
                      self.total_size = get_size
                      print(f"[Downloader {self.download_id}] Obtained file size via fallback GET: {self.total_size}")
                 else:
                      print(f"Warning: [Downloader {self.download_id}] Fallback download also reports size 0 or missing. Progress may be inaccurate.")
                      self.total_size = 0 # Ensure it's 0 if unknown

             # Ensure output directory exists
             self.output_path.parent.mkdir(parents=True, exist_ok=True)

             with open(self.output_path, 'wb') as f:
                 for chunk in response.iter_content(self.chunk_size):
                     if self.is_cancelled:
                          print(f"[Downloader {self.download_id}] Fallback download cancelled.")
                          # Cleanup happens in the finally block of the main download() method
                          return False

                     if chunk:
                         bytes_written = f.write(chunk)
                         self._update_progress(bytes_written) # Update progress/speed

             # Final check after download completes
             # Only perform check if size was known
             if self.total_size > 0 and self.downloaded != self.total_size:
                 self.error = f"Fallback download size mismatch. Expected {self.total_size}, got {self.downloaded}."
                 print(f"Warning: [Downloader {self.download_id}] {self.error}")
                 # Don't automatically fail, but log warning. Let caller decide.
                 # Consider it success for now, but log clearly.

             print(f"[Downloader {self.download_id}] Fallback download completed.")
             return True

         except requests.exceptions.RequestException as e:
             error_msg_detail = f"{e}"
             if hasattr(e, 'response') and e.response is not None:
                  if e.response.status_code == 401: error_msg_detail += " (Unauthorized - Check API Key?)"
                  elif e.response.status_code == 403: error_msg_detail += " (Forbidden - Permissions Issue?)"
             self.error = f"Fallback download RequestException: {error_msg_detail}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             # Cleanup in download() finally block
             return False
         except Exception as e:
             self.error = f"Fallback download failed with unexpected error: {e}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             # Cleanup in download() finally block
             return False
         finally:
             if response:
                 response.close()

    def download(self) -> bool:
        """Starts the multi-threaded or fallback download process."""
        self._start_time = time.monotonic()
        success = False
        self.downloaded = 0 # Reset crucial state
        self.error = None

        # Make sure temp dir doesn't exist from a previous failed run
        if self.temp_dir.exists():
            print(f"Warning: Removing leftover temp directory: {self.temp_dir}")
            self._cleanup_temp(success=False) # Clean up including potential old output file

        # Check range support and get final URL. Handles its own errors.
        final_url, supports_ranges = self._get_range_support_and_url()
        # self.error might be set if HEAD failed

        # --- Decide Download Strategy ---
        # Use multi-connection if:
        # 1. Range requests ARE supported (HEAD request succeeded and confirmed support).
        # 2. Number of connections requested is > 1.
        # 3. We know the total file size (either from init or HEAD) and it's > 0.
        # 4. Optional: File size is large enough (prevents overhead for small files).
        MIN_SIZE_FOR_MULTI_MB = 10 # Lowered threshold slightly
        use_multi_connection = (
            supports_ranges and
            self.num_connections > 1 and
            self.total_size > 0 and
            self.total_size > MIN_SIZE_FOR_MULTI_MB * 1024 * 1024
        )

        # Store the initially calculated total_size for final check
        expected_final_size = self.total_size

        try:
            if use_multi_connection:
                # --- Attempt Multi-Connection Download ---
                self.connection_type = f"Multi ({self.num_connections})"
                if self.manager and self.download_id:
                    self.manager._update_download_status(self.download_id, connection_type=self.connection_type)

                print(f"[Downloader {self.download_id}] Starting multi-connection download for {self.output_path.name} "
                      f"({self.total_size / (1024 * 1024):.2f} MB) using {self.num_connections} connections.")

                # Ensure temp directory exists and is clean
                try:
                    if self.temp_dir.exists(): shutil.rmtree(self.temp_dir)
                    self.temp_dir.mkdir(parents=True)
                except Exception as e:
                    self.error = f"Failed to create temp directory {self.temp_dir}: {e}"
                    print(f"Error: [Downloader {self.download_id}] {self.error}")
                    return False # Cannot proceed without temp dir

                self.part_files = [] # Reset list of parts

                # Calculate segments
                segment_size = self.total_size // self.num_connections
                if segment_size == 0: # Handle tiny files if threshold was bypassed
                     segment_size = self.total_size
                segments = []
                current_byte = 0
                for i in range(self.num_connections):
                    if current_byte >= self.total_size: break
                    start_byte = current_byte
                    # Use min to prevent exceeding total_size, especially with integer division
                    end_byte = min(current_byte + segment_size - 1, self.total_size - 1)
                    # Ensure last segment goes exactly to the end
                    if i == self.num_connections - 1:
                         end_byte = self.total_size - 1

                    if start_byte <= end_byte < self.total_size:
                         segments.append((i, start_byte, end_byte))
                         self.part_files.append(self.temp_dir / f"part_{i}")
                    else:
                         # Should not happen with `min()` unless size is 0, which is checked earlier
                         print(f"Warning: [Downloader {self.download_id}] Skipping invalid segment {i}, start={start_byte}, end={end_byte}, total={self.total_size}")
                         break
                    current_byte = end_byte + 1

                if not segments:
                     self.error = "No valid download segments calculated for multi-connection."
                     print(f"Error: [Downloader {self.download_id}] {self.error}")
                     # Don't return yet, fallback might still work if size becomes known later
                     use_multi_connection = False # Force fallback

            # --- Fallback or Initial Single Connection ---
            if not use_multi_connection:
                 reason = "Range requests not supported" if not supports_ranges else \
                          "Single connection selected" if self.num_connections <= 1 else \
                          "File size unknown or too small" if self.total_size <= MIN_SIZE_FOR_MULTI_MB * 1024*1024 else \
                          "HEAD check failed" if self.error else \
                          "Segment calculation failed" # Add this case
                 print(f"[Downloader {self.download_id}] ({reason}). Using fallback single-connection download.")
                 # Fallback download handles setting connection_type and updating status
                 success = self.fallback_download()
                 # expected_final_size might be updated inside fallback_download if initially unknown
                 expected_final_size = self.total_size
                 # No merging needed for fallback. If it failed, `success` is False.
                 if not success and not self.error: # Ensure error is set if fallback returns false
                     self.error = self.error or "Single connection download failed."

            else:
                 # --- Start and Wait for Multi-Connection Threads ---
                 self.threads = []
                 for index, start, end in segments:
                     if self.is_cancelled: break
                     thread = threading.Thread(target=self.download_segment, args=(index, start, end), daemon=True)
                     self.threads.append(thread)
                     thread.start()

                 # --- Wait for threads ---
                 active_threads = list(self.threads)
                 while active_threads:
                     if self.is_cancelled:
                         print(f"[Downloader {self.download_id}] Cancellation detected during multi-download wait, stopping.")
                         self.error = self.error or "Cancelled"
                         break # Exit waiting loop

                     # Check thread status with a timeout
                     time.sleep(0.2)
                     active_threads = [t for t in active_threads if t.is_alive()]

                 # --- Post-Download Checks (Multi-Connection) ---
                 if self.is_cancelled: # Check again after loop exit
                      print(f"[Downloader {self.download_id}] Download stopped (cancelled).")
                      # Error should be set by cancel() or failing thread
                 elif self.error:
                      print(f"[Downloader {self.download_id}] Download stopped (error in thread): {self.error}")
                 elif self.downloaded != expected_final_size:
                      # Check size match ONLY if no cancellation/error occurred and size was known
                      if expected_final_size > 0:
                           self.error = f"Multi-download size mismatch. Expected {expected_final_size}, got {self.downloaded}."
                           print(f"Error: [Downloader {self.download_id}] {self.error}")
                      else:
                            # This case shouldn't be reachable because multi-conn requires known size > 0
                            print(f"Warning: Multi-download finished but expected size was unknown? Downloaded: {self.downloaded}")

                 # --- Merge Parts (only if no error/cancellation so far) ---
                 if not self.error and not self.is_cancelled:
                     merge_success = self.merge_parts()
                     if merge_success:
                          success = True
                          print(f"[Downloader {self.download_id}] Successfully downloaded and merged: {self.output_path}")
                     else:
                          # error should be set by merge_parts
                          print(f"Error: [Downloader {self.download_id}] Merge process failed.")
                          success = False
                 else:
                     # Download failed before merge stage
                     success = False

        except KeyboardInterrupt:
             print(f"[Downloader {self.download_id}] Interrupted! Signalling cancellation.")
             self.cancel()
             success = False
        except Exception as e:
              # Catch-all for unexpected errors in the main download logic
             import traceback
             print(f"--- Critical Error in Download {self.download_id} ('{self.output_path.name}') ---")
             traceback.print_exc()
             print("--- End Error ---")
             self.error = self.error or f"Unexpected download error: {str(e)}"
             success = False
        finally:
            # --- Cleanup ---
            # If successful, only cleanup temp dir.
            # If failed OR cancelled, cleanup temp AND the potentially incomplete output file.
            self._cleanup_temp(success=success)

            # Final status update via manager
            if self.manager and self.download_id:
                 final_status = "completed" if success else ("cancelled" if self.is_cancelled else "failed")
                 # Ensure progress is 100% on success, use last known otherwise
                 final_progress = 100.0 if success else (self.total_size > 0 and (self.downloaded / self.total_size * 100)) or 0
                 self.manager._update_download_status(
                     self.download_id,
                     status=final_status,
                     progress=min(100.0, final_progress), # Cap at 100
                     speed=0, # Final speed is 0
                     error=self.error,
                     connection_type=self.connection_type # Send final connection type
                 )

        return success