// ComfyUI_Civitai_Downloader/web/js/civitaiDownloader.js
// Paste the complete Javascript content below
// REMEMBER to change placeholder image paths to /extensions/... <<< THIS REMINDER IS NOW OUTDATED/INCORRECT

// Civitai Downloader UI for ComfyUI
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

console.log("Loading Civitai Downloader UI...");

// --- Configuration ---
// !! IMPORTANT: This should match the name of your extension's folder !!
const EXTENSION_NAME = "Civicomfy";
const CSS_URL = `./civitaiDownloader.css`;
const PLACEHOLDER_IMAGE_URL = `./placeholder.png`;

// --- CSS Injection ---
function addCssLink() {
    const cssPath = import.meta.resolve(CSS_URL);
	//console.log(cssPath);
	const $link = document.createElement("link");
	$link.setAttribute("rel", 'stylesheet');
	$link.setAttribute("href", cssPath);
	document.head.appendChild($link);
}

// Add Menu Button to ComfyUI
function addMenuButton() {
    
    // Target the main button group directly
    const buttonGroup = document.querySelector(".comfyui-button-group");

    if (!buttonGroup) {
        console.warn("[Civitai DL] ComfyUI button group (.comfyui-button-group) not found yet. Retrying...");
        setTimeout(addMenuButton, 500); // Retry after a short delay
        return;
    }

    // Prevent adding the button multiple times if script re-runs or retries
    if (document.getElementById("civitai-downloader-button")) {
        console.log("[Civitai DL] Button already exists.");
        return;
    }

    const civitaiButton = document.createElement("button");
    civitaiButton.textContent = "Civitai DL"; // Shorter text fits better in the group
    civitaiButton.id = "civitai-downloader-button";
    // Optional: Add Tooltip
    civitaiButton.title = "Open Civitai Downloader";

    civitaiButton.onclick = () => {
        // Initialize the UI class instance on the first click
        if (!window.civitaiDownloaderUI) {
            console.info("[Civitai DL] Initializing CivitaiDownloaderUI...");
            window.civitaiDownloaderUI = new CivitaiDownloaderUI();
            // Append the modal structure to the document body ONCE upon initialization
            document.body.appendChild(window.civitaiDownloaderUI.modal);
        }
        // Always open the (potentially newly created) modal
        window.civitaiDownloaderUI.openModal();
    };

    // Append the new button to the main button group
    buttonGroup.appendChild(civitaiButton);
    console.log("[Civitai DL] Civitai Downloader button added to .comfyui-button-group.");

    // Fallback (less likely needed, but safe): If appending failed but menu exists, add to menu
    const menu = document.querySelector(".comfy-menu");
    if (!buttonGroup.contains(civitaiButton) && menu && !menu.contains(civitaiButton)) {
        console.warn("[Civitai DL] Failed to append button to group, falling back to menu.");
         // Insert before settings as a last resort if group append failed
        const settingsButton = menu.querySelector("#comfy-settings-button");
        if (settingsButton) {
            settingsButton.insertAdjacentElement("beforebegin", civitaiButton);
        } else {
            menu.appendChild(civitaiButton);
        }
    }
}

