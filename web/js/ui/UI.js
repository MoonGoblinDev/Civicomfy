import { Feedback } from "./feedback.js";
import { setupEventListeners } from "./handlers/eventListeners.js";
import { handleDownloadSubmit, fetchAndDisplayDownloadPreview, debounceFetchDownloadPreview } from "./handlers/downloadHandler.js";
import { handleSearchSubmit } from "./handlers/searchHandler.js";
import { handleSettingsSave, loadAndApplySettings, loadSettingsFromCookie, saveSettingsToCookie, applySettings, getDefaultSettings } from "./handlers/settingsHandler.js";
import { startStatusUpdates, stopStatusUpdates, updateStatus, handleCancelDownload, handleRetryDownload, handleOpenPath, handleClearHistory } from "./handlers/statusHandler.js";
import { renderSearchResults } from "./searchRenderer.js";
import { renderDownloadList } from "./statusRenderer.js";
import { renderDownloadPreview } from "./previewRenderer.js";
import { modalTemplate } from "./templates.js";
import { CivitaiDownloaderAPI } from "../api/civitai.js";

export class CivitaiDownloaderUI {
    constructor() {
        this.modal = null;
        this.tabs = {};
        this.tabContents = {};
        this.activeTab = 'download';
        this.modelTypes = {};
        this.statusInterval = null;
        this.statusData = { queue: [], active: [], history: [] };
        this.baseModels = [];
        this.searchPagination = { currentPage: 1, totalPages: 1, limit: 20 };
        this.settings = this.getDefaultSettings();
        this.toastTimeout = null;
        this.modelPreviewDebounceTimeout = null;

        this.updateStatus();
        this.buildModalHTML();
        this.cacheDOMElements();
        this.setupEventListeners();
        this.feedback = new Feedback(this.modal.querySelector('#civitai-toast'));
        // Ensure icon stylesheet is loaded so buttons render icons immediately
        this.ensureFontAwesome();
    }

    // --- Core UI Methods ---
    buildModalHTML() {
        this.modal = document.createElement('div');
        this.modal.className = 'civitai-downloader-modal';
        this.modal.id = 'civitai-downloader-modal';
        this.modal.innerHTML = modalTemplate(this.settings);
    }

    cacheDOMElements() {
        this.closeButton = this.modal.querySelector('#civitai-close-modal');
        this.tabContainer = this.modal.querySelector('.civitai-downloader-tabs');

        // Download Tab
        this.downloadForm = this.modal.querySelector('#civitai-download-form');
        this.downloadPreviewArea = this.modal.querySelector('#civitai-download-preview-area');
        this.modelUrlInput = this.modal.querySelector('#civitai-model-url');
        this.modelVersionIdInput = this.modal.querySelector('#civitai-model-version-id');
        this.downloadModelTypeSelect = this.modal.querySelector('#civitai-model-type');
        this.createModelTypeButton = this.modal.querySelector('#civitai-create-model-type');
        this.customFilenameInput = this.modal.querySelector('#civitai-custom-filename');
        this.subdirSelect = this.modal.querySelector('#civitai-subdir-select');
        this.createSubdirButton = this.modal.querySelector('#civitai-create-subdir');
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
        this.clearHistoryButton = this.modal.querySelector('#civitai-clear-history-button');
        this.confirmClearModal = this.modal.querySelector('#civitai-confirm-clear-modal');
        this.confirmClearYesButton = this.modal.querySelector('#civitai-confirm-clear-yes');
        this.confirmClearNoButton = this.modal.querySelector('#civitai-confirm-clear-no');

        // Settings Tab
        this.settingsForm = this.modal.querySelector('#civitai-settings-form');
        this.settingsApiKeyInput = this.modal.querySelector('#civitai-settings-api-key');
        this.settingsConnectionsInput = this.modal.querySelector('#civitai-settings-connections');
        this.settingsDefaultTypeSelect = this.modal.querySelector('#civitai-settings-default-type');
        this.settingsAutoOpenCheckbox = this.modal.querySelector('#civitai-settings-auto-open-status');
        this.settingsHideMatureCheckbox = this.modal.querySelector('#civitai-settings-hide-mature');
        this.settingsNsfwThresholdInput = this.modal.querySelector('#civitai-settings-nsfw-threshold');
        this.settingsSaveButton = this.modal.querySelector('#civitai-settings-save');

        // Toast Notification
        this.toastElement = this.modal.querySelector('#civitai-toast');

        // Collect tabs and contents
        this.tabs = {};
        this.modal.querySelectorAll('.civitai-downloader-tab').forEach(tab => {
            this.tabs[tab.dataset.tab] = tab;
        });
        this.tabContents = {};
        this.modal.querySelectorAll('.civitai-downloader-tab-content').forEach(content => {
            const tabName = content.id.replace('civitai-tab-', '');
            if (tabName) this.tabContents[tabName] = content;
        });
    }

