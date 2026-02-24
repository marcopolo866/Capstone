        function clearOutput() {
            document.getElementById('output').textContent = 'Output cleared.';
            document.getElementById('status-badge').innerHTML = '';
            progressClear();
            clearCharts();
        }

        function clearCharts() {
            const charts = document.getElementById('charts');
            const runtime = document.getElementById('runtime-chart');
            const memory = document.getElementById('memory-chart');
            if (runtimeChartInstance) {
                runtimeChartInstance.destroy();
                runtimeChartInstance = null;
            }
            if (memoryChartInstance) {
                memoryChartInstance.destroy();
                memoryChartInstance = null;
            }
            if (runtime) runtime.height = runtime.height;
            if (memory) memory.height = memory.height;
            if (charts) charts.hidden = true;
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

        let runtimeChartInstance = null;
        let memoryChartInstance = null;
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

        function renderCharts(result) {
            const charts = document.getElementById('charts');
            if (!charts) return;

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
                memoryChartInstance = renderBarChart('memory-chart', memoryData, 'kB', 'Memory');
                charts.hidden = false;
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
                    ? renderBarChart('memory-chart', memoryData, 'kB', 'Memory')
                    : null;
                charts.hidden = false;
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
            memoryChartInstance = renderBarChart('memory-chart', memoryData, 'kB', 'Memory');
            charts.hidden = false;
        }