// API Interface
class CivitaiDownloaderAPI {
    static async _request(endpoint, options = {}) {
        try {
            const response = await api.fetchApi(endpoint, options);
            if (!response.ok) {
                let errorData;
                try {
                    errorData = await response.json();
                } catch (jsonError) {
                    errorData = { error: `HTTP error ${response.status}`, details : await response.text().catch(() => 'Could not read error text') };
                }
                console.error(`API Error: ${endpoint}`, errorData);
                // Rethrow a custom error object for easier handling
                const error = new Error(errorData.error || `HTTP error ${response.status}`);
                error.details = errorData.details || errorData.error; // Add details if available
                error.status = response.status;
                throw error;
            }
            // Handle empty response body for success codes like 204
             if (response.status === 204 || response.headers.get('content-length') === '0') {
                return null; // Or return an empty object/true? depends on expected usage
            }
            return await response.json();
        } catch (error) {
            console.error(`Failed to fetch ${endpoint}:`, error);
            // Re-throw the error (could be the custom one created above or a network error)
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
        return await this._request('/civitai/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });
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
        this.modelTypes = {}; // { lora: "loras", ... }
        this.statusInterval = null;
        this.statusData = { queue: [], active: [], history: [] };
        this.searchPagination = { currentPage: 1, totalPages: 1, limit: 10 };
        this.settings = this.loadSettings();
        this.toastTimeout = null;

        this.buildModalHTML(); // Creates this.modal element
        this.cacheDOMElements();
        this.setupEventListeners();
        this.populateModelTypes(); // Fetch and populate dropdowns
        this.applySettings(); // Apply loaded settings to UI
    }

    loadSettings() {
        const defaults = {
            apiKey: '',
            numConnections: 4,
            defaultModelType: 'checkpoint',
            autoOpenStatusTab: true, // Example setting
        };
        try {
            const saved = localStorage.getItem('civitaiDownloaderSettings');
            return saved ? { ...defaults, ...JSON.parse(saved) } : defaults;
        } catch (e) {
            console.error("Failed to load settings:", e);
            return defaults;
        }
    }

    saveSettings() {
        try {
            localStorage.setItem('civitaiDownloaderSettings', JSON.stringify(this.settings));
            this.showToast('Settings saved', 'success');
        } catch (e) {
            console.error("Failed to save settings:", e);
            this.showToast('Failed to save settings', 'error');
        }
    }

    applySettings() {
        // Apply settings to relevant UI elements (e.g., API key field)
        if (this.settingsApiKeyInput) {
            this.settingsApiKeyInput.value = this.settings.apiKey;
        }
        if (this.settingsConnectionsInput) {
            this.settingsConnectionsInput.value = this.settings.numConnections;
        }
        // Apply to download form defaults
        if (this.downloadConnectionsInput) {
             this.downloadConnectionsInput.value = this.settings.numConnections;
        }
        if (this.downloadModelTypeSelect) {
             this.downloadModelTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
        }
        // Apply to search controls (if defaults are desired there)
    }

    buildModalHTML() {
        this.modal = document.createElement('div');
        this.modal.className = 'civitai-downloader-modal';
        this.modal.id = 'civitai-downloader-modal';
        // HTML structure remains the same
        this.modal.innerHTML = `
            <div class="civitai-downloader-modal-content">
                <div class="civitai-downloader-header">
                    <h2>Civitai Downloader</h2>
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
                                    <input type="number" id="civitai-connections" class="civitai-input" value="${this.settings.numConnections}" min="1" max="16" required>
                                </div>
                            </div>
                            <div class="civitai-form-group inline">
                                 <input type="checkbox" id="civitai-force-redownload" class="civitai-checkbox">
                                <label for="civitai-force-redownload">Force Re-download</label>
                            </div>
                            <button type="submit" id="civitai-download-submit" class="civitai-button primary">Start Download</button>
                        </form>
                    </div>
                    <div id="civitai-tab-search" class="civitai-downloader-tab-content">
                        <form id="civitai-search-form">
                            <div class="civitai-search-controls">
                                <input type="text" id="civitai-search-query" class="civitai-input" placeholder="Search Civitai..." required>
                                <select id="civitai-search-type" class="civitai-select">
                                    <option value="any">Any Type</option>
                                    <!-- Model types will be populated here -->
                                </select>
                                <select id="civitai-search-sort" class="civitai-select">
                                    <option value="Highest Rated">Highest Rated</option>
                                    <option value="Most Downloaded">Most Downloaded</option>
                                    <option value="Newest">Newest</option>
                                </select>
                                <select id="civitai-search-period" class="civitai-select">
                                    <option value="AllTime">All Time</option>
                                   <option value="Year">Past Year</option>
                                    <option value="Month">Past Month</option>
                                    <option value="Week">Past Week</option>
                                    <option value="Day">Past Day</option>
                                </select>
                                <button type="submit" id="civitai-search-submit" class="civitai-button primary">Search</button>
                            </div>
                        </form>
                        <div id="civitai-search-results" class="civitai-search-results">
                            <!-- Search results will be populated here -->
                            <p>Enter a query and click Search.</p>
                        </div>
                         <div id="civitai-search-pagination" style="text-align: center; margin-top: 20px;">
                             <!-- Pagination controls -->
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
                                <h3>Download History (Last 100)</h3>
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
                                    <input type="password" id="civitai-settings-api-key" class="civitai-input" placeholder="Enter your API key for higher limits/features">
                                    <p style="font-size: 0.85em; color: #bbb; margin-top: 5px;">Find or create keys at civitai.com/user/account</p>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-connections">Default Connections</label>
                                    <input type="number" id="civitai-settings-connections" class="civitai-input" value="4" min="1" max="16" required>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-default-type">Default Model Type</label>
                                    <select id="civitai-settings-default-type" class="civitai-select" required></select>
                                </div>
                             </div>
                             <div class="civitai-settings-section">
                                 <h4>Interface</h4>
                                 <div class="civitai-form-group inline">
                                     <input type="checkbox" id="civitai-settings-auto-open-status" class="civitai-checkbox">
                                     <label for="civitai-settings-auto-open-status">Switch to Status tab after starting download</label>
                                 </div>
                                 </div>
                             </div>
                         </div>
                         <button type="submit" id="civitai-settings-save" class="civitai-button primary" style="margin-top: 20px;">Save Settings</button>
                        </form>
                    </div>
                </div>
                <div id="civitai-toast" class="civitai-toast"></div>
            </div>
        `;
        // Append to body only when the button is first clicked, handled in addMenuButton
    }

     cacheDOMElements() {
        // Cache frequently accessed elements
        this.closeButton = this.modal.querySelector('#civitai-close-modal');
        this.tabContainer = this.modal.querySelector('.civitai-downloader-tabs');
        this.tabContentContainer = this.modal.querySelector('.civitai-downloader-body'); // Check this

        // Download Tab
        this.downloadForm = this.modal.querySelector('#civitai-download-form');
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
        this.settingsSaveButton = this.modal.querySelector('#civitai-settings-save');

        // Toast Notification
        this.toastElement = this.modal.querySelector('#civitai-toast');

        // Collect tabs and contents
        this.tabs = {};
        this.tabContainer.querySelectorAll('.civitai-downloader-tab').forEach(tab => {
            this.tabs[tab.dataset.tab] = tab;
        });
        this.tabContents = {};
         this.modal.querySelectorAll('.civitai-downloader-tab-content').forEach(content => {
            this.tabContents[content.id.replace('civitai-tab-', '')] = content;
        });
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

        // Search form submission
         this.searchForm.addEventListener('submit', (event) => {
            event.preventDefault();
            this.searchPagination.currentPage = 1; // Reset to first page on new search
            this.handleSearchSubmit();
        });

         // Settings form submission
        this.settingsForm.addEventListener('submit', (event) => {
            event.preventDefault();
            this.handleSettingsSave();
        });

        // Dynamic event listeners for cancel buttons (using event delegation on status tab)
        this.statusContent.addEventListener('click', (event) => {
            if (event.target.matches('.civitai-cancel-button')) {
                 const downloadId = event.target.dataset.id;
                 if (downloadId) {
                     this.handleCancelDownload(downloadId);
                 }
            } else if (event.target.matches('.civitai-retry-button')) {
                 const downloadId = event.target.dataset.id;
                 // Find corresponding history item and re-queue (needs more info stored)
                 // This requires storing enough info in history to re-queue
                 console.warn("Retry functionality not implemented yet.");
                 this.showToast("Retry is not yet implemented.", "info");

            } else if (event.target.matches('.civitai-clear-history-button')) {
                 // TODO: Add a button to clear history? maybe confirmation?
                 console.warn("Clear history functionality not implemented yet.");
            }
        });

         // Event listener for search result download buttons
        this.searchResultsContainer.addEventListener('click', (event) => {
             if (event.target.matches('.civitai-search-download-button')) {
                 const button = event.target;
                 const modelId = button.dataset.modelId;
                 const versionId = button.dataset.versionId;
                 const modelType = button.dataset.modelType; // Type of the model itself
                 const defaultSaveType = this.settings.defaultModelType; // Where user wants to save it

                 // Use model's type if sensible, otherwise fallback to user default
                 const saveType = ['checkpoint', 'lora', 'locon', 'lycoris', 'vae', 'embedding', 'hypernetwork', 'controlnet', 'motionmodule'].includes(modelType?.toLowerCase())
                                  ? modelType.toLowerCase()
                                  : defaultSaveType;

                 // Pre-fill the download form
                 this.modelUrlInput.value = modelId; // Use ID for simplicity
                 this.modelVersionIdInput.value = versionId;
                 this.downloadModelTypeSelect.value = saveType;
                 this.customFilenameInput.value = ''; // Clear custom filename
                 this.forceRedownloadCheckbox.checked = false;

                 this.switchTab('download'); // Switch to download tab
                 this.showToast(`Filled download form for model ID ${modelId}, version ${versionId}. Adjust type/filename if needed.`, 'info', 4000);
             }
        });

        // Event listener for pagination
         this.searchPaginationContainer.addEventListener('click', (event) => {
             if (event.target.matches('.civitai-page-button')) {
                 const page = parseInt(event.target.dataset.page, 10);
                 if (page && page !== this.searchPagination.currentPage) {
                     this.searchPagination.currentPage = page;
                     this.handleSearchSubmit(); // Re-run search for the new page
                 }
             }
         });

    }

    switchTab(tabId) {
        if (this.activeTab === tabId) return;

        // Deactivate current tab
        if (this.tabs[this.activeTab]) {
            this.tabs[this.activeTab].classList.remove('active');
        }
        if (this.tabContents[this.activeTab]) {
             this.tabContents[this.activeTab].classList.remove('active');
        }

        // Activate new tab
        if (this.tabs[tabId]) {
            this.tabs[tabId].classList.add('active');
        }
        if (this.tabContents[tabId]) {
            this.tabContents[tabId].classList.add('active');
             // Ensure the content area is scrolled to top when switching tabs
            this.tabContents[tabId].scrollTop = 0;
        } else {
             console.error(`Tab content for '${tabId}' not found.`);
        }

        this.activeTab = tabId;

        // Specific actions when switching to a tab
        if (tabId === 'status') {
            this.updateStatus(); // Refresh status immediately when switching to tab
        } else if (tabId === 'settings') {
             this.applySettings(); // Ensure settings fields are up-to-date
        }
    }

    async populateModelTypes() {
        try {
            const types = await CivitaiDownloaderAPI.getModelTypes();
            this.modelTypes = types; // Store for later use { "lora": "Lora", ... }

            // Clear existing options except the 'Any Type' for search
            this.downloadModelTypeSelect.innerHTML = '';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
            this.settingsDefaultTypeSelect.innerHTML = '';

            // Populate dropdowns
            // Sort alphabetically by display name (value)
            const sortedTypes = Object.entries(this.modelTypes).sort((a, b) => a[1].localeCompare(b[1]));

            sortedTypes.forEach(([key, displayName]) => {
                const option = document.createElement('option');
                option.value = key; // e.g., "lora"
                option.textContent = displayName; // Use display name from API (e.g., "Lora")
                this.downloadModelTypeSelect.appendChild(option.cloneNode(true));
                this.settingsDefaultTypeSelect.appendChild(option.cloneNode(true));

                // For search, use the internal key for filtering on the backend
                const searchOption = document.createElement('option');
                searchOption.value = key; // Use internal key e.g. "lora"
                searchOption.textContent = displayName; // Show display name e.g. "Lora"
                this.searchTypeSelect.appendChild(searchOption);

            });

            // Set default selected value based on settings AFTER populating
            this.downloadModelTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
            this.settingsDefaultTypeSelect.value = this.settings.defaultModelType || 'checkpoint';

        } catch (error) {
            console.error("Failed to get model types:", error);
            this.showToast('Failed to load model types', 'error');
            // Add a default option if failed?
            this.downloadModelTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
            this.settingsDefaultTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';

        }
    }

    async handleDownloadSubmit() {
        this.downloadSubmitButton.disabled = true;
        this.downloadSubmitButton.textContent = 'Starting...';

        const params = {
            model_url_or_id: this.modelUrlInput.value,
            model_type: this.downloadModelTypeSelect.value,
            model_version_id: this.modelVersionIdInput.value ? parseInt(this.modelVersionIdInput.value, 10) : null,
            custom_filename: this.customFilenameInput.value,
            num_connections: parseInt(this.downloadConnectionsInput.value, 10),
            force_redownload: this.forceRedownloadCheckbox.checked,
            api_key: this.settings.apiKey // Pass API key from settings
        };

        try {
            const result = await CivitaiDownloaderAPI.downloadModel(params);
            if (result.status === 'queued') {
                this.showToast(`Download queued: ${result.details?.filename || 'Model'}`, 'success');
                this.modelUrlInput.value = ''; // Clear input on success
                this.customFilenameInput.value = '';
                this.modelVersionIdInput.value = '';
                this.forceRedownloadCheckbox.checked = false;
                 // Optionally switch to status tab
                 if(this.settings.autoOpenStatusTab) {
                    this.switchTab('status');
                 } else {
                     this.updateStatus(); // Still update status in background
                 }
            } else if (result.status === 'exists' || result.status === 'exists_size_mismatch') {
                this.showToast(`${result.message}`, 'info');
            } else {
                 // Should not happen based on current backend logic, but handle just in case
                this.showToast(`Unexpected response: ${result.message || result.status}`, 'info');
            }
        } catch (error) {
             // Error format from _request helper: error.message, error.details
            const message = `Download failed: ${error.details || error.message}`;
            this.showToast(message, 'error', 5000); // Show longer for errors
        } finally {
            this.downloadSubmitButton.disabled = false;
            this.downloadSubmitButton.textContent = 'Start Download';
        }
    }

     async handleSearchSubmit() {
        this.searchSubmitButton.disabled = true;
        this.searchSubmitButton.textContent = 'Searching...';
        this.searchResultsContainer.innerHTML = '<p>Searching...</p>'; // Indicate loading
        this.searchPaginationContainer.innerHTML = ''; // Clear old pagination

        const params = {
            query: this.searchQueryInput.value,
            // Send selected internal type key, backend will map if necessary
            model_types: this.searchTypeSelect.value === 'any' ? [] : [this.searchTypeSelect.value],
            sort: this.searchSortSelect.value,
            period: this.searchPeriodSelect.value,
            limit: this.searchPagination.limit,
            page: this.searchPagination.currentPage,
            api_key: this.settings.apiKey
        };

        try {
            const results = await CivitaiDownloaderAPI.searchModels(params);
            this.renderSearchResults(results);
             this.renderSearchPagination(results.metadata);
        } catch (error) {
            const message = `Search failed: ${error.details || error.message}`;
            this.searchResultsContainer.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
            this.showToast(message, 'error');
        } finally {
            this.searchSubmitButton.disabled = false;
            this.searchSubmitButton.textContent = 'Search';
        }
    }

    handleSettingsSave() {
        this.settings.apiKey = this.settingsApiKeyInput.value.trim();
        this.settings.numConnections = parseInt(this.settingsConnectionsInput.value, 10) || 4;
        this.settings.defaultModelType = this.settingsDefaultTypeSelect.value || 'checkpoint';
        this.settings.autoOpenStatusTab = this.settingsAutoOpenCheckbox.checked;

        this.saveSettings();
        this.applySettings(); // Re-apply in case validation changed values (though not implemented here)
        // Potentially restart download manager if connections changed? Or apply on next download.
    }

    async handleCancelDownload(downloadId) {
         const button = this.modal.querySelector(`.civitai-cancel-button[data-id="${downloadId}"]`);
         if (button) {
              button.disabled = true;
              button.textContent = 'Cancelling...';
         }

        try {
            const result = await CivitaiDownloaderAPI.cancelDownload(downloadId);
            this.showToast(result.message || `Cancellation requested for ${downloadId}`, 'info');
            // Status update will reflect the change shortly
            this.updateStatus(); // Trigger immediate refresh
        } catch (error) {
             const message = `Cancel failed: ${error.details || error.message}`;
             this.showToast(message, 'error');
             if (button) { // Re-enable button if cancel failed
                  button.disabled = false;
                  button.textContent = 'Cancel';
             }
        }
    }

    // --- Status Update and Rendering ---

    startStatusUpdates() {
        if (!this.statusInterval) {
            this.updateStatus(); // Initial update
            this.statusInterval = setInterval(() => this.updateStatus(), 3000); // Update every 3 seconds
             console.log("[Civitai DL] Started status updates timer.");
        }
    }

    stopStatusUpdates() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
            this.statusInterval = null;
             console.log("[Civitai DL] Stopped status updates timer.");
        }
    }

