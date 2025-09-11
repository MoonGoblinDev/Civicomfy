import { setCookie, getCookie } from "../../utils/cookies.js";

const SETTINGS_COOKIE_NAME = 'civitaiDownloaderSettings';

export function getDefaultSettings() {
    return {
        apiKey: '',
        numConnections: 1,
        defaultModelType: 'checkpoint',
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
        ui.settingsDefaultTypeSelect.value = ui.settings.defaultModelType || 'checkpoint';
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
        ui.downloadModelTypeSelect.value = ui.settings.defaultModelType || 'checkpoint';
    }
    ui.searchPagination.limit = ui.settings.searchResultLimit || 20;
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
