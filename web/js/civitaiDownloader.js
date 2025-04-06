import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

console.log("Loading Civicomfy UI...");

// --- Configuration ---
const EXTENSION_NAME = "Civicomfy"; // Matches Python WEB_DIRECTORY
const CSS_URL = `./civitaiDownloader.css`;
const PLACEHOLDER_IMAGE_URL = `./placeholder.png`;
const SETTINGS_COOKIE_NAME = 'civitaiDownloaderSettings'; // Cookie name

// --- Cookie Helper Functions ---
function setCookie(name, value, days) {
    let expires = "";
    if (days) {
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = "; expires=" + date.toUTCString();
    }
    // Use SameSite=Lax for reasonable security and usability within the domain
    document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax";
    // console.log("Setting cookie:", name, "=", value, "; expires=", expires);
}

function getCookie(name) {
    const nameEQ = name + "=";
    const ca = document.cookie.split(';');
    for (let i = 0; i < ca.length; i++) {
        let c = ca[i];
        while (c.charAt(0) == ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) == 0) {
            const value = c.substring(nameEQ.length, c.length);
            // console.log("Found cookie:", name, "=", value);
            return value;
        }
    }
    // console.log("Cookie not found:", name);
    return null;
}

function deleteCookie(name) {
    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT; SameSite=Lax';
}

// --- CSS Injection ---
function addCssLink() {
    // Check if already added
    if (document.getElementById('civitai-downloader-styles')) return;

    const cssPath = import.meta.resolve(CSS_URL);
	//console.log(cssPath);
	const $link = document.createElement("link");
    $link.id = 'civitai-downloader-styles'; // Add ID for checking
	$link.setAttribute("rel", 'stylesheet');
	$link.setAttribute("href", cssPath);
	document.head.appendChild($link);
}

// Add Menu Button to ComfyUI
function addMenuButton() {
    // Target the main button group directly
    const buttonGroup = document.querySelector(".comfyui-button-group");

    if (!buttonGroup) {
        console.warn("[Civicomfy] ComfyUI button group (.comfyui-button-group) not found yet. Retrying...");
        setTimeout(addMenuButton, 500); // Retry after a short delay
        return;
    }

    // Prevent adding the button multiple times if script re-runs or retries
    if (document.getElementById("civitai-downloader-button")) {
        console.log("[Civicomfy] Button already exists.");
        return;
    }

    const civitaiButton = document.createElement("button");
    civitaiButton.textContent = "Civicomfy";
    civitaiButton.id = "civitai-downloader-button";
    civitaiButton.title = "Open Civicomfy";

    civitaiButton.onclick = async () => { // Make onclick async
        // Initialize the UI class instance ONCE on the first click
        if (!window.civitaiDownloaderUI) {
            console.info("[Civicomfy] Creating CivitaiDownloaderUI instance...");
            window.civitaiDownloaderUI = new CivitaiDownloaderUI(); // Builds HTML, caches elements, sets default settings
            document.body.appendChild(window.civitaiDownloaderUI.modal); // Append modal structure to body

            // Initialize UI components (fetch types, base models, load/apply settings)
            try {
                 await window.civitaiDownloaderUI.initializeUI();
                 console.info("[Civicomfy] UI Initialization complete.");
            } catch (error) {
                 console.error("[Civicomfy] Error during UI initialization:", error);
                 // Attempt to show a toast even if initialization failed partially
                 if (window.civitaiDownloaderUI && window.civitaiDownloaderUI.showToast) {
                     window.civitaiDownloaderUI.showToast("Error initializing UI components. Check console.", "error", 5000);
                 }
            }
        }
        // Always open the (potentially newly created and initialized) modal
        if (window.civitaiDownloaderUI) {
            window.civitaiDownloaderUI.openModal();
        } else {
             // Fallback if initialization failed very early
             console.error("[Civicomfy] Cannot open modal: UI instance not available.");
             alert("Civicomfy failed to initialize. Please check the browser console for errors.");
        }
    };

    // Append the new button to the main button group
    buttonGroup.appendChild(civitaiButton);
    console.log("[Civicomfy] Civicomfy button added to .comfyui-button-group.");

    // Fallback logic (remains the same)
    const menu = document.querySelector(".comfy-menu");
    if (!buttonGroup.contains(civitaiButton) && menu && !menu.contains(civitaiButton)) {
        console.warn("[Civicomfy] Failed to append button to group, falling back to menu.");
        const settingsButton = menu.querySelector("#comfy-settings-button");
        if (settingsButton) {
            settingsButton.insertAdjacentElement("beforebegin", civitaiButton);
        } else {
            menu.appendChild(civitaiButton);
        }
    }
}

// API Interface (No changes needed based on request, assuming previous fixes were good)
class CivitaiDownloaderAPI {
    static async _request(endpoint, options = {}) {
        try {
            
            // Add prefix if it doesn't exist
            const url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
            const response = await api.fetchApi(url, options); // Use api.fetchApi directly

            if (!response.ok) {
                let errorData;
                const status = response.status;
                const statusText = response.statusText;
                try {
                    // Try parsing JSON first
                    errorData = await response.json();
                     // Ensure errorData is an object
                     if (typeof errorData !== 'object' || errorData === null) {
                        errorData = { detail: String(errorData) }; // Wrap non-object detail
                    }

                } catch (jsonError) {
                     // If JSON parsing fails, read response as text
                    let detailText = await response.text().catch(() => `Status ${status} - Could not read error text`);
                    errorData = {
                        error: `HTTP error ${status}`,
                        details: detailText.substring(0, 500), // Limit length
                    };
                 }
                console.error(`API Error: ${options.method || 'GET'} ${url} -> ${status}`, errorData);

                // Construct a more informative error message
                const error = new Error(
                    errorData.error || errorData.reason || `HTTP Error: ${status} ${statusText}`
                );
                // Try to extract the most useful detail field
                error.details = errorData.details || errorData.detail || errorData.error || 'No details provided.';
                error.status = status;

                throw error;
            }
            // Handle empty response body for success codes like 204
             if (response.status === 204 || response.headers.get('Content-Length') === '0') {
                return null;
            }
            // Assume JSON response for other success codes
            return await response.json();
        } catch (error) {
            // Re-throw the error (could be the custom one created above or a network/parsing error)
             console.error(`API Request Failed: ${options.method || 'GET'} ${endpoint}`, error);
             // Ensure it has a user-friendly message if it's not our custom error
             if (!error.details) {
                 error.details = error.message;
             }
             throw error;
        }
    }

    static async downloadModel(params) {
        return await this._request('/civitai/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });
    }

    static async getModelDetails(params) {
        return await this._request('/civitai/get_model_details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });
    }

    static async getStatus() {
        return await this._request('/civitai/status');
    }

    static async cancelDownload(downloadId) {
        return await this._request('/civitai/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_id: downloadId }),
        });
    }

    static async searchModels(params) {
        return await this._request('/civitai/search', { // Endpoint URL is the same
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params), // Send new params including base_models
        });
    }

    // Add method to fetch base models for the filter dropdown
    static async getBaseModels() {
        return await this._request('/civitai/base_models');
    }

    static async getModelTypes() {
        return await this._request('/civitai/model_types');
    }
}

// --- UI Class ---
class CivitaiDownloaderUI {
    constructor() {
        this.modal = null;
        this.tabs = {};
        this.tabContents = {};
        this.activeTab = 'download'; // Default tab
        this.modelTypes = {}; // { internal_key: display_name }
        this.statusInterval = null;
        this.statusData = { queue: [], active: [], history: [] };
        this.baseModels = [];
        this.searchPagination = { currentPage: 1, totalPages: 1, limit: 20 }; // Consistent limit
        this.settings = this.getDefaultSettings(); // Initialize with defaults first
        this.toastTimeout = null;
        this.modelPreviewDebounceTimeout = null;
        this.downloadHistoryCookieName = 'civitaiDownloadHistory';
        this.maxHistoryItems = 50; // Limit history size
        this.updateStatus();

        this.buildModalHTML(); // Creates this.modal element
        this.cacheDOMElements();
        this.setupEventListeners();
        // NOTE: Loading settings and populating dropdowns now happens *after* initialization
        // in addMenuButton -> loadAndApplySettings / populateModelTypes
    }

    getDefaultSettings() {
         return {
            apiKey: '',
            numConnections: 1,
            defaultModelType: 'checkpoint',
            autoOpenStatusTab: true,
            searchResultLimit: 10, // Added default
            // Add other future settings here with defaults
        };
    }

    loadAndApplySettings() {
        console.log("[Civicomfy] Loading settings...");
        this.settings = this.loadSettingsFromCookie(); // Load from cookie or get defaults
        console.log("[Civicomfy] Applying settings...", this.settings);
        this.applySettings(); // Apply loaded settings to UI
    }

    loadSettingsFromCookie() {
        const defaults = this.getDefaultSettings();
        const cookieValue = getCookie(SETTINGS_COOKIE_NAME);

        if (cookieValue) {
            try {
                const loadedSettings = JSON.parse(cookieValue);
                // Merge defaults with loaded to ensure all keys exist
                console.log("[Civicomfy] Settings loaded from cookie:", loadedSettings);
                return { ...defaults, ...loadedSettings };
            } catch (e) {
                console.error("Failed to parse settings cookie:", e);
                // Optionally delete the corrupted cookie
                // deleteCookie(SETTINGS_COOKIE_NAME);
                return defaults; // Fallback to defaults
            }
        } else {
            console.log("[Civicomfy] No settings cookie found, using defaults.");
            return defaults; // No cookie, use defaults
        }
    }

    saveSettingsToCookie() {
        try {
            const settingsString = JSON.stringify(this.settings);
            setCookie(SETTINGS_COOKIE_NAME, settingsString, 365); // Save for 1 year
            console.log("[Civicomfy] Settings saved to cookie:", this.settings);
            this.showToast('Settings saved successfully!', 'success');
        } catch (e) {
            console.error("Failed to save settings to cookie:", e);
            this.showToast('Error saving settings', 'error');
        }
    }

    loadHistoryFromCookie() {
        const cookieValue = getCookie(this.downloadHistoryCookieName);
        if (cookieValue) {
            try {
                const history = JSON.parse(cookieValue);
                if (Array.isArray(history)) {
                    this.statusData.history = history; // Load into statusData
                    console.log("[Civicomfy] Download history loaded from cookie.");
                    return; // Exit if successful.
                } else {
                    console.warn("[Civicomfy] Invalid history format from cookie.");
                }
            } catch (error) {
                console.error("[Civicomfy] Failed to parse download history cookie:", error);
                // Optionally delete the corrupted cookie
                 deleteCookie(this.downloadHistoryCookieName);
            }
        }
        console.log("[Civicomfy] No download history cookie found or invalid, using default.");
        // If cookie doesn't exist or fails to parse, use the existing logic
    }

