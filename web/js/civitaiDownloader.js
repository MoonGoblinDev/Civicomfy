// ComfyUI_Civitai_Downloader/web/js/civitaiDownloader.js
// Refactored for ComfyUI Sidebar Integration
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

console.log("Loading Civitai Downloader UI for Sidebar...");

// --- Constants ---
const SIDEBAR_CONTAINER_SELECTOR = ".side-tool-bar-container";
const SIDEBAR_END_SELECTOR = ".side-tool-bar-end";
const SIDEBAR_BUTTON_SELECTOR = ".side-bar-button";
const SIDEBAR_SELECTED_CLASS = "side-bar-button-selected";
// We need to *find* where ComfyUI puts its sidebar content panels.
// Inspect the DOM in your browser when switching sidebar tabs (Queue, Nodes, Models, Workflows).
// It's likely a sibling or nearby container relative to the sidebar <nav>.
// Example (NEEDS VERIFICATION):
const SIDEBAR_CONTENT_AREA_SELECTOR = ".comfy-content-area"; // !! GUESSWORK - ADJUST THIS !!
const PLUGIN_CONTENT_ID = "civitai-downloader-sidebar-content";
const PLUGIN_BUTTON_ID = "civitai-downloader-sidebar-button";

// --- API Interface (Keep As Is) ---
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
                const error = new Error(errorData.error || `HTTP error ${response.status}`);
                error.details = errorData.details || errorData.error;
                error.status = response.status;
                throw error;
            }
             if (response.status === 204 || response.headers.get('content-length') === '0') {
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Failed to fetch ${endpoint}:`, error);
            throw error;
        }
    }

    static async downloadModel(params) { /* ...no change... */ }
    static async getStatus() { /* ...no change... */ }
    static async cancelDownload(downloadId) { /* ...no change... */ }
    static async searchModels(params) { /* ...no change... */ }
    static async getModelTypes() { /* ...no change... */ }
     // --- Re-add Static Methods from previous snippet ---
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
        this.sidebarButton = null; // Reference to our sidebar button
        this.sidebarContent = null; // Reference to our content container
        this.tabs = {};
        this.tabContents = {};
        this.activeTab = 'download'; // Default internal tab
        this.modelTypes = {};
        this.statusInterval = null;
        this.statusData = { queue: [], active: [], history: [] };
        this.searchPagination = { currentPage: 1, totalPages: 1, limit: 10 };
        this.settings = this.loadSettings();
        this.toastTimeout = null;
        this.isContentVisible = false; // Track if our panel is active

        // Create content container but don't append yet
        this.buildSidebarContentHTML();
        this.cacheDOMElements(); // MUST be called after buildSidebarContentHTML
        this.setupInternalEventListeners(); // Listeners within our content
        this.populateModelTypes();
        this.applySettings();
    }

    // --- Settings Load/Save/Apply (Keep As Is) ---
    loadSettings() { /* ...no change... */ }
    saveSettings() { /* ...no change... */ }
    applySettings() { /* ...no change... */ }
    // --- Re-add Settings Methods ---
     loadSettings() {
        const defaults = {
            apiKey: '',
            numConnections: 4,
            defaultModelType: 'checkpoint',
            autoOpenStatusTab: true,
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
             // Wait for populateModelTypes if necessary
             if(Object.keys(this.modelTypes).length > 0) {
                this.downloadModelTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
             }
             // Settings tab default type select also needs this check or population there
             if(this.settingsDefaultTypeSelect && this.settingsDefaultTypeSelect.options.length > 0) {
                 this.settingsDefaultTypeSelect.value = this.settings.defaultModelType || 'checkpoint';
             }
        }
        // Settings tab auto open checkbox
        if (this.settingsAutoOpenCheckbox) {
            this.settingsAutoOpenCheckbox.checked = this.settings.autoOpenStatusTab;
        }
    }

    // --- Sidebar Integration ---

    addSidebarButton() {
        const sidebar = document.querySelector(SIDEBAR_CONTAINER_SELECTOR);
        const sidebarEnd = document.querySelector(SIDEBAR_END_SELECTOR);

        if (!sidebar) {
            console.error("[Civitai DL] Sidebar container not found.");
            return null;
        }
        if (document.getElementById(PLUGIN_BUTTON_ID)) {
            console.log("[Civitai DL] Sidebar button already exists.");
            return document.getElementById(PLUGIN_BUTTON_ID);
        }

        const button = document.createElement("button");
        button.id = PLUGIN_BUTTON_ID;
        button.className = "p-button p-component p-button-icon-only p-button-text side-bar-button p-button-secondary"; // Base classes
        button.type = "button";
        button.setAttribute("aria-label", "Civitai Downloader");
        button.setAttribute("data-pd-tooltip", "true");
        // Add any other necessary attributes seen on other buttons (like pc*, data-pc-*) if needed, though often framework-internal

        // Icon
        const icon = document.createElement("i");
        // Choose a suitable icon: pi-download, pi-cloud-download, etc.
        icon.className = "pi pi-download side-bar-button-icon";
        button.appendChild(icon);

        // Label (seems hidden in the original buttons)
        const label = document.createElement("span");
        label.className = "p-button-label";
        label.innerHTML = "&nbsp;"; // Or Civitai DL if needed
        button.appendChild(label);

        // Click Handler
        button.onclick = () => this.togglePluginContent(true); // Explicitly show

        // Insert before the end buttons (Settings, Theme)
        if (sidebarEnd) {
            sidebar.insertBefore(button, sidebarEnd);
        } else {
            sidebar.appendChild(button); // Fallback
        }

        console.log("[Civitai DL] Sidebar button added.");
        this.sidebarButton = button; // Store reference
        return button;
    }

    appendSidebarContent() {
        // Find the *actual* main content area where sidebar panels are shown.
        // This requires inspecting the live DOM. Let's use the placeholder selector.
        const contentArea = document.querySelector(SIDEBAR_CONTENT_AREA_SELECTOR);
        if (!contentArea) {
            console.error("[Civitai DL] *** ComfyUI Sidebar Content Area not found using selector:", SIDEBAR_CONTENT_AREA_SELECTOR, "*** Adjust the selector in the script!");
            // Fallback: append to body, but it won't be positioned correctly.
            document.body.appendChild(this.sidebarContent);
            return;
        }

        // Check if already appended
        if (!document.getElementById(PLUGIN_CONTENT_ID)) {
             contentArea.appendChild(this.sidebarContent);
             console.log("[Civitai DL] Sidebar content container appended.");
        }
         // Ensure it starts hidden
         this.sidebarContent.style.display = 'none';
    }

    togglePluginContent(show) {
        console.log(`[Civitai DL] Toggling content: ${show ? 'Show' : 'Hide'}`);
        if (!this.sidebarButton || !this.sidebarContent) {
            console.error("[Civitai DL] Cannot toggle, button or content missing.");
            return;
        }

        this.isContentVisible = show;

        if (show) {
            // Hide other potential active panels (BEST EFFORT - VERY BRITTLE)
            // We need to identify the other panels container or individual panels
            // Example: assume siblings within the content area are the panels
            const contentArea = this.sidebarContent.parentElement;
            if (contentArea) {
                Array.from(contentArea.children).forEach(child => {
                    if (child !== this.sidebarContent && child.style.display !== 'none') {
                        console.log("[Civitai DL] Hiding potential sibling panel:", child.id || child.className);
                        child.style.display = 'none'; // Hide other panels
                    }
                });
            } else {
                 console.warn("[Civitai DL] Could not find parent content area to hide siblings.");
            }

            // Show our panel
            this.sidebarContent.style.display = 'flex'; // Use flex as defined in CSS

            // Deselect other sidebar buttons and Select ours
            document.querySelectorAll(`${SIDEBAR_CONTAINER_SELECTOR} ${SIDEBAR_BUTTON_SELECTOR}`).forEach(btn => {
                btn.classList.remove(SIDEBAR_SELECTED_CLASS);
                // PrimeVue might use p-button-primary vs p-button-secondary for selection
                 btn.classList.replace('p-button-primary', 'p-button-secondary');
            });
            this.sidebarButton.classList.add(SIDEBAR_SELECTED_CLASS);
            this.sidebarButton.classList.replace('p-button-secondary','p-button-primary');

            // Start status updates if not already running
            this.startStatusUpdates();
            // Refresh status immediately when shown
            if (this.activeTab === 'status') {
                 this.updateStatus();
            }

        } else {
            // Hide our panel
            this.sidebarContent.style.display = 'none';
            // Deselect our button (ComfyUI's own logic should select the new one)
            this.sidebarButton.classList.remove(SIDEBAR_SELECTED_CLASS);
            this.sidebarButton.classList.replace('p-button-primary','p-button-secondary');
            // Stop status updates? Optional, maybe keep running for indicator bubble.
             // this.stopStatusUpdates(); // Decide if you want updates only when visible
        }
    }

     // Listen for clicks on *other* sidebar buttons to hide our panel
     setupSidebarInteractionListener() {
         const sidebar = document.querySelector(SIDEBAR_CONTAINER_SELECTOR);
         if (!sidebar) return;

         sidebar.addEventListener('click', (event) => {
             const clickedButton = event.target.closest(SIDEBAR_BUTTON_SELECTOR);

             // If a sidebar button was clicked, AND it's NOT our button, AND our panel is currently visible
             if (clickedButton && clickedButton !== this.sidebarButton && this.isContentVisible) {
                 console.log("[Civitai DL] Another sidebar button clicked, hiding plugin content.");
                 this.togglePluginContent(false); // Hide our panel
                 // ComfyUI's native logic should handle showing its own panel and selecting the clicked button.
             }
             // If our button was clicked, togglePluginContent(true) handles it.
              if (clickedButton && clickedButton === this.sidebarButton && !this.isContentVisible) {
                   this.togglePluginContent(true);
              }
         });
         console.log("[Civitai DL] Added sidebar interaction listener.");
     }

    // --- HTML Building ---

    buildSidebarContentHTML() {
        this.sidebarContent = document.createElement('div');
        this.sidebarContent.className = 'civitai-downloader-sidebar-content'; // New main class for styling
        this.sidebarContent.id = PLUGIN_CONTENT_ID;
        // Initial state should be hidden, managed by togglePluginContent
        this.sidebarContent.style.display = 'none';
        this.sidebarContent.style.flexDirection = 'column'; // Match old modal structure
        this.sidebarContent.style.height = '100%'; // Try to fill sidebar height
        this.sidebarContent.style.overflow = 'hidden';

        // Re-use the internal structure (tabs, content panels) but remove modal-specific parts
        this.sidebarContent.innerHTML = `
                <!-- No Header or Close Button -->
                <div class="civitai-downloader-body"> <!-- Keep this structure for tabs+content -->
                    <div class="civitai-downloader-tabs">
                        <button class="civitai-downloader-tab active" data-tab="download">Download</button>
                        <button class="civitai-downloader-tab" data-tab="search">Search</button>
                        <button class="civitai-downloader-tab" data-tab="status">Status <span id="civitai-status-indicator" style="display: none;">(<span id="civitai-active-count">0</span>)</span></button>
                        <button class="civitai-downloader-tab" data-tab="settings">Settings</button>
                    </div>
                    <div id="civitai-tab-download" class="civitai-downloader-tab-content active">
                       <!-- Download Form (content same as before) -->
                       <form id="civitai-download-form">
                            <div class="civitai-form-group">
                                <label for="civitai-model-url">Model URL or ID</label>
                                <input type="text" id="civitai-model-url" class="civitai-input" placeholder="e.g., https://civitai.com/models/12345 or 12345" required>
                            </div>
                            <p style="font-size: 0.9em; color: #ccc; margin-top: -10px; margin-bottom: 15px;">Optionally add "?modelVersionId=xxxxx" in URL or field below.</p>
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
                                    <input type="text" id="civitai-custom-filename" class="civitai-input" placeholder="Leave blank for original">
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
                        <!-- Search Form & Results (content same as before) -->
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
                            <p>Enter a query and click Search.</p>
                        </div>
                         <div id="civitai-search-pagination" style="text-align: center; margin-top: 20px;"></div>
                    </div>
                    <div id="civitai-tab-status" class="civitai-downloader-tab-content">
                         <!-- Status Lists (content same as before) -->
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
                        <!-- Settings Form (content same as before) -->
                         <form id="civitai-settings-form">
                         <div class="civitai-settings-container">
                             <div class="civitai-settings-section">
                                 <h4>API & Defaults</h4>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-api-key">Civitai API Key (Optional)</label>
                                    <input type="password" id="civitai-settings-api-key" class="civitai-input" placeholder="Enter your API key">
                                    <p style="font-size: 0.85em; color: #bbb; margin-top: 5px;">Find keys at civitai.com/user/account</p>
                                </div>
                                <div class="civitai-form-group">
                                    <label for="civitai-settings-connections">Default Connections</label>
                                    <input type="number" id="civitai-settings-connections" class="civitai-input" value="4" min="1" max="16" required>
                                </div>
                                <div class="civitai-form-goup">
                                    <label for="civitai-settings-default-type">Default Model Type</label>
                                    <select id="civitai-settings-default-type" class="civitai-select" required></select>
                                </div>
                             </div>
                             <div class="civitai-settings-section">
                                 <h4>Interface</h4>
                                 <div class="civitai-form-group inline">
                                     <input type="checkbox" id="civitai-settings-auto-open-status" class="civitai-checkbox">
                                     <label for="civitai-settings-auto-open-status">Switch to Status tab after download</label>
                                 </div>
                                 </div>
                             </div>
                         </div>
                         <button type="submit" id="civitai-settings-save" class="civitai-button primary" style="margin-top: 20px;">Save Settings</button>
                        </form>
                    </div>
                </div>
                <div id="civitai-toast" class="civitai-toast"></div> <!-- Toast position might need CSS adjustment -->
            </div>
        `;
    }

    cacheDOMElements() {
        // Cache elements *within* this.sidebarContent
        if (!this.sidebarContent) return;

        // Remove modal-specific elements: closeButton, modal itself
        // this.closeButton = null;

        // References based on the new structure
        this.tabContainer = this.sidebarContent.querySelector('.civitai-downloader-tabs');
        // This is the container FOR the tab content panels, not the main app content area
        this.tabContentContainer = this.sidebarContent.querySelector('.civitai-downloader-body');

        // Download Tab
        this.downloadForm = this.sidebarContent.querySelector('#civitai-download-form');
        this.modelUrlInput = this.sidebarContent.querySelector('#civitai-model-url');
        this.modelVersionIdInput = this.sidebarContent.querySelector('#civitai-model-version-id');
        this.downloadModelTypeSelect = this.sidebarContent.querySelector('#civitai-model-type');
        this.customFilenameInput = this.sidebarContent.querySelector('#civitai-custom-filename');
        this.downloadConnectionsInput = this.sidebarContent.querySelector('#civitai-connections');
        this.forceRedownloadCheckbox = this.sidebarContent.querySelector('#civitai-force-redownload');
        this.downloadSubmitButton = this.sidebarContent.querySelector('#civitai-download-submit');

        // Search Tab
        this.searchForm = this.sidebarContent.querySelector('#civitai-search-form');
        this.searchQueryInput = this.sidebarContent.querySelector('#civitai-search-query');
        this.searchTypeSelect = this.sidebarContent.querySelector('#civitai-search-type');
        this.searchSortSelect = this.sidebarContent.querySelector('#civitai-search-sort');
        this.searchPeriodSelect = this.sidebarContent.querySelector('#civitai-search-period');
        this.searchSubmitButton = this.sidebarContent.querySelector('#civitai-search-submit');
        this.searchResultsContainer = this.sidebarContent.querySelector('#civitai-search-results');
        this.searchPaginationContainer = this.sidebarContent.querySelector('#civitai-search-pagination');

        // Status Tab
        this.statusContent = this.sidebarContent.querySelector('#civitai-status-content');
        this.activeListContainer = this.sidebarContent.querySelector('#civitai-active-list');
        this.queuedListContainer = this.sidebarContent.querySelector('#civitai-queued-list');
        this.historyListContainer = this.sidebarContent.querySelector('#civitai-history-list');
        this.statusIndicator = this.sidebarContent.querySelector('#civitai-status-indicator'); // Should still work
        this.activeCountSpan = this.sidebarContent.querySelector('#civitai-active-count'); // Should still work

        // Settings Tab
        this.settingsForm = this.sidebarContent.querySelector('#civitai-settings-form');
        this.settingsApiKeyInput = this.sidebarContent.querySelector('#civitai-settings-api-key');
        this.settingsConnectionsInput = this.sidebarContent.querySelector('#civitai-settings-connections');
        this.settingsDefaultTypeSelect = this.sidebarContent.querySelector('#civitai-settings-default-type');
        this.settingsAutoOpenCheckbox = this.sidebarContent.querySelector('#civitai-settings-auto-open-status');
        this.settingsSaveButton = this.sidebarContent.querySelector('#civitai-settings-save');

        // Toast Notification
        this.toastElement = this.sidebarContent.querySelector('#civitai-toast'); // Still inside our container

        // Collect internal tabs and contents
        this.tabs = {};
        this.tabContainer.querySelectorAll('.civitai-downloader-tab').forEach(tab => {
            this.tabs[tab.dataset.tab] = tab;
        });
        this.tabContents = {};
         this.sidebarContent.querySelectorAll('.civitai-downloader-tab-content').forEach(content => {
            this.tabContents[content.id.replace('civitai-tab-', '')] = content;
        });
    }

     // Setup listeners within our plugin's content panel
    setupInternalEventListeners() {
        if (!this.sidebarContent) return;
        // Remove modal-specific listeners (close button, clicking outside)

        // Tab switching (internal tabs)
        this.tabContainer.addEventListener('click', (event) => {
            if (event.target.matches('.civitai-downloader-tab')) {
                this.switchTab(event.target.dataset.tab);
            }
        });

        // Forms, status actions, search actions, pagination (Keep these listeners as they operate *within* our content)
        this.downloadForm.addEventListener('submit', (event) => { event.preventDefault(); this.handleDownloadSubmit(); });
        this.searchForm.addEventListener('submit', (event) => { event.preventDefault(); this.searchPagination.currentPage = 1; this.handleSearchSubmit(); });
        this.settingsForm.addEventListener('submit', (event) => { event.preventDefault(); this.handleSettingsSave(); });
         this.statusContent.addEventListener('click', (event) => {
              if (event.target.matches('.civitai-cancel-button')) { const id = event.target.dataset.id; if(id) this.handleCancelDownload(id); }
              // else if (event.target.matches('.civitai-retry-button')) { console.warn("Retry not implemented."); this.showToast("Retry not implemented.", "info"); }
         });
        this.searchResultsContainer.addEventListener('click', (event) => {
             if (event.target.matches('.civitai-search-download-button')) {
                 const btn = event.target;
                 this.modelUrlInput.value = btn.dataset.modelId;
                 this.modelVersionIdInput.value = btn.dataset.versionId;
                 const modelType = btn.dataset.modelType?.toLowerCase();
                 const saveType = ['checkpoint', 'lora', 'locon', 'lycoris', 'vae', 'embedding', 'hypernetwork', 'controlnet', 'motionmodule', 'upscaler', 'wildcards', 'poses'].includes(modelType)
                                  ? modelType
                                  : (this.settings.defaultModelType || 'checkpoint'); // Fallback carefully
                 this.downloadModelTypeSelect.value = saveType;
                  this.customFilenameInput.value = '';
                  this.forceRedownloadCheckbox.checked = false;
                 this.switchTab('download');
                 this.showToast(`Filled form for model ${btn.dataset.modelId}. Adjust type/filename if needed.`, 'info', 4000);
             }
        });
        this.searchPaginationContainer.addEventListener('click', (event) => {
             if (event.target.matches('.civitai-page-button')) {
                 const page = parseInt(event.target.dataset.page, 10);
                 if (page && page !== this.searchPagination.currentPage) {
                     this.searchPagination.currentPage = page;
                     this.handleSearchSubmit();
                 }
             }
         });
    }

    // --- Internal Tab Switching (Keep As Is) ---
    switchTab(tabId) { /* ...no change needed in logic... */ }
    // -- Re-add internal tab switch ---
    switchTab(tabId) {
        if (this.activeTab === tabId || !this.tabs[tabId] || !this.tabContents[tabId]) return;

        if (this.tabs[this.activeTab]) this.tabs[this.activeTab].classList.remove('active');
        if (this.tabContents[this.activeTab]) this.tabContents[this.activeTab].classList.remove('active');

        this.tabs[tabId].classList.add('active');
        this.tabContents[tabId].classList.add('active');
        this.tabContents[tabId].scrollTop = 0; // Scroll to top

        this.activeTab = tabId;

        if (tabId === 'status') this.updateStatus();
        else if (tabId === 'settings') this.applySettings();
    }

    // --- Data Handling & Rendering (Keep As Is) ---
    async populateModelTypes() { /* ...no change... */ }
    async handleDownloadSubmit() { /* ...no change... */ }
    async handleSearchSubmit() { /* ...no change... */ }
    handleSettingsSave() { /* ...no change... */ }
    async handleCancelDownload(downloadId) { /* ...no change... */ }
    startStatusUpdates() { /* ...no change... */ }
    stopStatusUpdates() { /* ...no change... */ }
    async updateStatus() { /* Logic slightly changed to check if OUR panel is visible */
         // Only render lists fully if our sidebar panel is visible *and* the status tab is active
         const shouldRenderLists = this.isContentVisible && this.activeTab === 'status';

         try {
            const newStatusData = await CivitaiDownloaderAPI.getStatus();
             if (newStatusData && Array.isArray(newStatusData.active) && Array.isArray(newStatusData.queue) && Array.isArray(newStatusData.history)) {
                   this.statusData = newStatusData;

                   const activeCount = this.statusData.active.length + this.statusData.queue.length;
                   if (this.activeCountSpan) this.activeCountSpan.textContent = activeCount;
                   if (this.statusIndicator) this.statusIndicator.style.display = activeCount > 0 ? 'inline' : 'none';

                    if (shouldRenderLists) {
                        this.renderDownloadList(this.statusData.active, this.activeListContainer, 'No active downloads.');
                        this.renderDownloadList(this.statusData.queue, this.queuedListContainer, 'Download queue is empty.');
                        this.renderDownloadList(this.statusData.history, this.historyListContainer, 'No download history yet.');
                    }
             } else {
                  console.warn("Invalid status data:", newStatusData);
             }
         } catch (error) {
             console.error("Failed status update:", error);
              if (shouldRenderLists) {
                 this.activeListContainer.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">Failed status: ${error.message}</p>`;
                 this.queuedListContainer.innerHTML = ''; this.historyListContainer.innerHTML = '';
             }
         }
     }
    formatBytes(bytes, decimals = 2) { /* ...no change... */ }
    formatSpeed(bytesPerSecond) { /* ...no change... */ }
    renderDownloadList(items, container, emptyMessage) { /* ...no change... */ }
    renderSearchResults(results) { /* ...no change... */ }
    renderSearchPagination(metadata) { /* ...no change... */ }

    // --- Re-add all data handling and rendering methods ---
    // (Copy paste the methods from the original CivitaiDownloaderUI class:
    // populateModelTypes, handleDownloadSubmit, handleSearchSubmit, handleSettingsSave,
    // handleCancelDownload, startStatusUpdates, stopStatusUpdates,
    // formatBytes, formatSpeed, renderDownloadList, renderSearchResults, renderSearchPagination)
    async populateModelTypes() {
        try {
            const types = await CivitaiDownloaderAPI.getModelTypes();
            this.modelTypes = types;

            const createOption = (key, displayName) => `<option value="${key}">${displayName}</option>`;

            this.downloadModelTypeSelect.innerHTML = '';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
            this.settingsDefaultTypeSelect.innerHTML = '';

            const sortedTypes = Object.entries(this.modelTypes).sort((a, b) => a[1].localeCompare(b[1]));

            sortedTypes.forEach(([key, displayName]) => {
                this.downloadModelTypeSelect.innerHTML += createOption(key, displayName);
                this.settingsDefaultTypeSelect.innerHTML += createOption(key, displayName);
                this.searchTypeSelect.innerHTML += createOption(key, displayName);
            });

            // Apply defaults after population
            this.applySettings();

        } catch (error) {
            console.error("Failed to get model types:", error);
            this.showToast('Failed to load model types', 'error');
             this.downloadModelTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
             this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
             this.settingsDefaultTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
        }
    }

    async handleDownloadSubmit() {
        this.downloadSubmitButton.disabled = true;
        this.downloadSubmitButton.textContent = 'Starting...';
        const params = {
            model_url_or_id: this.modelUrlInput.value, model_type: this.downloadModelTypeSelect.value,
            model_version_id: this.modelVersionIdInput.value ? parseInt(this.modelVersionIdInput.value, 10) : null,
            custom_filename: this.customFilenameInput.value, num_connections: parseInt(this.downloadConnectionsInput.value, 10),
            force_redownload: this.forceRedownloadCheckbox.checked, api_key: this.settings.apiKey
        };
        try {
            const result = await CivitaiDownloaderAPI.downloadModel(params);
            if (result.status === 'queued') {
                this.showToast(`Download queued: ${result.details?.filename || 'Model'}`, 'success');
                this.modelUrlInput.value = ''; this.customFilenameInput.value = '';
                this.modelVersionIdInput.value = ''; this.forceRedownloadCheckbox.checked = false;
                if(this.settings.autoOpenStatusTab) this.switchTab('status');
                 else this.updateStatus();
            } else if (result.status === 'exists' || result.status === 'exists_size_mismatch') {
                this.showToast(`${result.message}`, 'info');
            } else { this.showToast(`Unexpected response: ${result.message || result.status}`, 'info'); }
        } catch (error) {
            this.showToast(`Download failed: ${error.details || error.message}`, 'error', 5000);
        } finally {
            this.downloadSubmitButton.disabled = false; this.downloadSubmitButton.textContent = 'Start Download';
        }
    }

     async handleSearchSubmit() {
        this.searchSubmitButton.disabled = true; this.searchSubmitButton.textContent = 'Searching...';
        this.searchResultsContainer.innerHTML = '<p>Searching...</p>'; this.searchPaginationContainer.innerHTML = '';
        const params = {
            query: this.searchQueryInput.value, model_types: this.searchTypeSelect.value === 'any' ? [] : [this.searchTypeSelect.value],
            sort: this.searchSortSelect.value, period: this.searchPeriodSelect.value,
            limit: this.searchPagination.limit, page: this.searchPagination.currentPage, api_key: this.settings.apiKey
        };
        try {
            const results = await CivitaiDownloaderAPI.searchModels(params);
            this.renderSearchResults(results); this.renderSearchPagination(results.metadata);
        } catch (error) {
            const message = `Search failed: ${error.details || error.message}`;
            this.searchResultsContainer.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
            this.showToast(message, 'error');
        } finally {
            this.searchSubmitButton.disabled = false; this.searchSubmitButton.textContent = 'Search';
        }
    }

    handleSettingsSave() {
        this.settings.apiKey = this.settingsApiKeyInput.value.trim();
        this.settings.numConnections = parseInt(this.settingsConnectionsInput.value, 10) || 4;
        this.settings.defaultModelType = this.settingsDefaultTypeSelect.value || 'checkpoint';
        this.settings.autoOpenStatusTab = this.settingsAutoOpenCheckbox.checked;
        this.saveSettings(); this.applySettings();
    }

    async handleCancelDownload(downloadId) {
         const button = this.sidebarContent.querySelector(`.civitai-cancel-button[data-id="${downloadId}"]`);
         if (button) { button.disabled = true; button.textContent = 'Cancelling...'; }
        try {
            const result = await CivitaiDownloaderAPI.cancelDownload(downloadId);
            this.showToast(result.message || `Cancellation requested`, 'info');
            this.updateStatus();
        } catch (error) {
             this.showToast(`Cancel failed: ${error.details || error.message}`, 'error');
             if (button) { button.disabled = false; button.textContent = 'Cancel'; }
        }
    }

     startStatusUpdates() {
        if (!this.statusInterval) {
            this.updateStatus(); // Initial
            this.statusInterval = setInterval(() => this.updateStatus(), 3000);
             // Keep running even if panel is hidden for indicator bubble update
        }
    }

    stopStatusUpdates() {
        // Decide if you want to stop when hidden. Keeping it running is fine for the bubble.
        // if (this.statusInterval) {
        //     clearInterval(this.statusInterval);
        //     this.statusInterval = null;
        // }
    }

    formatBytes(bytes, decimals = 2) {
        if (bytes === 0 || !bytes) return '0 Bytes'; const k = 1024; const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']; const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSecond) {
        if (!isFinite(bytesPerSecond) || bytesPerSecond < 0) return '0 Bytes/s';
        if (bytesPerSecond < 1024) return this.formatBytes(bytesPerSecond, 0) + '/s';
        else if (bytesPerSecond < 1024 * 1024) return (bytesPerSecond / 1024).toFixed(1) + ' KB/s';
        else if (bytesPerSecond < 1024 * 1024 * 1024) return (bytesPerSecond / (1024 * 1024)).toFixed(2) + ' MB/s';
        else return (bytesPerSecond / (1024 * 1024 * 1024)).toFixed(2) + ' GB/s';
    }

     renderDownloadList(items, container, emptyMessage) {
         if (!container) return; // Guard against missing elements
         if (!items || items.length === 0) { container.innerHTML = `<p>${emptyMessage}</p>`; return; }
         let html = '';
         const placeholder = '/extensions/ComfyUI_Civitai_Downloader/placeholder.png';
         items.forEach(item => {
             const progress = item.progress || 0; const speed = item.speed || 0; const status = item.status || 'unknown';
             const size = item.file_size || 0; const downloadedBytes = size * (progress / 100);
             let progressBarClass = ''; let statusText = status.charAt(0).toUpperCase() + status.slice(1);
             switch(status) {
                 case 'completed': progressBarClass = 'completed'; break; case 'failed': progressBarClass = 'failed'; break;
                 case 'cancelled': progressBarClass = 'cancelled'; break;
             }
             const thumbSrc = item.thumbnail || placeholder;
             html += `<div class="civitai-download-item" data-id="${item.id}"><img src="${thumbSrc}" alt="thumb" class="civitai-download-thumbnail" onerror="this.onerror=null; this.src='${placeholder}';"><div class="civitai-download-info"><strong>${item.model_name || 'Unknown'}</strong><p>Ver: ${item.version_name || 'N/A'}</p><p class="filename" title="${item.filename || 'N/A'}">File: ${item.filename || 'N/A'}</p>${size > 0 ? `<p>Size: ${this.formatBytes(size)}</p>` : ''}${(status === 'failed' && item.error) ? `<p class="error-message" title="${item.error}">Error: ${item.error.substring(0,100)}...</p>` : ''}${(status === 'downloading' || status === 'starting' || status === 'completed') ? `<div class="civitai-progress-container" title="${statusText} - ${progress.toFixed(1)}%"><div class="civitai-progress-bar ${progressBarClass}" style="width: ${progress}%;">${progress > 5 ? progress.toFixed(0)+'%' : ''}</div></div>${(status === 'downloading' && speed > 0) ? `<div class="civitai-speed-indicator">${this.formatSpeed(speed)} (${this.formatBytes(downloadedBytes)}/${this.formatBytes(size)})</div>` : ''}${status === 'completed' ? '<div class="civitai-speed-indicator">Completed</div>' : ''}` : (status !== 'queued' && status !== 'cancelled') ? `<div>Status: ${statusText}</div>` : '' }${status === 'queued' ? `<div data-tooltip="Added: ${item.added_time ? new Date(item.added_time).toLocaleString() : 'N/A'}">Status: Queued</div>` : '' }${status === 'cancelled' ? `<div>Status: Cancelled</div>` : '' }</div><div class="civitai-download-actions">${(status === 'queued' || status === 'downloading' || status === 'starting') ? `<button class="civitai-button danger small civitai-cancel-button" data-id="${item.id}">Cancel</button>` : ''}${(status === 'failed' || status === 'cancelled') ? `<button class="civitai-button small civitai-retry-button" data-id="${item.id}" disabled title="Retry not implemented">Retry</button>` : '' }</div></div>`;});
         container.innerHTML = html;
     }

    renderSearchResults(results) {
         if (!this.searchResultsContainer) return;
         if (!results || !results.items || results.items.length === 0) { this.searchResultsContainer.innerHTML = '<p>No models found.</p>'; return; }
         const placeholder = '/extensions/ComfyUI_Civitai_Downloader/placeholder.png'; let html = '';
         results.items.forEach(item => {
             const version = item.modelVersions?.[0] || {}; const stats = item.stats || {}; const thumbnailUrl = item.thumbnailUrl || placeholder; const fileSizeKB = version.files?.[0]?.sizeKB;
             html += `<div class="civitai-search-item" data-model-id="${item.id}"><img src="${thumbnailUrl}" alt="${item.name}" class="civitai-search-thumbnail" loading="lazy" onerror="this.onerror=null; this.src='${placeholder}';"><div class="civitai-search-info"><h4>${item.name}</h4><p>by ${item.creator?.username || 'Anon'} | ${item.type || 'N/A'}</p><div class="civitai-search-stats"><span title="Downloads"><i class="fas fa-download"></i> ${stats.downloadCount?.toLocaleString() || 0}</span><span title="Rating"><i class="fas fa-star"></i> ${stats.rating?.toFixed(1) || 'N/A'} (${stats.ratingCount?.toLocaleString() || 0})</span><span title="Favorites"><i class="fas fa-heart"></i> ${stats.favoriteCount?.toLocaleString() || 0}</span></div>${item.tags?.length > 0 ? `<div class="civitai-search-tags">${item.tags.slice(0, 5).map(tag => `<span class="civitai-search-tag">${tag}</span>`).join('')}${item.tags.length > 5 ? `...` : ''}</div>` : ''}<p title="Latest: ${version.name || 'N/A'}">Latest: ${version.name || 'N/A'} ${fileSizeKB ? '- ' + this.formatBytes(fileSizeKB * 1024) : ''}</p></div><div class="civitai-search-actions"><a href="https://civitai.com/models/${item.id}?modelVersionId=${version.id || ''}" target="_blank" class="civitai-button small" title="View on Civitai">View <i class="fas fa-external-link-alt"></i></a><button class="civitai-button primary small civitai-search-download-button" data-model-id="${item.id}" data-version-id="${version.id || ''}" data-model-type="${item.type || ''}" ${!version.id ? 'disabled' : ''} title="Add to Download">DL <i class="fas fa-download"></i></button></div></div>`;});
         this.searchResultsContainer.innerHTML = html;
         if (!document.querySelector('link[href*="fontawesome"]')) { const faLink = document.createElement('link'); faLink.rel = 'stylesheet'; faLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css'; document.head.appendChild(faLink); }
     }

    renderSearchPagination(metadata) {
         if (!this.searchPaginationContainer) return;
         if (!metadata || metadata.totalPages <= 1) { this.searchPaginationContainer.innerHTML = ''; return; }
         const { currentPage, totalPages } = metadata; this.searchPagination.currentPage = currentPage; this.searchPagination.totalPages = totalPages; let html = ''; const maxBtns = 5;
         html += `<button class="civitai-button small civitai-page-button" data-page="${currentPage - 1}" ${currentPage === 1 ? 'disabled' : ''}>&laquo;</button>`;
         let start = Math.max(1, currentPage - Math.floor(maxBtns / 2)); let end = Math.min(totalPages, start + maxBtns - 1); start = Math.max(1, end - maxBtns + 1);
         if (start > 1) html += `<button class="civitai-button small civitai-page-button" data-page="1">1</button>${start > 2 ? `<span>...</span>` : ''}`;
         for (let i = start; i <= end; i++) html += `<button class="civitai-button small civitai-page-button ${i === currentPage ? 'primary active' : ''}" data-page="${i}">${i}</button>`;
         if (end < totalPages) html += `${end < totalPages - 1 ? `<span>...</span>` : ''}<button class="civitai-button small civitai-page-button" data-page="${totalPages}">${totalPages}</button>`;
         html += `<button class="civitai-button small civitai-page-button" data-page="${currentPage + 1}" ${currentPage === totalPages ? 'disabled' : ''}>&raquo;</button>`;
         this.searchPaginationContainer.innerHTML = html;
    }

    // --- Modal Control (REMOVED) ---
    // openModal() - Removed
    // closeModal() - Removed

    // --- Toast Notifications ---
    showToast(message, type = 'info', duration = 3000) {
        // Position toast relative to the sidebar or main view now
        if (!this.toastElement) return;
        if (this.toastTimeout) clearTimeout(this.toastTimeout);
        this.toastElement.textContent = message;
        this.toastElement.className = `civitai-toast ${type} show`; // Add type and show class
        // CSS needs to be updated to position the toast correctly without the modal
         this.toastTimeout = setTimeout(() => {
            this.toastElement.classList.remove('show'); this.toastTimeout = null;
        }, duration);
    }

} // End of CivitaiDownloaderUI class

