# ComfyUI_Civitai_Downloader/api/civitai.py
import requests
import json
from typing import List, Optional, Dict, Any, Union

class CivitaiAPI:
    """Simple wrapper for interacting with the Civitai API v1."""
    BASE_URL = "https://civitai.com/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers = {'Content-Type': 'application/json'}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
            print("[Civitai API] Using API Key.")
        else:
            print("[Civitai API] No API Key provided.")

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None,
                 json_data: Optional[Dict] = None, stream: bool = False,
                 allow_redirects: bool = True, timeout: int = 30) -> Union[Dict[str, Any], requests.Response, None]:
        """Makes a request to the Civitai API and handles basic errors."""
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        request_headers = self.headers.copy()

        # Don't send content-type for GET/HEAD if no json_data
        if method.upper() in ["GET", "HEAD"] and json_data is None:
            request_headers.pop('Content-Type', None)

        try:
            response = requests.request(
                method,
                url,
                headers=request_headers,
                params=params,
                json=json_data,
                stream=stream,
                allow_redirects=allow_redirects,
                timeout=timeout
            )
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            if stream:
                return response  # Return the response object for streaming

            # Handle No Content response (e.g., 204)
            if response.status_code == 204 or not response.content:
                return None

            return response.json()

        except requests.exceptions.HTTPError as http_err:
            error_detail = None
            status_code = http_err.response.status_code
            try:
                error_detail = http_err.response.json()
            except json.JSONDecodeError:
                error_detail = http_err.response.text[:200] # First 200 chars
            print(f"Civitai API HTTP Error ({method} {url}): Status {status_code}, Response: {error_detail}")
            # Return a structured error dictionary
            return {"error": f"HTTP Error: {status_code}", "details": error_detail, "status_code": status_code}

        except requests.exceptions.RequestException as req_err:
            print(f"Civitai API Request Error ({method} {url}): {req_err}")
            return {"error": str(req_err), "details": None, "status_code": None}

        except json.JSONDecodeError as json_err:
            print(f"Civitai API Error: Failed to decode JSON response from {url}: {json_err}")
            # Include response text if possible and not streaming
            response_text = response.text[:200] if not stream and hasattr(response, 'text') else "N/A"
            return {"error": "Invalid JSON response", "details": response_text, "status_code": response.status_code if hasattr(response, 'status_code') else None}

    def get_model_info(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Gets information about a model by its ID."""
        endpoint = f"/models/{model_id}"
        result = self._request("GET", endpoint)
        # Check if the result is an error dictionary
        if isinstance(result, dict) and "error" in result:
            return result # Propagate error dict
        return result # Return model info dict or None

    def get_model_version_info(self, version_id: int) -> Optional[Dict[str, Any]]:
        """Gets information about a specific model version by its ID."""
        endpoint = f"/model-versions/{version_id}"
        result = self._request("GET", endpoint)
        if isinstance(result, dict) and "error" in result:
            return result
        return result

    def get_download_url(self, version_id: int, file_id: Optional[int] = None, file_type: Optional[str] = None) -> Optional[str]:
        """
        Gets the actual download URL for a model version file.
        Handles potential redirects from the API endpoint.
        Returns the final redirect URL or None on error.
        """
        endpoint = f"/model-versions/{version_id}/download"
        params = {}
        if file_id:
            params["fileId"] = file_id
        if file_type:
            params["type"] = file_type # e.g., 'Model', 'Pruned Model'

        # Use HEAD request first to get redirect without downloading body
        # Allow redirects=False to capture the Location header ourselves
        head_resp = self._request("HEAD", endpoint, params=params, allow_redirects=False, timeout=20)

        if isinstance(head_resp, requests.Response):
            if head_resp.status_code in [301, 302, 307, 308] and 'Location' in head_resp.headers:
                print(f"Obtained download URL via HEAD redirect: {head_resp.headers['Location']}")
                return head_resp.headers['Location']
            else:
                print(f"Warning: HEAD request to download endpoint returned status {head_resp.status_code} without Location header.")
        elif isinstance(head_resp, dict) and "error" in head_resp:
             print(f"HEAD request for download URL failed: {head_resp}")
        else:
             print(f"Warning: Unexpected response type from HEAD request for download URL: {type(head_resp)}")

        # Fallback: Try GET request if HEAD didn't work (some servers might require GET)
        print("Falling back to GET request for download URL...")
        get_resp = self._request("GET", endpoint, params=params, allow_redirects=False, timeout=30, stream=True) # Stream might prevent accidental download

        redirect_url = None
        if isinstance(get_resp, requests.Response):
             if get_resp.status_code in [301, 302, 307, 308] and 'Location' in get_resp.headers:
                   redirect_url = get_resp.headers['Location']
                   print(f"Obtained download URL via GET redirect: {redirect_url}")
             else:
                   print(f"GET request to download endpoint also failed to redirect. Status: {get_resp.status_code}")
             # Close the connection if streaming
             get_resp.close()
        elif isinstance(get_resp, dict) and "error" in get_resp:
              print(f"GET request for download URL failed: {get_resp}")
        else:
             print(f"Warning: Unexpected response type from GET request for download URL: {type(get_resp)}")

        return redirect_url

    def search_models(self, query: str, types: Optional[List[str]] = None,
                      sort: str = 'Highest Rated', period: str = 'AllTime',
                      limit: int = 20, page: int = 1) -> Optional[Dict[str, Any]]:
        """Searches for models on Civitai."""
        endpoint = "/models"
        params = {
            "limit": max(1, min(100, limit)), # Ensure limit is reasonable
            "page": max(1, page),
            "query": query,
            "sort": sort,
            "period": period
        }
        if types:
            # API expects comma-separated string
            params["types"] = ",".join(types)

        result = self._request("GET", endpoint, params=params)
        if isinstance(result, dict) and "error" in result:
            return result
        # Ensure structure is as expected before returning
        if isinstance(result, dict) and "items" in result and "metadata" in result:
             return result
        else:
             print(f"Warning: Unexpected search result format: {result}")
             # Return a consistent empty structure on unexpected format
             return {"items": [], "metadata": {"totalItems": 0, "currentPage": page, "pageSize": limit, "totalPages": 0}}