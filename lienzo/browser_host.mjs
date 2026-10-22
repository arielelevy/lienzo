// Worker local: JSON por stdin/stdout. Chrome y CDP sólo escuchan en loopback.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
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
let consentProcess = null;
let autoApproving = false;
let consentError = '';
const pages = new Map();
const attaching = new Map();
const fail = (message, status = 400) => { throw Object.assign(new Error(message), { status }); };
const REPLACED = 'Chrome soltó la pestaña (se cerró, se recargó o estaba sin cargar). Elegila de nuevo en la lista';

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
      if (target && msg.method === 'Page.screencastFrame') target.onFrame?.(msg.params);
      if (msg.method === 'Target.detachedFromTarget') this.detached(msg.params?.sessionId);
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

  // Chrome soltó una sesión de pestaña sin contestar (medido 2026-10-21 en el Chrome de Ariel: pestañas restauradas
  // sin cargar cambian de id al engancharse). Lo pendiente de esa sesión se corta ya, sin esperar los 8 s.
  detached(sessionId) {
    const cdp = this.sessions.get(sessionId);
    if (!cdp) return;
    this.sessions.delete(sessionId);
    cdp.gone = true;
    stopCast(cdp, false);
    if (pages.get(cdp.targetId) === cdp) pages.delete(cdp.targetId);
    for (const [id, p] of this.pending) {
      if (p.sessionId !== sessionId) continue;
      clearTimeout(p.timer);
      this.pending.delete(id);
      p.reject(Object.assign(new Error(REPLACED), {status: 409}));
    }
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
        reject(Object.assign(new Error(`Chrome tardó demasiado en responder (${method})`), {status: 504}));
      }, 8000);
      this.pending.set(id, {resolve, reject, timer, sessionId});
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
    if (chrome === child) { chrome = null; endpoint = ''; browser?.socket.close(); browser = null; dropPages(); }
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
  // context: cada perfil abierto es un contexto propio del mismo Chrome. CDP no dice cuál; el visor lo
  // une con el perfil que Windows marca en cada ventana (browser_window.Windows.windows)
  const list = targetInfos.filter(t => t.type === 'page').map(t => ({id: t.targetId, title: t.title, url: t.url,
    ...(typeof t.browserContextId === 'string' ? {context: t.browserContextId} : {})}));
  for (const [id, cdp] of pages) {
    if (!list.some(t => t.id === id)) browser.detached(cdp.sessionId); // corta lo pendiente con 409 y suelta el cast
  }
  return list;
}

async function page(id, cached = false) {
  if (cached && pages.has(id)) return pages.get(id);
  if (attaching.has(id)) return attaching.get(id);
  const pending = attachPage(id);
  attaching.set(id, pending);
  try { return await pending; } finally { attaching.delete(id); }
}

async function attachPage(id) {
  if (typeof id !== 'string' || !(await tabs()).some(t => t.id === id)) fail('La pestaña ya no existe', 404);
  if (!pages.has(id)) {
    // Una sola conexión autorizada por Chrome; las páginas usan sesiones CDP.
    const root = browser;
    const {sessionId} = await root.send('Target.attachToTarget', {targetId: id, flatten: true});
    // una sesión que Chrome ya soltó no recibe más comandos: se contesta lo mismo que a lo que estaba pendiente
    const cdp = {sessionId, targetId: id, dialog: null, gone: false,
      send: (method, params) => cdp.gone ? Promise.reject(Object.assign(new Error(REPLACED), {status: 409})) : root.send(method, params, sessionId)};
    root.sessions.set(sessionId, cdp);
    try {
      await cdp.send('Page.enable');
      // existing: la pestaña es del usuario; al adjuntarse se deshace lo que pudo dejar otra sesión o versión
      if (!chrome) await cdp.send('Emulation.clearDeviceMetricsOverride');
    }
    catch (e) {
      // sin pages.set: el próximo pedido adjunta de cero; la sesión fallida no queda colgada en Chrome
      root.sessions.delete(sessionId);
      if (!cdp.gone) void root.send('Target.detachFromTarget', {sessionId}).catch(d => process.stderr.write(`Chrome al soltar la pestaña: ${d.message}\n`));
      if (e.status === 504) e.message += '. Si la pestaña no está al frente en esa PC, elegila en la lista para traerla';
      throw e;
    }
    pages.set(id, cdp);
  }
  return pages.get(id);
}

