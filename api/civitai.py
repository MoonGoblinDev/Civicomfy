# ================================================
# File: api/civitai.py
# ================================================
import requests
import json
from typing import List, Optional, Dict, Any, Union

class CivitaiAPI:
    """Simple wrapper for interacting with the Civitai API v1."""
    BASE_URL = "https://civitai.com/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_headers = {'Content-Type': 'application/json'}
        if api_key:
            self.base_headers["Authorization"] = f"Bearer {api_key}"
            print("[Civitai API] Using API Key.")
        else:
            print("[Civitai API] No API Key provided.")

    def _get_request_headers(self, method: str, has_json_data: bool) -> Dict[str, str]:
        """Returns headers for a specific request."""
        headers = self.base_headers.copy()
        # Don't send content-type for GET/HEAD if no json_data
        if method.upper() in ["GET", "HEAD"] and not has_json_data:
            headers.pop('Content-Type', None)
        return headers

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None,
                 json_data: Optional[Dict] = None, stream: bool = False,
                 allow_redirects: bool = True, timeout: int = 30) -> Union[Dict[str, Any], requests.Response, None]:
        """Makes a request to the Civitai API and handles basic errors."""
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        request_headers = self._get_request_headers(method, json_data is not None)

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
        """Gets information about a model by its ID. (GET /models/{id})"""
        endpoint = f"/models/{model_id}"
        result = self._request("GET", endpoint)
        # Check if the result is an error dictionary
        if isinstance(result, dict) and "error" in result:
            return result # Propagate error dict
        return result # Return model info dict or None

    def get_model_version_info(self, version_id: int) -> Optional[Dict[str, Any]]:
        """Gets information about a specific model version by its ID. (GET /model-versions/{id})"""
        endpoint = f"/model-versions/{version_id}"
        result = self._request("GET", endpoint)
        if isinstance(result, dict) and "error" in result:
            return result
        return result

    def search_models(self, query: str, types: Optional[List[str]] = None,
                      sort: str = 'Highest Rated', period: str = 'AllTime',
                      limit: int = 20, page: int = 1,
                      nsfw: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """Searches for models on Civitai. (GET /models)"""
        endpoint = "/models"
        params = {
            "limit": max(1, min(100, limit)), # Ensure limit is reasonable
            "page": max(1, page),
            "query": query,
            "sort": sort,
            "period": period
        }
        if types:
            # `requests` handles lists by appending multiple key=value pairs,
            # which matches the expectation for 'array' type in the API doc.
             params["types"] = types
        if nsfw is not None:
            params["nsfw"] = str(nsfw).lower() # API expects string "true" or "false"

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