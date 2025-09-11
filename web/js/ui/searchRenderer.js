// Rendering of search results list
// Usage: renderSearchResults(uiInstance, itemsArray)

const PLACEHOLDER_IMAGE_URL = `/extensions/Civicomfy/images/placeholder.jpeg`;

export function renderSearchResults(ui, items) {
  ui.feedback?.ensureFontAwesome();

  if (!items || items.length === 0) {
    const queryUsed = ui.searchQueryInput && ui.searchQueryInput.value.trim();
    const typeFilterUsed = ui.searchTypeSelect && ui.searchTypeSelect.value !== 'any';
    const baseModelFilterUsed = ui.searchBaseModelSelect && ui.searchBaseModelSelect.value !== 'any';
    const message = (queryUsed || typeFilterUsed || baseModelFilterUsed)
      ? 'No models found matching your criteria.'
      : 'Enter a query or select filters and click Search.';
    ui.searchResultsContainer.innerHTML = `<p>${message}</p>`;
    return;
  }

  const placeholder = PLACEHOLDER_IMAGE_URL;
  const onErrorScript = `this.onerror=null; this.src='${placeholder}'; this.style.backgroundColor='#444';`;
  const fragment = document.createDocumentFragment();

  items.forEach(hit => {
    const modelId = hit.id;
    if (!modelId) return;

    const creator = hit.user?.username || 'Unknown Creator';
    const modelName = hit.name || 'Untitled Model';
    const modelTypeApi = hit.type || 'other';
    console.log('Model type for badge:', modelTypeApi);
    const stats = hit.metrics || {};
    const tags = hit.tags?.map(t => t.name) || [];

    const thumbnailUrl = hit.thumbnailUrl || placeholder;
    const firstImage = Array.isArray(hit.images) && hit.images.length > 0 ? hit.images[0] : null;
    const thumbnailType = firstImage?.type;
    const nsfwLevel = Number(firstImage?.nsfwLevel ?? hit.nsfwLevel ?? 0);
    const blurMinLevel = Number(ui.settings?.nsfwBlurMinLevel ?? 4);
    const shouldBlur = ui.settings?.hideMatureInSearch === true && nsfwLevel >= blurMinLevel;

    const allVersions = hit.versions || [];
    const primaryVersion = hit.version || (allVersions.length > 0 ? allVersions[0] : {});
    const primaryVersionId = primaryVersion.id;
    const primaryBaseModel = primaryVersion.baseModel || 'N/A';

    const uniqueBaseModels = allVersions.length > 0
      ? [...new Set(allVersions.map(v => v.baseModel).filter(Boolean))]
      : (primaryBaseModel !== 'N/A' ? [primaryBaseModel] : []);
    const baseModelsDisplay = uniqueBaseModels.length > 0 ? uniqueBaseModels.join(', ') : 'N/A';

    const publishedAt = hit.publishedAt;
    let lastUpdatedFormatted = 'N/A';
    if (publishedAt) {
      try {
        const date = new Date(publishedAt);
        lastUpdatedFormatted = date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
      } catch (_) {}
    }

    const listItem = document.createElement('div');
    listItem.className = 'civitai-search-item';
    listItem.dataset.modelId = modelId;

    const MAX_VISIBLE_VERSIONS = 3;
    let visibleVersions = [];
    if (primaryVersionId) {
      visibleVersions.push({ id: primaryVersionId, name: primaryVersion.name || 'Primary Version', baseModel: primaryBaseModel });
    }
    allVersions.forEach(v => {
      if (v.id !== primaryVersionId && visibleVersions.length < MAX_VISIBLE_VERSIONS) visibleVersions.push(v);
    });

    let versionButtonsHtml = visibleVersions.map(version => {
      const versionId = version.id;
      const versionName = version.name || 'Unknown Version';
      const baseModel = version.baseModel || 'N/A';
      return `
        <button class="civitai-button primary small civitai-search-download-button"
                data-model-id="${modelId}"
                data-version-id="${versionId || ''}"
                data-model-type="${modelTypeApi || ''}"
                ${!versionId ? 'disabled title="Version ID missing, cannot pre-fill"' : 'title="Pre-fill Download Tab"'} >
          <span class="base-model-badge">${baseModel}</span> ${versionName} <i class="fas fa-download"></i>
        </button>
      `;
    }).join('');

    const hasMoreVersions = allVersions.length > visibleVersions.length;
    const totalVersionCount = allVersions.length;
    const moreButtonHtml = hasMoreVersions ? `
      <button class="civitai-button secondary small show-all-versions-button"
              data-model-id="${modelId}"
              data-total-versions="${totalVersionCount}"
              title="Show all ${totalVersionCount} versions">
        All versions (${totalVersionCount}) <i class="fas fa-chevron-down"></i>
      </button>
    ` : '';

    let allVersionsHtml = '';
    if (hasMoreVersions) {
      const hiddenVersions = allVersions.filter(v => !visibleVersions.some(vis => vis.id === v.id));
      allVersionsHtml = `
        <div class="all-versions-container" id="all-versions-${modelId}" style="display: none;">
          ${hiddenVersions.map(version => {
            const versionId = version.id;
            const versionName = version.name || 'Unknown Version';
            const baseModel = version.baseModel || 'N/A';
            return `
              <button class="civitai-button primary small civitai-search-download-button"
                      data-model-id="${modelId}"
                      data-version-id="${versionId || ''}"
                      data-model-type="${modelTypeApi || ''}"
                      ${!versionId ? 'disabled title="Version ID missing, cannot pre-fill"' : 'title="Pre-fill Download Tab"'} >
                <span class="base-model-badge">${baseModel}</span> ${versionName} <i class="fas fa-download"></i>
              </button>
            `;
          }).join('')}
        </div>
      `;
    }

    let thumbnailHtml = '';
    const videoTitle = `Video preview for ${modelName}`;
    const imageAlt = `${modelName} thumbnail`;
    if (thumbnailUrl && typeof thumbnailUrl === 'string' && thumbnailType === 'video') {
      thumbnailHtml = `
        <video class="civitai-search-thumbnail" src="${thumbnailUrl}" autoplay loop muted playsinline
               title="${videoTitle}"
               onerror="console.error('Failed to load video preview:', this.src)">
          Your browser does not support the video tag.
        </video>
      `;
    } else {
      const effective = thumbnailUrl || placeholder;
      thumbnailHtml = `
        <img src="${effective}" alt="${imageAlt}" class="civitai-search-thumbnail" loading="lazy" onerror="${onErrorScript}">
      `;
    }

    const overlayHtml = shouldBlur ? `<div class="civitai-nsfw-overlay" title="R-rated: click to reveal">R</div>` : '';
    const containerClasses = `civitai-thumbnail-container${shouldBlur ? ' blurred' : ''}`;

    listItem.innerHTML = `
      <div class="${containerClasses}" data-nsfw-level="${nsfwLevel ?? ''}">
        ${thumbnailHtml}
        ${overlayHtml}
        <div class="civitai-type-badge" data-type="${modelTypeApi.toLowerCase()}">${modelTypeApi}</div>
      </div>
      <div class="civitai-search-info">
        <h4>${modelName}</h4>
        <div class="civitai-search-meta-info">
          <span title="Creator: ${creator}"><i class="fas fa-user"></i> ${creator}</span>
          <span title="Base Models: ${baseModelsDisplay}"><i class="fas fa-layer-group"></i> ${baseModelsDisplay}</span>
          <span title="Published: ${lastUpdatedFormatted}"><i class="fas fa-calendar-alt"></i> ${lastUpdatedFormatted}</span>
        </div>
        <div class="civitai-search-stats" title="Stats: Downloads / Rating (Count) / Likes">
          <span title="Downloads"><i class="fas fa-download"></i> ${stats.downloadCount?.toLocaleString() || 0}</span>
          <span title="Thumbs"><i class="fas fa-thumbs-up"></i> ${stats.thumbsUpCount?.toLocaleString() || 0}</span>
          <span title="Collected"><i class="fas fa-archive"></i> ${stats.collectedCount?.toLocaleString() || 0}</span>
          <span title="Buzz"><i class="fas fa-bolt"></i> ${stats.tippedAmountCount?.toLocaleString() || 0}</span>
        </div>
        ${tags.length > 0 ? `
        <div class="civitai-search-tags" title="${tags.join(', ')}">
          ${tags.slice(0, 5).map(tag => `<span class="civitai-search-tag">${tag}</span>`).join('')}
          ${tags.length > 5 ? `<span class="civitai-search-tag">...</span>` : ''}
        </div>
        ` : ''}
      </div>
      <div class="civitai-search-actions">
        <a href="https://civitai.com/models/${modelId}${primaryVersionId ? '?modelVersionId='+primaryVersionId : ''}" 
           target="_blank" rel="noopener noreferrer" class="civitai-button small" 
           title="Open on Civitai website">
          View <i class="fas fa-external-link-alt"></i>
        </a>
        <div class="version-buttons-container">
          ${versionButtonsHtml}
          ${moreButtonHtml}
        </div>
        ${allVersionsHtml}
      </div>
    `;

    fragment.appendChild(listItem);
  });

  ui.searchResultsContainer.innerHTML = '';
  ui.searchResultsContainer.appendChild(fragment);
}
