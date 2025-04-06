# ================================================
# File: downloader/chunk_downloader.py 
# Multi-connection somehow still not working
# ================================================

import requests
import threading
import time
import shutil
from pathlib import Path
import os
from typing import Optional, Dict, Tuple, Union, TYPE_CHECKING

# Import manager type hint without circular dependency during type checking
if TYPE_CHECKING:
    from .manager import DownloadManager

# Import config values
from ..config import DEFAULT_CHUNK_SIZE, DOWNLOAD_TIMEOUT, HEAD_REQUEST_TIMEOUT

class ChunkDownloader:
    """Handles downloading files in chunks using multiple connections or fallback."""
    # Constants
    STATUS_UPDATE_INTERVAL = 0.5
    HEAD_REQUEST_TIMEOUT = HEAD_REQUEST_TIMEOUT
    DOWNLOAD_TIMEOUT = DOWNLOAD_TIMEOUT
    MIN_SIZE_FOR_MULTI_MB = 100  # Minimum file size for multi-connection download

    def __init__(self, url: str, output_path: str, num_connections: int = 4,
                 chunk_size: int = DEFAULT_CHUNK_SIZE, manager: 'DownloadManager' = None,
                 download_id: str = None, api_key: Optional[str] = None,
                 known_size: Optional[int] = None):
        # URLs
        self.initial_url = url
        self.url = url
        
        # Paths
        self.output_path = Path(output_path)
        self.temp_dir = self.output_path.parent / f".{self.output_path.name}.parts_{download_id or int(time.time())}"
        
        # Download configuration
        self.num_connections = max(1, num_connections)
        self.chunk_size = chunk_size
        self.manager = manager
        self.download_id = download_id
        self.api_key = api_key
        self.known_size = known_size if known_size and known_size > 0 else None
        
        # Download state
        self.total_size = self.known_size or 0
        self.downloaded = 0
        self.connection_type = "N/A"
        self.error = None
        
        # Thread management
        self.threads = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.part_files = []
        
        # Performance tracking
        self._start_time = 0
        self._last_update_time = 0
        self._last_downloaded_bytes = 0
        self._speed = 0

    def _get_request_headers(self, add_range: Optional[str] = None) -> Dict[str, str]:
        """Constructs request headers with optional auth and range."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if add_range:
            headers['Range'] = add_range
        return headers

    @property
    def is_cancelled(self) -> bool:
        """Check if download has been cancelled."""
        return self.cancel_event.is_set()

    def cancel(self):
        """Signal the download to cancel."""
        if not self.is_cancelled:
            print(f"[Downloader {self.download_id or 'N/A'}] Cancellation requested by user.")
            self.cancel_event.set()
            self.error = "Download cancelled by user"
            if self.manager and self.download_id:
                self.manager._update_download_status(self.download_id, status="cancelled", error=self.error)

    def _cleanup_temp(self, success: bool):
        """Remove temporary directory and potentially the output file."""
        # Clean up temp directory
        if self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"[Downloader {self.download_id}] Warning: Could not remove temp directory {self.temp_dir}: {e}")

        # Remove output file if download failed
        if not success and self.output_path.exists():
            try:
                self.output_path.unlink()
                print(f"[Downloader {self.download_id}] Removed incomplete/failed output file: {self.output_path}")
            except Exception as e:
                print(f"[Downloader {self.download_id}] Warning: Could not remove incomplete output file {self.output_path}: {e}")

    def _get_range_support_and_url(self) -> Tuple[str, bool]:
        """Check for range support and get final URL after redirects."""
        final_url = self.initial_url
        supports_ranges = False
        
        try:
            request_headers = self._get_request_headers()
            
            print(f"[Downloader {self.download_id}] Checking range support/redirects for: {self.initial_url} (Timeout: {self.HEAD_REQUEST_TIMEOUT}s)")
            response = requests.head(
                self.initial_url,
                allow_redirects=True,
                timeout=self.HEAD_REQUEST_TIMEOUT,
                headers=request_headers
            )
            response.raise_for_status()

            # Update URL after redirects
            final_url = response.url
            self.url = final_url

            # Check range support
            accept_ranges = response.headers.get('accept-ranges', 'none').lower()
            supports_ranges = accept_ranges == 'bytes'

            # Get file size if not already known
            if self.total_size <= 0:
                head_size = int(response.headers.get('Content-Length', 0))
                if head_size > 0:
                    self.total_size = head_size
                    print(f"[Downloader {self.download_id}] Got file size from HEAD: {self.total_size} bytes")
            
            print(f"[Downloader {self.download_id}] HEAD Check OK - Final URL: {final_url}, Range Support: {supports_ranges}")
            return final_url, supports_ranges
            
        except requests.exceptions.Timeout:
            print(f"[Downloader {self.download_id}] Warning: HEAD request timed out. Proceeding with Single connection.")
            return self.initial_url, False
            
        except requests.exceptions.RequestException as e:
            http_error_details = ""
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                http_error_details = f" (Status Code: {status_code})"
            print(f"[Downloader {self.download_id}] Warning: HEAD request failed{http_error_details}. Proceeding with Single connection.")
            return self.initial_url, False
            
        except Exception as e:
            print(f"[Downloader {self.download_id}] Warning: Unexpected error during HEAD request: {e}. Proceeding with Single connection.")
            return self.initial_url, False

    def _update_progress(self, chunk_len: int):
        """Thread-safe update of download progress and speed calculation."""
        with self.lock:
            self.downloaded += chunk_len
            current_time = time.monotonic()
            time_diff = current_time - self._last_update_time

            # Update speed and notify manager periodically
            if time_diff >= self.STATUS_UPDATE_INTERVAL or self.downloaded == self.total_size:
                progress = min((self.downloaded / self.total_size) * 100, 100.0) if self.total_size > 0 else 0

                # Calculate speed
                if time_diff > 0:
                    bytes_diff = self.downloaded - self._last_downloaded_bytes
                    self._speed = bytes_diff / time_diff

                self._last_update_time = current_time
                self._last_downloaded_bytes = self.downloaded

                if self.manager and self.download_id:
                    self.manager._update_download_status(
                        self.download_id,
                        progress=progress,
                        speed=self._speed,
                        status="downloading"
                    )

    def download_segment(self, segment_index: int, start_byte: int, end_byte: int):
        """Downloads a specific segment of the file."""
        part_file_path = self.temp_dir / f"part_{segment_index}"
        request_headers = self._get_request_headers(add_range=f'bytes={start_byte}-{end_byte}')
        retries = 3
        
        for current_try in range(retries):
            if self.is_cancelled:
                print(f"[Downloader {self.download_id}] Segment {segment_index} cancelled before request (Try {current_try+1}).")
                # Ensure error is set if not already
                if not self.error: self.error = "Cancelled during segment download"
                return 
                
            response = None
            try:
                response = requests.get(self.url, headers=request_headers, stream=True, timeout=self.DOWNLOAD_TIMEOUT)
                response.raise_for_status()

                bytes_written_this_segment = 0
                with open(part_file_path, 'wb') as f:
                    for chunk in response.iter_content(self.chunk_size):
                        if self.is_cancelled:
                            print(f"[Downloader {self.download_id}] Segment {segment_index} cancelled mid-stream.")
                            # Ensure error is set if not already
                            if not self.error: self.error = "Cancelled during segment download"
                            
                            
                        if chunk:
                            bytes_written = f.write(chunk)
                            bytes_written_this_segment += bytes_written
                            self._update_progress(bytes_written)

                # Verify segment size
                expected_size = (end_byte - start_byte) + 1
                if bytes_written_this_segment != expected_size:
                    if response:
                        response.close()
                    raise ValueError(f"Size mismatch. Expected {expected_size}, got {bytes_written_this_segment}")

                return  # Success

            
            except (requests.exceptions.RequestException, ValueError) as e:
                # Handle HTTP status codes
                status_code = None
                error_msg_detail = f"{e}"
                
                if isinstance(e, requests.exceptions.RequestException) and hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 401: 
                        error_msg_detail += " (Unauthorized)"
                    elif status_code == 403: 
                        error_msg_detail += " (Forbidden)"
                    elif status_code == 416:
                        error_msg_detail += " (Range Not Satisfiable)"
                        self.error = f"Segment {segment_index} failed: {error_msg_detail}"
                        self.cancel()
                        return

                print(f"[Downloader {self.download_id}] Warning: Segment {segment_index} failed (Try {current_try+1}/{retries}): {error_msg_detail}")
                
                if current_try >= retries - 1:  # Last attempt failed
                    self.error = f"Segment {segment_index} failed after {retries} attempts: {error_msg_detail}"
                    self.cancel()
                    return
                    
                # Exponential backoff before retry
                time.sleep(min(2 ** current_try, 10))
                
            except Exception as e:
                self.error = f"Segment {segment_index} critical error: {e}"
                print(f"[Downloader {self.download_id}] Error: {self.error}")
                self.cancel()
                return
                
            finally:
                if response:
                    response.close()

    def merge_parts(self) -> bool:
        """Merges all downloaded part files into the final output file."""
        print(f"[Downloader {self.download_id}] Merging {len(self.part_files)} parts for {self.output_path.name}...")
        
        # Check if we have parts to merge
        if not self.part_files:
            if self.is_cancelled:
                self.error = self.error or "Cancelled before any parts downloaded."
            elif not self.error:
                self.error = "No part files were created to merge."
            print(f"[Downloader {self.download_id}] Error during merge: {self.error}")
            return False
            
        try:
            # Sort part files numerically
            sorted_part_files = sorted(self.part_files, key=lambda p: int(p.name.split('_')[-1]))

            with open(self.output_path, 'wb') as outfile:
                for part_file in sorted_part_files:
                    # Check if part exists
                    if not part_file.exists():
                        if self.is_cancelled:
                            self.error = self.error or "Cancelled during download, a part file is missing."
                        elif not self.error:
                            self.error = f"Merge failed, required part file is missing: {part_file}."
                        print(f"[Downloader {self.download_id}] Warning: Aborting merge. Missing part: {part_file.name}.")
                        return False

                    # Copy part data to output file
                    try:
                        with open(part_file, 'rb') as infile:
                            shutil.copyfileobj(infile, outfile, length=1024*1024*2)  # 2MB buffer
                    except Exception as copy_e:
                        self.error = f"Error copying data from part {part_file.name} during merge: {copy_e}"
                        print(f"[Downloader {self.download_id}] Error: {self.error}")
                        return False

            print(f"[Downloader {self.download_id}] Merging complete.")
            
            # Verify final file size
            final_size = self.output_path.stat().st_size
            if self.total_size > 0 and abs(final_size - self.total_size) > 1:
                self.error = f"Merged size ({final_size}) differs significantly from expected ({self.total_size}). File may be corrupt."
                print(f"[Downloader {self.download_id}] Error: {self.error}")
                return False
            elif self.total_size > 0 and final_size != self.total_size:
                print(f"[Downloader {self.download_id}] Warning: Final merged size ({final_size}) differs slightly from expected ({self.total_size}).")

            return True

        except Exception as e:
            self.error = f"Failed to merge parts: {e}"
            print(f"[Downloader {self.download_id}] Error: {self.error}")
            return False

    def fallback_download(self) -> bool:
        """Fallback to standard single-connection download."""
        self.connection_type = "Single"
        if self.manager and self.download_id:
            self.manager._update_download_status(self.download_id, connection_type=self.connection_type, status="downloading")

        print(f"[Downloader {self.download_id}] Using standard single-connection download for {self.output_path.name}...")
        
        self._start_time = self._start_time or time.monotonic()
        self._last_update_time = self._start_time
        self._last_downloaded_bytes = 0
        self.downloaded = 0
        
        response = None
        
        try:
            request_headers = self._get_request_headers()
            response = requests.get(self.url, stream=True, timeout=self.DOWNLOAD_TIMEOUT, 
                                    allow_redirects=True, headers=request_headers)
            response.raise_for_status()

            # Update URL after potential redirects
            final_get_url = response.url
            if final_get_url != self.url:
                print(f"[Downloader {self.download_id}] URL redirected during GET to: {final_get_url}")
                self.url = final_get_url

            # Get/confirm file size
            if self.total_size <= 0:
                get_size = int(response.headers.get('Content-Length', 0))
                if get_size > 0:
                    self.total_size = get_size
                    print(f"[Downloader {self.download_id}] Obtained file size via fallback GET: {self.total_size}")
                else:
                    print(f"[Downloader {self.download_id}] Warning: File size unknown. Progress may be inaccurate.")

            # Ensure output directory exists
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.output_path, 'wb') as f:
                for chunk in response.iter_content(self.chunk_size):
                    if self.is_cancelled:
                        print(f"[Downloader {self.download_id}] Fallback download cancelled.")
                        return False
                    if chunk:
                        bytes_written = f.write(chunk)
                        self._update_progress(bytes_written)

                    

            # Verify download size if known
            if self.total_size > 0 and self.downloaded != self.total_size and not self.error:
                print(f"[Downloader {self.download_id}] Warning: Size mismatch. Expected {self.total_size}, got {self.downloaded}.")

            print(f"[Downloader {self.download_id}] Fallback download completed.")
            return not self.error

        except requests.exceptions.RequestException as e:
            error_msg_detail = f"{e}"
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 401: 
                    error_msg_detail += " (Unauthorized - Check API Key?)"
                elif status_code == 403: 
                    error_msg_detail += " (Forbidden - Permissions Issue?)"
            
            if not self.error:
                self.error = f"Fallback download failed: {error_msg_detail}"
            print(f"[Downloader {self.download_id}] Error during fallback download: {self.error}")
            return False
            
        except Exception as e:
            if not self.error:
                self.error = f"Fallback download failed: {e}"
            print(f"[Downloader {self.download_id}] Error during fallback download: {self.error}")
            return False
            
        finally:
            if response:
                response.close()

    def download(self) -> bool:
        """Main download method that chooses between multi-connection or fallback approach."""
        self._start_time = time.monotonic()
        self.downloaded = 0
        self.error = None
        self.threads = []
        self.part_files = []
        success = False

        # Clean up any existing temp directory
        if self.temp_dir.exists():
            print(f"[Downloader {self.download_id}] Warning: Removing leftover temp directory: {self.temp_dir}")
            self._cleanup_temp(success=False)

        # Check range support and get final URL
        final_url, supports_ranges = self._get_range_support_and_url()
        
        # Decide on download strategy
        use_multi_connection = False
        if supports_ranges and self.num_connections > 1 and self.total_size > 0:
            if self.total_size > self.MIN_SIZE_FOR_MULTI_MB * 1024 * 1024:
                use_multi_connection = True
            else:
                print(f"[Downloader {self.download_id}] File size ({self.total_size / (1024*1024):.2f} MB) below threshold for multi-connection.")
        
        expected_final_size = self.total_size

        try:
            if use_multi_connection:
                # Multi-connection download approach
                success = self._do_multi_connection_download()
            else:
                # Single connection fallback
                reason = "Range requests not supported" if not supports_ranges else \
                         "Single connection requested" if self.num_connections <= 1 else \
                         "File size unknown or too small"
                print(f"[Downloader {self.download_id}] ({reason}). Using fallback single-connection download.")
                success = self.fallback_download()
                expected_final_size = self.total_size
                
                if not success and not self.error:
                    self.error = "Single connection download failed."

        except KeyboardInterrupt:
            print(f"[Downloader {self.download_id}] Interrupted! Signalling cancellation.")
            self.cancel()
            if not self.error: 
                self.error = "Download interrupted by user."
            success = False
            
        except Exception as e:
            import traceback
            print(f"--- Critical Error in Download {self.download_id} ('{self.output_path.name}') ---")
            traceback.print_exc()
            print("--- End Error ---")
            
            if not self.error:
                self.error = f"Unexpected download error: {str(e)}"
            
            success = False
            if not self.is_cancelled: 
                self.cancel()

        finally:
            # Cleanup and final status update
            self._cleanup_temp(success=success and not self.is_cancelled and not self.error)

            if self.manager and self.download_id:
                final_status = "completed" if success else ("cancelled" if self.is_cancelled else "failed")
                final_progress = 100.0 if success else ((self.downloaded / self.total_size * 100) if self.total_size > 0 else 0)
                
                self.manager._update_download_status(
                    self.download_id,
                    status=final_status,
                    progress=min(100.0, final_progress),
                    speed=0,
                    error=self.error,
                    connection_type=self.connection_type
                )

        return success and not self.error and not self.is_cancelled

    def _do_multi_connection_download(self) -> bool:
        """Handle multi-connection download process."""
        self.connection_type = f"Multi ({self.num_connections})"
        if self.manager and self.download_id:
            self.manager._update_download_status(self.download_id, connection_type=self.connection_type, status="downloading")

        print(f"[Downloader {self.download_id}] Starting multi-connection download for {self.output_path.name} "
              f"({self.total_size / (1024 * 1024):.2f} MB) using {self.num_connections} connections.")

        # Create temp directory
        try:
            if self.temp_dir.exists(): 
                shutil.rmtree(self.temp_dir)
            self.temp_dir.mkdir(parents=True)
        except Exception as e:
            self.error = f"Failed to create temp directory: {e}"
            print(f"[Downloader {self.download_id}] Error: {self.error}")
            return False

        # Calculate segments
        segment_size = self.total_size // self.num_connections
        
        # Handle small files with many connections
        if segment_size == 0 and self.total_size > 0:
            segment_size = self.total_size // min(self.num_connections, self.total_size) if self.total_size >= self.num_connections else self.total_size
            if segment_size == 0:
                segment_size = self.total_size
                self.num_connections = 1
                print(f"[Downloader {self.download_id}] Warning: Forcing single connection for very small file.")
                return self.fallback_download()

        # Create segments
        segments = []
        current_byte = 0
        for i in range(self.num_connections):
            if current_byte >= self.total_size: 
                break
                
            start_byte = current_byte
            end_byte = min(current_byte + segment_size - 1, self.total_size - 1)
            
            # Ensure last segment goes to the end
            if i == self.num_connections - 1:
                end_byte = self.total_size - 1

            # Ensure segment is valid
            if start_byte <= end_byte < self.total_size:
                segments.append((i, start_byte, end_byte))
                self.part_files.append(self.temp_dir / f"part_{i}")
            else:
                print(f"[Downloader {self.download_id}] Warning: Skipping invalid segment {i}, start={start_byte}, end={end_byte}")
            
            current_byte = end_byte + 1

        if not segments:
            self.error = f"No valid download segments calculated (Total Size: {self.total_size})."
            print(f"[Downloader {self.download_id}] Error: {self.error}")
            return False

        # Start download threads
        for index, start, end in segments:
            if self.is_cancelled: 
                break
            thread = threading.Thread(target=self.download_segment, args=(index, start, end), daemon=True)
            self.threads.append(thread)
            thread.start()

        # Wait for threads to complete
        active_threads = list(self.threads)
        while active_threads and not self.is_cancelled:
            joined_threads = []
            for t in active_threads:
                t.join(timeout=0.2)
                if not t.is_alive():
                    joined_threads.append(t)
            
            active_threads = [t for t in active_threads if t not in joined_threads]

        # Handle download completion
        if self.is_cancelled:
            print(f"[Downloader {self.download_id}] Download stopped (cancelled).")
            self.error = self.error or "Download cancelled."
            return False
        elif self.error:
            print(f"[Downloader {self.download_id}] Download stopped (error): {self.error}")
            return False
        elif self.total_size > 0 and self.downloaded != self.total_size:
            self.error = f"Multi-download size mismatch. Expected {self.total_size}, got {self.downloaded}."
            print(f"[Downloader {self.download_id}] Error: {self.error}")
            return False

        # Merge parts
        return self.merge_parts()