    async initializeUI() {
        console.info("[Civicomfy] Initializing UI components...");
        await this.populateModelTypes();
        await this.populateBaseModels();
        this.loadAndApplySettings();
    }

    async populateModelTypes() {
        console.log("[Civicomfy] Populating model types...");
        try {
            const types = await CivitaiDownloaderAPI.getModelTypes();
            if (!types || typeof types !== 'object' || Object.keys(types).length === 0) {
                 throw new Error("Received invalid model types data format.");
            }
            this.modelTypes = types;
            const sortedTypes = Object.entries(this.modelTypes).sort((a, b) => a[1].localeCompare(b[1]));

            this.downloadModelTypeSelect.innerHTML = '';
            this.searchTypeSelect.innerHTML = '<option value="any">Any Type</option>';
            this.settingsDefaultTypeSelect.innerHTML = '';

            sortedTypes.forEach(([key, displayName]) => {
                const option = document.createElement('option');
                option.value = key;
                option.textContent = displayName;
            this.downloadModelTypeSelect.appendChild(option.cloneNode(true));
            this.settingsDefaultTypeSelect.appendChild(option.cloneNode(true));
            this.searchTypeSelect.appendChild(option.cloneNode(true));
        });
        // After types are populated, load subdirs for the current selection
        await this.loadAndPopulateSubdirs(this.downloadModelTypeSelect.value);
        } catch (error) {
            console.error("[Civicomfy] Failed to get or populate model types:", error);
            this.showToast('Failed to load model types', 'error');
            this.downloadModelTypeSelect.innerHTML = '<option value="checkpoint">Checkpoint (Default)</option>';
            this.modelTypes = { "checkpoint": "Checkpoint (Default)" };
        }
    }

    async loadAndPopulateSubdirs(modelType) {
        try {
            const res = await CivitaiDownloaderAPI.getModelDirs(modelType);
            const select = this.subdirSelect;
            if (!select) return;
            const current = select.value;
            select.innerHTML = '';
            const optRoot = document.createElement('option');
            optRoot.value = '';
            optRoot.textContent = '(root)';
            select.appendChild(optRoot);
            if (res && Array.isArray(res.subdirs)) {
                // res.subdirs contains '' for root; skip empty since we added (root)
                res.subdirs.filter(p => p && typeof p === 'string').forEach(rel => {
                    const opt = document.createElement('option');
                    opt.value = rel;
                    opt.textContent = rel;
                    select.appendChild(opt);
                });
            }
            // Restore selection if still present
            if (Array.from(select.options).some(o => o.value === current)) {
                select.value = current;
            }
        } catch (e) {
            console.error('[Civicomfy] Failed to load subdirectories:', e);
            if (this.subdirSelect) {
                this.subdirSelect.innerHTML = '<option value="">(root)</option>';
            }
        }
    }

    // (loadAndPopulateRoots removed; dynamic types already reflect models/ subfolders)

    async populateBaseModels() {
        console.log("[Civicomfy] Populating base models...");
        try {
            const result = await CivitaiDownloaderAPI.getBaseModels();
            if (!result || !Array.isArray(result.base_models)) {
                throw new Error("Invalid base models data format received.");
            }
            this.baseModels = result.base_models.sort();
            const existingOptions = Array.from(this.searchBaseModelSelect.options);
            existingOptions.slice(1).forEach(opt => opt.remove());
            this.baseModels.forEach(baseModelName => {
                const option = document.createElement('option');
                option.value = baseModelName;
                option.textContent = baseModelName;
                this.searchBaseModelSelect.appendChild(option);
            });
        } catch (error) {
             console.error("[Civicomfy] Failed to get or populate base models:", error);
             this.showToast('Failed to load base models list', 'error');
        }
    }

