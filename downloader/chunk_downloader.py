# ComfyUI_Civitai_Downloader/downloader/chunk_downloader.py
import requests
import threading
import time
import shutil
from pathlib import Path
import os

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
                 download_id: str = None):
        self.url: str = url
        self.output_path: Path = Path(output_path)
        self.temp_dir: Path = self.output_path.parent / f".{self.output_path.name}.parts_{download_id or int(time.time())}"
        self.num_connections: int = max(1, num_connections) # Ensure at least 1
        self.chunk_size: int = chunk_size # Chunk size for reading response content
        self.manager: 'DownloadManager' = manager
        self.download_id: str = download_id

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

    def get_file_info(self) -> tuple[int, bool]:
        """Get the size of the file and check for range support."""
        try:
            # Use HEAD request with a Range header to check for range support more reliably
            response = requests.head(self.url, allow_redirects=True, timeout=20, headers={'Range': 'bytes=0-0'})
            response.raise_for_status()

            # Follow redirects if needed (requests.head handles this automatically if allow_redirects=True)
            self.url = response.url # Update URL to the final destination after redirects

            size = int(response.headers.get('content-length', 0))
            # Check if 'bytes' is explicitly in accept-ranges or if content-range is returned for 0-0 request
            accept_ranges = response.headers.get('accept-ranges', 'none').lower() == 'bytes'
            content_range = response.headers.get('content-range', None)
            range_supported = accept_ranges or (content_range is not None and content_range.startswith('bytes'))

            if size <= 0:
                 print("Warning: Reported file size is 0 or missing.")
                 # Optionally try GET request to double check size? For now, trust HEAD.

            return size, range_supported
        except requests.exceptions.RequestException as e:
            self.error = f"Failed to get file info: {e}"
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
            if time_diff >= self.STATUS_UPDATE_INTERVAL:
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
        headers = {'Range': f'bytes={start_byte}-{end_byte}'}
        retries = 3
        current_try = 0
        segment_url = self.url # Use the potentially redirected URL

        while current_try < retries and not self.is_cancelled:
            try:
                # print(f"Thread {segment_index}: Requesting range {start_byte}-{end_byte} from {segment_url}")
                response = requests.get(segment_url, headers=headers, stream=True, timeout=60) # Longer timeout for active download
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
                   # This might happen with flaky connections, retry?
                    raise ValueError(f"Size mismatch. Expected {expected_size}, got {bytes_written_this_segment}")

                # print(f"Thread {segment_index}: Finished range {start_byte}-{end_byte}")
                return # Success for this segment

            except requests.exceptions.RequestException as e:
                current_try += 1
                error_msg = f"Segment {segment_index} failed (Try {current_try}/{retries}): {e}"
                print(f"Warning: [Downloader {self.download_id}] {error_msg}")
                if current_try >= retries:
                    self.error = error_msg # Set final error
                    self.cancel() # Signal other threads to stop if one fails critically
                    print(f"Error: [Downloader {self.download_id}] Segment {segment_index} giving up.")
                    return
                # Exponential backoff before retry
                time.sleep(min(2 ** current_try, 10)) # Sleep max 10s between retries

            except Exception as e: # Catch other errors like ValueError
                 self.error = f"Segment {segment_index} critical error: {e}"
                 print(f"Error: [Downloader {self.download_id}] {self.error}")
                 self.cancel() # Signal cancellation on critical error
                 return
            finally:
                 # Ensure response is closed if loop terminates unexpectedly
                 if 'response' in locals() and response:
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
                           raise FileNotFoundError(f"Missing part file: {part_file}")
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
                  print(f"Warning: [Downloader {self.download_id}] Final merged size ({final_size}) differs from expected ({self.total_size}).")
             return True

        except Exception as e:
            self.error = f"Failed to merge parts: {e}"
            print(f"Error: [Downloader {self.download_id}] {self.error}")
            # If merge fails, the output file might be corrupt
            if self.output_path.exists():
                 try:
                      self.output_path.unlink()
                      print(f"Removed failed merge output: {self.output_path}")
                 except Exception as unlink_e:
                      print(f"Warning: Could not remove failed merge output {self.output_path}: {unlink_e}")
            return False

    def fallback_download(self) -> bool:
         """Fallback to standard single-connection download."""
         print(f"[Downloader {self.download_id}] Using standard single-connection download for {self.output_path.name}...")
         self._start_time = time.monotonic()
         self._last_update_time = self._start_time
         self._last_downloaded_bytes = 0
         self.downloaded = 0

         try:
             response = requests.get(self.url, stream=True, timeout=60, allow_redirects=True)
             response.raise_for_status()

             # Update size if not already known or was 0
             if self.total_size <= 0:
                 self.total_size = int(response.headers.get('content-length', 0))
                 if self.total_size <= 0:
                      print("Warning: Fallback download also reports size 0. Proceeding anyway.")

             with open(self.output_path, 'wb') as f:
                 for chunk in response.iter_content(self.chunk_size):
                     if self.is_cancelled:
                          print(f"[Downloader {self.download_id}] Fallback download cancelled.")
                          self._cleanup_temp(success=False)
                          return False

                     if chunk:
                         bytes_written = f.write(chunk)
                         self._update_progress(bytes_written)

             # Final check after download completes
             if self.total_size > 0 and self.downloaded != self.total_size:
                 print(f"Warning: [Downloader {self.download_id}] Fallback download size mismatch. Expected {self.total_size}, got {self.downloaded}.")
                 # Don't automatically fail, but log warning.

             print(f"[Downloader {self.download_id}] Fallback download completed.")
             return True

         except requests.exceptions.RequestException as e:
             self.error = f"Fallback download failed: {e}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False
         except Exception as e:
             self.error = f"Fallback download failed with unexpected error: {e}"
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False
         finally:
             if 'response' in locals() and response:
                 response.close()

    def download(self) -> bool:
        """Starts the multi-threaded or fallback download process."""
        self._start_time = time.monotonic()
        self.total_size, supports_ranges = self.get_file_info()

        if self.error: # If get_file_info already failed
            self._cleanup_temp(success=False)
            return False
        if self.total_size <= 0:
            print("File size is 0 or unavailable. Attempting fallback download.")
            # Fallback might still work if server didn't report size correctly in HEAD
            success = self.fallback_download()
            self._cleanup_temp(success=success)
            return success

        use_multi_connection = supports_ranges and self.num_connections > 1
        if not use_multi_connection:
             print("Range requests not supported or single connection selected. Using fallback.")
             success = self.fallback_download()
             # Fallback handles its own cleanup on error
             return success

        # --- Proceed with Multi-Connection Download ---
        print(f"[Downloader {self.download_id}] Starting multi-connection download for {self.output_path.name} "
              f"({self.total_size / (1024 * 1024):.2f} MB) using {self.num_connections} connections.")

        # Ensure temp directory exists and is clean
        if self.temp_dir.exists():
             shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True)
        self.part_files = [] # Reset list of parts for this download attempt

        # Calculate segments based on connections
        segment_size = self.total_size // self.num_connections
        segments = []
        current_byte = 0
        for i in range(self.num_connections):
            start_byte = current_byte
            end_byte = current_byte + segment_size - 1
            # Last segment takes the remainder
            if i == self.num_connections - 1:
                 end_byte = self.total_size - 1

            # Avoid creating segment if start > end (can happen if total_size < num_connections)
            if start_byte <= end_byte:
                 segments.append((i, start_byte, end_byte))
                 # Add part file path to the list expected for merging
                 self.part_files.append(self.temp_dir / f"part_{i}")

            current_byte = end_byte + 1

        if not segments:
             self.error = "No segments calculated (total size might be too small for connections)."
             print(f"Error: [Downloader {self.download_id}] {self.error}")
             self._cleanup_temp(success=False)
             return False

        # Create and start download threads
        self.threads = []
        for index, start, end in segments:
            if self.is_cancelled: break # Check before starting new threads
            thread = threading.Thread(target=self.download_segment, args=(index, start, end), daemon=True)
            self.threads.append(thread)
            thread.start()

        # Simple wait loop to allow cancellation check while waiting
        while any(t.is_alive() for t in self.threads):
            if self.is_cancelled:
                print(f"[Downloader {self.download_id}] Cancellation detected, waiting for threads to exit...")
                # No need to explicitly join if daemon=True, they will exit.
                # Give them a moment to finish writing/close connections.
                time.sleep(1)
                break
            time.sleep(0.2) # Check threads status periodically

        # Check for overall download success
        if self.is_cancelled or self.error:
            print(f"[Downloader {self.download_id}] Download stopped early. Cancelled: {self.is_cancelled}, Error: {self.error}")
            self._cleanup_temp(success=False)
            return False

        # Verify downloaded size (basic check) after threads potentially finish
        if self.downloaded != self.total_size:
             print(f"Warning: [Downloader {self.download_id}] Final downloaded bytes ({self.downloaded}) "
                   f"does not match expected total size ({self.total_size}). Merging process might fail or file may be incomplete.")
             # Optionally: treat this as an error? For now, just warn.
             # self.error = "Downloaded size mismatch"
             # self._cleanup_temp(success=False)
             # return False

        # -------- Merge the parts --------
        merge_success = self.merge_parts()
        self._cleanup_temp(success=merge_success) # Cleanup temp files after merge attempt

        if merge_success:
            print(f"[Downloader {self.download_id}] Successfully downloaded and merged: {self.output_path}")
            # Final status update (will be done by manager wrapper)
        else:
             # Error already set by merge_parts if it failed
             print(f"Error: [Downloader {self.download_id}] Merge process failed.")

        return merge_success