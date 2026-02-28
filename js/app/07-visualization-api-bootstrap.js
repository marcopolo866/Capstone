        function clearVisualization() {
            const panel = document.getElementById('graph-panel');
            const note = document.getElementById('graph-note');
            const canvas = document.getElementById('graph-canvas');
            const patternPanel = document.getElementById('pattern-panel');
            const patternNote = document.getElementById('pattern-note');
            const patternCanvas = document.getElementById('pattern-canvas');
            const graphCenterBtn = document.getElementById('graph-center-btn');
            const patternCenterBtn = document.getElementById('pattern-center-btn');
            const solutionControls = document.getElementById('solution-controls');
            const solutionWarning = document.getElementById('solution-warning');
            const iterationControls = document.getElementById('iteration-controls');
            const iterationLabel = document.getElementById('iteration-label');
            const iterationPrev = document.getElementById('iteration-prev-btn');
            const iterationNext = document.getElementById('iteration-next-btn');
            if (graphInstance) {
                graphInstance.destroy();
                graphInstance = null;
            }
            if (patternInstance) {
                patternInstance.destroy();
                patternInstance = null;
            }
            graphHoverEdgeId = null;
            patternHoverEdgeId = null;
            visSolutions = [];
            currentSolutionIndex = 0;
            visIterations = [];
            currentIterationIndex = 0;
            if (canvas) canvas.innerHTML = '';
            if (patternCanvas) patternCanvas.innerHTML = '';
            if (note) note.textContent = '';
            if (patternNote) patternNote.textContent = '';
            if (graphCenterBtn) graphCenterBtn.disabled = true;
            if (patternCenterBtn) patternCenterBtn.disabled = true;
            if (solutionControls) solutionControls.hidden = true;
            if (solutionWarning) solutionWarning.hidden = true;
            if (iterationControls) iterationControls.hidden = true;
            if (iterationLabel) iterationLabel.textContent = 'Iteration 1';
            if (iterationPrev) iterationPrev.disabled = true;
            if (iterationNext) iterationNext.disabled = true;
            if (panel) panel.hidden = true;
            if (patternPanel) patternPanel.hidden = true;
        }

        function centerGraphInstance(instance) {
            if (!instance) return;
            instance.resize();
            instance.fit();
            instance.center();
        }

        function centerMainGraph() {
            centerGraphInstance(graphInstance);
        }

        function centerPatternGraph() {
            centerGraphInstance(patternInstance);
        }

        function updateIterationControls() {
            const label = document.getElementById('iteration-label');
            const prevBtn = document.getElementById('iteration-prev-btn');
            const nextBtn = document.getElementById('iteration-next-btn');
            const controls = document.getElementById('iteration-controls');
            const total = visIterations.length;
            if (!controls) return;
            controls.hidden = false;
            const safeTotal = total || 1;
            const displayIndex = Math.min(Math.max(currentIterationIndex, 0), safeTotal - 1);
            if (label) label.textContent = `Iteration ${displayIndex + 1} of ${safeTotal}`;
            const disabled = safeTotal <= 1;
            if (prevBtn) prevBtn.disabled = disabled || displayIndex <= 0;
            if (nextBtn) nextBtn.disabled = disabled || displayIndex >= safeTotal - 1;
        }

        function showPreviousIteration() {
            if (currentIterationIndex <= 0) return;
            applyIteration(currentIterationIndex - 1);
        }

        function showNextIteration() {
            if (currentIterationIndex >= visIterations.length - 1) return;
            applyIteration(currentIterationIndex + 1);
        }

        function applyIteration(index) {
            if (!visIterations.length) return;
            const safeIndex = Math.min(Math.max(0, index), visIterations.length - 1);
            currentIterationIndex = safeIndex;
            renderVisualizationCurrent();
        }

        function updateSolutionControls() {
            const label = document.getElementById('solution-label');
            const prevBtn = document.getElementById('solution-prev-btn');
            const nextBtn = document.getElementById('solution-next-btn');
            const controls = document.getElementById('solution-controls');
            const total = visSolutions.length;
            if (!controls) return;
            if (!total) {
                controls.hidden = true;
                return;
            }
            controls.hidden = false;
            if (label) {
                const current = visSolutions[currentSolutionIndex] || null;
                const name = current && typeof current.name === 'string' ? current.name.trim() : '';
                label.textContent = name
                    ? `Solution ${currentSolutionIndex + 1} of ${total}: ${name}`
                    : `Solution ${currentSolutionIndex + 1} of ${total}`;
            }
            if (prevBtn) prevBtn.disabled = currentSolutionIndex <= 0;
            if (nextBtn) nextBtn.disabled = currentSolutionIndex >= total - 1;
        }

        function applySolution(index) {
            if (!graphInstance || !visSolutions.length) return;
            const solution = visSolutions[index];
            if (!solution) return;
            graphInstance.elements('.highlight-node').removeClass('highlight-node');
            graphInstance.elements('.highlight-edge').removeClass('highlight-edge');
            if (Array.isArray(solution.highlight_nodes)) {
                for (const nodeId of solution.highlight_nodes) {
                    const node = graphInstance.getElementById(String(nodeId));
                    if (node) node.addClass('highlight-node');
                }
            }
            if (Array.isArray(solution.highlight_edges)) {
                for (const edgeId of solution.highlight_edges) {
                    const edge = graphInstance.getElementById(String(edgeId));
                    if (edge) edge.addClass('highlight-edge');
                }
            }
            if (patternInstance && Array.isArray(solution.mapping)) {
                for (let i = 0; i < solution.mapping.length; i++) {
                    const node = patternInstance.getElementById(`p${i}`);
                    if (!node) continue;
                    const label = solution.mapping[i];
                    node.data('label', label === null || label === undefined ? String(i) : String(label));
                }
            }
            currentSolutionIndex = index;
            updateSolutionControls();
        }

        function showPreviousSolution() {
            if (currentSolutionIndex <= 0) return;
            applySolution(currentSolutionIndex - 1);
        }

        function showNextSolution() {
            if (currentSolutionIndex >= visSolutions.length - 1) return;
            applySolution(currentSolutionIndex + 1);
        }

        function attachHoverHighlight(cy, hoverState) {
            if (!cy) return;
            cy.on('mouseover', 'edge', (evt) => {
                const edge = evt.target;
                if (!edge) return;
                const edgeId = edge.id();
                if (hoverState.current && hoverState.current !== edgeId) {
                    const prev = cy.getElementById(hoverState.current);
                    if (prev) {
                        prev.removeClass('hover-edge');
                        prev.connectedNodes().removeClass('hover-node');
                    }
                }
                hoverState.current = edgeId;
                edge.addClass('hover-edge');
                edge.connectedNodes().addClass('hover-node');
            });
            cy.on('mouseout', 'edge', (evt) => {
                const edge = evt.target;
                if (!edge) return;
                const edgeId = edge.id();
                if (hoverState.current && hoverState.current !== edgeId) {
                    return;
                }
                edge.removeClass('hover-edge');
                edge.connectedNodes().removeClass('hover-node');
                hoverState.current = null;
            });
        }

        function renderVisualization(result) {
            const baseVis = result && result.visualization ? result.visualization : null;
            const iterations = baseVis && Array.isArray(baseVis.visualization_iterations)
                ? baseVis.visualization_iterations
                : (baseVis ? [baseVis] : []);
            if (!iterations.length) {
                clearVisualization();
                return;
            }
            visIterations = iterations;
            currentIterationIndex = 0;
            updateIterationControls();
            renderVisualizationCurrent();
        }

        function renderVisualizationCurrent() {
            const panel = document.getElementById('graph-panel');
            const note = document.getElementById('graph-note');
            const canvas = document.getElementById('graph-canvas');
            const patternPanel = document.getElementById('pattern-panel');
            const patternNote = document.getElementById('pattern-note');
            const patternCanvas = document.getElementById('pattern-canvas');
            if (!panel || !canvas || !window.cytoscape) return;

            const vis = visIterations[currentIterationIndex];
            if (!vis || !Array.isArray(vis.nodes) || !Array.isArray(vis.edges)) {
                clearVisualization();
                return;
            }
            if (graphInstance) {
                graphInstance.destroy();
                graphInstance = null;
            }
            if (patternInstance) {
                patternInstance.destroy();
                patternInstance = null;
            }
            canvas.innerHTML = '';
            if (patternCanvas) patternCanvas.innerHTML = '';
            panel.hidden = false;
            if (patternPanel) patternPanel.hidden = true;
            const graphCenterBtn = document.getElementById('graph-center-btn');
            const patternCenterBtn = document.getElementById('pattern-center-btn');
            const solutionWarning = document.getElementById('solution-warning');

            const elements = [];
            for (const node of vis.nodes) {
                elements.push(node);
            }
            for (const edge of vis.edges) {
                elements.push(edge);
            }

            graphInstance = cytoscape({
                container: canvas,
                elements,
                style: [
                    {
                        selector: 'node',
                        style: {
                            'background-color': '#7aa6c2',
                            'label': 'data(label)',
                            'color': '#1f2d3d',
                            'font-size': 10,
                            'text-outline-width': 2,
                            'text-outline-color': '#ffffff',
                            'text-valign': 'center',
                            'text-halign': 'center',
                            'width': 16,
                            'height': 16
                        }
                    },
                    {
                        selector: 'edge',
                        style: {
                            'line-color': '#cbd2d9',
                            'width': 1,
                            'curve-style': 'straight',
                            'target-arrow-shape': 'none'
                        }
                    },
                    {
                        selector: '.highlight-node',
                        style: {
                            'background-color': '#e45756',
                            'width': 20,
                            'height': 20
                        }
                    },
                    {
                        selector: '.highlight-edge',
                        style: {
                            'line-color': '#e45756',
                            'width': 3
                        }
                    },
                    {
                        selector: '.hover-edge',
                        style: {
                            'line-color': '#f2a444',
                            'width': 3
                        }
                    },
                    {
                        selector: '.hover-node',
                        style: {
                            'background-color': '#f2a444',
                            'width': 20,
                            'height': 20
                        }
                    }
                ],
                layout: {
                    name: 'grid',
                    avoidOverlap: true,
                    spacingFactor: 1.2,
                    fit: true
                }
            });

            if (Array.isArray(vis.highlight_nodes)) {
                for (const nodeId of vis.highlight_nodes) {
                    const node = graphInstance.getElementById(String(nodeId));
                    if (node) node.addClass('highlight-node');
                }
            }
            if (Array.isArray(vis.highlight_edges)) {
                for (const edgeId of vis.highlight_edges) {
                    const edge = graphInstance.getElementById(String(edgeId));
                    if (edge) edge.addClass('highlight-edge');
                }
            }
            attachHoverHighlight(graphInstance, { current: graphHoverEdgeId, set current(val) { graphHoverEdgeId = val; }, get current() { return graphHoverEdgeId; } });
            if (graphCenterBtn) graphCenterBtn.disabled = false;

            visSolutions = Array.isArray(vis.solutions) ? vis.solutions : [];
            if (!visSolutions.length && (Array.isArray(vis.highlight_nodes) || Array.isArray(vis.highlight_edges))) {
                visSolutions = [{
                    mapping: Array.isArray(vis.pattern_nodes) ? vis.pattern_nodes : [],
                    highlight_nodes: vis.highlight_nodes || [],
                    highlight_edges: vis.highlight_edges || []
                }];
            }
            currentSolutionIndex = 0;
            if (solutionWarning) {
                solutionWarning.hidden = !vis.no_solutions;
            }

            const noteParts = [];
            if (Number.isFinite(Number(vis.node_count)) && Number.isFinite(Number(vis.edge_count))) {
                noteParts.push(`Nodes: ${vis.node_count}, Edges: ${vis.edge_count}`);
            }
            if (vis.truncated) {
                noteParts.push('Showing up to 4000 nodes and 4000 edges.');
            }
            note.textContent = noteParts.join(' ');

            if (patternPanel && patternCanvas) {
                const patternCount = Number.isFinite(Number(vis.pattern_node_count))
                    ? Number(vis.pattern_node_count)
                    : (Array.isArray(vis.pattern_nodes) ? vis.pattern_nodes.length : 0);
                const patternEdges = Array.isArray(vis.pattern_edges) ? vis.pattern_edges : [];
                const hasPattern = patternCount > 0 && patternEdges.length > 0;
                if (!hasPattern) {
                    patternPanel.hidden = true;
                } else {
                    const patternElements = [];
                    for (let i = 0; i < patternCount; i++) {
                        patternElements.push({ data: { id: `p${i}`, label: String(i) } });
                    }
                    for (const edge of patternEdges) {
                        if (!Array.isArray(edge) || edge.length < 2) continue;
                        const a = Number(edge[0]);
                        const b = Number(edge[1]);
                        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
                        const eid = `p${a}-p${b}`;
                        patternElements.push({ data: { id: eid, source: `p${a}`, target: `p${b}` } });
                    }
                    patternPanel.hidden = false;
                    patternInstance = cytoscape({
                        container: patternCanvas,
                        elements: patternElements,
                    style: [
                        {
                            selector: 'node',
                            style: {
                                'background-color': '#7aa6c2',
                                'label': 'data(label)',
                                'color': '#1f2d3d',
                                'font-size': 10,
                                'text-outline-width': 2,
                                'text-outline-color': '#ffffff',
                                'text-valign': 'center',
                                'text-halign': 'center',
                                'width': 16,
                                'height': 16
                            }
                        },
                        {
                            selector: 'edge',
                            style: {
                                'line-color': '#cbd2d9',
                                'width': 1,
                                'curve-style': 'straight',
                                'target-arrow-shape': 'none'
                            }
                        },
                        {
                            selector: '.hover-edge',
                            style: {
                                'line-color': '#f2a444',
                                'width': 3
                            }
                        },
                        {
                            selector: '.hover-node',
                            style: {
                                'background-color': '#f2a444',
                                'width': 20,
                                'height': 20
                            }
                        }
                    ],
                    layout: {
                        name: 'circle',
                        fit: true,
                        padding: 20
                    }
                });
                attachHoverHighlight(patternInstance, { current: patternHoverEdgeId, set current(val) { patternHoverEdgeId = val; }, get current() { return patternHoverEdgeId; } });
                if (patternCenterBtn) patternCenterBtn.disabled = false;
                if (patternNote) {
                    patternNote.textContent = `Nodes: ${patternCount}, Edges: ${patternEdges.length}`;
                }
                requestAnimationFrame(() => {
                    if (patternInstance) {
                        patternInstance.resize();
                        patternInstance.fit();
                    }
                });
                }
            }
            if (visSolutions.length) {
                updateIterationControls();
                applySolution(0);
            } else {
                updateIterationControls();
                updateSolutionControls();
            }
            requestAnimationFrame(() => {
                if (graphInstance) {
                    graphInstance.resize();
                    graphInstance.fit();
                }
            });
        }
        
        function buildRequestHeaders(options = {}) {
            const { useAuth = true, accept = 'application/vnd.github.v3+json' } = options;
            const headers = {
                'Accept': accept,
                'X-GitHub-Api-Version': '2022-11-28'
            };
            if (useAuth && config.token) {
                const lower = config.token.toLowerCase();
                const useBearer = lower.startsWith('github_pat_') || lower.startsWith('ghs_') || lower.startsWith('ghu_');
                headers['Authorization'] = useBearer
                    ? `Bearer ${config.token}`
                    : `token ${config.token}`;
            }
            return headers;
        }

        async function apiRequest(endpoint, method = 'GET', body = null, options = {}) {
            const { useAuth = true } = options;
            const headers = buildRequestHeaders({ useAuth });
            
            const requestOptions = {
                method: method,
                headers: headers
            };
            
            if (body) {
                headers['Content-Type'] = 'application/json';
                requestOptions.body = JSON.stringify(body);
            }
            
            const url = `https://api.github.com/repos/${config.owner}/${config.repo}${endpoint}`;
            const response = await fetch(url, requestOptions);
                        
            if (!response.ok) {
                let responseText = '';
                try {
                    responseText = await response.text();
                } catch (_) {}
                throw new Error(`GitHub API error: ${response.status} ${response.statusText} | endpoint=${endpoint} method=${method} ref=${config.ref || 'main'} | body=${responseText}`);
            }
            
            if (method === 'POST' && (response.status === 204 || response.status === 202)) {
                return { success: true };
            }

            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                return await response.json();
            }

            const text = await response.text();
            return text ? { text } : { success: true };
        }

        function reportDebugError(context, error, meta = {}) {
            const detail = (error && error.message) ? error.message : String(error);
            const metaStr = Object.entries(meta).map(([k,v]) => `${k}=${v}`).join(', ');
            const debugMsg = `[${context}] ${detail}${metaStr ? ' | ' + metaStr : ''}`;
            showStatus(debugMsg, 'error');
            if (console && console.error) {
                console.error(debugMsg, error);
            }
        }

        let statusClearTimerId = null;

        function showStatus(message, type) {
            const container = document.getElementById('status-message');
            if (!container) return;
            if (statusClearTimerId) {
                clearTimeout(statusClearTimerId);
                statusClearTimerId = null;
            }
            container.innerHTML = `<div class="${type}">${escapeHtml(message)}</div>`;
            statusClearTimerId = setTimeout(() => {
                container.innerHTML = '';
                statusClearTimerId = null;
            }, 5000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        window.addEventListener('load', () => {
            updateInputModeVisibility();
            updateGeneratorFieldsForAlgorithm();
            updateGeneratorEstimate();
            updateRunButton();
        });