const TIMING = process.env.LIENZO_BROWSER_TIMING === '1';
const traced = (cdp, source) => { if (TIMING) cdp.source = source; };

// Chrome habitual (existing): sólo se emula el tamaño con viewport fit (el dueño del stream de esa pestaña) y hasta
// el unfit; se lee el tamaño de la pestaña (el emulado, si lo hay) y se captura sin tocar scroll.
// innerWidth/innerHeight y no cssVisualViewport: el cuadro (screencast o captura sin clip) incluye la barra de
// scroll (medido 2026-10-21: 1479 px a DPR 1,5 = 986 CSS, con clientWidth 970,7). Se leen en un mundo aislado:
// un script de la página no puede falsear innerWidth ni visibilityState ahí.
const VIEW = '[innerWidth, innerHeight, document.visibilityState]';

async function isolated(cdp) {
  if (!cdp.world) {
    cdp.world = (async () => {
      const {frameTree} = await cdp.send('Page.getFrameTree');
      const {executionContextId} = await cdp.send('Page.createIsolatedWorld', {frameId: frameTree.frame.id, worldName: 'lienzo-vista'});
      return executionContextId;
    })();
    cdp.world.catch(() => { cdp.world = null; });
  }
  return cdp.world;
}

async function evaluate(cdp, expression) {
  for (let attempt = 0; ; attempt++) {
    const contextId = await isolated(cdp);
    try {
      return await cdp.send('Runtime.evaluate', {expression, returnByValue: true, contextId});
    } catch (e) {
      // una navegación destruye el mundo aislado: se crea otro y se repite la lectura (no tiene efectos)
      if (attempt > 0 || e.status === 504 || cdp.gone) throw e;
      cdp.world = null;
    }
  }
}

async function realViewport(cdp) {
  const {result, exceptionDetails} = await evaluate(cdp, VIEW);
  const [width, height, visibility] = Array.isArray(result?.value) ? result.value : [];
  if (exceptionDetails || !Number.isInteger(width) || !Number.isInteger(height)
      || !(width >= 1 && width <= 3840 && height >= 1 && height <= 2160)) fail('Chrome informó un tamaño de pestaña inválido', 502);
  cdp.css = {width, height};
  return {width, height, hidden: visibility === 'hidden'};
}

// Cuadros empujados (Page.startScreencast) a la resolución real del dispositivo. El acuse a Chrome se manda
// cuando el visor se lleva el cuadro: Chrome no codifica otro hasta entonces, así no gasta CPU sin nadie mirando.
// Con la pestaña oculta (ventana minimizada, o tapada sin las banderas anti-oclusión) Chrome deja de empujar:
// ahí se captura a pedido, que sí pinta (medido 2026-10-21: 51 ms minimizada, screencast 0,3 c/s).
// Tope 2560×1600 px: una pestaña 4K a DPR 2 pasaría los 4 MiB por cuadro del stream.
const CAST_WAIT = 500, CAST_IDLE = 4000, HIDDEN_MIN = 100, HIDDEN_MAX = 1000, MAX_PX = [2560, 1600];
// Scroll: mientras la posición cambia entre cuadros, los cuadros van a 1× CSS y calidad 80; a los SETTLE ms quieta
// vuelve a calidad 90 a DPR real y ese cuadro refina la imagen. Una animación sin scroll sigue siempre nítida.
// Medido 2026-10-21 (texto denso a DPR 1,5): 539 KB por cuadro a q90 DPR contra 193 KB a q80 1×; parar y volver a
// arrancar el screencast da el primer cuadro con los parámetros nuevos en ~25 ms (sin parar, Chrome los ignora).
const SETTLE = 300;
const castParams = (cdp, mode) => mode === 'scroll'
  ? {format: 'jpeg', quality: 80, maxWidth: Math.min(cdp.css?.width || MAX_PX[0], MAX_PX[0]),
    maxHeight: Math.min(cdp.css?.height || MAX_PX[1], MAX_PX[1]), everyNthFrame: 1}
  : {format: 'jpeg', quality: 90, maxWidth: MAX_PX[0], maxHeight: MAX_PX[1], everyNthFrame: 1};