// --- Global Instance ---
// Create instance immediately, but button/content attachment happens in setup
let civitaiDownloaderUIInstance = null;

// --- Initialization ---
app.registerExtension({
	name: "Comfy.CivitaiDownloaderSidebar", // Changed name slightly
	async setup(appInstance) {
        console.log("[Civitai DL] Setting up Sidebar Extension...");

        // 1. Create the UI instance (handles HTML creation internally now)
        if (!civitaiDownloaderUIInstance) {
            civitaiDownloaderUIInstance = new CivitaiDownloaderUI();
        }

        // 2. Add the button to the sidebar (needs DOM ready)
        // Use a slight delay or wait for a specific ComfyUI event if needed,
        // but usually setup runs late enough.
        setTimeout(() => {
             const button = civitaiDownloaderUIInstance.addSidebarButton();

             // 3. Append the content container to the DOM (hidden initially)
             // Make sure the content area selector is correct!
             civitaiDownloaderUIInstance.appendSidebarContent();

             // 4. Setup listener for interaction with *other* sidebar buttons
             civitaiDownloaderUIInstance.setupSidebarInteractionListener();

              // 5. Start status updates (runs even if panel hidden for indicator)
              civitaiDownloaderUIInstance.startStatusUpdates();

              // Check placeholder image (optional)
              const placeholderSrc = '/extensions/ComfyUI_Civitai_Downloader/placeholder.png';
              fetch(placeholderSrc).then(res => {
                  if (!res.ok) console.log("[Civitai DL] Placeholder image not found.");
              }).catch(err => console.warn("[Civitai DL] Placeholder check failed:", err));

              console.log("[Civitai DL] Sidebar Extension Setup Complete.");

        }, 100); // Short delay allow ComfyUI's own sidebar rendering
	},

     // Optional: Add custom nodes or widgets if needed in the future
    // getCustomWidgets() { ... },
    // addCustomNodeDefs(defs, app) { ... },
});