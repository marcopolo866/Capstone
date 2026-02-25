        async function runAlgorithm() {
            const outputDiv = document.getElementById('output');
            const statusBadge = document.getElementById('status-badge');
            const runBtn = document.getElementById('run-btn');
            const abortBtn = document.getElementById('abort-btn');
            runBtn.disabled = true;
            if (abortBtn) abortBtn.disabled = true;

            if (activeRun && !activeRun.aborted) {
                showStatus('A run is already in progress. Abort it before starting a new one.', 'error');
                runBtn.disabled = false;
                return;
            }

            clearCharts();

            const nowMs = () => (window.performance && typeof window.performance.now === 'function')
                ? window.performance.now()
                : Date.now();
            const formatDurationMs = (ms) => {
                if (!Number.isFinite(ms)) return '';
                const totalSeconds = ms / 1000;
                const minutes = Math.floor(totalSeconds / 60);
                const seconds = totalSeconds - minutes * 60;
                const secondsStr = seconds.toFixed(1).padStart(4, '0');
                return `${minutes}m ${secondsStr}s`;
            };
            const endToEndStartMs = nowMs();

            const fail = (message) => {
                const elapsedMs = nowMs() - endToEndStartMs;
                progressClear();
                outputDiv.textContent = `Failure: ${message}\n\nTotal end-to-end time: ${formatDurationMs(elapsedMs)}`;
                statusBadge.innerHTML = '<span class="status-badge status-error">Failed</span>';
                runBtn.disabled = false;
            };

            if (!config.selectedAlgorithm) {
                fail('No algorithm selected.');
                return;
            }

            const algo = algorithmConfigs[config.selectedAlgorithm];
            if (!algo) {
                fail('Unknown algorithm selected.');
                return;
            }

            if (!config.token) {
                fail('Personal Access Token is required to run workflows.');
                return;
            }

            const runMode = getSelectedRunMode();
            const inputMode = getInputMode();

                if (inputMode === 'generate') {
                    if (runMode === 'local') {
                        fail('Generator mode is only available for GitHub Actions runs.');
                        return;
                    }
                    const validation = validateGeneratorInputs();
                    if (!validation.valid) {
                        fail('Generator inputs are invalid. Ensure N >= 2, density is 0-1, and k < N.');
                        return;
                    }
                } else if (config.selectedFiles.length !== algo.requiredFiles) {
                fail(`Selected ${config.selectedFiles.length} file(s); expected ${algo.requiredFiles}.`);
                return;
            }

            try {
                if (inputMode !== 'generate') {
                    await normalizeGraphInputOrder(config.selectedAlgorithm);
                }
            } catch (_) {}
            updateRunInfo();

            const inputLines = inputMode === 'generate'
                ? [
                    `Generated: N=${config.generator.n || '?'}` +
                    (isGraphPairAlgorithm(config.selectedAlgorithm) ? `, k=${config.generator.k || '?'}` : '') +
                    `, density=${config.generator.density || '?'}`
                ]
                : config.selectedFiles.map((file, index) => {
                    const label = algo.fileLabels ? algo.fileLabels[index] : `File ${index + 1}`;
                    return `${label}: ${file.path}`;
                });

            const summaryLines = [
                `Algorithm: ${algo.name}`,
                'Inputs:',
                ...inputLines,
                '',
                'Result:',
                runMode === 'local' ? 'Starting local run...' : 'Triggering workflow...'
            ];
            outputDiv.textContent = summaryLines.join('\n');
            statusBadge.innerHTML = '<span class="status-badge status-running">Running...</span>';

            const requestId = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
            const runCtx = {
                requestId,
                mode: runMode,
                branchRef: '',
                runSha: '',
                aborted: false,
                abortController: new AbortController()
            };
            activeRun = runCtx;
            if (abortBtn) abortBtn.disabled = false;

            const iterationsEl = document.getElementById('iterations');
            const warmupEl = document.getElementById('warmup');
            const iterationsRaw = iterationsEl ? String(iterationsEl.value || '').trim() : '';
            const warmupRaw = warmupEl ? String(warmupEl.value || '').trim() : '';
            let iterations = 1;
            if (iterationsRaw) {
                const parsed = parseInt(iterationsRaw, 10);
                if (Number.isFinite(parsed) && parsed >= 1) iterations = parsed;
            }

            let warmup = 0;
            if (warmupRaw) {
                const parsed = parseInt(warmupRaw, 10);
                if (Number.isFinite(parsed) && parsed >= 0) warmup = parsed;
            }
            if (warmup > 50) warmup = 50;

            const branchRef = config.ref || 'main';
            runCtx.branchRef = branchRef;
            runTimerStart(runCtx);

            let dispatched = false;
            try {
                if (runMode === 'local') {
                    const localResult = await runAlgorithmLocally(runCtx, config.selectedAlgorithm, iterations, warmup);
                    if (runCtx.aborted || (localResult && localResult.status === 'aborted')) {
                        if (activeRun === runCtx) {
                            outputDiv.textContent = 'Run Aborted';
                            statusBadge.innerHTML = '<span class="status-badge status-aborted">Aborted</span>';
                            progressClear();
                        }
                        return;
                    }
                    if (!localResult || localResult.status !== 'success') {
                        throw new Error((localResult && localResult.error) ? localResult.error : 'Local run failed');
                    }

                    const finalLines = [
                        `Algorithm: ${algo.name} (Local)`,
                        'Inputs:',
                        ...inputLines,
                        '',
                        'Result:',
                        localResult.output || '(No output)'
                    ];
                    const elapsedMs = nowMs() - endToEndStartMs;
                    finalLines.push('', `Total end-to-end time: ${formatDurationMs(elapsedMs)}`);
                    outputDiv.textContent = finalLines.join('\n');
                    statusBadge.innerHTML = '<span class="status-badge status-ready">Success</span>';
                    clearCharts();
                    return;
                }

                progressReset(config.selectedAlgorithm, iterations, requestId);

                let runSha = '';
                try {
                    runSha = await getBranchHeadSha(branchRef);
                    if (runSha) progressState.runSha = runSha;
                    runCtx.runSha = runSha;
                } catch (_) {}

                const workflowData = {
                    ref: branchRef,
                    inputs: {
                        algorithm: config.selectedAlgorithm,
                        iterations: String(iterations),
                        warmup: String(warmup),
                        input_files: inputMode === 'generate' ? '' : config.selectedFiles.map(f => f.path).join(','),
                        input_mode: inputMode,
                        n: String(config.generator.n || ''),
                        k: String(config.generator.k || ''),
                        density: String(config.generator.density || ''),
                        seed: String(config.generator.seed || ''),
                        request_id: requestId
                    }
                };

                await ensureWorkflowDispatch(branchRef);
                await dispatchWorkflow(workflowData);
                dispatched = true;
                const applyResultToUi = (result, finalize) => {
                    const finalLines = [
                        `Algorithm: ${algo.name}`,
                        'Inputs:',
                        ...inputLines,
                        '',
                        'Result:',
                        result.output || '(No output)'
                    ];
                    const seedUsed = result && result.inputs && result.inputs.seed ? String(result.inputs.seed) : '';
                    const elapsedMs = nowMs() - endToEndStartMs;
                    if (inputMode === 'generate' && seedUsed) {
                        finalLines.push('', `Seed used: ${seedUsed}`);
                        finalLines.push(`Total end-to-end time: ${formatDurationMs(elapsedMs)}`);
                    } else {
                        finalLines.push('', `Total end-to-end time: ${formatDurationMs(elapsedMs)}`);
                    }
                    outputDiv.textContent = finalLines.join('\n');
                    statusBadge.innerHTML = '<span class="status-badge status-ready">Success</span>';
                    if (finalize && progressState.total > 0) {
                        progressSetDeterminate('Completed', progressState.total, progressState.total);
                    }
                    renderCharts(result);
                    renderVisualization(result);
                };

                const result = await waitForResult(requestId, branchRef, runSha, runCtx);
                if (runCtx.aborted || (result && result.status === 'aborted')) {
                    if (activeRun === runCtx) {
                        outputDiv.textContent = 'Run Aborted';
                        statusBadge.innerHTML = '<span class="status-badge status-aborted">Aborted</span>';
                        progressClear();
                    }
                    return;
                }
                if (result.status !== 'success') {
                    throw new Error(result.error || 'Workflow reported failure');
                }

                if (result.algorithm === 'subgraph' && result.subgraph_phase === 'vf3') {
                    applyResultToUi(result, false);
                    const followUp = await waitForResult(requestId, branchRef, runSha, runCtx, {
                        skipSubgraphPhases: ['vf3']
                    });
                    if (runCtx.aborted || (followUp && followUp.status === 'aborted')) {
                        if (activeRun === runCtx) {
                            outputDiv.textContent = 'Run Aborted';
                            statusBadge.innerHTML = '<span class="status-badge status-aborted">Aborted</span>';
                            progressClear();
                        }
                        return;
                    }
                    if (followUp.status !== 'success') {
                        throw new Error(followUp.error || 'Workflow reported failure');
                    }
                    applyResultToUi(followUp, true);
                } else {
                    applyResultToUi(result, true);
                }
            } catch (error) {
                if (runCtx && runCtx.aborted) {
                    return;
                }
                const message = error && error.message ? error.message : String(error);
                const elapsedMs = nowMs() - endToEndStartMs;
                outputDiv.textContent = `Failure: ${message}\n\nTotal end-to-end time: ${formatDurationMs(elapsedMs)}`;
                reportDebugError('runAlgorithm', error, {
                    algorithm: config.selectedAlgorithm,
                    files: config.selectedFiles.map(f => f.path).join(','),
                    ref: branchRef
                });
                statusBadge.innerHTML = '<span class="status-badge status-error">Failed</span>';
                clearCharts();

                if (!dispatched) {
                    progressClear();
                } else {
                    const phaseText = message.length > 120 ? message.slice(0, 117) + '...' : message;
                    progressSetDeterminate(phaseText, progressState.completed, progressState.total);
                }
            } finally {
                if (activeRun === runCtx) {
                    runTimerStop(runCtx);
                    activeRun = null;
                    if (abortBtn) abortBtn.disabled = true;
                    updateRunButton();
                }
            }
        }

        let workflowDispatchEndpointCache = null;
        let runAlgorithmWorkflowIdCache = null;
        async function getWorkflowDispatchEndpoint() {
            if (workflowDispatchEndpointCache) return workflowDispatchEndpointCache;
            // Prefer workflow ID to avoid path mismatches; fall back to path if needed.
            try {
                const data = await apiRequest('/actions/workflows');
                if (data && Array.isArray(data.workflows)) {
                    const match = data.workflows.find(wf =>
                        wf.path === '.github/workflows/run-algorithm.yml' ||
                        (wf.name && wf.name.toLowerCase().includes('run algorithm'))
                    );
                    if (match && match.id) {
                        workflowDispatchEndpointCache = `/actions/workflows/${match.id}/dispatches`;
                        return workflowDispatchEndpointCache;
                    }
                }
            } catch (error) {
                // Ignore and fall back
            }
            workflowDispatchEndpointCache = '/actions/workflows/run-algorithm.yml/dispatches';
            return workflowDispatchEndpointCache;
        }

        async function getRunAlgorithmWorkflowId() {
            if (runAlgorithmWorkflowIdCache) return runAlgorithmWorkflowIdCache;
            try {
                const data = await apiRequest('/actions/workflows');
                if (data && Array.isArray(data.workflows)) {
                    const match = data.workflows.find(wf =>
                        wf.path === '.github/workflows/run-algorithm.yml' ||
                        (wf.name && wf.name.toLowerCase().includes('run algorithm'))
                    );
                    if (match && match.id) {
                        runAlgorithmWorkflowIdCache = String(match.id);
                        return runAlgorithmWorkflowIdCache;
                    }
                }
            } catch (_) {}
            return '';
        }

        async function dispatchWorkflow(workflowData) {
            const dispatchEndpoint = await getWorkflowDispatchEndpoint();
            try {
                await apiRequest(dispatchEndpoint, 'POST', workflowData);
            } catch (error) {
                const msg = (error && error.message) ? error.message : '';
                const isMissingTrigger = msg.includes("Workflow does not have 'workflow_dispatch' trigger") || msg.includes('422');
                if (!isMissingTrigger) {
                    throw error;
                }
                // Fallback to repository_dispatch event
                const repoPayload = {
                    event_type: 'run-algorithm',
                    client_payload: {
                        algorithm: workflowData.inputs.algorithm,
                        iterations: workflowData.inputs.iterations,
                        warmup: workflowData.inputs.warmup,
                        input_files: workflowData.inputs.input_files,
                        input_mode: workflowData.inputs.input_mode,
                        n: workflowData.inputs.n,
                        k: workflowData.inputs.k,
                        density: workflowData.inputs.density,
                        seed: workflowData.inputs.seed,
                        request_id: workflowData.inputs.request_id || ''
                    }
                };
                await apiRequest('/dispatches', 'POST', repoPayload);
            }
        }

        async function listWorkflowRuns(workflowId, branchRef, perPage = 30) {
            const id = String(workflowId || '').trim();
            if (!id) return [];

            const pageSize = Math.max(1, Math.min(100, Number(perPage) || 30));
            const params = [`per_page=${pageSize}`];
            const branch = String(branchRef || '').trim();
            if (branch) params.push(`branch=${encodeURIComponent(branch)}`);

            const endpoint = `/actions/workflows/${id}/runs?${params.join('&')}`;
            const data = await apiRequest(endpoint);
            return (data && Array.isArray(data.workflow_runs)) ? data.workflow_runs : [];
        }

        async function resolveWorkflowRunId(requestId, branchRef, runSha) {
            const request = String(requestId || '').trim();
            if (!request) return '';

            if (progressState.workflowRunId && /^[0-9]+$/.test(progressState.workflowRunId)) {
                return progressState.workflowRunId;
            }

            let sha = String(runSha || progressState.runSha || '').trim();
            if (!sha) {
                try {
                    sha = await getBranchHeadSha(branchRef || config.ref || 'main');
                    if (sha) progressState.runSha = sha;
                } catch (_) {}
            }

            if (sha) {
                try {
                    await tryUpdateProgressFromChecks(request, sha);
                } catch (_) {}
            }

            if (progressState.workflowRunId && /^[0-9]+$/.test(progressState.workflowRunId)) {
                return progressState.workflowRunId;
            }

            const workflowId = await getRunAlgorithmWorkflowId();
            if (!workflowId) return '';

            let runs = [];
            try {
                runs = await listWorkflowRuns(workflowId, branchRef || config.ref || 'main');
            } catch (_) {
                runs = [];
            }

            const byTitle = runs.find(r =>
                r &&
                typeof r.display_title === 'string' &&
                r.display_title.includes(request) &&
                r.id
            );
            if (byTitle && byTitle.id) {
                progressState.workflowRunId = String(byTitle.id);
                return progressState.workflowRunId;
            }

            const bySha = sha
                ? runs.find(r => r && r.head_sha === sha && r.id && r.status !== 'completed')
                : null;
            if (bySha && bySha.id) {
                progressState.workflowRunId = String(bySha.id);
                return progressState.workflowRunId;
            }

            return '';
        }

        async function cancelWorkflowRun(runId) {
            const id = String(runId || '').trim();
            if (!id || !/^[0-9]+$/.test(id)) {
                throw new Error('Missing workflow run id');
            }
            await apiRequest(`/actions/runs/${id}/cancel`, 'POST');
        }

        async function getWorkflowRunState(runId) {
            const id = String(runId || '').trim();
            if (!id || !/^[0-9]+$/.test(id)) return null;
            try {
                const data = await apiRequest(`/actions/runs/${id}`);
                if (!data || typeof data !== 'object') return null;
                return {
                    id,
                    status: typeof data.status === 'string' ? data.status.toLowerCase() : '',
                    conclusion: typeof data.conclusion === 'string' ? data.conclusion.toLowerCase() : '',
                    htmlUrl: typeof data.html_url === 'string' ? data.html_url : ''
                };
            } catch (error) {
                const msg = error && error.message ? error.message : '';
                if (msg.includes('401') || msg.includes('403')) {
                    return null;
                }
                throw error;
            }
        }

        async function abortRun() {
            const run = activeRun;
            const outputDiv = document.getElementById('output');
            const statusBadge = document.getElementById('status-badge');
            const runBtn = document.getElementById('run-btn');
            const abortBtn = document.getElementById('abort-btn');

            if (!run || !run.requestId) {
                showStatus('No run is currently active', 'error');
                return;
            }

            if (run.aborted) return;
            run.aborted = true;

            if (abortBtn) abortBtn.disabled = true;
            if (outputDiv) outputDiv.textContent = 'Run Aborted';
            if (statusBadge) statusBadge.innerHTML = '<span class="status-badge status-aborted">Aborted</span>';
            runTimerStop(run);

            try {
                if (run.abortController) run.abortController.abort();
            } catch (_) {}

            // Local runs do not create a GitHub Actions workflow to cancel.
            if (run.mode === 'local') {
                if (runBtn) runBtn.disabled = false;
                return;
            }

            // Best-effort: cancel the GitHub Actions workflow run.
            try {
                const runId = await resolveWorkflowRunId(run.requestId, run.branchRef, run.runSha);
                if (runId) {
                    await cancelWorkflowRun(runId);
                } else {
                    showStatus('Abort requested, but could not determine the workflow run id to cancel.', 'error');
                }
            } catch (error) {
                const msg = (error && error.message) ? error.message : String(error);
                showStatus(`Abort requested, but cancel failed: ${msg}`, 'error');
            }

            // Allow starting a new run immediately; the polling loop will exit via abortController.
            if (runBtn) runBtn.disabled = false;
        }

        function delay(ms, signal) {
            return new Promise(resolve => {
                const timeoutId = setTimeout(resolve, ms);
                if (!signal) return;
                if (signal.aborted) {
                    clearTimeout(timeoutId);
                    resolve();
                    return;
                }
                signal.addEventListener('abort', () => {
                    clearTimeout(timeoutId);
                    resolve();
                }, { once: true });
            });
        }

        async function ensureWorkflowDispatch(branchRef) {
            const refParam = branchRef ? `?ref=${encodeURIComponent(branchRef)}` : '';
            const path = `/contents/.github/workflows/run-algorithm.yml${refParam}`;
            try {
                const wf = await apiRequest(path);
                if (!wf || !wf.content) return;
                const decoded = atob(wf.content.replace(/\s/g, ''));
                if (!decoded.includes('workflow_dispatch')) {
                    throw new Error('run-algorithm.yml is missing a workflow_dispatch trigger on this branch');
                }
            } catch (error) {
                // Surface a clear error for the common 422 case
                throw new Error(`Workflow unavailable on branch ${branchRef || 'main'}: ${error.message || error}`);
            }
        }

        async function downloadArtifactZip(artifact) {
            const item = artifact || {};
            const id = item.id ? String(item.id) : '';
            if (!id) throw new Error('Missing artifact id');

            const url = item.archive_download_url ||
                `https://api.github.com/repos/${config.owner}/${config.repo}/actions/artifacts/${id}/zip`;
            const headers = buildRequestHeaders({ accept: 'application/vnd.github+json' });

            const response = await fetch(url, { method: 'GET', headers });
            if (!response.ok) {
                const text = await response.text().catch(() => '');
                throw new Error(`Artifact download failed: ${response.status} ${response.statusText} ${text}`);
            }
            return await response.arrayBuffer();
        }

        async function extractResultJsonFromZip(buffer) {
            if (!window.JSZip) {
                throw new Error('JSZip is required to read results artifacts.');
            }
            const zip = await window.JSZip.loadAsync(buffer);
            let file = zip.file('outputs/result.json') || zip.file('result.json');
            if (!file) {
                const matches = zip.file(/result\.json$/i);
                if (matches && matches.length) file = matches[0];
            }
            if (!file) throw new Error('Result artifact is missing result.json');
            const text = await file.async('text');
            return JSON.parse(text);
        }

        async function fetchResultFromArtifact(requestId, branchRef, runSha) {
            const runId = await resolveWorkflowRunId(requestId, branchRef, runSha);
            if (!runId) return null;

            let data;
            try {
                data = await apiRequest(`/actions/runs/${runId}/artifacts`);
            } catch (error) {
                const msg = error && error.message ? error.message : '';
                if (msg.includes('401') || msg.includes('403')) {
                    throw new Error('Cannot access workflow artifacts. Ensure your token has Actions: Read permission.');
                }
                return null;
            }

            const artifactsRaw = (data && Array.isArray(data.artifacts)) ? data.artifacts : [];
            const artifacts = artifactsRaw.filter(item => item && !item.expired);
            if (!artifacts.length) return null;

            const match = artifacts.find(item => item.name === 'algorithm-result') ||
                (requestId ? artifacts.find(item => item.name && item.name.includes(requestId)) : null) ||
                artifacts[0];

            if (!match) return null;
            const buffer = await downloadArtifactZip(match);
            const json = await extractResultJsonFromZip(buffer);
            if (!requestId || !json.request_id || json.request_id === requestId) {
                return json;
            }
            return null;
        }

        async function waitForResult(requestId, branchRef, runSha, runCtx, options = {}) {
            const waitMs = 5000;
            const estimateMaxAttempts = 720; // UI-only fallback when Checks can't be read
            let lastError = null;
            let sha = runSha || '';
            const waitStartedMs = runTimerNowMs();
            const maxWaitMsRaw = options && options.maxWaitMs !== undefined ? Number(options.maxWaitMs) : NaN;
            // No timeout by default; the user can stop long runs with the Abort button.
            const maxWaitMs = Number.isFinite(maxWaitMsRaw) && maxWaitMsRaw > 0
                ? maxWaitMsRaw
                : 0;
            let completedSuccessNoArtifactSinceMs = 0;
            const skipSubgraphPhases = Array.isArray(options.skipSubgraphPhases)
                ? options.skipSubgraphPhases.map(phase => String(phase || '').toLowerCase())
                : [];

            for (let attempt = 1; ; attempt++) {
                if (runCtx && runCtx.aborted) {
                    return { status: 'aborted', error: 'Run Aborted' };
                }
                if (!sha) {
                    try {
                        sha = await getBranchHeadSha(branchRef || config.ref || 'main');
                        if (sha) progressState.runSha = sha;
                    } catch (_) {}
                }
                let progressUpdated = false;
                let progressReason = '';
                if (sha) {
                    try {
                        const progressRes = await tryUpdateProgressFromChecks(requestId, sha);
                        progressUpdated = !!(progressRes && progressRes.updated);
                        progressReason = progressRes && progressRes.reason ? progressRes.reason : '';
                    } catch (_) {}
                }
                if (!progressUpdated) {
                    const stage = (progressState && progressState.stage === 'tests') ? 'tests' : 'setup';
                    if (stage === 'setup') {
                        const setupMaxAttempts = 24; // ~2 minutes at 5s intervals
                        const phase = progressReason === 'forbidden'
                            ? 'Setting up Testing Environment (enable Checks: Read)'
                            : 'Setting up Testing Environment';
                        progressUpdateEstimated(Math.min(attempt, setupMaxAttempts), setupMaxAttempts, phase);

                        // If we can't read Checks, we can't detect the stage transition; still show two phases.
                        if (progressReason === 'forbidden' && attempt === setupMaxAttempts) {
                            const setupTotal = Number.isFinite(Number(progressState.total))
                                ? Number(progressState.total)
                                : (progressState.setupTotal || 100);
                            progressSetDeterminate('Setting up Testing Environment (enable Checks: Read)', setupTotal, setupTotal, { stage: 'setup' });
                            const testsTotal = Number.isFinite(Number(progressState.testsTotal)) ? Number(progressState.testsTotal) : 0;
                            progressSetDeterminate('Running tests... (enable Checks: Read)', 0, testsTotal, { stage: 'tests', reset: true });
                        }
                    } else {
                        const phase = progressReason === 'forbidden'
                            ? 'Running tests... (enable Checks: Read)'
                            : 'Running tests...';
                        progressUpdateEstimated(attempt, estimateMaxAttempts, phase);
                    }
                }
                let sawSkippedPhaseArtifact = false;
                try {
                    const result = await fetchResultFromArtifact(requestId, branchRef, sha);
                    if (result) {
                        if (
                            result.algorithm === 'subgraph' &&
                            skipSubgraphPhases.length > 0 &&
                            skipSubgraphPhases.includes(String(result.subgraph_phase || '').toLowerCase())
                        ) {
                            sawSkippedPhaseArtifact = true;
                        } else {
                            return result;
                        }
                    }
                } catch (error) {
                    lastError = error;
                    const msg = error && error.message ? error.message : '';
                    if (msg.includes('workflow artifacts') || msg.includes('JSZip')) {
                        throw error;
                    }
                }

                const workflowRunId = (progressState.workflowRunId && /^[0-9]+$/.test(progressState.workflowRunId))
                    ? String(progressState.workflowRunId)
                    : '';
                if (workflowRunId) {
                    let runState = null;
                    try {
                        runState = await getWorkflowRunState(workflowRunId);
                    } catch (error) {
                        lastError = error;
                        runState = null;
                    }
                    if (runState && runState.status === 'completed') {
                        const conclusion = runState.conclusion || 'unknown';
                        if (conclusion !== 'success') {
                            const runUrlNote = runState.htmlUrl ? ` Run: ${runState.htmlUrl}` : '';
                            throw new Error(`Workflow run ${workflowRunId} completed with conclusion '${conclusion}'.${runUrlNote}`);
                        }

                        const nowMs = runTimerNowMs();
                        if (!completedSuccessNoArtifactSinceMs) {
                            completedSuccessNoArtifactSinceMs = nowMs;
                        } else if ((nowMs - completedSuccessNoArtifactSinceMs) >= 15000) {
                            const expectedArtifact = sawSkippedPhaseArtifact
                                ? 'updated result artifact for the next subgraph phase'
                                : 'result artifact';
                            const runUrlNote = runState.htmlUrl ? ` Run: ${runState.htmlUrl}` : '';
                            throw new Error(`Workflow run ${workflowRunId} completed successfully, but no ${expectedArtifact} was found.${runUrlNote}`);
                        }
                    } else if (runState) {
                        completedSuccessNoArtifactSinceMs = 0;
                    }
                } else {
                    completedSuccessNoArtifactSinceMs = 0;
                }

                const elapsedWaitMs = runTimerNowMs() - waitStartedMs;
                if (maxWaitMs > 0 && elapsedWaitMs >= maxWaitMs) {
                    const runSuffix = workflowRunId ? ` (workflow run ${workflowRunId})` : '';
                    const lastErrorText = lastError && lastError.message ? ` Last error: ${lastError.message}` : '';
                    throw new Error(`Timed out after ${Math.round(elapsedWaitMs / 1000)}s waiting for workflow result${runSuffix}.${lastErrorText}`);
                }

                const backoffWaitMs = attempt > 96 ? 12000 : (attempt > 24 ? 8000 : waitMs);
                await delay(backoffWaitMs, runCtx && runCtx.abortController ? runCtx.abortController.signal : null);
            }
        }
