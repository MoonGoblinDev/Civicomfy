export function setupEventListeners(ui) {
    // Modal close
    ui.closeButton.addEventListener('click', () => ui.closeModal());
    ui.modal.addEventListener('click', (event) => {
        if (event.target === ui.modal) ui.closeModal();
    });

    // Tab switching
    ui.tabContainer.addEventListener('click', (event) => {
        if (event.target.matches('.civitai-downloader-tab')) {
            ui.switchTab(event.target.dataset.tab);
        }
    });

    // --- FORMS ---
    ui.downloadForm.addEventListener('submit', (event) => {
        event.preventDefault();
        ui.handleDownloadSubmit();
    });

    ui.searchForm.addEventListener('submit', (event) => {
        event.preventDefault();
        if (!ui.searchQueryInput.value.trim() && ui.searchTypeSelect.value === 'any' && ui.searchBaseModelSelect.value === 'any') {
            ui.showToast("Please enter a search query or select a filter.", "error");
            if (ui.searchResultsContainer) ui.searchResultsContainer.innerHTML = '<p>Please enter a search query or select a filter.</p>';
            if (ui.searchPaginationContainer) ui.searchPaginationContainer.innerHTML = '';
            return;
        }
        ui.searchPagination.currentPage = 1;
        ui.handleSearchSubmit();
    });

    ui.settingsForm.addEventListener('submit', (event) => {
        event.preventDefault();
        ui.handleSettingsSave();
    });

    // Download form inputs
    ui.modelUrlInput.addEventListener('input', () => ui.debounceFetchDownloadPreview());
    ui.modelUrlInput.addEventListener('paste', () => ui.debounceFetchDownloadPreview(0));
    ui.modelVersionIdInput.addEventListener('blur', () => ui.fetchAndDisplayDownloadPreview());

    // --- DYNAMIC CONTENT LISTENERS (Event Delegation) ---

    // Status tab actions (Cancel/Retry/Open/Clear)
    ui.statusContent.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button) return;

        const downloadId = button.dataset.id;
        if (downloadId) {
            if (button.classList.contains('civitai-cancel-button')) ui.handleCancelDownload(downloadId);
            else if (button.classList.contains('civitai-retry-button')) ui.handleRetryDownload(downloadId, button);
            else if (button.classList.contains('civitai-openpath-button')) ui.handleOpenPath(downloadId, button);
        } else if (button.id === 'civitai-clear-history-button') {
            ui.confirmClearModal.style.display = 'flex';
        }
    });

    // Search results actions
    ui.searchResultsContainer.addEventListener('click', (event) => {
        const downloadButton = event.target.closest('.civitai-search-download-button');
        if (downloadButton) {
            event.preventDefault();
            const { modelId, versionId, modelType } = downloadButton.dataset;
            if (!modelId || !versionId) {
                ui.showToast("Error: Missing data for download.", "error");
                return;
            }
            const modelTypeInternalKey = Object.keys(ui.modelTypes).find(key => ui.modelTypes[key]?.toLowerCase() === modelType?.toLowerCase()) || ui.settings.defaultModelType;

            ui.modelUrlInput.value = modelId;
            ui.modelVersionIdInput.value = versionId;
            ui.customFilenameInput.value = '';
            ui.forceRedownloadCheckbox.checked = false;
            ui.downloadModelTypeSelect.value = modelTypeInternalKey;

            ui.switchTab('download');
            ui.showToast(`Filled download form for Model ID ${modelId}.`, 'info', 4000);
            ui.fetchAndDisplayDownloadPreview();
            return;
        }

        const viewAllButton = event.target.closest('.show-all-versions-button');
        if (viewAllButton) {
            const modelId = viewAllButton.dataset.modelId;
            const versionsContainer = ui.searchResultsContainer.querySelector(`#all-versions-${modelId}`);
            if (versionsContainer) {
                const currentlyVisible = versionsContainer.style.display !== 'none';
                versionsContainer.style.display = currentlyVisible ? 'none' : 'flex';
                viewAllButton.innerHTML = currentlyVisible
                    ? `All versions (${viewAllButton.dataset.totalVersions}) <i class="fas fa-chevron-down"></i>`
                    : `Show less <i class="fas fa-chevron-up"></i>`;
            }
        }
    });

    // Pagination
    ui.searchPaginationContainer.addEventListener('click', (event) => {
        const button = event.target.closest('.civitai-page-button');
        if (button && !button.disabled) {
            const page = parseInt(button.dataset.page, 10);
            if (page && page !== ui.searchPagination.currentPage) {
                ui.searchPagination.currentPage = page;
                ui.handleSearchSubmit();
            }
        }
    });

    // Confirmation Modal
    ui.confirmClearYesButton.addEventListener('click', () => ui.handleClearHistory());
    ui.confirmClearNoButton.addEventListener('click', () => {
        ui.confirmClearModal.style.display = 'none';
    });
    ui.confirmClearModal.addEventListener('click', (event) => {
        if (event.target === ui.confirmClearModal) {
            ui.confirmClearModal.style.display = 'none';
        }
    });
}