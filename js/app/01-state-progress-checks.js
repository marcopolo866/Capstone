        let config = {
            owner: '',
            repo: '',
            token: '',
            ref: 'main',
            selectedAlgorithm: null,
            selectedFiles: [],
            inputMode: 'generate',
            generator: {
                n: '100',
                k: '10',
                density: '0.01',
                seed: ''
            }
        };

        let dataFileMeta = {};
        const graphMetricCache = new Map();
        let activeRun = null;
        const runTimerState = {
            owner: null,
            startMs: 0,
            intervalId: null
        };
        
        const algorithmConfigs = {
            dijkstra: {
                name: "Dijkstra's Algorithm",
                requiredFiles: 1,
                fileTypes: ['.txt', '.csv', '.grf'],
                instructions: [
                    'Plain text format: first line is the vertex count, second line is "start,target", remaining lines are "u,v,weight" (commas or spaces).',
                    'CSV format: rows contain "source,target,weight"; vertex labels can be names. Add an optional comment line like "# start=A target=D" to choose the endpoints (defaults to the first source and last target).',
                    'When labels are present the reported path will use those labels in the output window.'
                ]
            },
            glasgow: {
                name: "Glasgow Subgraph Solver",
                requiredFiles: 2,
                fileTypes: ['.grf'],
                fileLabels: ['Pattern File', 'Target File']
            },
            vf3: {
                name: "VF3 Algorithm",
                requiredFiles: 2,
                fileTypes: ['.grf'],
                fileLabels: ['Subgraph File', 'Graph File']
            },
            subgraph: {
                name: "Subgraph Isomorphism (Combined)",
                requiredFiles: 2,
                fileTypes: ['.vf', '.lad', '.grf'],
                fileLabels: ['Pattern File', 'Target File'],
                instructions: [
                    'Provide either a .vf/.grf pair (VF3 format) or a .lad pair (Glasgow format).',
                    'Both files must be in the same format; the runner will convert to both formats internally.'
                ]
            }
        };

        const progressState = {
            requestId: '',
            runSha: '',
            workflowRunId: '',
            stage: 'idle', // 'idle' | 'setup' | 'tests'
            setupTotal: 0,
            testsTotal: 0,
            hasLiveSetup: false,
            total: 0,
            completed: 0,
            phase: ''
        };

        function getTestsPerIteration(algoId) {
            if (algoId === 'dijkstra') return 2;
            if (algoId === 'glasgow') return 3;
            if (algoId === 'vf3') return 3;
            if (algoId === 'subgraph') return 6;
            return 0;
        }

        function getProgressEls() {
            return {
                area: document.getElementById('progress-area'),
                wrapper: document.getElementById('progress-wrapper'),
                timer: document.getElementById('run-timer'),
                phase: document.getElementById('progress-phase'),
                count: document.getElementById('progress-count'),
                bar: document.getElementById('progress-bar'),
                fill: document.getElementById('progress-fill')
            };
        }

        function runTimerNowMs() {
            return (window.performance && typeof window.performance.now === 'function')
                ? window.performance.now()
                : Date.now();
        }

        function formatElapsedMs(ms) {
            const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
            const seconds = totalSeconds % 60;
            const minutesTotal = Math.floor(totalSeconds / 60);
            const minutes = minutesTotal % 60;
            const hours = Math.floor(minutesTotal / 60);

            if (hours > 0) {
                return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            }
            return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        }

        function runTimerSetElapsed(ms) {
            const els = getProgressEls();
            if (!els.timer) return;
            els.timer.textContent = `Elapsed: ${formatElapsedMs(ms)}`;
        }

        function runTimerStart(runCtx) {
            const els = getProgressEls();
            if (!els.timer) return;

            runTimerStop();
            runTimerState.owner = runCtx || null;
            runTimerState.startMs = runTimerNowMs();

            els.timer.hidden = false;
            runTimerSetElapsed(0);

            runTimerState.intervalId = window.setInterval(() => {
                if (runTimerState.owner !== runCtx) return;
                runTimerSetElapsed(runTimerNowMs() - runTimerState.startMs);
            }, 1000);
        }

        function runTimerStop(runCtx = null) {
            if (runCtx && runTimerState.owner !== runCtx) return;
            if (runTimerState.intervalId) {
                clearInterval(runTimerState.intervalId);
                runTimerState.intervalId = null;
            }
        }

        function runTimerReset() {
            runTimerStop();
            runTimerState.owner = null;
            runTimerState.startMs = 0;
            runTimerSetElapsed(0);
            const els = getProgressEls();
            if (els.timer) els.timer.hidden = true;
        }

        function setProgressVisible(visible) {
            const els = getProgressEls();
            if (els.area) {
                els.area.hidden = !visible;
                return;
            }
            if (els.wrapper) {
                els.wrapper.hidden = !visible;
            }
        }

        function progressReset(algoId, iterations, requestId, options = {}) {
            const testsPerIterRaw = options && options.testsPerIter !== undefined ? Number(options.testsPerIter) : NaN;
            const testsPerIter = Number.isFinite(testsPerIterRaw) ? Math.max(0, Math.floor(testsPerIterRaw)) : getTestsPerIteration(algoId);
            const setupTotalRaw = options && options.setupTotal !== undefined ? Number(options.setupTotal) : NaN;
            const setupTotal = Number.isFinite(setupTotalRaw) ? Math.max(1, Math.floor(setupTotalRaw)) : 100;
            const initialPhase = options && typeof options.initialPhase === 'string'
                ? options.initialPhase
                : 'Setting up Testing Environment';
            progressState.requestId = requestId || '';
            progressState.runSha = '';
            progressState.workflowRunId = '';
            progressState.stage = 'setup';
            progressState.setupTotal = setupTotal;
            progressState.testsTotal = Math.max(0, Number(iterations) || 0) * testsPerIter;
            progressState.hasLiveSetup = false;
            progressState.total = progressState.setupTotal;
            progressState.completed = 0;
            progressState.phase = '';

            setProgressVisible(true);
            progressSetDeterminate(initialPhase, 0, progressState.total, { stage: 'setup', reset: true });
        }

        function progressClear() {
            progressState.requestId = '';
            progressState.runSha = '';
            progressState.workflowRunId = '';
            progressState.stage = 'idle';
            progressState.setupTotal = 0;
            progressState.testsTotal = 0;
            progressState.hasLiveSetup = false;
            progressState.total = 0;
            progressState.completed = 0;
            progressState.phase = '';

            const els = getProgressEls();
            if (els.area) {
                els.area.hidden = true;
            } else if (els.wrapper) {
                els.wrapper.hidden = true;
            }
            runTimerReset();
            if (els.fill) els.fill.style.width = '0%';
            if (els.bar) els.bar.setAttribute('aria-valuenow', '0');
            if (els.phase) els.phase.textContent = '';
            if (els.count) els.count.textContent = '';
        }

        function progressSetDeterminate(phaseText, completed, total, options = {}) {
            const els = getProgressEls();

            const prevTotal = Number.isFinite(Number(progressState.total)) ? Number(progressState.total) : 0;
            const prevCompleted = Number.isFinite(Number(progressState.completed)) ? Number(progressState.completed) : 0;
            const prevStage = typeof progressState.stage === 'string' ? progressState.stage : 'idle';
            const nextStage = options && typeof options.stage === 'string' ? options.stage : prevStage;
            const stageChanged = nextStage !== prevStage;
            const shouldReset = !!(options && (options.reset || stageChanged));

            const safeTotal = Math.max(0, Number(total) || 0);
            const effectiveTotal = safeTotal ? safeTotal : (shouldReset ? 0 : prevTotal);
            const requestedCompleted = Math.max(0, Math.min(effectiveTotal || 0, Number(completed) || 0));
            const safeCompleted = shouldReset ? requestedCompleted : Math.max(prevCompleted, requestedCompleted);
            const clampedCompleted = effectiveTotal ? Math.min(effectiveTotal, safeCompleted) : 0;
            const percent = effectiveTotal ? (clampedCompleted / effectiveTotal) * 100 : 0;
            const displayCompleted = Math.floor(clampedCompleted);

            progressState.stage = nextStage;
            progressState.completed = clampedCompleted;
            progressState.total = effectiveTotal;
            progressState.phase = phaseText || '';

            if (els.phase) els.phase.textContent = phaseText || 'Running...';
            if (els.count) els.count.textContent = effectiveTotal ? `${displayCompleted}/${effectiveTotal} (${percent.toFixed(1)}%)` : `${displayCompleted}/0`;
            if (els.fill) els.fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
            if (els.bar) els.bar.setAttribute('aria-valuenow', String(Math.round(percent)));
        }

        function progressUpdateEstimated(attempt, maxAttempts, phaseText) {
            const total = Number.isFinite(Number(progressState.total)) ? Number(progressState.total) : 0;
            if (!total) {
                progressSetDeterminate(phaseText || 'Running...', 0, 0);
                return;
            }

            const denom = Math.max(1, Number(maxAttempts) || 1);
            const step = Math.min(Math.max(1, Number(attempt) || 1), denom);
            const targetPercent = Math.min(95, (step / denom) * 95);
            const currentPercent = (progressState.completed / total) * 100;
            const percent = Math.max(currentPercent, targetPercent);
            const estimatedCompleted = (percent / 100) * total;
            progressSetDeterminate(phaseText || 'Running...', estimatedCompleted, total);
        }

        function encodePathPreservingSlashes(value) {
            return String(value || '').split('/').map(part => encodeURIComponent(part)).join('/');
        }

        async function getBranchHeadSha(branchRef) {
            const ref = String(branchRef || '').trim();
            if (!ref) return '';

            try {
                const data = await apiRequest(`/git/ref/heads/${encodePathPreservingSlashes(ref)}`);
                if (data && data.object && data.object.sha) return data.object.sha;
            } catch (_) {}

            try {
                const data = await apiRequest(`/commits/${encodePathPreservingSlashes(ref)}`);
                if (data && data.sha) return data.sha;
            } catch (_) {}

            return '';
        }

        async function tryUpdateProgressFromChecks(requestId, runSha) {
            if (!requestId || !runSha) return { updated: false, reason: 'missing' };

            const endpoint = `/commits/${runSha}/check-runs?per_page=100&filter=latest`;

            let data = null;
            let authError = null;
            try {
                data = await apiRequest(endpoint);
            } catch (error) {
                authError = error;
            }

            if (!data) {
                const msg = authError && authError.message ? authError.message : '';
                // If a fine-grained token lacks Checks: Read but the repo is public, retry without auth.
                if (config.token && (msg.includes('403') || msg.includes('401'))) {
                    try {
                        data = await apiRequest(endpoint, 'GET', null, { useAuth: false });
                    } catch (fallbackError) {
                        const fallbackMsg = fallbackError && fallbackError.message ? fallbackError.message : '';
                        if (msg.includes('403') || fallbackMsg.includes('403')) {
                            return { updated: false, reason: 'forbidden' };
                        }
                        return { updated: false, reason: 'error' };
                    }
                } else {
                    if (msg.includes('403')) {
                        return { updated: false, reason: 'forbidden' };
                    }
                    return { updated: false, reason: 'error' };
                }
            }

            const checkRuns = (data && Array.isArray(data.check_runs)) ? data.check_runs : [];
            if (!checkRuns.length) return { updated: false, reason: 'no_check_runs' };

            const match = checkRuns.find(cr => typeof cr.name === 'string' && cr.name.includes(requestId)) ||
                          checkRuns.find(cr => cr.output && typeof cr.output.text === 'string' && cr.output.text.includes(requestId));
            if (!match) return { updated: false, reason: 'not_found' };

            let progress = null;
            if (match.output && typeof match.output.text === 'string') {
                try {
                    progress = JSON.parse(match.output.text);
                } catch (_) {
                    progress = null;
                }
            }

            const runIdRaw = progress && (typeof progress.run_id === 'string' || typeof progress.run_id === 'number')
                ? String(progress.run_id).trim()
                : '';
            if (runIdRaw && /^[0-9]+$/.test(runIdRaw)) {
                progressState.workflowRunId = runIdRaw;
            }

            const completed = progress && Number.isFinite(Number(progress.completed)) ? Number(progress.completed) : 0;
            const total = progress && Number.isFinite(Number(progress.total)) ? Number(progress.total) : (progressState.total || 0);
            const phase = progress && typeof progress.phase === 'string' ? progress.phase : '';

            const stage = progress && typeof progress.stage === 'string' ? progress.stage : '';
            if (stage === 'setup') {
                const setupCompleted = progress && Number.isFinite(Number(progress.setup_completed)) ? Number(progress.setup_completed) : 0;
                const setupTotal = progress && Number.isFinite(Number(progress.setup_total)) ? Number(progress.setup_total) : (progressState.setupTotal || 100);
                progressState.setupTotal = setupTotal || progressState.setupTotal || 100;
                const reset = !progressState.hasLiveSetup;
                progressState.hasLiveSetup = true;
                progressSetDeterminate('Setting up Testing Environment', setupCompleted, setupTotal, { stage: 'setup', reset });
            } else if (stage === 'tests') {
                const testsCompleted = progress && Number.isFinite(Number(progress.tests_completed))
                    ? Number(progress.tests_completed)
                    : completed;
                const testsTotal = progress && Number.isFinite(Number(progress.tests_total))
                    ? Number(progress.tests_total)
                    : total;
                progressState.testsTotal = testsTotal || progressState.testsTotal || 0;
                progressSetDeterminate(phase || 'Running tests...', testsCompleted, testsTotal, { stage: 'tests' });
            } else if (stage === 'glasgow') {
                const testsCompleted = progress && Number.isFinite(Number(progress.tests_completed))
                    ? Number(progress.tests_completed)
                    : completed;
                const testsTotal = progress && Number.isFinite(Number(progress.tests_total))
                    ? Number(progress.tests_total)
                    : total;
                progressState.testsTotal = testsTotal || progressState.testsTotal || 0;
                progressSetDeterminate(phase || 'Running Glasgow...', testsCompleted, testsTotal, { stage: 'glasgow' });
            } else {
                // Backwards-compatible: treat legacy payload as test progress.
                progressSetDeterminate(phase || 'Running tests...', completed, total, { stage: 'tests' });
            }
            return { updated: true, reason: 'ok' };
        }
        