// medido 2026-10-21 en el Chrome de Ariel: las pestañas de fondo también quedan hidden, con o sin la bandera
const HIDDEN = 'Chrome no está pintando esa pestaña (está de fondo en su ventana, la ventana está minimizada, o tapada sin la bandera anti-oclusión)';

function startCast(cdp) {
  const cast = {frame: null, last: null, waiters: new Set(), idle: null, failed: false, hiddenAt: 0, hiddenEvery: HIDDEN_MIN,
    mode: 'sharp', scroll: null, moves: 0, scrolledAt: 0};
  cdp.cast = cast;
  cdp.onFrame = params => {
    if (cdp.cast !== cast) return;
    // un cuadro 1× del screencast anterior que llega después de volver a nítido no se muestra como refinado
    const width = jpegWidth(params.data);
    if (cast.mode === 'sharp' && cast.sharpWidth && width && width < cast.sharpWidth) {
      void cdp.send('Page.screencastFrameAck', {sessionId: params.sessionId}).catch(() => {});
      return;
    }
    if (cast.mode === 'sharp' && width) cast.sharpWidth = Math.max(cast.sharpWidth || 0, width);
    cast.frame = params;
    const at = [params.metadata?.scrollOffsetX, params.metadata?.scrollOffsetY];
    const moved = cast.scroll && (at[0] !== cast.scroll[0] || at[1] !== cast.scroll[1]);
    cast.scroll = at;
    cast.moves = moved ? cast.moves + 1 : 0;
    if (moved) cast.scrolledAt = Date.now();
    // dos cuadros seguidos con el scroll en movimiento: no es un salto suelto (un clic en un ancla)
    if (cast.moves >= 2) recast(cdp, cast, 'scroll');
    for (const wake of cast.waiters) wake();
  };
  cdp.send('Page.startScreencast', castParams(cdp, cast.mode))
    .catch(e => { cast.failed = true; process.stderr.write(`Chrome screencast: ${e.message}\n`); });
  return cast;
}

function recast(cdp, cast, mode) {
  if (cast.mode === mode || cdp.cast !== cast) return;
  cast.mode = mode;
  cast.moves = 0;
  void cdp.send('Page.stopScreencast')
    .then(() => cdp.cast === cast && cast.mode === mode && cdp.send('Page.startScreencast', castParams(cdp, mode)))
    .catch(e => {
      // sin screencast no hay cuadros: se descarta y el próximo pedido lo arranca de cero (no queda congelado)
      process.stderr.write(`Chrome screencast (${mode}): ${e.message}\n`);
      if (cdp.cast === cast) stopCast(cdp, false);
    });
}

// ancho del JPEG en base64 leyendo sólo el encabezado (SOF), sin decodificar la imagen
function jpegWidth(b64) {
  const head = Buffer.from(b64.slice(0, 4096), 'base64');
  for (let i = 2; i + 9 < head.length;) {
    if (head[i] !== 0xff) return 0;
    const marker = head[i + 1], length = head.readUInt16BE(i + 2);
    if (marker >= 0xc0 && marker <= 0xc3) return head.readUInt16BE(i + 7);
    i += 2 + length;
  }
  return 0;
}

async function waitFrame(cast, ms) {
  let wake, timer;
  await new Promise(resolve => { wake = resolve; cast.waiters.add(wake); timer = setTimeout(resolve, ms); });
  clearTimeout(timer);
  cast.waiters.delete(wake);
}

// remote: false cuando el socket ya no sirve (stop, Chrome cerrado): sólo se sueltan timers y esperas
function stopCast(cdp, remote = true) {
  const cast = cdp.cast;
  if (!cast) return;
  clearTimeout(cast.idle);
  cdp.cast = null;
  for (const wake of cast.waiters) wake();
  if (remote) void cdp.send('Page.stopScreencast').catch(e => process.stderr.write(`Chrome al parar el screencast: ${e.message}\n`));
}

function dropPages() {
  for (const cdp of pages.values()) stopCast(cdp, false);
  pages.clear();
}

// el cuadro tiene que medir lo que se va a informar: uno de antes de un resize no se muestra con el tamaño nuevo
const sameSize = (size, width, height) => Math.abs(size.width - width) <= 1 && Math.abs(size.height - height) <= 1;

