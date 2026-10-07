// Worker local: JSON por stdin/stdout. Chrome y CDP sólo escuchan en loopback.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { profiles, existingEndpoint } from './browser_profiles.mjs';

const profile = process.argv[2];
let chrome = null;
let endpoint = '';
let browser = null;
let connecting = false;
let connectionError = '';
let generation = 0;
let pendingSocket = null;
const pages = new Map();
const fail = (message, status = 400) => { throw Object.assign(new Error(message), { status }); };

function executable() {
  const paths = process.platform === 'win32'
    ? [process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA]
      .filter(Boolean).map(root => join(root, 'Google/Chrome/Application/chrome.exe'))
    : process.platform === 'darwin' ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
      : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'];
  const found = paths.find(existsSync);
  if (!found) fail('No se encontró Chrome instalado en esta PC', 503);
  return found;
}

class CDP {
  constructor(socket) {
    this.socket = socket;
    this.pending = new Map();
    this.id = 0;
    this.dialog = null;
    this.sessions = new Map();
    socket.addEventListener('message', e => {
      const msg = JSON.parse(e.data);
      const target = msg.sessionId ? this.sessions.get(msg.sessionId) : this;
      if (target && msg.method === 'Page.javascriptDialogOpening') target.dialog = msg.params;
      if (target && msg.method === 'Page.javascriptDialogClosed') target.dialog = null;
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) p.reject(Object.assign(new Error(msg.error.message), {status: 502}));
      else p.resolve(msg.result);
    });
    socket.addEventListener('close', () => this.rejectPending('Se cortó la conexión con Chrome'));
    socket.addEventListener('error', () => this.rejectPending('Falló la conexión con Chrome'));
  }

  rejectPending(message) {
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(Object.assign(new Error(message), {status: 502}));
    }
    this.pending.clear();
  }

  static async open(url, timeout = 5000, onSocket = () => {}) {
    const socket = new WebSocket(url);
    onSocket(socket);
    const cdp = new CDP(socket);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { socket.close(); reject(new Error('Chrome no autorizó la conexión a tiempo. Revisá el aviso en esa PC y volvé a conectar.')); }, timeout);
      socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, {once: true});
      socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('No se pudo conectar con Chrome')); }, {once: true});
      socket.addEventListener('close', () => { clearTimeout(timer); reject(new Error('Chrome cerró la solicitud de conexión')); }, {once: true});
    });
    return cdp;
  }

  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      if (this.socket.readyState !== WebSocket.OPEN) return reject(new Error('La pestaña está desconectada'));
      const id = ++this.id;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(Object.assign(new Error('Chrome tardó demasiado en responder'), {status: 504}));
      }, 8000);
      this.pending.set(id, {resolve, reject, timer});
      this.socket.send(JSON.stringify({id, method, params, sessionId}));
    });
  }
}

async function start() {
  if (browser || connecting) fail('Desconectá la sesión actual antes de abrir otra', 409);
  mkdirSync(profile, {recursive: true});
  const child = spawn(executable(), [
    '--headless', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1280,800', 'about:blank',
  ], {windowsHide: true, stdio: ['ignore', 'ignore', 'pipe']});
  chrome = child;
  child.once('exit', () => {
    if (chrome === child) { chrome = null; endpoint = ''; browser?.socket.close(); browser = null; pages.clear(); }
  });
  endpoint = await new Promise((resolve, reject) => {
    let tail = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('Chrome no arrancó en 10 segundos')); }, 10000);
    const failed = () => { clearTimeout(timer); reject(new Error('Chrome no pudo abrir su perfil. Revisá que no esté en uso')); };
    child.once('error', failed);
    child.once('exit', failed);
    child.stderr.on('data', chunk => {
      tail = (tail + chunk.toString()).slice(-8192);
      const match = tail.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[\w-]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  browser = await CDP.open(endpoint);
  await browser.send('Browser.setDownloadBehavior', {behavior: 'deny'});
}

async function tabs() {
  if (!browser) return [];
  const {targetInfos} = await browser.send('Target.getTargets');
  const list = targetInfos.filter(t => t.type === 'page').map(t => ({id: t.targetId, title: t.title, url: t.url}));
  for (const [id, cdp] of pages) {
    if (!list.some(t => t.id === id)) { browser.sessions.delete(cdp.sessionId); pages.delete(id); }
  }
  return list;
}

async function page(id) {
  if (typeof id !== 'string' || !(await tabs()).some(t => t.id === id)) fail('La pestaña ya no existe', 404);
  if (!pages.has(id)) {
    // Una sola conexión autorizada por Chrome; las páginas usan sesiones CDP.
    const root = browser;
    const {sessionId} = await root.send('Target.attachToTarget', {targetId: id, flatten: true});
    const cdp = {sessionId, dialog: null, send: (method, params) => root.send(method, params, sessionId)};
    root.sessions.set(sessionId, cdp);
    await cdp.send('Page.enable');
    pages.set(id, cdp);
  }
  return pages.get(id);
}

function url(value) {
  if (value === 'about:blank') return value;
  if (typeof value !== 'string' || value.length > 8192) fail('Dirección inválida');
  let parsed;
  try { parsed = new URL(value); } catch { fail('Escribí una dirección http o https'); }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) fail('Usá una dirección http o https sin credenciales');
  return parsed.href;
}