    async updateStatus() {
        // Don't update if modal isn't visible (unless maybe background indicator needed?)
        // If we always want the indicator updated, remove this check.
         if (!this.modal.classList.contains('open') && this.activeTab !== 'status') {
            // If modal is closed AND we're not on the status tab, maybe skip the fetch?
            // Keep fetching to update the indicator bubble.
           // return;
         }

        try {
            const newStatusData = await CivitaiDownloaderAPI.getStatus();
            // Basic check if data structure is valid
             if (newStatusData && Array.isArray(newStatusData.active) && Array.isArray(newStatusData.queue) && Array.isArray(newStatusData.history)) {
                   // Only re-render if data has changed significantly? Deep compare is expensive.
                   // Simple check: compare lengths or stringify? For now, always re-render if status tab is active.
                   this.statusData = newStatusData;

                   // Update the status indicator bubble
                   const activeCount = this.statusData.active.length + this.statusData.queue.length;
                   this.activeCountSpan.textContent = activeCount;
                   this.statusIndicator.style.display = activeCount > 0 ? 'inline' : 'none';

                    // Only render lists if the status tab is currently active to save resources
                    if (this.activeTab === 'status') {
                        this.renderDownloadList(this.statusData.active, this.activeListContainer, 'No active downloads.');
                        this.renderDownloadList(this.statusData.queue, this.queuedListContainer, 'Download queue is empty.');
                        this.renderDownloadList(this.statusData.history, this.historyListContainer, 'No download history yet.');
                    }
             } else {
                  console.warn("Received invalid status data structure:", newStatusData);
             }

        } catch (error) {
            console.error("Failed to update status:", error);
            // Show error on status tab? For now, just log it.
            // Maybe stop updates if error persists?
             if (this.activeTab === 'status') {
                 this.activeListContainer.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">Failed to load status: ${error.message}</p>`;
                 this.queuedListContainer.innerHTML = '';
                 this.historyListContainer.innerHTML = '';
             }
             // Don't show toast every 3s on error
        }
    }

