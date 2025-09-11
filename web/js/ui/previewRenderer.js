// Renders the download preview panel

const PLACEHOLDER_IMAGE_URL = `/extensions/Civicomfy/images/placeholder.jpeg`;

export function renderDownloadPreview(ui, data) {
  if (!ui.downloadPreviewArea) return;
  ui.ensureFontAwesome();

  const modelId = data.model_id;
  const modelName = data.model_name || 'Untitled Model';
  const creator = data.creator_username || 'Unknown Creator';
  const modelType = data.model_type || 'N/A';
  const versionName = data.version_name || 'N/A';
  const baseModel = data.base_model || 'N/A';
  const stats = data.stats || {};
  const descriptionHtml = data.description_html || '<p><em>No description.</em></p>';
  const version_description_html = data.version_description_html || '<p><em>No description.</em></p>';
  const fileInfo = data.file_info || {};
  const files = Array.isArray(data.files) ? data.files : [];
  const thumbnail = data.thumbnail_url || PLACEHOLDER_IMAGE_URL;
  const nsfwLevel = Number(data.nsfw_level ?? 0);
  const blurMinLevel = Number(ui.settings?.nsfwBlurMinLevel ?? 4);
  const shouldBlur = ui.settings?.hideMatureInSearch === true && nsfwLevel >= blurMinLevel;
  const civitaiLink = `https://civitai.com/models/${modelId}${data.version_id ? '?modelVersionId=' + data.version_id : ''}`;

  const onErrorScript = `this.onerror=null; this.src='${PLACEHOLDER_IMAGE_URL}'; this.style.backgroundColor='#444';`;

  const overlayHtml = shouldBlur ? `<div class="civitai-nsfw-overlay" title="R-rated: click to reveal">R</div>` : '';
  const containerClasses = `civitai-thumbnail-container${shouldBlur ? ' blurred' : ''}`;

  const previewHtml = `
    <div class="civitai-search-item" style="background-color: var(--comfy-input-bg);">
      <div class="${containerClasses}" data-nsfw-level="${Number.isFinite(nsfwLevel) ? nsfwLevel : ''}">
        <img src="${thumbnail}" alt="${modelName} thumbnail" class="civitai-search-thumbnail" loading="lazy" onerror="${onErrorScript}">
        ${overlayHtml}
        <div class="civitai-type-badge">${modelType}</div>
      </div>
      <div class="civitai-search-info">
        <h4>${modelName} <span style="font-weight: normal; font-size: 0.9em;">by ${creator}</span></h4>
        <p style="font-weight: bold;">Version: ${versionName} <span class="base-model-badge" style="margin-left: 5px;">${baseModel}</span></p>
        <div class="civitai-search-stats" title="Stats: Downloads / Rating (Count) / Likes">
          <span title="Downloads"><i class="fas fa-download"></i> ${stats.downloads?.toLocaleString() || 0}</span>
          <span title="Likes"><i class="fas fa-thumbs-up"></i> ${stats.likes?.toLocaleString(0) || 0}</span>
          <span title="Dislikes"><i class="fas fa-thumbs-down"></i> ${stats.dislikes?.toLocaleString() || 0}</span>
          <span title="Buzz"><i class="fas fa-bolt"></i> ${stats.buzz?.toLocaleString() || 0}</span>
        </div>
        <p style="font-weight: bold; margin-top: 10px;">Primary File:</p>
        <p style="font-size: 0.9em; color: #ccc;">
          Name: ${fileInfo.name || 'N/A'}<br>
          Size: ${ui.formatBytes(fileInfo.size_kb * 1024) || 'N/A'} <br>
          Format: ${fileInfo.format || 'N/A'}<br>
          Precision: ${fileInfo.precision || 'N/A'}<br>
          Model Size: ${fileInfo.model_size || 'N/A'}
        </p>
        ${files.length > 0 ? `
          <div class=\"civitai-form-group\" style=\"margin-top: 10px;\">
            <label for=\"civitai-file-select\">Choose File (optional)</label>
            <select id=\"civitai-file-select\" class=\"civitai-select\">
              <option value=\"\">Auto (primary/best)</option>
              ${files.map(f => {
                const id = f.id ?? '';
                const name = (f.name || '').replace(/</g,'&lt;');
                const fmt = f.format || 'N/A';
                const prec = (f.precision || '').toUpperCase();
                const msize = f.model_size || '';
                const size = (typeof f.size_kb === 'number') ? ui.formatBytes(f.size_kb * 1024) : 'N/A';
                const disabled = f.downloadable ? '' : 'disabled';
                const title = f.downloadable ? '' : ' (not downloadable)';
                const extras = [prec, msize].filter(Boolean).join(' • ');
                return `<option value=\"${id}\" ${disabled}>#${id} • ${name} • ${fmt}${extras ? ' • ' + extras : ''} • ${size}${title}</option>`;
              }).join('')}
            </select>
            <p style=\"font-size: 0.9em; color: #aaa; margin-top: 6px;\">Pick other variants when available.</p>
          </div>
        ` : ''}
        <a href="${civitaiLink}" target="_blank" rel="noopener noreferrer" class="civitai-button small" title="Open on Civitai website" style="margin-top: 5px; display: inline-block;">
          View on Civitai <i class="fas fa-external-link-alt"></i>
        </a>
      </div>
    </div>
    <div style="margin-top: 15px;">
      <h5 style="margin-bottom: 5px;">Model Description:</h5>
      <div class="model-description-content" style="max-height: 200px; overflow-y: auto; background-color: var(--comfy-input-bg); padding: 10px; border-radius: 4px; font-size: 0.9em; border: 1px solid var(--border-color, #555);">
        ${descriptionHtml}
      </div>
    </div>
    <div style="margin-top: 15px;">
      <h5 style="margin-bottom: 5px;">Version Description:</h5>
      <div class="model-description-content" style="max-height: 200px; overflow-y: auto; background-color: var(--comfy-input-bg); padding: 10px; border-radius: 4px; font-size: 0.9em; border: 1px solid var(--border-color, #555);">
        ${version_description_html}
      </div>
    </div>
  `;

  ui.downloadPreviewArea.innerHTML = previewHtml;
}