    saveHistoryToCookie() {
        try {
            // Limit and stringify the history
            const limitedHistory = this.statusData.history.slice(0, this.maxHistoryItems);  // Only store recent items
            const historyString = JSON.stringify(limitedHistory); // Stringify for the storage.
            setCookie(this.downloadHistoryCookieName, historyString, 30); // Expires in 30 days
            console.log("[Civicomfy] Download history saved to cookie.");
        } catch (error) {
            console.error("[Civicomfy] Failed to save download history to cookie:", error);
        }
    }

    applySettings() {
        // Make sure elements exist before trying to set values
        if (this.settingsApiKeyInput) {
            this.settingsApiKeyInput.value = this.settings.apiKey || '';
        }
        if (this.settingsConnectionsInput) {
             // Ensure value is within bounds if loaded value is weird
            this.settingsConnectionsInput.value = Math.max(1, Math.min(16, this.settings.numConnections || 4));
        }
        if (this.settingsDefaultTypeSelect) {
             // This requires modelTypes to be populated first, handle in populateModelTypes or ensure order
             this.settingsDefaultTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
        }
        if (this.settingsAutoOpenCheckbox) {
            this.settingsAutoOpenCheckbox.checked = this.settings.autoOpenStatusTab === true; // Explicit boolean check
        }
        // Apply to download form defaults as well
        if (this.downloadConnectionsInput) {
             this.downloadConnectionsInput.value = Math.max(1, Math.min(16, this.settings.numConnections || 4));
        }
        if (this.downloadModelTypeSelect) {
            // Check if modelTypes are loaded before setting
            if (Object.keys(this.modelTypes).length > 0) {
                 this.downloadModelTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
            } else {
                 // If types not loaded, might need to re-apply later in populateModelTypes
                 console.warn("[Civicomfy] Cannot apply default model type yet, types not loaded.");
            }
        }

        // Apply search result limit if we add that setting
        this.searchPagination.limit = this.settings.searchResultLimit || 10;
        // Update placeholder if search limit setting exists
         // if(this.settingsSearchResultLimitInput) {
         //      this.settingsSearchResultLimitInput.value = this.searchPagination.limit;
         // }
    }

    async initializeUI() {
        // This might be called after the modal is created and elements are cached
        console.info("[Civicomfy] Initializing UI components...");
        await this.populateModelTypes(); // Fetch model types first (essential for defaults)
        await this.populateBaseModels(); // Fetch base models for search filter
        this.loadAndApplySettings(); // Load and apply settings AFTER types are loaded
    }

    buildModalHTML() {
        this.modal = document.createElement('div');
        this.modal.className = 'civitai-downloader-modal';
        this.modal.id = 'civitai-downloader-modal';
        // HTML structure including Settings Tab
        this.modal.innerHTML = `
            <div class="civitai-downloader-modal-content">
                <div class="civitai-downloader-header">
                    <h2>Civicomfy</h2>
                    <button class="civitai-close-button" id="civitai-close-modal">&times;</button>
                </div>
                <div class="civitai-downloader-body">
                    <div class="civitai-downloader-tabs">
                        <button class="civitai-downloader-tab active" data-tab="download">Download</button>
                        <button class="civitai-downloader-tab" data-tab="search">Search</button>
                        <button class="civitai-downloader-tab" data-tab="status">Status <span id="civitai-status-indicator" style="display: none;">(<span id="civitai-active-count">0</span>)</span></button>
                        <button class="civitai-downloader-tab" data-tab="settings">Settings</button>
                    </div>
                    <div id="civitai-tab-download" class="civitai-downloader-tab-content active">
                        <form id="civitai-download-form">
                            <div class="civitai-form-group">
                                <label for="civitai-model-url">Model URL or ID</label>
                                <input type="text" id="civitai-model-url" class="civitai-input" placeholder="e.g., https://civitai.com/models/12345 or 12345" required>
                            </div>
                            <p style="font-size: 0.9em; color: #ccc; margin-top: -10px; margin-bottom: 15px;">You can optionally specify a version ID using "?modelVersionId=xxxxx" in the URL or in the field below.</p>
                            <div class="civitai-form-row">
                                <div class="civitai-form-group">
                                    <label for="civitai-model-type">Model Type (Save Location)</label>
                                    <select id="civitai-model-type" class="civitai-select" required></select>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-model-version-id">Version ID (Optional)</label>
                                    <input type="number" id="civitai-model-version-id" class="civitai-input" placeholder="Overrides URL/Latest">
                                </div>
                            </div>
                             <div class="civitai-form-row">
                                <div class="civitai-form-group">
                                    <label for="civitai-custom-filename">Custom Filename (Optional)</label>
                                    <input type="text" id="civitai-custom-filename" class="civitai-input" placeholder="Leave blank to use original name">
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-connections">Connections</label>
                                    <input type="number" id="civitai-connections" class="civitai-input" value="${this.settings.numConnections}" min="1" max="16" step="1" required>
                                </div>
                            </div>
                            <div class="civitai-form-group inline">
                                 <input type="checkbox" id="civitai-force-redownload" class="civitai-checkbox">
                                <label for="civitai-force-redownload">Force Re-download (if exists)</label>
                            </div>

                            <div id="civitai-download-preview-area" class="civitai-download-preview-area" style="margin-top: 25px; padding-top: 15px; border-top: 1px solid var(--border-color, #444);">
                            <!-- Preview content will be injected here -->
                            </div>

                            <button type="submit" id="civitai-download-submit" class="civitai-button primary">Start Download</button>
                        </form>
                    </div>
                    <div id="civitai-tab-search" class="civitai-downloader-tab-content">
                        <form id="civitai-search-form">
                            <div class="civitai-search-controls">
                                <input type="text" id="civitai-search-query" class="civitai-input" placeholder="Search Civitai..."> <!-- Remove required -->
                                <select id="civitai-search-type" class="civitai-select">
                                    <option value="any">Any Type</option>
                                    <!-- Model types populated here -->
                                </select>
                                <!-- ADDED: Base Model Filter Dropdown -->
                                <select id="civitai-search-base-model" class="civitai-select">
                                    <option value="any">Any Base Model</option>
                                    <!-- Base models populated here -->
                                </select>
                                <select id="civitai-search-sort" class="civitai-select">
                                    <option value="Relevancy">Relevancy</option>
                                    <option value="Highest Rated">Highest Rated</option>
                                    <option value="Most Liked">Most Liked</option>
                                    <option value="Most Discussed">Most Discussed</option> 
                                    <option value="Most Collected">Most Collected</option>
                                    <option value="Most Buzz">Most Buzz</option>
                                    <option value="Most Downloaded">Most Downloaded</option>
                                    <option value="Newest">Newest</option>
                                </select>
                            </div>
                        <button type="submit" id="civitai-search-submit" class="civitai-button primary">Search</button>
                        </form>
                        <div id="civitai-search-results" class="civitai-search-results">
                            <!-- Search results -->
                        </div>
                        <div id="civitai-search-pagination" style="text-align: center; margin-top: 20px;">
                            <!-- Pagination -->
                        </div>
                    </div>
                    <div id="civitai-tab-status" class="civitai-downloader-tab-content">
                        <div id="civitai-status-content">
                             <div class="civitai-status-section">
                                <h3>Active Downloads</h3>
                                <div id="civitai-active-list" class="civitai-download-list">
                                    <p>No active downloads.</p>
                                </div>
                            </div>
                             <div class="civitai-status-section">
                                <h3>Queued Downloads</h3>
                                <div id="civitai-queued-list" class="civitai-download-list">
                                    <p>Download queue is empty.</p>
                                </div>
                            </div>
                             <div class="civitai-status-section">
                                <h3>Download History (Recent)</h3>
                                <div id="civitai-history-list" class="civitai-download-list">
                                    <p>No download history yet.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div id="civitai-tab-settings" class="civitai-downloader-tab-content">
                        <form id="civitai-settings-form">
                         <div class="civitai-settings-container">
                             <div class="civitai-settings-section">
                                 <h4>API & Defaults</h4>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-api-key">Civitai API Key (Optional)</label>
                                    <input type="password" id="civitai-settings-api-key" class="civitai-input" placeholder="Enter API key for higher limits / authenticated access" autocomplete="new-password">
                                    <p style="font-size: 0.85em; color: #bbb; margin-top: 5px;">Needed for some downloads/features. Find keys at civitai.com/user/account</p>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-connections">Default Connections</label>
                                    <input type="number" id="civitai-settings-connections" class="civitai-input" value="4" min="1" max="16" step="1" required>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-default-type">Default Model Type (for saving)</label>
                                    <select id="civitai-settings-default-type" class="civitai-select" required></select>
                                </div>
                             </div>
                            <div class="civitai-settings-section">
                                <h4>Interface & Search</h4>
                                <div class="civitai-form-group inline">
                                    <input type="checkbox" id="civitai-settings-auto-open-status" class="civitai-checkbox">
                                    <label for="civitai-settings-auto-open-status">Switch to Status tab after starting download</label>
                                </div>
                                <!-- Example: Add search result limit setting -->
                                <!--
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-search-limit">Search Results per Page</label>
                                    <input type="number" id="civitai-settings-search-limit" class="civitai-input" value="10" min="5" max="50" step="5" required>
                                </div>
                                -->
                            </div>
                         </div>
                         <button type="submit" id="civitai-settings-save" class="civitai-button primary" style="margin-top: 20px;">Save Settings</button>
                        </form>
                    </div>
                </div>
                <div id="civitai-toast" class="civitai-toast"></div>
            </div>
        `;
    }

