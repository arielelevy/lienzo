import { appendFileSync } from 'node:fs';
// Sólo lo carga el subproceso de browser_host.test.mjs mediante --import.
// No abre sockets, procesos Chrome, ventanas ni perfiles reales.
const scenario = process.env.TEST_BROWSER_HOST_SCENARIO;
if (!scenario) throw new Error('Falta TEST_BROWSER_HOST_SCENARIO para el fixture');
const realTimeout = globalThis.setTimeout;
// Reloj acelerado sólo para el plazo CDP de 8000 ms. No mide latencia real.
globalThis.setTimeout = (callback, delay, ...args) => realTimeout(callback, delay === 8000 ? 50 : delay, ...args);
let dropped = false;
let attached = 0;
let targetRequests = 0;
let layoutRequests = 0;
let frames = 0;
let worlds = 0;
let replaced = false;
let casts = 0;
let matches = 0;
const dropNth = Number(process.env.TEST_BROWSER_HOST_DROP_NTH || 1);
// el cuadro mide lo que la pestaña (en CSS); cast-stale-size simula uno de antes de un resize
const frameSize = () => {
  const [deviceWidth, deviceHeight] = (scenario === 'cast-stale-size' ? '900x600' : process.env.TEST_BROWSER_HOST_VIEW || '1280x800').split('x').map(Number);
  // cast-scroll: los primeros 4 cuadros con el scroll en movimiento; después la página queda quieta
  const scrollOffsetY = scenario === 'cast-scroll' ? Math.min(frames, 4) * 10 : 0;
  return {deviceWidth, deviceHeight, pageScaleFactor:1, scrollOffsetX:0, scrollOffsetY};
};
// cuadros del screencast: uno al arrancar; con cast-stream, otro tras cada acuse. Sin cuadros cuando el
// escenario prueba la captura a pedido (o la pestaña está oculta: Chrome no empuja)
const visibility = process.env.TEST_BROWSER_HOST_VISIBILITY || 'visible';
const pushes = !['Page.captureScreenshot', 'late-screenshot'].includes(scenario) && visibility === 'visible';
class FixtureSocket extends EventTarget {
  static OPEN = 1;
  static CLOSED = 3;
  readyState = 0;
  constructor() {
    super();
    realTimeout(() => { this.readyState = 1; this.dispatchEvent(new Event('open')); }, 0);
  }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
  send(line) {
    const command = JSON.parse(line);
    appendFileSync(process.env.TEST_BROWSER_HOST_TRACE, JSON.stringify({method:command.method,
      ...(['Input.dispatchMouseEvent', 'Input.dispatchKeyEvent', 'Page.captureScreenshot', 'Runtime.evaluate', 'Page.startScreencast', 'Emulation.setDeviceMetricsOverride'].includes(command.method) ? {params:command.params} : {}), ns:process.hrtime.bigint().toString()}) + '\n');
    process.stderr.write('CDP ' + command.method + '\n');
    const reply = result => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({id:command.id, result})}));
    // TEST_BROWSER_HOST_FAIL_RECAST: el segundo Page.startScreencast (el del cambio de modo) falla
    if (command.method === 'Page.startScreencast' && ++casts === 2 && process.env.TEST_BROWSER_HOST_FAIL_RECAST) {
      appendFileSync(process.env.TEST_BROWSER_HOST_TRACE, JSON.stringify({method:'fallo-recast'}) + '\n');
      return queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({id:command.id, error:{message:'fixture: no arrancó'}})})));
    }
    const frame = () => realTimeout(() => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({sessionId:command.sessionId,
      method:'Page.screencastFrame', params:{data:scenario === 'cast-stream' ? 'frame-' + ++frames : 'fixture-image', sessionId:++frames + 1000, metadata:frameSize()}})})), 5);
    const late = scenario === 'late-screenshot' && command.method === 'Page.captureScreenshot';
    if (command.method === 'Target.getTargets') targetRequests++;
    const eligible = command.method !== 'Target.getTargets' || targetRequests > 1;
    // TEST_BROWSER_HOST_DROP_NTH: vence la n-ésima llamada del método del escenario (por defecto la primera)
    if (command.method === scenario) matches++;
    if (!dropped && eligible && ((command.method === scenario && matches >= dropNth) || late)) {
      dropped = true;
      if (late) realTimeout(() => reply({data:'expired-image'}), 100);
      return;
    }
    let result = {};
    // replaced-tab: Chrome reemplaza la pestaña al engancharse (restaurada sin cargar): suelta la sesión sin contestar
    // Page.enable y la lista pasa a tener otro id con la misma dirección
    if (scenario === 'replaced-tab' && command.method === 'Page.enable' && !replaced) {
      replaced = true;
      realTimeout(() => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({method:'Target.detachedFromTarget', params:{sessionId:command.sessionId, targetId:'fixture-tab'}})})), 5);
      return;
    }
    if (command.method === 'Target.getTargets') result = {targetInfos:[{type:'page', targetId:replaced ? 'fixture-tab-2' : 'fixture-tab', title:'fixture', url:'about:blank', browserContextId:'fixture-context'}]};
    if (command.method === 'Target.attachToTarget') result = {sessionId:'session-' + ++attached};
    if (command.method === 'Page.captureScreenshot') result = {data:'fixture-image'};
    if (command.method === 'Page.getNavigationHistory') result = {currentIndex:0, entries:[{id:1}]};
    if (command.method === 'Page.getFrameTree') result = {frameTree:{frame:{id:'fixture-frame'}}};
    if (command.method === 'Page.createIsolatedWorld') result = {executionContextId:++worlds};
    // pestaña real de 1280x800 (TEST_BROWSER_HOST_VIEW la cambia): innerWidth/innerHeight y visibilidad
    if (command.method === 'Runtime.evaluate' && command.params.expression.includes('innerWidth')) {
      layoutRequests++;
      const view = scenario === 'resize-before-input' && layoutRequests > 1 ? '900x600' : process.env.TEST_BROWSER_HOST_VIEW || '1280x800';
      result = {result:{type:'object', value:[...view.split('x').map(Number), visibility]}};
    } else if (command.method === 'Runtime.evaluate' && command.params.expression === 'document.visibilityState') {
      result = {result:{type:'string', value:visibility}};
    }
    if (pushes && (command.method === 'Page.startScreencast' || (scenario === 'cast-stream' && command.method === 'Page.screencastFrameAck')
      || (scenario === 'cast-scroll' && command.method === 'Page.screencastFrameAck' && frames < 8))) frame();
    queueMicrotask(() => reply(result));
  }
}
globalThis.WebSocket = FixtureSocket;