    switchTab(tabId) {
        if (this.activeTab === tabId || !this.tabs[tabId] || !this.tabContents[tabId]) return;

        this.tabs[this.activeTab]?.classList.remove('active');
        this.tabContents[this.activeTab]?.classList.remove('active');

        this.tabs[tabId].classList.add('active');
        this.tabContents[tabId].classList.add('active');
        this.tabContents[tabId].scrollTop = 0;
        this.activeTab = tabId;

        if (tabId === 'status') this.updateStatus();
        else if (tabId === 'settings') this.applySettings();
        else if(tabId === 'download') {
            this.downloadConnectionsInput.value = this.settings.numConnections;
            if (Object.keys(this.modelTypes).length > 0) {
                this.downloadModelTypeSelect.value = this.settings.defaultModelType;
            }
        }
    }

    // --- Modal Control ---
    openModal() {
        this.modal?.classList.add('open');
        document.body.style.setProperty('overflow', 'hidden', 'important');
        this.startStatusUpdates();
        if (this.activeTab === 'status') this.updateStatus();
        if (!this.settings.apiKey) this.switchTab('settings');
    }

    closeModal() {
        this.modal?.classList.remove('open');
        document.body.style.removeProperty('overflow');
        this.stopStatusUpdates();
    }

    // --- Utility Methods ---
    formatBytes(bytes, decimals = 2) {
        if (bytes === null || bytes === undefined || isNaN(bytes)) return 'N/A';
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSecond) {
        if (!isFinite(bytesPerSecond) || bytesPerSecond <= 0) return '';
        return this.formatBytes(bytesPerSecond) + '/s';
    }

    formatDuration(isoStart, isoEnd) {
        try {
            const diffSeconds = Math.round((new Date(isoEnd) - new Date(isoStart)) / 1000);
            if (isNaN(diffSeconds) || diffSeconds < 0) return 'N/A';
            if (diffSeconds < 60) return `${diffSeconds}s`;
            const diffMinutes = Math.floor(diffSeconds / 60);
            const remainingSeconds = diffSeconds % 60;
            return `${diffMinutes}m ${remainingSeconds}s`;
        } catch (e) {
            return 'N/A';
        }
    }

    showToast(message, type = 'info', duration = 3000) {
        this.feedback?.show(message, type, duration);
    }

    ensureFontAwesome() {
        this.feedback?.ensureFontAwesome();
    }

    // --- Rendering (delegated to external renderers) ---
    renderDownloadList = (items, container, emptyMessage) => renderDownloadList(this, items, container, emptyMessage);
    renderSearchResults = (items) => renderSearchResults(this, items);
    renderDownloadPreview = (data) => renderDownloadPreview(this, data);
    
    // --- Auto-select model type based on Civitai model type ---
    inferFolderFromCivitaiType(civitaiType) {
        if (!civitaiType || typeof civitaiType !== 'string') return null;
        const t = civitaiType.trim().toLowerCase();
        const keys = Object.keys(this.modelTypes || {});
        if (keys.length === 0) return null;

        const exists = (k) => keys.includes(k);
        const findBy = (pred) => keys.find(pred);

        // Direct matches first
        if (exists(t)) return t;
        if (exists(`${t}s`)) return `${t}s`;

        // Common mappings from Civitai types to ComfyUI folders
        const candidates = [];
        const addIfExists = (k) => { if (exists(k)) candidates.push(k); };

        switch (t) {
            case 'checkpoint':
                addIfExists('checkpoints');
                addIfExists('models');
                break;
            case 'lora': case 'locon': case 'lycoris':
                addIfExists('loras');
                break;
            case 'vae':
                addIfExists('vae');
                break;
            case 'textualinversion': case 'embedding': case 'embeddings':
                addIfExists('embeddings');
                break;
            case 'hypernetwork':
                addIfExists('hypernetworks');
                break;
            case 'controlnet':
                addIfExists('controlnet');
                break;
            case 'unet': case 'unet2':
                addIfExists('unet');
                break;
            case 'diffusers': case 'diffusionmodels': case 'diffusion_models': case 'diffusion':
                addIfExists('diffusers');
                addIfExists('diffusion_models');
                break;
            case 'upscaler': case 'upscalers':
                addIfExists('upscale_models');
                addIfExists('upscalers');
                break;
            case 'motionmodule':
                addIfExists('motion_models');
                break;
            case 'poses':
                addIfExists('poses');
                break;
            case 'wildcards':
                addIfExists('wildcards');
                break;
            case 'onnx':
                addIfExists('onnx');
                break;
        }
        if (candidates.length > 0) return candidates[0];

        // Relaxed match: name contains type
        const contains = findBy(k => k.toLowerCase().includes(t));
        if (contains) return contains;

        return null;
    }

