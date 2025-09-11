// Renders active/queued/history download lists

const PLACEHOLDER_IMAGE_URL = `/extensions/Civicomfy/images/placeholder.jpeg`;

export function renderDownloadList(ui, items, container, emptyMessage) {
  if (!items || items.length === 0) {
    container.innerHTML = `<p>${emptyMessage}</p>`;
    return;
  }

  const fragment = document.createDocumentFragment();
  items.forEach(item => {
    const id = item.id || 'unknown-id';
    const progress = item.progress !== undefined ? Math.max(0, Math.min(100, item.progress)) : 0;
    const speed = item.speed !== undefined ? Math.max(0, item.speed) : 0;
    const status = item.status || 'unknown';
    const size = item.known_size !== undefined && item.known_size !== null ? item.known_size : (item.file_size || 0);
    const downloadedBytes = size > 0 ? size * (progress / 100) : 0;
    const errorMsg = item.error || null;
    const modelName = item.model_name || item.model?.name || 'Unknown Model';
    const versionName = item.version_name || 'Unknown Version';
    const filename = item.filename || 'N/A';
    const addedTime = item.added_time || null;
    const startTime = item.start_time || null;
    const endTime = item.end_time || null;
    const thumbnail = item.thumbnail || PLACEHOLDER_IMAGE_URL;
    const nsfwLevel = Number(item.thumbnail_nsfw_level ?? 0);
    const blurMinLevel = Number(ui.settings?.nsfwBlurMinLevel ?? 4);
    const shouldBlur = ui.settings?.hideMatureInSearch === true && nsfwLevel >= blurMinLevel;
    const connectionType = item.connection_type || "N/A";

    let progressBarClass = '';
    let statusText = status.charAt(0).toUpperCase() + status.slice(1);
    switch (status) {
      case 'completed': progressBarClass = 'completed'; break;
      case 'failed': progressBarClass = 'failed'; statusText = 'Failed'; break;
      case 'cancelled': progressBarClass = 'cancelled'; statusText = 'Cancelled'; break;
      case 'downloading': case 'queued': case 'starting': default: break;
    }

    const listItem = document.createElement('div');
    listItem.className = 'civitai-download-item';
    listItem.dataset.id = id;

    const onErrorScript = `this.onerror=null; this.src='${PLACEHOLDER_IMAGE_URL}'; this.style.backgroundColor='#444';`;
    const addedTooltip = addedTime ? `data-tooltip="Added: ${new Date(addedTime).toLocaleString()}"` : '';
    const startedTooltip = startTime ? `data-tooltip="Started: ${new Date(startTime).toLocaleString()}"` : '';
    const endedTooltip = endTime ? `data-tooltip="Ended: ${new Date(endTime).toLocaleString()}"` : '';
    const durationTooltip = startTime && endTime ? `data-tooltip="Duration: ${ui.formatDuration(startTime, endTime)}"` : '';
    const filenameTooltip = filename !== 'N/A' ? `title="Filename: ${filename}"` : '';
    const errorTooltip = errorMsg ? `title="Error Details: ${String(errorMsg).substring(0, 200)}${String(errorMsg).length > 200 ? '...' : ''}"` : '';
    const connectionInfoHtml = connectionType !== "N/A" ? `<span style="font-size: 0.85em; color: #aaa; margin-left: 10px;">(Conn: ${connectionType})</span>` : '';

    const overlayHtml = shouldBlur ? `<div class=\"civitai-nsfw-overlay\" title=\"R-rated: click to reveal\">R</div>` : '';
    const containerClasses = `civitai-thumbnail-container${shouldBlur ? ' blurred' : ''}`;

    let innerHTML = `
      <div class="${containerClasses}" data-nsfw-level="${Number.isFinite(nsfwLevel) ? nsfwLevel : ''}">
        <img src="${thumbnail}" alt="thumbnail" class="civitai-download-thumbnail" loading="lazy" onerror="${onErrorScript}">
        ${overlayHtml}
      </div>
      <div class="civitai-download-info">
        <strong>${modelName}</strong>
        <p>Ver: ${versionName}</p>
        <p class="filename" ${filenameTooltip}>${filename}</p>
        ${size > 0 ? `<p>Size: ${ui.formatBytes(size)}</p>` : ''}
        ${item.file_format ? `<p>Format: ${item.file_format}</p>` : ''}
        ${item.file_precision || item.file_model_size ? `<p>${item.file_precision ? 'Precision: ' + String(item.file_precision).toUpperCase() : ''}${item.file_precision && item.file_model_size ? ' • ' : ''}${item.file_model_size ? 'Model Size: ' + item.file_model_size : ''}</p>` : ''}
        ${errorMsg ? `<p class="error-message" ${errorTooltip}><i class="fas fa-exclamation-triangle"></i> ${String(errorMsg).substring(0, 100)}${String(errorMsg).length > 100 ? '...' : ''}</p>` : ''}
    `;

    if (status === 'downloading' || status === 'starting' || status === 'completed') {
      const statusLine = `<div ${durationTooltip} ${endedTooltip}>Status: ${statusText} ${connectionInfoHtml}</div>`;
      innerHTML += `
        <div class="civitai-progress-container" title="${statusText} - ${progress.toFixed(1)}%">
          <div class="civitai-progress-bar ${progressBarClass}" style="width: ${progress}%;">
            ${progress > 15 ? progress.toFixed(0)+'%' : ''}
          </div>
        </div>
      `;
      const speedText = (status === 'downloading' && speed > 0) ? ui.formatSpeed(speed) : '';
      const progressText = (status === 'downloading' && size > 0) ? `(${ui.formatBytes(downloadedBytes)} / ${ui.formatBytes(size)})` : '';
      const completedText = status === 'completed' ? '' : '';
      const speedProgLine = `<div class="civitai-speed-indicator">${speedText} ${progressText} ${completedText}</div>`;
      if (status === 'downloading') { innerHTML += speedProgLine; }
      innerHTML += statusLine;
    } else if (status === 'failed' || status === 'cancelled' || status === 'queued') {
      innerHTML += `<div class="status-line-simple" ${durationTooltip} ${endedTooltip} ${addedTooltip}>Status: ${statusText} ${connectionInfoHtml}</div>`;
    } else {
      innerHTML += `<div class="status-line-simple">Status: ${statusText} ${connectionInfoHtml}</div>`;
    }

    innerHTML += `</div>`;
    innerHTML += `<div class="civitai-download-actions">`;
    if (status === 'queued' || status === 'downloading' || status === 'starting') {
      innerHTML += `<button class="civitai-button danger small civitai-cancel-button" data-id="${id}" title="Cancel Download"><i class="fas fa-times"></i></button>`;
    }
    if (status === 'failed' || status === 'cancelled') {
      innerHTML += `<button class="civitai-button small civitai-retry-button" data-id="${id}" title="Retry Download"><i class="fas fa-redo"></i></button>`;
    }
    if (status === 'completed') {
      innerHTML += `<button class="civitai-button small civitai-openpath-button" data-id="${id}" title="Open Containing Folder"><i class="fas fa-folder-open"></i></button>`;
    }
    innerHTML += `</div>`;

    listItem.innerHTML = innerHTML;
    fragment.appendChild(listItem);
  });

  container.innerHTML = '';
  container.appendChild(fragment);
  ui.ensureFontAwesome();
}
