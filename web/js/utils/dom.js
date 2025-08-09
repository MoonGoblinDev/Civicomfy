// DOM-related helpers for Civicomfy UI
// Exports: addCssLink

export function addCssLink(href, id = "civitai-downloader-styles") {
  if (document.getElementById(id)) return; // Prevent duplicates
  
  // Try multiple potential paths for ComfyUI extension CSS
  const possiblePaths = [
    `/extensions/Civicomfy/js/${href}`, // Most likely correct path for ComfyUI extensions
    `/extensions/Civicomfy/${href}`,
    `/custom_nodes/Civicomfy/web/js/${href}`,
    `extensions/Civicomfy/js/${href}`, // Without leading slash
    `extensions/Civicomfy/${href}`,
    `/web/extensions/Civicomfy/js/${href}`,
    `./web/js/${href}`,
    `./${href}`,
    `../js/${href}`,
    `../../../custom_nodes/Civicomfy/web/js/${href}`
  ];
  
  console.log("[Civicomfy] Attempting to load CSS, trying paths:", possiblePaths);
  
  let pathIndex = 0;
  
  function tryNextPath() {
    if (pathIndex >= possiblePaths.length) {
      console.error("[Civicomfy] All CSS paths failed, injecting inline styles as fallback");
      injectFallbackStyles();
      return;
    }
    
    const cssPath = possiblePaths[pathIndex];
    const link = document.createElement("link");
    link.id = pathIndex === 0 ? id : `${id}-${pathIndex}`;
    link.rel = "stylesheet";
    link.href = cssPath;
    
    link.onload = () => {
      console.log("[Civicomfy] CSS loaded successfully:", cssPath);
    };
    
    link.onerror = () => {
      console.warn("[Civicomfy] Failed to load CSS from:", cssPath);
      document.head.removeChild(link);
      pathIndex++;
      tryNextPath();
    };
    
    document.head.appendChild(link);
  }
  
  // Start trying paths
  tryNextPath();
}