     formatBytes(bytes, decimals = 2) {
        if (bytes === 0 || !bytes) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSecond) {
        if (!isFinite(bytesPerSecond) || bytesPerSecond < 0) return '0 Bytes/s'; // Handle NaN/Infinity/-ve
        if (bytesPerSecond < 1024) {
            return this.formatBytes(bytesPerSecond, 0) + '/s'; // No decimals for Bytes/s
        } else if (bytesPerSecond < 1024 * 1024) {
            return (bytesPerSecond / 1024).toFixed(1) + ' KB/s';
        } else if (bytesPerSecond < 1024 * 1024 * 1024) {
            return (bytesPerSecond / (1024 * 1024)).toFixed(2) + ' MB/s';
        } else {
            return (bytesPerSecond / (1024 * 1024 * 1024)).toFixed(2) + ' GB/s';
        }
    }

    renderDownloadList(items, container, emptyMessage) {
        if (!items || items.length === 0) {
            container.innerHTML = `<p>${emptyMessage}</p>`;
            return;
        }

        // Consider using document fragments for performance if lists get very long
        let html = '';
        items.forEach(item => {
             const progress = item.progress || 0;
             const speed = item.speed || 0;
             const status = item.status || 'unknown';
             const size = item.file_size || 0;
             const downloadedBytes = size * (progress / 100);

             let progressBarClass = '';
             let statusText = status.charAt(0).toUpperCase() + status.slice(1);
             switch(status) {
                 case 'completed': progressBarClass = 'completed'; break;
                 case 'failed': progressBarClass = 'failed'; statusText += `: ${item.error || 'Unknown error'}`; break;
                 case 'cancelled': progressBarClass = 'cancelled'; break;
                 case 'downloading': break; // Default color
                 case 'queued': statusText = 'Queued'; break;
                 case 'starting': statusText = 'Starting...'; break;
             }

             // Use the placeholder URL defined at the top
             const placeholder = PLACEHOLDER_IMAGE_URL;
             const thumbSrc = item.thumbnail || placeholder; // Use item.thumbnail if available, otherwise fallback

             // Construct the onerror attribute correctly
             const onErrorScript = `this.onerror=null; this.src='${placeholder}'; this.style.backgroundColor='#444';`;

            html += `
                <div class="civitai-download-item" data-id="${item.id}">
                    <img src="${thumbSrc}" alt="thumbnail" class="civitai-download-thumbnail" onerror="${onErrorScript}">
                    <div class="civitai-download-info">
                        <strong>${item.model_name || 'Unknown Model'}</strong>
                        <p>Version: ${item.version_name || 'Unknown'}</p>
                        <p class="filename" title="${item.filename || 'N/A'}">File: ${item.filename || 'N/A'}</p>
                         ${size > 0 ? `<p>Size: ${this.formatBytes(size)}</p>` : ''}
                         ${(status === 'failed' && item.error) ? `<p class="error-message" title="${item.error}">Error: ${item.error}</p>` : ''}

                        ${(status === 'downloading' || status === 'starting' || status === 'completed') ? `
                        <div class="civitai-progress-container" title="${statusText} - ${progress.toFixed(1)}%">
                            <div class="civitai-progress-bar ${progressBarClass}" style="width: ${progress}%;">
                                ${progress > 5 ? progress.toFixed(0)+'%' : ''} <!-- Only show % if bar is wide enough -->
                            </div>
                        </div>
                        ${(status === 'downloading' && speed > 0) ? `<div class="civitai-speed-indicator">${this.formatSpeed(speed)} (${this.formatBytes(downloadedBytes)} / ${this.formatBytes(size)})</div>` : ''}
                        ${status === 'completed' ? '<div class="civitai-speed-indicator">Completed</div>' : ''}
                         ` : (status !== 'queued' && status !== 'cancelled') ? `<div>Status: ${statusText}</div>` : '' }
                         ${status === 'queued' ? `<div data-tooltip="Added: ${item.added_time ? new Date(item.added_time).toLocaleString() : 'N/A'}">Status: Queued</div>` : '' }
                         ${status === 'cancelled' ? `<div>Status: Cancelled</div>` : '' }
                    </div>
                     <div class="civitai-download-actions">
                          ${(status === 'queued' || status === 'downloading' || status === 'starting') ? `
                          <button class="civitai-button danger small civitai-cancel-button" data-id="${item.id}">Cancel</button>
                          ` : ''}
                           ${(status === 'failed' || status === 'cancelled') ? `
                           <button class="civitai-button small civitai-retry-button" data-id="${item.id}" disabled title="Retry not implemented">Retry</button>
                           ` : ''}
                           <!-- Add other actions? e.g., 'Locate File' -->
                    </div>
                 </div>
             `;
        });
        container.innerHTML = html;
    }

