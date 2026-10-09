// Local dev server for the scenes.   node serve.mjs [port] [--open]
// Binds 127.0.0.1 only (no Windows Firewall prompt, not reachable from the LAN) and
// 403s any path segment starting with '.', so .git/config (holds a PAT) is never served.
// The check runs on the realpath too, which catches 8.3 aliases (GIT~1) and junctions.
import { createServer } from 'http';
import { createReadStream, statSync, realpathSync } from 'fs';
import { join, resolve, relative, extname, isAbsolute } from 'path';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';

const ROOT = realpathSync.native(fileURLToPath(new URL('.', import.meta.url)));
const args = process.argv.slice(2);
const PORT = +(args.find(a => /^\d+$/.test(a)) ?? process.env.PORT ?? 7432);
const OPEN = args.includes('--open');
const BASE = `http://127.0.0.1:${PORT}/`;
const MIME = {
  '.html':'text/html; charset=utf-8', '.js':'text/javascript', '.mjs':'text/javascript', '.css':'text/css',
  '.json':'application/json', '.wasm':'application/wasm', '.svg':'image/svg+xml',
  '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.jfif':'image/jpeg',
  '.glb':'model/gltf-binary', '.gltf':'model/gltf+json', '.exr':'image/x-exr', '.hdr':'image/vnd.radiance',
  '.md':'text/plain; charset=utf-8', '.txt':'text/plain; charset=utf-8',
}; // everything else (.bin .f32 .u8 .gz ...) goes out as octet-stream

const dotted = p => p.split(/[\\/]/).some(s => s.startsWith('.'));
const stat = f => { try { return statSync(f); } catch { return null; } };
const send = (res, code) => { res.writeHead(code, { 'Content-Type':'text/plain' }); res.end(`${code}\n`); };
const openBrowser = () => exec(process.platform === 'win32' ? `start "" "${BASE}"`
  : `${process.platform === 'darwin' ? 'open' : 'xdg-open'} "${BASE}"`);

const server = createServer((req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405);
  let p;
  try { p = decodeURIComponent(new URL(req.url, BASE).pathname); } catch { return send(res, 400); }
  if (dotted(p)) return send(res, 403);
  let f = resolve(join(ROOT, p)), st = stat(f);
  if (st?.isDirectory()) { f = join(f, 'index.html'); st = stat(f); } // no directory listings
  if (!st?.isFile()) return send(res, 404);
  const rel = relative(ROOT, realpathSync.native(f));
  if (rel.startsWith('..') || isAbsolute(rel) || dotted(rel)) return send(res, 403);
  res.writeHead(200, { 'Content-Type': MIME[extname(f).toLowerCase()] ?? 'application/octet-stream',
    'Content-Length': st.size, 'Cache-Control': 'no-store' });
  if (req.method === 'HEAD') return res.end();
  createReadStream(f).on('error', () => res.destroy()).pipe(res);
});

server.on('error', e => {
  if (e.code !== 'EADDRINUSE') throw e;
  console.log(`Port ${PORT} is already in use (probably already serving): ${BASE}`);
  if (OPEN) openBrowser();
  setTimeout(() => process.exit(0), 500);
});
server.listen(PORT, '127.0.0.1', () => {
  console.log(`Serving ${ROOT}\n  ${BASE}                     Valley Map\n  ${BASE}neighbourhood.html  Alva Court block\nCtrl+C (or close this window) to stop.`);
  if (OPEN) openBrowser();
});