     cacheDOMElements() {
        // Cache frequently accessed elements (Ensure IDs match HTML)
        this.closeButton = this.modal.querySelector('#civitai-close-modal');
        this.tabContainer = this.modal.querySelector('.civitai-downloader-tabs');
        // this.tabContentContainer = this.modal.querySelector('.civitai-downloader-body'); // Not needed?

        // Download Tab
        this.downloadForm = this.modal.querySelector('#civitai-download-form');
        this.downloadPreviewArea = this.modal.querySelector('#civitai-download-preview-area');
        this.modelUrlInput = this.modal.querySelector('#civitai-model-url');
        this.modelVersionIdInput = this.modal.querySelector('#civitai-model-version-id');
        this.downloadModelTypeSelect = this.modal.querySelector('#civitai-model-type');
        this.customFilenameInput = this.modal.querySelector('#civitai-custom-filename');
        this.downloadConnectionsInput = this.modal.querySelector('#civitai-connections');
        this.forceRedownloadCheckbox = this.modal.querySelector('#civitai-force-redownload');
        this.downloadSubmitButton = this.modal.querySelector('#civitai-download-submit');

        // Search Tab
        this.searchForm = this.modal.querySelector('#civitai-search-form');
        this.searchQueryInput = this.modal.querySelector('#civitai-search-query');
        this.searchTypeSelect = this.modal.querySelector('#civitai-search-type');
        this.searchBaseModelSelect = this.modal.querySelector('#civitai-search-base-model');
        this.searchSortSelect = this.modal.querySelector('#civitai-search-sort');
        this.searchPeriodSelect = this.modal.querySelector('#civitai-search-period');
        this.searchSubmitButton = this.modal.querySelector('#civitai-search-submit');
        this.searchResultsContainer = this.modal.querySelector('#civitai-search-results');
        this.searchPaginationContainer = this.modal.querySelector('#civitai-search-pagination');

        // Status Tab
        this.statusContent = this.modal.querySelector('#civitai-status-content');
        this.activeListContainer = this.modal.querySelector('#civitai-active-list');
        this.queuedListContainer = this.modal.querySelector('#civitai-queued-list');
        this.historyListContainer = this.modal.querySelector('#civitai-history-list');
        this.statusIndicator = this.modal.querySelector('#civitai-status-indicator');
        this.activeCountSpan = this.modal.querySelector('#civitai-active-count');

        // Settings Tab
        this.settingsForm = this.modal.querySelector('#civitai-settings-form');
        this.settingsApiKeyInput = this.modal.querySelector('#civitai-settings-api-key');
        this.settingsConnectionsInput = this.modal.querySelector('#civitai-settings-connections');
        this.settingsDefaultTypeSelect = this.modal.querySelector('#civitai-settings-default-type');
        this.settingsAutoOpenCheckbox = this.modal.querySelector('#civitai-settings-auto-open-status');
        // this.settingsSearchResultLimitInput = this.modal.querySelector('#civitai-settings-search-limit'); // If limit setting added
        this.settingsSaveButton = this.modal.querySelector('#civitai-settings-save');

        // Toast Notification
        this.toastElement = this.modal.querySelector('#civitai-toast');

        // Collect tabs and contents dynamically
        this.tabs = {};
        this.modal.querySelectorAll('.civitai-downloader-tab').forEach(tab => {
            this.tabs[tab.dataset.tab] = tab;
        });
        this.tabContents = {};
         this.modal.querySelectorAll('.civitai-downloader-tab-content').forEach(content => {
             // Assumes content ID follows pattern "civitai-tab-[tabName]"
            const tabName = content.id.replace('civitai-tab-', '');
            if (tabName) {
                this.tabContents[tabName] = content;
            } else {
                 console.warn("Tab content found with unexpected ID format:", content.id);
            }
        });
    }

    debounceFetchDownloadPreview(delay = 500) { // Default 500ms delay
        clearTimeout(this.modelPreviewDebounceTimeout);
        this.modelPreviewDebounceTimeout = setTimeout(() => {
            this.fetchAndDisplayDownloadPreview();
        }, delay);
    }

    setupEventListeners() {
        // Modal close
        this.closeButton.addEventListener('click', () => this.closeModal());
        this.modal.addEventListener('click', (event) => {
            // Close if clicked outside the content area
            if (event.target === this.modal) {
                this.closeModal();
            }
        });

        // Tab switching
        this.tabContainer.addEventListener('click', (event) => {
            if (event.target.matches('.civitai-downloader-tab')) {
                this.switchTab(event.target.dataset.tab);
            }
        });

        // Download form submission
        this.downloadForm.addEventListener('submit', (event) => {
            event.preventDefault();
            this.handleDownloadSubmit();
        });

        this.modelUrlInput.addEventListener('input', () => {
            this.debounceFetchDownloadPreview();
        });
        this.modelUrlInput.addEventListener('paste', () => {
            // Trigger immediately on paste for better UX
            this.debounceFetchDownloadPreview(0); // 0ms delay
        });

        this.modelVersionIdInput.addEventListener('blur', () => {
            this.fetchAndDisplayDownloadPreview(); // Fetch immediately on blur
       });

        // Search form submission
        this.searchForm.addEventListener('submit', (event) => {
            event.preventDefault();
            // Validate that there's at least a query or a filter selected
            if (!this.searchQueryInput.value.trim() &&
                this.searchTypeSelect.value === 'any' &&
                this.searchBaseModelSelect.value === 'any')
            {
                 this.showToast("Please enter a search query or select a Type/Base Model filter.", "error");
                 if (this.searchResultsContainer) this.searchResultsContainer.innerHTML = '<p>Please enter a search query or select a filter.</p>';
                 if (this.searchPaginationContainer) this.searchPaginationContainer.innerHTML = ''; // Clear pagination
                 return;
            }

            this.searchPagination.currentPage = 1; // Reset to first page on new search
            this.handleSearchSubmit();
        });

         // Settings form submission
        this.settingsForm.addEventListener('submit', (event) => {
            event.preventDefault();
            this.handleSettingsSave();
        });

        // --- Event Delegation for dynamic buttons ---

        // Status tab Actions (Cancel/Retry)
        this.statusContent.addEventListener('click', (event) => {
            const button = event.target.closest('button'); // Find nearest button clicked
            if (!button) return; // Exit if click wasn't on or inside a button

            if (button.classList.contains('civitai-cancel-button')) {
                 const downloadId = button.dataset.id;
                 if (downloadId) {
                     this.handleCancelDownload(downloadId);
                 }
            }
            else if (button.classList.contains('civitai-retry-button')) {
                 // Requires storing necessary info in history item's element/data attrs
                 console.warn("Retry functionality not implemented yet.");
                 this.showToast("Retry is not yet implemented.", "info");
            }
            else if (button.classList.contains('civitai-openpath-button')) {
                // Requires storing necessary info in history item's element/data attrs
                console.warn("Need to implement open path");
                this.showToast("Need to implement open path", "info");
           }
        });

         // Search result Actions (Download Button)
        // Search result Actions (Download Button and Show All Versions) - MODIFIED
        this.searchResultsContainer.addEventListener('click', (event) => {
            const downloadButton = event.target.closest('.civitai-search-download-button');
            const viewAllButton = event.target.closest('.show-all-versions-button'); // ADDED: Check for this button

            if (downloadButton) { // Existing download logic
                 // Prevent handling if the click was also somehow on the view all button ancestor (unlikely but safe)
                 if (viewAllButton && downloadButton.contains(viewAllButton)) return;

                const modelId = downloadButton.dataset.modelId;
                const versionId = downloadButton.dataset.versionId;
                const modelTypeApi = downloadButton.dataset.modelType;
                const defaultSaveTypeKey = this.settings.defaultModelType;

                if (!modelId || !versionId) {
                    console.error("Missing model/version ID on search download button.");
                    this.showToast("Error: Missing data for download.", "error");
                    return;
                }

                // Determine save location... (rest of your existing download logic)
                const modelTypeInternalKey = Object.keys(this.modelTypes).find(key =>
                    (this.modelTypes[key]?.toLowerCase() === modelTypeApi?.toLowerCase()) ||
                    (key === modelTypeApi?.toLowerCase())
                ) || defaultSaveTypeKey;

                console.log(`Search DL: ModelID=${modelId}, VersionID=${versionId}, API Type=${modelTypeApi}, Target Save Key=${modelTypeInternalKey}`);

                this.modelUrlInput.value = modelId;
                this.modelVersionIdInput.value = versionId;
                this.customFilenameInput.value = '';
                this.forceRedownloadCheckbox.checked = false;
                this.downloadConnectionsInput.value = this.settings.numConnections;

                this.switchTab('download');

                if (this.downloadModelTypeSelect.querySelector(`option[value="${modelTypeInternalKey}"]`)) {
                    this.downloadModelTypeSelect.value = modelTypeInternalKey;
                    console.log(`Set download dropdown value AFTER switchTab to: ${modelTypeInternalKey}`);
                } else {
                    console.warn(`Target save type '${modelTypeInternalKey}' not found in dropdown after switchTab. Default '${defaultSaveTypeKey}' should be selected.`);
                }

                this.showToast(`Filled download form for Model ID ${modelId}. Review save location.`, 'info', 4000);
                this.fetchAndDisplayDownloadPreview();
                return; // Important: Stop further processing if it was a download button

            } else if (viewAllButton) { // **** ADDED: Handler for 'Show All Versions' ****
                 const modelId = viewAllButton.dataset.modelId;
                 if (!modelId) {
                     console.error("Missing model ID on show-all-versions button.");
                     return;
                 }

                 // Find the container holding the extra versions within the same search result item
                 // The container ID was set in renderSearchResults as `all-versions-${modelId}`
                 const versionsContainer = this.searchResultsContainer.querySelector(`#all-versions-${modelId}`);
                 const icon = viewAllButton.querySelector('i'); // Get the icon element

                 if (versionsContainer) {
                     const currentlyVisible = versionsContainer.style.display !== 'none';
                     if (currentlyVisible) {
                         // Hide the versions
                         versionsContainer.style.display = 'none';
                         // Restore original button text/icon
                         viewAllButton.innerHTML = `All versions (${viewAllButton.dataset.totalVersions}) <i class="fas fa-chevron-down"></i>`;
                         viewAllButton.title = `Show all ${viewAllButton.dataset.totalVersions} versions`;
                         // Optional: Set ARIA attribute for accessibility
                         // viewAllButton.setAttribute('aria-expanded', 'false');
                     } else {
                         // Show the versions (use 'block' or 'flex' or 'grid' depending on how you want them displayed)
                         // Setting to 'block' is usually safe for simple buttons vertically listed.
                         // You might need 'display: flex; flex-direction: column; gap: 5px;' via CSS instead.
                         versionsContainer.style.display = 'flex';
                         // Change button text/icon
                         viewAllButton.innerHTML = `Show less <i class="fas fa-chevron-up"></i>`;
                         viewAllButton.title = `Show less versions`;
                         // Optional: Set ARIA attribute for accessibility
                         // viewAllButton.setAttribute('aria-expanded', 'true');
                     }
                 } else {
                     console.warn(`Could not find versions container #all-versions-${modelId}`);
                 }
                 return; // Stop further processing
            }

            // If other delegated events are needed within searchResultsContainer, add more `else if` blocks here.
        });

        // Pagination (using event delegation)
        this.searchPaginationContainer.addEventListener('click', (event) => {
            const button = event.target.closest('.civitai-page-button');
             if (button && !button.disabled) { // Check if button and not disabled
                 const page = parseInt(button.dataset.page, 10);
                 if (page && page !== this.searchPagination.currentPage) {
                     this.searchPagination.currentPage = page;
                     this.handleSearchSubmit(); // <-- **** UNCOMMENT THIS LINE ****
                 }
             }
         });
         
    }

