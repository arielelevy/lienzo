// Medición M (2026-10-22): franjas, cuadros/s, nitidez y vuelta al tamaño con un Chrome real aislado (con ventana).
// Uso: node pruebas-agenticas/chrome_fit_real.mjs [--fit] [salida.json]. Con --fit sale con 1 si queda franja,
// si cambia el DPR, si un tamaño repetido rehace el layout o si la pestaña no vuelve a su tamaño al soltarla.
// Sin --fit mide el contrato anterior (viewport de sólo lectura); con --fit pide la emulación al tamaño del visor.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const fit = process.argv.includes('--fit');
const out = process.argv.slice(2).find(a => !a.startsWith('--'));
const host = fileURLToPath(new URL('../lienzo/browser_host.mjs', import.meta.url));
const root = join(tmpdir(), `lienzo-M-${process.pid}`);
const data = join(root, 'Google/Chrome/User Data');
mkdirSync(data, {recursive: true});
const page = join(root, 'pagina.html');
writeFileSync(page, `<!doctype html><meta charset=utf-8><title>medicion M</title>
<style>body{margin:0;font:14px system-ui}#n{position:fixed;top:4px;right:4px;font:24px monospace;background:#ffe}p{margin:4px 8px}</style>
<div id=n>0</div>${'<p>Texto denso para medir nitidez: Lorem ipsum dolor sit amet, consectetur adipiscing elit 0123456789.</p>'.repeat(60)}
<script>window.__resizes=0;addEventListener('resize',()=>window.__resizes++);let i=0;(function f(){document.getElementById('n').textContent=++i;requestAnimationFrame(f)})()</script>`);
const exe = [process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA]
  .filter(Boolean).map(r => join(r, 'Google/Chrome/Application/chrome.exe')).find(existsSync);
const chrome = spawn(exe, [`--user-data-dir=${data}`, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
  '--disable-features=CalculateNativeWinOcclusion', '--window-position=40,40', '--window-size=1500,900', `file:///${page.replaceAll('\\', '/')}`],
  {stdio: 'ignore', windowsHide: false});
