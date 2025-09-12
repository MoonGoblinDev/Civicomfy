import { CivitaiDownloaderAPI } from "../../api/civitai.js";

export function debounceFetchDownloadPreview(ui, delay = 500) {
    clearTimeout(ui.modelPreviewDebounceTimeout);
    ui.modelPreviewDebounceTimeout = setTimeout(() => {
        fetchAndDisplayDownloadPreview(ui);
    }, delay);
}

export async function fetchAndDisplayDownloadPreview(ui) {
    const modelUrlOrId = ui.modelUrlInput.value.trim();
    const versionId = ui.modelVersionIdInput.value.trim();

    if (!modelUrlOrId) {
        ui.downloadPreviewArea.innerHTML = '';
        return;
    }

    ui.downloadPreviewArea.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Loading model details...</p>';
    ui.ensureFontAwesome();

    const params = {
        model_url_or_id: modelUrlOrId,
        model_version_id: versionId ? parseInt(versionId, 10) : null,
        api_key: ui.settings.apiKey
    };

    try {
        const result = await CivitaiDownloaderAPI.getModelDetails(params);
        if (result && result.success) {
            ui.renderDownloadPreview(result);
            // Auto-select model type save location based on Civitai model type
            if (result.model_type) {
                await ui.autoSelectModelTypeFromCivitai(result.model_type);
            }
        } else {
            const message = `Failed to get details: ${result.details || result.error || 'Unknown backend error'}`;
            ui.downloadPreviewArea.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
        }
    } catch (error) {
        const message = `Error fetching details: ${error.details || error.message || 'Unknown error'}`;
        console.error("Download Preview Fetch Error:", error);
        ui.downloadPreviewArea.innerHTML = `<p style="color: var(--error-text, #ff6b6b);">${message}</p>`;
    }
}

export async function handleDownloadSubmit(ui) {
    if (!ui.settings.apiKey) {
        ui.showToast("API key empty, please fill your API key in the settings", "error");
        ui.switchTab("settings");
        return;
    }

    ui.downloadSubmitButton.disabled = true;
    ui.downloadSubmitButton.textContent = 'Starting...';

    const modelUrlOrId = ui.modelUrlInput.value.trim();
    if (!modelUrlOrId) {
        ui.showToast("Model URL or ID cannot be empty.", "error");
        ui.downloadSubmitButton.disabled = false;
        ui.downloadSubmitButton.textContent = 'Start Download';
        return;
    }

    // Subfolder comes from dropdown; filename is base name only
    const selectedSubdir = ui.subdirSelect ? ui.subdirSelect.value.trim() : '';
    const userFilename = ui.customFilenameInput.value.trim();

    const params = {
        model_url_or_id: modelUrlOrId,
        model_type: ui.downloadModelTypeSelect.value,
        model_version_id: ui.modelVersionIdInput.value ? parseInt(ui.modelVersionIdInput.value, 10) : null,
        custom_filename: userFilename,
        subdir: selectedSubdir,
        num_connections: parseInt(ui.downloadConnectionsInput.value, 10),
        force_redownload: ui.forceRedownloadCheckbox.checked,
        api_key: ui.settings.apiKey
    };

    const fileSelectEl = ui.modal.querySelector('#civitai-file-select');
    if (fileSelectEl && fileSelectEl.value) {
        const fid = parseInt(fileSelectEl.value, 10);
        if (!Number.isNaN(fid)) params.file_id = fid;
    }

    try {
        const result = await CivitaiDownloaderAPI.downloadModel(params);

        if (result.status === 'queued') {
            ui.showToast(`Download queued: ${result.details?.filename || 'Model'}`, 'success');
            if (ui.settings.autoOpenStatusTab) {
                ui.switchTab('status');
            } else {
                ui.updateStatus();
            }
        } else if (result.status === 'exists' || result.status === 'exists_size_mismatch') {
            ui.showToast(`${result.message}`, 'info', 4000);
        } else {
            console.warn("Unexpected success response from /civitai/download:", result);
            ui.showToast(`Unexpected status: ${result.status} - ${result.message || ''}`, 'info');
        }
    } catch (error) {
        const message = `Download failed: ${error.details || error.message || 'Unknown error'}`;
        console.error("Download Submit Error:", error);
        ui.showToast(message, 'error', 6000);
    } finally {
        ui.downloadSubmitButton.disabled = false;
        ui.downloadSubmitButton.textContent = 'Start Download';
    }
}