function takeFrame(cdp, cast, width, height) {
  const frame = cast.frame;
  cast.frame = null;
  void cdp.send('Page.screencastFrameAck', {sessionId: frame.sessionId}).catch(e => process.stderr.write(`Chrome acuse de cuadro: ${e.message}\n`));
  const size = {width: Math.round(frame.metadata?.deviceWidth), height: Math.round(frame.metadata?.deviceHeight)};
  if (!sameSize(size, width, height)) return null;
  cast.last = {data: frame.data, width, height};
  traced(cdp, {from: 'cast', ts: frame.metadata?.timestamp, mode: cast.mode});
  return frame.data;
}

async function capture(cdp, cast, width, height) {
  let {data} = await cdp.send('Page.captureScreenshot', {format: 'jpeg', quality: 90, captureBeyondViewport: false});
  // la captura a pedido no tiene tope de px: una pestaña enorme baja la calidad antes que pasar los 4 MiB
  if (data.length > 4 * 1024 * 1024) ({data} = await cdp.send('Page.captureScreenshot', {format: 'jpeg', quality: 50, captureBeyondViewport: false}));
  if (cdp.cast === cast) cast.last = {data, width, height};
  traced(cdp, {from: 'capture', ts: Date.now() / 1000});
  return data;
}

// Devuelve el JPEG en base64 de una pestaña de width×height CSS. hidden: no pinta sola y se captura a pedido.
async function castShot(cdp, hidden, width, height) {
  const cast = cdp.cast ?? startCast(cdp);
  clearTimeout(cast.idle);
  cast.idle = setTimeout(() => { if (cdp.cast === cast) stopCast(cdp); }, CAST_IDLE);
  if (!hidden && !cast.failed) {
    const quiet = () => Date.now() - cast.scrolledAt;
    // con scroll se espera sólo hasta que la página se queda quieta: ahí sale el cuadro nítido. Quieta = sin cuadro
    // pendiente y SETTLE ms desde el último movimiento (un cuadro pendiente con movimiento es scroll en curso)
    if (!cast.frame) await waitFrame(cast, cast.mode === 'scroll' ? Math.max(30, SETTLE - quiet()) : CAST_WAIT);
    if (!cast.frame && cdp.cast === cast && cast.mode === 'scroll' && quiet() >= SETTLE) {
      recast(cdp, cast, 'sharp');
      await waitFrame(cast, CAST_WAIT);
    }
  }
  if (cdp.cast === cast && cast.frame) {
    const data = takeFrame(cdp, cast, width, height);
    if (data) return data;
  }
  if (!hidden && !cast.failed) {
    // página quieta y visible: se repite el último del mismo tamaño (el stream no reenvía bytes iguales)
    if (cast.last && sameSize(cast.last, width, height)) { traced(cdp, {from: 'repeat'}); return cast.last.data; }
    return capture(cdp, cast, width, height);
  }
  // oculta: captura a pedido; si la imagen no cambia, cada vez más espaciada (hasta 1 s) para no gastar CPU de esa PC
  const pause = cast.hiddenEvery - (Date.now() - cast.hiddenAt);
  if (pause > 0) await new Promise(resolve => setTimeout(resolve, pause));
  const previous = cast.last?.data;
  const data = await capture(cdp, cast, width, height);
  cast.hiddenAt = Date.now();
  cast.hiddenEvery = data === previous ? Math.min(HIDDEN_MAX, cast.hiddenEvery * 2) : HIDDEN_MIN;
  return data;
}

// LIENZO_BROWSER_TIMING=1: la respuesta de snapshot/frame del host dice de dónde salió el cuadro y cuánto tardó cada
// paso (sólo para perfilar desde quien llama al host; el stream de pestañas no la reenvía).

async function realShot(cdp) {
  const t0 = performance.now();
  const view = await realViewport(cdp);
  const t1 = performance.now();
  const image = await castShot(cdp, view.hidden, view.width, view.height);
  const timing = TIMING ? {timing: {viewMs: +(t1 - t0).toFixed(2), shotMs: +(performance.now() - t1).toFixed(2), ...cdp.source, sentAt: Date.now() / 1000}} : {};
  return {image, width: view.width, height: view.height, hidden: view.hidden, ...timing};
}