function injectFallbackStyles() {
  console.log("[Civicomfy] Injecting comprehensive fallback styles");
  
  // Remove any existing styles first
  const existingStyle = document.getElementById('civitai-downloader-fallback-styles');
  if (existingStyle) {
    existingStyle.remove();
  }
  
  const style = document.createElement('style');
  style.id = 'civitai-downloader-fallback-styles';
  
  // Also directly apply styles via JavaScript as a backup
  setTimeout(() => {
    console.log("[Civicomfy] Applying direct JavaScript styling to badges");
    const badges = document.querySelectorAll('.civitai-type-badge');
    console.log(`[Civicomfy] Found ${badges.length} badges to style`);
    
    badges.forEach((badge, index) => {
      console.log(`[Civicomfy] Badge ${index}: data-type="${badge.dataset.type}", current styles:`, {
        position: getComputedStyle(badge).position,
        top: getComputedStyle(badge).top,
        right: getComputedStyle(badge).right,
        backgroundColor: getComputedStyle(badge).backgroundColor,
        zIndex: getComputedStyle(badge).zIndex
      });
      
      // Force styles directly via JavaScript
      badge.style.setProperty('position', 'absolute', 'important');
      badge.style.setProperty('top', '8px', 'important');
      badge.style.setProperty('right', '8px', 'important');
      badge.style.setProperty('z-index', '999', 'important');
      badge.style.setProperty('color', 'white', 'important');
      badge.style.setProperty('padding', '4px 8px', 'important');
      badge.style.setProperty('border-radius', '4px', 'important');
      badge.style.setProperty('font-size', '0.7em', 'important');
      badge.style.setProperty('font-weight', 'bold', 'important');
      badge.style.setProperty('white-space', 'nowrap', 'important');
      badge.style.setProperty('text-transform', 'uppercase', 'important');
      badge.style.setProperty('letter-spacing', '0.5px', 'important');
      badge.style.setProperty('box-shadow', '0 2px 4px rgba(0, 0, 0, 0.5)', 'important');
      badge.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.2)', 'important');
      badge.style.setProperty('line-height', '1', 'important');
      badge.style.setProperty('display', 'block', 'important');
      
      // Type-specific colors
      const dataType = badge.dataset.type;
      let bgColor = '#666';
      switch(dataType) {
        case 'checkpoint': bgColor = '#e74c3c'; break;
        case 'lora': bgColor = '#3498db'; break;
        case 'lycoris': bgColor = '#9b59b6'; break;
        case 'locon': bgColor = '#8e44ad'; break;
        case 'embedding': bgColor = '#f39c12'; break;
        case 'hypernetwork': bgColor = '#e67e22'; break;
        case 'vae': bgColor = '#1abc9c'; break;
        case 'controlnet': bgColor = '#16a085'; break;
        case 'upscaler': bgColor = '#2ecc71'; break;
        case 'motionmodule': bgColor = '#f1c40f'; break;
        case 'poses': bgColor = '#e91e63'; break;
        case 'wildcards': bgColor = '#795548'; break;
        case 'other': bgColor = '#607d8b'; break;
        case 'diffusionmodels': bgColor = '#ff5722'; break;
        case 'unet': bgColor = '#673ab7'; break;
      }
      badge.style.setProperty('background-color', bgColor, 'important');
      
      console.log(`[Civicomfy] Badge ${index} styled with data-type="${dataType}" color="${bgColor}"`);
    });
  }, 500);  // Wait a bit for DOM to be ready
  
  // Create styles with very high specificity to override any existing CSS
  style.textContent = `
/* HIGH PRIORITY BADGE STYLES */
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge {
  position: absolute !important;
  top: 8px !important;
  right: 8px !important;
  color: white !important;
  padding: 4px 8px !important;
  border-radius: 4px !important;
  font-size: 0.7em !important;
  font-weight: bold !important;
  z-index: 999 !important;
  white-space: nowrap !important;
  text-transform: uppercase !important;
  letter-spacing: 0.5px !important;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.5) !important;
  background-color: #666 !important;
  border: 1px solid rgba(255, 255, 255, 0.2) !important;
  line-height: 1 !important;
  display: block !important;
}

/* TYPE COLORS WITH ULTRA HIGH SPECIFICITY */
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="checkpoint"] { background-color: #e74c3c !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="lora"] { background-color: #3498db !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="lycoris"] { background-color: #9b59b6 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="locon"] { background-color: #8e44ad !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="embedding"] { background-color: #f39c12 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="hypernetwork"] { background-color: #e67e22 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="vae"] { background-color: #1abc9c !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="controlnet"] { background-color: #16a085 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="upscaler"] { background-color: #2ecc71 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="motionmodule"] { background-color: #f1c40f !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="poses"] { background-color: #e91e63 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="wildcards"] { background-color: #795548 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="other"] { background-color: #607d8b !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="diffusionmodels"] { background-color: #ff5722 !important; }
div.civitai-search-item div.civitai-thumbnail-container div.civitai-type-badge[data-type="unet"] { background-color: #673ab7 !important; }

/* CONTAINER POSITIONING */  
.civitai-thumbnail-container {
  position: relative !important;
  display: block !important;
  width: 180px !important;
  height: 100% !important;
  min-height: 200px !important;
  flex-shrink: 0 !important;
  overflow: visible !important;
  border-radius: 4px !important;
}

.civitai-search-thumbnail {
  width: 100% !important;
  height: 100% !important;
  object-fit: cover !important;
  border-radius: 4px !important;
  background-color: #333 !important;
}

/* BASIC MODAL STYLES */
.civitai-downloader-modal {
  position: fixed !important;
  z-index: 1001 !important;
  left: 0 !important;
  top: 0 !important;
  width: 100% !important;
  height: 100% !important;
  background-color: rgba(0, 0, 0, 0.6) !important;
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  opacity: 0 !important;
  visibility: hidden !important;
  transition: opacity 0.3s ease, visibility 0s linear 0.3s !important;
}

.civitai-downloader-modal.open {
  opacity: 1 !important;
  visibility: visible !important;
  transition: opacity 0.3s ease !important;
}

.civitai-downloader-modal-content {
  background-color: var(--comfy-menu-bg, #202020) !important;
  color: var(--comfy-text-color, #fff) !important;
  border-radius: 8px !important;
  width: 900px !important;
  max-width: 95% !important;
  height: 700px !important;
  max-height: 90vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.civitai-search-item {
  display: flex !important;
  gap: 15px !important;
  align-items: flex-start !important;
  margin-bottom: 15px !important;
  padding: 15px !important;
  border-radius: 6px !important;
  background-color: var(--comfy-input-bg, #333) !important;
  border: 1px solid var(--border-color, #555) !important;
  min-height: 200px !important;
  overflow: visible !important;
}

/* OTHER ESSENTIAL STYLES */
.civitai-downloader-header {
  display: flex !important;
  justify-content: space-between !important;
  align-items: center !important;
  padding: 15px 20px !important;
  border-bottom: 1px solid var(--border-color, #444) !important;
}

.civitai-downloader-body {
  display: flex !important;
  flex-direction: column !important;
  flex-grow: 1 !important;
  overflow: hidden !important;
}

.civitai-downloader-tabs {
  display: flex !important;
  border-bottom: 1px solid var(--border-color, #444) !important;
  padding: 0 15px !important;
}

.civitai-downloader-tab {
  padding: 10px 18px !important;
  cursor: pointer !important;
  border: none !important;
  background: none !important;
  color: var(--comfy-text-color, #fff) !important;
  opacity: 0.7 !important;
}

.civitai-downloader-tab.active {
  opacity: 1 !important;
  border-bottom: 3px solid var(--accent-color, #5c8aff) !important;
  font-weight: bold !important;
}

.civitai-downloader-tab-content {
  display: none !important;
  padding: 20px !important;
  flex-grow: 1 !important;
  overflow-y: auto !important;
}

.civitai-downloader-tab-content.active {
  display: block !important;
}

.civitai-close-button {
  background: none !important;
  border: none !important;
  color: var(--comfy-text-color, #fff) !important;
  font-size: 28px !important;
  cursor: pointer !important;
  padding: 0 5px !important;
}
  `;
  
  document.head.appendChild(style);
  console.log("[Civicomfy] High-priority fallback styles injected with ultra-specific selectors");
}

