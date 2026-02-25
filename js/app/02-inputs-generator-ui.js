        function selectAlgorithm(evt, algoId) {
            config.selectedAlgorithm = algoId;
            config.selectedFiles = [];
            
            document.querySelectorAll('.algorithm-card').forEach(card => {
                card.classList.remove('selected');
            });
            if (evt && evt.currentTarget) {
                evt.currentTarget.classList.add('selected');
            }
            
            updateRunButton();
            updateRunInfo();
            updateGeneratorFieldsForAlgorithm();
            
            if (config.owner && config.repo) {
                loadDataFiles();
            }
        }

        function getInputMode() {
            return config.inputMode || 'premade';
        }

        function onInputModeChange() {
            const modeEl = document.getElementById('input-mode');
            const mode = modeEl ? modeEl.value : 'premade';
            config.inputMode = mode;
            if (mode === 'generate') {
                config.selectedFiles = [];
            }
            updateInputModeVisibility();
            updateGeneratorFieldsForAlgorithm();
            updateRunInfo();
            updateRunButton();
        }

        function onRunModeChange() {
            updateInputModeVisibility();
            updateRunButton();
        }

        function updateInputModeVisibility() {
            const mode = getInputMode();
            const form = document.getElementById('generator-form');
            const fileList = document.getElementById('files-content');
            const warning = document.getElementById('generator-warning');
            const note = document.getElementById('generator-disabled-note');
            const runMode = getSelectedRunMode();

            if (form) form.hidden = mode !== 'generate';
            if (fileList) fileList.hidden = mode === 'generate';
            if (warning && mode !== 'generate') warning.hidden = true;
            if (note) note.hidden = !(mode === 'generate' && runMode === 'local');
            updateGeneratorEstimate();
        }

        function onGeneratorInputChange() {
            const nEl = document.getElementById('gen-n');
            const kEl = document.getElementById('gen-k');
            const dEl = document.getElementById('gen-density');
            const seedEl = document.getElementById('gen-seed');
            config.generator.n = nEl ? nEl.value : '';
            config.generator.k = kEl ? kEl.value : '';
            config.generator.density = dEl ? dEl.value : config.generator.density;
            config.generator.seed = seedEl ? seedEl.value : '';
            updateGeneratorEstimate();
            updateRunInfo();
            updateRunButton();
        }

        function updateGeneratorFieldsForAlgorithm() {
            const kGroup = document.getElementById('gen-k-group');
            const warning = document.getElementById('generator-warning');
            if (!kGroup) return;
            const needsK = isGraphPairAlgorithm(config.selectedAlgorithm);
            kGroup.hidden = !needsK;
            if (!needsK && warning) {
                warning.hidden = true;
            }
            updateGeneratorEstimate();
        }
        
        async function connect() {
            const owner = document.getElementById('owner').value.trim();
            const repo = document.getElementById('repo').value.trim();
            const token = document.getElementById('token').value.trim();
            
            if (!owner || !repo) {
                showStatus('Please enter both username/org and repository name', 'error');
                return;
            }
            
            if (!token) {
                showStatus('Personal Access Token is required to run algorithms', 'error');
                return;
            }
            
            config.owner = owner;
            config.repo = repo;
            config.token = token;
            
            try {
                const repoInfo = await apiRequest('');
                if (repoInfo && repoInfo.default_branch) {
                    config.ref = repoInfo.default_branch;
                }
            } catch (e) {
                // default branch fallback already set to 'main'
            }

            showStatus('Connected successfully!', 'success');
            await loadDataFiles();
        }
        
        async function loadDataFiles() {
            const container = document.getElementById('files-content');
            container.innerHTML = '<p class="loading">Loading data files...</p>';
            
            try {
                const ref = config.ref ? `?ref=${encodeURIComponent(config.ref)}` : '';
                let contents;
                try {
                    contents = await apiRequest(`/contents/data${ref}`);
                } catch (error) {
                    const msg = (error && error.message) ? error.message : '';
                    if (config.token && (msg.includes('404') || msg.includes('401') || msg.includes('403'))) {
                        try {
                            contents = await apiRequest(`/contents/data${ref}`, 'GET', null, { useAuth: false });
                        } catch (fallbackError) {
                            throw fallbackError;
                        }
                    } else {
                        throw error;
                    }
                }
                
                const files = Array.isArray(contents) ? contents : [contents];

                dataFileMeta = {};
                files.forEach(item => {
                    if (item && item.type === 'file' && item.path) {
                        dataFileMeta[item.path] = {
                            size: (typeof item.size === 'number') ? item.size : null,
                            sha: item.sha || '',
                            downloadUrl: item.download_url || ''
                        };
                    }
                });
                
                const list = document.createElement('ul');
                list.className = 'file-list';
                const selectedPaths = new Set(
                    (Array.isArray(config.selectedFiles) ? config.selectedFiles : [])
                        .map(file => (file && file.path) ? String(file.path) : '')
                );

                files.forEach(item => {
                    if (!item || item.type !== 'file') return;

                    const filePath = String(item.path || '');
                    const fileName = String(item.name || filePath.split('/').pop() || '');
                    const row = document.createElement('li');
                    row.className = 'file-item';
                    row.setAttribute('role', 'button');
                    row.tabIndex = 0;
                    if (selectedPaths.has(filePath)) {
                        row.classList.add('selected');
                    }

                    row.addEventListener('click', (event) => {
                        toggleFileSelection(event, filePath, fileName);
                    });
                    row.addEventListener('keydown', (event) => {
                        if (event.key !== 'Enter' && event.key !== ' ') return;
                        event.preventDefault();
                        row.click();
                    });

                    const iconSpan = document.createElement('span');
                    iconSpan.className = 'file-icon';
                    iconSpan.textContent = '📄';

                    const nameSpan = document.createElement('span');
                    nameSpan.textContent = fileName;

                    row.appendChild(iconSpan);
                    row.appendChild(nameSpan);
                    list.appendChild(row);
                });

                container.replaceChildren(list);
                
            } catch (error) {
                    reportDebugError('loadDataFiles', error, {
                        owner: config.owner,
                        repo: config.repo,
                        ref: config.ref
                    });
                    let hint = 'Verify the repo has a top-level "data" folder on the selected branch.';
                    let extra = '';
                    const msg = (error && error.message) ? error.message : '';
                    if (msg.includes('401')) {
                        extra = ' (check that your PAT is valid and has repo/workflow scopes; if the repo is public, retry without auth)';
                    }
                    container.innerHTML = `<div class="error">Error loading files: ${escapeHtml(error.message)}${escapeHtml(extra)}<br>${hint}</div>`;
            }
        }
        
        function isGraphPairAlgorithm(algoId) {
            return algoId === 'glasgow' || algoId === 'vf3' || algoId === 'subgraph';
        }

        function parseLeadingIntLine(text) {
            const lines = String(text || '').split(/\r?\n/);
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || trimmed.startsWith('#')) continue;
                const match = trimmed.match(/^(-?\d+)/);
                if (!match) continue;
                const value = parseInt(match[1], 10);
                if (Number.isFinite(value)) return value;
            }
            return null;
        }

        async function getGraphMetrics(path) {
            const p = String(path || '');
            const ref = String(config.ref || '').trim();
            const cacheKey = `${ref}::${p}`;
            if (graphMetricCache.has(cacheKey)) return graphMetricCache.get(cacheKey);

            const meta = dataFileMeta && dataFileMeta[p] ? dataFileMeta[p] : null;
            const bytes = meta && Number.isFinite(Number(meta.size)) ? Number(meta.size) : null;

            const ext = p.toLowerCase().split('.').pop();
            if (ext !== 'grf' && ext !== 'lad' && ext !== 'vf') {
                const result = { nodes: null, bytes };
                graphMetricCache.set(cacheKey, result);
                return result;
            }

            // Avoid pulling content for very large files; fall back to bytes.
            if (bytes && bytes > 1500000) {
                const result = { nodes: null, bytes };
                graphMetricCache.set(cacheKey, result);
                return result;
            }

            try {
                const refParam = ref ? `?ref=${encodeURIComponent(ref)}` : '';
                const file = await apiRequest(`/contents/${encodePathPreservingSlashes(p)}${refParam}`);
                if (file && typeof file.content === 'string' && file.encoding === 'base64') {
                    const decoded = atob(file.content.replace(/\s/g, ''));
                    const nodes = parseLeadingIntLine(decoded);
                    const fallbackBytes = Number.isFinite(Number(file.size)) ? Number(file.size) : null;
                    const resolvedBytes = (bytes !== null && bytes !== undefined) ? bytes : fallbackBytes;
                    const result = { nodes, bytes: resolvedBytes };
                    graphMetricCache.set(cacheKey, result);
                    return result;
                }
            } catch (_) {}

            const result = { nodes: null, bytes };
            graphMetricCache.set(cacheKey, result);
            return result;
        }

        async function normalizeGraphInputOrder(algoId) {
            const id = String(algoId || '');
            if (!isGraphPairAlgorithm(id)) return;
            if (!Array.isArray(config.selectedFiles) || config.selectedFiles.length < 2) return;

            const first = config.selectedFiles[0];
            const second = config.selectedFiles[1];
            if (!first || !second || !first.path || !second.path) return;

            // Guard against races if the user changes selection while we fetch metadata.
            const snapshot = config.selectedFiles.map(f => (f && f.path) ? f.path : '').join(',');
            const [m0, m1] = await Promise.all([getGraphMetrics(first.path), getGraphMetrics(second.path)]);

            if (!isGraphPairAlgorithm(config.selectedAlgorithm)) return;
            if (!Array.isArray(config.selectedFiles) || config.selectedFiles.length < 2) return;
            const current = config.selectedFiles.map(f => (f && f.path) ? f.path : '').join(',');
            if (current !== snapshot) return;

            const n0 = m0 && Number.isFinite(Number(m0.nodes)) ? Number(m0.nodes) : null;
            const n1 = m1 && Number.isFinite(Number(m1.nodes)) ? Number(m1.nodes) : null;
            const b0 = m0 && Number.isFinite(Number(m0.bytes)) ? Number(m0.bytes) : null;
            const b1 = m1 && Number.isFinite(Number(m1.bytes)) ? Number(m1.bytes) : null;

            const shouldSwap = (() => {
                if (n0 !== null && n1 !== null) {
                    if (n0 !== n1) return n0 > n1;
                    if (b0 !== null && b1 !== null && b0 !== b1) return b0 > b1;
                    return false;
                }
                if (b0 !== null && b1 !== null && b0 !== b1) return b0 > b1;
                return false;
            })();

            if (shouldSwap) {
                config.selectedFiles[0] = second;
                config.selectedFiles[1] = first;
            }
        }

        function toggleFileSelection(evt, path, name) {
            if (getInputMode() === 'generate') {
                return;
            }
            const algo = algorithmConfigs[config.selectedAlgorithm];
            if (!algo) {
                showStatus('Please select an algorithm first', 'error');
                return;
            }
            
            const index = config.selectedFiles.findIndex(f => f.path === path);
            
            if (index > -1) {
                config.selectedFiles.splice(index, 1);
                if (evt && evt.currentTarget) {
                    evt.currentTarget.classList.remove('selected');
                }
            } else {
                if (config.selectedFiles.length >= algo.requiredFiles) {
                    showStatus(`This algorithm requires exactly ${algo.requiredFiles} file(s)`, 'error');
                    return;
                }
                config.selectedFiles.push({ path, name });
                if (evt && evt.currentTarget) {
                    evt.currentTarget.classList.add('selected');
                }
            }
            
            updateRunButton();
            updateRunInfo();
            normalizeGraphInputOrder(config.selectedAlgorithm)
                .then(() => updateRunInfo())
                .catch(() => {});
        }
        
        function updateRunButton() {
            const btn = document.getElementById('run-btn');
            const algo = algorithmConfigs[config.selectedAlgorithm];
            if (!btn) return;

            const mode = getInputMode();
            const runMode = getSelectedRunMode();
            let enabled = false;

            if (!algo || !config.token) {
                enabled = false;
            } else if (mode === 'generate') {
                const validation = validateGeneratorInputs();
                const generatorAllowed = true;
                enabled = validation.valid && generatorAllowed;
            } else {
                enabled = config.selectedFiles.length === algo.requiredFiles;
            }

            btn.disabled = !enabled;
        }

        function validateGeneratorInputs() {
            const warning = document.getElementById('generator-warning');
            const seedWarning = document.getElementById('generator-seed-warning');
            const nEl = document.getElementById('gen-n');
            const kEl = document.getElementById('gen-k');
            const dEl = document.getElementById('gen-density');
            const seedEl = document.getElementById('gen-seed');
            if (nEl) config.generator.n = nEl.value;
            if (kEl) config.generator.k = kEl.value;
            if (dEl) config.generator.density = dEl.value;
            if (seedEl) config.generator.seed = seedEl.value;
            const nValue = parseInt(String(config.generator.n || '').trim(), 10);
            const kValue = parseInt(String(config.generator.k || '').trim(), 10);
            const densityValue = parseFloat(String(config.generator.density || '').trim());
            const seedRaw = String(config.generator.seed || '').trim();
            const needsK = isGraphPairAlgorithm(config.selectedAlgorithm);

            let valid = Number.isFinite(nValue) && nValue >= 2;
            let showKWarning = false;
            let showSeedWarning = false;

            if (needsK) {
                if (!Number.isFinite(kValue) || kValue < 1) {
                    valid = false;
                } else if (Number.isFinite(nValue) && kValue >= nValue) {
                    valid = false;
                    showKWarning = true;
                }
            }
            if (!Number.isFinite(densityValue) || densityValue <= 0 || densityValue > 1) {
                valid = false;
            }
            if (seedRaw && !/^-?\d+$/.test(seedRaw)) {
                valid = false;
                showSeedWarning = true;
            }

            if (warning) {
                warning.hidden = !showKWarning;
            }
            if (seedWarning) {
                seedWarning.hidden = !showSeedWarning;
            }

            return { valid, n: nValue, k: kValue, density: densityValue };
        }
        
        function updateRunInfo() {
            const infoDiv = document.getElementById('run-info');
            const algo = algorithmConfigs[config.selectedAlgorithm];
            
            if (!algo) {
                infoDiv.innerHTML = '<div class="info">Select an algorithm above to get started</div>';
                return;
            }
            
            let html = `<div class="info">
                <strong>Algorithm:</strong> ${algo.name}<br>
                <strong>Required files:</strong> ${algo.requiredFiles}
            `;
            
            if (algo.instructions && algo.instructions.length) {
                html += '<div class="instructions"><strong>File format tips:</strong><ul>';
                html += algo.instructions.map(item => `<li>${escapeHtml(item)}</li>`).join('');
                html += '</ul></div>';
            }

            const mode = getInputMode();
            if (mode === 'generate') {
                const n = String(config.generator.n || '').trim();
                const k = String(config.generator.k || '').trim();
                const density = String(config.generator.density || '').trim();
                let formatHint = '';
                if (config.selectedAlgorithm === 'dijkstra') formatHint = 'CSV (labeled)';
                if (config.selectedAlgorithm === 'glasgow') formatHint = '.lad';
                if (config.selectedAlgorithm === 'vf3') formatHint = '.grf';
                if (config.selectedAlgorithm === 'subgraph') formatHint = '.lad/.vf';
                html += `<div class="selected-files"><strong>Generated:</strong> N=${escapeHtml(n || '?')}`;
                if (isGraphPairAlgorithm(config.selectedAlgorithm)) {
                    html += `, k=${escapeHtml(k || '?')}`;
                }
                if (density) {
                    html += `, density=${escapeHtml(density)}`;
                }
                if (formatHint) {
                    html += `, format=${formatHint}`;
                }
                html += '</div>';
            } else if (config.selectedFiles.length > 0) {
                html += '<div class="selected-files"><strong>Selected:</strong> ';
                html += config.selectedFiles.map((f, i) => {
                    const label = algo.fileLabels ? algo.fileLabels[i] : `File ${i+1}`;
                    return `${escapeHtml(label)}: ${escapeHtml(f && f.name ? f.name : '')}`;
                }).join(', ');
                html += '</div>';
            }
            
            html += '</div>';
            infoDiv.innerHTML = html;
        }

        function estimateEdgeCount(n, density, directed) {
            const maxEdges = directed ? (n * (n - 1)) : (n * (n - 1)) / 2;
            const targetEdges = Math.round(density * maxEdges);
            return Math.max(n - 1, Math.min(maxEdges, targetEdges));
        }

        function estimateAvgDegree(n, m, directed) {
            if (n <= 0) return 0;
            return directed ? (m / n) : (2 * m / n);
        }

        function estimateHeuristicPerRunMs(algoId, nRaw, kRaw, densityRaw) {
            const n = parseInt(String(nRaw || '').trim(), 10);
            const k = parseInt(String(kRaw || '').trim(), 10);
            const density = parseFloat(String(densityRaw || '').trim());
            if (!Number.isFinite(n) || n <= 1) return '';
            if (!Number.isFinite(density) || density <= 0 || density > 1) return '';

            const isSubgraph = algoId === 'vf3' || algoId === 'glasgow' || algoId === 'subgraph';
            const directed = algoId === 'dijkstra';
            const mTarget = estimateEdgeCount(n, density, directed);
            const avgDegTarget = estimateAvgDegree(n, mTarget, directed);

            let ms = 0;
            if (algoId === 'dijkstra') {
                const ops = (n + mTarget) * Math.log2(n + 1);
                ms = ops * 0.000002;
            } else if (isSubgraph) {
                if (!Number.isFinite(k) || k < 1 || k >= n) return '';
                const mPattern = estimateEdgeCount(k, density, directed);
                const avgDegPattern = estimateAvgDegree(k, mPattern, directed);

                const labelBuckets = (algoId === 'vf3' || algoId === 'subgraph') ? 4 : 1;
                const candidateScale = Math.max(2, n / labelBuckets);
                const branchFactor = Math.pow(candidateScale, Math.min(k, 10) / 6);

                const hardness = 0.6 + 1.8 * (1 - Math.abs(2 * density - 1));
                const edgeFactor = 1 + Math.log2(1 + avgDegTarget) * 0.9;
                const patternFactor = 1 + avgDegPattern * 0.8;

                ms = 0.35 * hardness * edgeFactor * patternFactor * branchFactor;
            } else {
                return '';
            }

            if (!Number.isFinite(ms) || ms <= 0) return '';
            return ms;
        }

        function formatDurationMs(ms) {
            const value = Number(ms);
            if (!Number.isFinite(value) || value <= 0) return '';
            const totalSeconds = value / 1000;
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds - hours * 3600) / 60);
            const seconds = totalSeconds - hours * 3600 - minutes * 60;
            return `~${hours}h ${minutes}m ${seconds.toFixed(3)}s`;
        }

