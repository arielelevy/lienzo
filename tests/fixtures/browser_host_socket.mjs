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
// el cuadro mide lo que la pestaña (en CSS); cast-stale-size simula uno de antes de un resize
const frameSize = () => {
  const [deviceWidth, deviceHeight] = (scenario === 'cast-stale-size' ? '900x600' : process.env.TEST_BROWSER_HOST_VIEW || '1280x800').split('x').map(Number);
  return {deviceWidth, deviceHeight, pageScaleFactor:1};
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
      ...(['Input.dispatchMouseEvent', 'Input.dispatchKeyEvent', 'Page.captureScreenshot', 'Runtime.evaluate'].includes(command.method) ? {params:command.params} : {}), ns:process.hrtime.bigint().toString()}) + '\n');
    process.stderr.write('CDP ' + command.method + '\n');
    const reply = result => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({id:command.id, result})}));
    const frame = () => realTimeout(() => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({sessionId:command.sessionId,
      method:'Page.screencastFrame', params:{data:scenario === 'cast-stream' ? 'frame-' + ++frames : 'fixture-image', sessionId:++frames + 1000, metadata:frameSize()}})})), 5);
    const late = scenario === 'late-screenshot' && command.method === 'Page.captureScreenshot';
    if (command.method === 'Target.getTargets') targetRequests++;
    const eligible = command.method !== 'Target.getTargets' || targetRequests > 1;
    if (!dropped && eligible && (command.method === scenario || late)) {
      dropped = true;
      if (late) realTimeout(() => reply({data:'expired-image'}), 100);
      return;
    }
    let result = {};
    if (command.method === 'Target.getTargets') result = {targetInfos:[{type:'page', targetId:'fixture-tab', title:'fixture', url:'about:blank'}]};
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
    if (pushes && (command.method === 'Page.startScreencast' || (scenario === 'cast-stream' && command.method === 'Page.screencastFrameAck'))) frame();
    queueMicrotask(() => reply(result));
  }
}
globalThis.WebSocket = FixtureSocket;