// mouseMoved no se espera: con la pestaña oculta Chrome lo confirma recién a los 5 s (medido 2026-10-21, 12 de 12)
// y una ráfaga de hover llegaba al límite de 8 s. Uno solo en vuelo; mientras tanto gana el último, sin cola.
function moveLatest(cdp, params) {
  if (cdp.moving) { cdp.nextMove = params; return; }
  cdp.moving = true;
  const go = p => cdp.send('Input.dispatchMouseEvent', p)
    .catch(e => process.stderr.write(`Chrome move: ${e.message}\n`))
    .finally(() => {
      const next = cdp.nextMove;
      cdp.nextMove = null;
      if (next) go(next); else cdp.moving = false;
    });
  go(params);
}

// Antes de otra entrada sale el último move guardado, sin esperarlo: el clic o el fin de un arrastre llegan
// después de la última posición y no hace falta esperar su confirmación. La entrada vuelve a captura rápida.
function flushMove(cdp) {
  if (cdp.cast) cdp.cast.hiddenEvery = HIDDEN_MIN;
  const next = cdp.nextMove;
  if (!next) return;
  cdp.nextMove = null;
  void cdp.send('Input.dispatchMouseEvent', next).catch(e => process.stderr.write(`Chrome move: ${e.message}\n`));
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

async function input(cdp, events, releaseOnly = false) {
  if (!Array.isArray(events) || events.length > 64) fail('Demasiados eventos de entrada');
  const commands = [];
  for (const e of events) {
    if (releaseOnly && !((e.kind === 'key' && e.type === 'keyUp') || (e.kind === 'mouse' && e.type === 'mouseReleased'))) fail('La liberación sólo admite eventos up');
    if (e.kind === 'text') {
      if (typeof e.text !== 'string' || e.text.length > 16000) fail('Texto demasiado largo');
      commands.push(['Input.insertText', {text: e.text}]);
    } else if (e.kind === 'key') {
      if (!['keyDown', 'keyUp'].includes(e.type) || typeof e.key !== 'string' || e.key.length > 40
          || typeof e.code !== 'string' || e.code.length > 40) fail('Tecla inválida');
      commands.push(['Input.dispatchKeyEvent', {
        type: e.type, key: e.key, code: e.code,
        windowsVirtualKeyCode: integer(e.keyCode, 0, 255),
        modifiers: integer(e.modifiers, 0, 15),
        ...(e.type === 'keyDown' && !(e.modifiers & 7) && (e.key.length === 1 || e.key === 'Enter')
          ? {text: e.key === 'Enter' ? '\r' : e.key} : {}),
      }]);
    } else if (e.kind === 'mouse') {
      if (!['mousePressed', 'mouseReleased', 'mouseMoved', 'mouseWheel'].includes(e.type)
          || !['none', 'left', 'middle', 'right'].includes(e.button)) fail('Acción de mouse inválida');
      const params = {
        type: e.type, x: integer(e.x, 0, 3840), y: integer(e.y, 0, 2160),
        button: e.button, buttons: integer(e.buttons, 0, 7), modifiers: integer(e.modifiers, 0, 15),
        clickCount: releaseOnly ? 0 : ['mousePressed', 'mouseReleased'].includes(e.type) ? Math.max(1, integer(e.clickCount, 0, 3)) : integer(e.clickCount, 0, 3),
      };
      if (e.type === 'mouseWheel') {
        params.deltaX = integer(e.deltaX, -4000, 4000);
        params.deltaY = integer(e.deltaY, -4000, 4000);
      }
      commands.push(['Input.dispatchMouseEvent', params]);
    } else fail('Entrada desconocida');
  }
  // Validar TODO el lote antes del primer efecto; un 400 nunca significa ejecucion parcial.
  for (const [method, params] of commands) {
    if (method === 'Input.dispatchMouseEvent' && params.type === 'mouseMoved') moveLatest(cdp, params);
    else { flushMove(cdp); await cdp.send(method, params); }
  }
}

async function stop() {
  generation++;
  connecting = false;
  connectionError = '';
  consentError = '';
  autoApproving = false;
  consentProcess?.kill();
  consentProcess = null;
  pendingSocket?.close();
  pendingSocket = null;
  dropPages();
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

async function prepareProfile(id, setup = true) {
  if (!profiles().some(p => p.id === id)) fail('Elegí un perfil existente de esa PC');
  // Sin el cálculo de oclusión, Chrome sigue pintando la ventana tapada o con la PC bloqueada y la vista por
  // pestañas recibe cuadros (medido 2026-10-21: tapada 92 c/s en vez de 0,3). Sólo vale si este arranque abre
  // el proceso de Chrome; con Chrome ya abierto, Chrome la ignora y sólo abre la ventana.
  const child = spawn(executable(), [`--profile-directory=${id}`, '--disable-features=CalculateNativeWinOcclusion', '--new-window', setup ? 'chrome://inspect/#remote-debugging' : 'about:blank'],
    {detached: true, windowsHide: false, stdio: 'ignore'});
  await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
  child.unref();
  return {prepared: true};
}

function approveChrome(address, attempt) {
  if (process.platform !== 'win32') fail('El clic automático del aviso de Chrome requiere Windows', 409);
  if (!process.env.SystemRoot) fail('No se encontró SystemRoot para autorizar Chrome');
  const powershell = join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe');
  const child = spawn(powershell, ['-NoProfile', '-NonInteractive', '-File', fileURLToPath(new URL('./browser_consent.ps1', import.meta.url)), '-DebugPort', new URL(address).port],
    {windowsHide: true, stdio: ['ignore', 'ignore', 'pipe']});
  consentProcess = child;
  autoApproving = true;
  let detail = '';
  child.stderr.on('data', data => { detail = (detail + data.toString()).slice(-2000); });
  const failed = message => {
    if (attempt !== generation || !connecting) return;
    consentError = `El Lienzo de esta PC no pudo autorizar el aviso de Chrome: ${message}`;
    autoApproving = false;
    pendingSocket?.close();
  };
  child.once('error', e => failed(e.message));
  child.once('exit', code => {
    if (consentProcess === child) consentProcess = null;
    if (code !== 0) failed(detail.trim() || `el controlador terminó con código ${code}`);
  });
}

function connectExisting(autoApprove = false) {
  if (browser || connecting) fail('Desconectá la sesión actual antes de conectar otra', 409);
  if (autoApprove && process.platform !== 'win32') fail('El clic automático del aviso de Chrome requiere Windows', 409);
  const address = existingEndpoint();
  const attempt = ++generation;
  connecting = true;
  connectionError = '';
  consentError = '';
  void CDP.open(address, 60000, socket => { pendingSocket = socket; if (autoApprove) approveChrome(address, attempt); }).then(cdp => {
    if (attempt !== generation) { cdp.socket.close(); return; }
    pendingSocket = null;
    browser = cdp;
    connecting = false;
    autoApproving = false;
    consentProcess?.kill();
    consentProcess = null;
    cdp.socket.addEventListener('close', () => {
      if (browser !== cdp) return;
      browser = null;
      dropPages();
      connectionError = 'Chrome cerró la conexión. Volvé a conectar y aceptá su aviso.';
    });
  }).catch(e => {
    if (attempt !== generation) return;
    pendingSocket?.close();
    pendingSocket = null;
    connecting = false;
    autoApproving = false;
    consentProcess?.kill();
    consentProcess = null;
    connectionError = consentError || e.message;
  });
  return {connecting: true, autoApproving, running: false, mode: 'existing', tabs: []};
}

async function handle(d) {
  if (!d || typeof d !== 'object') fail('Pedido inválido');
  if (d.action === 'profiles') return {profiles: profiles()};
  if (d.action === 'prepare') {
    if (d.setup !== undefined && typeof d.setup !== 'boolean') fail('Modo de apertura inválido');
    return prepareProfile(d.profile, d.setup);
  }
  if (d.action === 'connect') {
    if (d.autoApprove !== undefined && typeof d.autoApprove !== 'boolean') fail('Autoaprobación inválida');
    return connectExisting(d.autoApprove);
  }
  if (d.action === 'start') {
    if (browser || connecting) fail('Desconectá la sesión actual antes de abrir otra', 409);
    try { await start(); return {running: true, mode: 'lienzo', tabs: await tabs()}; }
    catch (e) { await stop(); throw e; }
  }
  if (d.action === 'state') return {running: !!browser, connecting, autoApproving, connectionError, mode: chrome ? 'lienzo' : 'existing', tabs: await tabs()};
  if (d.action === 'stop') { await stop(); return {running: false, connecting: false, tabs: []}; }
  if (!browser) fail('Chrome está desconectado. Conectalo nuevamente', 409);
  if (d.action === 'new') {
    if ((await tabs()).length >= 12) fail('Cerrá alguna pestaña antes de abrir otra (máximo 12)', 409);
    const {targetId} = await browser.send('Target.createTarget', {url: url(d.url)});
    return {id: targetId, running: true, tabs: await tabs()};
  }
  if (d.action === 'activate') {
    // Sólo la elección explícita de pestaña la trae al frente (medido en ar-it33940, 2026-10-20: una
    // pestaña de fondo no da cuadros). Del navegador, sin adjuntarse: no espera un Page.enable que no
    // contesta. viewport, captura y reconexión nunca activan: competirían con quien usa esa PC.
    if (typeof d.tab !== 'string' || !(await tabs()).some(t => t.id === d.tab)) fail('La pestaña ya no existe', 404);
    await browser.send('Target.activateTarget', {targetId: d.tab});
    return {ok: true};
  }
  if (d.action === 'unfit') {
    // sólo una sesión ya adjunta pudo emular: soltar nunca adjunta ni activa. Una pestaña cerrada no tiene qué limpiar.
    const cdp = pages.get(d.tab);
    if (cdp?.fit) {
      // fit se borra recién con el clear confirmado: si falla, el próximo unfit lo vuelve a intentar
      await cdp.send('Emulation.clearDeviceMetricsOverride').catch(e => { if (!cdp.gone) throw e; });
      cdp.fit = null;
    }
    return {ok: true};
  }
  if (d.action === 'viewport') {
    integer(d.width, 320, 1920); integer(d.height, 240, 1080);
    if (d.fit !== undefined && typeof d.fit !== 'boolean') fail('Ajuste de tamaño inválido');
  }
  const cdp = await page(d.tab, ['snapshot', 'input', 'release-input', 'viewport', 'tab-state'].includes(d.action));
  const timedOut = e => {
    if (e.status === 504) e.message += '. Si la pestaña no está al frente en esa PC, elegila en la lista para traerla';
    throw e;
  };
  if (d.action === 'viewport') {
    const width = integer(d.width, 320, 1920), height = integer(d.height, 240, 1080);
    // existing: sin fit el tamaño del visor sólo escala la captura. Con fit (sólo el dueño del stream de esa pestaña)
    // la pestaña toma el tamaño CSS del visor a su DPR real (deviceScaleFactor 0) hasta el unfit; se manda sólo
    // cuando el tamaño cambia: repetir el mismo no vuelve a hacer layout en la ventana de esa PC.
    // Se informa siempre el tamaño leído de la pestaña, que es sobre el que se mapea la entrada.
    if (!chrome) {
      if (d.fit && cdp.fit !== `${width}x${height}`) {
        // marcado antes de mandarlo: un override vencido que Chrome aplica tarde igual se limpia con unfit
        cdp.fit = 'incierto';
        await cdp.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 0, mobile: false});
        cdp.fit = `${width}x${height}`;
      }
      return realViewport(cdp).then(v => ({width: v.width, height: v.height}));
    }
    // lienzo (headless propio): el override cambia la pestaña; se manda sólo cuando cambia el tamaño
    if (cdp.size !== `${width}x${height}`) {
      await cdp.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
      cdp.size = `${width}x${height}`;
    }
    cdp.css = {width, height};
    return {width, height};
  }
  if (d.action === 'frame' || d.action === 'snapshot') {
    const width = integer(d.width, 320, 1920), height = integer(d.height, 240, 1080);
    // Snapshot nunca modifica el viewport: open/viewport es la unica operacion que lo establece.
    if (d.action === 'snapshot') {
      if (cdp.dialog) return {dialog: cdp.dialog};
      if (!chrome) return await realShot(cdp).catch(timedOut);
      return {image: await castShot(cdp, false, width, height).catch(timedOut), width, height};
    }
    if (chrome && cdp.size !== `${width}x${height}`) {
      await cdp.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
      cdp.size = `${width}x${height}`;
      cdp.css = {width, height};
    }
    if (cdp.dialog) return {running: true, tabs: await tabs(), dialog: cdp.dialog};
    const shot = chrome
      ? {image: await castShot(cdp, false, width, height), width, height}
      : await realShot(cdp);
    const history = await cdp.send('Page.getNavigationHistory');
    return {running: true, tabs: await tabs(), ...shot,
      back: history.currentIndex > 0, forward: history.currentIndex < history.entries.length - 1, dialog: null};
  }
  if (d.action === 'tab-state') {
    const history = await cdp.send('Page.getNavigationHistory');
    // hidden: el visor lo avisa; los cuadros siguen por captura a pedido y la rueda no se manda
    const hidden = !chrome && !cdp.dialog && (await evaluate(cdp, 'document.visibilityState')).result?.value === 'hidden';
    return {running: true, tabs: await tabs(), back: history.currentIndex > 0,
      forward: history.currentIndex < history.entries.length - 1, dialog: cdp.dialog, hidden, ...(hidden ? {hiddenMessage: HIDDEN} : {})};
  }
  if (d.action === 'navigate') {
    const result = await cdp.send('Page.navigate', {url: url(d.url)});
    if (result.errorText) fail(`No se pudo cargar la página: ${result.errorText}`, 502);
  } else if (d.action === 'reload') await cdp.send('Page.reload');
  else if (d.action === 'close') await browser.send('Target.closeTarget', {targetId: d.tab});
  else if (d.action === 'history') {
    if (![-1, 1].includes(d.direction)) fail('Dirección inválida');
    const h = await cdp.send('Page.getNavigationHistory');
    const entry = h.entries[h.currentIndex + d.direction];
    if (entry) await cdp.send('Page.navigateToHistoryEntry', {entryId: entry.id});
  } else if (d.action === 'input') {
    // la entrada se mapeó sobre el tamaño de un cuadro: si la pestaña cambió desde entonces, no se manda
    let current = null;
    if (d.basis !== undefined) {
      // existing: el último cuadro no prueba que la ventana conserve su tamaño. Comparar con
      // esta lectura, no con la caché compartida que otro snapshot puede modificar mientras esperamos.
      current = chrome ? cdp.css : await realViewport(cdp);
      if (!d.basis || integer(d.basis.width, 1, 3840) !== current?.width || integer(d.basis.height, 1, 2160) !== current?.height)
        fail('La pestaña cambió de tamaño; la entrada no se envió', 409);
    }
    // con la pestaña oculta Chrome no confirma la rueda (medido: más de 9 s); mejor no mandarla que dejarla incierta
    if (!chrome && Array.isArray(d.events) && d.events.some(e => e?.kind === 'mouse' && e.type === 'mouseWheel')
        && (current ?? await realViewport(cdp)).hidden) fail(HIDDEN + '; la rueda no se envió', 409);
    await input(cdp, d.events);
  }
  else if (d.action === 'release-input') await input(cdp, d.events, true);
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
let lifecycle = Promise.resolve();
let active = new Set();
const inputs = new Map();
lines.on('line', line => {
  let request;
  try { request = JSON.parse(line); }
  catch (e) { process.stdout.write(JSON.stringify({status: 400, error: e.message}) + '\n'); return; }
  // El worker de ventana conserva su protocolo FIFO; HOST usa ids para concurrencia.
  const correlated = typeof request.requestId === 'number';
  const run = async () => {
    let result;
    try { result = await handle(request); }
    catch (e) { result = {status: e.status ?? 502, error: e.message}; }
    if (correlated) result.requestId = request.requestId;
    process.stdout.write(JSON.stringify(result) + '\n');
  };
  if (!correlated) { chain = chain.then(run); return; }
  if (['start', 'stop', 'connect', 'prepare'].includes(request.action)) {
    const previous = [...active];
    lifecycle = lifecycle.then(() => Promise.allSettled(previous)).then(run);
    return;
  }
  const barrier = lifecycle;
  const key = request.tab;
  const ordered = !['snapshot', 'frame', 'state', 'profiles', 'tab-state'].includes(request.action);
  const before = ordered ? inputs.get(key) ?? Promise.resolve() : Promise.resolve();
  const work = Promise.all([barrier, before]).then(run);
  active.add(work);
  if (ordered) inputs.set(key, work);
  void work.finally(() => { active.delete(work); if (inputs.get(key) === work) inputs.delete(key); });
});
lines.on('close', () => { void stop().finally(() => process.exit(0)); });
process.on('SIGTERM', () => { void stop().finally(() => process.exit(0)); });
