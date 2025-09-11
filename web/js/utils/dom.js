// File: web/js/utils/dom.js

/**
 * Dynamically adds a CSS link to the document's head.
 * It resolves the path relative to this script's location using import.meta.url,
 * making it robust against case-sensitivity issues and different install paths.
 * @param {string} relativeHref - Relative path to the CSS file (e.g., '../civitaiDownloader.css').
 * @param {string} [id="civitai-downloader-styles"] - The ID for the link element.
 */
export function addCssLink(relativeHref, id = "civitai-downloader-styles") {
  if (document.getElementById(id)) return; // Prevent duplicates

  try {
    const absoluteUrl = new URL(relativeHref, import.meta.url);

    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = absoluteUrl.href;

    link.onload = () => {
      console.log("[Civicomfy] CSS loaded successfully:", link.href);
    };
    link.onerror = () => {
      console.error("[Civicomfy] Critical error: Failed to load CSS from:", link.href);
    };

    document.head.appendChild(link);
  } catch (e) {
    console.error("[Civicomfy] Error creating CSS link. import.meta.url may be unsupported in this context.", e);
  }
}
