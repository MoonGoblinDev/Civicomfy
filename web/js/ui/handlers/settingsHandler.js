import { setCookie, getCookie } from "../../utils/cookies.js";
import { CivitaiDownloaderAPI } from "../../api/civitai.js";

const SETTINGS_COOKIE_NAME = 'civitaiDownloaderSettings';

export function getDefaultSettings() {
    return {
        apiKey: '',
        numConnections: 1,
        defaultModelType: 'checkpoints',
        autoOpenStatusTab: true,
        searchResultLimit: 20,
        hideMatureInSearch: true,
        nsfwBlurMinLevel: 4, // Blur thumbnails with nsfwLevel >= this value
    };
}

export function loadAndApplySettings(ui) {
    ui.settings = ui.loadSettingsFromCookie();
    ui.applySettings();
}

export function loadSettingsFromCookie(ui) {
    const defaults = ui.getDefaultSettings();
    const cookieValue = getCookie(SETTINGS_COOKIE_NAME);

    if (cookieValue) {
        try {
            const loadedSettings = JSON.parse(cookieValue);
            return { ...defaults, ...loadedSettings };
        } catch (e) {
            console.error("Failed to parse settings cookie:", e);
            return defaults;
        }
    }
    return defaults;
}

export function saveSettingsToCookie(ui) {
    try {
        const settingsString = JSON.stringify(ui.settings);
        setCookie(SETTINGS_COOKIE_NAME, settingsString, 365);
        ui.showToast('Settings saved successfully!', 'success');
    } catch (e) {
        console.error("Failed to save settings to cookie:", e);
        ui.showToast('Error saving settings', 'error');
    }
}

export function applySettings(ui) {
    if (ui.settingsApiKeyInput) {
        ui.settingsApiKeyInput.value = ui.settings.apiKey || '';
    }
    if (ui.settingsConnectionsInput) {
        ui.settingsConnectionsInput.value = Math.max(1, Math.min(16, ui.settings.numConnections || 1));
    }
    if (ui.settingsDefaultTypeSelect) {
        const desired = ui.settings.defaultModelType || 'checkpoints';
        ui.settingsDefaultTypeSelect.value = desired;
        if (!ui.settingsDefaultTypeSelect.querySelector(`option[value="${ui.settingsDefaultTypeSelect.value}"]`)) {
            const first = ui.settingsDefaultTypeSelect.querySelector('option');
            if (first) ui.settingsDefaultTypeSelect.value = first.value;
        }
    }
    if (ui.settingsAutoOpenCheckbox) {
        ui.settingsAutoOpenCheckbox.checked = ui.settings.autoOpenStatusTab === true;
    }
    if (ui.settingsHideMatureCheckbox) {
        ui.settingsHideMatureCheckbox.checked = ui.settings.hideMatureInSearch === true;
    }
    if (ui.settingsNsfwThresholdInput) {
        const val = Number(ui.settings.nsfwBlurMinLevel);
        ui.settingsNsfwThresholdInput.value = Number.isFinite(val) ? val : 4;
    }
    if (ui.downloadConnectionsInput) {
        ui.downloadConnectionsInput.value = Math.max(1, Math.min(16, ui.settings.numConnections || 1));
    }
    if (ui.downloadModelTypeSelect && Object.keys(ui.modelTypes).length > 0) {
        const desired = ui.settings.defaultModelType || 'checkpoints';
        ui.downloadModelTypeSelect.value = desired;
        if (!ui.downloadModelTypeSelect.querySelector(`option[value="${ui.downloadModelTypeSelect.value}"]`)) {
            const first = ui.downloadModelTypeSelect.querySelector('option');
            if (first) ui.downloadModelTypeSelect.value = first.value;
        }
    }
    ui.searchPagination.limit = ui.settings.searchResultLimit || 20;
}

export async function loadGlobalRootSetting(ui) {
    if (!ui.settingsGlobalRootInput) return;
    try {
        const result = await CivitaiDownloaderAPI.getGlobalRoot();
        const globalRoot = (result && typeof result.global_root === 'string') ? result.global_root : '';
        ui.settingsGlobalRootInput.value = globalRoot;
    } catch (e) {
        console.warn("[Civicomfy] Failed to load global root setting:", e);
    }
}

export async function handleSetGlobalRoot(ui) {
    if (!ui.settingsGlobalRootInput) return;
    const path = ui.settingsGlobalRootInput.value.trim();
    if (!path) {
        ui.showToast("Please enter a global root path first.", "error");
        return;
    }
    try {
        const result = await CivitaiDownloaderAPI.setGlobalRoot(path);
        const saved = (result && typeof result.global_root === 'string') ? result.global_root : path;
        ui.settingsGlobalRootInput.value = saved;
        ui.showToast("Global root updated.", "success");
        if (ui.downloadModelTypeSelect) {
            await ui.loadAndPopulateSubdirs(ui.downloadModelTypeSelect.value);
        }
    } catch (e) {
        ui.showToast(e.details || e.message || "Failed to set global root.", "error", 6000);
    }
}

export async function handleClearGlobalRoot(ui) {
    if (!ui.settingsGlobalRootInput) return;
    try {
        await CivitaiDownloaderAPI.clearGlobalRoot();
        ui.settingsGlobalRootInput.value = "";
        ui.showToast("Global root cleared. Using default ComfyUI paths.", "success");
        if (ui.downloadModelTypeSelect) {
            await ui.loadAndPopulateSubdirs(ui.downloadModelTypeSelect.value);
        }
    } catch (e) {
        ui.showToast(e.details || e.message || "Failed to clear global root.", "error", 6000);
    }
}

export function handleSettingsSave(ui) {
    const apiKey = ui.settingsApiKeyInput.value.trim();
    const numConnections = parseInt(ui.settingsConnectionsInput.value, 10);
    const defaultModelType = ui.settingsDefaultTypeSelect.value;
    const autoOpenStatusTab = ui.settingsAutoOpenCheckbox.checked;
    const hideMatureInSearch = ui.settingsHideMatureCheckbox.checked;
    const nsfwBlurMinLevel = Number(ui.settingsNsfwThresholdInput.value);

    if (isNaN(numConnections) || numConnections < 1 || numConnections > 16) {
        ui.showToast("Invalid Default Connections (must be 1-16).", "error");
        return;
    }
    if (!ui.settingsDefaultTypeSelect.querySelector(`option[value="${defaultModelType}"]`)) {
        ui.showToast("Invalid Default Model Type selected.", "error");
        return;
    }

    ui.settings.apiKey = apiKey;
    ui.settings.numConnections = numConnections;
    ui.settings.defaultModelType = defaultModelType;
    ui.settings.autoOpenStatusTab = autoOpenStatusTab;
    ui.settings.hideMatureInSearch = hideMatureInSearch;
    ui.settings.nsfwBlurMinLevel = (Number.isFinite(nsfwBlurMinLevel) && nsfwBlurMinLevel >= 0) ? Math.min(128, Math.round(nsfwBlurMinLevel)) : 4;

    ui.saveSettingsToCookie();
    ui.applySettings();
}
