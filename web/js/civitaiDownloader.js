import { app } from "../../../scripts/app.js";
import { addCssLink } from "./utils/dom.js";
import { CivitaiDownloaderUI } from "./ui/UI.js";

console.log("Loading Civicomfy UI...");

// --- Configuration ---
const EXTENSION_NAME = "Civicomfy";
const CSS_URL = `../civitaiDownloader.css`;
const PLACEHOLDER_IMAGE_URL = `/extensions/Civicomfy/images/placeholder.jpeg`;

// Add Menu Button to ComfyUI
function addMenuButton() {
    const buttonGroup = document.querySelector(".comfyui-button-group");

    if (!buttonGroup) {
        console.warn(`[${EXTENSION_NAME}] ComfyUI button group not found. Retrying...`);
        setTimeout(addMenuButton, 500);
        return;
    }

    if (document.getElementById("civitai-downloader-button")) {
        console.log(`[${EXTENSION_NAME}] Button already exists.`);
        return;
    }

    const civitaiButton = document.createElement("button");
    civitaiButton.textContent = "Civicomfy";
    civitaiButton.id = "civitai-downloader-button";
    civitaiButton.title = "Open Civicomfy";

    civitaiButton.onclick = async () => {
        if (!window.civitaiDownloaderUI) {
            console.info(`[${EXTENSION_NAME}] Creating CivitaiDownloaderUI instance...`);
            window.civitaiDownloaderUI = new CivitaiDownloaderUI();
            document.body.appendChild(window.civitaiDownloaderUI.modal);

            try {
                await window.civitaiDownloaderUI.initializeUI();
                console.info(`[${EXTENSION_NAME}] UI Initialization complete.`);
            } catch (error) {
                console.error(`[${EXTENSION_NAME}] Error during UI initialization:`, error);
                window.civitaiDownloaderUI?.showToast("Error initializing UI components. Check console.", "error", 5000);
            }
        }

        if (window.civitaiDownloaderUI) {
            window.civitaiDownloaderUI.openModal();
        } else {
            console.error(`[${EXTENSION_NAME}] Cannot open modal: UI instance not available.`);
            alert("Civicomfy failed to initialize. Please check the browser console for errors.");
        }
    };

    buttonGroup.appendChild(civitaiButton);
    console.log(`[${EXTENSION_NAME}] Civicomfy button added to .comfyui-button-group.`);

    const menu = document.querySelector(".comfy-menu");
    if (!buttonGroup.contains(civitaiButton) && menu && !menu.contains(civitaiButton)) {
        console.warn(`[${EXTENSION_NAME}] Failed to append button to group, falling back to menu.`);
        const settingsButton = menu.querySelector("#comfy-settings-button");
        if (settingsButton) {
            settingsButton.insertAdjacentElement("beforebegin", civitaiButton);
        } else {
            menu.appendChild(civitaiButton);
        }
    }
}

// --- Initialization ---
app.registerExtension({
    name: "Civicomfy.CivitaiDownloader",
    async setup(appInstance) {
        console.log(`[${EXTENSION_NAME}] Setting up Civicomfy Extension...`);
        addCssLink(CSS_URL);
        addMenuButton();

        // Optional: Pre-check placeholder image
        fetch(PLACEHOLDER_IMAGE_URL)
            .then(res => {
                if (!res.ok) {
                    console.warn(`[${EXTENSION_NAME}] Placeholder image not found at ${PLACEHOLDER_IMAGE_URL}.`);
                }
            })
            .catch(err => console.warn(`[${EXTENSION_NAME}] Error checking for placeholder image:`, err));

        console.log(`[${EXTENSION_NAME}] Extension setup complete. UI will initialize on first click.`);
    },
});