const sleep = ms => new Promise(r => setTimeout(r, ms));
for (let i = 0; i < 100 && !existsSync(join(data, 'DevToolsActivePort')); i++) await sleep(100);
await sleep(800);
const port = readFileSync(join(data, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim();

// lector propio de la página (otra sesión CDP): innerWidth y resizes que ve quien usa esa PC
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const target = targets.find(t => t.type === 'page' && t.url.startsWith('file:'));
const probe = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => probe.addEventListener('open', r, {once: true}));
let pid = 0; const waits = new Map();
probe.addEventListener('message', e => { const m = JSON.parse(e.data); waits.get(m.id)?.(m.result); waits.delete(m.id); });
const look = () => new Promise(r => { const id = ++pid; waits.set(id, r); probe.send(JSON.stringify({id, method: 'Runtime.evaluate',
  params: {expression: '[innerWidth, innerHeight, window.__resizes, devicePixelRatio]', returnByValue: true}})); }).then(r => r.result.value);

const child = spawn(process.execPath, [host, join(root, 'perfil-lienzo')], {env: {...process.env, LOCALAPPDATA: root}, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true});
const queue = []; let rid = 0; const lines = createInterface({input: child.stdout});
lines.on('line', l => { const m = JSON.parse(l); queue.find(q => q.id === m.requestId)?.resolve(m); });
const ask = d => new Promise(resolve => { const id = ++rid; queue.push({id, resolve}); child.stdin.write(JSON.stringify({...d, requestId: id}) + '\n'); });
await ask({action: 'connect'});
let state;
for (let i = 0; i < 50; i++) { state = await ask({action: 'state'}); if (state.running) break; await sleep(100); }
if (!state.running) throw new Error('no conectó: ' + JSON.stringify(state));
const tab = state.tabs.find(t => t.url.startsWith('file:')).id;

function jpegSize(b64) {
  const h = Buffer.from(b64, 'base64');
  for (let i = 2; i + 9 < h.length;) { const m = h[i + 1], n = h.readUInt16BE(i + 2); if (m >= 0xc0 && m <= 0xc3) return [h.readUInt16BE(i + 7), h.readUInt16BE(i + 5)]; i += 2 + n; }
  return [0, 0];
}
const original = await look();
const result = {modo: fit ? 'fit (después)' : 'sin emulación (antes)', chrome: exe, ventana: original, visores: []};
for (const [w, h] of [[700, 1000], [1400, 520]]) {
  const before = await look();
  const opened = await ask({action: 'viewport', tab, width: w, height: h, ...(fit ? {fit: true} : {})});
  if (opened.status) throw new Error(JSON.stringify(opened));
  let frames = 0, last = '', img = [0, 0]; const t0 = Date.now();
  while (Date.now() - t0 < 3000) {
    const s = await ask({action: 'snapshot', tab, width: w, height: h});
    if (s.image && s.image !== last) { frames++; last = s.image; img = jpegSize(s.image); }
  }
  const s = await ask({action: 'snapshot', tab, width: w, height: h});
  const a = img[0] / img[1];
  const fittedW = Math.min(w, h * a), fittedH = Math.min(h, w / a);
  const after = await look();
  result.visores.push({visor: [w, h], pestanaCss: [s.width, s.height], jpeg: img,
    franjas: {horizontalPx: +(w - fittedW).toFixed(1), verticalPx: +(h - fittedH).toFixed(1)},
    cuadrosPorSegundo: +(frames / 3).toFixed(1), jpegPxPorPxCss: +(img[0] / s.width).toFixed(2), jpegPxPorPxVisor: +(img[0] / fittedW).toFixed(2),
    resizesEnLaPagina: after[2] - before[2], innerAntes: before.slice(0, 2), innerDurante: after.slice(0, 2)});
}
// ráfaga de resize: lo que manda la UI tras su debounce (un tamaño por gesto) y repeticiones del mismo tamaño
const r0 = (await look())[2];
for (const size of [[900, 700], [900, 700], [900, 700], [905, 700], [905, 700]]) await ask({action: 'viewport', tab, width: size[0], height: size[1], ...(fit ? {fit: true} : {})});
result.rafaga = {pedidos: 5, tamañosDistintos: 2, resizesEnLaPagina: (await look())[2] - r0};
if (fit) {
  await ask({action: 'unfit', tab});
  await sleep(200);
  result.alSoltar = {inner: (await look()).slice(0, 2), esperado: original.slice(0, 2)};
  await ask({action: 'viewport', tab, width: 800, height: 600, fit: true});
  result.caidaHost = {durante: (await look()).slice(0, 2)};
}
child.stdin.end();
await new Promise(r => child.once('exit', r));
await sleep(300);
result[fit ? 'caidaHost' : 'trasCerrarHost'] = {...(result.caidaHost ?? {}), despues: (await look()).slice(0, 2), esperado: original.slice(0, 2)};
probe.close();
chrome.kill();
await sleep(800);
try { rmSync(root, {recursive: true, force: true}); } catch { /* Chrome puede tardar en soltar el perfil */ }
const text = JSON.stringify(result, null, 2);
if (out) writeFileSync(out, text);
console.log(text);
const problemas = [];
if (fit) {
  for (const v of result.visores) {
    if (v.franjas.horizontalPx > 1 || v.franjas.verticalPx > 1) problemas.push(`franja en el visor ${v.visor.join('x')}`);
    if (v.jpegPxPorPxCss !== original[3]) problemas.push(`DPR ${v.jpegPxPorPxCss} distinto del real ${original[3]}`);
    if (v.resizesEnLaPagina > 1) problemas.push(`más de un resize por tamaño en ${v.visor.join('x')}`);
  }
  if (result.rafaga.resizesEnLaPagina > result.rafaga.tamañosDistintos) problemas.push('la ráfaga rehízo el layout con tamaños repetidos');
  if (result.alSoltar.inner.join('x') !== original.slice(0, 2).join('x')) problemas.push('unfit no devolvió el tamaño');
  if (result.caidaHost.despues.join('x') !== original.slice(0, 2).join('x')) problemas.push('la caída del host no devolvió el tamaño');
}
if (problemas.length) console.error(problemas.join('\n'));
process.exit(problemas.length ? 1 : 0);