function integer(n, min, max) {
  if (!Number.isInteger(n) || n < min || n > max) fail('Valor fuera de rango');
  return n;
}

async function input(cdp, events) {
  if (!Array.isArray(events) || events.length > 64) fail('Demasiados eventos de entrada');
  for (const e of events) {
    if (e.kind === 'text') {
      if (typeof e.text !== 'string' || e.text.length > 16000) fail('Texto demasiado largo');
      await cdp.send('Input.insertText', {text: e.text});
    } else if (e.kind === 'key') {
      if (!['keyDown', 'keyUp'].includes(e.type) || typeof e.key !== 'string' || e.key.length > 40
          || typeof e.code !== 'string' || e.code.length > 40) fail('Tecla inválida');
      await cdp.send('Input.dispatchKeyEvent', {
        type: e.type, key: e.key, code: e.code,
        windowsVirtualKeyCode: integer(e.keyCode, 0, 255),
        modifiers: integer(e.modifiers, 0, 15),
        ...(e.type === 'keyDown' && !(e.modifiers & 7) && (e.key.length === 1 || e.key === 'Enter')
          ? {text: e.key === 'Enter' ? '\r' : e.key} : {}),
      });
    } else if (e.kind === 'mouse') {
      if (!['mousePressed', 'mouseReleased', 'mouseMoved', 'mouseWheel'].includes(e.type)
          || !['none', 'left', 'middle', 'right'].includes(e.button)) fail('Acción de mouse inválida');
      const params = {
        type: e.type, x: integer(e.x, 0, 1920), y: integer(e.y, 0, 1080),
        button: e.button, buttons: integer(e.buttons, 0, 7), modifiers: integer(e.modifiers, 0, 15),
        clickCount: integer(e.clickCount, 0, 3),
      };
      if (e.type === 'mouseWheel') {
        params.deltaX = integer(e.deltaX, -4000, 4000);
        params.deltaY = integer(e.deltaY, -4000, 4000);
      }
      await cdp.send('Input.dispatchMouseEvent', params);
    } else fail('Entrada desconocida');
  }
}

async function stop() {
  generation++;
  connecting = false;
  connectionError = '';
  pendingSocket?.close();
  pendingSocket = null;
  pages.clear();
  const child = chrome;
  if (browser) {
    // Browser.close puede cerrar el socket antes de contestar: la salida del proceso es la prueba.
    if (child) void browser.send('Browser.close').catch(e => process.stderr.write(`Chrome al cerrar: ${e.message}\n`));
    else browser.socket.close(); // El Chrome habitual pertenece al usuario, no a Lienzo.
    browser = null;
  }
  if (child && child.exitCode === null) {
    await new Promise(resolve => {
      const timer = setTimeout(() => { child.kill(); resolve(); }, 2000);
      child.once('exit', () => { clearTimeout(timer); resolve(); });
    });
  }
  chrome = null;
  endpoint = '';
}

async function prepareProfile(id) {
  if (!profiles().some(p => p.id === id)) fail('Elegí un perfil existente de esa PC');
  const child = spawn(executable(), [`--profile-directory=${id}`, '--new-window', 'chrome://inspect/#remote-debugging'],
    {detached: true, windowsHide: false, stdio: 'ignore'});
  await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
  child.unref();
  return {prepared: true};
}

function connectExisting() {
  if (browser || connecting) fail('Desconectá la sesión actual antes de conectar otra', 409);
  const address = existingEndpoint();
  const attempt = ++generation;
  connecting = true;
  connectionError = '';
  void CDP.open(address, 60000, socket => { pendingSocket = socket; }).then(cdp => {
    if (attempt !== generation) { cdp.socket.close(); return; }
    pendingSocket = null;
    browser = cdp;
    connecting = false;
    cdp.socket.addEventListener('close', () => {
      if (browser !== cdp) return;
      browser = null;
      pages.clear();
      connectionError = 'Chrome cerró la conexión. Volvé a conectar y aceptá su aviso.';
    });
  }).catch(e => {
    if (attempt !== generation) return;
    pendingSocket = null;
    connecting = false;
    connectionError = e.message;
  });
  return {connecting: true, running: false, mode: 'existing', tabs: []};
}

