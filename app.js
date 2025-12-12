// Lightweight local runner for algorithms (no GitHub Actions required).
// Start with: node app.js
// Endpoints:
//   GET  /status        -> { ok: true }
//   GET  /files         -> [{ path, name }]
//   POST /run           -> { status, output, error }
//
// Algorithms:
// - dijkstra: builds/runs baselines/dijkstra
// - vf3: runs baseline vf3 (if available) plus LLM VF3 variants (src/vf3, src/chatvf3)
// Glasgow and other heavy dependencies are not built automatically; if their binaries
// already exist, they will be used, otherwise a friendly error is returned.

const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const isWin = process.platform === 'win32';
const dataDir = path.join(__dirname, 'data');

const binaries = {
  dijkstra: path.join(__dirname, 'baselines', isWin ? 'dijkstra.exe' : 'dijkstra'),
  vf3Baseline: path.join(__dirname, 'baselines', 'vf3lib', 'bin', isWin ? 'vf3.exe' : 'vf3'),
  vf3Gemini: path.join(__dirname, 'src', isWin ? 'vf3.exe' : 'vf3'),
  vf3Chat: path.join(__dirname, 'src', isWin ? 'chatvf3.exe' : 'chatvf3'),
};

async function runCommand(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { ...opts, shell: false });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => (stdout += d.toString()));
    child.stderr.on('data', (d) => (stderr += d.toString()));
    child.on('error', reject);
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

async function ensureDijkstraBuilt() {
  if (fs.existsSync(binaries.dijkstra)) return;
  const srcDir = path.join(__dirname, 'baselines', 'Dijkastra Shortest Path');
  const main = path.join(srcDir, 'dijkstra_main.cpp');
  const impl = path.join(srcDir, 'dijkstra.cpp');
  const include = srcDir;
  const out = binaries.dijkstra;
  const args = ['-std=c++17', '-O3', '-I', include, main, impl, '-o', out];
  const res = await runCommand('g++', args);
  if (res.code !== 0) {
    throw new Error(`Failed to build Dijkstra: ${res.stderr || res.stdout}`);
  }
}

async function ensureVf3Built() {
  // LLM Gemini VF3
  if (!fs.existsSync(binaries.vf3Gemini)) {
    const src = path.join(__dirname, 'src', 'VF3.cpp');
    const res = await runCommand('g++', ['-std=c++17', '-O3', src, '-o', binaries.vf3Gemini]);
    if (res.code !== 0) throw new Error(`Failed to build VF3 Gemini: ${res.stderr || res.stdout}`);
  }
  // LLM ChatGPT VF3
  if (!fs.existsSync(binaries.vf3Chat)) {
    const src = path.join(__dirname, 'src', 'chatVF3.cpp');
    const res = await runCommand('g++', ['-std=c++17', '-O3', src, '-o', binaries.vf3Chat]);
    if (res.code !== 0) throw new Error(`Failed to build VF3 ChatGPT: ${res.stderr || res.stdout}`);
  }
}

