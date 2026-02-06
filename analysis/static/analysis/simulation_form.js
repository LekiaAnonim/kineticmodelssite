document.addEventListener('DOMContentLoaded', function () {
    const simForm = document.getElementById('simulation-form');
    // Pre-selected IDs from fuel-map play button
    let preselectedDatasetIds = [];
    let preselectedModelId = '';
    try {
        preselectedDatasetIds = JSON.parse(simForm?.dataset.preselectedDatasets || '[]');
    } catch(e) {}
    preselectedModelId = simForm?.dataset.preselectedModel || '';

    // Model search
    const modelSearch = document.getElementById('model-search');
    const modelList = document.getElementById('model-list');
    const modelCount = document.getElementById('model-count');
    const modelApiUrl = modelList?.dataset.apiUrl;
    const modelCountsApiUrl = modelList?.dataset.countsUrl;
    let modelController = null;
    let modelCountsController = null;
    let modelTimer = null;

    function renderModels(models) {
        if (!modelList) return;
        modelList.innerHTML = '';

        if (!models.length) {
            const empty = document.createElement('div');
            empty.className = 'p-3 text-muted text-center';
            empty.textContent = 'No kinetic models available';
            modelList.appendChild(empty);
            if (modelCount) modelCount.textContent = '0';
            return;
        }

        // Sort pre-selected model to the top
        if (preselectedModelId) {
            models.sort(function (a, b) {
                const aSelected = String(a.id) === String(preselectedModelId) ? 0 : 1;
                const bSelected = String(b.id) === String(preselectedModelId) ? 0 : 1;
                return aSelected - bSelected;
            });
        }

        models.forEach(function (model) {
            const isPreselected = preselectedModelId && String(model.id) === String(preselectedModelId);
            const wrapper = document.createElement('div');
            wrapper.className = 'model-item d-flex align-items-center p-2 border-bottom'
                + (isPreselected ? ' bg-success-subtle' : '');
            wrapper.dataset.name = (model.model_name || '').toLowerCase();

            const input = document.createElement('input');
            input.className = 'form-check-input me-2';
            input.type = 'radio';
            input.name = 'kinetic_model';
            input.value = model.id;
            input.id = `model_${model.id}`;

            // Pre-select if matching
            if (preselectedModelId && String(model.id) === String(preselectedModelId)) {
                input.checked = true;
            }

            const label = document.createElement('label');
            label.className = 'flex-grow-1 mb-0';
            label.setAttribute('for', input.id);
            label.style.cursor = 'pointer';
            label.textContent = model.model_name;

            const meta = document.createElement('div');
            meta.className = 'text-muted small';
            meta.dataset.modelId = String(model.id);
            meta.textContent = 'Loading counts…';
            label.appendChild(document.createElement('br'));
            label.appendChild(meta);

            wrapper.appendChild(input);
            wrapper.appendChild(label);
            modelList.appendChild(wrapper);
        });

        if (modelCount) modelCount.textContent = String(models.length);
    }

    async function fetchModels(query) {
        if (!modelApiUrl) return;
        if (modelController) modelController.abort();
        modelController = new AbortController();

        const url = new URL(modelApiUrl, window.location.origin);
        if (query) url.searchParams.set('q', query);
        url.searchParams.set('limit', '200');

        console.debug('[analysis] model search', url.toString());
        const response = await fetch(url.toString(), { signal: modelController.signal });
        if (!response.ok) {
            console.warn('[analysis] model search failed', response.status);
            return;
        }
        const data = await response.json();
        const models = data.models || [];
        renderModels(models);
        fetchModelCounts(models);
    }

    async function fetchModelCounts(models) {
        if (!modelCountsApiUrl || !models.length) return;
        if (modelCountsController) modelCountsController.abort();
        modelCountsController = new AbortController();

        const ids = models.map(model => model.id).filter(Boolean).slice(0, 200);
        if (!ids.length) return;

        const url = new URL(modelCountsApiUrl, window.location.origin);
        url.searchParams.set('ids', ids.join(','));

        try {
            const response = await fetch(url.toString(), { signal: modelCountsController.signal });
            if (!response.ok) return;
            const payload = await response.json();
            const counts = payload.counts || {};

            ids.forEach(function (id) {
                const meta = modelList?.querySelector(`.model-item [data-model-id="${id}"]`);
                if (!meta) return;
                const entry = counts[String(id)];
                if (!entry) {
                    meta.textContent = 'Counts unavailable';
                    return;
                }
                meta.textContent = `${entry.species_count || 0} species, ${entry.reaction_count || 0} reactions`;
            });
        } catch (error) {
            if (error?.name === 'AbortError') return;
        }
    }

    if (modelSearch) {
        modelSearch.addEventListener('input', function () {
            const query = this.value.trim();
            clearTimeout(modelTimer);
            modelTimer = setTimeout(function () {
                fetchModels(query);
            }, 200);
        });
        fetchModels('');
    }

    // Dataset search + filters
    const datasetSearch = document.getElementById('dataset-search');
    const expTypeFilter = document.getElementById('exp-type-filter');
    const apparatusFilter = document.getElementById('apparatus-filter');
    const targetFilter = document.getElementById('target-filter');
    const datasetList = document.getElementById('dataset-list');
    const datasetCount = document.getElementById('dataset-count');
    const selectedCount = document.getElementById('selected-count');
    const datasetApiUrl = datasetList?.dataset.apiUrl;
    const datasetStatus = document.getElementById('dataset-status');
    let datasetController = null;
    let datasetTimer = null;

    function updateSelectedCount() {
        if (!selectedCount) return;
        const checked = datasetList?.querySelectorAll('.dataset-item input:checked').length || 0;
        selectedCount.textContent = checked;
    }

    function renderDatasets(datasets) {
        if (!datasetList) return;
        datasetList.innerHTML = '';

        if (!datasets.length) {
            const empty = document.createElement('div');
            empty.className = 'p-3 text-muted text-center';
            empty.textContent = 'No datasets available';
            datasetList.appendChild(empty);
            if (datasetCount) datasetCount.textContent = '0';
            updateSelectedCount();
            return;
        }

        // Sort pre-selected datasets to the top
        if (preselectedDatasetIds.length > 0) {
            datasets.sort(function (a, b) {
                const aSelected = preselectedDatasetIds.includes(a.id) ? 0 : 1;
                const bSelected = preselectedDatasetIds.includes(b.id) ? 0 : 1;
                return aSelected - bSelected;
            });
        }

        datasets.forEach(function (dataset) {
            const isPreselected = preselectedDatasetIds.length > 0 &&
                preselectedDatasetIds.includes(dataset.id);
            const wrapper = document.createElement('div');
            wrapper.className = 'dataset-item d-flex align-items-start p-2 border-bottom'
                + (isPreselected ? ' bg-success-subtle' : '');
            wrapper.dataset.fuel = (dataset.fuel_species || []).join(', ').toLowerCase();
            wrapper.dataset.type = (dataset.experiment_type || '').toLowerCase();
            wrapper.dataset.apparatus = (dataset.apparatus_kind || '').toLowerCase();
            wrapper.dataset.path = (dataset.chemked_file_path || '').toLowerCase();
            wrapper.dataset.name = (dataset.short_name || '').toLowerCase();
            wrapper.dataset.target = (dataset.ignition_target || '').toLowerCase();

            const input = document.createElement('input');
            input.className = 'form-check-input me-2 mt-1';
            input.type = 'checkbox';
            input.name = 'datasets';
            input.value = dataset.id;
            input.id = `dataset_${dataset.id}`;
            input.style.minWidth = '16px';
            input.style.minHeight = '16px';

            // Pre-select if in the fuel-map batch
            if (preselectedDatasetIds.length > 0 &&
                preselectedDatasetIds.includes(dataset.id)) {
                input.checked = true;
            }

            const label = document.createElement('label');
            label.className = 'flex-grow-1';
            label.setAttribute('for', input.id);
            label.style.cursor = 'pointer';

            const title = document.createElement('strong');
            title.textContent = dataset.short_name || 'Dataset';
            label.appendChild(title);

            const countBadge = document.createElement('span');
            countBadge.className = 'badge bg-secondary-subtle text-secondary ms-1';
            countBadge.textContent = `${dataset.datapoints_count || 0} pts`;
            label.appendChild(countBadge);

            const typeBadge = document.createElement('span');
            if ((dataset.experiment_type || '').toLowerCase() === 'ignition delay') {
                typeBadge.className = 'badge bg-danger-subtle text-danger ms-1';
                typeBadge.textContent = 'IDT';
            } else if ((dataset.experiment_type || '').toLowerCase() === 'laminar flame speed') {
                typeBadge.className = 'badge bg-warning-subtle text-warning ms-1';
                typeBadge.textContent = 'LFS';
            } else {
                typeBadge.className = 'badge bg-info-subtle text-info ms-1';
                typeBadge.textContent = dataset.experiment_type || '';
            }
            label.appendChild(typeBadge);

            if (dataset.ignition_target) {
                const targetBadge = document.createElement('span');
                targetBadge.className = 'badge bg-primary-subtle text-primary ms-1';
                targetBadge.textContent = dataset.ignition_target;
                label.appendChild(targetBadge);
            }

            label.appendChild(document.createElement('br'));
            const meta = document.createElement('small');
            meta.className = 'text-muted';
            const fuels = (dataset.fuel_species || []).join(', ');
            meta.textContent = fuels || 'Unknown fuel';
            if (dataset.apparatus_kind) {
                meta.textContent += ` • ${dataset.apparatus_kind}`;
            }
            label.appendChild(meta);

            wrapper.appendChild(input);
            wrapper.appendChild(label);
            datasetList.appendChild(wrapper);

            input.addEventListener('change', updateSelectedCount);
        });

        // Insert a visual separator after the pre-selected block
        if (preselectedDatasetIds.length > 0) {
            const preselectedItems = datasetList.querySelectorAll('.dataset-item.bg-success-subtle');
            const lastPreselected = preselectedItems[preselectedItems.length - 1];
            if (lastPreselected && lastPreselected.nextSibling) {
                const sep = document.createElement('div');
                sep.className = 'text-center text-muted small py-1 bg-light border-bottom border-top';
                sep.innerHTML = `<i class="bi bi-dash-lg"></i> ${preselectedDatasetIds.length} pre-selected above &mdash; other datasets below <i class="bi bi-dash-lg"></i>`;
                lastPreselected.after(sep);
            }
        }

        if (datasetCount) datasetCount.textContent = String(datasets.length);
        updateSelectedCount();
    }

    async function fetchDatasets() {
        if (!datasetApiUrl) return;
        if (datasetController) datasetController.abort();
        datasetController = new AbortController();

        const url = new URL(datasetApiUrl, window.location.origin);
        const query = (datasetSearch?.value || '').trim();
        const expType = (expTypeFilter?.value || '').trim();
        const apparatus = (apparatusFilter?.value || '').trim();
        const target = (targetFilter?.value || '').trim();

        if (query) url.searchParams.set('q', query);
        if (expType) url.searchParams.set('experiment_type', expType);
        if (apparatus) url.searchParams.set('apparatus_kind', apparatus);
        if (target) url.searchParams.set('target', target);
        url.searchParams.set('limit', '200');

        if (datasetStatus) {
            datasetStatus.style.display = 'block';
            datasetStatus.textContent = 'Searching datasets...';
        }

        console.debug('[analysis] dataset search', url.toString());
        const response = await fetch(url.toString(), { signal: datasetController.signal });
        if (!response.ok) {
            console.warn('[analysis] dataset search failed', response.status);
            if (datasetStatus) {
                datasetStatus.textContent = 'Search failed. Check console for details.';
            }
            return;
        }
        const data = await response.json();
        renderDatasets(data.datasets || []);
        if (datasetStatus) {
            datasetStatus.textContent = `Showing ${data.datasets?.length || 0} result(s).`;
        }
    }

    function queueDatasetFetch() {
        clearTimeout(datasetTimer);
        datasetTimer = setTimeout(fetchDatasets, 200);
    }

    datasetSearch?.addEventListener('input', queueDatasetFetch);
    expTypeFilter?.addEventListener('change', queueDatasetFetch);
    apparatusFilter?.addEventListener('change', queueDatasetFetch);
    targetFilter?.addEventListener('change', queueDatasetFetch);

    document.getElementById('select-all')?.addEventListener('click', function () {
        datasetList?.querySelectorAll('.dataset-item input').forEach(function (checkbox) {
            checkbox.checked = true;
        });
        updateSelectedCount();
    });

    document.getElementById('clear-all')?.addEventListener('click', function () {
        datasetList?.querySelectorAll('.dataset-item input').forEach(function (checkbox) {
            checkbox.checked = false;
        });
        updateSelectedCount();
    });

    fetchDatasets();
});
