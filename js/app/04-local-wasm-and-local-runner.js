        function getSelectedRunMode() {
            const selected = document.querySelector('input[name="run-mode"]:checked');
            const raw = selected ? String(selected.value || '').trim().toLowerCase() : 'standard';
            return raw === 'local' ? 'local' : 'standard';
        }

        const localWasmScriptPromises = new Map();
        const localWasmModulePromises = new Map();
        let localWasmWorkerPromise = null;
        let localWasmWorkerDisabled = false;
        let localWasmWorkerRequestSeq = 1;
        let localWasmActiveAbortSignal = null;
        const localWasmWorkerPending = new Map();
        const localWasmWorkerTokensByModuleId = new Map();
        const WASM_MEMORY_METRIC_UNIT = 'KiB';
        const WASM_MEMORY_HEAP_KIND = 'wasm_heap_peak_kib';
        const WASM_MEMORY_HEAP_LABEL = 'WASM Heap Peak';
        const WASM_MEMORY_ALLOCATOR_KIND = 'wasm_allocator_peak_kib';
        const WASM_MEMORY_ALLOCATOR_LABEL = 'WASM Allocator Peak';

        function numberOrNull(value, min = null) {
            const num = Number(value);
            if (!Number.isFinite(num)) return null;
            if (min !== null && num < min) return null;
            return num;
        }

        function getDefaultWasmMemoryMetricInfo() {
            return {
                kind: WASM_MEMORY_HEAP_KIND,
                label: WASM_MEMORY_HEAP_LABEL,
                unit: WASM_MEMORY_METRIC_UNIT
            };
        }

        function normalizeWasmMemorySample(raw) {
            const src = (raw && typeof raw === 'object') ? raw : {};
            const kindRaw = String(src.metricKind || '').trim().toLowerCase();
            const isAllocator = kindRaw === WASM_MEMORY_ALLOCATOR_KIND;
            const valueKiB = numberOrNull(src.valueKiB, 0);
            const heapCapacityKiB = numberOrNull(src.heapCapacityKiB, 0);
            const allocatorPeakKiB = numberOrNull(src.allocatorPeakKiB, 0);
            const allocatorCurrentKiB = numberOrNull(src.allocatorCurrentKiB, 0);
            const allocatorAllocCount = numberOrNull(src.allocatorAllocCount, 0);
            const allocatorFreeCount = numberOrNull(src.allocatorFreeCount, 0);
            const allocatorDroppedRecords = numberOrNull(src.allocatorDroppedRecords, 0);

            const metricKind = isAllocator ? WASM_MEMORY_ALLOCATOR_KIND : WASM_MEMORY_HEAP_KIND;
            const metricLabel = isAllocator ? WASM_MEMORY_ALLOCATOR_LABEL : WASM_MEMORY_HEAP_LABEL;
            const preferredValue = isAllocator
                ? (allocatorPeakKiB !== null ? allocatorPeakKiB : valueKiB)
                : (valueKiB !== null ? valueKiB : heapCapacityKiB);

            return {
                metricKind,
                metricLabel,
                metricUnit: WASM_MEMORY_METRIC_UNIT,
                valueKiB: preferredValue,
                heapCapacityKiB,
                allocatorPeakKiB,
                allocatorCurrentKiB,
                allocatorAllocCount,
                allocatorFreeCount,
                allocatorDroppedRecords
            };
        }

        function makeHeapOnlyWasmMemorySample(heapKiB) {
            return normalizeWasmMemorySample({
                metricKind: WASM_MEMORY_HEAP_KIND,
                valueKiB: numberOrNull(heapKiB, 0),
                heapCapacityKiB: numberOrNull(heapKiB, 0)
            });
        }

        function pickPreferredWasmMemoryMetricInfo(currentInfo, candidateInfo) {
            const current = (currentInfo && typeof currentInfo === 'object') ? currentInfo : null;
            const candidate = (candidateInfo && typeof candidateInfo === 'object') ? candidateInfo : null;
            if (!candidate) return current;
            if (!current) return candidate;
            if (current.kind === WASM_MEMORY_HEAP_KIND && candidate.kind === WASM_MEMORY_ALLOCATOR_KIND) {
                return candidate;
            }
            return current;
        }

        function shouldUseLocalWasmWorker() {
            return !localWasmWorkerDisabled &&
                typeof Worker === 'function' &&
                typeof Blob === 'function' &&
                typeof URL !== 'undefined' &&
                typeof URL.createObjectURL === 'function';
        }

        function localWasmWorkerWarn(message, error) {
            try {
                if (typeof console !== 'undefined' && console && typeof console.warn === 'function') {
                    console.warn('[capstone][local-wasm-worker]', message, error || '');
                }
            } catch (_) {}
        }

        function localWasmWorkerRejectAllPending(error) {
            for (const [requestId, pending] of localWasmWorkerPending.entries()) {
                localWasmWorkerPending.delete(requestId);
                try {
                    pending.reject(error instanceof Error ? error : new Error(String(error || 'Worker failed')));
                } catch (_) {}
            }
        }

        function makeLocalWasmAbortError(message) {
            const error = new Error(String(message || 'Run Aborted'));
            error.name = 'AbortError';
            return error;
        }

        function revokeLocalWasmWorkerUrl(worker) {
            try {
                const url = worker && worker.__capstoneWorkerUrl ? String(worker.__capstoneWorkerUrl) : '';
                if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
                    URL.revokeObjectURL(url);
                }
            } catch (_) {}
        }

        async function teardownLocalWasmWorker(reason, options = {}) {
            const opts = (options && typeof options === 'object') ? options : {};
            const disableWorker = Boolean(opts.disableWorker);
            if (disableWorker) localWasmWorkerDisabled = true;

            const workerPromise = localWasmWorkerPromise;
            localWasmWorkerPromise = null;

            const error = reason instanceof Error
                ? reason
                : new Error(String(reason || 'Local WASM worker stopped'));
            localWasmWorkerRejectAllPending(error);

            const worker = await Promise.resolve(workerPromise).catch(() => null);
            if (worker && typeof worker.terminate === 'function') {
                try { worker.terminate(); } catch (_) {}
                revokeLocalWasmWorkerUrl(worker);
            }
            localWasmWorkerTokensByModuleId.clear();
            localWasmModulePromises.clear();
        }

        async function abortLocalWasmExecution(reason = 'Run Aborted') {
            const abortError = makeLocalWasmAbortError(reason);
            await teardownLocalWasmWorker(abortError, { disableWorker: false });
            // Abort should not permanently disable worker mode; the next run may recreate it.
            localWasmWorkerDisabled = false;
            localWasmModulePromises.clear();
            localWasmWorkerTokensByModuleId.clear();
        }
        if (typeof window !== 'undefined') {
            window.abortLocalWasmExecution = abortLocalWasmExecution;
        }

        function buildLocalWasmWorkerSource() {
            return String.raw`"use strict";
const __capstoneScriptLoads = new Set();
const __capstoneModules = new Map();
let __capstoneNextToken = 1;

function __capNowMs() {
  try {
    if (self.performance && typeof self.performance.now === 'function') return self.performance.now();
  } catch (_) {}
  return Date.now();
}

function __capLoadScriptOnce(url) {
  const u = String(url || '').trim();
  if (!u) throw new Error('Missing script URL');
  if (__capstoneScriptLoads.has(u)) return;
  importScripts(u);
  __capstoneScriptLoads.add(u);
}

function __capMakeCapture() {
  return {
    out: [],
    err: [],
    _runOpts: null,
    _outChars: 0,
    _errChars: 0,
    _mappingLinesKept: 0,
    _mappingLinesDropped: 0,
    _outTruncated: false,
    _errTruncated: false,
    reset() {
      this.out.length = 0;
      this.err.length = 0;
      this._runOpts = null;
      this._outChars = 0;
      this._errChars = 0;
      this._mappingLinesKept = 0;
      this._mappingLinesDropped = 0;
      this._outTruncated = false;
      this._errTruncated = false;
    },
    beginRun(opts) {
      this._runOpts = (opts && typeof opts === 'object') ? opts : null;
      this._outChars = 0;
      this._errChars = 0;
      this._mappingLinesKept = 0;
      this._mappingLinesDropped = 0;
      this._outTruncated = false;
      this._errTruncated = false;
    },
    endRun() {
      this._runOpts = null;
    },
    _pushWithLimit(arr, text, kind) {
      const opts = this._runOpts || null;
      let s = String(text == null ? '' : text);
      if (kind === 'out' && opts) {
        const mappingPolicy = String(opts.mappingLinePolicy || '').trim().toLowerCase();
        if (mappingPolicy && /^mapping\s*:/i.test(s)) {
          if (mappingPolicy === 'drop-all') {
            this._mappingLinesDropped++;
            return;
          }
          if (mappingPolicy === 'keep-first' && this._mappingLinesKept >= 1) {
            this._mappingLinesDropped++;
            return;
          }
          this._mappingLinesKept++;
        }
      }
      const maxCharsRaw = kind === 'err' ? (opts && opts.maxErrorChars) : (opts && opts.maxOutputChars);
      const maxChars = Number.isFinite(Number(maxCharsRaw)) ? Math.max(0, Math.floor(Number(maxCharsRaw))) : 0;
      let used = kind === 'err' ? this._errChars : this._outChars;
      if (maxChars > 0) {
        if (used >= maxChars) {
          if (kind === 'err' && !this._errTruncated) {
            this._errTruncated = true;
            arr.push('[capstone] stderr truncated');
          }
          if (kind === 'out' && !this._outTruncated) {
            this._outTruncated = true;
            arr.push('[capstone] stdout truncated');
          }
          return;
        }
        if (used + s.length > maxChars) {
          const keep = Math.max(0, maxChars - used);
          s = keep > 0 ? s.slice(0, keep) : '';
        }
      }
      arr.push(s);
      used += s.length;
      if (kind === 'err') this._errChars = used; else this._outChars = used;
    },
    pushOut(text) { this._pushWithLimit(this.out, text, 'out'); },
    pushErr(text) { this._pushWithLimit(this.err, text, 'err'); }
  };
}

function __capHeapKiBFromModule(mod) {
  try {
    const mem = mod && mod.__capstoneWasmMemory;
    const bytes = mem && mem.buffer ? mem.buffer.byteLength : 0;
    if (!Number.isFinite(bytes) || bytes <= 0) return null;
    return bytes / 1024;
  } catch (_) {
    return null;
  }
}

function __capAllocatorFnsFromModule(mod) {
  const m = mod && typeof mod === 'object' ? mod : null;
  if (!m) return null;
  const reset = typeof m._capstone_allocator_telemetry_reset === 'function' ? m._capstone_allocator_telemetry_reset : null;
  const peak = typeof m._capstone_allocator_telemetry_peak_bytes === 'function' ? m._capstone_allocator_telemetry_peak_bytes : null;
  const current = typeof m._capstone_allocator_telemetry_current_bytes === 'function' ? m._capstone_allocator_telemetry_current_bytes : null;
  const allocCount = typeof m._capstone_allocator_telemetry_alloc_count === 'function' ? m._capstone_allocator_telemetry_alloc_count : null;
  const freeCount = typeof m._capstone_allocator_telemetry_free_count === 'function' ? m._capstone_allocator_telemetry_free_count : null;
  const droppedRecords = typeof m._capstone_allocator_telemetry_dropped_records === 'function' ? m._capstone_allocator_telemetry_dropped_records : null;
  if (!reset || !peak || !current) return null;
  return { reset, peak, current, allocCount, freeCount, droppedRecords };
}

function __capToNumOrNull(v, min) {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  if (Number.isFinite(min) && n < min) return null;
  return n;
}

function __capBuildMemorySample(mod) {
  const heapKiB = __capHeapKiBFromModule(mod);
  const fallback = {
    metricKind: 'wasm_heap_peak_kib',
    metricLabel: 'WASM Heap Peak',
    metricUnit: 'KiB',
    valueKiB: heapKiB,
    heapCapacityKiB: heapKiB,
    allocatorPeakKiB: null,
    allocatorCurrentKiB: null,
    allocatorAllocCount: null,
    allocatorFreeCount: null,
    allocatorDroppedRecords: null
  };
  const fns = mod && mod.__capstoneAllocatorFns ? mod.__capstoneAllocatorFns : __capAllocatorFnsFromModule(mod);
  if (!fns) return fallback;
  if (mod && !mod.__capstoneAllocatorFns) {
    try { mod.__capstoneAllocatorFns = fns; } catch (_) {}
  }
  const peakBytes = __capToNumOrNull((() => { try { return fns.peak(); } catch (_) { return null; } })(), 0);
  const currentBytes = __capToNumOrNull((() => { try { return fns.current(); } catch (_) { return null; } })(), 0);
  const allocCount = __capToNumOrNull((() => { try { return fns.allocCount ? fns.allocCount() : null; } catch (_) { return null; } })(), 0);
  const freeCount = __capToNumOrNull((() => { try { return fns.freeCount ? fns.freeCount() : null; } catch (_) { return null; } })(), 0);
  const droppedRecords = __capToNumOrNull((() => { try { return fns.droppedRecords ? fns.droppedRecords() : null; } catch (_) { return null; } })(), 0);
  const peakKiB = peakBytes === null ? null : (peakBytes / 1024);
  const currentKiB = currentBytes === null ? null : (currentBytes / 1024);
  if (peakKiB === null) return fallback;
  return {
    metricKind: 'wasm_allocator_peak_kib',
    metricLabel: 'WASM Allocator Peak',
    metricUnit: 'KiB',
    valueKiB: peakKiB,
    heapCapacityKiB: heapKiB,
    allocatorPeakKiB: peakKiB,
    allocatorCurrentKiB: currentKiB,
    allocatorAllocCount: allocCount,
    allocatorFreeCount: freeCount,
    allocatorDroppedRecords: droppedRecords
  };
}

async function __capCreateModule(payload) {
  const spec = payload && payload.spec ? payload.spec : {};
  const id = String(spec.id || '').trim();
  const scriptUrl = String(spec.scriptUrl || spec.scriptPath || '').trim();
  const wasmUrl = String(spec.wasmUrl || spec.wasmPath || '').trim();
  const factoryName = String(spec.factoryName || '').trim();
  if (!id || !scriptUrl || !wasmUrl || !factoryName) {
    throw new Error('Invalid worker wasm module spec');
  }
  if (!('WebAssembly' in self)) {
    throw new Error('WebAssembly is not supported in this browser.');
  }

  const t0 = __capNowMs();
  __capLoadScriptOnce(scriptUrl);
  const factory = self[factoryName];
  if (typeof factory !== 'function') {
    throw new Error('WASM factory not found: ' + factoryName + ' (did ' + scriptUrl + ' load?)');
  }

  const moduleCaptureState = { wasmMemory: null };
  const capture = __capMakeCapture();
  const wasmObj = (typeof WebAssembly === 'object' && WebAssembly) ? WebAssembly : null;
  const origInstantiate = wasmObj && typeof wasmObj.instantiate === 'function' ? wasmObj.instantiate : null;
  const origInstantiateStreaming = wasmObj && typeof wasmObj.instantiateStreaming === 'function' ? wasmObj.instantiateStreaming : null;
  const attachWasmMemoryFromResult = (result) => {
    try {
      const instance = result && result.instance ? result.instance : result;
      const exportsObj = instance && instance.exports ? instance.exports : null;
      if (!exportsObj || typeof exportsObj !== 'object') return result;
      let mem = null;
      if (exportsObj.memory instanceof WebAssembly.Memory) {
        mem = exportsObj.memory;
      } else {
        for (const value of Object.values(exportsObj)) {
          if (value instanceof WebAssembly.Memory) {
            mem = value;
            break;
          }
        }
      }
      if (mem) moduleCaptureState.wasmMemory = mem;
    } catch (_) {}
    return result;
  };

  if (wasmObj && origInstantiate) {
    wasmObj.instantiate = function(...args) {
      const out = origInstantiate.apply(this, args);
      if (!out || typeof out.then !== 'function') return attachWasmMemoryFromResult(out);
      return out.then((result) => attachWasmMemoryFromResult(result));
    };
  }
  if (wasmObj && origInstantiateStreaming) {
    wasmObj.instantiateStreaming = function(...args) {
      const out = origInstantiateStreaming.apply(this, args);
      if (!out || typeof out.then !== 'function') return attachWasmMemoryFromResult(out);
      return out.then((result) => attachWasmMemoryFromResult(result));
    };
  }

  let module;
  try {
    module = await factory({
      noInitialRun: true,
      noExitRuntime: true,
      locateFile: function(path, prefix) {
        if (typeof path === 'string' && path.endsWith('.wasm')) return wasmUrl;
        return (prefix || '') + path;
      },
      print: function(text) { capture.pushOut(text); },
      printErr: function(text) { capture.pushErr(text); }
    });
  } finally {
    try {
      if (wasmObj && origInstantiate) wasmObj.instantiate = origInstantiate;
      if (wasmObj && origInstantiateStreaming) wasmObj.instantiateStreaming = origInstantiateStreaming;
    } catch (_) {}
  }

  if (!module || !module.FS || typeof module.callMain !== 'function') {
    throw new Error('WASM module missing FS/callMain: ' + id);
  }

  module.__capstoneCapture = capture;
  module.__capstoneId = id;
  module.__capstoneWasmMemory = moduleCaptureState.wasmMemory || null;
  module.__capstoneAllocatorFns = __capAllocatorFnsFromModule(module);

  const token = (__capstoneNextToken++);
  __capstoneModules.set(token, module);
  const t1 = __capNowMs();
  return { token, refreshMs: Math.max(0, t1 - t0) };
}

function __capApplyFsOps(mod, fsOps) {
  const ops = Array.isArray(fsOps) ? fsOps : [];
  for (const raw of ops) {
    const op = raw && typeof raw === 'object' ? raw : null;
    if (!op) continue;
    const type = String(op.op || '').trim();
    if (type === 'mkdir') {
      const path = String(op.path || '').trim();
      if (!path) continue;
      try { mod.FS.mkdir(path); } catch (_) {}
      continue;
    }
    if (type === 'writeFileText') {
      const path = String(op.path || '').trim();
      if (!path) continue;
      mod.FS.writeFile(path, String(op.text == null ? '' : op.text), { encoding: 'utf8' });
    }
  }
}

async function __capRunModuleMain(payload) {
  const token = Number(payload && payload.token);
  if (!Number.isInteger(token) || !__capstoneModules.has(token)) {
    throw new Error('Unknown worker wasm module token');
  }
  const mod = __capstoneModules.get(token);
  __capApplyFsOps(mod, payload && payload.fsOps);

  const args = Array.isArray(payload && payload.args) ? payload.args.map(v => String(v)) : [];
  const options = payload && payload.options && typeof payload.options === 'object' ? payload.options : {};
  const capture = mod.__capstoneCapture;
  if (!capture) throw new Error('Missing wasm capture');
  capture.reset();
  if (typeof capture.beginRun === 'function') {
    try { capture.beginRun(options.captureOptions || null); } catch (_) {}
  }
  const allocatorFns = mod && mod.__capstoneAllocatorFns ? mod.__capstoneAllocatorFns : __capAllocatorFnsFromModule(mod);
  if (allocatorFns) {
    try { allocatorFns.reset(); } catch (_) {}
  }

  const hasStdinText = Object.prototype.hasOwnProperty.call(options, 'stdinText');
  const stdinText = hasStdinText ? String(options.stdinText == null ? '' : options.stdinText) : null;
  let restorePrompt = null;
  if (hasStdinText && typeof self.prompt === 'function') {
    const originalPrompt = self.prompt;
    let served = false;
    self.prompt = function() {
      if (served) return null;
      served = true;
      return stdinText;
    };
    restorePrompt = function() {
      try { self.prompt = originalPrompt; } catch (_) {}
    };
  } else if (hasStdinText) {
    const originalPrompt = self.prompt;
    let served = false;
    self.prompt = function() {
      if (served) return null;
      served = true;
      return stdinText;
    };
    restorePrompt = function() {
      try { self.prompt = originalPrompt; } catch (_) {}
    };
  }
  const finalizeRun = function() {
    try { if (restorePrompt) restorePrompt(); } catch (_) {}
    try { if (typeof capture.endRun === 'function') capture.endRun(); } catch (_) {}
  };

  try {
    mod.callMain(args);
  } catch (error) {
    const status = (error && typeof error.status === 'number') ? error.status : null;
    const stdout = capture.out.join('\n');
    const stderr = capture.err.join('\n');
    const memory = __capBuildMemorySample(mod);
    if (status === 0) {
      finalizeRun();
      return {
        stdout: stdout.trimEnd(),
        stderr: stderr.trimEnd(),
        heapKiB: memory && Number.isFinite(Number(memory.heapCapacityKiB)) ? Number(memory.heapCapacityKiB) : null,
        memory
      };
    }
    const msg = stderr || stdout || (error && error.message ? error.message : String(error));
    if (status !== null) {
      finalizeRun();
      throw new Error('WASM program exited with status ' + status + ': ' + msg);
    }
    __capstoneModules.delete(token);
    finalizeRun();
    throw error;
  }
  finalizeRun();
  const memory = __capBuildMemorySample(mod);
  return {
    stdout: capture.out.join('\n').trimEnd(),
    stderr: capture.err.join('\n').trimEnd(),
    heapKiB: memory && Number.isFinite(Number(memory.heapCapacityKiB)) ? Number(memory.heapCapacityKiB) : null,
    memory
  };
}

function __capDisposeModule(payload) {
  const token = Number(payload && payload.token);
  if (Number.isInteger(token)) __capstoneModules.delete(token);
  return { ok: true };
}

function __capApplyFsOpsOnly(payload) {
  const token = Number(payload && payload.token);
  if (!Number.isInteger(token) || !__capstoneModules.has(token)) {
    throw new Error('Unknown worker wasm module token');
  }
  const mod = __capstoneModules.get(token);
  __capApplyFsOps(mod, payload && payload.fsOps);
  const memory = __capBuildMemorySample(mod);
  return {
    ok: true,
    heapKiB: memory && Number.isFinite(Number(memory.heapCapacityKiB)) ? Number(memory.heapCapacityKiB) : null,
    memory
  };
}

self.onmessage = async function(ev) {
  const msg = ev && ev.data && typeof ev.data === 'object' ? ev.data : {};
  const requestId = msg.requestId;
  const type = String(msg.type || '');
  try {
    let result;
    if (type === 'create_module') result = await __capCreateModule(msg.payload || {});
    else if (type === 'run_module_main') result = await __capRunModuleMain(msg.payload || {});
    else if (type === 'dispose_module') result = __capDisposeModule(msg.payload || {});
    else if (type === 'apply_fs_ops') result = __capApplyFsOpsOnly(msg.payload || {});
    else throw new Error('Unknown worker request: ' + type);
    self.postMessage({ requestId, ok: true, result: result });
  } catch (error) {
    const e = error instanceof Error ? error : new Error(String(error || 'Worker error'));
    self.postMessage({ requestId, ok: false, error: { message: e.message || String(e), stack: e.stack || '' } });
  }
};`;
        }

        async function getLocalWasmWorker() {
            if (!shouldUseLocalWasmWorker()) {
                throw new Error('Local WASM worker is unavailable');
            }
            if (localWasmWorkerPromise) return localWasmWorkerPromise;
            localWasmWorkerPromise = (async () => {
                const blob = new Blob([buildLocalWasmWorkerSource()], { type: 'text/javascript' });
                const workerUrl = URL.createObjectURL(blob);
                const worker = new Worker(workerUrl);
                worker.__capstoneWorkerUrl = workerUrl;
                worker.addEventListener('message', (ev) => {
                    const msg = ev && ev.data && typeof ev.data === 'object' ? ev.data : null;
                    if (!msg) return;
                    const requestId = msg.requestId;
                    if (!localWasmWorkerPending.has(requestId)) return;
                    const pending = localWasmWorkerPending.get(requestId);
                    localWasmWorkerPending.delete(requestId);
                    if (msg.ok) {
                        pending.resolve(msg.result);
                        return;
                    }
                    const errObj = msg.error && typeof msg.error === 'object' ? msg.error : {};
                    const error = new Error(String(errObj.message || 'Local WASM worker error'));
                    if (errObj.stack) {
                        try { error.stack = String(errObj.stack); } catch (_) {}
                    }
                    pending.reject(error);
                });
                worker.addEventListener('error', (ev) => {
                    const message = ev && ev.message ? String(ev.message) : 'Worker runtime error';
                    const error = new Error(message);
                    localWasmWorkerWarn('Local WASM worker runtime error; falling back to main-thread execution for this session.', error);
                    teardownLocalWasmWorker(error, { disableWorker: true }).catch(() => {});
                });
                return worker;
            })().catch((error) => {
                localWasmWorkerPromise = null;
                localWasmWorkerDisabled = true;
                localWasmWorkerWarn('Failed to initialize local WASM worker; falling back to main thread execution.', error);
                throw error;
            });
            return localWasmWorkerPromise;
        }

        async function callLocalWasmWorker(type, payload, options = {}) {
            const worker = await getLocalWasmWorker();
            const requestId = localWasmWorkerRequestSeq++;
            const opts = (options && typeof options === 'object') ? options : {};
            const abortSignal = (opts.abortSignal && typeof opts.abortSignal === 'object')
                ? opts.abortSignal
                : null;
            const terminateOnAbort = Boolean(opts.terminateOnAbort);
            return await new Promise((resolve, reject) => {
                let settled = false;
                const cleanup = () => {
                    if (abortSignal && typeof abortSignal.removeEventListener === 'function') {
                        try { abortSignal.removeEventListener('abort', onAbort); } catch (_) {}
                    }
                };
                const settleResolve = (value) => {
                    if (settled) return;
                    settled = true;
                    cleanup();
                    resolve(value);
                };
                const settleReject = (error) => {
                    if (settled) return;
                    settled = true;
                    cleanup();
                    reject(error instanceof Error ? error : new Error(String(error || 'Worker request failed')));
                };
                const onAbort = () => {
                    localWasmWorkerPending.delete(requestId);
                    const abortError = makeLocalWasmAbortError(opts.abortMessage || 'Run Aborted');
                    settleReject(abortError);
                    if (terminateOnAbort) {
                        teardownLocalWasmWorker(abortError, { disableWorker: false }).catch(() => {});
                    }
                };

                localWasmWorkerPending.set(requestId, { resolve: settleResolve, reject: settleReject });
                if (abortSignal && typeof abortSignal.addEventListener === 'function') {
                    if (abortSignal.aborted) {
                        onAbort();
                        return;
                    }
                    abortSignal.addEventListener('abort', onAbort, { once: true });
                }
                try {
                    worker.postMessage({
                        requestId,
                        type: String(type || ''),
                        payload: payload && typeof payload === 'object' ? payload : {}
                    });
                } catch (error) {
                    localWasmWorkerPending.delete(requestId);
                    settleReject(error);
                }
            });
        }

        function makeLocalWasmAbsoluteUrl(path) {
            const p = String(path || '').trim();
            if (!p) return '';
            try {
                if (typeof window !== 'undefined' && window.location) {
                    return new URL(p, window.location.href).href;
                }
            } catch (_) {}
            return p;
        }

        function makeLocalWasmWorkerSpec(spec) {
            const src = spec && typeof spec === 'object' ? spec : {};
            return {
                id: String(src.id || '').trim(),
                factoryName: String(src.factoryName || '').trim(),
                scriptUrl: makeLocalWasmAbsoluteUrl(src.scriptPath),
                wasmUrl: makeLocalWasmAbsoluteUrl(src.wasmPath)
            };
        }

        function registerLocalWasmWorkerModuleToken(moduleId, token) {
            const id = String(moduleId || '').trim();
            const t = Number(token);
            if (!id || !Number.isInteger(t)) return;
            if (!localWasmWorkerTokensByModuleId.has(id)) {
                localWasmWorkerTokensByModuleId.set(id, new Set());
            }
            localWasmWorkerTokensByModuleId.get(id).add(t);
        }

        function unregisterLocalWasmWorkerModuleToken(moduleId, token) {
            const id = String(moduleId || '').trim();
            const t = Number(token);
            if (!id || !Number.isInteger(t)) return;
            const set = localWasmWorkerTokensByModuleId.get(id);
            if (!set) return;
            set.delete(t);
            if (!set.size) localWasmWorkerTokensByModuleId.delete(id);
        }

        function makeLocalWasmWorkerModuleProxy(spec, workerSpec, createResult) {
            const token = Number(createResult && createResult.token);
            if (!Number.isInteger(token)) throw new Error('Invalid local WASM worker module token');
            const refreshMsRaw = createResult && createResult.refreshMs;
            const refreshMs = Number.isFinite(Number(refreshMsRaw)) ? Math.max(0, Number(refreshMsRaw)) : null;
            const moduleId = String(spec && spec.id ? spec.id : '').trim();
            registerLocalWasmWorkerModuleToken(moduleId, token);
            const proxy = {
                __capstoneWorkerProxy: true,
                __capstoneWorkerToken: token,
                __capstoneWorkerSpec: workerSpec,
                __capstoneId: moduleId,
                __capstoneWorkerFsOps: [],
                __capstoneLastHeapKiB: null,
                __capstoneLastMemorySample: null,
                __capstoneCreateRefreshMs: refreshMs,
                FS: null
            };
            proxy.FS = {
                mkdir(path) {
                    proxy.__capstoneWorkerFsOps.push({ op: 'mkdir', path: String(path || '') });
                },
                writeFile(path, text) {
                    proxy.__capstoneWorkerFsOps.push({
                        op: 'writeFileText',
                        path: String(path || ''),
                        text: String(text == null ? '' : text)
                    });
                }
            };
            return proxy;
        }

        function invalidateEmscriptenModule(id) {
            const key = String(id || '').trim();
            if (!key) return;
            localWasmModulePromises.delete(key);
            const tokens = localWasmWorkerTokensByModuleId.get(key);
            if (tokens && tokens.size) {
                const list = Array.from(tokens);
                localWasmWorkerTokensByModuleId.delete(key);
                for (const token of list) {
                    callLocalWasmWorker('dispose_module', { token }).catch(() => {});
                }
            }
        }

        function loadScriptOnce(src) {
            const url = String(src || '').trim();
            if (!url) return Promise.reject(new Error('Missing script URL'));
            if (localWasmScriptPromises.has(url)) return localWasmScriptPromises.get(url);

            const rawPromise = new Promise((resolve, reject) => {
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
            const promise = rawPromise.catch((error) => {
                localWasmScriptPromises.delete(url);
                throw error;
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
                if (shouldUseLocalWasmWorker()) {
                    try {
                        const workerSpec = makeLocalWasmWorkerSpec(spec);
                        const createResult = await callLocalWasmWorker('create_module', { spec: workerSpec }, {
                            abortSignal: localWasmActiveAbortSignal,
                            abortMessage: 'Run Aborted',
                            terminateOnAbort: true
                        });
                        return makeLocalWasmWorkerModuleProxy(spec, workerSpec, createResult);
                    } catch (error) {
                        const isAbort = Boolean(
                            error &&
                            (String(error.name || '').toLowerCase() === 'aborterror' ||
                                String(error.message || '').toLowerCase().includes('run aborted'))
                        );
                        if (isAbort) {
                            await teardownLocalWasmWorker(error, { disableWorker: false }).catch(() => {});
                            throw error;
                        }
                        localWasmWorkerDisabled = true;
                        localWasmWorkerWarn('Local WASM worker module creation failed; falling back to main-thread WASM execution for this session.', error);
                        await teardownLocalWasmWorker(error, { disableWorker: true }).catch(() => {});
                    }
                }
                if (!('WebAssembly' in window)) {
                    throw new Error('WebAssembly is not supported in this browser.');
                }

                await loadScriptOnce(scriptPath);
                const factory = window[factoryName];
                if (typeof factory !== 'function') {
                    throw new Error(`WASM factory not found: ${factoryName} (did ${scriptPath} load?)`);
                }

                const moduleCaptureState = {
                    wasmMemory: null
                };

                const capture = {
                    out: [],
                    err: [],
                    _runOpts: null,
                    _outChars: 0,
                    _errChars: 0,
                    _mappingLinesKept: 0,
                    _mappingLinesDropped: 0,
                    _outTruncated: false,
                    _errTruncated: false,
                    reset() {
                        this.out.length = 0;
                        this.err.length = 0;
                        this._runOpts = null;
                        this._outChars = 0;
                        this._errChars = 0;
                        this._mappingLinesKept = 0;
                        this._mappingLinesDropped = 0;
                        this._outTruncated = false;
                        this._errTruncated = false;
                    },
                    beginRun(opts) {
                        const o = (opts && typeof opts === 'object') ? opts : null;
                        this._runOpts = o;
                        this._outChars = 0;
                        this._errChars = 0;
                        this._mappingLinesKept = 0;
                        this._mappingLinesDropped = 0;
                        this._outTruncated = false;
                        this._errTruncated = false;
                    },
                    endRun() {
                        this._runOpts = null;
                    },
                    _pushWithLimit(arr, text, kind) {
                        const s0 = String(text ?? '');
                        const opts = this._runOpts || null;
                        let s = s0;
                        if (kind === 'out' && opts) {
                            const mappingPolicy = String(opts.mappingLinePolicy || '').trim().toLowerCase();
                            if (mappingPolicy && /^mapping\s*:/i.test(s)) {
                                if (mappingPolicy === 'drop-all') {
                                    this._mappingLinesDropped++;
                                    return;
                                }
                                if (mappingPolicy === 'keep-first' && this._mappingLinesKept >= 1) {
                                    this._mappingLinesDropped++;
                                    return;
                                }
                                this._mappingLinesKept++;
                            }
                        }

                        const maxCharsRaw = kind === 'err'
                            ? (opts && opts.maxErrorChars)
                            : (opts && opts.maxOutputChars);
                        const maxChars = Number.isFinite(Number(maxCharsRaw)) ? Math.max(0, Math.floor(Number(maxCharsRaw))) : 0;
                        let used = kind === 'err' ? this._errChars : this._outChars;
                        if (maxChars > 0) {
                            if (used >= maxChars) {
                                if (kind === 'err' && !this._errTruncated) {
                                    this._errTruncated = true;
                                    arr.push('[capstone] stderr truncated');
                                }
                                if (kind === 'out' && !this._outTruncated) {
                                    this._outTruncated = true;
                                    arr.push('[capstone] stdout truncated');
                                }
                                return;
                            }
                            if (used + s.length > maxChars) {
                                const keep = Math.max(0, maxChars - used);
                                s = keep > 0 ? s.slice(0, keep) : '';
                            }
                        }
                        arr.push(s);
                        used += s.length;
                        if (kind === 'err') this._errChars = used;
                        else this._outChars = used;
                    },
                    pushOut(text) {
                        this._pushWithLimit(this.out, text, 'out');
                    },
                    pushErr(text) {
                        this._pushWithLimit(this.err, text, 'err');
                    }
                };

                const wasmObj = (typeof WebAssembly === 'object' && WebAssembly) ? WebAssembly : null;
                const origInstantiate = wasmObj && typeof wasmObj.instantiate === 'function' ? wasmObj.instantiate : null;
                const origInstantiateStreaming = wasmObj && typeof wasmObj.instantiateStreaming === 'function' ? wasmObj.instantiateStreaming : null;
                const attachWasmMemoryFromResult = (result) => {
                    try {
                        const instance = result && result.instance ? result.instance : result;
                        const exportsObj = instance && instance.exports ? instance.exports : null;
                        if (!exportsObj || typeof exportsObj !== 'object') return result;
                        let mem = null;
                        if (exportsObj.memory instanceof WebAssembly.Memory) {
                            mem = exportsObj.memory;
                        } else {
                            for (const value of Object.values(exportsObj)) {
                                if (value instanceof WebAssembly.Memory) {
                                    mem = value;
                                    break;
                                }
                            }
                        }
                        if (mem) moduleCaptureState.wasmMemory = mem;
                    } catch (_) {}
                    return result;
                };

                if (wasmObj && origInstantiate) {
                    wasmObj.instantiate = function(...args) {
                        const out = origInstantiate.apply(this, args);
                        if (!out || typeof out.then !== 'function') {
                            return attachWasmMemoryFromResult(out);
                        }
                        return out.then((result) => attachWasmMemoryFromResult(result));
                    };
                }
                if (wasmObj && origInstantiateStreaming) {
                    wasmObj.instantiateStreaming = function(...args) {
                        const out = origInstantiateStreaming.apply(this, args);
                        if (!out || typeof out.then !== 'function') {
                            return attachWasmMemoryFromResult(out);
                        }
                        return out.then((result) => attachWasmMemoryFromResult(result));
                    };
                }

                let module;
                try {
                    module = await factory({
                        noInitialRun: true,
                        // We call callMain() many times per run; keep the runtime alive between invocations.
                        noExitRuntime: true,
                        locateFile: (path, prefix) => {
                            if (typeof path === 'string' && path.endsWith('.wasm')) {
                                return wasmPath;
                            }
                            return (prefix || '') + path;
                        },
                        print: (text) => capture.pushOut(text),
                        printErr: (text) => capture.pushErr(text)
                    });
                } finally {
                    try {
                        if (wasmObj && origInstantiate) wasmObj.instantiate = origInstantiate;
                        if (wasmObj && origInstantiateStreaming) wasmObj.instantiateStreaming = origInstantiateStreaming;
                    } catch (_) {}
                }

                if (!module || !module.FS || typeof module.callMain !== 'function') {
                    throw new Error(`WASM module missing FS/callMain: ${id}`);
                }

                module.__capstoneCapture = capture;
                module.__capstoneId = id;
                module.__capstoneWasmMemory = moduleCaptureState.wasmMemory || null;
                module.__capstoneAllocatorTelemetryFns = null;
                module.__capstoneAllocatorTelemetryChecked = false;
                module.__capstoneLastMemorySample = null;
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

        async function flushEmscriptenWorkerFsOps(mod) {
            if (!mod || !mod.__capstoneWorkerProxy) return;
            const token = Number(mod.__capstoneWorkerToken);
            if (!Number.isInteger(token)) return;
            const ops = Array.isArray(mod.__capstoneWorkerFsOps) ? mod.__capstoneWorkerFsOps.splice(0) : [];
            if (!ops.length) return;
            const result = await callLocalWasmWorker('apply_fs_ops', { token, fsOps: ops }, {
                abortSignal: localWasmActiveAbortSignal,
                abortMessage: 'Run Aborted',
                terminateOnAbort: true
            });
            const heapKiBRaw = result && result.heapKiB;
            const heapKiB = Number.isFinite(Number(heapKiBRaw)) ? Math.max(0, Number(heapKiBRaw)) : null;
            mod.__capstoneLastHeapKiB = heapKiB;
            if (result && typeof result.memory === 'object' && result.memory) {
                mod.__capstoneLastMemorySample = normalizeWasmMemorySample(result.memory);
            } else if (heapKiB !== null) {
                mod.__capstoneLastMemorySample = makeHeapOnlyWasmMemorySample(heapKiB);
            }
        }

        function getEmscriptenAllocatorTelemetryFns(mod) {
            if (!mod || typeof mod !== 'object' || mod.__capstoneWorkerProxy) return null;
            if (mod.__capstoneAllocatorTelemetryChecked) {
                return mod.__capstoneAllocatorTelemetryFns || null;
            }
            const reset = typeof mod._capstone_allocator_telemetry_reset === 'function'
                ? mod._capstone_allocator_telemetry_reset
                : null;
            const peakBytes = typeof mod._capstone_allocator_telemetry_peak_bytes === 'function'
                ? mod._capstone_allocator_telemetry_peak_bytes
                : null;
            const currentBytes = typeof mod._capstone_allocator_telemetry_current_bytes === 'function'
                ? mod._capstone_allocator_telemetry_current_bytes
                : null;
            const allocCount = typeof mod._capstone_allocator_telemetry_alloc_count === 'function'
                ? mod._capstone_allocator_telemetry_alloc_count
                : null;
            const freeCount = typeof mod._capstone_allocator_telemetry_free_count === 'function'
                ? mod._capstone_allocator_telemetry_free_count
                : null;
            const droppedRecords = typeof mod._capstone_allocator_telemetry_dropped_records === 'function'
                ? mod._capstone_allocator_telemetry_dropped_records
                : null;
            const fns = (reset && peakBytes && currentBytes)
                ? { reset, peakBytes, currentBytes, allocCount, freeCount, droppedRecords }
                : null;
            mod.__capstoneAllocatorTelemetryFns = fns;
            mod.__capstoneAllocatorTelemetryChecked = true;
            return fns;
        }

        function resetEmscriptenAllocatorTelemetry(mod) {
            const fns = getEmscriptenAllocatorTelemetryFns(mod);
            if (!fns || typeof fns.reset !== 'function') return false;
            try {
                fns.reset();
                return true;
            } catch (_) {
                return false;
            }
        }

        function readEmscriptenAllocatorTelemetry(mod) {
            const fns = getEmscriptenAllocatorTelemetryFns(mod);
            if (!fns) return null;
            const peakBytes = numberOrNull((() => {
                try { return fns.peakBytes(); } catch (_) { return null; }
            })(), 0);
            const currentBytes = numberOrNull((() => {
                try { return fns.currentBytes(); } catch (_) { return null; }
            })(), 0);
            if (peakBytes === null) return null;
            return {
                peakKiB: peakBytes / 1024,
                currentKiB: currentBytes !== null ? (currentBytes / 1024) : null,
                allocCount: numberOrNull((() => {
                    try { return fns.allocCount ? fns.allocCount() : null; } catch (_) { return null; }
                })(), 0),
                freeCount: numberOrNull((() => {
                    try { return fns.freeCount ? fns.freeCount() : null; } catch (_) { return null; }
                })(), 0),
                droppedRecords: numberOrNull((() => {
                    try { return fns.droppedRecords ? fns.droppedRecords() : null; } catch (_) { return null; }
                })(), 0)
            };
        }

        function getEmscriptenMemorySample(mod) {
            try {
                if (mod && mod.__capstoneWorkerProxy) {
                    if (mod.__capstoneLastMemorySample && typeof mod.__capstoneLastMemorySample === 'object') {
                        return normalizeWasmMemorySample(mod.__capstoneLastMemorySample);
                    }
                    const heapKiB = numberOrNull(mod.__capstoneLastHeapKiB, 0);
                    if (heapKiB !== null) return makeHeapOnlyWasmMemorySample(heapKiB);
                    return makeHeapOnlyWasmMemorySample(null);
                }
                const mem = mod && mod.__capstoneWasmMemory;
                const bytes = mem && mem.buffer ? mem.buffer.byteLength : 0;
                const heapKiB = (Number.isFinite(bytes) && bytes > 0) ? (bytes / 1024) : null;
                const allocator = readEmscriptenAllocatorTelemetry(mod);
                if (allocator && Number.isFinite(Number(allocator.peakKiB))) {
                    return normalizeWasmMemorySample({
                        metricKind: WASM_MEMORY_ALLOCATOR_KIND,
                        valueKiB: allocator.peakKiB,
                        heapCapacityKiB: heapKiB,
                        allocatorPeakKiB: allocator.peakKiB,
                        allocatorCurrentKiB: allocator.currentKiB,
                        allocatorAllocCount: allocator.allocCount,
                        allocatorFreeCount: allocator.freeCount,
                        allocatorDroppedRecords: allocator.droppedRecords
                    });
                }
                return makeHeapOnlyWasmMemorySample(heapKiB);
            } catch (_) {
                return makeHeapOnlyWasmMemorySample(null);
            }
        }

        function getEmscriptenMemoryMetricInfo(mod) {
            const sample = getEmscriptenMemorySample(mod);
            if (!sample || typeof sample !== 'object') {
                return getDefaultWasmMemoryMetricInfo();
            }
            const info = {
                kind: String(sample.metricKind || '').trim() || WASM_MEMORY_HEAP_KIND,
                label: String(sample.metricLabel || '').trim() || WASM_MEMORY_HEAP_LABEL,
                unit: String(sample.metricUnit || '').trim() || WASM_MEMORY_METRIC_UNIT
            };
            if (info.kind !== WASM_MEMORY_ALLOCATOR_KIND && info.kind !== WASM_MEMORY_HEAP_KIND) {
                return getDefaultWasmMemoryMetricInfo();
            }
            return info;
        }

        function getEmscriptenHeapPeakKiB(mod) {
            const sample = getEmscriptenMemorySample(mod);
            const value = numberOrNull(sample && sample.valueKiB, 0);
            return value;
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

        async function runEmscriptenMain(mod, args, options = {}) {
            if (mod && mod.__capstoneWorkerProxy) {
                const token = Number(mod.__capstoneWorkerToken);
                if (!Number.isInteger(token)) throw new Error('Missing local WASM worker module token');
                const argv = Array.isArray(args) ? args.map(a => String(a)) : [];
                const fsOps = Array.isArray(mod.__capstoneWorkerFsOps) ? mod.__capstoneWorkerFsOps.splice(0) : [];
                const abortSignal = (options && options.abortSignal && typeof options.abortSignal === 'object')
                    ? options.abortSignal
                    : localWasmActiveAbortSignal;
                const workerOptions = {};
                if (options && typeof options.captureOptions === 'object' && options.captureOptions) {
                    workerOptions.captureOptions = options.captureOptions;
                }
                if (Object.prototype.hasOwnProperty.call(options || {}, 'stdinText')) {
                    workerOptions.stdinText = options && options.stdinText !== undefined && options.stdinText !== null
                        ? String(options.stdinText)
                        : '';
                }
                try {
                    const result = await callLocalWasmWorker('run_module_main', {
                        token,
                        fsOps,
                        args: argv,
                        options: workerOptions
                    }, {
                        abortSignal,
                        abortMessage: 'Run Aborted',
                        terminateOnAbort: Boolean(abortSignal)
                    });
                    const heapKiBRaw = result && result.heapKiB;
                    const heapKiB = Number.isFinite(Number(heapKiBRaw)) ? Math.max(0, Number(heapKiBRaw)) : null;
                    mod.__capstoneLastHeapKiB = heapKiB;
                    if (result && typeof result.memory === 'object' && result.memory) {
                        mod.__capstoneLastMemorySample = normalizeWasmMemorySample(result.memory);
                    } else if (heapKiB !== null) {
                        mod.__capstoneLastMemorySample = makeHeapOnlyWasmMemorySample(heapKiB);
                    } else {
                        mod.__capstoneLastMemorySample = makeHeapOnlyWasmMemorySample(null);
                    }
                    return {
                        stdout: String(result && result.stdout ? result.stdout : ''),
                        stderr: String(result && result.stderr ? result.stderr : '')
                    };
                } catch (error) {
                    // Worker-side runtime traps may invalidate the worker module token.
                    try {
                        if (mod && mod.__capstoneId) invalidateEmscriptenModule(mod.__capstoneId);
                    } catch (_) {}
                    throw error;
                }
            }
            const argv = Array.isArray(args) ? args.map(a => String(a)) : [];
            const capture = mod.__capstoneCapture;
            if (!capture) throw new Error('Missing wasm capture');
            capture.reset();
            const captureOptions = (options && typeof options.captureOptions === 'object' && options.captureOptions)
                ? options.captureOptions
                : null;
            if (typeof capture.beginRun === 'function') {
                try { capture.beginRun(captureOptions); } catch (_) {}
            }
            resetEmscriptenAllocatorTelemetry(mod);

            const hasStdinText = Object.prototype.hasOwnProperty.call(options || {}, 'stdinText');
            const stdinText = hasStdinText ? String(options && options.stdinText !== undefined && options.stdinText !== null ? options.stdinText : '') : null;
            let restorePrompt = null;
            if (hasStdinText && typeof window !== 'undefined' && typeof window.prompt === 'function') {
                const originalPrompt = window.prompt;
                let served = false;
                window.prompt = function(..._args) {
                    if (served) return null;
                    served = true;
                    return stdinText;
                };
                restorePrompt = () => {
                    try { window.prompt = originalPrompt; } catch (_) {}
                };
            }
            const finalizeRun = () => {
                try {
                    if (restorePrompt) restorePrompt();
                } catch (_) {}
                try {
                    if (typeof capture.endRun === 'function') capture.endRun();
                } catch (_) {}
            };

            try {
                mod.callMain(argv);
            } catch (error) {
                // Emscripten may throw an ExitStatus object on exit().
                const status = (error && typeof error.status === 'number') ? error.status : null;
                const stdout = capture.out.join('\n');
                const stderr = capture.err.join('\n');
                if (status === 0) {
                    finalizeRun();
                    mod.__capstoneLastMemorySample = getEmscriptenMemorySample(mod);
                    return {
                        stdout: stdout.trimEnd(),
                        stderr: stderr.trimEnd()
                    };
                }
                const msg = stderr || stdout || (error && error.message ? error.message : String(error));
                if (status !== null) {
                    finalizeRun();
                    throw new Error(`WASM program exited with status ${status}: ${msg}`);
                }

                // Runtime traps (e.g., "function signature mismatch") can poison the module instance.
                // Drop it so the next run will recreate a fresh instance.
                try {
                    if (mod && mod.__capstoneId) invalidateEmscriptenModule(mod.__capstoneId);
                } catch (_) {}
                finalizeRun();
                throw error;
            }

            finalizeRun();
            mod.__capstoneLastMemorySample = getEmscriptenMemorySample(mod);
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

        const STATS_LABEL_WIDTH = 40;
        const STATS_VALUE_WIDTH = 10;

        function formatAlignedLabelValueRow(label, value, labelWidth = STATS_LABEL_WIDTH) {
            const cleanLabel = String(label || '').trim().replace(/:\s*$/, '');
            return `${cleanLabel.padEnd(labelWidth)} ${String(value == null ? '' : value)}`;
        }

        function formatAlignedMedianStdevRow(label, stats, labelWidth = STATS_LABEL_WIDTH) {
            if (!stats) return '';
            const cleanLabel = String(label || '').trim().replace(/:\s*$/, '');
            const fmt = (v) => Number(v).toFixed(3).padStart(STATS_VALUE_WIDTH);
            return `${cleanLabel.padEnd(labelWidth)} median=${fmt(stats.median)}  stdev=${fmt(stats.stdev)}`;
        }

        function formatStatsMsFirstAll(prefix, firstStats, allStats) {
            const raw = String(prefix || '').trim().replace(/:\s*$/, '');
            const unitMatch = raw.match(/^(.*)\(([^)]+)\)$/);
            const base = unitMatch ? String(unitMatch[1] || '').trim() : raw;
            const unit = unitMatch ? String(unitMatch[2] || '').trim() : '';
            const firstLabel = unit ? `${base} First (${unit})` : `${base} First`;
            const allLabel = unit ? `${base} All (${unit})` : `${base} All`;
            const width = Math.max(STATS_LABEL_WIDTH, firstLabel.length, allLabel.length);
            return [
                formatAlignedMedianStdevRow(firstLabel, firstStats, width),
                formatAlignedMedianStdevRow(allLabel, allStats, width)
            ].filter(Boolean);
        }

        function formatStatsMsSummary(prefix, stats) {
            return formatAlignedMedianStdevRow(prefix, stats, STATS_LABEL_WIDTH);
        }

        function formatWasmMemoryStatsPrefix(metricInfo) {
            const info = (metricInfo && typeof metricInfo === 'object')
                ? metricInfo
                : getDefaultWasmMemoryMetricInfo();
            const label = String(info.label || WASM_MEMORY_HEAP_LABEL).trim() || WASM_MEMORY_HEAP_LABEL;
            const unit = String(info.unit || WASM_MEMORY_METRIC_UNIT).trim() || WASM_MEMORY_METRIC_UNIT;
            return `${label} (${unit}): `;
        }

        let localWasmManifestPromise = null;
        let localPyodidePromise = null;
        let localGeneratorScriptSourcePromise = null;
        let localGeneratorBootstrapReady = false;

        async function loadLocalWasmManifest() {
            if (localWasmManifestPromise) return localWasmManifestPromise;
            localWasmManifestPromise = (async () => {
                try {
                    const resp = await fetch('wasm/manifest.json', { cache: 'no-cache' });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const data = await resp.json();
                    if (!data || typeof data !== 'object') throw new Error('Invalid manifest');
                    return data;
                } catch (_) {
                    return null;
                }
            })();
            return localWasmManifestPromise;
        }

        async function getLocalWasmModuleSpec(moduleId, fallbackSpec) {
            const id = String(moduleId || '').trim();
            if (!id) return fallbackSpec && typeof fallbackSpec === 'object' ? fallbackSpec : null;
            const manifest = await loadLocalWasmManifest();
            const item = manifest && manifest.modules && manifest.modules[id] ? manifest.modules[id] : null;
            if (!item || typeof item !== 'object') return fallbackSpec;
            const scriptPath = String(item.scriptPath || '').trim();
            const wasmPath = String(item.wasmPath || '').trim();
            const factoryName = String(item.factoryName || '').trim();
            if (!scriptPath || !wasmPath || !factoryName) return fallbackSpec;
            return { id, scriptPath, wasmPath, factoryName };
        }

        function localTitleCaseToken(value) {
            const parts = String(value || '')
                .trim()
                .split(/[^A-Za-z0-9]+/)
                .filter(Boolean);
            if (!parts.length) return 'Unknown';
            return parts
                .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
                .join(' ');
        }

        function localWasmFamilyLabel(familyPrefix) {
            const prefix = String(familyPrefix || '').trim().toLowerCase();
            if (prefix === 'vf3') return 'VF3';
            if (prefix === 'glasgow') return 'Glasgow';
            if (prefix === 'dijkstra') return 'Dijkstra';
            return localTitleCaseToken(prefix);
        }

        function localWasmVariantTokenFromId(moduleId, familyPrefix) {
            const id = String(moduleId || '').trim().toLowerCase();
            const prefix = `${String(familyPrefix || '').trim().toLowerCase()}_`;
            if (!id || !prefix || !id.startsWith(prefix)) return '';
            return id.slice(prefix.length).trim();
        }

        function buildLocalWasmVariantLabel(familyPrefix, variantToken) {
            const familyLabel = localWasmFamilyLabel(familyPrefix);
            const token = String(variantToken || '').trim().toLowerCase();
            if (!token) return familyLabel;
            if (token === 'baseline') return `${familyLabel} Baseline`;
            return `${familyLabel} ${localTitleCaseToken(token)}`;
        }

        function normalizeLocalWasmManifestSpec(moduleId, item) {
            const id = String(moduleId || '').trim();
            const src = (item && typeof item === 'object') ? item : null;
            if (!id || !src) return null;
            const scriptPath = String(src.scriptPath || '').trim();
            const wasmPath = String(src.wasmPath || '').trim();
            const factoryName = String(src.factoryName || '').trim();
            if (!scriptPath || !wasmPath || !factoryName) return null;
            return { id, scriptPath, wasmPath, factoryName };
        }

        async function getLocalWasmFamilyModuleSpecs(familyPrefix, fallbackSpecs = []) {
            const family = String(familyPrefix || '').trim().toLowerCase();
            if (!family) return [];
            const expectedPrefix = `${family}_`;
            const manifest = await loadLocalWasmManifest();
            const out = [];
            const seen = new Set();
            const pushSpec = (specLike, forcedId = '') => {
                const spec = normalizeLocalWasmManifestSpec(forcedId || (specLike && specLike.id ? specLike.id : ''), specLike);
                if (!spec || !spec.id.startsWith(expectedPrefix) || seen.has(spec.id)) return;
                seen.add(spec.id);
                out.push(spec);
            };

            if (manifest && manifest.modules && typeof manifest.modules === 'object') {
                for (const [moduleId, item] of Object.entries(manifest.modules)) {
                    const id = String(moduleId || '').trim();
                    if (!id.startsWith(expectedPrefix)) continue;
                    pushSpec(item, id);
                }
            }

            const fallbackList = Array.isArray(fallbackSpecs) ? fallbackSpecs : [];
            for (const fallback of fallbackList) {
                if (!fallback || typeof fallback !== 'object') continue;
                const id = String(fallback.id || '').trim();
                if (!id || !id.startsWith(expectedPrefix)) continue;
                pushSpec(fallback, id);
            }

            out.sort((a, b) => {
                const ta = localWasmVariantTokenFromId(a.id, family);
                const tb = localWasmVariantTokenFromId(b.id, family);
                if (ta === 'baseline' && tb !== 'baseline') return -1;
                if (tb === 'baseline' && ta !== 'baseline') return 1;
                return a.id.localeCompare(b.id);
            });
            return out;
        }

        function localRandom31() {
            if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
                const buf = new Uint32Array(1);
                window.crypto.getRandomValues(buf);
                return Number(buf[0] & 0x7fffffff);
            }
            return Math.floor(Math.random() * 0x80000000);
        }

        async function ensureLocalPyodide() {
            if (localPyodidePromise) return localPyodidePromise;
            localPyodidePromise = (async () => {
                if (typeof window.loadPyodide !== 'function') {
                    if (typeof loadScriptOnce !== 'function') {
                        throw new Error('Local generator runtime loader unavailable.');
                    }
                    await loadScriptOnce('https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js');
                }
                if (typeof window.loadPyodide !== 'function') {
                    throw new Error('Failed to load Pyodide for exact local generator parity.');
                }
                return await window.loadPyodide({
                    indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.27.2/full/'
                });
            })().catch((error) => {
                localPyodidePromise = null;
                throw error;
            });
            return localPyodidePromise;
        }

        async function getLocalGeneratorScriptSource() {
            if (localGeneratorScriptSourcePromise) return localGeneratorScriptSourcePromise;
            localGeneratorScriptSourcePromise = (async () => {
                if (typeof getRepoFileText === 'function') {
                    try {
                        return await getRepoFileText('utilities/generate_graphs.py');
                    } catch (_) {}
                }
                const resp = await fetch('utilities/generate_graphs.py', { cache: 'no-cache' });
                if (!resp.ok) throw new Error(`Failed to load utilities/generate_graphs.py (HTTP ${resp.status})`);
                return await resp.text();
            })().catch((error) => {
                localGeneratorScriptSourcePromise = null;
                throw error;
            });
            return localGeneratorScriptSourcePromise;
        }

        async function ensureLocalGeneratorBootstrap() {
            const pyodide = await ensureLocalPyodide();
            if (localGeneratorBootstrapReady) return pyodide;
            const source = await getLocalGeneratorScriptSource();
            pyodide.FS.mkdirTree('/capstone');
            pyodide.FS.writeFile('/capstone/generate_graphs.py', source, { encoding: 'utf8' });
            await pyodide.runPythonAsync(`
import contextlib, io, json, runpy, shutil, sys
from pathlib import Path

def capstone_run_local_generator(args, out_dir):
    out_dir_path = Path(out_dir)
    if out_dir_path.exists():
        shutil.rmtree(out_dir_path)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    prev_argv = sys.argv[:]
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    try:
        sys.argv = ["generate_graphs.py"] + [str(x) for x in args]
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            runpy.run_path("/capstone/generate_graphs.py", run_name="__main__")
    finally:
        sys.argv = prev_argv
    meta = {}
    meta_path = out_dir_path / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files = []
    for pstr in meta.get("files", []):
        p = Path(pstr)
        files.append({"path": p.as_posix(), "name": p.name, "text": p.read_text(encoding="utf-8")})
    return json.dumps({"stdout": out_buf.getvalue(), "stderr": err_buf.getvalue(), "metadata": meta, "files": files})
`);
            localGeneratorBootstrapReady = true;
            return pyodide;
        }

        function createLocalExactGeneratorSession(options = {}) {
            const algorithm = String(options.algorithm || '').trim().toLowerCase();
            const n = Number.isFinite(Number(options.n)) ? Math.floor(Number(options.n)) : null;
            const k = Number.isFinite(Number(options.k)) ? Math.floor(Number(options.k)) : null;
            const graphFamily = String(options.graphFamily || 'random_density').trim().toLowerCase() || 'random_density';
            const density = Number(options.density);
            const seedRaw = String(options.seed ?? '').trim();
            const hasUserSeed = /^-?\d+$/.test(seedRaw);
            const baseSeed = hasUserSeed ? parseInt(seedRaw, 10) : localRandom31();
            let counter = 0;
            let visSeed = null;

            const shouldSetVisSeed = (variant, iterTag) => {
                const v = String(variant || '');
                const t = String(iterTag || '');
                if (algorithm === 'dijkstra') return v === 'dijkstra_iter' && t === '1';
                if (algorithm === 'glasgow') return v === 'glasgow_iter' && t === '1';
                if (algorithm === 'vf3') return v === 'vf3_iter' && t === '1';
                if (algorithm === 'subgraph') return v === 'subgraph_iter' && t === '1';
                return false;
            };

            return {
                algorithm,
                baseSeed,
                hasUserSeed,
                get generatedSeed() { return baseSeed; },
                get counter() { return counter; },
                get visSeed() { return visSeed; },
                async generateForRun(variant, iterTag) {
                    counter += 1;
                    const derivedSeed = Number(baseSeed) + counter;
                    if (visSeed === null && shouldSetVisSeed(variant, iterTag)) {
                        visSeed = derivedSeed;
                    }
                    const pyodide = await ensureLocalGeneratorBootstrap();
                    const outDir = `/capstone/generated/${algorithm}/${String(variant || 'run')}/iter_${String(iterTag || '1')}`;
                    const args = [
                        '--algorithm', algorithm,
                        '--n', String(n),
                        '--graph-family', String(graphFamily),
                        '--density', String(density),
                        '--seed', String(derivedSeed),
                        '--out-dir', outDir
                    ];
                    if (algorithm !== 'dijkstra' && Number.isFinite(k)) {
                        args.push('--k', String(k));
                    }
                    const jsonText = await pyodide.runPythonAsync(
                        `capstone_run_local_generator(${JSON.stringify(args)}, ${JSON.stringify(outDir)})`
                    );
                    const payload = JSON.parse(String(jsonText || '{}'));
                    const files = Array.isArray(payload.files) ? payload.files : [];
                    return {
                        variant: String(variant || ''),
                        iterTag: String(iterTag || ''),
                        seed: derivedSeed,
                        metadata: payload && typeof payload.metadata === 'object' ? payload.metadata : {},
                        files: files.map(f => ({
                            path: String(f && f.path ? f.path : ''),
                            name: String(f && f.name ? f.name : ''),
                            text: String(f && f.text ? f.text : '')
                        }))
                    };
                }
            };
        }

        function localEdgeKey(a, b) {
            const x = Number(a);
            const y = Number(b);
            if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
            return x <= y ? [x, y] : [y, x];
        }

        function parseLocalLad(text, options = {}) {
            const opts = (options && typeof options === 'object') ? options : {};
            const forceVertexLabelled = opts.forceVertexLabelled === true;
            const forceStandard = opts.forceStandard === true;
            const preferVertexLabelled = !forceStandard && (forceVertexLabelled || opts.preferVertexLabelled !== false);
            const lines = String(text || '').replace(/\r/g, '').split('\n');
            let idx = 0;
            const nextLine = () => {
                while (idx < lines.length) {
                    const line = String(lines[idx++] || '').trim();
                    if (!line || line.startsWith('#')) continue;
                    return line;
                }
                return null;
            };
            const first = nextLine();
            const n = first ? parseInt(first, 10) : 0;
            const adjSets = Array.from({ length: Math.max(0, n) }, () => new Set());
            const labels = new Array(Math.max(0, n)).fill(0);
            for (let i = 0; i < n; i++) {
                const line = nextLine();
                if (!line) continue;
                const vals = line.split(/\s+/).map(Number).filter(v => Number.isFinite(v));
                if (!vals.length) continue;
                let useVertexLabelled = false;
                if (forceVertexLabelled) {
                    useVertexLabelled = true;
                } else if (forceStandard) {
                    useVertexLabelled = false;
                } else if (vals.length >= 2) {
                    if (vals[1] === (vals.length - 2)) {
                        useVertexLabelled = true;
                    } else if (preferVertexLabelled && vals[1] >= 0 && vals[1] <= (vals.length - 2)) {
                        useVertexLabelled = true;
                    }
                }
                let degree = vals[0];
                let start = 1;
                if (useVertexLabelled) {
                    labels[i] = vals[0];
                    degree = vals[1];
                    start = 2;
                }
                degree = Number.isInteger(degree) ? degree : Math.floor(Number(degree) || 0);
                if (degree < 0) degree = 0;
                for (let j = 0; j < degree && (start + j) < vals.length; j++) {
                    const v = vals[start + j];
                    if (Number.isInteger(v) && v >= 0 && v < n && v !== i) {
                        adjSets[i].add(v);
                        adjSets[v].add(i);
                    }
                }
            }
            return { adj: adjSets.map(s => Array.from(s).sort((a, b) => a - b)), labels };
        }

        function sanitizeLocalUndirectedParsedGraph(parsed) {
            const srcAdj = Array.isArray(parsed && parsed.adj) ? parsed.adj : [];
            const n = srcAdj.length;
            const cleanSets = Array.from({ length: n }, () => new Set());
            for (let u = 0; u < n; u++) {
                const neighbors = Array.isArray(srcAdj[u]) ? srcAdj[u] : [];
                for (const rawV of neighbors) {
                    const v = Number(rawV);
                    if (!Number.isInteger(v) || v < 0 || v >= n || v === u) continue;
                    cleanSets[u].add(v);
                    cleanSets[v].add(u);
                }
            }
            const labelsRaw = Array.isArray(parsed && parsed.labels) ? parsed.labels : [];
            const labels = Array.from({ length: n }, (_, i) => {
                const num = Number(labelsRaw[i]);
                return Number.isFinite(num) ? Math.trunc(num) : (i % 4);
            });
            return {
                adj: cleanSets.map((s) => Array.from(s).sort((a, b) => a - b)),
                labels
            };
        }

        function parseLocalVf(text) {
            const lines = String(text || '').replace(/\r/g, '').split('\n');
            let idx = 0;
            const nextNums = () => {
                while (idx < lines.length) {
                    const line = String(lines[idx++] || '');
                    const trimmed = line.trim();
                    if (!trimmed || trimmed.startsWith('#')) continue;
                    const nums = (line.match(/-?\d+/g) || []).map(Number).filter(v => Number.isFinite(v));
                    if (nums.length) return nums;
                }
                return null;
            };
            const header = nextNums();
            const n = header && header.length ? Math.max(0, Number(header[0])) : 0;
            const labels = new Array(n).fill(0);
            for (let i = 0; i < n; i++) {
                const row = nextNums();
                if (!row) break;
                if (row.length >= 2) labels[i] = Number(row[1]);
            }
            const adjSets = Array.from({ length: n }, () => new Set());
            for (let i = 0; i < n; i++) {
                const countLine = nextNums();
                if (!countLine) break;
                const edgeCount = Math.max(0, Number(countLine[0]) || 0);
                for (let k = 0; k < edgeCount; k++) {
                    const edgeNums = nextNums();
                    if (!edgeNums || !edgeNums.length) continue;
                    let j = null;
                    if (edgeNums.length >= 2) {
                        const a = Number(edgeNums[0]);
                        const b = Number(edgeNums[1]);
                        if (a === i && b >= 0 && b < n) j = b;
                        else if (b === i && a >= 0 && a < n) j = a;
                        else if (a >= 0 && a < n) j = a;
                        else if (b >= 0 && b < n) j = b;
                    } else {
                        const a = Number(edgeNums[0]);
                        if (a >= 0 && a < n) j = a;
                    }
                    if (Number.isInteger(j) && j !== i) {
                        adjSets[i].add(j);
                        adjSets[j].add(i);
                    }
                }
            }
            return { adj: adjSets.map(s => Array.from(s).sort((a, b) => a - b)), labels };
        }

        function getLocalGraphFormatFromFile(fileLike) {
            const path = String(
                (fileLike && (fileLike.path || fileLike.name)) ? (fileLike.path || fileLike.name) : ''
            ).trim().toLowerCase();
            if (path.endsWith('.lad')) return 'lad';
            if (path.endsWith('.vf') || path.endsWith('.grf')) return 'vf';
            return 'vf';
        }

        function serializeLocalLad(parsed, options = {}) {
            const adj = Array.isArray(parsed && parsed.adj) ? parsed.adj : [];
            const labels = Array.isArray(parsed && parsed.labels) ? parsed.labels : [];
            const forceVertexLabels = !!(options && options.vertexLabelled);
            const lines = [String(adj.length)];
            for (let i = 0; i < adj.length; i++) {
                const nbrs = Array.isArray(adj[i]) ? adj[i].map(Number).filter(v => Number.isInteger(v) && v >= 0 && v < adj.length && v !== i) : [];
                const uniq = Array.from(new Set(nbrs)).sort((a, b) => a - b);
                if (forceVertexLabels) {
                    const label = Number.isFinite(Number(labels[i])) ? Number(labels[i]) : 0;
                    lines.push(`${label} ${uniq.length}${uniq.length ? ` ${uniq.join(' ')}` : ''}`);
                } else {
                    lines.push(`${uniq.length}${uniq.length ? ` ${uniq.join(' ')}` : ''}`);
                }
            }
            return lines.join('\n') + '\n';
        }

        function serializeLocalVf(parsed) {
            const adj = Array.isArray(parsed && parsed.adj) ? parsed.adj : [];
            const labels = Array.isArray(parsed && parsed.labels) ? parsed.labels : [];
            const lines = [String(adj.length)];
            for (let i = 0; i < adj.length; i++) {
                const label = Number.isFinite(Number(labels[i])) ? Number(labels[i]) : 0;
                lines.push(`${i} ${label}`);
            }
            for (let i = 0; i < adj.length; i++) {
                const nbrs = Array.isArray(adj[i]) ? adj[i].map(Number).filter(v => Number.isInteger(v) && v >= 0 && v < adj.length && v !== i) : [];
                const uniq = Array.from(new Set(nbrs)).sort((a, b) => a - b);
                lines.push(String(uniq.length));
                for (const j of uniq) {
                    lines.push(`${i} ${j}`);
                }
            }
            return lines.join('\n') + '\n';
        }

        function parseLocalGraphByFormat(text, format) {
            const fmt = String(format || '').trim().toLowerCase();
            return fmt === 'lad' ? parseLocalLad(text) : parseLocalVf(text);
        }

        function buildLocalDualFormatGraphPair(opts = {}) {
            const patternText = String(opts.patternText || '');
            const targetText = String(opts.targetText || '');
            const patternFormat = String(opts.patternFormat || 'vf').trim().toLowerCase();
            const targetFormat = String(opts.targetFormat || 'vf').trim().toLowerCase();
            const patternParsedRaw = parseLocalGraphByFormat(patternText, patternFormat);
            const targetParsedRaw = parseLocalGraphByFormat(targetText, targetFormat);
            const patternParsed = sanitizeLocalUndirectedParsedGraph(patternParsedRaw);
            const targetParsed = sanitizeLocalUndirectedParsedGraph(targetParsedRaw);
            return {
                parsed: {
                    pattern: patternParsed,
                    target: targetParsed
                },
                vf: {
                    patternText: serializeLocalVf(patternParsed),
                    targetText: serializeLocalVf(targetParsed)
                },
                lad: {
                    patternText: serializeLocalLad(patternParsed, { vertexLabelled: true }),
                    targetText: serializeLocalLad(targetParsed, { vertexLabelled: true })
                },
                ladUnlabelled: {
                    patternText: serializeLocalLad(patternParsed, { vertexLabelled: false }),
                    targetText: serializeLocalLad(targetParsed, { vertexLabelled: false })
                }
            };
        }

        function dirnameFromPath(path) {
            const p = String(path || '');
            const slash = p.lastIndexOf('/');
            if (slash < 0) return '';
            return p.slice(0, slash);
        }

        function canonicalizeLocalSubgraphIterationFiles(files) {
            const entries = Array.isArray(files) ? files.filter(Boolean) : [];
            if (!entries.length) return null;

            const pickRoleExt = (roleNeedle, ext) => entries.find((entry) => {
                const name = String(entry && (entry.name || entry.path) ? (entry.name || entry.path) : '').toLowerCase();
                return name.includes(roleNeedle) && name.endsWith(ext);
            });
            const pickExt = (ext) => entries.filter((entry) => {
                const name = String(entry && (entry.name || entry.path) ? (entry.name || entry.path) : '').toLowerCase();
                return name.endsWith(ext);
            });

            const vfPattern = pickRoleExt('pattern', '.vf');
            const vfTarget = pickRoleExt('target', '.vf');
            const ladPattern = pickRoleExt('pattern', '.lad');
            const ladTarget = pickRoleExt('target', '.lad');

            let patternParsed = null;
            let targetParsed = null;
            let source = 'vf';
            if (vfPattern && vfTarget) {
                patternParsed = parseLocalVf(String(vfPattern.text || ''));
                targetParsed = parseLocalVf(String(vfTarget.text || ''));
                source = 'vf';
            } else if (ladPattern && ladTarget) {
                patternParsed = parseLocalLad(String(ladPattern.text || ''), { forceVertexLabelled: true });
                targetParsed = parseLocalLad(String(ladTarget.text || ''), { forceVertexLabelled: true });
                source = 'lad';
            } else {
                const vfAny = pickExt('.vf');
                const ladAny = pickExt('.lad');
                if (vfAny.length >= 2) {
                    patternParsed = parseLocalVf(String(vfAny[0].text || ''));
                    targetParsed = parseLocalVf(String(vfAny[1].text || ''));
                    source = 'vf';
                } else if (ladAny.length >= 2) {
                    patternParsed = parseLocalLad(String(ladAny[0].text || ''), { forceVertexLabelled: true });
                    targetParsed = parseLocalLad(String(ladAny[1].text || ''), { forceVertexLabelled: true });
                    source = 'lad';
                } else {
                    return null;
                }
            }

            const pattern = sanitizeLocalUndirectedParsedGraph(patternParsed);
            const target = sanitizeLocalUndirectedParsedGraph(targetParsed);
            const basePath = String(
                (vfPattern && vfPattern.path) ||
                (ladPattern && ladPattern.path) ||
                (entries[0] && entries[0].path) ||
                '__local/generated/subgraph'
            );
            const dir = dirnameFromPath(basePath) || '__local/generated/subgraph';
            const filesOut = [
                {
                    name: 'canonical_pattern.vf',
                    path: `${dir}/canonical_pattern.vf`,
                    text: serializeLocalVf(pattern)
                },
                {
                    name: 'canonical_target.vf',
                    path: `${dir}/canonical_target.vf`,
                    text: serializeLocalVf(target)
                },
                {
                    name: 'canonical_pattern.lad',
                    path: `${dir}/canonical_pattern.lad`,
                    text: serializeLocalLad(pattern, { vertexLabelled: true })
                },
                {
                    name: 'canonical_target.lad',
                    path: `${dir}/canonical_target.lad`,
                    text: serializeLocalLad(target, { vertexLabelled: true })
                }
            ];
            return { source, files: filesOut };
        }

        function buildLocalUndirectedEdgeSet(adj) {
            const set = new Set();
            const list = Array.isArray(adj) ? adj : [];
            for (let i = 0; i < list.length; i++) {
                const neighbors = Array.isArray(list[i]) ? list[i] : [];
                for (const rawV of neighbors) {
                    const v = Number(rawV);
                    if (!Number.isInteger(v) || v < 0 || v >= list.length || v === i) continue;
                    const a = i < v ? i : v;
                    const b = i < v ? v : i;
                    set.add(`${a}:${b}`);
                }
            }
            return set;
        }

        function compareLocalParsedGraphs(vfParsed, ladParsed, graphName) {
            const vfAdj = Array.isArray(vfParsed && vfParsed.adj) ? vfParsed.adj : [];
            const ladAdj = Array.isArray(ladParsed && ladParsed.adj) ? ladParsed.adj : [];
            const vfLabels = Array.isArray(vfParsed && vfParsed.labels) ? vfParsed.labels : [];
            const ladLabels = Array.isArray(ladParsed && ladParsed.labels) ? ladParsed.labels : [];
            const nVf = vfAdj.length;
            const nLad = ladAdj.length;
            const n = Math.min(nVf, nLad);
            const labelMismatches = [];
            for (let i = 0; i < n; i++) {
                const lVf = Number.isFinite(Number(vfLabels[i])) ? Number(vfLabels[i]) : 0;
                const lLad = Number.isFinite(Number(ladLabels[i])) ? Number(ladLabels[i]) : 0;
                if (lVf !== lLad) {
                    labelMismatches.push({ node: i, vf_label: lVf, lad_label: lLad });
                }
            }
            const vfEdges = buildLocalUndirectedEdgeSet(vfAdj);
            const ladEdges = buildLocalUndirectedEdgeSet(ladAdj);
            const missingEdges = [];
            for (const e of vfEdges) {
                if (!ladEdges.has(e)) missingEdges.push(e);
            }
            const extraEdges = [];
            for (const e of ladEdges) {
                if (!vfEdges.has(e)) extraEdges.push(e);
            }
            // Equivalence for this pipeline is adjacency-only (labels are informational).
            const equivalent = nVf === nLad && !missingEdges.length && !extraEdges.length;
            return {
                graph: graphName,
                equivalent,
                node_count_vf: nVf,
                node_count_lad: nLad,
                label_compare_ignored: true,
                label_mismatch_count: labelMismatches.length,
                label_mismatch_samples: labelMismatches.slice(0, 10),
                missing_edges_count: missingEdges.length,
                missing_edge_samples: missingEdges.slice(0, 10).map((k) => k.split(':').map(Number)),
                extra_edges_count: extraEdges.length,
                extra_edge_samples: extraEdges.slice(0, 10).map((k) => k.split(':').map(Number))
            };
        }

        function buildLocalVfLadEquivalenceReport(opts = {}) {
            const vfPatternText = String(opts.vfPatternText || '');
            const vfTargetText = String(opts.vfTargetText || '');
            const ladPatternText = String(opts.ladPatternText || '');
            const ladTargetText = String(opts.ladTargetText || '');
            const patternCmp = compareLocalParsedGraphs(parseLocalVf(vfPatternText), parseLocalLad(ladPatternText), 'pattern');
            const targetCmp = compareLocalParsedGraphs(parseLocalVf(vfTargetText), parseLocalLad(ladTargetText), 'target');
            const equivalent = !!(patternCmp.equivalent && targetCmp.equivalent);
            const summary = equivalent
                ? 'vf and lad encodings are mathematically identical for pattern and target.'
                : [
                    patternCmp.equivalent ? null : `pattern: nodes(vf=${patternCmp.node_count_vf},lad=${patternCmp.node_count_lad}), missing_edges=${patternCmp.missing_edges_count}, extra_edges=${patternCmp.extra_edges_count}`,
                    targetCmp.equivalent ? null : `target: nodes(vf=${targetCmp.node_count_vf},lad=${targetCmp.node_count_lad}), missing_edges=${targetCmp.missing_edges_count}, extra_edges=${targetCmp.extra_edges_count}`
                ].filter(Boolean).join('; ');
            return {
                equivalent,
                summary,
                pattern: patternCmp,
                target: targetCmp
            };
        }

        function extractLocalSolutionCount(text) {
            const lines = String(text || '')
                .replace(/\r/g, '')
                .split('\n')
                .map(line => String(line || '').trim())
                .filter(Boolean);
            if (!lines.length) return null;

            for (let i = lines.length - 1; i >= 0; i--) {
                let m = lines[i].match(/\bsolution[_\s-]*count\b\s*(?:=|:)?\s*(-?\d+)\b/i);
                if (!m) m = lines[i].match(/\b(?:solutions?|count)\b[^0-9-]*(-?\d+)\b/i);
                if (m) {
                    const n = Number(m[1]);
                    if (Number.isInteger(n)) return n;
                }
            }

            let timeLineIndex = -1;
            for (let i = lines.length - 1; i >= 0; i--) {
                if (/^time\s*:/i.test(lines[i]) || /time\b/i.test(lines[i])) {
                    timeLineIndex = i;
                    break;
                }
            }
            if (timeLineIndex > 0) {
                for (let i = timeLineIndex - 1; i >= 0; i--) {
                    if (/^-?\d+$/.test(lines[i])) {
                        const n = Number(lines[i]);
                        if (Number.isInteger(n)) return n;
                    }
                }
            }

            for (let i = lines.length - 1; i >= 0; i--) {
                if (/^-?\d+$/.test(lines[i])) {
                    const n = Number(lines[i]);
                    if (Number.isInteger(n)) return n;
                }
            }
            return null;
        }

        function extractRobustSolutionCount(text) {
            const normalized = String(text || '').replace(/\r/g, '');
            const lines = normalized.split('\n').map(line => String(line || '').trim()).filter(Boolean);
            if (!lines.length) return 0;

            const mappingCount = extractLocalMappingsFromText(normalized, Math.max(1, lines.length)).length;

            // Priority 1: Explicit solution_count keyword (= or :)
            for (let i = lines.length - 1; i >= 0; i--) {
                let m = lines[i].match(/\bsolution[_\s-]*count\b\s*[=:]\s*(-?\d+)\b/i);
                if (m) {
                    const n = Number(m[1]);
                    if (Number.isInteger(n)) return n;
                }
            }

            // Priority 2: Other keyword phrases ("N solutions", "solutions: N", "count: N")
            for (let i = lines.length - 1; i >= 0; i--) {
                let m = lines[i].match(/\b(?:solutions?|count)\b[^0-9-]*(-?\d+)\b/i);
                if (!m) m = lines[i].match(/\b(-?\d+)\s+solutions?\b/i);
                if (m) {
                    const n = Number(m[1]);
                    if (Number.isInteger(n)) return n;
                }
            }

            // Priority 3: Standalone integer on its own line (scan from end).
            for (let i = lines.length - 1; i >= 0; i--) {
                if (/^-?\d+$/.test(lines[i])) {
                    const n = Number(lines[i]);
                    if (Number.isInteger(n)) return n;
                }
            }

            // Priority 4: Fall back to counting mapping-style lines (workflow behavior),
            // then return 0 when output exists but does not include a numeric count.
            return mappingCount > 0 ? mappingCount : 0;
        }

        function extractLocalCountTimeMs(text) {
            const raw = String(text || '').replace(/\r/g, '');
            const lines = raw.split('\n').map(line => String(line || '').trim()).filter(Boolean);
            if (!lines.length) {
                // Mirror workflow parser behavior for Glasgow ChatGPT/Gemini: no output => no solutions.
                return { count: 0, timeMs: 0 };
            }

            let count = null;
            let timeMs = null;
            let mappingCount = 0;
            for (const line of lines) {
                if (/mapping\s*:/i.test(line)) {
                    mappingCount++;
                    continue;
                }
                if (/\btime\b/i.test(line) || /\bruntime\b/i.test(line)) {
                    const nums = line.match(/[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g);
                    if (nums && nums.length) {
                        const value = Number(nums[nums.length - 1]);
                        if (Number.isFinite(value)) timeMs = value;
                    }
                    continue;
                }
                if (/^-?\d+$/.test(line)) {
                    const value = Number(line);
                    if (Number.isInteger(value)) count = value;
                    continue;
                }
                let m = line.match(/\bsolution[_\s-]*count\b\s*(?:=|:)?\s*(-?\d+)\b/i);
                if (!m) m = line.match(/\b(?:count|solutions?)\b[^0-9-]*(-?\d+)\b/i);
                if (m) {
                    const value = Number(m[1]);
                    if (Number.isInteger(value)) count = value;
                }
            }

            if (count === null) count = mappingCount;
            if (timeMs === null) timeMs = 0;
            return { count, timeMs };
        }

        function parseLocalDijkstraCsv(text) {
            const lines = String(text || '').replace(/\r/g, '').split('\n');
            const comments = [];
            const rows = [];
            for (const raw of lines) {
                const trimmed = String(raw || '').trim();
                if (!trimmed) continue;
                if (trimmed.startsWith('#')) comments.push(trimmed);
                else rows.push(String(raw || ''));
            }

            let startLabel = '';
            let targetLabel = '';
            for (const c of comments) {
                const s = c.match(/\bstart\s*[:=]\s*([^\s,;]+)/i);
                const t = c.match(/\b(?:target|end)\s*[:=]\s*([^\s,;]+)/i);
                if (s && !startLabel) startLabel = s[1].trim();
                if (t && !targetLabel) targetLabel = t[1].trim();
            }

            const idMap = new Map();
            const labels = [];
            const getId = (label) => {
                const key = String(label);
                if (idMap.has(key)) return idMap.get(key);
                const id = labels.length;
                idMap.set(key, id);
                labels.push(key);
                return id;
            };

            const directed = [];
            let headerConsumed = false;
            for (const row of rows) {
                const cells = row.split(/[;,]/).map(v => String(v || '').trim());
                if (cells.length < 3) continue;
                const weight = Number(cells[2]);
                if (!Number.isFinite(weight)) {
                    if (!headerConsumed) {
                        headerConsumed = true;
                    }
                    continue;
                }
                const u = getId(cells[0]);
                const v = getId(cells[1]);
                directed.push([u, v, weight]);
                if (!startLabel) startLabel = cells[0];
                targetLabel = cells[1];
            }

            const n = labels.length;
            const directedAdj = Array.from({ length: n }, () => []);
            const undirectedSets = Array.from({ length: n }, () => new Set());
            for (const [u, v, w] of directed) {
                if (u < 0 || v < 0 || u >= n || v >= n) continue;
                directedAdj[u].push([v, w]);
                if (u !== v) {
                    undirectedSets[u].add(v);
                    undirectedSets[v].add(u);
                }
            }
            const undirectedAdj = undirectedSets.map(s => Array.from(s).sort((a, b) => a - b));

            const startIdx = idMap.has(startLabel) ? idMap.get(startLabel) : null;
            const targetIdx = idMap.has(targetLabel) ? idMap.get(targetLabel) : null;
            const dist = new Array(n).fill(Number.POSITIVE_INFINITY);
            const parent = new Array(n).fill(-1);
            if (Number.isInteger(startIdx) && startIdx >= 0 && startIdx < n) {
                dist[startIdx] = 0;
                const pq = [[0, startIdx]];
                while (pq.length) {
                    pq.sort((a, b) => a[0] - b[0]);
                    const [d, u] = pq.shift();
                    if (d !== dist[u]) continue;
                    if (u === targetIdx) break;
                    for (const [v, w] of directedAdj[u]) {
                        const nd = d + w;
                        if (nd < dist[v]) {
                            dist[v] = nd;
                            parent[v] = u;
                            pq.push([nd, v]);
                        }
                    }
                }
            }

            let pathNodes = [];
            let pathDistance = null;
            if (Number.isInteger(targetIdx) && targetIdx >= 0 && targetIdx < n && dist[targetIdx] !== Number.POSITIVE_INFINITY) {
                pathDistance = dist[targetIdx];
                let cur = targetIdx;
                while (cur !== -1) {
                    pathNodes.push(cur);
                    if (cur === startIdx) break;
                    cur = parent[cur];
                }
                if (!pathNodes.length || pathNodes[pathNodes.length - 1] !== startIdx) {
                    pathNodes = [];
                    pathDistance = null;
                } else {
                    pathNodes.reverse();
                }
            }

            return { adj: undirectedAdj, nodeLabels: labels, startLabel, targetLabel, startIdx, targetIdx, pathNodes, pathDistance };
        }

        function extractLocalMappingsFromText(text, limit = 25) {
            const raw = String(text || '');
            if (!raw) return [];
            const out = [];
            const seen = new Set();
            const max = Math.max(1, Math.floor(Number(limit) || 1));
            const addPairs = (pairs) => {
                if (!pairs || !pairs.length) return;
                const mapping = {};
                for (const p of pairs) {
                    mapping[Number(p[1])] = Number(p[2]);
                }
                const key = JSON.stringify(mapping);
                if (key === '{}' || seen.has(key)) return;
                seen.add(key);
                out.push(mapping);
            };

            for (const rawLine of raw.replace(/\r/g, '').split('\n')) {
                const line = String(rawLine || '').trim();
                if (!line) continue;

                // Glasgow style: "Mapping: (0 -> 12) (1 -> 7)" or "mapping = ..."
                let pairs = Array.from(line.matchAll(/\(\s*(\d+)\s*->\s*(\d+)\s*\)/g));
                if (pairs.length) {
                    addPairs(pairs);
                    if (out.length >= max) break;
                    continue;
                }

                // VF3 style: "0,4: 1,2: 2,7:"
                pairs = Array.from(line.matchAll(/(\d+)\s*,\s*(\d+)\s*:/g));
                if (pairs.length) {
                    addPairs(pairs);
                    if (out.length >= max) break;
                    continue;
                }

                // Generic arrow fallback for lines that mention mapping or include arrows.
                if (/mapping\s*[:=]/i.test(line) || /->/.test(line)) {
                    pairs = Array.from(line.matchAll(/(\d+)\s*->\s*(\d+)/g));
                    if (pairs.length) {
                        addPairs(pairs);
                        if (out.length >= max) break;
                        continue;
                    }
                    // Alternate mapping style: "0=12 1=7"
                    pairs = Array.from(line.matchAll(/(\d+)\s*=\s*(\d+)/g));
                    if (pairs.length) {
                        addPairs(pairs);
                        if (out.length >= max) break;
                        continue;
                    }
                }
            }

            if (!out.length) {
                // Last resort: parse a single aggregate mapping from the whole text.
                let pairs = Array.from(raw.matchAll(/\(\s*(\d+)\s*->\s*(\d+)\s*\)/g));
                if (!pairs.length) pairs = Array.from(raw.matchAll(/(\d+)\s*->\s*(\d+)/g));
                if (pairs.length) addPairs(pairs);
            }
            return out;
        }

        function findLocalSubgraphMappings(opts = {}) {
            const patternAdjRaw = Array.isArray(opts.patternAdj) ? opts.patternAdj : [];
            const targetAdjRaw = Array.isArray(opts.targetAdj) ? opts.targetAdj : [];
            const patternLabels = Array.isArray(opts.patternLabels) ? opts.patternLabels : [];
            const targetLabels = Array.isArray(opts.targetLabels) ? opts.targetLabels : [];
            const limit = Math.max(1, Math.min(64, Math.floor(Number(opts.limit) || 1)));
            const timeBudgetMs = Math.max(50, Math.min(5000, Math.floor(Number(opts.timeBudgetMs) || 600)));

            const pN = patternAdjRaw.length;
            const tN = targetAdjRaw.length;
            if (!pN || !tN || pN > tN) return [];

            const toAdjSet = (adj) => (Array.isArray(adj) ? adj : []).map((row) => {
                const set = new Set();
                if (Array.isArray(row)) {
                    for (const v of row) {
                        const n = Number(v);
                        if (Number.isInteger(n) && n >= 0) set.add(n);
                    }
                }
                return set;
            });
            const pAdj = toAdjSet(patternAdjRaw);
            const tAdj = toAdjSet(targetAdjRaw);
            if (pAdj.length !== pN || tAdj.length !== tN) return [];

            const pDeg = pAdj.map((s) => s.size);
            const tDeg = tAdj.map((s) => s.size);

            const hasLabelSignal = (() => {
                const norm = (arr) => arr.some((v) => Number.isFinite(Number(v)) && Number(v) !== 0);
                return norm(patternLabels) || norm(targetLabels);
            })();
            const labelsMatch = (p, t) => {
                if (!hasLabelSignal) return true;
                const pl = Number.isFinite(Number(patternLabels[p])) ? Number(patternLabels[p]) : 0;
                const tl = Number.isFinite(Number(targetLabels[t])) ? Number(targetLabels[t]) : 0;
                return pl === tl;
            };

            const candidates = [];
            for (let p = 0; p < pN; p++) {
                const cand = [];
                for (let t = 0; t < tN; t++) {
                    if (tDeg[t] < pDeg[p]) continue;
                    if (!labelsMatch(p, t)) continue;
                    cand.push(t);
                }
                if (!cand.length) return [];
                candidates.push(cand);
            }

            const order = Array.from({ length: pN }, (_, i) => i).sort((a, b) => {
                const dc = candidates[a].length - candidates[b].length;
                if (dc !== 0) return dc;
                return pDeg[b] - pDeg[a];
            });

            const mapping = new Array(pN).fill(-1);
            const used = new Array(tN).fill(false);
            const results = [];
            const nowMs = () => (typeof performance !== 'undefined' && performance && typeof performance.now === 'function')
                ? performance.now()
                : Date.now();
            const start = nowMs();
            const timedOut = () => (nowMs() - start) > timeBudgetMs;

            const isConsistent = (p, t) => {
                for (let q = 0; q < pN; q++) {
                    const tq = mapping[q];
                    if (!Number.isInteger(tq) || tq < 0) continue;
                    if (pAdj[p].has(q) && !tAdj[t].has(tq)) return false;
                    if (pAdj[q].has(p) && !tAdj[tq].has(t)) return false;
                }
                return true;
            };

            const dfs = (depth) => {
                if (results.length >= limit || timedOut()) return;
                if (depth >= order.length) {
                    const m = {};
                    for (let p = 0; p < pN; p++) {
                        const t = mapping[p];
                        if (Number.isInteger(t) && t >= 0) m[p] = t;
                    }
                    if (Object.keys(m).length === pN) results.push(m);
                    return;
                }

                const p = order[depth];
                for (const t of candidates[p]) {
                    if (used[t]) continue;
                    if (!isConsistent(p, t)) continue;
                    used[t] = true;
                    mapping[p] = t;
                    dfs(depth + 1);
                    mapping[p] = -1;
                    used[t] = false;
                    if (results.length >= limit || timedOut()) return;
                }
            };

            dfs(0);
            return results;
        }

        function buildLocalDijkstraVisualization(opts = {}) {
            const parsed = parseLocalDijkstraCsv(String(opts.inputText || ''));
            const iteration = Number.isFinite(Number(opts.iteration)) ? Number(opts.iteration) : 1;
            const seed = (opts.seed === null || opts.seed === undefined || opts.seed === '') ? null : opts.seed;
            const adj = Array.isArray(parsed.adj) ? parsed.adj : [];
            const solverSolutions = Array.isArray(opts.solverSolutions) ? opts.solverSolutions : [];

            const allEdges = new Set();
            for (let i = 0; i < adj.length; i++) {
                for (const j of (adj[i] || [])) {
                    if (i === j) continue;
                    const ek = localEdgeKey(i, j);
                    if (ek) allEdges.add(`${ek[0]}:${ek[1]}`);
                }
            }

            const maxNodes = 4000;
            const maxEdges = 4000;
            const allowedNodes = new Set(Array.from({ length: Math.min(adj.length, maxNodes) }, (_, i) => i));
            let truncated = adj.length > maxNodes;

            const filteredEdges = [];
            for (const [a, b] of Array.from(allEdges).map(k => k.split(':').map(Number)).sort((x, y) => (x[0] - y[0]) || (x[1] - y[1]))) {
                if (allowedNodes.has(a) && allowedNodes.has(b)) filteredEdges.push([a, b]);
                if (filteredEdges.length >= maxEdges) {
                    truncated = true;
                    break;
                }
            }
            const filteredEdgeSet = new Set(filteredEdges.map(([a, b]) => `${a}:${b}`));

            const nodes = [];
            for (let i = 0; i < Math.min(adj.length, maxNodes); i++) {
                nodes.push({ data: { id: String(i), label: String(parsed.nodeLabels && parsed.nodeLabels[i] !== undefined ? parsed.nodeLabels[i] : i) } });
            }
            const edges = filteredEdges.map(([a, b]) => ({ data: { id: `${a}-${b}`, source: String(a), target: String(b) } }));
            const nodeLabels = Array.isArray(parsed.nodeLabels) ? parsed.nodeLabels : [];
            const labelToId = new Map();
            const labelToIdLower = new Map();
            for (let i = 0; i < nodeLabels.length; i++) {
                const raw = String(nodeLabels[i] == null ? '' : nodeLabels[i]).trim();
                if (!raw) continue;
                if (!labelToId.has(raw)) labelToId.set(raw, i);
                const lower = raw.toLowerCase();
                if (!labelToIdLower.has(lower)) labelToIdLower.set(lower, i);
            }

            const parseDijkstraPathFromOutput = (outputText) => {
                const lines = String(outputText || '').replace(/\r/g, '').split('\n');
                const first = lines.map(line => String(line || '').trim()).find(line => line && !/^runtime\b/i.test(line));
                if (!first) return null;
                if (/no\s*path|path\s*not\s*found/i.test(first)) return null;

                const sep = first.indexOf(';');
                const left = sep >= 0 ? first.slice(0, sep).trim() : '';
                const right = sep >= 0 ? first.slice(sep + 1).trim() : first;
                if (/^inf$/i.test(left) || /^-1$/.test(left)) return null;

                const rightNorm = right.replace(/\s*->\s*/g, ' -> ');
                const rawTokens = rightNorm.split(/[,\s]+/).map(t => String(t || '').trim()).filter(Boolean);
                const cleanToken = (tok) => String(tok || '')
                    .replace(/^[\[\]{}()'"`]+/, '')
                    .replace(/[\[\]{}()'"`,;:]+$/, '')
                    .trim();
                const parseNodeId = (tok) => {
                    const t = cleanToken(tok);
                    if (!t || t === '->') return null;
                    if (labelToId.has(t)) return labelToId.get(t);
                    const lower = t.toLowerCase();
                    if (labelToIdLower.has(lower)) return labelToIdLower.get(lower);
                    const n = Number(t);
                    if (Number.isInteger(n) && n >= 0 && n < adj.length) return n;
                    return null;
                };
                const path = [];
                for (const tok of rawTokens) {
                    if (tok === '->') continue;
                    const id = parseNodeId(tok);
                    if (!Number.isInteger(id)) continue;
                    path.push(id);
                }
                if (!path.length) return null;
                const compact = [];
                for (const id of path) {
                    if (!compact.length || compact[compact.length - 1] !== id) compact.push(id);
                }
                if (compact.length < 2) return null;
                return compact;
            };

            const toDijkstraSolution = (pathNodesRaw, name = '') => {
                const src = Array.isArray(pathNodesRaw) ? pathNodesRaw : [];
                if (!src.length) return null;
                const keptNodes = [];
                for (const raw of src) {
                    const n = Number(raw);
                    if (!Number.isInteger(n) || n < 0 || n >= adj.length) continue;
                    if (!allowedNodes.has(n)) continue;
                    if (!keptNodes.includes(n)) keptNodes.push(n);
                }
                if (!keptNodes.length) return null;
                const keptEdges = [];
                for (let i = 0; i + 1 < src.length; i++) {
                    const ek = localEdgeKey(src[i], src[i + 1]);
                    if (!ek) continue;
                    const key = `${ek[0]}:${ek[1]}`;
                    if (filteredEdgeSet.has(key)) keptEdges.push(`${ek[0]}-${ek[1]}`);
                }
                const labels = src
                    .map(v => Number(v))
                    .filter(v => Number.isInteger(v) && v >= 0 && v < nodeLabels.length)
                    .map(v => String(nodeLabels[v] !== undefined ? nodeLabels[v] : v));
                return {
                    name: String(name || '').trim(),
                    mapping: [],
                    highlight_nodes: keptNodes,
                    highlight_edges: keptEdges,
                    path_labels: labels
                };
            };

            const solutions = [];
            const parsedFallbackPathNodes = Array.isArray(parsed.pathNodes) ? parsed.pathNodes : [];
            for (const raw of solverSolutions) {
                const entry = raw && typeof raw === 'object' ? raw : {};
                const name = String(entry.name || '').trim() || `Solver ${solutions.length + 1}`;
                const output = String(entry.output || '');
                const path = parseDijkstraPathFromOutput(output) || (parsedFallbackPathNodes.length ? parsedFallbackPathNodes : null);
                if (!Array.isArray(path) || !path.length) continue;
                const sol = toDijkstraSolution(path, name);
                if (sol) solutions.push(sol);
            }

            if (!solutions.length) {
                const fallbackPath = Array.isArray(parsed.pathNodes) ? parsed.pathNodes : [];
                const fallback = toDijkstraSolution(fallbackPath, 'Reference shortest path');
                if (fallback) solutions.push(fallback);
            }

            const fallbackHighlightNodes = [];
            if (Number.isInteger(parsed.startIdx)) fallbackHighlightNodes.push(parsed.startIdx);
            if (Number.isInteger(parsed.targetIdx) && parsed.targetIdx !== parsed.startIdx) fallbackHighlightNodes.push(parsed.targetIdx);
            const first = solutions[0] || null;
            const highlightNodes = first && Array.isArray(first.highlight_nodes) && first.highlight_nodes.length
                ? first.highlight_nodes.map(v => String(v))
                : fallbackHighlightNodes.filter(n => allowedNodes.has(n)).map(v => String(v));
            const highlightEdges = first && Array.isArray(first.highlight_edges) ? first.highlight_edges : [];
            const bestPathLabels = first && Array.isArray(first.path_labels) ? first.path_labels : [];

            const payload = {
                algorithm: 'dijkstra',
                seed,
                iteration,
                node_count: adj.length,
                edge_count: allEdges.size,
                nodes,
                edges,
                highlight_nodes: highlightNodes,
                highlight_edges: highlightEdges,
                pattern_node_count: 0,
                pattern_nodes: [],
                pattern_edges: [],
                solutions,
                no_solutions: solutions.length === 0,
                truncated
            };
            if (parsed.startLabel) payload.start_label = parsed.startLabel;
            if (parsed.targetLabel) payload.target_label = parsed.targetLabel;
            if (bestPathLabels.length) payload.shortest_path = bestPathLabels;
            if (Number.isFinite(Number(parsed.pathDistance))) payload.shortest_path_distance = Number(parsed.pathDistance);
            return payload;
        }

        function buildLocalVisualizationIterations(payloads) {
            const list = (Array.isArray(payloads) ? payloads : []).filter(Boolean);
            if (!list.length) return null;
            const root = Object.assign({}, list[0]);
            root.visualization_iterations = list;
            return root;
        }

        function buildLocalSubgraphLikeVisualization(opts = {}) {
            const algorithm = String(opts.algorithm || '').trim().toLowerCase();
            const patternText = String(opts.patternText || '');
            const targetText = String(opts.targetText || '');
            const patternFormat = String(opts.patternFormat || '').trim().toLowerCase() || (algorithm === 'glasgow' ? 'lad' : 'vf');
            const targetFormat = String(opts.targetFormat || '').trim().toLowerCase() || (algorithm === 'glasgow' ? 'lad' : 'vf');
            const patternNodes = Array.isArray(opts.patternNodes) ? opts.patternNodes.map(Number) : null;
            const iteration = Number.isFinite(Number(opts.iteration)) ? Number(opts.iteration) : 1;
            const seed = (opts.seed === null || opts.seed === undefined || opts.seed === '') ? null : opts.seed;
            const mappingSources = Array.isArray(opts.mappingSources) ? opts.mappingSources : [];

            const parseGraph = (fmt, text) => (fmt === 'lad' ? parseLocalLad(text) : parseLocalVf(text));
            const patternParsed = parseGraph(patternFormat, patternText);
            const targetParsed = parseGraph(targetFormat, targetText);
            const adjPattern = Array.isArray(patternParsed.adj) ? patternParsed.adj : [];
            const adjTarget = Array.isArray(targetParsed.adj) ? targetParsed.adj : [];
            const patternLabels = Array.isArray(patternParsed.labels) ? patternParsed.labels : [];
            const targetLabels = Array.isArray(targetParsed.labels) ? targetParsed.labels : [];

            const targetEdges = new Set();
            for (let i = 0; i < adjTarget.length; i++) {
                for (const j of (adjTarget[i] || [])) {
                    if (i === j) continue;
                    const ek = localEdgeKey(i, j);
                    if (ek) targetEdges.add(`${ek[0]}:${ek[1]}`);
                }
            }

            const patternEdges = [];
            const patternEdgeSet = new Set();
            for (let i = 0; i < adjPattern.length; i++) {
                for (const j of (adjPattern[i] || [])) {
                    if (i === j) continue;
                    const ek = localEdgeKey(i, j);
                    if (!ek) continue;
                    const key = `${ek[0]}:${ek[1]}`;
                    if (patternEdgeSet.has(key)) continue;
                    patternEdgeSet.add(key);
                    patternEdges.push([ek[0], ek[1]]);
                }
            }
            patternEdges.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));

            const solutionLimit = 2000;
            const normalizeMappings = (rawMappings) => {
                const inList = Array.isArray(rawMappings) ? rawMappings : [];
                const out = [];
                const seen = new Set();
                const parseMaybeIndex = (value) => {
                    const num = Number(value);
                    if (Number.isInteger(num)) return num;
                    const m = String(value == null ? '' : value).match(/-?\d+/);
                    if (!m) return null;
                    const parsed = Number(m[0]);
                    return Number.isInteger(parsed) ? parsed : null;
                };
                const pCount = adjPattern.length;
                const tCount = adjTarget.length;

                for (const mappingObj of inList) {
                    if (!mappingObj || typeof mappingObj !== 'object') continue;
                    const pairs = [];
                    for (const [pk, tv] of Object.entries(mappingObj)) {
                        const p = parseMaybeIndex(pk);
                        const t = parseMaybeIndex(tv);
                        if (Number.isInteger(p) && Number.isInteger(t)) pairs.push([p, t]);
                    }
                    if (!pairs.length) continue;

                    const allowPatternShift = pCount > 0 && pairs.every(([p]) => p >= 1 && p <= pCount);
                    const allowTargetShift = tCount > 0 && pairs.every(([, t]) => t >= 1 && t <= tCount);
                    const variants = [[0, 0]];
                    if (allowPatternShift) variants.push([-1, 0]);
                    if (allowTargetShift) variants.push([0, -1]);
                    if (allowPatternShift && allowTargetShift) variants.push([-1, -1]);

                    let best = null;
                    let bestScore = -1;
                    let bestPenalty = Number.POSITIVE_INFINITY;
                    for (const [patternShift, targetShift] of variants) {
                        const normalized = {};
                        for (const [pRaw, tRaw] of pairs) {
                            const p = pRaw + patternShift;
                            const t = tRaw + targetShift;
                            if (!Number.isInteger(p) || !Number.isInteger(t)) continue;
                            if (p < 0 || p >= pCount) continue;
                            if (t < 0 || t >= tCount) continue;
                            normalized[p] = t;
                        }
                        const score = Object.keys(normalized).length;
                        if (!score) continue;
                        const penalty = Math.abs(patternShift) + Math.abs(targetShift);
                        if (score > bestScore || (score === bestScore && penalty < bestPenalty)) {
                            best = normalized;
                            bestScore = score;
                            bestPenalty = penalty;
                        }
                    }
                    if (!best) continue;

                    const key = JSON.stringify(best);
                    if (key === '{}' || seen.has(key)) continue;
                    seen.add(key);
                    out.push(best);
                    if (out.length >= solutionLimit) break;
                }
                return out;
            };
            let mappings = [];
            for (const src of mappingSources) {
                const found = extractLocalMappingsFromText(src, solutionLimit);
                if (found.length) mappings = mappings.concat(found);
                if (mappings.length >= solutionLimit) break;
            }
            mappings = normalizeMappings(mappings);
            if (!mappings.length && patternNodes && patternNodes.length) {
                const fallback = {};
                patternNodes.forEach((t, p) => {
                    if (Number.isInteger(t)) fallback[p] = t;
                });
                if (Object.keys(fallback).length) mappings = [fallback];
            }
            mappings = normalizeMappings(mappings);
            if (!mappings.length) {
                const discovered = findLocalSubgraphMappings({
                    patternAdj: adjPattern,
                    targetAdj: adjTarget,
                    patternLabels,
                    targetLabels,
                    limit: solutionLimit,
                    timeBudgetMs: 750
                });
                if (Array.isArray(discovered) && discovered.length) {
                    mappings = discovered;
                }
            }
            mappings = normalizeMappings(mappings);
            if (!mappings.length && algorithm === 'glasgow') {
                // Some Glasgow local runs can provide mappings with incompatible label/index conventions.
                // For visualization fallback, retry a label-agnostic structural match.
                const discovered = findLocalSubgraphMappings({
                    patternAdj: adjPattern,
                    targetAdj: adjTarget,
                    patternLabels: [],
                    targetLabels: [],
                    limit: solutionLimit,
                    timeBudgetMs: 2000
                });
                if (Array.isArray(discovered) && discovered.length) {
                    mappings = normalizeMappings(discovered);
                }
            }

            const maxNodes = 4000;
            const maxEdges = 4000;
            const allowedNodes = new Set(Array.from({ length: Math.min(adjTarget.length, maxNodes) }, (_, i) => i));
            let truncated = adjTarget.length > maxNodes;

            const filteredEdges = [];
            for (const [a, b] of Array.from(targetEdges).map(k => k.split(':').map(Number)).sort((x, y) => (x[0] - y[0]) || (x[1] - y[1]))) {
                if (allowedNodes.has(a) && allowedNodes.has(b)) filteredEdges.push([a, b]);
                if (filteredEdges.length >= maxEdges) {
                    truncated = true;
                    break;
                }
            }
            const filteredEdgeSet = new Set(filteredEdges.map(([a, b]) => `${a}:${b}`));

            const nodes = [];
            for (let i = 0; i < Math.min(adjTarget.length, maxNodes); i++) {
                nodes.push({ data: { id: String(i), label: String(i) } });
            }
            const edges = filteredEdges.map(([a, b]) => ({ data: { id: `${a}-${b}`, source: String(a), target: String(b) } }));

            const mappingToSolution = (mappingObj) => {
                if (!mappingObj || typeof mappingObj !== 'object') return null;
                const mapping = new Array(adjPattern.length).fill(null);
                for (const [pk, tv] of Object.entries(mappingObj)) {
                    const p = Number(pk);
                    const t = Number(tv);
                    if (Number.isInteger(p) && Number.isInteger(t) && p >= 0 && p < mapping.length) {
                        mapping[p] = t;
                    }
                }
                const highlightNodes = mapping.filter(v => Number.isInteger(v));
                const highlightEdges = [];
                for (const [a, b] of patternEdges) {
                    const ta = mapping[a];
                    const tb = mapping[b];
                    if (!Number.isInteger(ta) || !Number.isInteger(tb)) continue;
                    const ek = localEdgeKey(ta, tb);
                    if (!ek) continue;
                    const key = `${ek[0]}:${ek[1]}`;
                    if (targetEdges.has(key)) highlightEdges.push(key);
                }
                return { mapping, highlightNodes, highlightEdges };
            };

            const solutions = [];
            const seen = new Set();
            for (const m of mappings) {
                const sol = mappingToSolution(m);
                if (!sol) continue;
                const key = JSON.stringify(sol.mapping);
                if (seen.has(key)) continue;
                seen.add(key);
                const keptNodes = sol.highlightNodes.filter(n => allowedNodes.has(n));
                const keptEdges = sol.highlightEdges
                    .filter(k => filteredEdgeSet.has(k))
                    .map(k => {
                        const [a, b] = k.split(':').map(Number);
                        return `${a}-${b}`;
                    });
                solutions.push({
                    mapping: sol.mapping,
                    highlight_nodes: keptNodes,
                    highlight_edges: keptEdges
                });
                if (solutions.length >= solutionLimit) break;
            }

            const first = solutions[0] || null;
            return {
                algorithm,
                seed,
                iteration,
                node_count: adjTarget.length,
                edge_count: targetEdges.size,
                nodes,
                edges,
                highlight_nodes: first ? first.highlight_nodes.map(v => String(v)) : [],
                highlight_edges: first ? first.highlight_edges : [],
                pattern_node_count: adjPattern.length,
                pattern_nodes: first ? first.mapping : [],
                pattern_edges: patternEdges.map(([a, b]) => [a, b]),
                solutions,
                no_solutions: solutions.length === 0,
                truncated
            };
        }

        async function runDijkstraLocally(runCtx, iterations, warmup) {
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));

            const inputFile = (config.selectedFiles && config.selectedFiles[0]) ? config.selectedFiles[0] : null;
            if (!inputFile || !inputFile.path) {
                throw new Error('Dijkstra requires one input file');
            }

            const inputName = sanitizeFsFilename(inputFile.name || 'input');
            const inputFsPath = `/inputs/${inputName}`;

            const inputText = await getRepoFileText(inputFile.path);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const resolveDijkstraInputForIteration = (iterIndex) => {
                const generated = getLocalGeneratedIterationInput('dijkstra', iterIndex);
                const generatedFiles = generated && Array.isArray(generated.selectedFiles) ? generated.selectedFiles : null;
                const generatedInput = generatedFiles && generatedFiles[0] ? generatedFiles[0] : null;
                const generatedPath = generatedInput && generatedInput.path ? String(generatedInput.path) : '';
                let text = inputText;
                if (generatedPath && _localInMemoryRepoFiles.has(generatedPath)) {
                    text = String(_localInMemoryRepoFiles.get(generatedPath) || '');
                }
                return {
                    inputText: String(text || ''),
                    seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed')
                        ? generated.seed
                        : null
                };
            };
            const firstDijkstraInput = resolveDijkstraInputForIteration(0);

            const dijkstraSpecs = await getLocalWasmFamilyModuleSpecs('dijkstra', [
                {
                    id: 'dijkstra_baseline',
                    scriptPath: 'wasm/dijkstra_baseline.js',
                    wasmPath: 'wasm/dijkstra_baseline.wasm',
                    factoryName: 'createDijkstraBaselineModule'
                },
                {
                    id: 'dijkstra_llm',
                    scriptPath: 'wasm/dijkstra_llm.js',
                    wasmPath: 'wasm/dijkstra_llm.wasm',
                    factoryName: 'createDijkstraLlmModule'
                },
                {
                    id: 'dijkstra_chatgpt',
                    scriptPath: 'wasm/dijkstra_chatgpt.js',
                    wasmPath: 'wasm/dijkstra_chatgpt.wasm',
                    factoryName: 'createDijkstraChatgptModule'
                },
                {
                    id: 'dijkstra_gemini',
                    scriptPath: 'wasm/dijkstra_gemini.js',
                    wasmPath: 'wasm/dijkstra_gemini.wasm',
                    factoryName: 'createDijkstraGeminiModule'
                }
            ]);
            const baselineSpec = dijkstraSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'dijkstra') === 'baseline') || null;
            if (!baselineSpec) {
                throw new Error('Missing Dijkstra baseline local WASM module (`dijkstra_baseline`) in `wasm/manifest.json`.');
            }
            const llmSpec = dijkstraSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'dijkstra') === 'llm') ||
                dijkstraSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'dijkstra') === 'chatgpt') ||
                null;
            const geminiSpec = dijkstraSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'dijkstra') === 'gemini') || null;
            const extraVariantSpecs = dijkstraSpecs.filter((spec) => {
                const id = String(spec && spec.id ? spec.id : '');
                if (!id) return false;
                if (baselineSpec && id === baselineSpec.id) return false;
                if (llmSpec && id === llmSpec.id) return false;
                if (geminiSpec && id === geminiSpec.id) return false;
                return true;
            });
            const llmToken = llmSpec ? (localWasmVariantTokenFromId(llmSpec.id, 'dijkstra') || 'llm') : 'llm';
            const geminiToken = geminiSpec ? (localWasmVariantTokenFromId(geminiSpec.id, 'dijkstra') || 'gemini') : 'gemini';
            const llmLabel = llmSpec ? buildLocalWasmVariantLabel('dijkstra', llmToken) : 'Dijkstra Llm';
            const geminiLabel = geminiSpec ? buildLocalWasmVariantLabel('dijkstra', geminiToken) : 'Dijkstra Gemini';
            const ticksPerIter = 1 + (llmSpec ? 1 : 0) + (geminiSpec ? 1 : 0) + extraVariantSpecs.length;
            const setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            const testsTotal = safeIterations * ticksPerIter;

            progressReset('dijkstra', safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter: ticksPerIter
            });

            const abortSignal = runCtx && runCtx.abortController ? runCtx.abortController.signal : null;

            const writeInput = (mod, textForRun = firstDijkstraInput.inputText) => {
                ensureEmscriptenDir(mod, '/inputs');
                writeEmscriptenTextFile(mod, inputFsPath, String(textForRun || ''));
            };

            const unloadModule = (spec) => {
                try {
                    invalidateEmscriptenModule(spec && spec.id ? spec.id : '');
                } catch (_) {}
            };

            const loadFreshModule = async (spec, textForRun = firstDijkstraInput.inputText) => {
                const mod = await getFreshEmscriptenModule(spec);
                writeInput(mod, textForRun);
                return mod;
            };
            const loadFreshModuleMeasured = async (spec, textForRun = firstDijkstraInput.inputText) => {
                const t0 = runTimerNowMs();
                const mod = await loadFreshModule(spec, textForRun);
                await flushEmscriptenWorkerFsOps(mod);
                const t1 = runTimerNowMs();
                return { mod, refreshMs: Math.max(0, t1 - t0) };
            };

            try {
                // Phase 1: setup + warmup (progress bar fills once)
                if (safeWarmup > 0) {
                    let setupDone = 0;
                    const warmupInput = resolveDijkstraInputForIteration(0);
                    const warmupOrder = [baselineSpec]
                        .concat(llmSpec ? [llmSpec] : [])
                        .concat(geminiSpec ? [geminiSpec] : [])
                        .concat(extraVariantSpecs);
                    for (const spec of warmupOrder) {
                        if (!spec || !spec.id) continue;
                        const token = localWasmVariantTokenFromId(spec.id, 'dijkstra');
                        const label = buildLocalWasmVariantLabel('dijkstra', token || spec.id);
                        let mod = await loadFreshModule(spec, warmupInput.inputText);
                        try {
                            for (let i = 0; i < safeWarmup; i++) {
                                if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                                progressSetDeterminate(`Warming up: ${label}`, setupDone, setupTotal, { stage: 'setup' });
                                try {
                                    await runEmscriptenMain(mod, [inputFsPath]);
                                } catch (error) {
                                    const msg = error && error.message ? error.message : String(error);
                                    throw new Error(`Warmup ${i + 1}/${safeWarmup} - ${label}: ${msg}`);
                                }
                                setupDone++;
                                progressSetDeterminate(`Warming up: ${label}`, setupDone, setupTotal, { stage: 'setup' });
                                await delay(0, abortSignal);
                            }
                        } finally {
                            mod = null;
                            unloadModule(spec);
                        }
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
                const baselineHeapKiB = [];
                const llmHeapKiB = [];
                const geminiHeapKiB = [];
                const baselineRefreshMs = [];
                const llmRefreshMs = [];
                const geminiRefreshMs = [];
                const extraVariantState = extraVariantSpecs.map((spec) => ({
                    spec,
                    token: localWasmVariantTokenFromId(spec.id, 'dijkstra') || spec.id,
                    metricKey: localWasmVariantTokenFromId(spec.id, 'dijkstra') || spec.id,
                    label: buildLocalWasmVariantLabel('dijkstra', localWasmVariantTokenFromId(spec.id, 'dijkstra') || spec.id),
                    times: [],
                    heapKiB: [],
                    refreshMs: [],
                    output: '',
                    outputsByIteration: new Array(safeIterations).fill('')
                }));
                let baselineResult = '';
                let llmResult = '';
                let geminiResult = '';
                let memoryMetricInfo = null;
                const baselineOutputsByIteration = new Array(safeIterations).fill('');
                const llmOutputsByIteration = new Array(safeIterations).fill('');
                const geminiOutputsByIteration = new Array(safeIterations).fill('');

                // Baseline chunk
                for (let iter = 0; iter < safeIterations; iter++) {
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                    progressSetDeterminate('Dijkstra baseline', ticksDone, testsTotal, { stage: 'tests' });
                    const iterInput = resolveDijkstraInputForIteration(iter);
                    const loaded = await loadFreshModuleMeasured(baselineSpec, iterInput.inputText);
                    let mod = loaded.mod;
                    baselineRefreshMs.push(loaded.refreshMs);
                    try {
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
                        const heapKiB = getEmscriptenHeapPeakKiB(mod);
                        if (Number.isFinite(Number(heapKiB))) baselineHeapKiB.push(Number(heapKiB));
                        memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                        baselineResult = parseFirstLine(stdout) || stdout.trim();
                        baselineOutputsByIteration[iter] = stdout;
                    } finally {
                        mod = null;
                        unloadModule(baselineSpec);
                    }
                    ticksDone++;
                    progressSetDeterminate('Dijkstra baseline', ticksDone, testsTotal, { stage: 'tests' });
                    await delay(0, abortSignal);
                }

                // LLM chunk
                if (llmSpec) {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate(llmLabel, ticksDone, testsTotal, { stage: 'tests' });
                        const iterInput = resolveDijkstraInputForIteration(iter);
                        const loaded = await loadFreshModuleMeasured(llmSpec, iterInput.inputText);
                        let mod = loaded.mod;
                        llmRefreshMs.push(loaded.refreshMs);
                        try {
                            const t0 = runTimerNowMs();
                            let stdout = '';
                            try {
                                const res = await runEmscriptenMain(mod, [inputFsPath]);
                                stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Iteration ${iter + 1}/${safeIterations} - ${llmLabel}: ${msg}`);
                            }
                            const t1 = runTimerNowMs();
                            llmTimes.push(Math.max(0, t1 - t0));
                            const heapKiB = getEmscriptenHeapPeakKiB(mod);
                            if (Number.isFinite(Number(heapKiB))) llmHeapKiB.push(Number(heapKiB));
                            memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                            llmResult = parseFirstLine(stdout) || stdout.trim();
                            llmOutputsByIteration[iter] = stdout;
                        } finally {
                            mod = null;
                            unloadModule(llmSpec);
                        }
                        ticksDone++;
                        progressSetDeterminate(llmLabel, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                }

                // Gemini chunk
                if (geminiSpec) {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate(geminiLabel, ticksDone, testsTotal, { stage: 'tests' });
                        const iterInput = resolveDijkstraInputForIteration(iter);
                        const loaded = await loadFreshModuleMeasured(geminiSpec, iterInput.inputText);
                        let mod = loaded.mod;
                        geminiRefreshMs.push(loaded.refreshMs);
                        try {
                            const t0 = runTimerNowMs();
                            let stdout = '';
                            try {
                                const res = await runEmscriptenMain(mod, [inputFsPath]);
                                stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Iteration ${iter + 1}/${safeIterations} - ${geminiLabel}: ${msg}`);
                            }
                            const t1 = runTimerNowMs();
                            geminiTimes.push(Math.max(0, t1 - t0));
                            const heapKiB = getEmscriptenHeapPeakKiB(mod);
                            if (Number.isFinite(Number(heapKiB))) geminiHeapKiB.push(Number(heapKiB));
                            memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                            geminiResult = parseFirstLine(stdout) || stdout.trim();
                            geminiOutputsByIteration[iter] = stdout;
                        } finally {
                            mod = null;
                            unloadModule(geminiSpec);
                        }
                        ticksDone++;
                        progressSetDeterminate(geminiLabel, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                }

                // Additional dynamically discovered variants
                for (const extra of extraVariantState) {
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        progressSetDeterminate(extra.label, ticksDone, testsTotal, { stage: 'tests' });
                        const iterInput = resolveDijkstraInputForIteration(iter);
                        const loaded = await loadFreshModuleMeasured(extra.spec, iterInput.inputText);
                        let mod = loaded.mod;
                        extra.refreshMs.push(loaded.refreshMs);
                        try {
                            const t0 = runTimerNowMs();
                            let stdout = '';
                            try {
                                const res = await runEmscriptenMain(mod, [inputFsPath]);
                                stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`Iteration ${iter + 1}/${safeIterations} - ${extra.label}: ${msg}`);
                            }
                            const t1 = runTimerNowMs();
                            extra.times.push(Math.max(0, t1 - t0));
                            const heapKiB = getEmscriptenHeapPeakKiB(mod);
                            if (Number.isFinite(Number(heapKiB))) extra.heapKiB.push(Number(heapKiB));
                            memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                            extra.output = parseFirstLine(stdout) || stdout.trim();
                            extra.outputsByIteration[iter] = stdout;
                        } finally {
                            mod = null;
                            unloadModule(extra.spec);
                        }
                        ticksDone++;
                        progressSetDeterminate(extra.label, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                }

                progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

                const sBaseline = calcStatsMs(baselineTimes);
                const sLlm = calcStatsMs(llmTimes);
                const sGemini = calcStatsMs(geminiTimes);
                const mBaseline = calcStatsMs(baselineHeapKiB);
                const mLlm = calcStatsMs(llmHeapKiB);
                const mGemini = calcStatsMs(geminiHeapKiB);
                const rBaseline = calcStatsMs(baselineRefreshMs);
                const rLlm = calcStatsMs(llmRefreshMs);
                const rGemini = calcStatsMs(geminiRefreshMs);
                for (const extra of extraVariantState) {
                    extra.sTime = calcStatsMs(extra.times);
                    extra.sMem = calcStatsMs(extra.heapKiB);
                    extra.sRefresh = calcStatsMs(extra.refreshMs);
                }
                const resolvedMemoryMetricInfo = memoryMetricInfo || getDefaultWasmMemoryMetricInfo();
                const memoryPrefix = formatWasmMemoryStatsPrefix(resolvedMemoryMetricInfo);

                const lines = [];
                const addSection = (title, _result, stats, memStats) => {
                    lines.push(`[${title}]`);
                    if (stats) {
                        lines.push(formatStatsMsSummary('Runtime (ms): ', stats));
                        lines.push(formatAlignedLabelValueRow('Samples', String(stats.n)));
                    }
                    if (memStats) {
                        lines.push(formatStatsMsSummary(memoryPrefix, memStats));
                    }
                    lines.push('');
                };

                addSection('Dijkstra Baseline', baselineResult, sBaseline, mBaseline);
                if (llmSpec) addSection(llmLabel, llmResult, sLlm, mLlm);
                if (geminiSpec) addSection(geminiLabel, geminiResult, sGemini, mGemini);
                for (const extra of extraVariantState) {
                    addSection(extra.label, extra.output, extra.sTime, extra.sMem);
                }

                let visualization = null;
                try {
                    if (typeof buildLocalDijkstraVisualization === 'function' && typeof buildLocalVisualizationIterations === 'function') {
                        const payloads = [];
                        for (let iter = 0; iter < safeIterations; iter++) {
                            const iterInput = resolveDijkstraInputForIteration(iter);
                            payloads.push(buildLocalDijkstraVisualization({
                                inputText: iterInput.inputText,
                                iteration: iter + 1,
                                seed: iterInput.seed,
                                solverSolutions: [
                                    { name: 'Dijkstra Baseline', output: baselineOutputsByIteration[iter] || '' },
                                    ...(llmSpec ? [{ name: llmLabel, output: llmOutputsByIteration[iter] || '' }] : []),
                                    ...(geminiSpec ? [{ name: geminiLabel, output: geminiOutputsByIteration[iter] || '' }] : []),
                                    ...extraVariantState.map(extra => ({ name: extra.label, output: extra.outputsByIteration[iter] || '' }))
                                ]
                            }));
                        }
                        visualization = buildLocalVisualizationIterations(payloads);
                    }
                } catch (_) {}

                const result = {
                    algorithm: 'dijkstra',
                    status: 'success',
                    output: lines.join('\n'),
                    iterations: safeIterations,
                    warmup: safeWarmup,
                    timings_ms: {},
                    timings_ms_stdev: {},
                    memory_kb: {},
                    memory_kb_stdev: {},
                    memory_metric_kind: resolvedMemoryMetricInfo.kind,
                    memory_metric_label: resolvedMemoryMetricInfo.label,
                    memory_metric_unit: resolvedMemoryMetricInfo.unit,
                    local_wasm_module_refresh_ms: {},
                    local_wasm_module_refresh_ms_stdev: {},
                    variant_metadata: []
                };
                if (sBaseline) {
                    result.timings_ms.baseline = sBaseline.median;
                    result.timings_ms_stdev.baseline = sBaseline.stdev;
                }
                if (sLlm) {
                    result.timings_ms[llmToken] = sLlm.median;
                    result.timings_ms_stdev[llmToken] = sLlm.stdev;
                    if (llmToken === 'llm') {
                        result.timings_ms.chatgpt = sLlm.median;
                        result.timings_ms_stdev.chatgpt = sLlm.stdev;
                    } else if (llmToken === 'chatgpt') {
                        result.timings_ms.llm = sLlm.median;
                        result.timings_ms_stdev.llm = sLlm.stdev;
                    }
                }
                if (sGemini) {
                    result.timings_ms[geminiToken] = sGemini.median;
                    result.timings_ms_stdev[geminiToken] = sGemini.stdev;
                }
                if (mBaseline) {
                    result.memory_kb.baseline = mBaseline.median;
                    result.memory_kb_stdev.baseline = mBaseline.stdev;
                }
                if (mLlm) {
                    result.memory_kb[llmToken] = mLlm.median;
                    result.memory_kb_stdev[llmToken] = mLlm.stdev;
                    if (llmToken === 'llm') {
                        result.memory_kb.chatgpt = mLlm.median;
                        result.memory_kb_stdev.chatgpt = mLlm.stdev;
                    } else if (llmToken === 'chatgpt') {
                        result.memory_kb.llm = mLlm.median;
                        result.memory_kb_stdev.llm = mLlm.stdev;
                    }
                }
                if (mGemini) {
                    result.memory_kb[geminiToken] = mGemini.median;
                    result.memory_kb_stdev[geminiToken] = mGemini.stdev;
                }
                if (rBaseline) {
                    result.local_wasm_module_refresh_ms.baseline = rBaseline.median;
                    result.local_wasm_module_refresh_ms_stdev.baseline = rBaseline.stdev;
                }
                if (rLlm) {
                    result.local_wasm_module_refresh_ms[llmToken] = rLlm.median;
                    result.local_wasm_module_refresh_ms_stdev[llmToken] = rLlm.stdev;
                    if (llmToken === 'llm') {
                        result.local_wasm_module_refresh_ms.chatgpt = rLlm.median;
                        result.local_wasm_module_refresh_ms_stdev.chatgpt = rLlm.stdev;
                    } else if (llmToken === 'chatgpt') {
                        result.local_wasm_module_refresh_ms.llm = rLlm.median;
                        result.local_wasm_module_refresh_ms_stdev.llm = rLlm.stdev;
                    }
                }
                if (rGemini) {
                    result.local_wasm_module_refresh_ms[geminiToken] = rGemini.median;
                    result.local_wasm_module_refresh_ms_stdev[geminiToken] = rGemini.stdev;
                }
                for (const extra of extraVariantState) {
                    if (extra.sTime) {
                        result.timings_ms[extra.metricKey] = extra.sTime.median;
                        result.timings_ms_stdev[extra.metricKey] = extra.sTime.stdev;
                    }
                    if (extra.sMem) {
                        result.memory_kb[extra.metricKey] = extra.sMem.median;
                        result.memory_kb_stdev[extra.metricKey] = extra.sMem.stdev;
                    }
                    if (extra.sRefresh) {
                        result.local_wasm_module_refresh_ms[extra.metricKey] = extra.sRefresh.median;
                        result.local_wasm_module_refresh_ms_stdev[extra.metricKey] = extra.sRefresh.stdev;
                    }
                }
                result.variant_metadata.push({
                    variant_id: baselineSpec.id,
                    label: 'Dijkstra Baseline',
                    role: 'baseline',
                    timing_key: 'baseline',
                    memory_key: 'baseline'
                });
                if (llmSpec) {
                    result.variant_metadata.push({
                        variant_id: llmSpec.id,
                        label: llmLabel,
                        role: 'variant',
                        timing_key: llmToken,
                        memory_key: llmToken
                    });
                }
                if (geminiSpec) {
                    result.variant_metadata.push({
                        variant_id: geminiSpec.id,
                        label: geminiLabel,
                        role: 'variant',
                        timing_key: geminiToken,
                        memory_key: geminiToken
                    });
                }
                for (const extra of extraVariantState) {
                    result.variant_metadata.push({
                        variant_id: extra.spec.id,
                        label: extra.label,
                        role: 'variant',
                        timing_key: extra.metricKey,
                        memory_key: extra.metricKey
                    });
                }
                if (!Object.keys(result.memory_kb).length) delete result.memory_kb;
                if (!Object.keys(result.memory_kb_stdev).length) delete result.memory_kb_stdev;
                if (!Object.keys(result.local_wasm_module_refresh_ms).length) delete result.local_wasm_module_refresh_ms;
                if (!Object.keys(result.local_wasm_module_refresh_ms_stdev).length) delete result.local_wasm_module_refresh_ms_stdev;
                if (!Array.isArray(result.variant_metadata) || !result.variant_metadata.length) delete result.variant_metadata;
                if (visualization) {
                    result.visualization = visualization;
                }

                return { status: 'success', output: lines.join('\n'), result };
            } finally {
                unloadModule(baselineSpec);
                unloadModule(llmSpec);
                unloadModule(geminiSpec);
                for (const extra of extraVariantSpecs) unloadModule(extra);
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

            let ticksPerIter = 6; // recalculated after module discovery
            let setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            let testsTotal = safeIterations * ticksPerIter;

            const patternName = sanitizeFsFilename(patternFile.name || 'pattern');
            const targetName = sanitizeFsFilename(targetFile.name || 'target');
            const patternFsPath = `/inputs/${patternName}`;
            const targetFsPath = `/inputs/${targetName}`;

            const [patternText, targetText] = await Promise.all([
                getRepoFileText(patternFile.path),
                getRepoFileText(targetFile.path)
            ]);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const resolveVf3InputForIteration = (iterIndex) => {
                const generated = getLocalGeneratedIterationInput('vf3', iterIndex);
                const generatedFiles = generated && Array.isArray(generated.selectedFiles) ? generated.selectedFiles : null;
                const generatedPattern = generatedFiles && generatedFiles[0] ? generatedFiles[0] : null;
                const generatedTarget = generatedFiles && generatedFiles[1] ? generatedFiles[1] : null;
                const generatedPatternPath = generatedPattern && generatedPattern.path ? String(generatedPattern.path) : '';
                const generatedTargetPath = generatedTarget && generatedTarget.path ? String(generatedTarget.path) : '';

                let patternTextForIter = patternText;
                let targetTextForIter = targetText;
                if (generatedPatternPath && _localInMemoryRepoFiles.has(generatedPatternPath)) {
                    patternTextForIter = String(_localInMemoryRepoFiles.get(generatedPatternPath) || '');
                }
                if (generatedTargetPath && _localInMemoryRepoFiles.has(generatedTargetPath)) {
                    targetTextForIter = String(_localInMemoryRepoFiles.get(generatedTargetPath) || '');
                }
                return {
                    patternText: String(patternTextForIter || ''),
                    targetText: String(targetTextForIter || ''),
                    seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed')
                        ? generated.seed
                        : null
                };
            };
            const firstVf3Input = resolveVf3InputForIteration(0);

            const vf3Specs = await getLocalWasmFamilyModuleSpecs('vf3', [
                {
                    id: 'vf3_baseline',
                    scriptPath: 'wasm/vf3_baseline.js',
                    wasmPath: 'wasm/vf3_baseline.wasm',
                    factoryName: 'createVf3BaselineModule'
                },
                {
                    id: 'vf3_chatgpt',
                    scriptPath: 'wasm/vf3_chatgpt.js',
                    wasmPath: 'wasm/vf3_chatgpt.wasm',
                    factoryName: 'createVf3ChatgptModule'
                },
                {
                    id: 'vf3_gemini',
                    scriptPath: 'wasm/vf3_gemini.js',
                    wasmPath: 'wasm/vf3_gemini.wasm',
                    factoryName: 'createVf3GeminiModule'
                }
            ]);
            const baselineSpec = vf3Specs.find(spec => localWasmVariantTokenFromId(spec.id, 'vf3') === 'baseline') || null;
            if (!baselineSpec) {
                throw new Error('Missing VF3 baseline local WASM module (`vf3_baseline`) in `wasm/manifest.json`.');
            }
            const chatgptSpec = vf3Specs.find(spec => localWasmVariantTokenFromId(spec.id, 'vf3') === 'chatgpt') || null;
            const geminiSpec = vf3Specs.find(spec => localWasmVariantTokenFromId(spec.id, 'vf3') === 'gemini') || null;
            const extraVariantSpecs = vf3Specs.filter((spec) => {
                const id = String(spec && spec.id ? spec.id : '');
                if (!id) return false;
                if (id === baselineSpec.id) return false;
                if (chatgptSpec && id === chatgptSpec.id) return false;
                if (geminiSpec && id === geminiSpec.id) return false;
                return true;
            });
            ticksPerIter = 2 + (chatgptSpec ? 2 : 0) + (geminiSpec ? 2 : 0) + (extraVariantSpecs.length * 2);
            setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            testsTotal = safeIterations * ticksPerIter;
            const chatToken = chatgptSpec ? (localWasmVariantTokenFromId(chatgptSpec.id, 'vf3') || 'chatgpt') : 'chatgpt';
            const gemToken = geminiSpec ? (localWasmVariantTokenFromId(geminiSpec.id, 'vf3') || 'gemini') : 'gemini';
            const chatLabel = chatgptSpec ? buildLocalWasmVariantLabel('vf3', chatToken) : 'VF3 Chatgpt';
            const gemLabel = geminiSpec ? buildLocalWasmVariantLabel('vf3', gemToken) : 'VF3 Gemini';
            progressReset('vf3', safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter: ticksPerIter
            });

            const writeInputs = (mod, inputForRun = firstVf3Input) => {
                ensureEmscriptenDir(mod, '/inputs');
                writeEmscriptenTextFile(mod, patternFsPath, String(inputForRun && inputForRun.patternText ? inputForRun.patternText : ''));
                writeEmscriptenTextFile(mod, targetFsPath, String(inputForRun && inputForRun.targetText ? inputForRun.targetText : ''));
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

            const loadFreshModule = async (spec, label, done, total, stage, inputForRun = firstVf3Input) => {
                if (label) {
                    const current = Number.isFinite(Number(done)) ? Number(done) : 0;
                    const denom = Number.isFinite(Number(total)) ? Number(total) : 1;
                    progressSetDeterminate(label, current, Math.max(1, denom), { stage });
                }
                const mod = await getFreshEmscriptenModule(spec);
                writeInputs(mod, inputForRun);
                return mod;
            };
            const loadFreshModuleMeasured = async (spec, label, done, total, stage, inputForRun = firstVf3Input) => {
                const t0 = runTimerNowMs();
                const mod = await loadFreshModule(spec, label, done, total, stage, inputForRun);
                await flushEmscriptenWorkerFsOps(mod);
                const t1 = runTimerNowMs();
                return { mod, refreshMs: Math.max(0, t1 - t0) };
            };

            try {
                const warmupSolver = async (title, spec, labelFirst, argsFirst, labelAll, argsAll, setupDoneRef, inputForRun) => {
                    let mod = await loadFreshModule(spec, `Loading ${title} WASM...`, setupDoneRef.value, setupTotal, 'setup', inputForRun || firstVf3Input);
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
                        ['-u', '-r', '0', '-F', patternFsPath, targetFsPath],
                        'VF3 baseline all',
                        ['-u', '-r', '0', patternFsPath, targetFsPath],
                        setupDoneRef,
                        firstVf3Input
                    );
                    if (geminiSpec) {
                        await warmupSolver(
                            gemLabel,
                            geminiSpec,
                            `${gemLabel} first`,
                            ['--first-only', patternFsPath, targetFsPath],
                            `${gemLabel} all`,
                            [patternFsPath, targetFsPath],
                            setupDoneRef,
                            firstVf3Input
                        );
                    }
                    if (chatgptSpec) {
                        await warmupSolver(
                            chatLabel,
                            chatgptSpec,
                            `${chatLabel} first`,
                            ['--first-only', patternFsPath, targetFsPath],
                            `${chatLabel} all`,
                            [patternFsPath, targetFsPath],
                            setupDoneRef,
                            firstVf3Input
                        );
                    }
                    for (const extraSpec of extraVariantSpecs) {
                        const token = localWasmVariantTokenFromId(extraSpec.id, 'vf3') || extraSpec.id;
                        const label = buildLocalWasmVariantLabel('vf3', token);
                        await warmupSolver(
                            label,
                            extraSpec,
                            `${label} first`,
                            ['--first-only', patternFsPath, targetFsPath],
                            `${label} all`,
                            [patternFsPath, targetFsPath],
                            setupDoneRef,
                            firstVf3Input
                        );
                    }
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
                const baseFirstHeapKiB = [];
                const baseAllHeapKiB = [];
                const gemFirstHeapKiB = [];
                const gemAllHeapKiB = [];
                const chatFirstHeapKiB = [];
                const chatAllHeapKiB = [];
                const baseFirstRefreshMs = [];
                const baseAllRefreshMs = [];
                const gemFirstRefreshMs = [];
                const gemAllRefreshMs = [];
                const chatFirstRefreshMs = [];
                const chatAllRefreshMs = [];
                const extraVariantState = extraVariantSpecs.map((spec) => ({
                    spec,
                    token: localWasmVariantTokenFromId(spec.id, 'vf3') || spec.id,
                    keyBase: localWasmVariantTokenFromId(spec.id, 'vf3') || spec.id,
                    label: buildLocalWasmVariantLabel('vf3', localWasmVariantTokenFromId(spec.id, 'vf3') || spec.id),
                    first: [],
                    all: [],
                    firstHeapKiB: [],
                    allHeapKiB: [],
                    firstRefreshMs: [],
                    allRefreshMs: [],
                    firstVisualizationByIter: new Array(safeIterations).fill(''),
                    allVisualizationByIter: new Array(safeIterations).fill(''),
                    allVisualizationOut: '',
                    result: ''
                }));
                let baseResult = '';
                let gemResult = '';
                let chatResult = '';
                let baseAllVisualizationOut = '';
                let gemAllVisualizationOut = '';
                let chatAllVisualizationOut = '';
                const baseFirstVisualizationByIter = new Array(safeIterations).fill('');
                const gemFirstVisualizationByIter = new Array(safeIterations).fill('');
                const chatFirstVisualizationByIter = new Array(safeIterations).fill('');
                const baseAllVisualizationByIter = new Array(safeIterations).fill('');
                const gemAllVisualizationByIter = new Array(safeIterations).fill('');
                const chatAllVisualizationByIter = new Array(safeIterations).fill('');
                let memoryMetricInfo = null;

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
                    const heapsFirst = Array.isArray(opts && opts.heapsFirst ? opts.heapsFirst : null) ? opts.heapsFirst : null;
                    const heapsAll = Array.isArray(opts && opts.heapsAll ? opts.heapsAll : null) ? opts.heapsAll : null;
                    const refreshFirst = Array.isArray(opts && opts.refreshFirst ? opts.refreshFirst : null) ? opts.refreshFirst : null;
                    const refreshAll = Array.isArray(opts && opts.refreshAll ? opts.refreshAll : null) ? opts.refreshAll : null;
                    const captureFirst = typeof (opts && opts.captureFirst) === 'function' ? opts.captureFirst : null;
                    const captureAll = typeof (opts && opts.captureAll) === 'function' ? opts.captureAll : null;

                    if (!spec || !spec.id) throw new Error(`Invalid wasm spec for ${title}`);
                    if (!timesFirst || !timesAll) throw new Error(`Invalid timing arrays for ${title}`);

                    const isTrapError = (error) => {
                        const msg = error && error.message ? String(error.message) : String(error);
                        const lower = msg.toLowerCase();
                        return lower.includes('function signature mismatch') ||
                            lower.includes('memory access out of bounds') ||
                            lower.includes('out of bounds memory access') ||
                            lower.includes('unreachable');
                    };

                    const runStepMeasuredFresh = async (iter, stepLabel, args, times, captureStdout = null, heapArr = null, refreshArr = null, inputForRun = firstVf3Input) => {
                        for (let attempt = 0; attempt < 2; attempt++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            const loaded = await loadFreshModuleMeasured(spec, `Loading ${title} WASM...`, ticksDone, testsTotal, 'tests', inputForRun);
                            let mod = loaded.mod;
                            if (refreshArr) refreshArr.push(loaded.refreshMs);
                            try {
                                const t0 = runTimerNowMs();
                                const res = await runEmscriptenMain(mod, args);
                                const t1 = runTimerNowMs();
                                times.push(Math.max(0, t1 - t0));
                                if (heapArr) {
                                    const heapKiB = getEmscriptenHeapPeakKiB(mod);
                                    if (Number.isFinite(Number(heapKiB))) heapArr.push(Number(heapKiB));
                                }
                                memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                                if (captureStdout) {
                                    const stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                                    const stderr = res && typeof res.stderr === 'string' ? res.stderr : '';
                                    const combined = [stdout, stderr].filter(part => typeof part === 'string' && part.trim()).join('\n');
                                    try { captureStdout(combined || stdout || stderr || ''); } catch (_) {}
                                }
                                return null;
                            } catch (error) {
                                const msg = error && error.message ? error.message : String(error);
                                const canRecover = isTrapError(error) && attempt === 0;
                                if (!canRecover) {
                                    throw new Error(`Iteration ${iter + 1}/${safeIterations} - ${stepLabel}: ${msg}`);
                                }
                            } finally {
                                mod = null;
                                unloadModule(spec);
                                await delay(0, abortSignal);
                            }
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        }
                        return null;
                    };
                    for (let iter = 0; iter < safeIterations; iter++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        const iterInput = resolveVf3InputForIteration(iter);

                        progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                        const captureFirstThisIter = captureFirst
                            ? ((stdout) => captureFirst(stdout, iter))
                            : null;
                        const firstRes = await runStepMeasuredFresh(iter, labelFirst, argsFirst, timesFirst, captureFirstThisIter, heapsFirst, refreshFirst, iterInput);
                        if (firstRes && firstRes.status === 'aborted') return firstRes;
                        ticksDone++;
                        progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);

                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

                        progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                        const captureAllThisIter = captureAll
                            ? ((stdout) => captureAll(stdout, iter))
                            : null;
                        const allRes = await runStepMeasuredFresh(iter, labelAll, argsAll, timesAll, captureAllThisIter, heapsAll, refreshAll, iterInput);
                        if (allRes && allRes.status === 'aborted') return allRes;
                        ticksDone++;
                        progressSetDeterminate(title, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                    }
                    return null;
                };

                const baselineRun = await runMeasuredSolver({
                    title: 'VF3 baseline',
                    spec: baselineSpec,
                    labelFirst: 'VF3 baseline first',
                    argsFirst: ['-u', '-r', '0', '-F', patternFsPath, targetFsPath],
                    labelAll: 'VF3 baseline all',
                    argsAll: ['-u', '-r', '0', patternFsPath, targetFsPath],
                    timesFirst: baseFirst,
                    timesAll: baseAll,
                    heapsFirst: baseFirstHeapKiB,
                    heapsAll: baseAllHeapKiB,
                    refreshFirst: baseFirstRefreshMs,
                    refreshAll: baseAllRefreshMs,
                    captureFirst: (stdout, iterIndex) => {
                        if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < baseFirstVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                            baseFirstVisualizationByIter[iterIndex] = stdout;
                        }
                    },
                    captureAll: (stdout, iterIndex) => {
                        if (!baseAllVisualizationOut && typeof stdout === 'string' && stdout.trim()) {
                            baseAllVisualizationOut = stdout;
                        }
                        if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < baseAllVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                            baseAllVisualizationByIter[iterIndex] = stdout;
                        }
                        const line = parseFirstLine(stdout);
                        baseResult = parseFirstToken(line) || line;
                    }
                });
                if (baselineRun && baselineRun.status === 'aborted') return baselineRun;

                if (geminiSpec) {
                    const geminiRun = await runMeasuredSolver({
                        title: gemLabel,
                        spec: geminiSpec,
                        labelFirst: `${gemLabel} first`,
                        argsFirst: ['--first-only', patternFsPath, targetFsPath],
                        labelAll: `${gemLabel} all`,
                        argsAll: [patternFsPath, targetFsPath],
                        timesFirst: gemFirst,
                        timesAll: gemAll,
                        heapsFirst: gemFirstHeapKiB,
                        heapsAll: gemAllHeapKiB,
                        refreshFirst: gemFirstRefreshMs,
                        refreshAll: gemAllRefreshMs,
                        captureFirst: (stdout, iterIndex) => {
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < gemFirstVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                gemFirstVisualizationByIter[iterIndex] = stdout;
                            }
                        },
                        captureAll: (stdout, iterIndex) => {
                            if (!gemAllVisualizationOut && typeof stdout === 'string' && stdout.trim()) {
                                gemAllVisualizationOut = stdout;
                            }
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < gemAllVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                gemAllVisualizationByIter[iterIndex] = stdout;
                            }
                            gemResult = parseFirstLine(stdout);
                        }
                    });
                    if (geminiRun && geminiRun.status === 'aborted') return geminiRun;
                }

                if (chatgptSpec) {
                    const chatgptRun = await runMeasuredSolver({
                        title: chatLabel,
                        spec: chatgptSpec,
                        labelFirst: `${chatLabel} first`,
                        argsFirst: ['--first-only', patternFsPath, targetFsPath],
                        labelAll: `${chatLabel} all`,
                        argsAll: [patternFsPath, targetFsPath],
                        timesFirst: chatFirst,
                        timesAll: chatAll,
                        heapsFirst: chatFirstHeapKiB,
                        heapsAll: chatAllHeapKiB,
                        refreshFirst: chatFirstRefreshMs,
                        refreshAll: chatAllRefreshMs,
                        captureFirst: (stdout, iterIndex) => {
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < chatFirstVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                chatFirstVisualizationByIter[iterIndex] = stdout;
                            }
                        },
                        captureAll: (stdout, iterIndex) => {
                            if (!chatAllVisualizationOut && typeof stdout === 'string' && stdout.trim()) {
                                chatAllVisualizationOut = stdout;
                            }
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < chatAllVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                chatAllVisualizationByIter[iterIndex] = stdout;
                            }
                            chatResult = parseFirstLine(stdout);
                        }
                    });
                    if (chatgptRun && chatgptRun.status === 'aborted') return chatgptRun;
                }

                for (const extra of extraVariantState) {
                    const extraRun = await runMeasuredSolver({
                        title: extra.label,
                        spec: extra.spec,
                        labelFirst: `${extra.label} first`,
                        argsFirst: ['--first-only', patternFsPath, targetFsPath],
                        labelAll: `${extra.label} all`,
                        argsAll: [patternFsPath, targetFsPath],
                        timesFirst: extra.first,
                        timesAll: extra.all,
                        heapsFirst: extra.firstHeapKiB,
                        heapsAll: extra.allHeapKiB,
                        refreshFirst: extra.firstRefreshMs,
                        refreshAll: extra.allRefreshMs,
                        captureFirst: (stdout, iterIndex) => {
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < extra.firstVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                extra.firstVisualizationByIter[iterIndex] = stdout;
                            }
                        },
                        captureAll: (stdout, iterIndex) => {
                            if (!extra.allVisualizationOut && typeof stdout === 'string' && stdout.trim()) {
                                extra.allVisualizationOut = stdout;
                            }
                            if (Number.isInteger(iterIndex) && iterIndex >= 0 && iterIndex < extra.allVisualizationByIter.length && typeof stdout === 'string' && stdout.trim()) {
                                extra.allVisualizationByIter[iterIndex] = stdout;
                            }
                            extra.result = parseFirstLine(stdout);
                        }
                    });
                    if (extraRun && extraRun.status === 'aborted') return extraRun;
                }

                let baselineVisualizationOut = baseAllVisualizationOut || '';
                if (!extractLocalMappingsFromText(baselineVisualizationOut, 1).length && !(runCtx && runCtx.aborted)) {
                    // Match the GitHub Actions visualizer path: run baseline VF3 once with solution-print flags.
                    let visMod = null;
                    try {
                        visMod = await loadFreshModule(
                            baselineSpec,
                            'Loading VF3 visualization baseline...',
                            ticksDone,
                            testsTotal,
                            'tests',
                            firstVf3Input
                        );
                        const visRes = await runEmscriptenMain(visMod, ['-u', '-s', '-r', '0', patternFsPath, targetFsPath], {
                            captureOptions: {
                                maxOutputChars: 262144,
                                maxErrorChars: 65536
                            }
                        });
                        const visStdout = visRes && typeof visRes.stdout === 'string' ? visRes.stdout : '';
                        const visStderr = visRes && typeof visRes.stderr === 'string' ? visRes.stderr : '';
                        const visOut = [visStdout, visStderr].filter(part => typeof part === 'string' && part.trim()).join('\n');
                        if (visOut.trim()) baselineVisualizationOut = visOut;
                    } catch (_) {
                        baselineVisualizationOut = baselineVisualizationOut || baseAllVisualizationOut || '';
                    } finally {
                        visMod = null;
                        unloadModule(baselineSpec);
                    }
                }

                progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

                const sBaseFirst = calcStatsMs(baseFirst);
                const sBaseAll = calcStatsMs(baseAll);
                const sGemFirst = calcStatsMs(gemFirst);
                const sGemAll = calcStatsMs(gemAll);
                const sChatFirst = calcStatsMs(chatFirst);
                const sChatAll = calcStatsMs(chatAll);
                const mBaseFirst = calcStatsMs(baseFirstHeapKiB);
                const mBaseAll = calcStatsMs(baseAllHeapKiB);
                const mGemFirst = calcStatsMs(gemFirstHeapKiB);
                const mGemAll = calcStatsMs(gemAllHeapKiB);
                const mChatFirst = calcStatsMs(chatFirstHeapKiB);
                const mChatAll = calcStatsMs(chatAllHeapKiB);
                const rBaseFirst = calcStatsMs(baseFirstRefreshMs);
                const rBaseAll = calcStatsMs(baseAllRefreshMs);
                const rGemFirst = calcStatsMs(gemFirstRefreshMs);
                const rGemAll = calcStatsMs(gemAllRefreshMs);
                const rChatFirst = calcStatsMs(chatFirstRefreshMs);
                const rChatAll = calcStatsMs(chatAllRefreshMs);
                const resolvedMemoryMetricInfo = memoryMetricInfo || getDefaultWasmMemoryMetricInfo();
                const memoryPrefix = formatWasmMemoryStatsPrefix(resolvedMemoryMetricInfo);

                // Compute per-iteration match_counts: compare ChatGPT and Gemini counts to baseline.
                // VF3 output format: first number on the first non-empty line is the solution count.
                const extractVf3Count = (stdout) => {
                    const text = String(stdout || '').replace(/\r/g, '');
                    for (const ln of text.split('\n')) {
                        const trimmed = ln.trim();
                        if (!trimmed) continue;
                        const m = trimmed.match(/^(-?\d+)/);
                        if (m) {
                            const n = Number(m[1]);
                            if (Number.isInteger(n)) return n;
                        }
                        break;
                    }
                    return extractLocalSolutionCount(stdout);
                };

                let vf3Success = 0;
                let vf3Fail = 0;
                let chatMatchCount = 0;
                let chatTotalCount = 0;
                let chatMismatchCount = 0;
                let gemMatchCount = 0;
                let gemTotalCount = 0;
                let gemMismatchCount = 0;
                const baselineCountByIter = [];
                const chatCountByIter = [];
                const gemCountByIter = [];
                for (const extra of extraVariantState) {
                    extra.matchCount = 0;
                    extra.totalCount = 0;
                    extra.mismatchCount = 0;
                    extra.countByIter = [];
                    extra.sFirst = calcStatsMs(extra.first);
                    extra.sAll = calcStatsMs(extra.all);
                    extra.mFirst = calcStatsMs(extra.firstHeapKiB);
                    extra.mAll = calcStatsMs(extra.allHeapKiB);
                    extra.rFirst = calcStatsMs(extra.firstRefreshMs);
                    extra.rAll = calcStatsMs(extra.allRefreshMs);
                }

                for (let iter = 0; iter < safeIterations; iter++) {
                    const baselineCount = extractVf3Count(baseAllVisualizationByIter[iter] || '');
                    if (!Number.isInteger(baselineCount)) {
                        vf3Fail++;
                        baselineCountByIter.push('NA');
                        chatCountByIter.push('NA');
                        gemCountByIter.push('NA');
                        for (const extra of extraVariantState) {
                            extra.countByIter.push('NA');
                        }
                        continue;
                    }
                    vf3Success++;
                    baselineCountByIter.push(String(baselineCount));

                    if (chatgptSpec) {
                        chatTotalCount++;
                        const chatCount = extractVf3Count(chatAllVisualizationByIter[iter] || '');
                        if (Number.isInteger(chatCount) && chatCount === baselineCount) {
                            chatMatchCount++;
                        } else {
                            chatMismatchCount++;
                        }
                        chatCountByIter.push(Number.isInteger(chatCount) ? String(chatCount) : 'NA');
                    } else {
                        chatCountByIter.push('NA');
                    }

                    if (geminiSpec) {
                        gemTotalCount++;
                        const gemCount = extractVf3Count(gemAllVisualizationByIter[iter] || '');
                        if (Number.isInteger(gemCount) && gemCount === baselineCount) {
                            gemMatchCount++;
                        } else {
                            gemMismatchCount++;
                        }
                        gemCountByIter.push(Number.isInteger(gemCount) ? String(gemCount) : 'NA');
                    } else {
                        gemCountByIter.push('NA');
                    }
                    for (const extra of extraVariantState) {
                        extra.totalCount++;
                        const count = extractVf3Count(extra.allVisualizationByIter[iter] || '');
                        if (Number.isInteger(count) && count === baselineCount) {
                            extra.matchCount++;
                        } else {
                            extra.mismatchCount++;
                        }
                        extra.countByIter.push(Number.isInteger(count) ? String(count) : 'NA');
                    }
                }

                const lines = [];
                const formatSolutionCountBlock = (label, rawCounts) => {
                    const counts = Array.isArray(rawCounts)
                        ? rawCounts.map((value) => {
                            const text = String(value == null ? '' : value).trim();
                            return text || 'NA';
                        })
                        : [];
                    if (!counts.length) return [`${label}: []`];

                    const wrap = 10;
                    const width = counts.reduce((max, value) => Math.max(max, value.length), 1);
                    const prefix = `${label}: [`;
                    const indent = ' '.repeat(prefix.length);
                    const out = [];
                    for (let i = 0; i < counts.length; i += wrap) {
                        const chunk = counts.slice(i, i + wrap).map((value) => value.padStart(width)).join(', ');
                        const isLast = (i + wrap) >= counts.length;
                        if (i === 0) out.push(`${prefix}${chunk}${isLast ? ']' : ','}`);
                        else out.push(`${indent}${chunk}${isLast ? ']' : ','}`);
                    }
                    return out;
                };
                const addSection = (title, _result, firstStats, allStats, firstMemStats, allMemStats, matchInfo = null, countList = null) => {
                    lines.push(`[${title}]`);
                    if (matchInfo && Number.isInteger(matchInfo.matches) && Number.isInteger(matchInfo.total)) {
                        lines.push(
                            formatAlignedLabelValueRow(
                                'Equivalence',
                                `${matchInfo.matches}/${matchInfo.total} matched (${matchInfo.mismatches} mismatches)`
                            )
                        );
                    }
                    if (Array.isArray(countList) && countList.length) {
                        lines.push(...formatSolutionCountBlock('Solution counts', countList));
                    }
                    if (firstStats && allStats) {
                        lines.push(...formatStatsMsFirstAll('Runtime (ms): ', firstStats, allStats));
                        lines.push(formatAlignedLabelValueRow('Samples (first/all)', `${firstStats.n}/${allStats.n}`));
                    }
                    if (firstMemStats && allMemStats) {
                        lines.push(...formatStatsMsFirstAll(memoryPrefix, firstMemStats, allMemStats));
                    }
                    lines.push('');
                };

                addSection('VF3 baseline', baseResult, sBaseFirst, sBaseAll, mBaseFirst, mBaseAll, null, baselineCountByIter);
                if (geminiSpec) {
                    addSection(gemLabel, gemResult, sGemFirst, sGemAll, mGemFirst, mGemAll,
                        { matches: gemMatchCount, total: gemTotalCount, mismatches: gemMismatchCount }, gemCountByIter);
                }
                if (chatgptSpec) {
                    addSection(chatLabel, chatResult, sChatFirst, sChatAll, mChatFirst, mChatAll,
                        { matches: chatMatchCount, total: chatTotalCount, mismatches: chatMismatchCount }, chatCountByIter);
                }
                for (const extra of extraVariantState) {
                    addSection(
                        extra.label,
                        extra.result,
                        extra.sFirst,
                        extra.sAll,
                        extra.mFirst,
                        extra.mAll,
                        { matches: extra.matchCount, total: extra.totalCount, mismatches: extra.mismatchCount },
                        extra.countByIter
                    );
                }

                let visualization = null;
                try {
                    if (typeof buildLocalSubgraphLikeVisualization === 'function' && typeof buildLocalVisualizationIterations === 'function') {
                        const payloads = [];
                        for (let iter = 0; iter < safeIterations; iter++) {
                            const iterInput = resolveVf3InputForIteration(iter);
                            payloads.push(
                                buildLocalSubgraphLikeVisualization({
                                    algorithm: 'vf3',
                                    patternText: iterInput.patternText,
                                    targetText: iterInput.targetText,
                                    patternFormat: 'vf',
                                    targetFormat: 'vf',
                                    mappingSources: [
                                        baseFirstVisualizationByIter[iter] || '',
                                        baseAllVisualizationByIter[iter] || '',
                                        ...(chatgptSpec ? [chatFirstVisualizationByIter[iter] || '', chatAllVisualizationByIter[iter] || ''] : []),
                                        ...(geminiSpec ? [gemFirstVisualizationByIter[iter] || '', gemAllVisualizationByIter[iter] || ''] : []),
                                        ...extraVariantState.flatMap(extra => [extra.firstVisualizationByIter[iter] || '', extra.allVisualizationByIter[iter] || '']),
                                        baselineVisualizationOut,
                                        baseAllVisualizationOut,
                                        ...(chatgptSpec ? [chatAllVisualizationOut, chatResult] : []),
                                        ...(geminiSpec ? [gemAllVisualizationOut, gemResult] : []),
                                        ...extraVariantState.flatMap(extra => [extra.allVisualizationOut, extra.result]),
                                        baseResult
                                    ],
                                    iteration: iter + 1,
                                    seed: iterInput.seed
                                })
                            );
                        }
                        visualization = buildLocalVisualizationIterations(payloads);
                    }
                } catch (_) {}

                const result = {
                    algorithm: 'vf3',
                    status: 'success',
                    output: lines.join('\n'),
                    iterations: safeIterations,
                    warmup: safeWarmup,
                    timings_ms: {},
                    timings_ms_stdev: {},
                    memory_kb: {},
                    memory_kb_stdev: {},
                    memory_metric_kind: resolvedMemoryMetricInfo.kind,
                    memory_metric_label: resolvedMemoryMetricInfo.label,
                    memory_metric_unit: resolvedMemoryMetricInfo.unit,
                    local_wasm_module_refresh_ms: {},
                    local_wasm_module_refresh_ms_stdev: {},
                    variant_metadata: []
                };
                const addPair = (key, stats) => {
                    if (!stats) return;
                    result.timings_ms[key] = stats.median;
                    result.timings_ms_stdev[key] = stats.stdev;
                };
                const addMemPair = (key, stats) => {
                    if (!stats) return;
                    result.memory_kb[key] = stats.median;
                    result.memory_kb_stdev[key] = stats.stdev;
                };
                const addRefreshPair = (key, stats) => {
                    if (!stats) return;
                    result.local_wasm_module_refresh_ms[key] = stats.median;
                    result.local_wasm_module_refresh_ms_stdev[key] = stats.stdev;
                };
                addPair('baseline_first', sBaseFirst);
                addPair('baseline_all', sBaseAll);
                addMemPair('baseline_first', mBaseFirst);
                addMemPair('baseline_all', mBaseAll);
                addRefreshPair('baseline_first', rBaseFirst);
                addRefreshPair('baseline_all', rBaseAll);
                if (geminiSpec) {
                    addPair(`${gemToken}_first`, sGemFirst);
                    addPair(`${gemToken}_all`, sGemAll);
                    addMemPair(`${gemToken}_first`, mGemFirst);
                    addMemPair(`${gemToken}_all`, mGemAll);
                    addRefreshPair(`${gemToken}_first`, rGemFirst);
                    addRefreshPair(`${gemToken}_all`, rGemAll);
                }
                if (chatgptSpec) {
                    addPair(`${chatToken}_first`, sChatFirst);
                    addPair(`${chatToken}_all`, sChatAll);
                    addMemPair(`${chatToken}_first`, mChatFirst);
                    addMemPair(`${chatToken}_all`, mChatAll);
                    addRefreshPair(`${chatToken}_first`, rChatFirst);
                    addRefreshPair(`${chatToken}_all`, rChatAll);
                }
                for (const extra of extraVariantState) {
                    addPair(`${extra.keyBase}_first`, extra.sFirst);
                    addPair(`${extra.keyBase}_all`, extra.sAll);
                    addMemPair(`${extra.keyBase}_first`, extra.mFirst);
                    addMemPair(`${extra.keyBase}_all`, extra.mAll);
                    addRefreshPair(`${extra.keyBase}_first`, extra.rFirst);
                    addRefreshPair(`${extra.keyBase}_all`, extra.rAll);
                }
                if (!Object.keys(result.memory_kb).length) delete result.memory_kb;
                if (!Object.keys(result.memory_kb_stdev).length) delete result.memory_kb_stdev;
                if (!Object.keys(result.local_wasm_module_refresh_ms).length) delete result.local_wasm_module_refresh_ms;
                if (!Object.keys(result.local_wasm_module_refresh_ms_stdev).length) delete result.local_wasm_module_refresh_ms_stdev;
                result.match_counts = {
                    baseline: { success: vf3Success, failed: vf3Fail }
                };
                if (chatgptSpec) {
                    result.match_counts[chatToken] = {
                        matches: chatMatchCount,
                        total: chatTotalCount,
                        mismatches: chatMismatchCount
                    };
                }
                if (geminiSpec) {
                    result.match_counts[gemToken] = {
                        matches: gemMatchCount,
                        total: gemTotalCount,
                        mismatches: gemMismatchCount
                    };
                }
                for (const extra of extraVariantState) {
                    result.match_counts[extra.keyBase] = {
                        matches: extra.matchCount,
                        total: extra.totalCount,
                        mismatches: extra.mismatchCount
                    };
                }
                result.variant_metadata.push({
                    variant_id: baselineSpec.id,
                    label: 'VF3 Baseline',
                    role: 'baseline',
                    timing_keys: { first: 'baseline_first', all: 'baseline_all' },
                    memory_keys: { first: 'baseline_first', all: 'baseline_all' }
                });
                if (chatgptSpec) {
                    result.variant_metadata.push({
                        variant_id: chatgptSpec.id,
                        label: chatLabel,
                        role: 'variant',
                        timing_keys: { first: `${chatToken}_first`, all: `${chatToken}_all` },
                        memory_keys: { first: `${chatToken}_first`, all: `${chatToken}_all` }
                    });
                }
                if (geminiSpec) {
                    result.variant_metadata.push({
                        variant_id: geminiSpec.id,
                        label: gemLabel,
                        role: 'variant',
                        timing_keys: { first: `${gemToken}_first`, all: `${gemToken}_all` },
                        memory_keys: { first: `${gemToken}_first`, all: `${gemToken}_all` }
                    });
                }
                for (const extra of extraVariantState) {
                    result.variant_metadata.push({
                        variant_id: extra.spec.id,
                        label: extra.label,
                        role: 'variant',
                        timing_keys: { first: `${extra.keyBase}_first`, all: `${extra.keyBase}_all` },
                        memory_keys: { first: `${extra.keyBase}_first`, all: `${extra.keyBase}_all` }
                    });
                }
                if (visualization) {
                    result.visualization = visualization;
                }

                const vf3BaselineCounts = baseAllVisualizationByIter.map(out => {
                    const n = extractVf3Count(out || '');
                    return Number.isInteger(n) ? n : null;
                });
                return { status: 'success', output: lines.join('\n'), result, _vf3BaselineCounts: vf3BaselineCounts };
            } finally {
                // Drop cached modules at the end of each local run to keep memory stable between runs.
                try { invalidateEmscriptenModule(baselineSpec.id); } catch (_) {}
                if (geminiSpec && geminiSpec.id) {
                    try { invalidateEmscriptenModule(geminiSpec.id); } catch (_) {}
                }
                if (chatgptSpec && chatgptSpec.id) {
                    try { invalidateEmscriptenModule(chatgptSpec.id); } catch (_) {}
                }
                for (const extra of extraVariantSpecs) {
                    try { invalidateEmscriptenModule(extra.id); } catch (_) {}
                }
            }
        }

        async function runGlasgowLocally(runCtx, iterations, warmup, options = {}) {
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));
            const baselineFormatFlag = String(
                (options && options.baselineFormatFlag) || 'lad'
            ).trim().toLowerCase() || 'lad';
            const resultAlgorithm = String(
                (options && options.resultAlgorithm) || 'glasgow'
            ).trim().toLowerCase() || 'glasgow';
            const enforceInducedCount = false;
            const preferVf3GeneratedInputs = Boolean(options && options.forceUseVf3GeneratedInputs);
            const hashText32 = (text) => {
                const s = String(text || '');
                let h = 2166136261 >>> 0;
                for (let i = 0; i < s.length; i++) {
                    h ^= s.charCodeAt(i);
                    h = Math.imul(h, 16777619) >>> 0;
                }
                return (`00000000${h.toString(16)}`).slice(-8);
            };
            const makeLadSignature = (ladPatternText, ladTargetText) => ({
                patternHash: hashText32(ladPatternText),
                targetHash: hashText32(ladTargetText),
                patternLength: String(ladPatternText || '').length,
                targetLength: String(ladTargetText || '').length
            });
            const buildUndirectedEdgeSet = (adj) => {
                const set = new Set();
                const list = Array.isArray(adj) ? adj : [];
                for (let i = 0; i < list.length; i++) {
                    const neighbors = Array.isArray(list[i]) ? list[i] : [];
                    for (const rawV of neighbors) {
                        const v = Number(rawV);
                        if (!Number.isInteger(v) || v < 0 || v >= list.length || v === i) continue;
                        const a = i < v ? i : v;
                        const b = i < v ? v : i;
                        set.add(`${a}:${b}`);
                    }
                }
                return set;
            };
            const isInducedMapping = (mapping, patternEdgeSet, targetEdgeSet, patternSize) => {
                if (!mapping || typeof mapping !== 'object') return false;
                const values = [];
                for (let i = 0; i < patternSize; i++) {
                    if (!Object.prototype.hasOwnProperty.call(mapping, i)) return false;
                    const mapped = Number(mapping[i]);
                    if (!Number.isInteger(mapped) || mapped < 0) return false;
                    values.push(mapped);
                }
                if (new Set(values).size !== values.length) return false;
                for (let i = 0; i < patternSize; i++) {
                    const mi = Number(mapping[i]);
                    for (let j = i + 1; j < patternSize; j++) {
                        const mj = Number(mapping[j]);
                        const patternKey = `${i}:${j}`;
                        const a = mi < mj ? mi : mj;
                        const b = mi < mj ? mj : mi;
                        const targetKey = `${a}:${b}`;
                        const patternHas = patternEdgeSet.has(patternKey);
                        const targetHas = targetEdgeSet.has(targetKey);
                        if (patternHas !== targetHas) return false;
                    }
                }
                return true;
            };
            const countInducedMappingsFromOutput = (text, ladPatternText, ladTargetText) => {
                const pParsed = parseLocalLad(ladPatternText || '');
                const tParsed = parseLocalLad(ladTargetText || '');
                const pAdj = pParsed && Array.isArray(pParsed.adj) ? pParsed.adj : [];
                const tAdj = tParsed && Array.isArray(tParsed.adj) ? tParsed.adj : [];
                const pN = pAdj.length;
                if (!pN || !tAdj.length) return 0;
                const patternEdgeSet = buildUndirectedEdgeSet(pAdj);
                const targetEdgeSet = buildUndirectedEdgeSet(tAdj);
                let count = 0;
                const seen = new Set();
                const lines = String(text || '').replace(/\r/g, '').split('\n');
                for (const rawLine of lines) {
                    const line = String(rawLine || '').trim();
                    if (!line || !/^mapping\s*:/i.test(line)) continue;
                    const pairs = Array.from(line.matchAll(/\(\s*(\d+)\s*->\s*(\d+)\s*\)/g));
                    if (!pairs.length) continue;
                    const mapping = {};
                    for (const pair of pairs) {
                        mapping[Number(pair[1])] = Number(pair[2]);
                    }
                    const key = JSON.stringify(mapping);
                    if (key === '{}' || seen.has(key)) continue;
                    seen.add(key);
                    if (isInducedMapping(mapping, patternEdgeSet, targetEdgeSet, pN)) {
                        count++;
                    }
                }
                return count;
            };
            const parseGlasgowOutputCount = (text, context = null) => {
                const normalized = String(text || '').replace(/\r/g, '');
                const lines = normalized.split('\n').map(line => String(line || '').trim()).filter(Boolean);
                if (!lines.length) return { count: 0, parsed: false, reason: 'empty' };

                for (let i = lines.length - 1; i >= 0; i--) {
                    let m = lines[i].match(/\bsolution[_\s-]*count\b\s*(?:=|:)\s*(-?\d+)\b/i);
                    if (m) {
                        const n = Number(m[1]);
                        if (Number.isInteger(n)) return { count: n, parsed: true, reason: 'solution_count' };
                    }
                }

                for (let i = lines.length - 1; i >= 0; i--) {
                    let m = lines[i].match(/\b(?:solutions?|count)\b[^0-9-]*(-?\d+)\b/i);
                    if (!m) m = lines[i].match(/\b(-?\d+)\s+solutions?\b/i);
                    if (m) {
                        const n = Number(m[1]);
                        if (Number.isInteger(n)) return { count: n, parsed: true, reason: 'keyword' };
                    }
                }

                for (let i = lines.length - 1; i >= 0; i--) {
                    if (/^-?\d+$/.test(lines[i])) {
                        const n = Number(lines[i]);
                        if (Number.isInteger(n)) return { count: n, parsed: true, reason: 'single_integer' };
                    }
                }

                if (
                    enforceInducedCount &&
                    context &&
                    typeof context === 'object' &&
                    context.ladPatternText &&
                    context.ladTargetText
                ) {
                    const inducedCount = countInducedMappingsFromOutput(
                        normalized,
                        context.ladPatternText,
                        context.ladTargetText
                    );
                    if (Number.isInteger(inducedCount) && inducedCount >= 0) {
                        return { count: inducedCount, parsed: true, reason: 'induced_mapping_filter' };
                    }
                }

                const mappingCount = extractLocalMappingsFromText(normalized, Math.max(1, lines.length)).length;
                if (mappingCount > 0) return { count: mappingCount, parsed: true, reason: 'mapping_fallback' };

                return { count: 0, parsed: false, reason: 'unrecognized_format' };
            };
            const summarizeOutputText = (text, maxSnippet = 600) => {
                const raw = String(text || '').replace(/\r/g, '');
                const length = raw.length;
                return {
                    length,
                    head: raw.slice(0, maxSnippet),
                    tail: raw.slice(-maxSnippet),
                    mappingLines: extractLocalMappingsFromText(raw, 1).length,
                    truncated: length > maxSnippet * 2
                };
            };

            const patternFile = (config.selectedFiles && config.selectedFiles[0]) ? config.selectedFiles[0] : null;
            const targetFile = (config.selectedFiles && config.selectedFiles[1]) ? config.selectedFiles[1] : null;
            if (!patternFile || !targetFile || !patternFile.path || !targetFile.path) {
                throw new Error('Glasgow requires a pattern and target file');
            }

            let ticksPerIter = 6; // recalculated after module discovery
            let setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            let testsTotal = safeIterations * ticksPerIter;

            const [patternTextRaw, targetTextRaw] = await Promise.all([
                getRepoFileText(patternFile.path),
                getRepoFileText(targetFile.path)
            ]);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const patternFormat = getLocalGraphFormatFromFile(patternFile);
            const targetFormat = getLocalGraphFormatFromFile(targetFile);
            const dual = buildLocalDualFormatGraphPair({
                patternText: patternTextRaw,
                targetText: targetTextRaw,
                patternFormat,
                targetFormat
            });
            const directEquivalenceReport = buildLocalVfLadEquivalenceReport({
                vfPatternText: dual.vf.patternText,
                vfTargetText: dual.vf.targetText,
                ladPatternText: dual.lad.patternText,
                ladTargetText: dual.lad.targetText
            });

            const useVertexLabelledLad = baselineFormatFlag === 'vertexlabelledlad';
            const defaultLadPatternText = useVertexLabelledLad ? dual.lad.patternText : dual.ladUnlabelled.patternText;
            const defaultLadTargetText = useVertexLabelledLad ? dual.lad.targetText : dual.ladUnlabelled.targetText;

            const patternName = sanitizeFsFilename(
                useVertexLabelledLad ? 'pattern_vertexlabelled.lad' : (patternFile.name || 'pattern.lad')
            );
            const targetName = sanitizeFsFilename(
                useVertexLabelledLad ? 'target_vertexlabelled.lad' : (targetFile.name || 'target.lad')
            );
            const patternFsPath = `/inputs/${patternName}`;
            const targetFsPath = `/inputs/${targetName}`;

            const resolveGlasgowInputForIteration = (iterIndex) => {
                const generatedPrimary = getLocalGeneratedIterationInput(preferVf3GeneratedInputs ? 'vf3' : 'glasgow', iterIndex);
                const generatedFallback = preferVf3GeneratedInputs
                    ? getLocalGeneratedIterationInput('glasgow', iterIndex)
                    : null;
                const generated = generatedPrimary || generatedFallback;
                const generatedFiles = generated && Array.isArray(generated.selectedFiles) ? generated.selectedFiles : null;
                const generatedPattern = generatedFiles && generatedFiles[0] ? generatedFiles[0] : null;
                const generatedTarget = generatedFiles && generatedFiles[1] ? generatedFiles[1] : null;
                const generatedPatternPath = generatedPattern && generatedPattern.path ? String(generatedPattern.path) : '';
                const generatedTargetPath = generatedTarget && generatedTarget.path ? String(generatedTarget.path) : '';
                const inputSource = generatedPrimary
                    ? (preferVf3GeneratedInputs ? 'vf3_generated' : 'glasgow_generated')
                    : (generatedFallback ? 'glasgow_generated_fallback' : 'selected_files');

                const patternFileForIter = generatedPattern || patternFile;
                const targetFileForIter = generatedTarget || targetFile;
                const patternFormatForIter = getLocalGraphFormatFromFile(patternFileForIter);
                const targetFormatForIter = getLocalGraphFormatFromFile(targetFileForIter);

                let patternTextForIter = patternTextRaw;
                let targetTextForIter = targetTextRaw;
                if (generatedPatternPath && _localInMemoryRepoFiles.has(generatedPatternPath)) {
                    patternTextForIter = String(_localInMemoryRepoFiles.get(generatedPatternPath) || '');
                }
                if (generatedTargetPath && _localInMemoryRepoFiles.has(generatedTargetPath)) {
                    targetTextForIter = String(_localInMemoryRepoFiles.get(generatedTargetPath) || '');
                }

                try {
                    const dualForIter = buildLocalDualFormatGraphPair({
                        patternText: patternTextForIter,
                        targetText: targetTextForIter,
                        patternFormat: patternFormatForIter,
                        targetFormat: targetFormatForIter
                    });
                    return {
                        ladPatternText: useVertexLabelledLad ? dualForIter.lad.patternText : dualForIter.ladUnlabelled.patternText,
                        ladTargetText: useVertexLabelledLad ? dualForIter.lad.targetText : dualForIter.ladUnlabelled.targetText,
                        seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed')
                            ? generated.seed
                            : null,
                        inputSource,
                        inputSignature: makeLadSignature(
                            useVertexLabelledLad ? dualForIter.lad.patternText : dualForIter.ladUnlabelled.patternText,
                            useVertexLabelledLad ? dualForIter.lad.targetText : dualForIter.ladUnlabelled.targetText
                        )
                    };
                } catch (_) {
                    return {
                        ladPatternText: String(defaultLadPatternText || ''),
                        ladTargetText: String(defaultLadTargetText || ''),
                        seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed')
                            ? generated.seed
                            : null,
                        inputSource,
                        inputSignature: makeLadSignature(defaultLadPatternText, defaultLadTargetText)
                    };
                }
            };
            const firstGlasgowInput = resolveGlasgowInputForIteration(0);

            const glasgowSpecs = await getLocalWasmFamilyModuleSpecs('glasgow', [
                {
                    id: 'glasgow_baseline',
                    scriptPath: 'wasm/glasgow_baseline.js',
                    wasmPath: 'wasm/glasgow_baseline.wasm',
                    factoryName: 'createGlasgowBaselineModule'
                },
                {
                    id: 'glasgow_chatgpt',
                    scriptPath: 'wasm/glasgow_chatgpt.js',
                    wasmPath: 'wasm/glasgow_chatgpt.wasm',
                    factoryName: 'createGlasgowChatgptModule'
                },
                {
                    id: 'glasgow_gemini',
                    scriptPath: 'wasm/glasgow_gemini.js',
                    wasmPath: 'wasm/glasgow_gemini.wasm',
                    factoryName: 'createGlasgowGeminiModule'
                }
            ]);
            const baselineSpec = glasgowSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'glasgow') === 'baseline') || null;
            if (!baselineSpec) {
                throw new Error('Missing Glasgow baseline local WASM module (`glasgow_baseline`) in `wasm/manifest.json`.');
            }
            const chatgptSpec = glasgowSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'glasgow') === 'chatgpt') || null;
            const geminiSpec = glasgowSpecs.find(spec => localWasmVariantTokenFromId(spec.id, 'glasgow') === 'gemini') || null;
            const extraVariantSpecs = glasgowSpecs.filter((spec) => {
                const id = String(spec && spec.id ? spec.id : '');
                if (!id) return false;
                if (id === baselineSpec.id) return false;
                if (chatgptSpec && id === chatgptSpec.id) return false;
                if (geminiSpec && id === geminiSpec.id) return false;
                return true;
            });
            ticksPerIter = 2 + (chatgptSpec ? 2 : 0) + (geminiSpec ? 2 : 0) + (extraVariantSpecs.length * 2);
            setupTotal = Math.max(1, safeWarmup * ticksPerIter);
            testsTotal = safeIterations * ticksPerIter;
            const chatToken = chatgptSpec ? (localWasmVariantTokenFromId(chatgptSpec.id, 'glasgow') || 'chatgpt') : 'chatgpt';
            const gemToken = geminiSpec ? (localWasmVariantTokenFromId(geminiSpec.id, 'glasgow') || 'gemini') : 'gemini';
            const chatLabel = chatgptSpec ? buildLocalWasmVariantLabel('glasgow', chatToken) : 'Glasgow Chatgpt';
            const gemLabel = geminiSpec ? buildLocalWasmVariantLabel('glasgow', gemToken) : 'Glasgow Gemini';
            progressReset(resultAlgorithm, safeIterations, runCtx.requestId, {
                setupTotal,
                testsPerIter: ticksPerIter
            });

            const writeInputs = (mod, inputForRun = firstGlasgowInput) => {
                ensureEmscriptenDir(mod, '/inputs');
                writeEmscriptenTextFile(mod, patternFsPath, String(inputForRun && inputForRun.ladPatternText ? inputForRun.ladPatternText : defaultLadPatternText));
                writeEmscriptenTextFile(mod, targetFsPath, String(inputForRun && inputForRun.ladTargetText ? inputForRun.ladTargetText : defaultLadTargetText));
            };

            const unloadModule = (spec) => {
                try {
                    invalidateEmscriptenModule(spec && spec.id ? spec.id : '');
                } catch (_) {}
            };
            const loadFreshModule = async (spec, label, done, total, stage, inputForRun = firstGlasgowInput) => {
                if (label) {
                    progressSetDeterminate(
                        label,
                        Number.isFinite(Number(done)) ? Number(done) : 0,
                        Math.max(1, Number.isFinite(Number(total)) ? Number(total) : 1),
                        { stage }
                    );
                }
                const mod = await getFreshEmscriptenModule(spec);
                writeInputs(mod, inputForRun);
                return mod;
            };
            const loadFreshModuleMeasured = async (spec, label, done, total, stage, inputForRun = firstGlasgowInput) => {
                const t0 = runTimerNowMs();
                const mod = await loadFreshModule(spec, label, done, total, stage, inputForRun);
                await flushEmscriptenWorkerFsOps(mod);
                const t1 = runTimerNowMs();
                return { mod, refreshMs: Math.max(0, t1 - t0) };
            };

            const abortSignal = runCtx && runCtx.abortController ? runCtx.abortController.signal : null;

            const inducedArgs = enforceInducedCount ? ['--induced'] : [];
            const baselineFirstArgs = [...inducedArgs, '--format', baselineFormatFlag, patternFsPath, targetFsPath];
            const baselineAllArgs = ['--count-solutions', ...inducedArgs, '--format', baselineFormatFlag, patternFsPath, targetFsPath];
            const chatArgs = [patternFsPath, targetFsPath];
            const gemArgs = [patternFsPath, targetFsPath];

            try {
                const warmupSingle = async (title, spec, argsList, tickIncrementRef, inputForRun) => {
                    let mod = await loadFreshModule(spec, `Loading ${title} WASM...`, tickIncrementRef.value, setupTotal, 'setup', inputForRun || firstGlasgowInput);
                    try {
                        for (let i = 0; i < safeWarmup; i++) {
                            for (const stepArgs of argsList) {
                                if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                                progressSetDeterminate(`Warming up: ${title}`, tickIncrementRef.value, setupTotal, { stage: 'setup' });
                                try {
                                    await runEmscriptenMain(mod, stepArgs, {
                                        captureOptions: {
                                            mappingLinePolicy: 'drop-all',
                                            maxOutputChars: 4096,
                                            maxErrorChars: 16384
                                        }
                                    });
                                } catch (error) {
                                    const msg = error && error.message ? error.message : String(error);
                                    throw new Error(`Warmup ${i + 1}/${safeWarmup} - ${title}: ${msg}`);
                                }
                                tickIncrementRef.value++;
                                progressSetDeterminate(`Warming up: ${title}`, tickIncrementRef.value, setupTotal, { stage: 'setup' });
                                await delay(0, abortSignal);
                            }
                        }
                    } finally {
                        mod = null;
                        unloadModule(spec);
                    }
                    return null;
                };

                if (safeWarmup > 0) {
                    const setupTicks = { value: 0 };
                    let warm = await warmupSingle('Glasgow baseline', baselineSpec, [baselineFirstArgs, baselineAllArgs], setupTicks, firstGlasgowInput);
                    if (warm && warm.status === 'aborted') return warm;
                    if (chatgptSpec) {
                        warm = await warmupSingle(chatLabel, chatgptSpec, [chatArgs], setupTicks, firstGlasgowInput);
                        if (warm && warm.status === 'aborted') return warm;
                        // Workflow counts one non-baseline Glasgow run as first+all.
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            setupTicks.value = Math.min(setupTotal, setupTicks.value + 1);
                            progressSetDeterminate(`Warming up: ${chatLabel}`, setupTicks.value, setupTotal, { stage: 'setup' });
                        }
                    }
                    if (geminiSpec) {
                        warm = await warmupSingle(gemLabel, geminiSpec, [gemArgs], setupTicks, firstGlasgowInput);
                        if (warm && warm.status === 'aborted') return warm;
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            setupTicks.value = Math.min(setupTotal, setupTicks.value + 1);
                            progressSetDeterminate(`Warming up: ${gemLabel}`, setupTicks.value, setupTotal, { stage: 'setup' });
                        }
                    }
                    for (const extraSpec of extraVariantSpecs) {
                        const extraToken = localWasmVariantTokenFromId(extraSpec.id, 'glasgow') || extraSpec.id;
                        const extraLabel = buildLocalWasmVariantLabel('glasgow', extraToken);
                        warm = await warmupSingle(extraLabel, extraSpec, [patternFsPath, targetFsPath], setupTicks, firstGlasgowInput);
                        if (warm && warm.status === 'aborted') return warm;
                        for (let i = 0; i < safeWarmup; i++) {
                            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                            setupTicks.value = Math.min(setupTotal, setupTicks.value + 1);
                            progressSetDeterminate(`Warming up: ${extraLabel}`, setupTicks.value, setupTotal, { stage: 'setup' });
                        }
                    }
                } else {
                    progressSetDeterminate('Setting up Testing Environment', setupTotal, setupTotal, { stage: 'setup', reset: true });
                }

                progressSetDeterminate('Running tests...', 0, testsTotal, { stage: 'tests', reset: true });

                const baseFirst = [];
                const baseAll = [];
                const chatFirst = [];
                const chatAll = [];
                const gemFirst = [];
                const gemAll = [];
                const baseFirstHeapKiB = [];
                const baseAllHeapKiB = [];
                const chatFirstHeapKiB = [];
                const chatAllHeapKiB = [];
                const gemFirstHeapKiB = [];
                const gemAllHeapKiB = [];
                const glasgowDiagnostics = [];
                const baseFirstRefreshMs = [];
                const baseAllRefreshMs = [];
                const chatFirstRefreshMs = [];
                const chatAllRefreshMs = [];
                const gemFirstRefreshMs = [];
                const gemAllRefreshMs = [];
                const extraVariantState = extraVariantSpecs.map((spec) => ({
                    spec,
                    token: localWasmVariantTokenFromId(spec.id, 'glasgow') || spec.id,
                    keyBase: localWasmVariantTokenFromId(spec.id, 'glasgow') || spec.id,
                    label: buildLocalWasmVariantLabel('glasgow', localWasmVariantTokenFromId(spec.id, 'glasgow') || spec.id),
                    first: [],
                    all: [],
                    firstHeapKiB: [],
                    allHeapKiB: [],
                    firstRefreshMs: [],
                    allRefreshMs: [],
                    match: 0,
                    total: 0,
                    mismatch: 0,
                    outputFirstSeen: '',
                    outputLatest: ''
                }));
                let ticksDone = 0;
                let memoryMetricInfo = null;

                let baselineFirstOut = '';
                let baselineAllOut = '';
                let chatOut = '';
                let gemOut = '';

                let glasgowSuccess = 0;
                let glasgowFail = 0;
                let chatMatch = 0;
                let chatTotal = 0;
                let chatMismatch = 0;
                let gemMatch = 0;
                let gemTotal = 0;
                let gemMismatch = 0;
                const iterationVisualizationSources = [];

                const isTrapError = (error) => {
                    const msg = error && error.message ? String(error.message) : String(error);
                    const lower = msg.toLowerCase();
                    return lower.includes('function signature mismatch') ||
                        lower.includes('memory access out of bounds') ||
                        lower.includes('out of bounds memory access') ||
                        lower.includes('unreachable');
                };

                const runOneMeasuredFresh = async (spec, title, args, storeTimes, captureStdout, heapArr = null, refreshArr = null, captureOptionsFactory = null, inputForRun = firstGlasgowInput) => {
                    for (let attempt = 0; attempt < 2; attempt++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        const loaded = await loadFreshModuleMeasured(spec, `Loading ${title} WASM...`, ticksDone, testsTotal, 'tests', inputForRun);
                        let mod = loaded.mod;
                        if (refreshArr) refreshArr.push(loaded.refreshMs);
                        try {
                            const captureOptions = (typeof captureOptionsFactory === 'function')
                                ? (captureOptionsFactory({ attempt }) || null)
                                : ((captureOptionsFactory && typeof captureOptionsFactory === 'object') ? captureOptionsFactory : null);
                            const t0 = runTimerNowMs();
                            const res = await runEmscriptenMain(mod, args, captureOptions ? { captureOptions } : {});
                            const t1 = runTimerNowMs();
                            storeTimes.push(Math.max(0, t1 - t0));
                            if (heapArr) {
                                const heapKiB = getEmscriptenHeapPeakKiB(mod);
                                if (Number.isFinite(Number(heapKiB))) heapArr.push(Number(heapKiB));
                            }
                            memoryMetricInfo = pickPreferredWasmMemoryMetricInfo(memoryMetricInfo, getEmscriptenMemoryMetricInfo(mod));
                            if (captureStdout) {
                                const stdout = res && typeof res.stdout === 'string' ? res.stdout : '';
                                const stderr = res && typeof res.stderr === 'string' ? res.stderr : '';
                                const combined = [stdout, stderr].filter(part => typeof part === 'string' && part.trim()).join('\n');
                                captureStdout(combined || stdout || stderr || '');
                            }
                            return null;
                        } catch (error) {
                            const canRecover = isTrapError(error) && attempt === 0;
                            if (!canRecover) {
                                const msg = error && error.message ? error.message : String(error);
                                throw new Error(`${title}: ${msg}`);
                            }
                        } finally {
                            mod = null;
                            unloadModule(spec);
                            await delay(0, abortSignal);
                        }
                    }
                    return null;
                };

                for (let iter = 0; iter < safeIterations; iter++) {
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                    const iterInput = resolveGlasgowInputForIteration(iter);

                    progressSetDeterminate('Glasgow baseline', ticksDone, testsTotal, { stage: 'tests' });
                    let latestBaselineFirst = '';
                    let latestBaselineAll = '';
                    const firstRes = await runOneMeasuredFresh(
                        baselineSpec,
                        `Iteration ${iter + 1}/${safeIterations} - Glasgow baseline first`,
                        baselineFirstArgs,
                        baseFirst,
                        (stdout) => {
                            latestBaselineFirst = stdout;
                            if (!baselineFirstOut) baselineFirstOut = stdout;
                        },
                        baseFirstHeapKiB,
                        baseFirstRefreshMs,
                        () => ({
                            maxOutputChars: 0,
                            maxErrorChars: 16384
                        }),
                        iterInput
                    );
                    if (firstRes && firstRes.status === 'aborted') return firstRes;
                    ticksDone++;
                    progressSetDeterminate('Glasgow baseline', ticksDone, testsTotal, { stage: 'tests' });
                    await delay(0, abortSignal);

                    progressSetDeterminate('Glasgow baseline', ticksDone, testsTotal, { stage: 'tests' });
                    const allRes = await runOneMeasuredFresh(
                        baselineSpec,
                        `Iteration ${iter + 1}/${safeIterations} - Glasgow baseline all`,
                        baselineAllArgs,
                        baseAll,
                        (stdout) => {
                            latestBaselineAll = stdout;
                            if (!baselineAllOut) baselineAllOut = stdout;
                        },
                        baseAllHeapKiB,
                        baseAllRefreshMs,
                        () => ({
                            maxOutputChars: 0,
                            maxErrorChars: 16384
                        }),
                        iterInput
                    );
                    if (allRes && allRes.status === 'aborted') return allRes;
                    ticksDone++;
                    progressSetDeterminate('Glasgow baseline', ticksDone, testsTotal, { stage: 'tests' });
                    await delay(0, abortSignal);

                    // Prefer VF3 baseline count as cross-solver reference; fall back to Glasgow baseline
                    const vf3RefCount = (options.vf3BaselineCounts && options.vf3BaselineCounts[iter] !== undefined)
                        ? options.vf3BaselineCounts[iter]
                        : null;
                    const glasgowBaselineCount = extractLocalSolutionCount(latestBaselineAll);
                    const referenceCount = (vf3RefCount !== null) ? vf3RefCount : glasgowBaselineCount;

                    if (referenceCount === null) {
                        console.warn('[runGlasgowLocally] Missing baseline reference count for iteration', iter + 1);
                        iterationVisualizationSources.push({
                            baselineFirstOut: latestBaselineFirst,
                            baselineAllOut: latestBaselineAll,
                            chatOut: '',
                            gemOut: '',
                            ladPatternText: iterInput.ladPatternText,
                            ladTargetText: iterInput.ladTargetText,
                            seed: iterInput.seed
                        });
                        glasgowFail++;
                        continue;
                    }
                    glasgowSuccess++;

                    let latestChat = '';
                    let latestGem = '';
                    let chatParse = { count: null, parsed: false, reason: 'not_run' };
                    let gemParse = { count: null, parsed: false, reason: 'not_run' };
                    const variantDiagnostics = {};

                    if (chatgptSpec) {
                        progressSetDeterminate(chatLabel, ticksDone, testsTotal, { stage: 'tests' });
                        chatTotal++;
                        const chatRes = await runOneMeasuredFresh(
                            chatgptSpec,
                            `Iteration ${iter + 1}/${safeIterations} - ${chatLabel}`,
                            chatArgs,
                            chatFirst,
                            (stdout) => {
                                latestChat = stdout;
                                if (!chatOut) chatOut = stdout;
                            },
                            chatFirstHeapKiB,
                            chatFirstRefreshMs,
                            () => ({
                                maxOutputChars: 0,
                                maxErrorChars: 16384
                            }),
                            iterInput
                        );
                        if (chatRes && chatRes.status === 'aborted') return chatRes;
                        if (chatFirst.length) chatAll.push(chatFirst[chatFirst.length - 1]);
                        if (chatFirstHeapKiB.length) chatAllHeapKiB.push(chatFirstHeapKiB[chatFirstHeapKiB.length - 1]);
                        if (chatFirstRefreshMs.length) chatAllRefreshMs.push(chatFirstRefreshMs[chatFirstRefreshMs.length - 1]);
                        ticksDone++;
                        progressSetDeterminate(chatLabel, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                        ticksDone++;
                        progressSetDeterminate(chatLabel, ticksDone, testsTotal, { stage: 'tests' });
                        chatParse = parseGlasgowOutputCount(latestChat, iterInput);
                        if (chatParse.count !== null && chatParse.count === referenceCount) chatMatch++;
                        else chatMismatch++;
                    }

                    if (geminiSpec) {
                        progressSetDeterminate(gemLabel, ticksDone, testsTotal, { stage: 'tests' });
                        gemTotal++;
                        const gemRes = await runOneMeasuredFresh(
                            geminiSpec,
                            `Iteration ${iter + 1}/${safeIterations} - ${gemLabel}`,
                            gemArgs,
                            gemFirst,
                            (stdout) => {
                                latestGem = stdout;
                                if (!gemOut) gemOut = stdout;
                            },
                            gemFirstHeapKiB,
                            gemFirstRefreshMs,
                            () => ({
                                maxOutputChars: 0,
                                maxErrorChars: 16384
                            }),
                            iterInput
                        );
                        if (gemRes && gemRes.status === 'aborted') return gemRes;
                        if (gemFirst.length) gemAll.push(gemFirst[gemFirst.length - 1]);
                        if (gemFirstHeapKiB.length) gemAllHeapKiB.push(gemFirstHeapKiB[gemFirstHeapKiB.length - 1]);
                        if (gemFirstRefreshMs.length) gemAllRefreshMs.push(gemFirstRefreshMs[gemFirstRefreshMs.length - 1]);
                        ticksDone++;
                        progressSetDeterminate(gemLabel, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                        ticksDone++;
                        progressSetDeterminate(gemLabel, ticksDone, testsTotal, { stage: 'tests' });
                        gemParse = parseGlasgowOutputCount(latestGem, iterInput);
                        if (gemParse.count !== null && gemParse.count === referenceCount) gemMatch++;
                        else gemMismatch++;
                    }

                    for (const extra of extraVariantState) {
                        progressSetDeterminate(extra.label, ticksDone, testsTotal, { stage: 'tests' });
                        extra.total++;
                        let latest = '';
                        const extraRes = await runOneMeasuredFresh(
                            extra.spec,
                            `Iteration ${iter + 1}/${safeIterations} - ${extra.label}`,
                            [patternFsPath, targetFsPath],
                            extra.first,
                            (stdout) => {
                                latest = stdout;
                                if (!extra.outputFirstSeen) extra.outputFirstSeen = stdout;
                            },
                            extra.firstHeapKiB,
                            extra.firstRefreshMs,
                            () => ({
                                maxOutputChars: 0,
                                maxErrorChars: 16384
                            }),
                            iterInput
                        );
                        if (extraRes && extraRes.status === 'aborted') return extraRes;
                        if (extra.first.length) extra.all.push(extra.first[extra.first.length - 1]);
                        if (extra.firstHeapKiB.length) extra.allHeapKiB.push(extra.firstHeapKiB[extra.firstHeapKiB.length - 1]);
                        if (extra.firstRefreshMs.length) extra.allRefreshMs.push(extra.firstRefreshMs[extra.firstRefreshMs.length - 1]);
                        ticksDone++;
                        progressSetDeterminate(extra.label, ticksDone, testsTotal, { stage: 'tests' });
                        await delay(0, abortSignal);
                        ticksDone++;
                        progressSetDeterminate(extra.label, ticksDone, testsTotal, { stage: 'tests' });
                        const parsed = parseGlasgowOutputCount(latest, iterInput);
                        if (parsed.count !== null && parsed.count === referenceCount) extra.match++;
                        else extra.mismatch++;
                        extra.outputLatest = latest;
                        variantDiagnostics[extra.keyBase] = {
                            count: parsed.count,
                            parsed: parsed.parsed,
                            reason: parsed.reason,
                            output: summarizeOutputText(latest),
                            match: parsed.count !== null && parsed.count === referenceCount
                        };
                    }
                    glasgowDiagnostics.push({
                        iteration: iter + 1,
                        referenceCount,
                        referenceSource: (options && options.vf3BaselineCounts && options.vf3BaselineCounts[iter] !== undefined) ? 'vf3' : 'glasgow',
                        baseline: {
                            count: referenceCount,
                            parse: parseGlasgowOutputCount(latestBaselineAll, iterInput)
                        },
                        chat: {
                            count: chatParse.count,
                            parsed: chatParse.parsed,
                            reason: chatParse.reason,
                            output: summarizeOutputText(latestChat),
                            match: chatParse.count !== null && chatParse.count === referenceCount
                        },
                        gem: {
                            count: gemParse.count,
                            parsed: gemParse.parsed,
                            reason: gemParse.reason,
                            output: summarizeOutputText(latestGem),
                            match: gemParse.count !== null && gemParse.count === referenceCount
                        },
                        variants: variantDiagnostics,
                        seeds: {
                            iterSeed: iterInput && Object.prototype.hasOwnProperty.call(iterInput, 'seed') ? iterInput.seed : null,
                            iteration: iter + 1
                        },
                        inputSource: iterInput && iterInput.inputSource ? iterInput.inputSource : 'selected_files',
                        inputSignature: (iterInput && iterInput.inputSignature) ? iterInput.inputSignature : null
                    });
                    iterationVisualizationSources.push({
                        baselineFirstOut: latestBaselineFirst,
                        baselineAllOut: latestBaselineAll,
                        chatOut: latestChat,
                        gemOut: latestGem,
                        extraVariantOutputs: Object.fromEntries(extraVariantState.map(extra => [extra.keyBase, extra.outputLatest || ''])),
                        ladPatternText: iterInput.ladPatternText,
                        ladTargetText: iterInput.ladTargetText,
                        seed: iterInput.seed
                    });
                }

                let baselineVisualizationOut = baselineAllOut || baselineFirstOut || '';
                if (!extractLocalMappingsFromText(baselineVisualizationOut, 1).length && !(runCtx && runCtx.aborted)) {
                    // Match the GitHub Actions visualizer path: run baseline Glasgow once with solution-print flags.
                    let visMod = null;
                    const visInput = resolveGlasgowInputForIteration(0);
                    try {
                        visMod = await loadFreshModule(
                            baselineSpec,
                            'Loading Glasgow visualization baseline...',
                            ticksDone,
                            testsTotal,
                            'tests',
                            visInput
                        );
                        const visRes = await runEmscriptenMain(
                            visMod,
                            [
                                ...(enforceInducedCount ? ['--induced'] : []),
                                '--format',
                                baselineFormatFlag,
                                '--print-all-solutions',
                                '--solution-limit',
                                '2000',
                                patternFsPath,
                                targetFsPath
                            ],
                            {
                                captureOptions: {
                                    maxOutputChars: 262144,
                                    maxErrorChars: 65536
                                }
                            }
                        );
                        const visStdout = visRes && typeof visRes.stdout === 'string' ? visRes.stdout : '';
                        const visStderr = visRes && typeof visRes.stderr === 'string' ? visRes.stderr : '';
                        const visOut = [visStdout, visStderr].filter(part => typeof part === 'string' && part.trim()).join('\n');
                        if (visOut.trim()) baselineVisualizationOut = visOut;
                    } catch (_) {
                        baselineVisualizationOut = baselineVisualizationOut || baselineAllOut || baselineFirstOut || '';
                    } finally {
                        visMod = null;
                        unloadModule(baselineSpec);
                    }
                }

                progressSetDeterminate('Completed', testsTotal, testsTotal, { stage: 'tests' });

                const sBaseFirst = calcStatsMs(baseFirst);
                const sBaseAll = calcStatsMs(baseAll);
                const sChatFirst = calcStatsMs(chatFirst);
                const sChatAll = calcStatsMs(chatAll);
                const sGemFirst = calcStatsMs(gemFirst);
                const sGemAll = calcStatsMs(gemAll);
                const mBaseFirst = calcStatsMs(baseFirstHeapKiB);
                const mBaseAll = calcStatsMs(baseAllHeapKiB);
                const mChatFirst = calcStatsMs(chatFirstHeapKiB);
                const mChatAll = calcStatsMs(chatAllHeapKiB);
                const mGemFirst = calcStatsMs(gemFirstHeapKiB);
                const mGemAll = calcStatsMs(gemAllHeapKiB);
                const rBaseFirst = calcStatsMs(baseFirstRefreshMs);
                const rBaseAll = calcStatsMs(baseAllRefreshMs);
                const rChatFirst = calcStatsMs(chatFirstRefreshMs);
                const rChatAll = calcStatsMs(chatAllRefreshMs);
                const rGemFirst = calcStatsMs(gemFirstRefreshMs);
                const rGemAll = calcStatsMs(gemAllRefreshMs);
                for (const extra of extraVariantState) {
                    extra.sFirst = calcStatsMs(extra.first);
                    extra.sAll = calcStatsMs(extra.all);
                    extra.mFirst = calcStatsMs(extra.firstHeapKiB);
                    extra.mAll = calcStatsMs(extra.allHeapKiB);
                    extra.rFirst = calcStatsMs(extra.firstRefreshMs);
                    extra.rAll = calcStatsMs(extra.allRefreshMs);
                }
                const resolvedMemoryMetricInfo = memoryMetricInfo || getDefaultWasmMemoryMetricInfo();
                const memoryPrefix = formatWasmMemoryStatsPrefix(resolvedMemoryMetricInfo);

                const lines = [];
                const usingVf3Ref = options.vf3BaselineCounts && options.vf3BaselineCounts.length > 0;
                const failureSuffix = glasgowFail > 0 ? `, ${glasgowFail} failed` : '';
                lines.push(usingVf3Ref ? '[Glasgow Subgraph Solver] (external baseline reference)' : '[Glasgow Subgraph Solver]');
                lines.push(`${glasgowSuccess} iterations ran successfully${failureSuffix}`);
                if (sBaseFirst && sBaseAll) lines.push(...formatStatsMsFirstAll('Runtime (ms): ', sBaseFirst, sBaseAll));
                if (mBaseFirst && mBaseAll) lines.push(...formatStatsMsFirstAll(memoryPrefix, mBaseFirst, mBaseAll));
                lines.push('');

                const addLlmSection = (title, match, total, mismatch, firstStats, allStats, firstMemStats, allMemStats) => {
                    lines.push(`[${title}]`);
                    if (Number.isInteger(match) && Number.isInteger(total)) {
                        lines.push(
                            formatAlignedLabelValueRow(
                                'Equivalence',
                                `${match}/${total} matched (${mismatch} mismatches)`
                            )
                        );
                    }
                    if (firstStats && allStats) {
                        lines.push(...formatStatsMsFirstAll('Runtime (ms): ', firstStats, allStats));
                        lines.push(formatAlignedLabelValueRow('Samples (first/all)', `${firstStats.n}/${allStats.n}`));
                    }
                    if (firstMemStats && allMemStats) lines.push(...formatStatsMsFirstAll(memoryPrefix, firstMemStats, allMemStats));
                    lines.push('');
                };
                if (chatgptSpec) {
                    addLlmSection(chatLabel, chatMatch, chatTotal, chatMismatch, sChatFirst, sChatAll, mChatFirst, mChatAll);
                }
                if (geminiSpec) {
                    addLlmSection(gemLabel, gemMatch, gemTotal, gemMismatch, sGemFirst, sGemAll, mGemFirst, mGemAll);
                }
                for (const extra of extraVariantState) {
                    addLlmSection(extra.label, extra.match, extra.total, extra.mismatch, extra.sFirst, extra.sAll, extra.mFirst, extra.mAll);
                }

                let visualization = null;
                try {
                    if (typeof buildLocalSubgraphLikeVisualization === 'function' && typeof buildLocalVisualizationIterations === 'function') {
                        const payloads = [];
                        const visCount = Math.max(1, Math.min(safeIterations, iterationVisualizationSources.length || safeIterations));
                        for (let i = 0; i < visCount; i++) {
                            const src = iterationVisualizationSources[i] || {};
                            payloads.push(
                                buildLocalSubgraphLikeVisualization({
                                    algorithm: 'glasgow',
                                    patternText: src.ladPatternText || firstGlasgowInput.ladPatternText,
                                    targetText: src.ladTargetText || firstGlasgowInput.ladTargetText,
                                    patternFormat: 'lad',
                                    targetFormat: 'lad',
                                    mappingSources: [
                                        src.baselineAllOut || '',
                                        src.baselineFirstOut || '',
                                        src.chatOut || '',
                                        src.gemOut || '',
                                        ...Object.values(src.extraVariantOutputs || {}),
                                        baselineVisualizationOut,
                                        baselineAllOut,
                                        baselineFirstOut,
                                        chatOut,
                                        gemOut,
                                        ...extraVariantState.map(extra => extra.outputFirstSeen || ''),
                                        ...extraVariantState.map(extra => extra.outputLatest || '')
                                    ],
                                    iteration: i + 1,
                                    seed: src.seed
                                })
                            );
                        }
                        visualization = buildLocalVisualizationIterations(payloads);
                    }
                } catch (_) {}

                const result = {
                    algorithm: resultAlgorithm,
                    status: 'success',
                    output: lines.join('\n'),
                    iterations: safeIterations,
                    warmup: safeWarmup,
                    timings_ms: {},
                    timings_ms_stdev: {},
                    memory_kb: {},
                    memory_kb_stdev: {},
                    memory_metric_kind: resolvedMemoryMetricInfo.kind,
                    memory_metric_label: resolvedMemoryMetricInfo.label,
                    memory_metric_unit: resolvedMemoryMetricInfo.unit,
                    local_wasm_module_refresh_ms: {},
                    local_wasm_module_refresh_ms_stdev: {},
                    variant_metadata: [],
                    match_counts: {
                        baseline: {
                            success: glasgowSuccess,
                            failed: glasgowFail
                        }
                    }
                };
                const addPair = (key, stats) => {
                    if (!stats) return;
                    result.timings_ms[key] = stats.median;
                    result.timings_ms_stdev[key] = stats.stdev;
                };
                const addMemPair = (key, stats) => {
                    if (!stats) return;
                    result.memory_kb[key] = stats.median;
                    result.memory_kb_stdev[key] = stats.stdev;
                };
                const addRefreshPair = (key, stats) => {
                    if (!stats) return;
                    result.local_wasm_module_refresh_ms[key] = stats.median;
                    result.local_wasm_module_refresh_ms_stdev[key] = stats.stdev;
                };
                addPair('first', sBaseFirst);
                addPair('all', sBaseAll);
                addMemPair('first', mBaseFirst);
                addMemPair('all', mBaseAll);
                addRefreshPair('first', rBaseFirst);
                addRefreshPair('all', rBaseAll);
                if (chatgptSpec) {
                    result.match_counts[chatToken] = { matches: chatMatch, total: chatTotal, mismatches: chatMismatch };
                    addPair(`${chatToken}_first`, sChatFirst);
                    addPair(`${chatToken}_all`, sChatAll);
                    addMemPair(`${chatToken}_first`, mChatFirst);
                    addMemPair(`${chatToken}_all`, mChatAll);
                    addRefreshPair(`${chatToken}_first`, rChatFirst);
                    addRefreshPair(`${chatToken}_all`, rChatAll);
                }
                if (geminiSpec) {
                    result.match_counts[gemToken] = { matches: gemMatch, total: gemTotal, mismatches: gemMismatch };
                    addPair(`${gemToken}_first`, sGemFirst);
                    addPair(`${gemToken}_all`, sGemAll);
                    addMemPair(`${gemToken}_first`, mGemFirst);
                    addMemPair(`${gemToken}_all`, mGemAll);
                    addRefreshPair(`${gemToken}_first`, rGemFirst);
                    addRefreshPair(`${gemToken}_all`, rGemAll);
                }
                for (const extra of extraVariantState) {
                    result.match_counts[extra.keyBase] = {
                        matches: extra.match,
                        total: extra.total,
                        mismatches: extra.mismatch
                    };
                    addPair(`${extra.keyBase}_first`, extra.sFirst);
                    addPair(`${extra.keyBase}_all`, extra.sAll);
                    addMemPair(`${extra.keyBase}_first`, extra.mFirst);
                    addMemPair(`${extra.keyBase}_all`, extra.mAll);
                    addRefreshPair(`${extra.keyBase}_first`, extra.rFirst);
                    addRefreshPair(`${extra.keyBase}_all`, extra.rAll);
                }
                result.variant_metadata.push({
                    variant_id: baselineSpec.id,
                    label: 'Glasgow Baseline',
                    role: 'baseline',
                    timing_keys: { first: 'first', all: 'all' },
                    memory_keys: { first: 'first', all: 'all' }
                });
                if (chatgptSpec) {
                    result.variant_metadata.push({
                        variant_id: chatgptSpec.id,
                        label: chatLabel,
                        role: 'variant',
                        timing_keys: { first: `${chatToken}_first`, all: `${chatToken}_all` },
                        memory_keys: { first: `${chatToken}_first`, all: `${chatToken}_all` }
                    });
                }
                if (geminiSpec) {
                    result.variant_metadata.push({
                        variant_id: geminiSpec.id,
                        label: gemLabel,
                        role: 'variant',
                        timing_keys: { first: `${gemToken}_first`, all: `${gemToken}_all` },
                        memory_keys: { first: `${gemToken}_first`, all: `${gemToken}_all` }
                    });
                }
                for (const extra of extraVariantState) {
                    result.variant_metadata.push({
                        variant_id: extra.spec.id,
                        label: extra.label,
                        role: 'variant',
                        timing_keys: { first: `${extra.keyBase}_first`, all: `${extra.keyBase}_all` },
                        memory_keys: { first: `${extra.keyBase}_first`, all: `${extra.keyBase}_all` }
                    });
                }
                if (!Object.keys(result.memory_kb).length) delete result.memory_kb;
                if (!Object.keys(result.memory_kb_stdev).length) delete result.memory_kb_stdev;
                if (!Object.keys(result.local_wasm_module_refresh_ms).length) delete result.local_wasm_module_refresh_ms;
                if (!Object.keys(result.local_wasm_module_refresh_ms_stdev).length) delete result.local_wasm_module_refresh_ms_stdev;
                if (visualization) result.visualization = visualization;

                return {
                    status: 'success',
                    output: lines.join('\n'),
                    result,
                    _localPhase: {
                        baselineFirstOut,
                        baselineAllOut,
                        chatOut,
                        gemOut,
                        ladPatternText: firstGlasgowInput.ladPatternText,
                        ladTargetText: firstGlasgowInput.ladTargetText
                    },
                    _glasgowIterationDiagnostics: glasgowDiagnostics
                };
            } finally {
                try { invalidateEmscriptenModule(baselineSpec.id); } catch (_) {}
                if (chatgptSpec && chatgptSpec.id) {
                    try { invalidateEmscriptenModule(chatgptSpec.id); } catch (_) {}
                }
                if (geminiSpec && geminiSpec.id) {
                    try { invalidateEmscriptenModule(geminiSpec.id); } catch (_) {}
                }
                for (const extra of extraVariantSpecs) {
                    try { invalidateEmscriptenModule(extra.id); } catch (_) {}
                }
            }
        }

        function copyLocalTimingKeysWithPrefix(targetValueObj, targetStdevObj, sourceResult, keyMap) {
            const timings = sourceResult && sourceResult.timings_ms ? sourceResult.timings_ms : {};
            const stdevs = sourceResult && sourceResult.timings_ms_stdev ? sourceResult.timings_ms_stdev : {};
            for (const [srcKey, dstKey] of Object.entries(keyMap || {})) {
                if (Object.prototype.hasOwnProperty.call(timings, srcKey)) {
                    targetValueObj[dstKey] = timings[srcKey];
                }
                if (Object.prototype.hasOwnProperty.call(stdevs, srcKey)) {
                    targetStdevObj[dstKey] = stdevs[srcKey];
                }
            }
        }

        function copyLocalMetricKeysWithPrefix(targetValueObj, targetStdevObj, sourceResult, valueKey, stdevKey, keyMap) {
            const values = sourceResult && sourceResult[valueKey] ? sourceResult[valueKey] : {};
            const stdevs = sourceResult && sourceResult[stdevKey] ? sourceResult[stdevKey] : {};
            for (const [srcKey, dstKey] of Object.entries(keyMap || {})) {
                if (Object.prototype.hasOwnProperty.call(values, srcKey)) {
                    targetValueObj[dstKey] = values[srcKey];
                }
                if (Object.prototype.hasOwnProperty.call(stdevs, srcKey)) {
                    targetStdevObj[dstKey] = stdevs[srcKey];
                }
            }
        }

        function copyAllLocalMetricKeysWithPrefix(targetValueObj, targetStdevObj, sourceResult, valueKey, stdevKey, prefix, transformKey = null) {
            const values = sourceResult && sourceResult[valueKey] && typeof sourceResult[valueKey] === 'object'
                ? sourceResult[valueKey]
                : {};
            const stdevs = sourceResult && sourceResult[stdevKey] && typeof sourceResult[stdevKey] === 'object'
                ? sourceResult[stdevKey]
                : {};
            const pfx = String(prefix || '').trim();
            const mapKey = (key) => {
                const raw = String(key || '').trim();
                if (!raw) return '';
                const next = (typeof transformKey === 'function') ? String(transformKey(raw) || '').trim() : raw;
                if (!next) return '';
                return pfx ? `${pfx}_${next}` : next;
            };

            for (const [srcKey, value] of Object.entries(values)) {
                const dstKey = mapKey(srcKey);
                if (!dstKey) continue;
                targetValueObj[dstKey] = value;
            }
            for (const [srcKey, stdev] of Object.entries(stdevs)) {
                const dstKey = mapKey(srcKey);
                if (!dstKey) continue;
                targetStdevObj[dstKey] = stdev;
            }
        }

        async function runSubgraphLocally(runCtx, iterations, warmup) {
            const safeWarmup = Math.max(0, Math.floor(Number(warmup) || 0));
            const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));

            const patternFile = (config.selectedFiles && config.selectedFiles[0]) ? config.selectedFiles[0] : null;
            const targetFile = (config.selectedFiles && config.selectedFiles[1]) ? config.selectedFiles[1] : null;
            if (!patternFile || !targetFile || !patternFile.path || !targetFile.path) {
                throw new Error('Subgraph requires a pattern and target file');
            }

            const [patternTextRaw, targetTextRaw] = await Promise.all([
                getRepoFileText(patternFile.path),
                getRepoFileText(targetFile.path)
            ]);
            if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };

            const patternFormat = getLocalGraphFormatFromFile(patternFile);
            const targetFormat = getLocalGraphFormatFromFile(targetFile);
            const dual = buildLocalDualFormatGraphPair({
                patternText: patternTextRaw,
                targetText: targetTextRaw,
                patternFormat,
                targetFormat
            });

            const prevSelectedFiles = Array.isArray(config.selectedFiles) ? config.selectedFiles.slice() : [];
            const tempKeys = [];
            const setTemp = (path, text) => {
                const key = String(path);
                _localInMemoryRepoFiles.set(key, String(text || ''));
                tempKeys.push(key);
                return key;
            };

            const vfPatternPath = setTemp('__local/subgraph_pattern.vf', dual.vf.patternText);
            const vfTargetPath = setTemp('__local/subgraph_target.vf', dual.vf.targetText);
            const ladPatternPath = setTemp('__local/subgraph_pattern.lad', dual.lad.patternText);
            const ladTargetPath = setTemp('__local/subgraph_target.lad', dual.lad.targetText);

            try {
                config.selectedFiles = [
                    { path: vfPatternPath, name: 'subgraph_pattern.vf' },
                    { path: vfTargetPath, name: 'subgraph_target.vf' }
                ];
                const vf3Run = await runVf3Locally(runCtx, safeIterations, safeWarmup);
                if (vf3Run && vf3Run.status === 'aborted') return vf3Run;

                const vf3BaselineCounts = (vf3Run && vf3Run._vf3BaselineCounts) ? vf3Run._vf3BaselineCounts : null;

                config.selectedFiles = [
                    { path: ladPatternPath, name: 'subgraph_pattern.lad' },
                    { path: ladTargetPath, name: 'subgraph_target.lad' }
                ];
                const glasgowRun = await runGlasgowLocally(runCtx, safeIterations, safeWarmup, {
                    baselineFormatFlag: 'vertexlabelledlad',
                    resultAlgorithm: 'glasgow',
                    vf3BaselineCounts,
                    forceUseVf3GeneratedInputs: true,
                    enforceInducedCount: false
                });
                if (glasgowRun && glasgowRun.status === 'aborted') return glasgowRun;

                const vf3Result = vf3Run && vf3Run.result && typeof vf3Run.result === 'object' ? vf3Run.result : null;
                const glasgowResult = glasgowRun && glasgowRun.result && typeof glasgowRun.result === 'object' ? glasgowRun.result : null;

                const combinedOutput = [vf3Run && vf3Run.output, glasgowRun && glasgowRun.output]
                    .filter(part => typeof part === 'string' && part.trim())
                    .join('\n\n');

                const result = {
                    algorithm: 'subgraph',
                    status: 'success',
                    output: combinedOutput || 'No output',
                    iterations: safeIterations,
                    warmup: safeWarmup,
                    subgraph_phase: 'full',
                    timings_ms: {},
                    timings_ms_stdev: {},
                    memory_kb: {},
                    memory_kb_stdev: {},
                    local_wasm_module_refresh_ms: {},
                    local_wasm_module_refresh_ms_stdev: {}
                };

                const normalizeGlasgowKey = (key) => {
                    const raw = String(key || '').trim();
                    if (raw === 'first') return 'baseline_first';
                    if (raw === 'all') return 'baseline_all';
                    return raw;
                };
                copyAllLocalMetricKeysWithPrefix(
                    result.timings_ms,
                    result.timings_ms_stdev,
                    vf3Result,
                    'timings_ms',
                    'timings_ms_stdev',
                    'vf3'
                );
                copyAllLocalMetricKeysWithPrefix(
                    result.timings_ms,
                    result.timings_ms_stdev,
                    glasgowResult,
                    'timings_ms',
                    'timings_ms_stdev',
                    'glasgow',
                    normalizeGlasgowKey
                );
                copyAllLocalMetricKeysWithPrefix(
                    result.memory_kb,
                    result.memory_kb_stdev,
                    vf3Result,
                    'memory_kb',
                    'memory_kb_stdev',
                    'vf3'
                );
                copyAllLocalMetricKeysWithPrefix(
                    result.memory_kb,
                    result.memory_kb_stdev,
                    glasgowResult,
                    'memory_kb',
                    'memory_kb_stdev',
                    'glasgow',
                    normalizeGlasgowKey
                );
                copyAllLocalMetricKeysWithPrefix(
                    result.local_wasm_module_refresh_ms,
                    result.local_wasm_module_refresh_ms_stdev,
                    vf3Result,
                    'local_wasm_module_refresh_ms',
                    'local_wasm_module_refresh_ms_stdev',
                    'vf3'
                );
                copyAllLocalMetricKeysWithPrefix(
                    result.local_wasm_module_refresh_ms,
                    result.local_wasm_module_refresh_ms_stdev,
                    glasgowResult,
                    'local_wasm_module_refresh_ms',
                    'local_wasm_module_refresh_ms_stdev',
                    'glasgow',
                    normalizeGlasgowKey
                );

                if (!Object.keys(result.timings_ms).length) delete result.timings_ms;
                if (!Object.keys(result.timings_ms_stdev).length) delete result.timings_ms_stdev;
                if (Object.keys(result.memory_kb).length) {
                    const metricSource = (vf3Result && vf3Result.memory_metric_kind) ? vf3Result : glasgowResult;
                    if (metricSource) {
                        if (metricSource.memory_metric_kind) result.memory_metric_kind = metricSource.memory_metric_kind;
                        if (metricSource.memory_metric_label) result.memory_metric_label = metricSource.memory_metric_label;
                        if (metricSource.memory_metric_unit) result.memory_metric_unit = metricSource.memory_metric_unit;
                    }
                } else {
                    delete result.memory_kb;
                    delete result.memory_kb_stdev;
                }
                if (!Object.keys(result.local_wasm_module_refresh_ms).length) delete result.local_wasm_module_refresh_ms;
                if (!Object.keys(result.local_wasm_module_refresh_ms_stdev).length) delete result.local_wasm_module_refresh_ms_stdev;

                const matchCounts = {};
                const copyMatchCountsWithPrefix = (sourceResult, prefix, transformKey = null) => {
                    const match = sourceResult && sourceResult.match_counts && typeof sourceResult.match_counts === 'object'
                        ? sourceResult.match_counts
                        : {};
                    const pfx = String(prefix || '').trim();
                    for (const [rawKey, rawValue] of Object.entries(match)) {
                        const srcKey = String(rawKey || '').trim();
                        if (!srcKey) continue;
                        const mapped = typeof transformKey === 'function'
                            ? String(transformKey(srcKey) || '').trim()
                            : srcKey;
                        if (!mapped) continue;
                        const dstKey = pfx ? `${pfx}_${mapped}` : mapped;
                        matchCounts[dstKey] = rawValue;
                    }
                };
                copyMatchCountsWithPrefix(vf3Result, 'vf3');
                copyMatchCountsWithPrefix(glasgowResult, 'glasgow', (key) => {
                    if (key === 'baseline') return 'baseline';
                    return key;
                });
                if (Object.keys(matchCounts).length) {
                    result.match_counts = matchCounts;
                }

                const prefixedVariantMeta = [];
                const addPrefixedVariantMeta = (sourceResult, prefix, normalizeMetricKey = null) => {
                    const rows = Array.isArray(sourceResult && sourceResult.variant_metadata)
                        ? sourceResult.variant_metadata
                        : [];
                    const pfx = String(prefix || '').trim();
                    const normalize = (rawKey) => {
                        const key = String(rawKey || '').trim();
                        if (!key) return '';
                        return (typeof normalizeMetricKey === 'function') ? String(normalizeMetricKey(key) || '').trim() : key;
                    };
                    const prefixKey = (rawKey) => {
                        const key = normalize(rawKey);
                        if (!key) return '';
                        return pfx ? `${pfx}_${key}` : key;
                    };

                    for (const row of rows) {
                        const src = (row && typeof row === 'object') ? row : null;
                        if (!src) continue;
                        const variantIdRaw = String(src.variant_id || '').trim();
                        const labelRaw = String(src.label || variantIdRaw || '').trim();
                        if (!labelRaw) continue;
                        const entry = {
                            variant_id: variantIdRaw ? `${pfx}_${variantIdRaw}` : `${pfx}_${labelRaw.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`,
                            label: labelRaw,
                            role: String(src.role || '').trim() || (String(src.variant_id || '').includes('baseline') ? 'baseline' : 'variant')
                        };
                        const timingKeys = (src.timing_keys && typeof src.timing_keys === 'object') ? src.timing_keys : null;
                        const memoryKeys = (src.memory_keys && typeof src.memory_keys === 'object') ? src.memory_keys : null;
                        const timingKey = String(src.timing_key || '').trim();
                        const memoryKey = String(src.memory_key || '').trim();
                        if (timingKeys) {
                            entry.timing_keys = {
                                first: prefixKey(timingKeys.first),
                                all: prefixKey(timingKeys.all)
                            };
                        }
                        if (memoryKeys) {
                            entry.memory_keys = {
                                first: prefixKey(memoryKeys.first),
                                all: prefixKey(memoryKeys.all)
                            };
                        }
                        if (timingKey) entry.timing_key = prefixKey(timingKey);
                        if (memoryKey) entry.memory_key = prefixKey(memoryKey);
                        prefixedVariantMeta.push(entry);
                    }
                };
                addPrefixedVariantMeta(vf3Result, 'vf3');
                addPrefixedVariantMeta(glasgowResult, 'glasgow', normalizeGlasgowKey);
                if (prefixedVariantMeta.length) {
                    result.variant_metadata = prefixedVariantMeta;
                }

                let visualization = null;
                if (vf3Result && vf3Result.visualization && typeof vf3Result.visualization === 'object') {
                    try {
                        visualization = JSON.parse(JSON.stringify(vf3Result.visualization));
                        if (visualization && typeof visualization === 'object') {
                            visualization.algorithm = 'subgraph';
                            if (Array.isArray(visualization.visualization_iterations)) {
                                for (const item of visualization.visualization_iterations) {
                                    if (item && typeof item === 'object') item.algorithm = 'subgraph';
                                }
                            }
                        }
                    } catch (_) {
                        visualization = vf3Result.visualization;
                    }
                } else if (glasgowResult && glasgowResult.visualization) {
                    visualization = glasgowResult.visualization;
                }
                if (visualization) {
                    result.visualization = visualization;
                }
                if (glasgowRun && Array.isArray(glasgowRun._glasgowIterationDiagnostics)) {
                    result._glasgowIterationDiagnostics = glasgowRun._glasgowIterationDiagnostics;
                }
                result.equivalence_check = {
                    applies: true,
                    records: [
                        {
                            algorithm: 'subgraph',
                            variant: 'premade_translation',
                            iteration: 1,
                            attempt: 1,
                            seed: null,
                            selected_for_solver: true,
                            equivalent: !!(directEquivalenceReport && directEquivalenceReport.equivalent),
                            note: String(directEquivalenceReport && directEquivalenceReport.summary ? directEquivalenceReport.summary : ''),
                            details: directEquivalenceReport
                        }
                    ],
                    selected_for_solver_count: 1,
                    selected_for_solver_failures: (directEquivalenceReport && directEquivalenceReport.equivalent) ? 0 : 1,
                    graphs_not_mathematically_identical: !(directEquivalenceReport && directEquivalenceReport.equivalent)
                };
                if (!(directEquivalenceReport && directEquivalenceReport.equivalent)) {
                    const out = String(result.output || '').replace(/\s+$/, '');
                    result.output = `${out}\n[Equivalence] Graphs were not mathematically identical for one or more selected solver inputs.`;
                }

                return {
                    status: 'success',
                    output: combinedOutput || 'No output',
                    result
                };
            } finally {
                for (const key of tempKeys) _localInMemoryRepoFiles.delete(key);
                config.selectedFiles = prevSelectedFiles;
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
            const prevAbortSignal = localWasmActiveAbortSignal;
            localWasmActiveAbortSignal = runCtx && runCtx.abortController ? runCtx.abortController.signal : null;
            try {
                if (algoKey === 'vf3') {
                    try {
                        return await runVf3Locally(runCtx, iterations, warmup);
                    } catch (error) {
                        const msg = error && error.message ? error.message : String(error);
                        if (msg.includes('Failed to load script') || msg.includes('WASM factory not found')) {
                            throw new Error('Local WASM modules not found. Run the "Build WASM Modules" workflow on this branch (it commits files into wasm/ and uploads a wasm-modules artifact).');
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
                            throw new Error('Local WASM modules not found. Run the "Build WASM Modules" workflow on this branch (it commits files into wasm/ and uploads a wasm-modules artifact).');
                        }
                        throw error;
                    }
                }

                if (algoKey === 'glasgow') {
                    try {
                        // Use normalized vertex-labelled LAD locally so the LLM Glasgow parsers cannot
                        // misinterpret unlabeled LAD rows that look like "<label> <count> ...".
                        return await runGlasgowLocally(runCtx, iterations, warmup, {
                            baselineFormatFlag: 'vertexlabelledlad',
                            resultAlgorithm: 'glasgow'
                        });
                    } catch (error) {
                        const msg = error && error.message ? error.message : String(error);
                        if (msg.includes('Failed to load script') || msg.includes('WASM factory not found')) {
                            throw new Error('Glasgow local WASM modules are missing or incomplete. Run the "Build WASM Modules" workflow on this branch, then confirm `wasm/manifest.json` contains at least `glasgow_baseline` plus any `glasgow_*` variants you expect to run.');
                        }
                        throw error;
                    }
                }

                if (algoKey === 'subgraph') {
                    try {
                        return await runSubgraphLocally(runCtx, iterations, warmup);
                    } catch (error) {
                        const msg = error && error.message ? error.message : String(error);
                        if (msg.includes('Failed to load script') || msg.includes('WASM factory not found')) {
                            throw new Error('Subgraph local WASM requires both VF3 and Glasgow module families. Run the "Build WASM Modules" workflow, then confirm `wasm/manifest.json` includes both baselines (`vf3_baseline`, `glasgow_baseline`) and any `vf3_*` / `glasgow_*` variants you expect.');
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
            } finally {
                localWasmActiveAbortSignal = prevAbortSignal;
            }
        }

        const _legacyGetRepoFileText = getRepoFileText;
        const _localInMemoryRepoFiles = new Map();
        getRepoFileText = async function(path) {
            const key = String(path || '').trim();
            if (key && _localInMemoryRepoFiles.has(key)) {
                return _localInMemoryRepoFiles.get(key);
            }
            return await _legacyGetRepoFileText(path);
        };

        let _localGeneratedIterationInputsByAlgo = Object.create(null);

        function clearLocalGeneratedIterationInputs() {
            _localGeneratedIterationInputsByAlgo = Object.create(null);
        }

        function setLocalGeneratedIterationInputs(algoKey, entries) {
            const key = String(algoKey || '').trim().toLowerCase();
            if (!key) return;
            const list = Array.isArray(entries) ? entries : [];
            _localGeneratedIterationInputsByAlgo[key] = list.map((entry) => {
                const selected = Array.isArray(entry && entry.selectedFiles) ? entry.selectedFiles : [];
                return {
                    seed: entry && Object.prototype.hasOwnProperty.call(entry, 'seed') ? entry.seed : null,
                    metadata: entry && entry.metadata && typeof entry.metadata === 'object' ? entry.metadata : {},
                    selectedFiles: selected
                        .map((f) => ({
                            path: String(f && f.path ? f.path : ''),
                            name: String(f && f.name ? f.name : '')
                        }))
                        .filter((f) => f.path)
                };
            });
        }

        function getLocalGeneratedIterationInput(algoKey, iterIndex) {
            const key = String(algoKey || '').trim().toLowerCase();
            if (!key) return null;
            const list = _localGeneratedIterationInputsByAlgo[key];
            if (!Array.isArray(list) || !list.length) return null;
            const idxRaw = Number(iterIndex);
            const idx = Number.isInteger(idxRaw) ? idxRaw : 0;
            if (idx >= 0 && idx < list.length) return list[idx];
            return list[list.length - 1] || null;
        }

        const _legacyRunAlgorithmLocally = runAlgorithmLocally;
        runAlgorithmLocally = async function(runCtx, algoId, iterations, warmup) {
            const inputMode = (typeof getInputMode === 'function') ? getInputMode() : 'premade';
            const algoKey = String(algoId || '').trim().toLowerCase();
            if (inputMode !== 'generate') {
                clearLocalGeneratedIterationInputs();
                return await _legacyRunAlgorithmLocally(runCtx, algoId, iterations, warmup);
            }

            if (typeof createLocalExactGeneratorSession !== 'function') {
                throw new Error('Local generator runtime is unavailable.');
            }

            if (!['dijkstra', 'vf3', 'glasgow', 'subgraph'].includes(algoKey)) {
                throw new Error(`Local generator mode is not implemented for "${algoKey}".`);
            }

            const prevSelectedFiles = Array.isArray(config.selectedFiles) ? config.selectedFiles.slice() : [];
            _localInMemoryRepoFiles.clear();
            clearLocalGeneratedIterationInputs();
            try {
                const safeIterations = Math.max(1, Math.floor(Number(iterations) || 0));
                const session = createLocalExactGeneratorSession({
                    algorithm: algoKey,
                    n: config.generator && config.generator.n,
                    k: config.generator && config.generator.k,
                    graphFamily: config.generator && config.generator.graphFamily,
                    density: config.generator && config.generator.density,
                    seed: config.generator && config.generator.seed
                });

                const generatedRuns = [];
                const equivalenceRecords = [];
                for (let iter = 1; iter <= safeIterations; iter++) {
                    if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                    const maxAttempts = algoKey === 'subgraph' ? 10 : 1;
                    let acceptedRun = null;
                    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                        if (runCtx && runCtx.aborted) return { status: 'aborted', error: 'Run Aborted' };
                        const generated = await session.generateForRun(`${algoKey}_iter`, String(iter));
                        const files = Array.isArray(generated && generated.files) ? generated.files : [];
                        if (!files.length) {
                            const selected = attempt === maxAttempts;
                            const details = { equivalent: false, summary: 'local_generator_produced_no_files' };
                            equivalenceRecords.push({
                                algorithm: algoKey,
                                variant: `${algoKey}_iter`,
                                iteration: iter,
                                attempt,
                                seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed') ? generated.seed : null,
                                selected_for_solver: selected,
                                equivalent: false,
                                note: details.summary,
                                details
                            });
                            if (selected) {
                                throw new Error(`Local generator did not produce any files for iteration ${iter} after ${maxAttempts} attempts.`);
                            }
                            continue;
                        }
                        const iterScopedFiles = [];
                        const iterPrefix = `__local/generated/${algoKey}/iter_${iter}/attempt_${attempt}`;
                        for (const f of files) {
                            const p = String(f && f.path ? f.path : '').trim();
                            if (!p) continue;
                            const scopedPath = `${iterPrefix}/${p.replace(/^[\\/]+/, '')}`;
                            const text = String(f && f.text ? f.text : '');
                            const n = {
                                name: String(f && f.name ? f.name : ''),
                                path: scopedPath,
                                text
                            };
                            iterScopedFiles.push(n);
                            _localInMemoryRepoFiles.set(scopedPath, text);
                        }
                        if (algoKey !== 'subgraph') {
                            acceptedRun = {
                                ...generated,
                                files: iterScopedFiles
                            };
                            break;
                        }

                        const pickRoleFile = (entries, roleNeedle, ext) => (Array.isArray(entries) ? entries : []).find((entry) => {
                            const name = String(entry && (entry.name || entry.path) ? (entry.name || entry.path) : '').toLowerCase();
                            return name.includes(roleNeedle) && name.endsWith(ext);
                        });
                        const vfPattern = pickRoleFile(iterScopedFiles, 'pattern', '.vf');
                        const vfTarget = pickRoleFile(iterScopedFiles, 'target', '.vf');
                        const ladPattern = pickRoleFile(iterScopedFiles, 'pattern', '.lad');
                        const ladTarget = pickRoleFile(iterScopedFiles, 'target', '.lad');

                        let details = null;
                        if (vfPattern && vfTarget && ladPattern && ladTarget) {
                            details = buildLocalVfLadEquivalenceReport({
                                vfPatternText: String(vfPattern.text || ''),
                                vfTargetText: String(vfTarget.text || ''),
                                ladPatternText: String(ladPattern.text || ''),
                                ladTargetText: String(ladTarget.text || '')
                            });
                        } else {
                            details = { equivalent: false, summary: 'missing_expected_vf_or_lad_files' };
                        }

                        const equivalent = !!(details && details.equivalent);
                        const selected = equivalent || attempt === maxAttempts;
                        equivalenceRecords.push({
                            algorithm: algoKey,
                            variant: `${algoKey}_iter`,
                            iteration: iter,
                            attempt,
                            seed: generated && Object.prototype.hasOwnProperty.call(generated, 'seed') ? generated.seed : null,
                            selected_for_solver: selected,
                            equivalent,
                            note: String(details && details.summary ? details.summary : ''),
                            details
                        });
                        if (selected) {
                            let selectedFilesForRun = iterScopedFiles;
                            if (algoKey === 'subgraph') {
                                const canonicalized = canonicalizeLocalSubgraphIterationFiles(iterScopedFiles);
                                if (!canonicalized || !Array.isArray(canonicalized.files) || canonicalized.files.length < 4) {
                                    throw new Error(`Local canonicalization failed for subgraph iteration ${iter}.`);
                                }
                                selectedFilesForRun = canonicalized.files;
                                for (const cf of selectedFilesForRun) {
                                    if (cf && cf.path) {
                                        _localInMemoryRepoFiles.set(String(cf.path), String(cf.text || ''));
                                    }
                                }
                            }
                            acceptedRun = {
                                ...generated,
                                files: selectedFilesForRun
                            };
                            break;
                        }
                    }
                    if (!acceptedRun) {
                        throw new Error(`Local generator failed to produce usable inputs for iteration ${iter}.`);
                    }
                    generatedRuns.push(acceptedRun);
                }

                const pickByName = (files, needle) => (Array.isArray(files) ? files : []).find(f => String(f && f.name ? f.name : '').toLowerCase().includes(String(needle || '').toLowerCase()));
                const pickByExt = (files, ext) => (Array.isArray(files) ? files : []).find(f => String(f && (f.name || f.path) ? (f.name || f.path) : '').toLowerCase().endsWith(String(ext || '').toLowerCase()));
                const pickPatternTargetPair = (files, prefixNeedle, preferredExts) => {
                    const exts = Array.isArray(preferredExts) ? preferredExts.map(e => String(e || '').toLowerCase()) : [];
                    const candidates = (Array.isArray(files) ? files : []).filter(Boolean);
                    const pickRole = (role) => {
                        const roleLower = String(role || '').toLowerCase();
                        const byPrefixAndRole = candidates.find(f => {
                            const name = String(f && (f.name || f.path) ? (f.name || f.path) : '').toLowerCase();
                            if (!name.includes(roleLower)) return false;
                            if (prefixNeedle && !name.includes(String(prefixNeedle).toLowerCase())) return false;
                            if (!exts.length) return true;
                            return exts.some(ext => name.endsWith(ext));
                        });
                        if (byPrefixAndRole) return byPrefixAndRole;
                        const byRoleExt = candidates.find(f => {
                            const name = String(f && (f.name || f.path) ? (f.name || f.path) : '').toLowerCase();
                            if (!name.includes(roleLower)) return false;
                            if (!exts.length) return true;
                            return exts.some(ext => name.endsWith(ext));
                        });
                        if (byRoleExt) return byRoleExt;
                        return candidates.find(f => String(f && (f.name || f.path) ? (f.name || f.path) : '').toLowerCase().includes(roleLower)) || null;
                    };
                    return {
                        pattern: pickRole('pattern'),
                        target: pickRole('target')
                    };
                };
                const normalizeSelected = (entry) => ({
                    path: String(entry && entry.path ? entry.path : ''),
                    name: String(entry && entry.name ? entry.name : '')
                });
                const buildIterationSelection = (files, selectionAlgo) => {
                    const all = Array.isArray(files) ? files : [];
                    if (!all.length) return null;
                    if (selectionAlgo === 'dijkstra') {
                        const input = all[0];
                        return input ? [normalizeSelected(input)] : null;
                    }
                    let pair = null;
                    if (selectionAlgo === 'vf3') {
                        pair = pickPatternTargetPair(all, 'vf3', ['.vf', '.grf']);
                    } else if (selectionAlgo === 'glasgow') {
                        pair = pickPatternTargetPair(all, 'glasgow', ['.lad']);
                    }
                    if (!pair || !pair.pattern || !pair.target) {
                        pair = {
                            pattern: pickByName(all, 'pattern') || pickByExt(all, '.lad') || pickByExt(all, '.vf') || pickByExt(all, '.grf') || all[0],
                            target: pickByName(all, 'target') || all[all.length - 1]
                        };
                    }
                    if (!pair.pattern || !pair.target) return null;
                    return [normalizeSelected(pair.pattern), normalizeSelected(pair.target)];
                };

                const dijkstraEntries = [];
                const vf3Entries = [];
                const glasgowEntries = [];
                const generatedSeeds = [];
                for (const generated of generatedRuns) {
                    const files = Array.isArray(generated && generated.files) ? generated.files : [];
                    const metadata = generated && generated.metadata && typeof generated.metadata === 'object' ? generated.metadata : {};
                    const seed = generated && Object.prototype.hasOwnProperty.call(generated, 'seed') ? generated.seed : null;
                    generatedSeeds.push(seed);
                    const dijkstraSelected = buildIterationSelection(files, 'dijkstra');
                    if (dijkstraSelected) dijkstraEntries.push({ seed, metadata, selectedFiles: dijkstraSelected });
                    const vf3Selected = buildIterationSelection(files, 'vf3');
                    if (vf3Selected) vf3Entries.push({ seed, metadata, selectedFiles: vf3Selected });
                    const glasgowSelected = buildIterationSelection(files, 'glasgow') || vf3Selected;
                    if (glasgowSelected) glasgowEntries.push({ seed, metadata, selectedFiles: glasgowSelected });
                }

                if (algoKey === 'dijkstra') {
                    setLocalGeneratedIterationInputs('dijkstra', dijkstraEntries);
                } else if (algoKey === 'vf3') {
                    setLocalGeneratedIterationInputs('vf3', vf3Entries);
                } else if (algoKey === 'glasgow') {
                    setLocalGeneratedIterationInputs('glasgow', glasgowEntries);
                } else if (algoKey === 'subgraph') {
                    setLocalGeneratedIterationInputs('vf3', vf3Entries);
                    setLocalGeneratedIterationInputs('glasgow', glasgowEntries.length ? glasgowEntries : vf3Entries);
                }

                const primaryEntries = (() => {
                    if (algoKey === 'dijkstra') return dijkstraEntries;
                    if (algoKey === 'vf3') return vf3Entries;
                    if (algoKey === 'glasgow') return glasgowEntries;
                    if (algoKey === 'subgraph') return vf3Entries.length ? vf3Entries : glasgowEntries;
                    return [];
                })();
                const firstSelectedFiles = primaryEntries.length ? primaryEntries[0].selectedFiles : [];
                if (!firstSelectedFiles.length) {
                    throw new Error('Local generator did not produce usable iteration inputs.');
                }
                config.selectedFiles = firstSelectedFiles.map((f) => ({
                    path: String(f && f.path ? f.path : ''),
                    name: String(f && f.name ? f.name : '')
                }));

                const localResult = await _legacyRunAlgorithmLocally(runCtx, algoKey, iterations, warmup);
                if (localResult && localResult.status === 'success' && localResult.result && typeof localResult.result === 'object') {
                    const result = localResult.result;
                    result.inputs = Object.assign({}, result.inputs || {}, {
                        input_mode: 'generate',
                        n: Number.isFinite(Number(config.generator && config.generator.n)) ? Number(config.generator.n) : config.generator.n,
                        graph_family: String((config.generator && config.generator.graphFamily) || 'random_density'),
                        density: Number.isFinite(Number(config.generator && config.generator.density)) ? Number(config.generator.density) : config.generator.density,
                        seed: session.generatedSeed
                    });
                    if (generatedSeeds.length) {
                        result.inputs.iteration_seeds = generatedSeeds.slice();
                    }
                    if (algoKey !== 'dijkstra') {
                        result.inputs.k = Number.isFinite(Number(config.generator && config.generator.k)) ? Number(config.generator.k) : config.generator.k;
                    }
                    if (algoKey === 'subgraph' && equivalenceRecords.length) {
                        const selected = equivalenceRecords.filter((r) => r && r.selected_for_solver);
                        const selectedFailures = selected.filter((r) => !r.equivalent);
                        result.equivalence_check = {
                            applies: true,
                            records: equivalenceRecords,
                            selected_for_solver_count: selected.length,
                            selected_for_solver_failures: selectedFailures.length,
                            graphs_not_mathematically_identical: selectedFailures.length > 0
                        };
                        if (selectedFailures.length > 0) {
                            const out = String(result.output || '').replace(/\s+$/, '');
                            result.output = `${out}\n[Equivalence] Graphs were not mathematically identical for one or more selected solver inputs.`;
                        }
                    }
                    const iterationEntries = primaryEntries.length
                        ? primaryEntries
                        : generatedSeeds.map((seed) => ({ seed, metadata: {}, selectedFiles: firstSelectedFiles }));
                    const entryAt = (idx) => {
                        if (!iterationEntries.length) return null;
                        if (idx >= 0 && idx < iterationEntries.length) return iterationEntries[idx];
                        return iterationEntries[iterationEntries.length - 1] || null;
                    };
                    const seedAt = (idx) => {
                        const entry = entryAt(idx);
                        if (entry && Object.prototype.hasOwnProperty.call(entry, 'seed')) return entry.seed;
                        return session.visSeed ?? session.generatedSeed;
                    };
                    const meta = (() => {
                        const firstEntry = entryAt(0);
                        return firstEntry && firstEntry.metadata && typeof firstEntry.metadata === 'object'
                            ? firstEntry.metadata
                            : {};
                    })();
                    const fallbackVisCount = Math.max(1, Math.floor(Number(result && result.iterations) || 1));
                    const buildRepeatedVisualization = (factory) => {
                        if (typeof factory !== 'function') return null;
                        const payloads = [];
                        for (let i = 0; i < fallbackVisCount; i++) {
                            payloads.push(factory(i));
                        }
                        return buildLocalVisualizationIterations(payloads);
                    };
                    const shouldRebuildGlasgowVisualization = (() => {
                        if (algoKey !== 'glasgow') return false;
                        if (!result.visualization || !Array.isArray(result.visualization.visualization_iterations) || !result.visualization.visualization_iterations.length) {
                            return true;
                        }
                        const first = result.visualization.visualization_iterations[0];
                        const noSolutions = Boolean(first && typeof first === 'object' && first.no_solutions);
                        const hasPatternNodes = iterationEntries.some((entry) => {
                            const m = entry && entry.metadata && typeof entry.metadata === 'object' ? entry.metadata : {};
                            return Array.isArray(m.pattern_nodes) && m.pattern_nodes.length > 0;
                        });
                        return noSolutions && hasPatternNodes;
                    })();
                    if ((algoKey === 'vf3' || algoKey === 'glasgow' || algoKey === 'subgraph') && result.visualization && Array.isArray(result.visualization.visualization_iterations)) {
                        result.visualization.seed = seedAt(0);
                        for (let i = 0; i < result.visualization.visualization_iterations.length; i++) {
                            const v = result.visualization.visualization_iterations[i];
                            if (v && typeof v === 'object') v.seed = seedAt(i);
                        }
                    }
                    if (
                        algoKey === 'vf3' &&
                        typeof buildLocalSubgraphLikeVisualization === 'function' &&
                        typeof buildLocalVisualizationIterations === 'function' &&
                        (!result.visualization || !Array.isArray(result.visualization.visualization_iterations) || !result.visualization.visualization_iterations.length)
                    ) {
                        const patternFile = config.selectedFiles[0];
                        const targetFile = config.selectedFiles[1];
                        const patternText = _localInMemoryRepoFiles.get(patternFile.path) || '';
                        const targetText = _localInMemoryRepoFiles.get(targetFile.path) || '';
                        try {
                            result.visualization = buildRepeatedVisualization((iterIndex) => buildLocalSubgraphLikeVisualization({
                                algorithm: 'vf3',
                                patternText,
                                targetText,
                                patternFormat: 'vf',
                                targetFormat: 'vf',
                                patternNodes: Array.isArray(meta.pattern_nodes) ? meta.pattern_nodes : null,
                                iteration: iterIndex + 1,
                                seed: seedAt(iterIndex)
                            }));
                        } catch (_) {}
                    } else if (
                        algoKey === 'subgraph' &&
                        typeof buildLocalSubgraphLikeVisualization === 'function' &&
                        typeof buildLocalVisualizationIterations === 'function' &&
                        (!result.visualization || !Array.isArray(result.visualization.visualization_iterations) || !result.visualization.visualization_iterations.length)
                    ) {
                        try {
                            const patternFile = config.selectedFiles[0];
                            const targetFile = config.selectedFiles[1];
                            const patternText = _localInMemoryRepoFiles.get(patternFile.path) || '';
                            const targetText = _localInMemoryRepoFiles.get(targetFile.path) || '';
                            const fmt = getLocalGraphFormatFromFile(patternFile);
                            result.visualization = buildRepeatedVisualization((iterIndex) => buildLocalSubgraphLikeVisualization({
                                algorithm: 'subgraph',
                                patternText,
                                targetText,
                                patternFormat: fmt,
                                targetFormat: getLocalGraphFormatFromFile(targetFile),
                                patternNodes: Array.isArray(meta.pattern_nodes) ? meta.pattern_nodes : null,
                                iteration: iterIndex + 1,
                                seed: seedAt(iterIndex)
                            }));
                        } catch (_) {}
                    } else if (algoKey === 'glasgow' && typeof buildLocalSubgraphLikeVisualization === 'function' && typeof buildLocalVisualizationIterations === 'function' && shouldRebuildGlasgowVisualization) {
                        try {
                            const patternFile = config.selectedFiles[0];
                            const targetFile = config.selectedFiles[1];
                            const patternText = _localInMemoryRepoFiles.get(patternFile.path) || '';
                            const targetText = _localInMemoryRepoFiles.get(targetFile.path) || '';
                            result.visualization = buildRepeatedVisualization((iterIndex) => buildLocalSubgraphLikeVisualization({
                                algorithm: 'glasgow',
                                patternText,
                                targetText,
                                patternFormat: getLocalGraphFormatFromFile(patternFile),
                                targetFormat: getLocalGraphFormatFromFile(targetFile),
                                patternNodes: Array.isArray(meta.pattern_nodes) ? meta.pattern_nodes : null,
                                iteration: iterIndex + 1,
                                seed: seedAt(iterIndex)
                            }));
                        } catch (_) {}
                    } else if (
                        algoKey === 'dijkstra' &&
                        typeof buildLocalDijkstraVisualization === 'function' &&
                        typeof buildLocalVisualizationIterations === 'function' &&
                        (!result.visualization || !Array.isArray(result.visualization.visualization_iterations) || !result.visualization.visualization_iterations.length)
                    ) {
                        try {
                            const inputFile = config.selectedFiles[0];
                            const inputText = inputFile && inputFile.path ? (_localInMemoryRepoFiles.get(inputFile.path) || '') : '';
                            result.visualization = buildRepeatedVisualization((iterIndex) => buildLocalDijkstraVisualization({
                                inputText,
                                iteration: iterIndex + 1,
                                seed: seedAt(iterIndex),
                                solverSolutions: []
                            }));
                        } catch (_) {}
                    }
                    if (algoKey === 'dijkstra' && result.visualization && Array.isArray(result.visualization.visualization_iterations)) {
                        result.visualization.seed = seedAt(0);
                        for (let i = 0; i < result.visualization.visualization_iterations.length; i++) {
                            const v = result.visualization.visualization_iterations[i];
                            if (v && typeof v === 'object') v.seed = seedAt(i);
                        }
                    }
                }
                return localResult;
            } finally {
                clearLocalGeneratedIterationInputs();
                _localInMemoryRepoFiles.clear();
                config.selectedFiles = prevSelectedFiles;
            }
        };