function formatNs(nsBigInt) {
  const s = nsBigInt.toString();
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

async function timedRun(cmd, args) {
  const start = process.hrtime.bigint();
  const res = await runCommand(cmd, args);
  const end = process.hrtime.bigint();
  return { ...res, duration: end - start };
}

function validateFileUnderData(p) {
  const resolved = path.resolve(__dirname, p);
  if (!resolved.startsWith(dataDir)) {
    throw new Error(`Invalid file path: ${p}`);
  }
  if (!fs.existsSync(resolved)) {
    throw new Error(`File not found: ${p}`);
  }
  return resolved;
}

async function listDataFiles() {
  const entries = await fs.promises.readdir(dataDir, { withFileTypes: true });
  return entries
    .filter((d) => d.isFile())
    .map((d) => ({ path: path.join('data', d.name), name: d.name }));
}

async function handleRun(body) {
  const algo = body.algorithm;
  const files = Array.isArray(body.files) ? body.files : [];
  if (!algo) throw new Error('algorithm is required');

  if (algo === 'dijkstra') {
    if (files.length !== 1) throw new Error('Dijkstra requires exactly one input file.');
    await ensureDijkstraBuilt();
    const f1 = validateFileUnderData(files[0]);
    const run = await timedRun(binaries.dijkstra, [f1]);
    if (run.code !== 0) throw new Error(run.stderr || run.stdout || 'Dijkstra failed');
    const output = `${run.stdout.trim()}\nRuntime (ns): ${formatNs(run.duration)}`;
    return output;
  }

  if (algo === 'glasgow') {
    throw new Error('Glasgow solver not available locally; requires external dependencies.');
  }

  if (algo === 'vf3') {
    if (files.length !== 2) throw new Error('VF3 requires two input files (pattern, target).');
    await ensureVf3Built();
    const p = validateFileUnderData(files[0]);
    const t = validateFileUnderData(files[1]);

    const sections = [];

    if (fs.existsSync(binaries.vf3Baseline)) {
      const baseFirst = await timedRun(binaries.vf3Baseline, ['-F', p, t]);
      const baseAll = await timedRun(binaries.vf3Baseline, [p, t]);
      if (baseFirst.code === 0 && baseAll.code === 0) {
        const baseResultLine = (baseAll.stdout.trim().split('\n')[0] || '').trim();
        sections.push('[VF3 baseline]');
        sections.push(baseResultLine || baseAll.stdout.trim());
        sections.push(
          `Runtime (ns): first=${formatNs(baseFirst.duration)} all=${formatNs(baseAll.duration)}`
        );
        sections.push('');
      } else {
        sections.push('[VF3 baseline] failed');
        sections.push(baseFirst.stderr || baseAll.stderr || baseFirst.stdout || baseAll.stdout);
        sections.push('');
      }
    } else {
      sections.push('[VF3 baseline]');
      sections.push('Binary not found (baselines/vf3lib/bin/vf3). Skipping baseline run.');
      sections.push('');
    }

    const gemFirst = await timedRun(binaries.vf3Gemini, ['--first-only', p, t]);
    const gemAll = await timedRun(binaries.vf3Gemini, [p, t]);
    if (gemFirst.code === 0 && gemAll.code === 0) {
      sections.push('[VF3 Gemini]');
      sections.push(gemAll.stdout.trim());
      sections.push(
        `Runtime (ns): first=${formatNs(gemFirst.duration)} all=${formatNs(gemAll.duration)}`
      );
      sections.push('');
    } else {
      sections.push('[VF3 Gemini] failed');
      sections.push(gemFirst.stderr || gemAll.stderr || gemFirst.stdout || gemAll.stdout);
      sections.push('');
    }

    const chatFirst = await timedRun(binaries.vf3Chat, ['--first-only', p, t]);
    const chatAll = await timedRun(binaries.vf3Chat, [p, t]);
    if (chatFirst.code === 0 && chatAll.code === 0) {
      sections.push('[VF3 ChatGPT]');
      sections.push(chatAll.stdout.trim());
      sections.push(
        `Runtime (ns): first=${formatNs(chatFirst.duration)} all=${formatNs(chatAll.duration)}`
      );
    } else {
      sections.push('[VF3 ChatGPT] failed');
      sections.push(chatFirst.stderr || chatAll.stderr || chatFirst.stdout || chatAll.stdout);
    }

    return sections.join('\n');
  }

  throw new Error(`Unknown algorithm: ${algo}`);
}

function sendJson(res, status, payload) {
  const data = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(data);
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      });
      return res.end();
    }

    if (req.method === 'GET' && req.url === '/status') {
      return sendJson(res, 200, { ok: true });
    }

    if (req.method === 'GET' && req.url === '/files') {
      const files = await listDataFiles();
      return sendJson(res, 200, { files });
    }

    if (req.method === 'POST' && req.url === '/run') {
      let body = '';
      req.on('data', (chunk) => (body += chunk));
      req.on('end', async () => {
        try {
          const parsed = body ? JSON.parse(body) : {};
          const output = await handleRun(parsed);
          sendJson(res, 200, { status: 'success', output });
        } catch (err) {
          sendJson(res, 400, { status: 'error', error: err.message || String(err) });
        }
      });
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'not found' }));
  } catch (err) {
    sendJson(res, 500, { status: 'error', error: err.message || String(err) });
  }
});

server.listen(PORT, () => {
  console.log(`Local runner listening on http://localhost:${PORT}`);
});