async function handle(d) {
  if (!d || typeof d !== 'object') fail('Pedido inválido');
  if (d.action === 'profiles') return {profiles: profiles()};
  if (d.action === 'prepare') return prepareProfile(d.profile);
  if (d.action === 'connect') return connectExisting();
  if (d.action === 'start') {
    if (browser || connecting) fail('Desconectá la sesión actual antes de abrir otra', 409);
    try { await start(); return {running: true, mode: 'lienzo', tabs: await tabs()}; }
    catch (e) { await stop(); throw e; }
  }
  if (d.action === 'state') return {running: !!browser, connecting, connectionError, mode: chrome ? 'lienzo' : 'existing', tabs: await tabs()};
  if (d.action === 'stop') { await stop(); return {running: false, connecting: false, tabs: []}; }
  if (!browser) fail('Chrome está desconectado. Conectalo nuevamente', 409);
  if (d.action === 'new') {
    if ((await tabs()).length >= 12) fail('Cerrá alguna pestaña antes de abrir otra (máximo 12)', 409);
    const {targetId} = await browser.send('Target.createTarget', {url: url(d.url)});
    return {id: targetId, running: true, tabs: await tabs()};
  }
  const cdp = await page(d.tab);
  if (d.action === 'frame') {
    const width = integer(d.width, 320, 1920), height = integer(d.height, 240, 1080);
    if (cdp.size !== `${width}x${height}`) {
      await cdp.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
      cdp.size = `${width}x${height}`;
    }
    if (cdp.dialog) return {running: true, tabs: await tabs(), dialog: cdp.dialog};
    const {data} = await cdp.send('Page.captureScreenshot', {format: 'jpeg', quality: 80, captureBeyondViewport: false});
    const history = await cdp.send('Page.getNavigationHistory');
    return {running: true, tabs: await tabs(), image: data, width, height,
      back: history.currentIndex > 0, forward: history.currentIndex < history.entries.length - 1, dialog: null};
  }
  if (d.action === 'navigate') {
    const result = await cdp.send('Page.navigate', {url: url(d.url)});
    if (result.errorText) fail(`No se pudo cargar la página: ${result.errorText}`, 502);
  } else if (d.action === 'reload') await cdp.send('Page.reload');
  else if (d.action === 'activate') await cdp.send('Page.bringToFront');
  else if (d.action === 'close') await browser.send('Target.closeTarget', {targetId: d.tab});
  else if (d.action === 'history') {
    if (![-1, 1].includes(d.direction)) fail('Dirección inválida');
    const h = await cdp.send('Page.getNavigationHistory');
    const entry = h.entries[h.currentIndex + d.direction];
    if (entry) await cdp.send('Page.navigateToHistoryEntry', {entryId: entry.id});
  } else if (d.action === 'input') await input(cdp, d.events);
  else if (d.action === 'copy') {
    const {result, exceptionDetails} = await cdp.send('Runtime.evaluate', {
      expression: `(() => { const e = document.activeElement; return (e instanceof HTMLInputElement || e instanceof HTMLTextAreaElement) && typeof e.selectionStart === 'number' ? e.value.slice(e.selectionStart, e.selectionEnd) : String(window.getSelection()); })()`,
      returnByValue: true,
    });
    if (exceptionDetails) fail('No se pudo leer la selección de la página', 502);
    return {text: String(result.value ?? '').slice(0, 16000)};
  }
  else if (d.action === 'dialog') {
    if (typeof d.accept !== 'boolean' || typeof d.text !== 'string' || d.text.length > 16000) fail('Respuesta inválida');
    await cdp.send('Page.handleJavaScriptDialog', {accept: d.accept, promptText: d.text});
  } else fail('Acción desconocida');
  return {ok: true};
}

const lines = createInterface({input: process.stdin, crlfDelay: Infinity});
let chain = Promise.resolve();
lines.on('line', line => {
  chain = chain.then(async () => {
    try { process.stdout.write(JSON.stringify(await handle(JSON.parse(line))) + '\n'); }
    catch (e) { process.stdout.write(JSON.stringify({status: e.status ?? 502, error: e.message}) + '\n'); }
  });
});
lines.on('close', () => { void stop().finally(() => process.exit(0)); });
process.on('SIGTERM', () => { void stop().finally(() => process.exit(0)); });
