// API client for Civicomfy UI
// Wraps ComfyUI's fetchApi with consistent error handling

import { api } from "../../../../scripts/api.js";

export class CivitaiDownloaderAPI {
  static async _request(endpoint, options = {}) {
    try {
      const url = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
      const response = await api.fetchApi(url, options);

      if (!response.ok) {
        let errorData;
        const status = response.status;
        const statusText = response.statusText;
        try {
          errorData = await response.json();
          if (typeof errorData !== "object" || errorData === null) {
            errorData = { detail: String(errorData) };
          }
        } catch (_) {
          const detailText = await response.text().catch(() => `Status ${status} - Could not read error text`);
          errorData = {
            error: `HTTP error ${status}`,
            details: String(detailText).substring(0, 500),
          };
        }
        const err = new Error(errorData.error || errorData.reason || `HTTP Error: ${status} ${statusText}`);
        err.details = errorData.details || errorData.detail || errorData.error || "No details provided.";
        err.status = status;
        throw err;
      }

      if (response.status === 204 || response.headers.get("Content-Length") === "0") {
        return null;
      }
      return await response.json();
    } catch (error) {
      if (!error.details) error.details = error.message;
      throw error;
    }
  }

  static async downloadModel(params) {
    return await this._request("/civitai/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  }

  static async getModelDetails(params) {
    return await this._request("/civitai/get_model_details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  }

  static async getStatus() {
    return await this._request("/civitai/status");
  }

  static async cancelDownload(downloadId) {
    return await this._request("/civitai/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ download_id: downloadId }),
    });
  }

  static async searchModels(params) {
    return await this._request("/civitai/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  }

  static async getBaseModels() {
    return await this._request("/civitai/base_models");
  }

  static async getModelTypes() {
    return await this._request("/civitai/model_types");
  }

  static async getModelDirs(modelType) {
    const q = encodeURIComponent(modelType || 'checkpoint');
    return await this._request(`/civitai/model_dirs?type=${q}`);
  }

  static async createModelDir(modelType, newDir) {
    return await this._request("/civitai/create_dir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_type: modelType, new_dir: newDir }),
    });
  }

  static async createModelType(name) {
    return await this._request("/civitai/create_model_type", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  static async getModelRoots(modelType) {
    const q = encodeURIComponent(modelType || 'checkpoint');
    return await this._request(`/civitai/model_roots?type=${q}`);
  }

  static async createModelRoot(modelType, absPath) {
    return await this._request("/civitai/create_root", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_type: modelType, path: absPath }),
    });
  }

  static async retryDownload(downloadId) {
    return await this._request("/civitai/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ download_id: downloadId }),
    });
  }

  static async openPath(downloadId) {
    return await this._request("/civitai/open_path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ download_id: downloadId }),
    });
  }

  static async clearHistory() {
    return await this._request("/civitai/clear_history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  }
}