     renderSearchResults(results) {
        if (!results || !results.items || results.items.length === 0) {
            if (this.searchQueryInput.value) { // Only show 'no results' if a search was attempted
                 this.searchResultsContainer.innerHTML = '<p>No models found matching your criteria.</p>';
            } else {
                 this.searchResultsContainer.innerHTML = '<p>Enter a query and click Search.</p>';
            }
            return;
        }

         // Use the placeholder URL defined at the top
        const placeholder = PLACEHOLDER_IMAGE_URL;
        const onErrorScript = `this.onerror=null; this.src='${placeholder}'; this.style.backgroundColor='#444';`;
        let html = '';
        results.items.forEach(item => {
            const version = item.modelVersions && item.modelVersions[0] ? item.modelVersions[0] : {};
            const stats = item.stats || {};
             // Use pre-processed thumb or fallback
            const thumbnailUrl = item.thumbnailUrl || placeholder;
            const fileSizeKB = version.files?.[0]?.sizeKB;

            html += `
                <div class="civitai-search-item" data-model-id="${item.id}">
                    <img src="${thumbnailUrl}" alt="${item.name} thumbnail" class="civitai-search-thumbnail" loading="lazy" onerror="${onErrorScript}">
                    <div class="civitai-search-info">
                        <h4>${item.name}</h4>
                        <p>by ${item.creator?.username || 'Unknown Creator'} | Type: ${item.type || 'Unknown'}</p>
                        <div class="civitai-search-stats">
                             <span title="Downloads"><i class="fas fa-download"></i> ${stats.downloadCount?.toLocaleString() || 0}</span>
                             <span title="Rating"><i class="fas fa-star"></i> ${stats.rating?.toFixed(1) || 'N/A'} (${stats.ratingCount?.toLocaleString() || 0})</span>
                            <span title="Favorites"><i class="fas fa-heart"></i> ${stats.favoriteCount?.toLocaleString() || 0}</span>
                        </div>
                         ${item.tags && item.tags.length > 0 ? `
                         <div class="civitai-search-tags">
                             ${item.tags.slice(0, 5).map(tag => `<span class="civitai-search-tag">${tag}</span>`).join('')}
                             ${item.tags.length > 5 ? `<span class="civitai-search-tag">...</span>` : ''}
                         </div>
                         ` : ''}
                        <p style="font-size: 0.8em; color: #aaa; margin-top: 5px;" title="Latest version: ${version.name || 'N/A'}">Latest: ${version.name || 'N/A'} ${fileSizeKB ? '- ' + this.formatBytes(fileSizeKB * 1024) : ''}</p>
                    </div>
                     <div class="civitai-search-actions">
                        <a href="https://civitai.com/models/${item.id}?modelVersionId=${version.id || ''}" target="_blank" class="civitai-button small" title="Open on Civitai">View <i class="fas fa-external-link-alt"></i></a>
                         <button class="civitai-button primary small civitai-search-download-button"
                                 data-model-id="${item.id}"
                                 data-version-id="${version.id || ''}"
                                 data-model-type="${item.type || ''}"
                                 ${!version.id ? 'disabled title="No version ID found"' : 'title="Add to Download Tab"'} >
                             Download <i class="fas fa-download"></i>
                         </button>
                    </div>
                </div>
             `;
        });

        this.searchResultsContainer.innerHTML = html;
        // Add FontAwesome link if not already present (simple check)
        if (!document.querySelector('link[href*="fontawesome"]')) {
             const faLink = document.createElement('link');
             faLink.rel = 'stylesheet';
             faLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css';
             document.head.appendChild(faLink);
        }
    }