    switchTab(tabId) {
        if (this.activeTab === tabId || !this.tabs[tabId] || !this.tabContents[tabId]) {
             if (!this.tabs[tabId]) console.error("SwitchTab: Target tab button not found for ID:", tabId);
             if (!this.tabContents[tabId]) console.error("SwitchTab: Target tab content not found for ID:", tabId);
             return; // Don't switch if already active or target invalid
        }

        // Deactivate current tab
        if (this.tabs[this.activeTab]) this.tabs[this.activeTab].classList.remove('active');
        if (this.tabContents[this.activeTab]) this.tabContents[this.activeTab].classList.remove('active');

        // Activate new tab
        this.tabs[tabId].classList.add('active');
        this.tabContents[tabId].classList.add('active');
        // Ensure the content area is scrolled to top when switching tabs
        this.tabContents[tabId].scrollTop = 0;

        this.activeTab = tabId;

        // Specific actions when switching TO a tab
        if (tabId === 'status') {
            this.loadHistoryFromCookie();
            this.updateStatus(); // Refresh status immediately when switching to tab
        } else if (tabId === 'settings') {
             // Re-apply settings from 'this.settings' to ensure UI matches state
             // (e.g. if settings were changed programmatically elsewhere)
             this.applySettings();
        } else if(tabId === 'download') {
            // When switching to download tab, ensure dropdowns reflect current settings
            this.downloadConnectionsInput.value = this.settings.numConnections;
            if (Object.keys(this.modelTypes).length > 0) { // Check if types are loaded
                this.downloadModelTypeSelect.value = this.settings.defaultModelType;
            }
        }
    }

    async populateModelTypes() {
        console.log("[Civicomfy] Populating model types...");
        try {
            const types = await CivitaiDownloaderAPI.getModelTypes();
            // Basic validation
            if (!types || typeof types !== 'object' || Object.keys(types).length === 0) {
                 throw new Error("Received invalid model types data format.");
            }

            this.modelTypes = types; // Store for later use { "lora": "Lora", ... }
            console.log("[Civicomfy] Model types fetched:", this.modelTypes);

            // Clear existing options first
            this.downloadModelTypeSelect.innerHTML = '';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>'; // Keep 'Any' for search
            this.settingsDefaultTypeSelect.innerHTML = '';

            // Populate dropdowns - Sort alphabetically by display name (value)
            const sortedTypes = Object.entries(this.modelTypes).sort((a, b) => a[1].localeCompare(b[1]));

            sortedTypes.forEach(([key, displayName]) => {
                // Use internal key (e.g., "lora") as value, display name (e.g., "Lora") as text
                const option = document.createElement('option');
                option.value = key;
                option.textContent = displayName;

                this.downloadModelTypeSelect.appendChild(option.cloneNode(true));
                this.settingsDefaultTypeSelect.appendChild(option.cloneNode(true));

                // Add to search dropdown as well
                this.searchTypeSelect.appendChild(option.cloneNode(true));
            });

            console.log("[Civicomfy] Model type dropdowns populated.");

            // Set default selected values based on loaded settings AFTER populating
            // Use try-catch as the stored setting might be invalid if types changed
            try {
                 if (this.settingsDefaultTypeSelect.querySelector(`option[value="${this.settings.defaultModelType}"]`)) {
                    this.settingsDefaultTypeSelect.value = this.settings.defaultModelType;
                 } else {
                      console.warn(`Saved default type "${this.settings.defaultModelType}" not found, using first option.`);
                      this.settingsDefaultTypeSelect.selectedIndex = 0; // Fallback to first option
                 }
            } catch (e) { console.error("Error setting default type in settings tab:", e); }

             try {
                 if (this.downloadModelTypeSelect.querySelector(`option[value="${this.settings.defaultModelType}"]`)) {
                    this.downloadModelTypeSelect.value = this.settings.defaultModelType;
                 } else {
                     this.downloadModelTypeSelect.selectedIndex = 0; // Fallback
                 }
            } catch (e) { console.error("Error setting default type in download tab:", e); }

        } catch (error) {
            console.error("[Civicomfy] Failed to get or populate model types:", error);
            this.showToast('Failed to load model types', 'error');
            // Add placeholder default options if API fails
            this.downloadModelTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
            this.settingsDefaultTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
            this.modelTypes = { "checkpoint": "Checkpoint (Default)" }; // Set minimal types
        }
    }

    async fetchAndDisplayDownloadPreview() {
        const modelUrlOrId = this.modelUrlInput.value.trim();
        const versionId = this.modelVersionIdInput.value.trim(); // Get version ID too

        if (!modelUrlOrId) {
            this.downloadPreviewArea.innerHTML = ''; // Clear preview if input is empty
            return;
        }

        // Show loading indicator
        this.downloadPreviewArea.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Loading model details...</p>';
        this.ensureFontAwesome(); // Make sure spinner icon works

        const params = {
            model_url_or_id: modelUrlOrId,
            model_version_id: versionId ? parseInt(versionId, 10) : null,
            api_key: this.settings.apiKey // Send API key from settings
        };

        try {
            const result = await CivitaiDownloaderAPI.getModelDetails(params);

            if (result && result.success) {
                 this.renderDownloadPreview(result); // Pass successful data to renderer
            } else {
                 // Handle explicit failure from backend (e.g., {success: false, error: ...})
                 const message = `Failed to get details: ${result.details || result.error || 'Unknown backend error'}`;
                 this.downloadPreviewArea.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
            }

        } catch (error) {
            // Handle exceptions from the API call itself (network, 404, etc.)
             const message = `Error fetching details: ${error.details || error.message || 'Unknown error'}`;
             console.error("Download Preview Fetch Error:", error);
             this.downloadPreviewArea.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
             // Do not show toast here, error is shown in the preview area
        }
    }

    renderDownloadPreview(data) {
         if (!this.downloadPreviewArea) return;
         this.ensureFontAwesome(); // Ensure icons are loaded
         // Safely extract data (similar to renderSearchResults but from the /get_model_details payload)
         const modelId = data.model_id;
         const modelName = data.model_name || 'Untitled Model';
         const creator = data.creator_username || 'Unknown Creator';
         const modelType = data.model_type || 'N/A';
         const versionName = data.version_name || 'N/A';
         const baseModel = data.base_model || 'N/A';
         const stats = data.stats || {};
         const descriptionHtml = data.description_html || '<p><em>No description.</em></p>';
         const version_description_html = data.version_description_html || '<p><em>No description.</em></p>';
         const fileInfo = data.file_info || {};
         const thumbnail = data.thumbnail_url || PLACEHOLDER_IMAGE_URL; // Use placeholder if missing
         const civitaiLink = `https://civitai.com/models/${modelId}${data.version_id ? '?modelVersionId='+data.version_id : ''}`;

         const placeholder = PLACEHOLDER_IMAGE_URL;
         const onErrorScript = `this.onerror=null; this.src='${placeholder}'; this.style.backgroundColor='#444';`;

         // --- Generate HTML (similar to search result item) ---
         // We can reuse the 'civitai-search-item' class for styling or create a new one. Let's reuse for now.
         const previewHtml = `
            <div class="civitai-search-item" style="background-color: var(--comfy-input-bg);"> <!-- Style override for clarity -->
                <div class="civitai-thumbnail-container">
                    <img src="${thumbnail}" alt="${modelName} thumbnail" class="civitai-search-thumbnail" loading="lazy" onerror="${onErrorScript}">
                    <div class="civitai-type-badge">${modelType}</div>
                </div>
                <div class="civitai-search-info">
                    <h4>${modelName} <span style="font-weight: normal; font-size: 0.9em;">by ${creator}</span></h4>
                    <p style="font-weight: bold;">Version: ${versionName} <span class="base-model-badge" style="margin-left: 5px;">${baseModel}</span></p>

                    <div class="civitai-search-stats" title="Stats: Downloads / Rating (Count) / Likes">
                        <span title="Downloads"><i class="fas fa-download"></i> ${stats.downloads?.toLocaleString() || 0}</span>
                        <span title="Likes"><i class="fas fa-thumbs-up"></i> ${stats.likes?.toLocaleString(0) || 0}</span>
                        <span title="Dislikes"><i class="fas fa-thumbs-down"></i> ${stats.dislikes?.toLocaleString() || 0}</span>
                        <span title="Buzz"><i class="fas fa-bolt"></i> ${stats.buzz?.toLocaleString() || 0}</span>
                    </div>

                    <p style="font-weight: bold; margin-top: 10px;">Primary File:</p>
                    <p style="font-size: 0.9em; color: #ccc;">
                        Name: ${fileInfo.name || 'N/A'}<br>
                        Size: ${this.formatBytes(fileInfo.size_kb * 1024) || 'N/A'} <br> <!-- Convert KB to bytes for formatter -->
                        Format: ${fileInfo.format || 'N/A'}
                    </p>
                     <a href="${civitaiLink}" target="_blank" rel="noopener noreferrer" class="civitai-button small" title="Open on Civitai website" style="margin-top: 5px; display: inline-block;">
                        View on Civitai <i class="fas fa-external-link-alt"></i>
                    </a>

                </div>
                </div>
                <!-- Description Section -->
                <div style="margin-top: 15px;">
                     <h5 style="margin-bottom: 5px;">Model Description:</h5>
                     <div class="model-description-content" style="max-height: 200px; overflow-y: auto; background-color: var(--comfy-input-bg); padding: 10px; border-radius: 4px; font-size: 0.9em; border: 1px solid var(--border-color, #555);">
                         ${descriptionHtml}
                     </div>
                </div>
                <div style="margin-top: 15px;">
                     <h5 style="margin-bottom: 5px;">Version Description:</h5>
                     <div class="model-description-content" style="max-height: 200px; overflow-y: auto; background-color: var(--comfy-input-bg); padding: 10px; border-radius: 4px; font-size: 0.9em; border: 1px solid var(--border-color, #555);">
                         ${version_description_html}
                     </div>
                </div>

         `; // End of previewHtml

         this.downloadPreviewArea.innerHTML = previewHtml;

    }

