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
      ...(['Input.dispatchMouseEvent', 'Input.dispatchKeyEvent', 'Page.captureScreenshot'].includes(command.method) ? {params:command.params} : {}), ns:process.hrtime.bigint().toString()}) + '\n');
    process.stderr.write('CDP ' + command.method + '\n');
    const reply = result => this.dispatchEvent(new MessageEvent('message', {data:JSON.stringify({id:command.id, result})}));
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
    // pestaña real de 1280x800 scrolleada a 1600: el clip tiene que arrancar ahí (TEST_BROWSER_HOST_VIEW la cambia)
    if (command.method === 'Page.getLayoutMetrics') {
      layoutRequests++;
      const view = scenario === 'resize-before-input' && layoutRequests > 1 ? '900x600' : process.env.TEST_BROWSER_HOST_VIEW || '1280x800';
      const [w, h] = view.split('x').map(Number);
      result = {cssVisualViewport:{pageX:0, pageY:1600, clientWidth:w, clientHeight:h, scale:1}, visualViewport:{clientWidth:w, clientHeight:h}};
    }
    queueMicrotask(() => reply(result));
  }
}
globalThis.WebSocket = FixtureSocket;