     renderSearchPagination(metadata) {
        if (!metadata || metadata.totalPages <= 1) {
            this.searchPaginationContainer.innerHTML = '';
            return;
        }

        const { currentPage, totalPages } = metadata;
        this.searchPagination.currentPage = currentPage;
        this.searchPagination.totalPages = totalPages;

        let paginationHTML = '';
        const maxButtons = 7; // Max number of page buttons to show

        // Previous Button
        paginationHTML += `<button class="civitai-button small civitai-page-button" data-page="${currentPage - 1}" ${currentPage === 1 ? 'disabled' : ''}>&laquo; Prev</button>`;

         // Page Number Buttons (simplified logic)
         let startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
         let endPage = Math.min(totalPages, startPage + maxButtons - 1);

         // Adjust startPage if endPage reaches the limit
         if (endPage === totalPages) {
            startPage = Math.max(1, endPage - maxButtons + 1);
         }

        if (startPage > 1) {
            paginationHTML += `<button class="civitai-button small civitai-page-button" data-page="1">1</button>`;
            if (startPage > 2) {
                paginationHTML += `<span style="margin: 0 5px;">...</span>`;
            }
        }

        for (let i = startPage; i <= endP; i++) {
            paginationHTML += `<button class="civitai-button small civitai-page-button ${i === currentPage ? 'primary active' : ''}" data-page="${i}">${i}</button>`; // Add active class
        }

         if (endPage < totalPages) {
             if (endPage < totalPages - 1) {
                 paginationHTML += `<span style="margin: 0 5px;">...</span>`;
             }
             paginationHTML += `<button class="civitai-button small civitai-page-button" data-page="${totalPages}">${totalPages}</button>`;
         }

        // Next Button
        paginationHTML += `<button class="civitai-button small civitai-page-button" data-page="${currentPage + 1}" ${currentPage === totalPages ? 'disabled' : ''}>Next &raquo;</button>`;

        this.searchPaginationContainer.innerHTML = paginationHTML;
    }

