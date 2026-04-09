        function clearOutput() {
            document.getElementById('output').textContent = 'Output cleared.';
            document.getElementById('status-badge').innerHTML = '';
            progressClear();
            clearCharts();
        }

        function clearCharts() {
            const charts = document.getElementById('charts');
            if (runtimeChartInstance) {
                runtimeChartInstance.destroy();
                runtimeChartInstance = null;
            }
            if (memoryChartInstance) {
                memoryChartInstance.destroy();
                memoryChartInstance = null;
            }
            lastResult = null;
            if (charts) charts.hidden = true;
            const exportRow = document.getElementById('export-row');
            if (exportRow) {
                exportRow.hidden = true;
                exportRow.replaceChildren();
            }
            const statsPanel = document.getElementById('stats-panel');
            const statsGrid = document.getElementById('stats-grid');
            if (statsGrid) statsGrid.replaceChildren();
            if (statsPanel) statsPanel.hidden = true;
            clearVisualization();
        }

        function normalizeVersionMetrics(result) {
            const timings = result && result.timings_ms ? result.timings_ms : {};
            const timingsStdev = result && result.timings_ms_stdev ? result.timings_ms_stdev : {};
            const memory = result && result.memory_kb ? result.memory_kb : {};
            const memoryStdev = result && result.memory_kb_stdev ? result.memory_kb_stdev : {};

            const pickNumber = (raw) => {
                if (raw === null || raw === undefined || raw === '') return null;
                const num = Number(raw);
                return Number.isFinite(num) ? num : null;
            };

            const pickValue = (keys, source) => {
                for (const key of keys) {
                    if (!source || !Object.prototype.hasOwnProperty.call(source, key)) continue;
                    const value = pickNumber(source[key]);
                    if (value !== null) return value;
                }
                return null;
            };

            const pickPair = (keys, valueSource, stdevSource) => {
                for (const key of keys) {
                    if (!valueSource || !Object.prototype.hasOwnProperty.call(valueSource, key)) continue;
                    const value = pickNumber(valueSource[key]);
                    if (value === null) continue;
                    const stdevRaw = stdevSource && Object.prototype.hasOwnProperty.call(stdevSource, key)
                        ? stdevSource[key]
                        : null;
                    const stdev = pickNumber(stdevRaw);
                    return { value, stdev };
                }
                return { value: null, stdev: null };
            };

            const parseGlasgowBaselineFromOutput = (output) => {
                if (!output) return null;
                const start = output.indexOf('[Glasgow Subgraph Solver]');
                if (start < 0) return null;
                const rest = output.slice(start);
                const nextHeader = rest.slice(1).search(/\n\[/);
                const section = nextHeader >= 0 ? rest.slice(0, nextHeader + 1) : rest;
                const firstMatch = section.match(/Runtime \(ms\):\s*first\s+median=\s*([0-9.]+)/i);
                const allMatch = section.match(/\n\s*all\s+median=\s*([0-9.]+)/i);
                if (!firstMatch || !allMatch) return null;
                const first = Number(firstMatch[1]);
                const all = Number(allMatch[1]);
                if (!Number.isFinite(first) || !Number.isFinite(all)) return null;
                return { first, all };
            };

            const runtime = {
                benchmark: {
                    first: pickPair(['baseline_first', 'first'], timings, timingsStdev),
                    all: pickPair(['baseline_all', 'baseline', 'all'], timings, timingsStdev)
                },
                chatgpt: {
                    first: pickPair(['chatgpt_first'], timings, timingsStdev),
                    all: pickPair(['chatgpt_all', 'llm'], timings, timingsStdev)
                },
                gemini: {
                    first: pickPair(['gemini_first'], timings, timingsStdev),
                    all: pickPair(['gemini_all'], timings, timingsStdev)
                }
            };

            if (result && result.algorithm === 'glasgow') {
                const baseline = parseGlasgowBaselineFromOutput(result.output);
                if (baseline) {
                    if (!Number.isFinite(runtime.benchmark.first.value)) {
                        runtime.benchmark.first = { value: baseline.first, stdev: null };
                    }
                    if (!Number.isFinite(runtime.benchmark.all.value)) {
                        runtime.benchmark.all = { value: baseline.all, stdev: null };
                    }
                }
            }

            const mem = {
                benchmark: pickPair(['baseline_all', 'all'], memory, memoryStdev),
                chatgpt: pickPair(['chatgpt_all', 'llm'], memory, memoryStdev),
                gemini: pickPair(['gemini_all'], memory, memoryStdev)
            };

            if (result && result.algorithm === 'dijkstra') {
                runtime.benchmark.all = pickPair(['baseline', 'baseline_all', 'all'], timings, timingsStdev);
                runtime.chatgpt.all = pickPair(['chatgpt', 'llm', 'chatgpt_all'], timings, timingsStdev);
                runtime.gemini.all = pickPair(['gemini', 'gemini_all'], timings, timingsStdev);
                mem.benchmark = pickPair(['baseline', 'baseline_all', 'all'], memory, memoryStdev);
                mem.chatgpt = pickPair(['chatgpt', 'llm', 'chatgpt_all'], memory, memoryStdev);
                mem.gemini = pickPair(['gemini', 'gemini_all'], memory, memoryStdev);
            }

            return { runtime, memory: mem };
        }

        function buildDynamicVariantRows(result) {
            if (!result || typeof result !== 'object') return [];
            const variantMeta = Array.isArray(result.variant_metadata) ? result.variant_metadata : null;
            if (!variantMeta || !variantMeta.length) return [];
            const timings = result && result.timings_ms ? result.timings_ms : {};
            const timingsStdev = result && result.timings_ms_stdev ? result.timings_ms_stdev : {};
            const memory = result && result.memory_kb ? result.memory_kb : {};
            const memoryStdev = result && result.memory_kb_stdev ? result.memory_kb_stdev : {};

            const toNum = (raw) => {
                if (raw === null || raw === undefined || raw === '') return null;
                const num = Number(raw);
                return Number.isFinite(num) ? num : null;
            };
            const pick = (obj, key) => {
                if (!obj || !key || !Object.prototype.hasOwnProperty.call(obj, key)) return null;
                return toNum(obj[key]);
            };
            const rows = [];
            for (const raw of variantMeta) {
                const entry = (raw && typeof raw === 'object') ? raw : null;
                if (!entry) continue;
                const label = String(entry.label || entry.variant_id || '').trim();
                if (!label) continue;

                const timingKeys = (entry.timing_keys && typeof entry.timing_keys === 'object') ? entry.timing_keys : null;
                const memoryKeys = (entry.memory_keys && typeof entry.memory_keys === 'object') ? entry.memory_keys : null;
                const timingKeySingle = String(entry.timing_key || '').trim();
                const memoryKeySingle = String(entry.memory_key || '').trim();

                const tFirstKey = timingKeys ? String(timingKeys.first || '').trim() : '';
                const tAllKey = timingKeys ? String(timingKeys.all || '').trim() : '';
                const mFirstKey = memoryKeys ? String(memoryKeys.first || '').trim() : '';
                const mAllKey = memoryKeys ? String(memoryKeys.all || '').trim() : '';

                const runtimeFirst = pick(timings, tFirstKey);
                const runtimeFirstStdev = pick(timingsStdev, tFirstKey);
                const runtimeAll = pick(timings, tAllKey) ?? pick(timings, timingKeySingle);
                const runtimeAllStdev = pick(timingsStdev, tAllKey) ?? pick(timingsStdev, timingKeySingle);
                const memoryFirst = pick(memory, mFirstKey);
                const memoryFirstStdev = pick(memoryStdev, mFirstKey);
                const memoryAll = pick(memory, mAllKey) ?? pick(memory, memoryKeySingle);
                const memoryAllStdev = pick(memoryStdev, mAllKey) ?? pick(memoryStdev, memoryKeySingle);

                rows.push({
                    label,
                    runtimeFirst,
                    runtimeFirstStdev,
                    runtimeAll,
                    runtimeAllStdev,
                    memoryFirst,
                    memoryFirstStdev,
                    memoryAll,
                    memoryAllStdev
                });
            }
            return rows;
        }

        let runtimeChartInstance = null;
        let memoryChartInstance = null;
        let lastResult = null; // stored for export
        let graphInstance = null;
        let patternInstance = null;
        let graphHoverEdgeId = null;
        let patternHoverEdgeId = null;
        let visSolutions = [];
        let currentSolutionIndex = 0;
        let visIterations = [];
        let currentIterationIndex = 0;

        const errorBarsPlugin = {
            id: 'errorBars',
            afterDatasetsDraw(chart, args, pluginOptions) {
                const { ctx, scales } = chart;
                const yScale = scales && scales.y ? scales.y : null;
                if (!yScale) return;
                chart.data.datasets.forEach((dataset, datasetIndex) => {
                    const meta = chart.getDatasetMeta(datasetIndex);
                    if (!meta || meta.type !== 'bar') return;
                    const errors = dataset.errorBars || [];
                    meta.data.forEach((bar, index) => {
                        const err = errors[index];
                        const value = dataset.data[index];
                        if (!Number.isFinite(err) || !Number.isFinite(value)) return;
                        const yTop = yScale.getPixelForValue(value + err);
                        const yBottom = yScale.getPixelForValue(Math.max(0, value - err));
                        const x = bar.x;
                        const capWidth = Number.isFinite(pluginOptions?.capWidth) ? pluginOptions.capWidth : 8;
                        const lineWidth = Number.isFinite(pluginOptions?.lineWidth) ? pluginOptions.lineWidth : 1;
                        const color = Array.isArray(dataset.borderColor)
                            ? dataset.borderColor[index]
                            : (dataset.borderColor || '#333');
                        ctx.save();
                        ctx.strokeStyle = color || '#333';
                        ctx.lineWidth = lineWidth;
                        ctx.beginPath();
                        ctx.moveTo(x, yTop);
                        ctx.lineTo(x, yBottom);
                        ctx.moveTo(x - capWidth / 2, yTop);
                        ctx.lineTo(x + capWidth / 2, yTop);
                        ctx.moveTo(x - capWidth / 2, yBottom);
                        ctx.lineTo(x + capWidth / 2, yBottom);
                        ctx.stroke();
                        ctx.restore();
                    });
                });
            }
        };

        function renderBarChart(canvasId, data, unitLabel, title) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || !window.Chart) return null;

            const labels = data.map(item => item.label);
            const values = data.map(item => (Number.isFinite(Number(item.value)) ? Number(item.value) : null));
            const errors = data.map(item => {
                const value = Number.isFinite(Number(item.value)) ? Number(item.value) : null;
                if (!Number.isFinite(value)) return null;
                return Number.isFinite(Number(item.stdev)) ? Number(item.stdev) : 0;
            });
            const palette = ['#1f77b4', '#e45756', '#54a24b', '#b279a2', '#f28e2b', '#59a14f'];
            const borderPalette = ['#1b6aa1', '#c84544', '#3f8f3b', '#9b6790', '#d07a25', '#4c8b4f'];
            const backgroundColor = labels.map((_, index) => palette[index % palette.length]);
            const borderColor = labels.map((_, index) => borderPalette[index % borderPalette.length]);

            return new Chart(canvas, {
                type: 'bar',
                plugins: [errorBarsPlugin],
                data: {
                    labels,
                    datasets: [
                        {
                            label: title,
                            data: values,
                            errorBars: errors,
                            backgroundColor,
                            borderColor,
                            borderWidth: 1,
                            borderRadius: 6
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: context => {
                                    const v = context.raw;
                                    if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
                                    const err = context.dataset && context.dataset.errorBars
                                        ? context.dataset.errorBars[context.dataIndex]
                                        : null;
                                    if (Number.isFinite(err) && err > 0) {
                                        return `${v.toFixed(2)} +/- ${err.toFixed(2)} ${unitLabel}`;
                                    }
                                    return `${v.toFixed(2)} ${unitLabel}`;
                                }
                            }
                        }
                        ,
                        errorBars: {
                            capWidth: 10,
                            lineWidth: 1
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: value => `${value} ${unitLabel}`
                            }
                        }
                    }
                }
            });
        }

        function renderGroupedBarChart(canvasId, labels, datasets, unitLabel) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || !window.Chart) return null;

            const chartDatasets = datasets.map((dataset) => ({
                label: dataset.label,
                data: dataset.values,
                errorBars: dataset.errors,
                backgroundColor: dataset.backgroundColor,
                borderColor: dataset.borderColor,
                borderWidth: 1,
                borderRadius: 6,
                minBarLength: Number.isFinite(dataset.minBarLength) ? dataset.minBarLength : 2
            }));

            return new Chart(canvas, {
                type: 'bar',
                plugins: [errorBarsPlugin],
                data: {
                    labels,
                    datasets: chartDatasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            labels: {
                                usePointStyle: true,
                                pointStyle: 'rectRounded'
                            }
                        },
                        tooltip: {
                            callbacks: {
                                label: context => {
                                    const v = context.raw;
                                    if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
                                    const err = context.dataset && context.dataset.errorBars
                                        ? context.dataset.errorBars[context.dataIndex]
                                        : null;
                                    if (Number.isFinite(err) && err > 0) {
                                        return `${context.dataset.label}: ${v.toFixed(2)} +/- ${err.toFixed(2)} ${unitLabel}`;
                                    }
                                    return `${context.dataset.label}: ${v.toFixed(2)} ${unitLabel}`;
                                }
                            }
                        },
                        errorBars: {
                            capWidth: 10,
                            lineWidth: 1
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                display: false
                            }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: value => `${value} ${unitLabel}`
                            }
                        }
                    }
                }
            });
        }

        function triggerDownload(filename, content, mimeType) {
            const blob = new Blob([content], { type: mimeType });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        function extractSeedUsed(result) {
            if (!result || typeof result !== 'object') return null;
            const candidates = [
                result.inputs && Object.prototype.hasOwnProperty.call(result.inputs, 'seed')
                    ? result.inputs.seed
                    : undefined,
                result.seed,
                result.visualization && Object.prototype.hasOwnProperty.call(result.visualization, 'seed')
                    ? result.visualization.seed
                    : undefined
            ];
            for (const candidate of candidates) {
                if (candidate === null || candidate === undefined || candidate === '') continue;
                return candidate;
            }
            return null;
        }

        function extractIterationSeeds(result) {
            const seeds = result && result.inputs && Array.isArray(result.inputs.iteration_seeds)
                ? result.inputs.iteration_seeds
                : null;
            return seeds ? seeds.slice() : null;
        }

        function extractSolutionCountsPerIteration(result) {
            if (result && result.solution_counts_per_iteration && typeof result.solution_counts_per_iteration === 'object') {
                return result.solution_counts_per_iteration;
            }
            const output = result && typeof result.output === 'string' ? result.output : '';
            if (!output.trim()) return null;

            const bySection = {};
            const lines = output.split(/\r?\n/);
            let currentSection = '';

            const parseCountTokens = (raw) => {
                const cleaned = String(raw || '').trim();
                if (!cleaned) return [];
                return cleaned
                    .split(',')
                    .map((token) => token.trim())
                    .filter((token) => token.length > 0)
                    .map((token) => {
                        if (/^na$/i.test(token)) return null;
                        const value = Number(token);
                        return Number.isFinite(value) ? value : null;
                    });
            };

            for (let i = 0; i < lines.length; i++) {
                const line = String(lines[i] || '');
                const sectionMatch = line.match(/^\[([^\]]+)\]/);
                if (sectionMatch) {
                    currentSection = sectionMatch[1].trim();
                }
                if (!currentSection) continue;

                const startMatch = line.match(/^Solution counts:\s*\[(.*)$/i);
                if (!startMatch) continue;

                let collected = startMatch[1] || '';
                while (!collected.includes(']') && i + 1 < lines.length) {
                    i += 1;
                    collected += ` ${String(lines[i] || '').trim()}`;
                }
                const endIdx = collected.indexOf(']');
                const inside = endIdx >= 0 ? collected.slice(0, endIdx) : collected;
                const parsed = parseCountTokens(inside);
                bySection[currentSection] = parsed;
            }

            return Object.keys(bySection).length ? bySection : null;
        }

        function formatStatNumber(value, decimals = 4) {
            if (!Number.isFinite(Number(value))) return 'n/a';
            return Number(value).toFixed(decimals);
        }

        function renderStatisticalTests(result) {
            const statsPanel = document.getElementById('stats-panel');
            const statsHost = document.getElementById('stats-grid');
            if (!statsPanel || !statsHost) return;
            statsHost.replaceChildren();

            const block = result && result.statistical_tests && typeof result.statistical_tests === 'object'
                ? result.statistical_tests
                : null;
            const rows = block && Array.isArray(block.pairs) ? block.pairs : [];
            if (!rows.length) {
                statsPanel.hidden = true;
                return;
            }

            const alphaRaw = block && Number.isFinite(Number(block.alpha)) ? Number(block.alpha) : 0.05;
            const alpha = alphaRaw > 0 ? alphaRaw : 0.05;
            const tableWrap = document.createElement('div');
            tableWrap.className = 'stats-table-wrap';
            const table = document.createElement('table');
            table.className = 'stats-table';

            const thead = document.createElement('thead');
            const headRow = document.createElement('tr');
            [
                'Variant',
                'Baseline',
                'N',
                'p-value',
                'Significance',
                'Direction',
                'Mean Delta (ms)',
                '95% CI Delta (ms)',
                'Hedges g',
                "Cliff's delta",
                'Mode'
            ].forEach((label) => {
                const th = document.createElement('th');
                th.textContent = label;
                headRow.appendChild(th);
            });
            thead.appendChild(headRow);
            table.appendChild(thead);

            const tbody = document.createElement('tbody');
            let inserted = 0;
            let significantCount = 0;
            let insufficientCount = 0;

            for (const raw of rows) {
                const row = raw && typeof raw === 'object' ? raw : null;
                if (!row) continue;
                const variantLabel = String(row.variant_label || row.variant_id || 'Variant').trim();
                const baselineLabel = String(row.baseline_label || row.baseline_variant_id || 'Baseline').trim();
                const mode = String(row.mode || 'single').trim();
                const n = Number.isFinite(Number(row.n)) ? Number(row.n) : 0;

                const paired = row.paired_t_test && typeof row.paired_t_test === 'object' ? row.paired_t_test : {};
                const effects = row.effect_sizes && typeof row.effect_sizes === 'object' ? row.effect_sizes : {};
                const ci = row.delta_ci_95_ms && typeof row.delta_ci_95_ms === 'object' ? row.delta_ci_95_ms : {};
                const pValue = paired.p_value_two_sided;
                const meanDelta = row.mean_delta_ms;
                const direction = String(row.direction || 'n/a');
                const ciLow = ci.low;
                const ciHigh = ci.high;
                const pFinite = Number.isFinite(Number(pValue));
                let significanceClass = 'stats-significance-ns';
                let significanceText = `Not significant (p >= ${alpha.toFixed(3)})`;
                if (n < 2 || !pFinite) {
                    significanceClass = 'stats-significance-insufficient';
                    significanceText = 'Insufficient data';
                    insufficientCount += 1;
                } else if (Number(pValue) < alpha) {
                    significanceClass = 'stats-significance-significant';
                    significanceText = `Significant (p < ${alpha.toFixed(3)})`;
                    significantCount += 1;
                }

                const tr = document.createElement('tr');
                tr.className = significanceClass;

                const cells = [
                    variantLabel,
                    baselineLabel,
                    String(n),
                    formatStatNumber(pValue, 6),
                    significanceText,
                    direction,
                    formatStatNumber(meanDelta, 3),
                    `[${formatStatNumber(ciLow, 3)}, ${formatStatNumber(ciHigh, 3)}]`,
                    formatStatNumber(effects.hedges_g, 4),
                    formatStatNumber(effects.cliffs_delta, 4),
                    mode
                ];
                cells.forEach((value) => {
                    const td = document.createElement('td');
                    td.textContent = value;
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
                inserted += 1;
            }

            if (!inserted) {
                statsPanel.hidden = true;
                return;
            }

            table.appendChild(tbody);
            tableWrap.appendChild(table);
            statsHost.appendChild(tableWrap);

            const blurb = statsPanel.querySelector('.stats-blurb');
            if (blurb) {
                const nonSignificantCount = Math.max(0, inserted - significantCount - insufficientCount);
                blurb.textContent = [
                    `Comparisons: ${inserted}.`,
                    `Significant (p < ${alpha.toFixed(3)}): ${significantCount}.`,
                    `Not significant: ${nonSignificantCount}.`,
                    `Insufficient: ${insufficientCount}.`
                ].join(' ');
            }

            const legend = statsPanel.querySelector('.stats-legend');
            if (legend) {
                legend.innerHTML = [
                    '<span class="stats-legend-item stats-significance-significant"><strong>Significant</strong>: p-value below alpha</span>',
                    '<span class="stats-legend-item stats-significance-ns"><strong>Not significant</strong>: p-value at/above alpha</span>',
                    '<span class="stats-legend-item stats-significance-insufficient"><strong>Insufficient</strong>: too few samples or missing p-value</span>'
                ].join('');
            }

            statsPanel.hidden = false;
        }

        function renderExportButtons(result) {
            const exportRow = document.getElementById('export-row');
            if (!exportRow || !result) return;

            const algo = result.algorithm || 'unknown';
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            const baseName = `${algo}-results-${timestamp}`;

            const jsonBtn = document.createElement('button');
            jsonBtn.className = 'btn btn-primary';
            jsonBtn.textContent = 'Download JSON';
            jsonBtn.type = 'button';
            jsonBtn.addEventListener('click', () => {
                const pickDefined = (value) => (value === undefined ? null : value);
                const seedUsed = extractSeedUsed(result);
                const iterationSeeds = extractIterationSeeds(result);
                const solutionCounts = extractSolutionCountsPerIteration(result);
                const inputs = (result && result.inputs && typeof result.inputs === 'object') ? result.inputs : {};
                const matchCounts = (result && result.match_counts && typeof result.match_counts === 'object')
                    ? result.match_counts
                    : null;
                const payload = {
                    algorithm: result.algorithm || null,
                    status: result.status || null,
                    error: result.error || null,
                    timestamp: result.timestamp || null,
                    request_id: result.request_id || null,
                    output: result.output || null,
                    timings_ms: result.timings_ms || {},
                    timings_ms_stdev: result.timings_ms_stdev || {},
                    memory_kb: result.memory_kb || {},
                    memory_kb_stdev: result.memory_kb_stdev || {},
                    memory_metric_unit: result.memory_metric_unit || 'kB',
                    memory_metric_label: result.memory_metric_label || 'Memory',
                    inputs,
                    iterations: result.iterations || null,
                    warmup: pickDefined(result.warmup),
                    run_duration_ms: pickDefined(result.run_duration_ms),
                    subgraph_phase: result.subgraph_phase || null,
                    match_counts: matchCounts,
                    statistical_tests: result.statistical_tests || null,
                    seed_used: seedUsed,
                    iteration_seeds: iterationSeeds,
                    solution_counts_per_iteration: solutionCounts,
                    exported_at: new Date().toISOString()
                };
                triggerDownload(`${baseName}.json`, JSON.stringify(payload, null, 2), 'application/json');
            });

            const csvBtn = document.createElement('button');
            csvBtn.className = 'btn btn-primary';
            csvBtn.textContent = 'Download CSV';
            csvBtn.type = 'button';
            csvBtn.addEventListener('click', () => {
                const escapeCsv = (value) => {
                    const text = value === null || value === undefined ? '' : String(value);
                    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
                };
                const addCsvRow = (metric, variant, value, stdev = '', unit = '') => {
                    rows.push(
                        `${escapeCsv(metric)},${escapeCsv(variant)},${escapeCsv(value)},${escapeCsv(stdev)},${escapeCsv(unit)}`
                    );
                };
                const flattenObjectRows = (metric, rootLabel, obj) => {
                    const walk = (path, value) => {
                        if (value && typeof value === 'object' && !Array.isArray(value)) {
                            for (const key of Object.keys(value)) {
                                walk(path ? `${path}.${key}` : String(key), value[key]);
                            }
                            return;
                        }
                        const serialized = Array.isArray(value) ? JSON.stringify(value) : value;
                        const unit = Number.isFinite(Number(serialized)) ? 'count' : '';
                        addCsvRow(metric, path || rootLabel, serialized, '', unit);
                    };
                    if (obj && typeof obj === 'object') walk(rootLabel, obj);
                };
                const seedUsed = extractSeedUsed(result);
                const iterationSeeds = extractIterationSeeds(result);
                const solutionCounts = extractSolutionCountsPerIteration(result);
                const inputs = (result && result.inputs && typeof result.inputs === 'object') ? result.inputs : {};
                const rows = ['metric,variant,value,stdev,unit'];
                const timings = result.timings_ms || {};
                const timingsStdev = result.timings_ms_stdev || {};
                const memory = result.memory_kb || {};
                const memoryStdev = result.memory_kb_stdev || {};

                addCsvRow('meta', 'status', result.status || null);
                addCsvRow('meta', 'error', result.error || null);
                addCsvRow('meta', 'timestamp', result.timestamp || null);
                addCsvRow('meta', 'request_id', result.request_id || null);
                addCsvRow('meta', 'output', result.output || null);
                addCsvRow('meta', 'subgraph_phase', result.subgraph_phase || null);
                addCsvRow('meta', 'exported_at', new Date().toISOString());
                addCsvRow('meta', 'seed_used', seedUsed);
                addCsvRow('run_context', 'iterations', result.iterations || null, '', 'count');
                addCsvRow('run_context', 'warmup', result.warmup === undefined ? null : result.warmup, '', 'count');
                addCsvRow(
                    'run_context',
                    'run_duration_ms',
                    result.run_duration_ms === undefined ? null : result.run_duration_ms,
                    '',
                    'ms'
                );
                for (const key of Object.keys(inputs)) {
                    if (key === 'iteration_seeds') continue;
                    const value = inputs[key];
                    const serialized = Array.isArray(value) ? JSON.stringify(value) : value;
                    addCsvRow('input_context', key, serialized);
                }
                if (Array.isArray(iterationSeeds)) {
                    for (let i = 0; i < iterationSeeds.length; i++) {
                        addCsvRow('iteration_seed', `iter_${i + 1}`, iterationSeeds[i]);
                    }
                }
                if (solutionCounts && typeof solutionCounts === 'object') {
                    for (const section of Object.keys(solutionCounts)) {
                        const counts = Array.isArray(solutionCounts[section]) ? solutionCounts[section] : [];
                        for (let i = 0; i < counts.length; i++) {
                            addCsvRow('solution_count', `${section} [iter ${i + 1}]`, counts[i], '', 'count');
                        }
                    }
                }
                flattenObjectRows('correctness', 'match_counts', result.match_counts);
                flattenObjectRows('statistics', 'statistical_tests', result.statistical_tests);
                for (const key of Object.keys(timings)) {
                    const val = timings[key];
                    const sd = timingsStdev[key] !== undefined ? timingsStdev[key] : '';
                    addCsvRow('runtime_ms', key, val, sd, 'ms');
                }
                for (const key of Object.keys(memory)) {
                    const val = memory[key];
                    const sd = memoryStdev[key] !== undefined ? memoryStdev[key] : '';
                    addCsvRow('memory', key, val, sd, result.memory_metric_unit || 'kB');
                }
                triggerDownload(`${baseName}.csv`, rows.join('\n'), 'text/csv');
            });

            exportRow.replaceChildren(jsonBtn, csvBtn);
            exportRow.hidden = false;
        }

        function renderCharts(result) {
            const charts = document.getElementById('charts');
            if (!charts) return;
            const memoryUnit = (result && typeof result.memory_metric_unit === 'string' && result.memory_metric_unit.trim())
                ? result.memory_metric_unit.trim()
                : 'kB';
            const memoryTitle = (result && typeof result.memory_metric_label === 'string' && result.memory_metric_label.trim())
                ? result.memory_metric_label.trim()
                : 'Memory';

            const dynamicRows = buildDynamicVariantRows(result);
            if (dynamicRows.length) {
                const hasRuntimeFirst = dynamicRows.some(row => Number.isFinite(Number(row.runtimeFirst)));
                const runtimeLabels = dynamicRows.map(row => row.label);
                const runtimeSingle = dynamicRows.map(row => ({
                    label: row.label,
                    value: Number.isFinite(Number(row.runtimeAll)) ? Number(row.runtimeAll) : row.runtimeFirst,
                    stdev: Number.isFinite(Number(row.runtimeAll)) ? row.runtimeAllStdev : row.runtimeFirstStdev
                })).filter(item => Number.isFinite(Number(item.value)));
                const runtimeFirstVals = dynamicRows.map(row => (Number.isFinite(Number(row.runtimeFirst)) ? Number(row.runtimeFirst) : null));
                const runtimeFirstErrs = dynamicRows.map(row => {
                    const value = Number.isFinite(Number(row.runtimeFirst)) ? Number(row.runtimeFirst) : null;
                    if (!Number.isFinite(value)) return null;
                    return Number.isFinite(Number(row.runtimeFirstStdev)) ? Number(row.runtimeFirstStdev) : 0;
                });
                const runtimeAllVals = dynamicRows.map(row => {
                    if (Number.isFinite(Number(row.runtimeAll))) return Number(row.runtimeAll);
                    if (Number.isFinite(Number(row.runtimeFirst))) return Number(row.runtimeFirst);
                    return null;
                });
                const runtimeAllErrs = dynamicRows.map(row => {
                    const v = Number.isFinite(Number(row.runtimeAll)) ? Number(row.runtimeAll) : row.runtimeFirst;
                    if (!Number.isFinite(Number(v))) return null;
                    if (Number.isFinite(Number(row.runtimeAllStdev))) return Number(row.runtimeAllStdev);
                    if (Number.isFinite(Number(row.runtimeFirstStdev))) return Number(row.runtimeFirstStdev);
                    return 0;
                });

                const memoryData = dynamicRows.map(row => {
                    const value = Number.isFinite(Number(row.memoryAll)) ? Number(row.memoryAll) : row.memoryFirst;
                    const stdev = Number.isFinite(Number(row.memoryAllStdev)) ? Number(row.memoryAllStdev) : row.memoryFirstStdev;
                    return { label: row.label, value, stdev };
                }).filter(item => Number.isFinite(Number(item.value)));

                if (runtimeChartInstance) runtimeChartInstance.destroy();
                if (memoryChartInstance) memoryChartInstance.destroy();

                if (hasRuntimeFirst) {
                    runtimeChartInstance = renderGroupedBarChart('runtime-chart', runtimeLabels, [
                        {
                            label: 'First',
                            values: runtimeFirstVals,
                            errors: runtimeFirstErrs,
                            backgroundColor: '#7aa6c2',
                            borderColor: '#5e869f'
                        },
                        {
                            label: 'All',
                            values: runtimeAllVals,
                            errors: runtimeAllErrs,
                            backgroundColor: '#e5a06a',
                            borderColor: '#c98453'
                        }
                    ], 'ms');
                } else {
                    runtimeChartInstance = runtimeSingle.length
                        ? renderBarChart('runtime-chart', runtimeSingle, 'ms', 'Runtime')
                        : null;
                }

                memoryChartInstance = memoryData.length
                    ? renderBarChart('memory-chart', memoryData, memoryUnit, memoryTitle)
                    : null;
                lastResult = result;
                charts.hidden = false;
                renderStatisticalTests(result);
                renderExportButtons(result);
                return;
            }

            if (result && result.algorithm === 'subgraph') {
                const timings = result.timings_ms || {};
                const timingsStdev = result.timings_ms_stdev || {};
                const memory = result.memory_kb || {};
                const memoryStdev = result.memory_kb_stdev || {};

                const pickNumber = (raw) => {
                    if (raw === null || raw === undefined || raw === '') return null;
                    const num = Number(raw);
                    return Number.isFinite(num) ? num : null;
                };

                const pickPair = (keys, valueSource, stdevSource) => {
                    for (const key of keys) {
                        if (!valueSource || !Object.prototype.hasOwnProperty.call(valueSource, key)) continue;
                        const value = pickNumber(valueSource[key]);
                        if (value === null) continue;
                        const stdevRaw = stdevSource && Object.prototype.hasOwnProperty.call(stdevSource, key)
                            ? stdevSource[key]
                            : null;
                        const stdev = pickNumber(stdevRaw);
                        return { value, stdev };
                    }
                    return { value: null, stdev: null };
                };

                const runtimeLabels = ['VF3', '.vf ChatGPT', '.vf Gemini', 'Glasgow', '.lad ChatGPT', '.lad Gemini'];
                const runtimeFirst = [
                    pickPair(['vf3_baseline_first', 'baseline_first'], timings, timingsStdev),
                    pickPair(['vf3_chatgpt_first', 'chatgpt_first'], timings, timingsStdev),
                    pickPair(['vf3_gemini_first', 'gemini_first'], timings, timingsStdev),
                    pickPair(['glasgow_baseline_first', 'glasgow_first', 'first'], timings, timingsStdev),
                    pickPair(['glasgow_chatgpt_first'], timings, timingsStdev),
                    pickPair(['glasgow_gemini_first'], timings, timingsStdev)
                ];
                const runtimeAll = [
                    pickPair(['vf3_baseline_all', 'baseline_all'], timings, timingsStdev),
                    pickPair(['vf3_chatgpt_all', 'chatgpt_all'], timings, timingsStdev),
                    pickPair(['vf3_gemini_all', 'gemini_all'], timings, timingsStdev),
                    pickPair(['glasgow_baseline_all', 'glasgow_all', 'all'], timings, timingsStdev),
                    pickPair(['glasgow_chatgpt_all'], timings, timingsStdev),
                    pickPair(['glasgow_gemini_all'], timings, timingsStdev)
                ];

                const runtimePairs = [...runtimeFirst, ...runtimeAll];
                const hasRuntime = runtimePairs.some(item => Number.isFinite(Number(item.value)));
                const memoryData = [
                    { label: 'VF3', ...pickPair(['vf3_baseline_all', 'baseline_all'], memory, memoryStdev) },
                    { label: '.vf ChatGPT', ...pickPair(['vf3_chatgpt_all', 'chatgpt_all'], memory, memoryStdev) },
                    { label: '.vf Gemini', ...pickPair(['vf3_gemini_all', 'gemini_all'], memory, memoryStdev) },
                    { label: 'Glasgow', ...pickPair(['glasgow_baseline_all', 'glasgow_all', 'all'], memory, memoryStdev) },
                    { label: '.lad ChatGPT', ...pickPair(['glasgow_chatgpt_all'], memory, memoryStdev) },
                    { label: '.lad Gemini', ...pickPair(['glasgow_gemini_all'], memory, memoryStdev) }
                ];
                const hasMemory = memoryData.some(item => Number.isFinite(Number(item.value)));

                if (!hasRuntime && !hasMemory) {
                    clearCharts();
                    return;
                }

                const runtimeDataSets = [
                    {
                        label: 'First',
                        values: runtimeFirst.map(item => (Number.isFinite(Number(item.value)) ? Number(item.value) : null)),
                        errors: runtimeFirst.map(item => {
                            const value = Number.isFinite(Number(item.value)) ? Number(item.value) : null;
                            if (!Number.isFinite(value)) return null;
                            return Number.isFinite(Number(item.stdev)) ? Number(item.stdev) : 0;
                        }),
                        backgroundColor: '#7aa6c2',
                        borderColor: '#5e869f'
                    },
                    {
                        label: 'All',
                        values: runtimeAll.map(item => (Number.isFinite(Number(item.value)) ? Number(item.value) : null)),
                        errors: runtimeAll.map(item => {
                            const value = Number.isFinite(Number(item.value)) ? Number(item.value) : null;
                            if (!Number.isFinite(value)) return null;
                            return Number.isFinite(Number(item.stdev)) ? Number(item.stdev) : 0;
                        }),
                        backgroundColor: '#e5a06a',
                        borderColor: '#c98453'
                    }
                ];

                if (runtimeChartInstance) runtimeChartInstance.destroy();
                if (memoryChartInstance) memoryChartInstance.destroy();
                runtimeChartInstance = renderGroupedBarChart('runtime-chart', runtimeLabels, runtimeDataSets, 'ms');
                memoryChartInstance = hasMemory
                    ? renderBarChart('memory-chart', memoryData, memoryUnit, memoryTitle)
                    : null;
                lastResult = result;
                charts.hidden = false;
                renderStatisticalTests(result);
                renderExportButtons(result);
                return;
            }

            const metrics = normalizeVersionMetrics(result || {});
            const runtimePairs = [
                metrics.runtime.benchmark.first,
                metrics.runtime.benchmark.all,
                metrics.runtime.chatgpt.first,
                metrics.runtime.chatgpt.all,
                metrics.runtime.gemini.first,
                metrics.runtime.gemini.all
            ];
            const hasRuntime = runtimePairs.some(v => Number.isFinite(Number(v.value)));
            const hasMemory = Object.values(metrics.memory).some(v => Number.isFinite(Number(v.value)));

            if (!hasRuntime && !hasMemory) {
                clearCharts();
                return;
            }

            if (result && result.algorithm === 'dijkstra') {
                const pickSingle = (pairAll, pairFirst) => {
                    if (pairAll && Number.isFinite(Number(pairAll.value))) {
                        return { value: pairAll.value, stdev: pairAll.stdev };
                    }
                    if (pairFirst && Number.isFinite(Number(pairFirst.value))) {
                        return { value: pairFirst.value, stdev: pairFirst.stdev };
                    }
                    return { value: null, stdev: null };
                };

                const runtimeData = [
                    { label: 'Benchmark', ...pickSingle(metrics.runtime.benchmark.all, metrics.runtime.benchmark.first) },
                    { label: 'ChatGPT', ...pickSingle(metrics.runtime.chatgpt.all, metrics.runtime.chatgpt.first) },
                    { label: 'Gemini', ...pickSingle(metrics.runtime.gemini.all, metrics.runtime.gemini.first) }
                ].filter(item => Number.isFinite(Number(item.value)));

                const memoryData = [
                    { label: 'Benchmark', value: metrics.memory.benchmark.value, stdev: metrics.memory.benchmark.stdev },
                    { label: 'ChatGPT', value: metrics.memory.chatgpt.value, stdev: metrics.memory.chatgpt.stdev },
                    { label: 'Gemini', value: metrics.memory.gemini.value, stdev: metrics.memory.gemini.stdev }
                ].filter(item => Number.isFinite(Number(item.value)));

                if (runtimeChartInstance) runtimeChartInstance.destroy();
                if (memoryChartInstance) memoryChartInstance.destroy();
                runtimeChartInstance = runtimeData.length
                    ? renderBarChart('runtime-chart', runtimeData, 'ms', 'Runtime')
                    : null;
                memoryChartInstance = memoryData.length
                    ? renderBarChart('memory-chart', memoryData, memoryUnit, memoryTitle)
                    : null;
                lastResult = result;
                charts.hidden = false;
                renderStatisticalTests(result);
                renderExportButtons(result);
                return;
            }

            const runtimeLabels = ['Benchmark', 'ChatGPT', 'Gemini'];
            const runtimeFirst = [
                metrics.runtime.benchmark.first,
                metrics.runtime.chatgpt.first,
                metrics.runtime.gemini.first
            ];
            const runtimeAll = [
                metrics.runtime.benchmark.all,
                metrics.runtime.chatgpt.all,
                metrics.runtime.gemini.all
            ];
            const runtimeDataSets = [
                {
                    label: 'First',
                    values: runtimeFirst.map(item => (Number.isFinite(Number(item.value)) ? Number(item.value) : null)),
                    errors: runtimeFirst.map(item => {
                        const value = Number.isFinite(Number(item.value)) ? Number(item.value) : null;
                        if (!Number.isFinite(value)) return null;
                        return Number.isFinite(Number(item.stdev)) ? Number(item.stdev) : 0;
                    }),
                    backgroundColor: '#7aa6c2',
                    borderColor: '#5e869f'
                },
                {
                    label: 'All',
                    values: runtimeAll.map(item => (Number.isFinite(Number(item.value)) ? Number(item.value) : null)),
                    errors: runtimeAll.map(item => {
                        const value = Number.isFinite(Number(item.value)) ? Number(item.value) : null;
                        if (!Number.isFinite(value)) return null;
                        return Number.isFinite(Number(item.stdev)) ? Number(item.stdev) : 0;
                    }),
                    backgroundColor: '#e5a06a',
                    borderColor: '#c98453'
                }
            ];
            const memoryData = [
                { label: 'Benchmark', value: metrics.memory.benchmark.value, stdev: metrics.memory.benchmark.stdev },
                { label: 'ChatGPT', value: metrics.memory.chatgpt.value, stdev: metrics.memory.chatgpt.stdev },
                { label: 'Gemini', value: metrics.memory.gemini.value, stdev: metrics.memory.gemini.stdev }
            ];

            if (runtimeChartInstance) runtimeChartInstance.destroy();
            if (memoryChartInstance) memoryChartInstance.destroy();
            runtimeChartInstance = renderGroupedBarChart('runtime-chart', runtimeLabels, runtimeDataSets, 'ms');
            memoryChartInstance = hasMemory
                ? renderBarChart('memory-chart', memoryData, memoryUnit, memoryTitle)
                : null;
            lastResult = result;
            charts.hidden = false;
            renderStatisticalTests(result);
            renderExportButtons(result);
        }