    async handleDownloadSubmit() {
        this.downloadSubmitButton.disabled = true;
        this.downloadSubmitButton.textContent = 'Starting...';

        const modelUrlOrId = this.modelUrlInput.value.trim();
        if (!modelUrlOrId) {
            this.showToast("Model URL or ID cannot be empty.", "error");
            this.downloadSubmitButton.disabled = false;
            this.downloadSubmitButton.textContent = 'Start Download';
            return;
        }

        const params = {
            model_url_or_id: modelUrlOrId,
            model_type: this.downloadModelTypeSelect.value, // The selected save location type key
            model_version_id: this.modelVersionIdInput.value ? parseInt(this.modelVersionIdInput.value, 10) : null,
            custom_filename: this.customFilenameInput.value.trim(),
            num_connections: parseInt(this.downloadConnectionsInput.value, 10),
            force_redownload: this.forceRedownloadCheckbox.checked,
            api_key: this.settings.apiKey // Pass API key from current settings state
        };

        // Basic validation
         if (isNaN(params.num_connections) || params.num_connections < 1 || params.num_connections > 16) {
             this.showToast("Invalid number of connections (must be 1-16).", "error");
             this.downloadSubmitButton.disabled = false;
             this.downloadSubmitButton.textContent = 'Start Download';
             return;
         }

        try {
            const result = await CivitaiDownloaderAPI.downloadModel(params);

            if (result.status === 'queued') {
                this.showToast(`Download queued: ${result.details?.filename || 'Model'}`, 'success');

                 if(this.settings.autoOpenStatusTab) {
                    this.switchTab('status');
                 } else {
                     this.updateStatus(); // Still update status in background even if not switching
                 }

            } else if (result.status === 'exists' || result.status === 'exists_size_mismatch') {
                // File exists message
                this.showToast(`${result.message}`, 'info', 4000); // Show info longer

            } else {
                 // Handle unexpected success response from backend (should ideally be queued/exists)
                console.warn("Unexpected success response from /civitai/download:", result);
                this.showToast(`Unexpected status: ${result.status} - ${result.message || ''}`, 'info');
            }
        } catch (error) {
             // Error format from _request helper: error.message / error.details / error.status
             // Prioritize details if available
             const message = `Download failed: ${error.details || error.message || 'Unknown error'}`;
             console.error("Download Submit Error:", error);
             this.showToast(message, 'error', 6000); // Show error longer

        } finally {
            this.downloadSubmitButton.disabled = false;
            this.downloadSubmitButton.textContent = 'Start Download';
        }
    }

    async handleSearchSubmit() {
        this.searchSubmitButton.disabled = true;
        this.searchSubmitButton.textContent = 'Searching...';
        this.searchResultsContainer.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Searching...</p>';
        this.searchPaginationContainer.innerHTML = '';

        // No need for separate validation here, done in event listener

        const params = {
            query: this.searchQueryInput.value.trim(),
            // Send selected *internal type key* (e.g., "lora") or empty array for "any"
            // Backend will map this key to the correct API type name (e.g., "LORA")
            model_types: this.searchTypeSelect.value === 'any' ? [] : [this.searchTypeSelect.value],
            // Send selected *base model name* (e.g., "SD 1.5") or empty array for "any"
            base_models: this.searchBaseModelSelect.value === 'any' ? [] : [this.searchBaseModelSelect.value],
            sort: this.searchSortSelect.value, // Send display value (e.g., "Most Downloaded")
            limit: this.searchPagination.limit,
            page: this.searchPagination.currentPage,
            api_key: this.settings.apiKey,
        };

        try {
            const response = await CivitaiDownloaderAPI.searchModels(params);
            if (!response || !response.metadata || !Array.isArray(response.items)) {
                console.error("Invalid search response structure:", response);
                throw new Error("Received invalid data from search API.");
            }

            this.renderSearchResults(response.items); // Pass only the items array to render function
            this.renderSearchPagination(response.metadata); // Pass metadata object

        } catch (error) {
            const message = `Search failed: ${error.details || error.message || 'Unknown error'}`;
            console.error("Search Submit Error:", error);
            this.searchResultsContainer.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
            this.showToast(message, 'error');
        } finally {
            this.searchSubmitButton.disabled = false;
            this.searchSubmitButton.textContent = 'Search';
        }
    }


    handleSettingsSave() {
        console.log("Saving settings...");
        // 1. Read values from UI elements
        const apiKey = this.settingsApiKeyInput.value.trim();
        const numConnections = parseInt(this.settingsConnectionsInput.value, 10);
        const defaultModelType = this.settingsDefaultTypeSelect.value;
        const autoOpenStatusTab = this.settingsAutoOpenCheckbox.checked;
        // const searchLimit = parseInt(this.settingsSearchResultLimitInput.value, 10); // If limit setting was added

        // 2. Basic Validation
        if (isNaN(numConnections) || numConnections < 1 || numConnections > 16) {
            this.showToast("Invalid Default Connections (must be 1-16). Settings not saved.", "error");
             // Optional: visually indicate error on the input field
            return; // Stop saving
        }
        // if (isNaN(searchLimit) || searchLimit < 5 || searchLimit > 50) { // If limit added
        //     this.showToast("Invalid Search Limit (must be 5-50). Settings not saved.", "error");
        //     return;
        // }
        if (!this.settingsDefaultTypeSelect.querySelector(`option[value="${defaultModelType}"]`)) {
             this.showToast("Invalid Default Model Type selected. Settings not saved.", "error");
             return;
        }

        // 3. Update the internal 'this.settings' object
        this.settings.apiKey = apiKey;
        this.settings.numConnections = numConnections;
        this.settings.defaultModelType = defaultModelType;
        this.settings.autoOpenStatusTab = autoOpenStatusTab;
        // this.settings.searchResultLimit = searchLimit; // If limit added

        // 4. Save the updated 'this.settings' object to cookie
        this.saveSettingsToCookie();

        // 5. Re-apply settings to potentially update other parts of the UI (like download tab defaults)
        this.applySettings();
    }

    async handleCancelDownload(downloadId) {
         const button = this.modal.querySelector(`.civitai-cancel-button[data-id="${downloadId}"]`);
         if (button) {
              button.disabled = true;
              button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; // Show spinner
              button.title = "Cancelling...";
         } else {
              console.warn(`Cancel button not found for ID: ${downloadId}`);
         }

        try {
            const result = await CivitaiDownloaderAPI.cancelDownload(downloadId);
            this.showToast(result.message || `Cancellation requested for ${downloadId}`, 'info');
            // Status update should happen automatically via polling, but trigger one now for faster UI feedback
            this.updateStatus();

        } catch (error) {
             const message = `Cancel failed: ${error.details || error.message || 'Unknown error'}`;
             console.error("Cancel Download Error:", error);
             this.showToast(message, 'error');
             // Re-enable button if cancel failed, only if it still exists
             const failedButton = this.modal.querySelector(`.civitai-cancel-button[data-id="${downloadId}"]`);
             if (failedButton) {
                  failedButton.disabled = false;
                  failedButton.innerHTML = 'Cancel'; // Restore text
                  failedButton.title = "Cancel Download";
             }
        }
    }

    // --- Status Update and Rendering ---

    startStatusUpdates() {
        if (!this.statusInterval) {
             console.log("[Civicomfy] Starting status updates (every 3s)...");
            this.updateStatus(); // Initial update immediately
            this.statusInterval = setInterval(() => this.updateStatus(), 3000); // Update every 3 seconds
        }
    }

