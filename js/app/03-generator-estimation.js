        function getTestsPerIteration(algoId) {
            const algo = String(algoId || '');
            if (algo === 'dijkstra') return 2;
            if (algo === 'glasgow' || algo === 'vf3' || algo === 'subgraph') return 6;
            return 1;
        }

        function readIterationsInput() {
            const iterationsEl = document.getElementById('iterations');
            const raw = iterationsEl ? String(iterationsEl.value || '').trim() : '';
            const parsed = parseInt(raw, 10);
            return Number.isFinite(parsed) && parsed >= 1 ? parsed : 1;
        }

        function readWarmupInput() {
            const warmupEl = document.getElementById('warmup');
            const raw = warmupEl ? String(warmupEl.value || '').trim() : '';
            const parsed = parseInt(raw, 10);
            if (!Number.isFinite(parsed) || parsed < 0) return 0;
            return parsed > 50 ? 50 : parsed;
        }

        function parseSummaryInputs(summary) {
            if (!summary || typeof summary !== 'object') return {};
            const inputs = summary.inputs && typeof summary.inputs === 'object' ? summary.inputs : {};
            return {
                input_mode: inputs.input_mode || summary.input_mode || '',
                n: Number.isFinite(Number(inputs.n)) ? Number(inputs.n) : null,
                k: Number.isFinite(Number(inputs.k)) ? Number(inputs.k) : null,
                density: Number.isFinite(Number(inputs.density)) ? Number(inputs.density) : null,
                input_files: inputs.input_files || summary.input_files || ''
            };
        }

        function extractPerIterationTotalMs(summary) {
            if (!summary || typeof summary !== 'object') return null;
            const algo = String(summary.algorithm || '');
            const timings = summary.timings_ms || {};
            const take = (key) => Number.isFinite(Number(timings[key])) ? Number(timings[key]) : 0;
            let total = 0;
            if (algo === 'dijkstra') {
                if (!Number.isFinite(Number(timings.baseline)) || !Number.isFinite(Number(timings.llm))) {
                    return null;
                }
                total = take('baseline') + take('llm');
            } else if (algo === 'glasgow') {
                const required = ['first','all','gemini_first','gemini_all','chatgpt_first','chatgpt_all'];
                if (required.some(k => !Number.isFinite(Number(timings[k])))) return null;
                total =
                    take('first') + take('all') +
                    take('gemini_first') + take('gemini_all') +
                    take('chatgpt_first') + take('chatgpt_all');
            } else if (algo === 'vf3') {
                const required = ['baseline_first','baseline_all','gemini_first','gemini_all','chatgpt_first','chatgpt_all'];
                if (required.some(k => !Number.isFinite(Number(timings[k])))) return null;
                total =
                    take('baseline_first') + take('baseline_all') +
                    take('gemini_first') + take('gemini_all') +
                    take('chatgpt_first') + take('chatgpt_all');
            }
            return total > 0 ? total : null;
        }

        function scoreHistoryMatch(target, candidate) {
            const dn = Math.abs((candidate.n || 0) - (target.n || 0)) / Math.max(1, target.n || 1);
            const dk = (target.k != null && candidate.k != null)
                ? Math.abs(candidate.k - target.k) / Math.max(1, target.k)
                : 0.5;
            const dd = (target.density != null && candidate.density != null)
                ? Math.abs(candidate.density - target.density) / Math.max(0.01, target.density)
                : 0.5;
            return dn + dk + dd;
        }

        async function fetchHistoricalSummaries(limit = 30) {
            const workflowId = await getRunAlgorithmWorkflowId();
            if (!workflowId) return [];
            let runs = [];
            try {
                runs = await listWorkflowRuns(workflowId, config.ref || 'main', limit);
            } catch (_) {
                return [];
            }
            const summaries = [];
            for (const run of runs) {
                if (!run || !run.id || run.status !== 'completed') continue;
                try {
                    const data = await apiRequest(`/actions/runs/${run.id}/artifacts`);
                    const artifactsRaw = (data && Array.isArray(data.artifacts)) ? data.artifacts : [];
                    const artifacts = artifactsRaw.filter(item => item && !item.expired);
                    const match = artifacts.find(item => item.name === 'algorithm-result');
                    if (!match) continue;
                    const buffer = await downloadArtifactZip(match);
                    const json = await extractResultJsonFromZip(buffer);
                    if (json) summaries.push(json);
                } catch (_) {
                    continue;
                }
                if (summaries.length >= limit) break;
            }
            return summaries;
        }

        async function estimateFromHistory(algoId, nVal, kVal, densityVal) {
            if (!config.token) return null;
            const target = { n: nVal, k: kVal, density: densityVal };
            const summaries = await fetchHistoricalSummaries(40);
            if (!summaries.length) return null;

            const candidates = [];
            for (const summary of summaries) {
                if (!summary || summary.status !== 'success') continue;
                if (String(summary.algorithm || '') !== String(algoId || '')) continue;
                const inputs = parseSummaryInputs(summary);
                if (inputs.input_mode !== 'generate') continue;
                if (!Number.isFinite(inputs.n) || !Number.isFinite(inputs.density)) continue;
                if ((algoId === 'vf3' || algoId === 'glasgow' || algoId === 'subgraph') && !Number.isFinite(inputs.k)) continue;
                const score = scoreHistoryMatch(target, inputs);
                const perIter = extractPerIterationTotalMs(summary);
                if (!Number.isFinite(perIter) || perIter <= 0) continue;
                candidates.push({ score, perIter });
            }

            if (!candidates.length) return null;
            candidates.sort((a, b) => a.score - b.score);
            const top = candidates.slice(0, 5);
            let totalWeight = 0;
            let weighted = 0;
            for (const item of top) {
                const weight = 1 / (1 + item.score);
                weighted += item.perIter * weight;
                totalWeight += weight;
            }
            if (!totalWeight) return null;
            const perIterMs = weighted / totalWeight;
            return { perIterMs, samples: top.length };
        }

        let generatorEstimateRequestId = 0;

        async function updateGeneratorEstimate() {
            const estimateEl = document.getElementById('generator-estimate');
            if (!estimateEl) return;
            if (getInputMode() !== 'generate') {
                estimateEl.hidden = true;
                estimateEl.textContent = '';
                return;
            }
            const nRaw = String(config.generator.n || '').trim();
            const kRaw = String(config.generator.k || '').trim();
            const densityRaw = String(config.generator.density || '').trim();
            const needsK = isGraphPairAlgorithm(config.selectedAlgorithm);

            const hasAnyInput = nRaw !== '' || (needsK && kRaw !== '');
            if (!hasAnyInput) {
                estimateEl.hidden = true;
                estimateEl.textContent = '';
                return;
            }

            const reasons = [];
            const nVal = parseInt(nRaw, 10);
            const kVal = parseInt(kRaw, 10);
            const dVal = parseFloat(densityRaw);

            if (!nRaw) {
                reasons.push('N is required');
            } else if (!Number.isFinite(nVal) || nVal < 2) {
                reasons.push('N must be >= 2');
            }

            if (!densityRaw) {
                reasons.push('Density is required');
            } else if (!Number.isFinite(dVal) || dVal <= 0 || dVal > 1) {
                reasons.push('Density must be between 0 and 1');
            }

            if (needsK) {
                if (!kRaw) {
                    reasons.push('k is required');
                } else if (!Number.isFinite(kVal) || kVal < 1) {
                    reasons.push('k must be >= 1');
                } else if (Number.isFinite(nVal) && kVal >= nVal) {
                    reasons.push('k must be smaller than N');
                }
            }

            if (reasons.length > 0) {
                const reason = reasons[0];
                const perRunLine = `Estimated time per run: N/A (${reason})`;
                const totalLine = `Estimated end-to-end time: N/A (${reason})`;
                estimateEl.innerHTML = `${escapeHtml(perRunLine)}<br>${escapeHtml(totalLine)}`;
                estimateEl.hidden = false;
                return;
            }

            const requestId = ++generatorEstimateRequestId;
            const densityVal = dVal;
            const iterations = readIterationsInput();
            const warmup = readWarmupInput();
            const testsPerIter = getTestsPerIteration(config.selectedAlgorithm);

            const heuristicPerRun = estimateHeuristicPerRunMs(config.selectedAlgorithm, nRaw, kRaw, densityRaw);
            if (!Number.isFinite(heuristicPerRun) || heuristicPerRun <= 0) {
                estimateEl.textContent = '';
                estimateEl.hidden = true;
                return;
            }

            const heuristicPerIter = heuristicPerRun * testsPerIter;
            const roughPerRun = formatDurationMs(heuristicPerRun);
            const roughTotal = formatDurationMs(heuristicPerIter * Math.max(1, (iterations + warmup)));
            const roughRunLine = `Estimated time per run: ${roughPerRun} (rough)`;
            const roughTotalLine = `Estimated end-to-end time: ${roughTotal} (rough)`;
            estimateEl.innerHTML = `${escapeHtml(roughRunLine)}<br>${escapeHtml(roughTotalLine)}`;
            estimateEl.hidden = false;

            if (!config.token) return;

            let perIterMs = null;
            try {
                const history = await estimateFromHistory(config.selectedAlgorithm, nVal, kVal, densityVal);
                if (history && Number.isFinite(history.perIterMs)) {
                    perIterMs = history.perIterMs;
                }
            } catch (_) {}

            if (requestId !== generatorEstimateRequestId) return;
            if (!Number.isFinite(perIterMs) || perIterMs <= 0) return;

            const perRunMs = perIterMs / Math.max(1, testsPerIter);
            const totalMs = perIterMs * Math.max(1, (iterations + warmup));
            const perRunText = formatDurationMs(perRunMs);
            const totalText = formatDurationMs(totalMs);

            const perRunLine = `Estimated time per run: ${perRunText} (fine)`;
            const totalLine = `Estimated end-to-end time: ${totalText} (fine)`;
            estimateEl.innerHTML = `${escapeHtml(perRunLine)}<br>${escapeHtml(totalLine)}`;
            estimateEl.hidden = false;
        }

