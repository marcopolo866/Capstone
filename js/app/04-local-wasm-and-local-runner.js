        function getSelectedRunMode() {
            const selected = document.querySelector('input[name="run-mode"]:checked');
            const raw = selected ? String(selected.value || '').trim().toLowerCase() : 'standard';
            return raw === 'local' ? 'local' : 'standard';
        }

        const localWasmScriptPromises = new Map();
        const localWasmModulePromises = new Map();

        function invalidateEmscriptenModule(id) {
            const key = String(id || '').trim();
            if (!key) return;
            localWasmModulePromises.delete(key);
        }

        function loadScriptOnce(src) {
            const url = String(src || '').trim();
            if (!url) return Promise.reject(new Error('Missing script URL'));
            if (localWasmScriptPromises.has(url)) return localWasmScriptPromises.get(url);

            const promise = new Promise((resolve, reject) => {
                const existing = Array.from(document.querySelectorAll('script[data-capstone-wasm-src]'))
                    .find(el => el && el.dataset && el.dataset.capstoneWasmSrc === url);
                if (existing) {
                    if (existing.dataset && existing.dataset.capstoneWasmLoaded === 'true') {
                        resolve();
                        return;
                    }
                    existing.addEventListener('load', () => resolve(), { once: true });
                    existing.addEventListener('error', () => reject(new Error(`Failed to load script: ${url}`)), { once: true });
                    return;
                }

                const el = document.createElement('script');
                el.src = url;
                el.async = true;
                el.dataset.capstoneWasmSrc = url;
                el.dataset.capstoneWasmLoaded = 'false';
                el.onload = () => {
                    el.dataset.capstoneWasmLoaded = 'true';
                    resolve();
                };
                el.onerror = () => reject(new Error(`Failed to load script: ${url}`));
                document.head.appendChild(el);
            });

            localWasmScriptPromises.set(url, promise);
            return promise;
        }

        function getGitHubAuthHeaderValue() {
            if (!config.token) return '';
            const lower = String(config.token).toLowerCase();
            const useBearer = lower.startsWith('github_pat_') || lower.startsWith('ghs_') || lower.startsWith('ghu_');
            return useBearer ? `Bearer ${config.token}` : `token ${config.token}`;
        }

        function sanitizeFsFilename(name) {
            const raw = String(name || 'file').trim() || 'file';
            return raw
                .replace(/[\\/]/g, '_')
                .replace(/[^a-zA-Z0-9._-]/g, '_')
                .slice(0, 120);
        }

        async function getRepoFileText(path) {
            const p = String(path || '').trim();
            if (!p) throw new Error('Missing file path');
            const ref = String(config.ref || '').trim();
            const refParam = ref ? `?ref=${encodeURIComponent(ref)}` : '';

            // Prefer GitHub Contents API (works for private repos with PAT).
            try {
                const file = await apiRequest(`/contents/${encodePathPreservingSlashes(p)}${refParam}`);
                if (file && typeof file.content === 'string' && file.encoding === 'base64') {
                    return atob(file.content.replace(/\s/g, ''));
                }
                if (file && typeof file.download_url === 'string' && file.download_url) {
                    const auth = getGitHubAuthHeaderValue();
                    const headers = auth ? { Authorization: auth } : {};
                    const resp = await fetch(file.download_url, { headers });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching ${p}`);
                    return await resp.text();
                }
            } catch (_) {}

            // Fallback: try downloadUrl from cached directory listing.
            const meta = dataFileMeta && dataFileMeta[p] ? dataFileMeta[p] : null;
            if (meta && meta.downloadUrl) {
                const auth = getGitHubAuthHeaderValue();
                const headers = auth ? { Authorization: auth } : {};
                const resp = await fetch(meta.downloadUrl, { headers });
                if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching ${p}`);
                return await resp.text();
            }

            throw new Error(`Failed to load file content: ${p}`);
        }

        async function getEmscriptenModule(spec) {
            const id = String(spec && spec.id ? spec.id : '').trim();
            if (!id) throw new Error('Missing wasm module id');
            if (localWasmModulePromises.has(id)) return localWasmModulePromises.get(id);

            const scriptPath = String(spec && spec.scriptPath ? spec.scriptPath : '').trim();
            const factoryName = String(spec && spec.factoryName ? spec.factoryName : '').trim();
            const wasmPath = String(spec && spec.wasmPath ? spec.wasmPath : '').trim();
            if (!scriptPath || !factoryName || !wasmPath) {
                throw new Error(`Invalid wasm module spec for ${id}`);
            }

            const promise = (async () => {
                if (!('WebAssembly' in window)) {
                    throw new Error('WebAssembly is not supported in this browser.');
                }

                await loadScriptOnce(scriptPath);
                const factory = window[factoryName];
                if (typeof factory !== 'function') {
                    throw new Error(`WASM factory not found: ${factoryName} (did ${scriptPath} load?)`);
                }

                const capture = {
                    out: [],
                    err: [],
                    reset() {
                        this.out.length = 0;
                        this.err.length = 0;
                    }
                };

                const module = await factory({
                    noInitialRun: true,
                    // We call callMain() many times per run; keep the runtime alive between invocations.
                    noExitRuntime: true,
                    locateFile: (path, prefix) => {
                        if (typeof path === 'string' && path.endsWith('.wasm')) {
                            return wasmPath;
                        }
                        return (prefix || '') + path;
                    },
                    print: (text) => capture.out.push(String(text)),
                    printErr: (text) => capture.err.push(String(text))
                });

                if (!module || !module.FS || typeof module.callMain !== 'function') {
                    throw new Error(`WASM module missing FS/callMain: ${id}`);
                }

                module.__capstoneCapture = capture;
                module.__capstoneId = id;
                return module;
            })();

            localWasmModulePromises.set(id, promise);
            return promise;
        }

        async function getFreshEmscriptenModule(spec) {
            const id = String(spec && spec.id ? spec.id : '').trim();
            if (!id) throw new Error('Missing wasm module id');
            invalidateEmscriptenModule(id);
            return await getEmscriptenModule(spec);
        }

        function ensureEmscriptenDir(mod, path) {
            const dir = String(path || '').trim();
            if (!dir) return;
            try {
                mod.FS.mkdir(dir);
            } catch (_) {}
        }

        function writeEmscriptenTextFile(mod, path, text) {
            mod.FS.writeFile(path, String(text || ''), { encoding: 'utf8' });
        }

        function parseFirstLine(text) {
            const raw = String(text || '').replace(/\r/g, '');
            const line = raw.split('\n')[0] || '';
            return line.trim();
        }

        function parseFirstToken(line) {
            const l = String(line || '').trim();
            if (!l) return '';
            return l.split(/\s+/)[0] || '';
        }

        async function runEmscriptenMain(mod, args) {
            const argv = Array.isArray(args) ? args.map(a => String(a)) : [];
            const capture = mod.__capstoneCapture;
            if (!capture) throw new Error('Missing wasm capture');
            capture.reset();

            try {
                mod.callMain(argv);
            } catch (error) {
                // Emscripten may throw an ExitStatus object on exit().
                const status = (error && typeof error.status === 'number') ? error.status : null;
                const stdout = capture.out.join('\n');
                const stderr = capture.err.join('\n');
                if (status === 0) {
                    return {
                        stdout: stdout.trimEnd(),
                        stderr: stderr.trimEnd()
                    };
                }
                const msg = stderr || stdout || (error && error.message ? error.message : String(error));
                if (status !== null) {
                    throw new Error(`WASM program exited with status ${status}: ${msg}`);
                }

                // Runtime traps (e.g., "function signature mismatch") can poison the module instance.
                // Drop it so the next run will recreate a fresh instance.
                try {
                    if (mod && mod.__capstoneId) invalidateEmscriptenModule(mod.__capstoneId);
                } catch (_) {}
                throw error;
            }

            return {
                stdout: capture.out.join('\n').trimEnd(),
                stderr: capture.err.join('\n').trimEnd()
            };
        }

        function calcStatsMs(values) {
            const vals = (Array.isArray(values) ? values : [])
                .map(v => Number(v))
                .filter(v => Number.isFinite(v));
            if (!vals.length) return null;

            const sorted = vals.slice().sort((a, b) => a - b);
            const n = sorted.length;
            const mean = sorted.reduce((s, v) => s + v, 0) / n;
            const median = (n % 2 === 1)
                ? sorted[(n - 1) / 2]
                : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
            const stdev = (n > 1)
                ? Math.sqrt(sorted.reduce((s, v) => s + Math.pow(v - mean, 2), 0) / (n - 1))
                : 0;
            const min = sorted[0];
            const max = sorted[n - 1];
            return { n, mean, median, stdev, min, max };
        }

        function formatStatsMsFirstAll(prefix, firstStats, allStats) {
            const pfx = String(prefix || '');
            const indent = ' '.repeat(pfx.length);
            const fmt = (v) => Number(v).toFixed(3).padStart(10);
            const line = (lead, label, s) => `${lead}${String(label).padEnd(5)} median=${fmt(s.median)} mean=${fmt(s.mean)} stdev=${fmt(s.stdev)} min=${fmt(s.min)} max=${fmt(s.max)}`;
            return [
                line(pfx, 'first', firstStats),
                line(indent, 'all', allStats)
            ];
        }

        function formatStatsMsSummary(prefix, stats) {
            if (!stats) return '';
            const pfx = String(prefix || '');
            const fmt = (v) => Number(v).toFixed(3);
            return `${pfx}median=${fmt(stats.median)} mean=${fmt(stats.mean)} stdev=${fmt(stats.stdev)} min=${fmt(stats.min)} max=${fmt(stats.max)}`;
        }

        async function runDijkstraLocally(runCtx, iterations, warmup) {
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));

            const inputFile = (config.selectedFiles && config.selectedFiles[0]) ? config.selectedFiles[0] : null;
            if (!inputFile || !inputFile.path) {
                throw new Error('Dijkstra requires one input file');
            }

            const ticksPerIter = 3; // baseline + chatgpt + gemini
            const setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            const testsTotal = safeIterations * ticksPerIter;

            progressReset('dijkstra', safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter: ticksPerIter
            });

            const inputName = sanitizeFsFilename(inputFile.name || 'input');
            const inputFsPath = `/inputs/${inputName}`;

            const inputText = await getRepoFileText(inputFile.path);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const baselineSpec = {
                id: 'dijkstra_baseline',
                scriptPath: 'wasm/dijkstra_baseline.js',
                wasmPath: 'wasm/dijkstra_baseline.wasm',
                factoryName: 'createDijkstraBaselineModule'
            };
            const llmSpec = {
                id: 'dijkstra_llm',
                scriptPath: 'wasm/dijkstra_llm.js',
                wasmPath: 'wasm/dijkstra_llm.wasm',
                factoryName: 'createDijkstraLlmModule'
            };
            const geminiSpec = {
                id: 'dijkstra_gemini',
                scriptPath: 'wasm/dijkstra_gemini.js',
                wasmPath: 'wasm/dijkstra_gemini.wasm',
                factoryName: 'createDijkstraGeminiModule'
            };

            const abortSignal = runCtx && runCtx.abortController ? runCtx.abortController.signal : null;

            const writeInput = (mod) => {
                ensureEmscriptenDir(mod, '/inputs');
                writeEmscriptenTextFile(mod, inputFsPath, inputText);
            };

            const unloadModule = (spec) => {
                try {
                    invalidateEmscriptenModule(spec && spec.id ? spec.id : '');
                } catch (_) {}
            };

            const loadFreshModule = async (spec) => {
                const mod = await getFreshEmscriptenModule(spec);
                writeInput(mod);
                return mod;
            };

            try {
                // Phase 1: setup + warmup (progress bar fills once)
                if (safeWarmup > 0) {
                    let setupDone = 0;

                    // Baseline warmups
                    let mod = await loadFreshModule(baselineSpec);
                    try {
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            progressSetDeterminate('Warming up: Dijkstra baseline', setupDone, setupTotal, { stage: 'setup' });
                            try {
                                await runEmscriptenMain(mod, [inputFsPath]);
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Warmup ${i + 1}/${safeWarmup} - Dijkstra baseline: ${msg}`);
                            }
                            setupDone++;
                            progressSetDeterminate('Warming up: Dijkstra baseline', setupDone, setupTotal, { stage: 'setup' });
                            await delay(0, abortSignal);
                        }
                    } finally {
                        mod = null;
                        unloadModule(baselineSpec);
                    }

                    // LLM warmups
                    mod = await loadFreshModule(llmSpec);
                    try {
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            progressSetDeterminate('Warming up: Dijkstra llm', setupDone, setupTotal, { stage: 'setup' });
                            try {
                                await runEmscriptenMain(mod, [inputFsPath]);
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Warmup ${i + 1}/${safeWarmup} - Dijkstra llm: ${msg}`);
                            }
                            setupDone++;
                            progressSetDeterminate('Warming up: Dijkstra llm', setupDone, setupTotal, { stage: 'setup' });
                            await delay(0, abortSignal);
                        }
                    } finally {
                        mod = null;
                        unloadModule(llmSpec);
                    }

                    // Gemini warmups
                    mod = await loadFreshModule(geminiSpec);
                    try {
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            progressSetDeterminate('Warming up: Dijkstra gemini', setupDone, setupTotal, { stage: 'setup' });
                            try {
                                await runEmscriptenMain(mod, [inputFsPath]);
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Warmup ${i + 1}/${safeWarmup} - Dijkstra gemini: ${msg}`);
                            }
                            setupDone++;
                            progressSetDeterminate('Warming up: Dijkstra gemini', setupDone, setupTotal, { stage: 'setup' });
                            await delay(0, abortSignal);
                        }
                    } finally {
                        mod = null;
                        unloadModule(geminiSpec);
                    }
                } else {
                    // Still complete the setup phase so the bar fills once.
                    progressSetDeterminate('Setting up Testing Environment', setupTotal, setupTotal, { stage: 'setup' });
                }

                // Phase 2: measured iterations (bar resets and fills again)
                progressSetDeterminate('Running tests...', 0, testsTotal, { stage: 'tests', reset: true });

                let ticksDone = 0;

                const baselineTimes = [];
                const llmTimes = [];
                const geminiTimes = [];
                let baselineResult = '';
                let llmResult = '';
                let geminiResult = '';

                // Baseline chunk
                let mod = await loadFreshModule(baselineSpec);
                try {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate('Dijkstra baseline', ticksDone, testsTotal, { stage: 'tests' });
                        const t0 = runTimerNowMs();
                        let stdout = '';
                        try {
                            const res = await runEmscriptenMain(mod, [inputFsPath]);
                            stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                        } catch (error) {
                            const msg = error && error.message ? error.message : String(error);
                            throw new Error(`Iteration ${iter + 1}/${safeIterations} - Dijkstra baseline: ${msg}`);
                        }
                        const t1 = runTimerNowMs();
                        baselineTimes.push(Math.max(0, t1 - t0));
                        baselineResult = parseFirstLine(stdout) || stdout.trim();
                        ticksDone++;
                        progressSetDeterminate('Dijkstra baseline', ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                } finally {
                    mod = null;
                    unloadModule(baselineSpec);
                }

                // LLM chunk
                mod = await loadFreshModule(llmSpec);
                try {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate('Dijkstra llm', ticksDone, testsTotal, { stage: 'tests' });
                        const t0 = runTimerNowMs();
                        let stdout = '';
                        try {
                            const res = await runEmscriptenMain(mod, [inputFsPath]);
                            stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                        } catch (error) {
                            const msg = error && error.message ? error.message : String(error);
                            throw new Error(`Iteration ${iter + 1}/${safeIterations} - Dijkstra llm: ${msg}`);
                        }
                        const t1 = runTimerNowMs();
                        llmTimes.push(Math.max(0, t1 - t0));
                        llmResult = parseFirstLine(stdout) || stdout.trim();
                        ticksDone++;
                        progressSetDeterminate('Dijkstra llm', ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                } finally {
                    mod = null;
                    unloadModule(llmSpec);
                }

                // Gemini chunk
                mod = await loadFreshModule(geminiSpec);
                try {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate('Dijkstra gemini', ticksDone, testsTotal, { stage: 'tests' });
                        const t0 = runTimerNowMs();
                        let stdout = '';
                        try {
                            const res = await runEmscriptenMain(mod, [inputFsPath]);
                            stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                        } catch (error) {
                            const msg = error && error.message ? error.message : String(error);
                            throw new Error(`Iteration ${iter + 1}/${safeIterations} - Dijkstra gemini: ${msg}`);
                        }
                        const t1 = runTimerNowMs();
                        geminiTimes.push(Math.max(0, t1 - t0));
                        geminiResult = parseFirstLine(stdout) || stdout.trim();
                        ticksDone++;
                        progressSetDeterminate('Dijkstra gemini', ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                } finally {
                    mod = null;
                    unloadModule(geminiSpec);
                }

                progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

                const sBaseline = calcStatsMs(baselineTimes);
                const sLlm = calcStatsMs(llmTimes);
                const sGemini = calcStatsMs(geminiTimes);

                const lines = [];
                const addSection = (title, result, stats) => {
                    lines.push(`[${title}]`);
                    lines.push(result || '(No output)');
                    lines.push(`Warmup: ${safeWarmup}`);
                    lines.push(`Iterations: ${safeIterations}`);
                    if (stats) {
                        lines.push(formatStatsMsSummary('Runtime (ms): ', stats));
                    }
                    lines.push('');
                };

                addSection('Dijkstra Baseline', baselineResult, sBaseline);
                addSection('Dijkstra ChatGPT', llmResult, sLlm);
                addSection('Dijkstra Gemini', geminiResult, sGemini);

                return { status: 'success', output: lines.join('\n') };
            } finally {
                unloadModule(baselineSpec);
                unloadModule(llmSpec);
                unloadModule(geminiSpec);
            }
        }

        async function runVf3Locally(runCtx, iterations, warmup) {
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));

            const patternFile = (config.selectedFiles && config.selectedFiles[0]) ? config.selectedFiles[0] : null;
            const targetFile = (config.selectedFiles && config.selectedFiles[1]) ? config.selectedFiles[1] : null;
            if (!patternFile || !targetFile || !patternFile.path || !targetFile.path) {
                throw new Error('VF3 requires a pattern and target file');
            }

            const ticksPerIter = 6; // baseline first/all + gemini first/all + chatgpt first/all
            const setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            const testsTotal = safeIterations * ticksPerIter;

            progressReset('vf3', safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter: ticksPerIter
            });

            const patternName = sanitizeFsFilename(patternFile.name || 'pattern');
            const targetName = sanitizeFsFilename(targetFile.name || 'target');
            const patternFsPath = `/inputs/${patternName}`;
            const targetFsPath = `/inputs/${targetName}`;

            const [patternText, targetText] = await Promise.all([
                getRepoFileText(patternFile.path),
                getRepoFileText(targetFile.path)
            ]);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const baselineSpec = {
                id: 'vf3_baseline',
                scriptPath: 'wasm/vf3_baseline.js',
                wasmPath: 'wasm/vf3_baseline.wasm',
                factoryName: 'createVf3BaselineModule'
            };
            const geminiSpec = {
                id: 'vf3_gemini',
                scriptPath: 'wasm/vf3_gemini.js',
                wasmPath: 'wasm/vf3_gemini.wasm',
                factoryName: 'createVf3GeminiModule'
            };
            const chatgptSpec = {
                id: 'vf3_chatgpt',
                scriptPath: 'wasm/vf3_chatgpt.js',
                wasmPath: 'wasm/vf3_chatgpt.wasm',
                factoryName: 'createVf3ChatgptModule'
            };

            const writeInputs = (mod) => {
                ensureEmscriptenDir(mod, '/inputs');
                writeEmscriptenTextFile(mod, patternFsPath, patternText);
                writeEmscriptenTextFile(mod, targetFsPath, targetText);
            };

            // IMPORTANT: these compiled WASM programs are invoked via `callMain()`. If the underlying C++
            // code has leaks/UB, long in-process runs can eventually trap. For stability and clarity, run
            // each solver in its own chunk (baseline -> Gemini -> ChatGPT) and periodically recreate the
            // baseline module during its chunk.
            const baselineRecycleEveryIterations = 50;
            const abortSignal = runCtx && runCtx.abortController ? runCtx.abortController.signal : null;

            const unloadModule = (spec) => {
                try {
                    invalidateEmscriptenModule(spec && spec.id ? spec.id : '');
                } catch (_) {}
            };

            const loadFreshModule = async (spec, label, done, total, stage) => {
                if (label) {
                    const current = Number.isFinite(Number(done)) ? Number(done) : 0;
                    const denom = Number.isFinite(Number(total)) ? Number(total) : 1;
                    progressSetDeterminate(label, current, Math.max(1, denom), { stage });
                }
                const mod = await getFreshEmscriptenModule(spec);
                writeInputs(mod);
                return mod;
            };

            try {
                const warmupSolver = async (title, spec, labelFirst, argsFirst, labelAll, argsAll, setupDoneRef) => {
                    let mod = await loadFreshModule(spec, `Loading ${title} WASM...`, setupDoneRef.value, setupTotal, 'setup');
                    try {
                        for (let i = 0; i < safeWarmup; i++) {
                            const steps = [
                                { label: labelFirst, args: argsFirst },
                                { label: labelAll, args: argsAll }
                            ];
                            for (const step of steps) {
                                if (runCtx && runCtx.aborted) return;
                                progressSetDeterminate(`Warming up: ${title}`, setupDoneRef.value, setupTotal, { stage: 'setup' });
                                try {
                                    await runEmscriptenMain(mod, step.args);
                                } catch (error) {
                                    const msg = error && error.message ? error.message : String(error);
                                    throw new Error(`Warmup ${i + 1}/${safeWarmup} - ${step.label}: ${msg}`);
                                }
                                setupDoneRef.value++;
                                progressSetDeterminate(`Warming up: ${title}`, setupDoneRef.value, setupTotal, { stage: 'setup' });
                                await delay(0, abortSignal);
                            }
                        }
                    } finally {
                        mod = null;
                        unloadModule(spec);
                    }
                };

                // Phase 1: setup + warmup (progress bar fills once)
                if (safeWarmup > 0) {
                    const setupDoneRef = { value: 0 };
                    await warmupSolver(
                        'VF3 baseline',
                        baselineSpec,
                        'VF3 baseline first',
                        ['-r', '0', '-F', patternFsPath, targetFsPath],
                        'VF3 baseline all',
                        ['-r', '0', patternFsPath, targetFsPath],
                        setupDoneRef
                    );
                    await warmupSolver(
                        'VF3 Gemini',
                        geminiSpec,
                        'VF3 Gemini first',
                        ['--first-only', patternFsPath, targetFsPath],
                        'VF3 Gemini all',
                        [patternFsPath, targetFsPath],
                        setupDoneRef
                    );
                    await warmupSolver(
                        'VF3 ChatGPT',
                        chatgptSpec,
                        'VF3 ChatGPT first',
                        ['--first-only', patternFsPath, targetFsPath],
                        'VF3 ChatGPT all',
                        [patternFsPath, targetFsPath],
                        setupDoneRef
                    );
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                } else {
                    // Still complete the setup phase so the bar fills once.
                    progressSetDeterminate('Setting up Testing Environment', setupTotal, setupTotal, { stage: 'setup', reset: true });
                }

                // Phase 2: measured iterations (bar resets and fills again)
                progressSetDeterminate('Running tests...', 0, testsTotal, { stage: 'tests', reset: true });

                const baseFirst = [];
                const baseAll = [];
                const gemFirst = [];
                const gemAll = [];
                const chatFirst = [];
                const chatAll = [];
                let baseResult = '';
                let gemResult = '';
                let chatResult = '';

                let ticksDone = 0;

                const runMeasuredSolver = async (opts) => {
                    const title = String(opts && opts.title ? opts.title : 'Solver');
                    const spec = opts && opts.spec ? opts.spec : null;
                    const labelFirst = String(opts && opts.labelFirst ? opts.labelFirst : 'first');
                    const argsFirst = Array.isArray(opts && opts.argsFirst ? opts.argsFirst : null) ? opts.argsFirst : [];
                    const labelAll = String(opts && opts.labelAll ? opts.labelAll : 'all');
                    const argsAll = Array.isArray(opts && opts.argsAll ? opts.argsAll : null) ? opts.argsAll : [];
                    const timesFirst = Array.isArray(opts && opts.timesFirst ? opts.timesFirst : null) ? opts.timesFirst : null;
                    const timesAll = Array.isArray(opts && opts.timesAll ? opts.timesAll : null) ? opts.timesAll : null;
                    const captureAll = typeof (opts && opts.captureAll) === 'function' ? opts.captureAll : null;
                    const recycleEvery = Math.max(0, Math.floor(Number(opts && opts.recycleEveryIterations ? opts.recycleEveryIterations : 0)));

                    if (!spec || !spec.id) throw new Error(`Invalid wasm spec for ${title}`);
                    if (!timesFirst || !timesAll) throw new Error(`Invalid timing arrays for ${title}`);

                    let mod = await loadFreshModule(spec, `Loading ${title} WASM...`, ticksDone, testsTotal, 'tests');

                    const isTrapError = (error) => {
                        const msg = error && error.message ? String(error.message) : String(error);
                        const lower = msg.toLowerCase();
                        return lower.includes('function signature mismatch') ||
                            lower.includes('memory access out of bounds') ||
                            lower.includes('out of bounds memory access') ||
                            lower.includes('unreachable');
                    };

                    const runStepMeasured = async (iter, stepLabel, args, times, captureStdout = null) => {
                        for (let attempt = 0; attempt < 2; attempt++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            const t0 = runTimerNowMs();
                            try {
                                const res = await runEmscriptenMain(mod, args);
                                const t1 = runTimerNowMs();
                                times.push(Math.max(0, t1 - t0));
                                if (captureStdout) {
                                    const stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                                    try { captureStdout(stdout); } catch (_) {}
                                }
                                return null;
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                const canRecover = isTrapError(error) && attempt === 0;
                                if (!canRecover) {
                                    throw new Error(`Iteration ${iter + 1}/${safeIterations} - ${stepLabel}: ${msg}`);
                                }

                                mod = null;
                                unloadModule(spec);
                                await delay(0, abortSignal);
                                if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                                mod = await loadFreshModule(spec, `Recovering ${title} WASM...`, ticksDone, testsTotal, 'tests');
                            }
                        }
                        return null;
                    };
                    try {
                        for (let iter = 0; iter < safeIterations; iter++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

                            if (recycleEvery > 0 && iter > 0 && (iter % recycleEvery) === 0) {
                                mod = null;
                                unloadModule(spec);
                                await delay(0, abortSignal);
                                if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                                mod = await loadFreshModule(spec, `Refreshing ${title} WASM (${iter}/${safeIterations})...`, ticksDone, testsTotal, 'tests');
                            }

                            progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                            const firstRes = await runStepMeasured(iter, labelFirst, argsFirst, timesFirst);
                            if (firstRes && firstRes.status === 'aborted') return firstRes;
                            ticksDone++;
                            progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                            await delay(0, abortSignal);

                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

                            progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                            const allRes = await runStepMeasured(iter, labelAll, argsAll, timesAll, captureAll);
                            if (allRes && allRes.status === 'aborted') return allRes;
                            ticksDone++;
                            progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                            await delay(0, abortSignal);
                        }
                    } finally {
                        mod = null;
                        unloadModule(spec);
                    }
                    return null;
                };

                const baselineRun = await runMeasuredSolver({
                    title: 'VF3 baseline',
                    spec: baselineSpec,
                    labelFirst: 'VF3 baseline first',
                    argsFirst: ['-r', '0', '-F', patternFsPath, targetFsPath],
                    labelAll: 'VF3 baseline all',
                    argsAll: ['-r', '0', patternFsPath, targetFsPath],
                    timesFirst: baseFirst,
                    timesAll: baseAll,
                    recycleEveryIterations: baselineRecycleEveryIterations,
                    captureAll: (stdout) => {
                        const line = parseFirstLine(stdout);
                        baseResult = parseFirstToken(line) || line;
                    }
                });
                if (baselineRun && baselineRun.status === 'aborted') return baselineRun;

                const geminiRun = await runMeasuredSolver({
                    title: 'VF3 Gemini',
                    spec: geminiSpec,
                    labelFirst: 'VF3 Gemini first',
                    argsFirst: ['--first-only', patternFsPath, targetFsPath],
                    labelAll: 'VF3 Gemini all',
                    argsAll: [patternFsPath, targetFsPath],
                    timesFirst: gemFirst,
                    timesAll: gemAll,
                    recycleEveryIterations: safeIterations >= 250 ? 200 : 0,
                    captureAll: (stdout) => {
                        gemResult = parseFirstLine(stdout);
                    }
                });
                if (geminiRun && geminiRun.status === 'aborted') return geminiRun;

                const chatgptRun = await runMeasuredSolver({
                    title: 'VF3 ChatGPT',
                    spec: chatgptSpec,
                    labelFirst: 'VF3 ChatGPT first',
                    argsFirst: ['--first-only', patternFsPath, targetFsPath],
                    labelAll: 'VF3 ChatGPT all',
                    argsAll: [patternFsPath, targetFsPath],
                    timesFirst: chatFirst,
                    timesAll: chatAll,
                    recycleEveryIterations: safeIterations >= 250 ? 200 : 0,
                    captureAll: (stdout) => {
                        chatResult = parseFirstLine(stdout);
                    }
                });
                if (chatgptRun && chatgptRun.status === 'aborted') return chatgptRun;

                progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

                const sBaseFirst = calcStatsMs(baseFirst);
                const sBaseAll = calcStatsMs(baseAll);
                const sGemFirst = calcStatsMs(gemFirst);
                const sGemAll = calcStatsMs(gemAll);
                const sChatFirst = calcStatsMs(chatFirst);
                const sChatAll = calcStatsMs(chatAll);

                const lines = [];
                const addSection = (title, result, firstStats, allStats) => {
                    lines.push(`[${title}]`);
                    lines.push(result || '(No output)');
                    lines.push(`Warmup: ${safeWarmup}`);
                    lines.push(`Iterations: ${safeIterations}`);
                    if (firstStats && allStats) {
                        lines.push(...formatStatsMsFirstAll('Runtime (ms): ', firstStats, allStats));
                    }
                    lines.push('');
                };

                addSection('VF3 baseline', baseResult, sBaseFirst, sBaseAll);
                addSection('VF3 Gemini', gemResult, sGemFirst, sGemAll);
                addSection('VF3 ChatGPT', chatResult, sChatFirst, sChatAll);

                return { status: 'success', output: lines.join('\n') };
            } finally {
                // Drop cached modules at the end of each local run to keep memory stable between runs.
                try { invalidateEmscriptenModule(baselineSpec.id); } catch (_) {}
                try { invalidateEmscriptenModule(geminiSpec.id); } catch (_) {}
                try { invalidateEmscriptenModule(chatgptSpec.id); } catch (_) {}
            }
        }

        let localWasmKernelPromise = null;
        async function getLocalWasmKernel() {
            if (localWasmKernelPromise) return localWasmKernelPromise;
            localWasmKernelPromise = (async () => {
                if (!('WebAssembly' in window)) {
                    throw new Error('WebAssembly is not supported in this browser.');
                }

                // Minimal WASM module exporting `work(n: i32) -> i32`.
                // Used as a lightweight local runner kernel (warmups + iterations) without GitHub Actions.
                const bytes = new Uint8Array([
                    0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
                    0x01, 0x06, 0x01, 0x60, 0x01, 0x7f, 0x01, 0x7f,
                    0x03, 0x02, 0x01, 0x00,
                    0x07, 0x08, 0x01, 0x04, 0x77, 0x6f, 0x72, 0x6b, 0x00, 0x00,
                    0x0a, 0x2d, 0x01, 0x2b, 0x01, 0x02, 0x7f,
                    0x41, 0x00, 0x21, 0x01,
                    0x41, 0x00, 0x21, 0x02,
                    0x02, 0x40,
                    0x03, 0x40,
                    0x20, 0x01,
                    0x20, 0x00,
                    0x4f,
                    0x0d, 0x01,
                    0x20, 0x02,
                    0x20, 0x01,
                    0x6a,
                    0x21, 0x02,
                    0x20, 0x01,
                    0x41, 0x01,
                    0x6a,
                    0x21, 0x01,
                    0x0c, 0x00,
                    0x0b,
                    0x0b,
                    0x20, 0x02,
                    0x0b
                ]);

                const { instance } = await WebAssembly.instantiate(bytes);
                if (!instance || !instance.exports || typeof instance.exports.work !== 'function') {
                    throw new Error('Failed to initialize local WebAssembly runner.');
                }
                return instance.exports;
            })();
            return localWasmKernelPromise;
        }

        function computeLocalWorkN(algoId, unitIndex, fileMetaList = []) {
            const unit = Math.max(0, Number(unitIndex) || 0);
            const algo = String(algoId || '');
            const bytes = Array.isArray(fileMetaList)
                ? fileMetaList.reduce((sum, m) => sum + (Number.isFinite(Number(m && m.bytes)) ? Number(m.bytes) : 0), 0)
                : 0;

            const algoFactor = algo === 'vf3' ? 3 : (algo === 'glasgow' ? 2 : 1);
            const base = Math.max(25000, Math.min(2500000, Math.floor(bytes / 3)));
            return base * algoFactor * (1 + (unit % 3));
        }

        async function runAlgorithmLocally(runCtx, algoId, iterations, warmup) {
            const algoKey = String(algoId || '');
            if (algoKey === 'vf3') {
                try {
                    return await runVf3Locally(runCtx, iterations, warmup);
                } catch (error) {
                    const msg = error && error.message ? error.message : String(error);
                    if (msg.includes('Failed to load script') || msg.includes('WASM factory not found')) {
                        throw new Error('Local WASM modules not found. Run the "Build WASM Modules" workflow to generate them.');
                    }
                    throw error;
                }
            }

            if (algoKey === 'dijkstra') {
                try {
                    return await runDijkstraLocally(runCtx, iterations, warmup);
                } catch (error) {
                    const msg = error && error.message ? error.message : String(error);
                    if (msg.includes('Failed to load script') || msg.includes('WASM factory not found')) {
                        throw new Error('Local WASM modules not found. Run the "Build WASM Modules" workflow to generate them.');
                    }
                    throw error;
                }
            }

            const kernel = await getLocalWasmKernel();
            const testsPerIter = getTestsPerIteration(algoId);
            const setupTotal = Math.max(1, 1 + (Math.max(0, Number(warmup) || 0) * testsPerIter));

            const metaList = (config.selectedFiles || []).map(f => {
                const m = dataFileMeta && f && f.path && dataFileMeta[f.path] ? dataFileMeta[f.path] : null;
                return { path: f && f.path ? String(f.path) : '', bytes: m && Number.isFinite(Number(m.size)) ? Number(m.size) : 0 };
            });

            let setupDone = 0;
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(0, Math.floor(Number(iterations) || 0));
            const testsTotal = safeIterations * testsPerIter;
            const localStartMs = runTimerNowMs();

            progressReset(algoId, safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter
            });

            setupDone = 1;
            progressSetDeterminate('Setting up Testing Environment', setupDone, setupTotal, { stage: 'setup', reset: true });

            // Warmup phase (fills the bar the first time)
            let warmupUnitsDone = 0;
            for (let i = 0; i < safeWarmup; i++) {
                for (let unit = 0; unit < testsPerIter; unit++) {
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                    kernel.work(computeLocalWorkN(algoId, unit, metaList));
                    warmupUnitsDone++;
                    const completed = Math.min(setupTotal, 1 + warmupUnitsDone);
                    if (completed !== setupDone) {
                        setupDone = completed;
                        progressSetDeterminate('Warming up...', setupDone, setupTotal, { stage: 'setup' });
                    }
                    if ((warmupUnitsDone % 25) === 0) {
                        await delay(0, runCtx && runCtx.abortController ? runCtx.abortController.signal : null);
                    }
                }
            }

            // Tests phase (reset to 0% and fill again)
            progressSetDeterminate('Running tests...', 0, testsTotal, { stage: 'tests', reset: true });
            let testsDone = 0;
            for (let iter = 0; iter < safeIterations; iter++) {
                for (let unit = 0; unit < testsPerIter; unit++) {
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                    kernel.work(computeLocalWorkN(algoId, unit, metaList));
                    testsDone++;
                    if ((testsDone % 10) === 0 || testsDone === testsTotal) {
                        progressSetDeterminate('Running tests...', testsDone, testsTotal, { stage: 'tests' });
                    }
                    if ((testsDone % 50) === 0) {
                        await delay(0, runCtx && runCtx.abortController ? runCtx.abortController.signal : null);
                    }
                }
            }

            const localElapsedMs = runTimerNowMs() - localStartMs;
            progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

            return {
                status: 'success',
                output: [
                    `[${algoId.toUpperCase()} Local]`,
                    `Warmup: ${safeWarmup}`,
                    `Iterations: ${safeIterations}`,
                    `Runtime (ms): ${Math.max(0, localElapsedMs).toFixed(1)}`,
                    `Work units: ${testsTotal}`,
                    '',
                    'Note: Local mode currently runs a lightweight WebAssembly kernel for quick UI testing.'
                ].join('\n')
            };
        }