    stopStatusUpdates() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
            this.statusInterval = null;
             console.log("[Civicomfy] Stopped status updates.");
        }
    }

    async updateStatus() {
        // Only fetch if the modal is open... (keep existing check)
        if (!this.modal || !this.modal.classList.contains('open')) {
            return;
        }
        try {
            const newStatusData = await CivitaiDownloaderAPI.getStatus();

            // Basic check if data structure is valid
            if (newStatusData && Array.isArray(newStatusData.active) && Array.isArray(newStatusData.queue) && Array.isArray(newStatusData.history)) {

                // --- MERGE LOGIC ---
                // 1. Keep track of IDs in the current history (from cookie/previous state)
                const existingHistoryIds = new Set(this.statusData.history.map(item => item.id));

                // 2. Filter the history from the API to include only items *not already* in our existing history
                const newHistoryItemsFromAPI = newStatusData.history.filter(item => !existingHistoryIds.has(item.id));

                // 3. Combine the new unique items from the API with the existing history
                //    Prepend new items so most recent finished appear first
                let combinedHistory = [...newHistoryItemsFromAPI, ...this.statusData.history];

                // 4. (Optional but recommended) Sort combined history - e.g., by end_time descending if available
                combinedHistory.sort((a, b) => {
                    const timeA = a.end_time || a.added_time || 0; // Use endTime, fallback to addedTime
                    const timeB = b.end_time || b.added_time || 0;
                    // Handle potential null/undefined times robustly
                     if (timeA && !timeB) return -1; // A has time, B doesn't -> A comes first
                     if (!timeA && timeB) return 1;  // B has time, A doesn't -> B comes first
                     if (!timeA && !timeB) return 0; // Neither has time, keep original relative order (or sort by ID?)
                    // Both have time, sort descending (most recent first)
                    return new Date(timeB).getTime() - new Date(timeA).getTime();
                });

                // 5. Limit the combined history
                const limitedHistory = combinedHistory.slice(0, this.maxHistoryItems);

                // --- CHECK FOR CHANGES ---
                // Compare relevant parts: active, queue, and the *potentially updated* history
                const oldStateString = JSON.stringify({
                    active: this.statusData.active,
                    queue: this.statusData.queue,
                    history: this.statusData.history // Use history *before* updating it below
                });
                 const newStateString = JSON.stringify({
                    active: newStatusData.active,
                    queue: newStatusData.queue,
                    history: limitedHistory // Use the *new* limited history for comparison
                });
                const changed = oldStateString !== newStateString;

                // --- UPDATE STATUS DATA ---
                // Update active and queue directly from the API
                this.statusData.active = newStatusData.active;
                this.statusData.queue = newStatusData.queue;
                // Update history with the combined, sorted, and limited list
                this.statusData.history = limitedHistory;

                // --- UPDATE UI ---
                // Update the status indicator bubble
                const activeCount = this.statusData.active.length + this.statusData.queue.length;
                this.activeCountSpan.textContent = activeCount;
                this.statusIndicator.style.display = activeCount > 0 ? 'inline' : 'none';

                // Only re-render lists if the status tab is active AND data changed
                if (this.activeTab === 'status' && changed) {
                    // console.log("[Civicomfy] Status data changed, re-rendering lists.");
                    this.renderDownloadList(this.statusData.active, this.activeListContainer, 'No active downloads.');
                    this.renderDownloadList(this.statusData.queue, this.queuedListContainer, 'Download queue is empty.');
                    this.renderDownloadList(this.statusData.history, this.historyListContainer, 'No download history yet.');
                } else if (this.activeTab === 'status' && !changed) {
                    // console.log("[Civicomfy] Status data unchanged, skipping re-render.");
                }

            } else {
                console.warn("[Civicomfy] Received invalid status data structure:", newStatusData);
                // Handle error display as before...
            }

        } catch (error) {
            console.error("[Civicomfy] Failed to update status:", error);
            // Handle error display as before...
             if (this.activeTab === 'status') {
                 const errorHtml = `<p style="color: var(--error-text, #ff6b6b);">Failed to load status: ${error.details || error.message}</p>`;
                 if (!this.activeListContainer.innerHTML.includes("Failed to load status")) {
                     this.activeListContainer.innerHTML = errorHtml;
                     this.queuedListContainer.innerHTML = '';
                     this.historyListContainer.innerHTML = '';
                 }
             }
        }
    }

     formatBytes(bytes, decimals = 2) {
         if (bytes === null || bytes === undefined || isNaN(bytes)) return 'N/A'; // Handle invalid input
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
        // Account for potential floating point inaccuracies in log
        const i = Math.max(0, Math.min(sizes.length - 1, Math.floor(Math.log(Math.abs(bytes)) / Math.log(k))));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSecond) {
        if (!isFinite(bytesPerSecond) || bytesPerSecond < 0) return ''; // Return empty string or 'N/A' for invalid speed
        // if (bytesPerSecond < 10) return ''; // Don't show tiny speeds? Maybe confusing.

        // Use formatBytes for consistency, adding '/s'
        if (bytesPerSecond < 1024) {
            return this.formatBytes(bytesPerSecond, 0) + '/s';
        }
        const k = 1024;
        const sizes = [' KB/s', ' MB/s', ' GB/s', ' TB/s']; // Suffixes include space and unit
        const i = Math.max(0, Math.min(sizes.length - 1, Math.floor(Math.log(bytesPerSecond) / Math.log(k)) -1)); // Adjust index for KB start

        let value = bytesPerSecond / Math.pow(k, i + 1);
        let decimals = (i === 0) ? 1 : 2; // 1 decimal for KB/s, 2 for MB/s+

        // Handle very small fractions (e.g., 0.002 MB/s should show as KB/s)
        if (i > 0 && value < 0.1) {
             value = bytesPerSecond / Math.pow(k, i); // Go back one unit (e.g., to KB)
             decimals = 1;
             i--; // Adjust index back
        } else if (value < 1 && i > 0) { // Show 1 decimal if value is < 1 (e.g., 0.8 MB/s)
             decimals = 1;
        } else if (value >= 10) { // Show 1 decimal if value is >= 10 (e.g., 12.3 MB/s)
            decimals = 1;
        } else if (value >= 100) { // Show 0 decimals if >= 100 (e.g., 150 MB/s)
            decimals = 0;
        }

        return value.toFixed(decimals) + sizes[i];
    }

    renderDownloadList(items, container, emptyMessage) {
        if (!items || items.length === 0) {
            container.innerHTML = `<p>${emptyMessage}</p>`;
            return;
        }

        // Use document fragment for potentially better performance with many items
        const fragment = document.createDocumentFragment();

        items.forEach(item => {
             // Safely access properties with defaults
             const id = item.id || 'unknown-id';
             const progress = item.progress !== undefined ? Math.max(0, Math.min(100, item.progress)) : 0;
             const speed = item.speed !== undefined ? Math.max(0, item.speed) : 0;
             const status = item.status || 'unknown';
             const size = item.known_size !== undefined && item.known_size !== null ? item.known_size : (item.file_size || 0); // Prioritize known_size, fallback to file_size
             const downloadedBytes = size > 0 ? size * (progress / 100) : 0;
             const errorMsg = item.error || null;
             const modelName = item.model_name || item.model.name;
             const versionName = item.version_name || 'Unknown Version';
             const filename = item.filename || 'N/A';
             const addedTime = item.added_time || null;
             const startTime = item.start_time || null;
             const endTime = item.end_time || null;
             const thumbnail = item.thumbnail || PLACEHOLDER_IMAGE_URL; // Use stored placeholder
             // ---> Get Connection Type <---
             const connectionType = item.connection_type || "N/A";

             let progressBarClass = '';
             let statusText = status.charAt(0).toUpperCase() + status.slice(1); // Capitalize first letter

             switch(status) {
                 case 'completed': progressBarClass = 'completed'; break;
                 case 'failed': progressBarClass = 'failed'; break; // Error message shown separately
                 case 'cancelled': progressBarClass = 'cancelled'; break;
                 case 'downloading': break; // Default color
                 case 'queued': break; // No progress bar for queued
                 case 'starting': break; // Use default progress bar at 0% or minimal width
             }

             // Create list item element
             const listItem = document.createElement('div');
             listItem.className = 'civitai-download-item';
             listItem.dataset.id = id;

             // Construct the onerror attribute correctly for the placeholder
             const onErrorScript = `this.onerror=null; this.src='${PLACEHOLDER_IMAGE_URL}'; this.style.backgroundColor='#444';`;

             // Tooltips for times
             const addedTooltip = addedTime ? `data-tooltip="Added: ${new Date(addedTime).toLocaleString()}"` : '';
             const startedTooltip = startTime ? `data-tooltip="Started: ${new Date(startTime).toLocaleString()}"`: '';
             const endedTooltip = endTime ? `data-tooltip="Ended: ${new Date(endTime).toLocaleString()}"`: '';
             const durationTooltip = startTime && endTime ? `data-tooltip="Duration: ${this.formatDuration(startTime, endTime)}"`: '';

             // Tooltip for filename
             const filenameTooltip = filename !== 'N/A' ? `title="Filename: ${filename}"` : '';
             // Tooltip for error
             const errorTooltip = errorMsg ? `title="Error Details: ${errorMsg}"` : '';

             // ---> Display Connection Type <---
             const connectionInfoHtml = connectionType !== "N/A"
                ? `<span style="font-size: 0.85em; color: #aaa; margin-left: 10px;">(Conn: ${connectionType})</span>`
                : '';

             let innerHTML = `
                <img src="${thumbnail}" alt="thumbnail" class="civitai-download-thumbnail" loading="lazy" onerror="${onErrorScript}">
                <div class="civitai-download-info">
                    <strong>${modelName}</strong>
                    <p>Ver: ${versionName}</p>
                    <p class="filename" ${filenameTooltip}>${filename}</p>
                    ${size > 0 ? `<p>Size: ${this.formatBytes(size)}</p>` : ''}
                    ${errorMsg ? `<p class="error-message" ${errorTooltip}>Error: ${errorMsg.substring(0, 100)}${errorMsg.length > 100 ? '...' : ''}</p>` : ''}
            `;

            // Progress Bar and Speed Section
             if (status === 'downloading' || status === 'starting' || status === 'completed') {
                  // Move status text here to combine with conn type
                  const statusLine = `<div ${durationTooltip} ${endedTooltip}>Status: ${statusText} ${connectionInfoHtml}</div>`;

                 innerHTML += `
                    <div class="civitai-progress-container" title="${statusText} - ${progress.toFixed(1)}%">
                        <div class="civitai-progress-bar ${progressBarClass}" style="width: ${progress}%;">
                            ${progress > 5 ? progress.toFixed(0)+'%' : ''}
                        </div>
                    </div>
                 `;
                 const speedText = (status === 'downloading' && speed > 0) ? this.formatSpeed(speed) : '';
                 const progressText = (status === 'downloading' && size > 0) ? `(${this.formatBytes(downloadedBytes)} / ${this.formatBytes(size)})` : '';
                 const completedText = status === 'completed' ? 'Completed' : '';

                 // Combine speed/progress/status into fewer lines
                 innerHTML += `<div class="civitai-speed-indicator">${speedText} ${progressText} ${completedText}</div>`;
                 innerHTML += statusLine;

             } else if (status === 'failed' || status === 'cancelled' || status === 'queued') {
                  innerHTML += `<div ${durationTooltip} ${endedTooltip} ${addedTooltip}>Status: ${statusText} ${connectionInfoHtml}</div>`;
             } else { // Catch 'unknown' or others
                 innerHTML += `<div>Status: ${statusText} ${connectionInfoHtml}</div>`;
             }

            innerHTML += `</div>`; // Close civitai-download-info

             // Actions Section
            innerHTML += `<div class="civitai-download-actions">`;
            if (status === 'queued' || status === 'downloading' || status === 'starting') {
                innerHTML += `<button class="civitai-button danger small civitai-cancel-button" data-id="${id}" title="Cancel Download"><i class="fas fa-times"></i></button>`;
            }
            if (status === 'failed' || status === 'cancelled') {
                innerHTML += `<button class="civitai-button small civitai-retry-button" data-id="${id}" disabled title="Retry not implemented"><i class="fas fa-redo"></i></button>`;
            }
            if (status === 'completed') {
                innerHTML += `<button class="civitai-button small civitai-openpath-button" data-id="${id}" title="Open download path"><i class="fas fa-folder-open"></i></button>`;
            }
            innerHTML += `</div>`; // Close civitai-download-actions

            listItem.innerHTML = innerHTML;
            fragment.appendChild(listItem);
        });// End forEach item

        // Replace container content efficiently
        container.innerHTML = ''; // Clear existing content
        container.appendChild(fragment);

         this.ensureFontAwesome(); // Ensure icons are available
    
    }

    // Helper function to format duration
     formatDuration(isoStart, isoEnd) {
         try {
             const start = new Date(isoStart);
             const end = new Date(isoEnd);
             const diffSeconds = Math.round((end.getTime() - start.getTime()) / 1000);

             if (isNaN(diffSeconds) || diffSeconds < 0) return 'N/A';
             if (diffSeconds < 60) return `${diffSeconds}s`;

             const diffMinutes = Math.floor(diffSeconds / 60);
             const remainingSeconds = diffSeconds % 60;
             if (diffMinutes < 60) return `${diffMinutes}m ${remainingSeconds}s`;

             const diffHours = Math.floor(diffMinutes / 60);
             const remainingMinutes = diffMinutes % 60;
             return `${diffHours}h ${remainingMinutes}m ${remainingSeconds}s`;
         } catch (e) {
             return 'N/A';
         }
     }

     

    // Helper function to ensure FontAwesome is loaded (keep your existing implementation)
    ensureFontAwesome() {
        if (!document.querySelector('link[href*="fontawesome"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css'; // Or your preferred FA source
            document.head.appendChild(link);
        }
    }

  

    // Helper function to ensure FontAwesome is loaded (keep your existing implementation)
    ensureFontAwesome() {
        if (!document.querySelector('link[href*="fontawesome"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css'; // Or your preferred FA source
            document.head.appendChild(link);
        }
    }

    async populateBaseModels() {
        console.log("[Civicomfy] Populating base models...");
        try {
            const result = await CivitaiDownloaderAPI.getBaseModels();
            if (!result || !Array.isArray(result.base_models)) {
                throw new Error("Invalid base models data format received.");
            }
            this.baseModels = result.base_models.sort(); // Store sorted list
            console.log("[Civicomfy] Base models fetched:", this.baseModels);

            // Clear existing options (after the "Any" option)
            const existingOptions = Array.from(this.searchBaseModelSelect.options);
            existingOptions.slice(1).forEach(opt => opt.remove()); // Keep index 0 ("Any")

            // Populate dropdown
            this.baseModels.forEach(baseModelName => {
                const option = document.createElement('option');
                option.value = baseModelName; // Value is the name itself
                option.textContent = baseModelName;
                this.searchBaseModelSelect.appendChild(option);
            });
            console.log("[Civicomfy] Base model dropdown populated.");

        } catch (error) {
             console.error("[Civicomfy] Failed to get or populate base models:", error);
             this.showToast('Failed to load base models list', 'error');
        }
    }

    renderSearchResults(items) { // Expects the array of hits (`processed_items` from backend)
        this.ensureFontAwesome(); // Ensure FontAwesome is loaded

        if (!items || items.length === 0) {
            // Determine message based on whether filters/query were used
            const queryUsed = this.searchQueryInput && this.searchQueryInput.value.trim();
            const typeFilterUsed = this.searchTypeSelect && this.searchTypeSelect.value !== 'any';
            const baseModelFilterUsed = this.searchBaseModelSelect && this.searchBaseModelSelect.value !== 'any';
            const message = (queryUsed || typeFilterUsed || baseModelFilterUsed)
                          ? 'No models found matching your criteria.'
                          : 'Enter a query or select filters and click Search.';
            this.searchResultsContainer.innerHTML = `<p>${message}</p>`;
            return;
        }

        const placeholder = PLACEHOLDER_IMAGE_URL; // Ensure this global var is accessible
        const onErrorScript = `this.onerror=null; this.src='${placeholder}'; this.style.backgroundColor='#444';`;
        const fragment = document.createDocumentFragment();

        // console.log("Rendering Meili results:", items); // Debug: Log items received

        items.forEach(hit => {
            // --- Safely extract data from Meili hit object ---
            const modelId = hit.id;
            if (!modelId) {
                console.warn("Skipping search result with missing ID:", hit);
                return; // Skip if essential ID is missing
            }
            const creator = hit.user?.username || 'Unknown Creator';
            const modelName = hit.name || 'Untitled Model';
            const modelTypeApi = hit.type || 'N/A'; // API Type (e.g., LORA, Checkpoint)
            const stats = hit.metrics || {}; // Top-level metrics
            const tags = hit.tags?.map(t => t.name) || []; // Extract just the tag names

            // Thumbnail URL (pre-processed by backend)
            const thumbnailUrl = hit.thumbnailUrl || placeholder;

            // --- Version Info ---
            const allVersions = hit.versions || []; // Array of all available versions
            const primaryVersion = hit.version || (allVersions.length > 0 ? allVersions[0] : {}); // Primary version details provided directly, fallback to first in array
            const primaryVersionId = primaryVersion.id;
            const primaryBaseModel = primaryVersion.baseModel || 'N/A'; // Base model from primary version

            // Get unique base models across *all* versions for display (more comprehensive)
            const uniqueBaseModels = allVersions.length > 0
                ? [...new Set(allVersions.map(v => v.baseModel).filter(Boolean))]
                : (primaryBaseModel !== 'N/A' ? [primaryBaseModel] : []); // Fallback to primary if array empty
            const baseModelsDisplay = uniqueBaseModels.length > 0 ? uniqueBaseModels.join(', ') : 'N/A';

            // --- Latest Update Date ---
            let lastUpdatedFormatted = 'N/A';
            const publishedAt = hit.publishedAt; // Use publishedAt from main hit
            if (publishedAt) {
                try {
                    const date = new Date(publishedAt);
                    // Use a more standard locale format
                    lastUpdatedFormatted = date.toLocaleDateString(undefined, { // undefined uses user's locale
                        year: 'numeric', month: 'short', day: 'numeric'
                    });
                } catch (e) {
                    console.error(`Error parsing date for model ${modelId}:`, publishedAt, e);
                    lastUpdatedFormatted = 'Invalid Date';
                }
            }

            // --- Create List Item ---
            const listItem = document.createElement('div');
            listItem.className = 'civitai-search-item';
            listItem.dataset.modelId = modelId; // Add model ID for potential future use

            // --- Generate Version Buttons ---
            // Show primary version first, then others, up to a limit initially
            const MAX_VISIBLE_VERSIONS = 3;
            let visibleVersions = [];
            if (primaryVersionId) {
                 // Ensure primary version object from `hit.version` has necessary fields
                 const primaryVersionData = {
                     id: primaryVersionId,
                     name: primaryVersion.name || 'Primary Version',
                     baseModel: primaryBaseModel,
                     // Add other fields if needed by the button template
                 };
                 visibleVersions.push(primaryVersionData);
            }
            // Add other versions, ensuring no duplicates with the primary one if it was also in the array
            allVersions.forEach(v => {
                 if (v.id !== primaryVersionId && visibleVersions.length < MAX_VISIBLE_VERSIONS) {
                     visibleVersions.push(v);
                 }
            });

            // Generate HTML for initially visible version buttons
            let versionButtonsHtml = visibleVersions.map(version => {
                const versionId = version.id;
                const versionName = version.name || 'Unknown Version';
                const baseModel = version.baseModel || 'N/A';
                return `
                    <button class="civitai-button primary small civitai-search-download-button"
                            data-model-id="${modelId}"
                            data-version-id="${versionId || ''}"
                            data-model-type="${modelTypeApi || ''}"
                            ${!versionId ? 'disabled title="Version ID missing, cannot pre-fill"' : 'title="Pre-fill Download Tab"'} >
                        <span class="base-model-badge">${baseModel}</span> ${versionName} <i class="fas fa-download"></i>
                    </button>
                `;
            }).join(''); // Join the HTML strings

            // --- "All/More Versions" Button Logic ---
            const hasMoreVersions = allVersions.length > visibleVersions.length;
            const totalVersionCount = allVersions.length;
            const moreButtonHtml = hasMoreVersions ? `
                <button class="civitai-button secondary small show-all-versions-button"
                        data-model-id="${modelId}"
                        data-total-versions="${totalVersionCount}"
                        title="Show all ${totalVersionCount} versions">
                    All versions (${totalVersionCount}) <i class="fas fa-chevron-down"></i>
                </button>
            ` : '';

            // --- Hidden Versions Container ---
            let allVersionsHtml = '';
            if (hasMoreVersions) {
                // Get versions that are not already visible
                const hiddenVersions = allVersions.filter(v => !visibleVersions.some(vis => vis.id === v.id));
                allVersionsHtml = `
                    <div class="all-versions-container" id="all-versions-${modelId}" style="display: none;">
                        ${hiddenVersions.map(version => {
                            const versionId = version.id;
                            const versionName = version.name || 'Unknown Version';
                            const baseModel = version.baseModel || 'N/A';
                            return `
                                <button class="civitai-button primary small civitai-search-download-button"
                                        data-model-id="${modelId}"
                                        data-version-id="${versionId || ''}"
                                        data-model-type="${modelTypeApi || ''}"
                                        ${!versionId ? 'disabled title="Version ID missing, cannot pre-fill"' : 'title="Pre-fill Download Tab"'} >
                                    <span class="base-model-badge">${baseModel}</span> ${versionName} <i class="fas fa-download"></i>
                                </button>
                            `;
                        }).join('')}
                    </div>
                `;
            }

            // --- Construct Final Inner HTML for the List Item ---
            listItem.innerHTML = `
                <div class="civitai-thumbnail-container">
                    <img src="${thumbnailUrl}" alt="${modelName} thumbnail" class="civitai-search-thumbnail" loading="lazy" onerror="${onErrorScript}">
                    <div class="civitai-type-badge">${modelTypeApi}</div>
                </div>
                <div class="civitai-search-info">
                    <h4>${modelName}</h4>
                    <div class="civitai-search-meta-info">
                        <span title="Creator: ${creator}"><i class="fas fa-user"></i> ${creator}</span>
                        <span title="Base Models: ${baseModelsDisplay}"><i class="fas fa-layer-group"></i> ${baseModelsDisplay}</span>
                        <span title="Published: ${lastUpdatedFormatted}"><i class="fas fa-calendar-alt"></i> ${lastUpdatedFormatted}</span>
                    </div>
                    <div class="civitai-search-stats" title="Stats: Downloads / Rating (Count) / Likes">
                        <span title="Downloads"><i class="fas fa-download"></i> ${stats.downloadCount?.toLocaleString() || 0}</span>
                        <span title="Thumbs"><i class="fas fa-thumbs-up"></i> ${stats.thumbsUpCount?.toLocaleString() || 0}</span>
                        <span title="Collected"><i class="fas fa-archive"></i> ${stats.collectedCount?.toLocaleString() || 0}</span>
                        <span title="Buzz"><i class="fas fa-bolt"></i> ${stats.tippedAmountCount?.toLocaleString() || 0}</span>

                    </div>
                    ${tags.length > 0 ? `
                    <div class="civitai-search-tags" title="${tags.join(', ')}">
                        ${tags.slice(0, 5).map(tag => `<span class="civitai-search-tag">${tag}</span>`).join('')}
                        ${tags.length > 5 ? `<span class="civitai-search-tag">...</span>` : ''}
                    </div>
                    ` : ''}
                </div>
                <div class="civitai-search-actions">
                    <a href="https://civitai.com/models/${modelId}${primaryVersionId ? '?modelVersionId='+primaryVersionId : ''}" target="_blank" rel="noopener noreferrer" class="civitai-button small" title="Open on Civitai website">
                        View <i class="fas fa-external-link-alt"></i>
                    </a>
                    <div class="version-buttons-container">
                        ${versionButtonsHtml}
                        ${moreButtonHtml} 
                    </div>
                    ${allVersionsHtml} 
                </div> 
            `; // End of listItem.innerHTML

            fragment.appendChild(listItem); // Add the completed item to the fragment
        }); // End forEach loop for hits

        // --- Update the DOM ---
        this.searchResultsContainer.innerHTML = ''; // Clear previous results/spinner
        this.searchResultsContainer.appendChild(fragment);

        // --- Post-render Actions ---
        // Event listeners for download and "show all versions" buttons are handled
        // by the event delegation set up in `setupEventListeners`. No need to re-attach here.

    } // End renderSearchResults method
    

    renderSearchPagination(metadata) { // Expects the metadata object from backend { totalItems, currentPage, pageSize, totalPages, ... }
        // Ensure the pagination container exists before proceeding
        if (!this.searchPaginationContainer) {
            console.error("Search pagination container not found in DOM.");
            return;
        }

        if (!metadata || !metadata.totalPages || metadata.totalPages <= 1) {
            this.searchPaginationContainer.innerHTML = ''; // Clear if no pagination needed
            // Update internal state even if not rendering
            this.searchPagination.currentPage = metadata?.currentPage || 1;
            this.searchPagination.totalPages = metadata?.totalPages || 1;
            this.searchPagination.totalItems = metadata?.totalItems || 0;
            return;
        }

        // --- Extract pagination data ---
        const currentPage = metadata.currentPage;
        const totalPages = metadata.totalPages;
        const totalItems = metadata.totalItems;
        // Limit is taken from internal state `this.searchPagination.limit` as metadata.pageSize reflects the *requested* limit
        const limit = this.searchPagination.limit;

        // Update internal state (important for next search submit)
        this.searchPagination.currentPage = currentPage;
        this.searchPagination.totalPages = totalPages;
        this.searchPagination.totalItems = totalItems;

        const fragment = document.createDocumentFragment();
        const maxButtons = 5; // Max number page buttons (e.g., 1 ... 4 5 6 ... 10)

        // Helper to create buttons (reusable)
        const createButton = (text, page, isDisabled = false, isCurrent = false) => {
            const button = document.createElement('button');
            // Use specific classes for styling and identification
            button.className = `civitai-button small civitai-page-button ${isCurrent ? 'primary active' : ''}`;
            button.dataset.page = page;
            button.disabled = isDisabled;
            button.innerHTML = text; // Allows HTML entities like &laquo;
            button.type = 'button'; // Prevent potential form submission issues
            return button;
        };

        // --- Previous Button ---
        fragment.appendChild(createButton('&laquo; Prev', currentPage - 1, currentPage === 1));

        // --- Page Number Buttons Logic ---
        let startPage, endPage;
        if (totalPages <= maxButtons + 2) { // Show all page numbers if total is small enough
            startPage = 1;
            endPage = totalPages;
        } else {
            // Calculate pages to show around the current page
            const maxSideButtons = Math.floor((maxButtons - 1) / 2); // e.g., maxButtons=5 -> maxSide=2 -> shows Current-2, Current-1, Current, Current+1, Current+2

            if (currentPage <= maxButtons - maxSideButtons) {
                // Near the start: Show 1, 2, 3, 4, 5 ... LastPage
                startPage = 1;
                endPage = maxButtons;
            } else if (currentPage >= totalPages - (maxButtons - maxSideButtons - 1)) {
                // Near the end: Show FirstPage ... Last-4, Last-3, Last-2, Last-1, Last
                startPage = totalPages - maxButtons + 1;
                endPage = totalPages;
            } else {
                // In the middle: Show FirstPage ... Current-2, Current-1, Current, Current+1, Current+2 ... LastPage
                startPage = currentPage - maxSideButtons;
                endPage = currentPage + maxSideButtons;
            }
        }

        // Add First page button and ellipsis if needed
        if (startPage > 1) {
            fragment.appendChild(createButton('1', 1)); // Always show first page
            if (startPage > 2) {
                // Add ellipsis if there's a gap between '1' and the startPage sequence
                const ellipsis = document.createElement('span');
                ellipsis.className = 'civitai-pagination-ellipsis';
                ellipsis.textContent = '...';
                fragment.appendChild(ellipsis);
            }
        }

        // Add the calculated range of page number buttons
        for (let i = startPage; i <= endPage; i++) {
            fragment.appendChild(createButton(i.toString(), i, false, i === currentPage));}

        // Add Ellipsis and Last page button if needed
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                // Add ellipsis if there's a gap between the endPage sequence and the LastPage
                const ellipsis = document.createElement('span');
                ellipsis.className = 'civitai-pagination-ellipsis';
                ellipsis.textContent = '...';
                fragment.appendChild(ellipsis);
            }
            fragment.appendChild(createButton(totalPages.toString(), totalPages)); // Always show last page if needed
        }

        // --- Next Button ---
        fragment.appendChild(createButton('Next &raquo;', currentPage + 1, currentPage === totalPages));

        // --- Display Total Items and Page Info ---
        if (totalItems > 0) {
            const info = document.createElement('div');
            info.className = 'civitai-pagination-info'; // Add class for styling
            info.textContent = `Page ${currentPage} of ${totalPages} (${totalItems.toLocaleString()} total models)`;
            fragment.appendChild(info);
        }

        // --- Update the DOM ---
        this.searchPaginationContainer.innerHTML = ''; // Clear previous pagination controls
        this.searchPaginationContainer.appendChild(fragment);

        // Note: Event listeners for pagination buttons are handled by event delegation
        // in setupEventListeners, targeting '.civitai-page-button'.

    } // End renderSearchPagination method

     // --- Modal Control ---

    openModal() {
        if (!this.modal) {
            console.error("[Civicomfy] Modal element not found for opening!");
            return;
        }
        this.modal.classList.add('open');
        // Temporarily disable body scroll - check if ComfyUI uses a specific class for this
        document.body.style.setProperty('overflow', 'hidden', 'important'); // Force override if needed

        this.startStatusUpdates(); // Start polling status when modal opens

        // Refresh status immediately if status tab is the active one upon opening
         if (this.activeTab === 'status') {
              this.updateStatus();
         }
    }

    closeModal() {
        if (!this.modal) return;
        this.modal.classList.remove('open');
        document.body.style.removeProperty('overflow'); // Restore background scrolling

        this.stopStatusUpdates(); // Stop polling status when modal closes
    }

     // --- Toast Notifications ---
     showToast(message, type = 'info', duration = 3000) {
        if (!this.toastElement) {
             console.warn("[Civicomfy] Toast element not found.");
             return;
        }

        // Clear existing timeout to prevent overlap / premature hiding
        if (this.toastTimeout) {
            clearTimeout(this.toastTimeout);
            this.toastTimeout = null; // Clear the ID
        }

        // Ensure type is one of the expected values
        const validTypes = ['info', 'success', 'error', 'warning'];
        const toastType = validTypes.includes(type) ? type : 'info';

        this.toastElement.textContent = message;
        // Use classList for cleaner class management
        this.toastElement.className = 'civitai-toast'; // Reset classes first
        this.toastElement.classList.add(toastType);
        // Defer adding 'show' class slightly to allow CSS transition
        requestAnimationFrame(() => {
            this.toastElement.classList.add('show');
        });

        // Automatically remove after duration
        this.toastTimeout = setTimeout(() => {
            this.toastElement.classList.remove('show');
            this.toastTimeout = null; // Clear timeout ID
            // Optional: Reset classes entirely after fade out animation (e.g., 300ms)
            // setTimeout(() => { if(this.toastElement) this.toastElement.className = 'civitai-toast'; }, 300);
        }, duration);
    }

    // Helper to add FontAwesome if needed (run once)
    ensureFontAwesome() {
         if (!document.getElementById('civitai-fontawesome-link')) {
             const faLink = document.createElement('link');
             faLink.id = 'civitai-fontawesome-link';
             faLink.rel = 'stylesheet';
             faLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css';
             faLink.integrity = 'sha512-1ycn6IcaQQ40/MKBW2W4Rhis/DbILU74C1vSrLJxCq57o941Ym01SwNsOMqvEBFlcgUa6xLiPY/NS5R+E6ztJQ=='; // Add integrity hash
             faLink.crossOrigin = 'anonymous';
             faLink.referrerPolicy = 'no-referrer';
             document.head.appendChild(faLink);
             console.log("[Civicomfy] FontAwesome loaded.");
         }
     }

} // End of CivitaiDownloaderUI class