     // --- Modal Control ---

    openModal() {
        if (!this.modal) {
            console.error("Modal element not found!");
            return;
        }
        this.modal.classList.add('open');
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        this.startStatusUpdates(); // Start polling status when modal opens
        // Refresh status immediately if switching to status tab
         if (this.activeTab === 'status') {
              this.updateStatus();
         }
    }

    closeModal() {
        if (!this.modal) return;
        this.modal.classList.remove('open');
        document.body.style.overflow = ''; // Restore background scrolling
        this.stopStatusUpdates(); // Stop polling status when modal closes
    }

     // --- Toast Notifications ---
     showToast(message, type = 'info', duration = 3000) {
        if (!this.toastElement) return;

        // Clear existing timeout if any
        if (this.toastTimeout) {
            clearTimeout(this.toastTimeout);
        }

        this.toastElement.textContent = message;
        this.toastElement.className = `civitai-toast ${type} show`; // Add type and show class

        // Automatically remove after duration
        this.toastTimeout = setTimeout(() => {
            this.toastElement.classList.remove('show');
             // Optional: Fully reset class after fade out animation (0.3s default)
            // setTimeout(() => { if (this.toastElement) this.toastElement.className = 'civitai-toast'; }, 300);
            this.toastTimeout = null; // Clear timeout ID
        }, duration);
    }

} // End of CivitaiDownloaderUI class

// --- Initialization ---
// Use app ready event to ensure ComfyUI is loaded
app.registerExtension({
	name: "Civicomfy", // Matches the Python WEB_DIRECTORY value
	async setup(appInstance) {

         // ---> NEW: Inject the CSS file <---
         addCssLink();

         // Add the menu button
         addMenuButton();

         // Check for placeholder image availability (optional, purely visual check)
         // Uses the new URL structure
         fetch(PLACEHOLDER_IMAGE_URL).then(res => {
            if (!res.ok) {
                console.warn(`[Civitai Downloader] Placeholder image not found at ${PLACEHOLDER_IMAGE_URL}. UI elements might lack default images.`);
            } else {
                 console.log(`[Civitai Downloader] Placeholder image OK at ${PLACEHOLDER_IMAGE_URL}`);
            }
        }).catch(err => console.warn("[Civitai Downloader] Error checking for placeholder image:", err));

         console.log("[Civitai Downloader] Extension Setup Complete.");
	}
});

// Initial setup outside the class, ensures UI is ready when button is clicked
// Instantiation happens on first button click now via addMenuButton().