import { CivitaiDownloaderAPI } from "../../api/civitai.js";

export function startStatusUpdates(ui) {
    if (!ui.statusInterval) {
        console.log("[Civicomfy] Starting status updates (every 3s)...");
        ui.updateStatus();
        ui.statusInterval = setInterval(() => ui.updateStatus(), 3000);
    }
}

export function stopStatusUpdates(ui) {
    if (ui.statusInterval) {
        clearInterval(ui.statusInterval);
        ui.statusInterval = null;
        console.log("[Civicomfy] Stopped status updates.");
    }
}

export async function updateStatus(ui) {
    if (!ui.modal || !ui.modal.classList.contains('open')) return;

    try {
        const newStatusData = await CivitaiDownloaderAPI.getStatus();
        if (!newStatusData || !Array.isArray(newStatusData.active) || !Array.isArray(newStatusData.queue) || !Array.isArray(newStatusData.history)) {
            throw new Error("Invalid status data structure received from server.");
        }

        const oldStateString = JSON.stringify(ui.statusData);
        const newStateString = JSON.stringify(newStatusData);

        // Cache new state if it differs
        if (oldStateString !== newStateString) {
            ui.statusData = newStatusData;
        }

        // Always keep counters in sync
        const activeCount = ui.statusData.active.length + ui.statusData.queue.length;
        ui.activeCountSpan.textContent = activeCount;
        ui.statusIndicator.style.display = activeCount > 0 ? 'inline' : 'none';

        // Always render when Status tab is active, even if data hasn't changed
        if (ui.activeTab === 'status') {
            ui.renderDownloadList(ui.statusData.active, ui.activeListContainer, 'No active downloads.');
            ui.renderDownloadList(ui.statusData.queue, ui.queuedListContainer, 'Download queue is empty.');
            ui.renderDownloadList(ui.statusData.history, ui.historyListContainer, 'No download history yet.');
        }
    } catch (error) {
        console.error("[Civicomfy] Failed to update status:", error);
        if (ui.activeTab === 'status') {
            const errorHtml = `<p style="color: var(--error-text, #ff6b6b);">${error.details || error.message}</p>`;
            if (ui.activeListContainer) ui.activeListContainer.innerHTML = errorHtml;
            if (ui.queuedListContainer) ui.queuedListContainer.innerHTML = '';
            if (ui.historyListContainer) ui.historyListContainer.innerHTML = '';
        }
    }
}

export async function handleCancelDownload(ui, downloadId) {
    const button = ui.modal.querySelector(`.civitai-cancel-button[data-id="${downloadId}"]`);
    if (button) {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        button.title = "Cancelling...";
    }
    try {
        const result = await CivitaiDownloaderAPI.cancelDownload(downloadId);
        ui.showToast(result.message || `Cancellation requested for ${downloadId}`, 'info');
        ui.updateStatus();
    } catch (error) {
        const message = `Cancel failed: ${error.details || error.message}`;
        console.error("Cancel Download Error:", error);
        ui.showToast(message, 'error');
        if (button) {
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-times"></i>';
            button.title = "Cancel Download";
        }
    }
}

export async function handleRetryDownload(ui, downloadId, button) {
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    button.title = "Retrying...";
    try {
        const result = await CivitaiDownloaderAPI.retryDownload(downloadId);
        if (result.success) {
            ui.showToast(result.message || `Retry queued successfully!`, 'success');
            if (ui.settings.autoOpenStatusTab) ui.switchTab('status');
            else ui.updateStatus();
        } else {
            ui.showToast(`Retry failed: ${result.details || result.error}`, 'error', 5000);
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-redo"></i>';
            button.title = "Retry Download";
        }
    } catch (error) {
        const message = `Retry failed: ${error.details || error.message}`;
        console.error("Retry Download UI Error:", error);
        ui.showToast(message, 'error', 5000);
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-redo"></i>';
        button.title = "Retry Download";
    }
}

export async function handleOpenPath(ui, downloadId, button) {
    const originalIcon = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    button.title = "Opening...";
    try {
        const result = await CivitaiDownloaderAPI.openPath(downloadId);
        if (result.success) {
            ui.showToast(result.message || `Opened path successfully!`, 'success');
        } else {
            ui.showToast(`Open path failed: ${result.details || result.error}`, 'error', 5000);
        }
    } catch (error) {
        const message = `Open path failed: ${error.details || error.message}`;
        console.error("Open Path UI Error:", error);
        ui.showToast(message, 'error', 5000);
    } finally {
        button.disabled = false;
        button.innerHTML = originalIcon;
        button.title = "Open Containing Folder";
    }
}

export async function handleClearHistory(ui) {
    ui.confirmClearYesButton.disabled = true;
    ui.confirmClearNoButton.disabled = true;
    ui.confirmClearYesButton.textContent = 'Clearing...';

    try {
        const result = await CivitaiDownloaderAPI.clearHistory();
        if (result.success) {
            ui.showToast(result.message || 'History cleared successfully!', 'success');
            ui.statusData.history = [];
            ui.renderDownloadList(ui.statusData.history, ui.historyListContainer, 'No download history yet.');
            ui.confirmClearModal.style.display = 'none';
        } else {
            ui.showToast(`Clear history failed: ${result.details || result.error}`, 'error', 5000);
        }
    } catch (error) {
        const message = `Clear history failed: ${error.details || error.message}`;
        console.error("Clear History UI Error:", error);
        ui.showToast(message, 'error', 5000);
    } finally {
        ui.confirmClearYesButton.disabled = false;
        ui.confirmClearNoButton.disabled = false;
        ui.confirmClearYesButton.textContent = 'Confirm Clear';
    }
}