    async autoSelectModelTypeFromCivitai(civitaiType) {
        try {
            const folder = this.inferFolderFromCivitaiType(civitaiType);
            if (!folder) return;
            if (this.downloadModelTypeSelect && this.downloadModelTypeSelect.value !== folder) {
                this.downloadModelTypeSelect.value = folder;
                await this.loadAndPopulateSubdirs(folder);
                // Reset subdir to root after auto-switch
                if (this.subdirSelect) this.subdirSelect.value = '';
            }
        } catch (e) {
            console.warn('[Civicomfy] Auto-select model type failed:', e);
        }
    }

    renderSearchPagination(metadata) {
        if (!this.searchPaginationContainer) return;
        if (!metadata || metadata.totalPages <= 1) {
            this.searchPaginationContainer.innerHTML = '';
            this.searchPagination = { ...this.searchPagination, ...metadata };
            return;
        }

        this.searchPagination = { ...this.searchPagination, ...metadata };
        const { currentPage, totalPages, totalItems } = this.searchPagination;

        const createButton = (text, page, isDisabled = false, isCurrent = false) => {
            const button = document.createElement('button');
            button.className = `civitai-button small civitai-page-button ${isCurrent ? 'primary active' : ''}`;
            button.dataset.page = page;
            button.disabled = isDisabled;
            button.innerHTML = text;
            button.type = 'button';
            return button;
        };

        const fragment = document.createDocumentFragment();
        fragment.appendChild(createButton('&laquo; Prev', currentPage - 1, currentPage === 1));
        
        let startPage = Math.max(1, currentPage - 2);
        let endPage = Math.min(totalPages, currentPage + 2);

        if (startPage > 1) fragment.appendChild(createButton('1', 1));
        if (startPage > 2) fragment.appendChild(document.createElement('span')).textContent = '...';

        for (let i = startPage; i <= endPage; i++) {
            fragment.appendChild(createButton(i, i, false, i === currentPage));
        }

        if (endPage < totalPages - 1) fragment.appendChild(document.createElement('span')).textContent = '...';
        if (endPage < totalPages) fragment.appendChild(createButton(totalPages, totalPages));
        
        fragment.appendChild(createButton('Next &raquo;', currentPage + 1, currentPage === totalPages));

        const info = document.createElement('div');
        info.className = 'civitai-pagination-info';
        info.textContent = `Page ${currentPage} of ${totalPages} (${totalItems.toLocaleString()} models)`;
        fragment.appendChild(info);

        this.searchPaginationContainer.innerHTML = '';
        this.searchPaginationContainer.appendChild(fragment);
    }

    // --- Event Handlers and State Management (delegated to handlers) ---
    setupEventListeners = () => setupEventListeners(this);
    getDefaultSettings = () => getDefaultSettings();
    loadAndApplySettings = () => loadAndApplySettings(this);
    loadSettingsFromCookie = () => loadSettingsFromCookie(this);
    saveSettingsToCookie = () => saveSettingsToCookie(this);
    applySettings = () => applySettings(this);
    handleSettingsSave = () => handleSettingsSave(this);
    handleDownloadSubmit = () => handleDownloadSubmit(this);
    handleSearchSubmit = () => handleSearchSubmit(this);
    fetchAndDisplayDownloadPreview = () => fetchAndDisplayDownloadPreview(this);
    debounceFetchDownloadPreview = (delay) => debounceFetchDownloadPreview(this, delay);
    startStatusUpdates = () => startStatusUpdates(this);
    stopStatusUpdates = () => stopStatusUpdates(this);
    updateStatus = () => updateStatus(this);
    handleCancelDownload = (downloadId) => handleCancelDownload(this, downloadId);
    handleRetryDownload = (downloadId, button) => handleRetryDownload(this, downloadId, button);
    handleOpenPath = (downloadId, button) => handleOpenPath(this, downloadId, button);
    handleClearHistory = () => handleClearHistory(this);
}