// --- Initialization ---
// Use app ready event to ensure ComfyUI is loaded and DOM is ready
app.registerExtension({
	name: "Civicomfy.CivitaiDownloader", // Specific name
	async setup(appInstance) {
         console.log("[Civicomfy] Setting up Civicomfy Extension...");

         // Inject the CSS file
         addCssLink();

         // Add the menu button - Initialization of the UI class is now lazy,
         // triggered on the first button click within addMenuButton.
         addMenuButton();

         // Optional: Pre-check placeholder image (remains the same)
         fetch(PLACEHOLDER_IMAGE_URL).then(res => {
            if (!res.ok) {
                console.warn(`[Civicomfy] Placeholder image not found at ${PLACEHOLDER_IMAGE_URL}. UI elements might lack default images.`);
            }
        }).catch(err => console.warn("[Civicomfy] Error checking for placeholder image:", err));

         // Font Awesome loading is handled within the UI class's rendering methods (`ensureFontAwesome`)
         // to ensure it's available when icons are needed.

         console.log("[Civicomfy] Extension setup complete. Button added, UI will initialize on first click.");
	},
    // Optional: Add startup method if needed after nodes/graph is ready
    // async loadedGraphNode(node, app) { }
    // async nodeCreated(node, app) { }
});

// NOTE: The CivitaiDownloaderUI instance is now created lazily when the
// "Civicomfy" button is first clicked in the addMenuButton function.
// Settings loading and populating dropdowns happens at that point.