import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline';

const host = fileURLToPath(new URL('../lienzo/browser_host.mjs', import.meta.url));
const preload = fileURLToPath(new URL('./fixtures/browser_host_socket.mjs', import.meta.url));

test('IPC correlacionado: input termina mientras screenshot sigue pendiente, sin abrir otro socket', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Page.captureScreenshot');
  const snapshot = request({action:'snapshot', tab:'fixture-tab', width:800, height:600, requestId:101});
  const input = request({action:'input', tab:'fixture-tab', events:[{kind:'text',text:'hola'}], requestId:102});
  // El helper conserva orden de llegada para observar deliberadamente las respuestas fuera de orden.
  const [first, second] = await Promise.all([snapshot, input]);
  assert.equal(first.requestId, 102);
  assert.equal(first.ok, true);
  assert.equal(second.requestId, 101);
  assert.equal(second.status, 504);
  assert.equal(trace().filter(x=>x.method === 'Target.attachToTarget').length, 1);
});

test('snapshot caliente no consulta targets/historia ni cambia viewport', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:201});
  const start = trace().length;
  await request({action:'snapshot', tab:'fixture-tab', width:900, height:700, requestId:202});
  // existing: lee el tamaño real (solo lectura) y toma el cuadro empujado; nunca emula ni captura a pedido
  assert.deepEqual(trace().slice(start).map(x=>x.method), ['Runtime.evaluate', 'Page.startScreencast', 'Page.screencastFrameAck']);
});

test('lote inválido se rechaza antes de enviar el primer evento', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const result = await request({action:'input', tab:'fixture-tab', requestId:301,
    events:[{kind:'text',text:'no debe enviarse'}, {kind:'mouse',type:'invalido'}]});
  assert.equal(result.status, 400);
  assert.equal(trace().some(x=>x.method.startsWith('Input.')), false);
});

test('release-input sólo admite ups y conserva clickCount cero de cancelación', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const event = {kind:'mouse',type:'mouseReleased',button:'left',buttons:0,x:300,y:300,modifiers:0,clickCount:0};
  assert.equal((await request({action:'release-input',tab:'fixture-tab',requestId:401,events:[event]})).ok, true);
  assert.equal(trace().find(x=>x.method === 'Input.dispatchMouseEvent').params.clickCount, 0);
  const before = trace().length;
  assert.equal((await request({action:'release-input',tab:'fixture-tab',requestId:402,events:[{...event,type:'mousePressed'}]})).status,400);
  assert.equal(trace().length, before);
});

test('viewport inválido se rechaza sin activar ni adjuntar la pestaña', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  const result = await request({action:'viewport', tab:'fixture-tab', width:5000, height:600, requestId:501});
  assert.equal(result.status, 400);
  assert.deepEqual(trace().slice(start).map(x=>x.method), []);
});

test('sólo activate trae la pestaña al frente, sin adjuntarse', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  assert.equal((await request({action:'activate', tab:'fixture-tab', requestId:601})).ok, true);
  assert.deepEqual(trace().slice(start).map(x=>x.method), ['Target.getTargets', 'Target.activateTarget']);
});

test('existing: viewport, captura y reaperturas nunca activan ni emulan el tamaño', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  // dos visores, refresco de captura y reconexión: todos reabren con viewport
  await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:611});
  await request({action:'snapshot', tab:'fixture-tab', width:800, height:600, requestId:612});
  await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:613});
  await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:614});
  const methods = trace().slice(start).map(x=>x.method);
  assert.equal(methods.filter(m => m === 'Target.activateTarget').length, 0, methods.join(','));
  assert.equal(methods.filter(m => m === 'Emulation.setDeviceMetricsOverride').length, 0, methods.join(','));
  await request({action:'viewport', tab:'fixture-tab', width:900, height:600, requestId:615});
  assert.equal(trace().slice(start).filter(x => x.method === 'Emulation.setDeviceMetricsOverride').length, 0);
});

test('captura vencida de una pestaña de fondo se informa con cómo traerla, sin activarla', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Page.captureScreenshot');
  await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:621});
  const failed = await request({action:'snapshot', tab:'fixture-tab', width:800, height:600, requestId:622});
  assert.equal(failed.status, 504);
  assert.match(failed.error, /captureScreenshot.*elegila en la lista/);
  assert.equal(trace().filter(x => x.method === 'Target.activateTarget').length, 0);
});

test('Page.enable vencido suelta la sesión y el próximo pedido adjunta de cero', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Page.enable');
  const failed = await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:701});
  assert.equal(failed.status, 504);
  assert.match(failed.error, /Page\.enable/);
  assert.equal(trace().filter(x=>x.method === 'Target.detachFromTarget').length, 1);
  assert.equal(trace().filter(x=>x.method === 'Emulation.clearDeviceMetricsOverride').length, 0); // la sesión fallida no llegó a limpiar
  assert.equal((await request({action:'viewport', tab:'fixture-tab', width:800, height:600, requestId:702})).width, 1280);
  assert.equal(trace().filter(x=>x.method === 'Target.attachToTarget').length, 2);
  assert.equal(trace().filter(x=>x.method === 'Emulation.clearDeviceMetricsOverride').length, 1); // la sesión nueva limpia una vez
});

test('pestaña reemplazada por Chrome al engancharse: corta enseguida con 409 y la nueva se engancha de cero', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'replaced-tab');
  const failed = await request({action:'viewport', tab:'fixture-tab', width:800, height:600});
  assert.equal(failed.status, 409);
  assert.match(failed.error, /soltó la pestaña/);
  assert.equal(trace().filter(x => x.method === 'Target.detachFromTarget').length, 0); // Chrome ya la soltó
  // el timeout de 8 s del fixture vale 50 ms: el corte tiene que venir del detach, no de la espera
  assert.equal((await request({action:'viewport', tab:'fixture-tab', width:800, height:600})).status, 404);
  const ok = await request({action:'viewport', tab:'fixture-tab-2', width:800, height:600});
  assert.deepEqual([ok.width, ok.height], [1280, 800]);
  assert.equal(trace().filter(x => x.method === 'Target.attachToTarget').length, 2);
});

test('existing: si Chrome no vuelve a arrancar el screencast al cambiar de modo, se rearranca en vez de congelar la vista', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'cast-scroll', '1280x800', 'visible', {TEST_BROWSER_HOST_FAIL_RECAST:'1'});
  for (let i = 0; i < 4; i++) await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.ok(trace().some(x => x.method === 'fallo-recast'));
  const shot = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  assert.equal(shot.image, 'fixture-image');
  assert.equal(trace().filter(x => x.method === 'Page.startScreencast').length, 3); // el que falló y uno nuevo
});

async function worker(t, scenario, view = '1280x800', visibility = 'visible', env = {}) {
  const folder = mkdtempSync(join(tmpdir(), 'lienzo-host-fixture-'));
  const data = process.platform === 'win32' ? join(folder, 'Google/Chrome/User Data')
    : process.platform === 'darwin' ? join(folder, 'Library/Application Support/Google/Chrome')
      : join(folder, '.config/google-chrome');
  mkdirSync(data, {recursive:true});
  writeFileSync(join(data, 'DevToolsActivePort'), '9222\n/devtools/browser/fixture\n');
  const traceFile = join(folder, 'cdp.jsonl');
  const child = spawn(process.execPath, ['--import', pathToFileURL(preload).href, host, join(folder, 'profile')], {
    env: {...process.env, LOCALAPPDATA:folder, HOME:folder, USERPROFILE:folder, TEST_BROWSER_HOST_SCENARIO:scenario, TEST_BROWSER_HOST_TRACE:traceFile, TEST_BROWSER_HOST_VIEW:view, TEST_BROWSER_HOST_VISIBILITY:visibility, ...env},
    windowsHide:true, stdio:['pipe', 'pipe', 'pipe'],
  });
  const queued = [], waiting = [], methods = [];
  let stderr = '';
  const exited = new Promise(resolve => { child.once('exit', resolve); child.once('error', resolve); });
  const lines = createInterface({input:child.stdout});
  lines.on('line', line => {
    const result = JSON.parse(line);
    if (waiting.length) waiting.shift().resolve(result); else queued.push(result);
  });
  const errors = createInterface({input:child.stderr});
  errors.on('line', line => {
    stderr += line + '\n';
    if (line.startsWith('CDP ')) methods.push(line.slice(4));
  });
  let failure;
  const rejectWaiting = error => {
    failure = error;
    while (waiting.length) waiting.shift().reject(error);
  };
  child.once('error', rejectWaiting);
  child.stdin.on('error', rejectWaiting);
  child.once('exit', code => rejectWaiting(new Error(`Worker terminó con ${code}: ${stderr}`)));
  t.after(async () => {
    child.stdin.end();
    const kill = setTimeout(() => child.kill(), 2000);
    await exited;
    clearTimeout(kill);
    lines.close();
    errors.close();
    const resolved = realpathSync(folder);
    assert.equal(dirname(resolved), realpathSync(tmpdir()), 'La limpieza debe permanecer en TEMP');
    assert.ok(basename(resolved).startsWith('lienzo-host-fixture-'));
    rmSync(resolved, {recursive:true, force:true});
  });
  const request = async data => {
    if (failure) throw failure;
    child.stdin.write(JSON.stringify(data) + '\n');
    const result = queued.length ? queued.shift() : await new Promise((resolve, reject) => waiting.push({resolve, reject}));
    return result;
  };
  assert.equal((await request({action:'connect'})).connecting, true);
  // La apertura simulada llega por evento, igual que el WebSocket del worker real.
  let state;
  for (let attempt = 0; attempt < 20; attempt++) {
    state = await request({action:'state'});
    if (state.running) break;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.equal(state.running, true, stderr);
  const trace = () => readFileSync(traceFile, 'utf8').trim().split('\n').map(line => JSON.parse(line));
  return {request, methods, child, trace};
}

for (const method of ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.clearDeviceMetricsOverride', 'Runtime.evaluate', 'Page.captureScreenshot', 'Page.getNavigationHistory']) {
  test(`frame: vence ${method}; state y el siguiente frame siguen usables`, {timeout:15000}, async t => {
    const {request, methods} = await worker(t, method);
    const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
    const failed = await request(frame);
    assert.equal(failed.status, 504);
    // Page.enable vencido suele ser una pestaña de fondo: el mensaje agrega cómo traerla al frente
    const hint = ['Page.enable', 'Emulation.clearDeviceMetricsOverride'].includes(method) ? '. Si la pestaña no está al frente en esa PC, elegila en la lista para traerla' : '';
    assert.equal(failed.error, `Chrome tardó demasiado en responder (${method})${hint}`);
    const stateAfter = await request({action:'state'});
    assert.equal(stateAfter.status, undefined);
    assert.equal(stateAfter.running, true);
    const recovered = await request(frame);
    assert.equal(recovered.status, undefined);
    assert.equal(recovered.image, 'fixture-image');
    assert.equal(recovered.running, true);
    assert.ok(methods.includes(method));
    t.diagnostic(JSON.stringify({method, failed, stateAfter:200, frameAfter:200}));
  });
}

test('una respuesta tardía del screenshot vencido no contamina state ni el siguiente frame', {timeout:15000}, async t => {
  const {request} = await worker(t, 'late-screenshot');
  const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
  assert.equal((await request(frame)).status, 504);
  await new Promise(resolve => setTimeout(resolve, 150));
  const state = await request({action:'state'});
  assert.equal(state.running, true);
  assert.equal(state.tabs[0].id, 'fixture-tab');
  assert.equal((await request(frame)).image, 'fixture-image');
});

test('timeout de entrada informa sólo el método, sin texto privado ni URL de navegación', {timeout:15000}, async t => {
  const {request} = await worker(t, 'Input.insertText');
  const secret = 'texto-privado-que-no-debe-aparecer https://private.invalid/secret';
  const result = await request({action:'input', tab:'fixture-tab', events:[{kind:'text', text:secret}]});
  assert.deepEqual(result, {status:504, error:'Chrome tardó demasiado en responder (Input.insertText)'});
  assert.ok(!JSON.stringify(result).includes(secret));
});

test('frame frío arranca el screencast; frame caliente no captura a pedido ni toca foco Win32', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'healthy');
  const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
  const before = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const cold = trace().slice(before);
  assert.deepEqual(cold.map(item => item.method), ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.clearDeviceMetricsOverride', 'Page.getFrameTree', 'Page.createIsolatedWorld', 'Runtime.evaluate', 'Page.startScreencast', 'Page.screencastFrameAck', 'Page.getNavigationHistory', 'Target.getTargets']);
  const next = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const warm = trace().slice(next);
  // página quieta: sin cuadro nuevo se repite el último (el stream no reenvía bytes iguales)
  assert.deepEqual(warm.map(item => item.method), ['Target.getTargets', 'Runtime.evaluate', 'Page.getNavigationHistory', 'Target.getTargets']);
  t.diagnostic(JSON.stringify({cold:cold.map(item => item.method), warm:warm.map(item => item.method), timing:'fixture; no es medición de Chrome remoto'}));
});

// Contrato (2026-10-20, parpadeo en ar-it33940 con 0.5.5): en modo existing la pestaña real nunca se emula;
// se captura a su tamaño real desde el scroll actual, y la entrada lleva el tamaño sobre el que se mapeó.
test('existing: dos visores con tamaños distintos y frame HTTP no alternan el tamaño de la pestaña real', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  await request({action:'viewport', tab:'fixture-tab', width:1280, height:800, requestId:801}); // visor A
  await request({action:'frame', tab:'fixture-tab', width:900, height:600, requestId:802});     // visor B por HTTP
  await request({action:'snapshot', tab:'fixture-tab', width:1280, height:800, requestId:803});
  await request({action:'frame', tab:'fixture-tab', width:900, height:600, requestId:804});
  await request({action:'viewport', tab:'fixture-tab', width:1280, height:800, requestId:805});
  const overrides = trace().slice(start).filter(x => x.method === 'Emulation.setDeviceMetricsOverride').length;
  t.diagnostic(`overrides en la pestaña real: ${overrides}`);
  assert.equal(overrides, 0);
});

// Pedido de Ariel (2026-10-22, franjas negras): el dueño del stream de una pestaña la ajusta al tamaño CSS de su visor
// a DPR real mientras la mira, un solo override por tamaño nuevo, y al soltarla la pestaña vuelve a su tamaño.
test('existing: fit ajusta la pestaña al visor una vez por tamaño y unfit la devuelve', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  const methods = () => trace().slice(start).map(x => x.method);
  await request({action:'viewport', tab:'fixture-tab', width:700, height:1000, fit:true, requestId:851});
  await request({action:'viewport', tab:'fixture-tab', width:700, height:1000, fit:true, requestId:852});
  await request({action:'snapshot', tab:'fixture-tab', width:700, height:1000, requestId:853});
  await request({action:'frame', tab:'fixture-tab', width:900, height:600, requestId:854}); // otro visor por HTTP
  await request({action:'viewport', tab:'fixture-tab', width:900, height:600, requestId:855}); // sin fit: sólo lee
  const overrides = trace().slice(start).filter(x => x.method === 'Emulation.setDeviceMetricsOverride');
  assert.deepEqual(overrides.map(x => x.params), [{width:700, height:1000, deviceScaleFactor:0, mobile:false}], methods().join(','));
  await request({action:'viewport', tab:'fixture-tab', width:1400, height:520, fit:true, requestId:856});
  assert.equal(trace().slice(start).filter(x => x.method === 'Emulation.setDeviceMetricsOverride').length, 2);
  // el único clear previo es el de adjuntarse (deshace lo que pudo dejar otra versión)
  const clears = () => methods().filter(m => m === 'Emulation.clearDeviceMetricsOverride').length - 1;
  assert.equal(clears(), 0);
  assert.deepEqual(await request({action:'unfit', tab:'fixture-tab', requestId:857}), {ok:true, requestId:857});
  assert.equal(clears(), 1);
  await request({action:'unfit', tab:'fixture-tab', requestId:858}); // ya suelta: no vuelve a tocar la pestaña
  assert.equal(clears(), 1);
  // tras soltarla, el mismo tamaño vuelve a emularse
  await request({action:'viewport', tab:'fixture-tab', width:1400, height:520, fit:true, requestId:859});
  assert.equal(trace().slice(start).filter(x => x.method === 'Emulation.setDeviceMetricsOverride').length, 3);
  assert.equal(methods().filter(m => m === 'Target.activateTarget').length, 0);
});

test('existing: un unfit que vence sigue pendiente y el próximo unfit vuelve a limpiar', {timeout:15000}, async t => {
  // el primer clear es el de adjuntarse; vence el segundo, el del unfit
  const {request, trace} = await worker(t, 'Emulation.clearDeviceMetricsOverride', '1280x800', 'visible', {TEST_BROWSER_HOST_DROP_NTH:'2'});
  await request({action:'viewport', tab:'fixture-tab', width:700, height:1000, fit:true, requestId:871});
  const start = trace().length;
  assert.equal((await request({action:'unfit', tab:'fixture-tab', requestId:872})).status, 504);
  assert.equal((await request({action:'unfit', tab:'fixture-tab', requestId:873})).ok, true);
  assert.equal(trace().slice(start).filter(x => x.method === 'Emulation.clearDeviceMetricsOverride').length, 2);
});

test('existing: un fit que vence igual se limpia con unfit (Chrome pudo aplicarlo tarde)', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Emulation.setDeviceMetricsOverride');
  assert.equal((await request({action:'viewport', tab:'fixture-tab', width:700, height:1000, fit:true, requestId:881})).status, 504);
  const start = trace().length;
  assert.equal((await request({action:'unfit', tab:'fixture-tab', requestId:882})).ok, true);
  assert.deepEqual(trace().slice(start).map(x => x.method), ['Emulation.clearDeviceMetricsOverride']);
});

test('existing: unfit de una pestaña no adjunta no la adjunta ni la activa; fit inválido se rechaza', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const start = trace().length;
  assert.equal((await request({action:'unfit', tab:'fixture-tab', requestId:861})).ok, true);
  assert.deepEqual(trace().slice(start).map(x => x.method), []);
  const bad = await request({action:'viewport', tab:'fixture-tab', width:800, height:600, fit:'si', requestId:862});
  assert.equal(bad.status, 400);
  assert.deepEqual(trace().slice(start).map(x => x.method), []);
});

test('existing: cuadros empujados a resolución real, sin clip, sin emular y con acuse al llevarlos', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'cast-stream');
  const first = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600, requestId:901});
  assert.deepEqual([first.width, first.height, first.image], [1280, 800, 'frame-1']); // tamaño CSS real, no el del visor
  const second = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600, requestId:902});
  assert.equal(second.image, 'frame-3'); // el siguiente cuadro llega después del acuse del anterior
  const methods = trace().map(x => x.method);
  assert.equal(methods.filter(m => m === 'Page.startScreencast').length, 1);
  assert.equal(methods.filter(m => m === 'Page.screencastFrameAck').length, 2);
  assert.equal(methods.filter(m => ['Page.captureScreenshot', 'Emulation.setDeviceMetricsOverride', 'Page.getLayoutMetrics'].includes(m)).length, 0);
});

test('existing: un cuadro de antes de un resize no sale con el tamaño nuevo: se captura a pedido', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'cast-stale-size');
  const shot = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  assert.deepEqual([shot.width, shot.height, shot.image], [1280, 800, 'fixture-image']);
  const methods = trace().map(x => x.method);
  assert.ok(methods.indexOf('Page.screencastFrameAck') < methods.indexOf('Page.captureScreenshot'), methods.join(','));
});

test('existing: con scroll los cuadros bajan a 1× CSS y calidad 80; quieta, vuelven a calidad 90 a DPR', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'cast-scroll');
  const shot = () => request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  for (let i = 0; i < 6; i++) assert.ok((await shot()).image);
  const casts = () => trace().filter(x => x.method === 'Page.startScreencast').map(x => [x.params.quality, x.params.maxWidth, x.params.maxHeight]);
  assert.deepEqual(casts().slice(0, 2), [[90, 2560, 1600], [80, 1280, 800]]);
  assert.ok(trace().some(x => x.method === 'Page.stopScreencast'));
  // el scroll paró: en menos de un segundo vuelve el screencast nítido y su cuadro refina la imagen
  const t0 = Date.now();
  while (casts().length < 3 && Date.now() - t0 < 2000) await shot();
  assert.deepEqual(casts()[2], [90, 2560, 1600]);
  assert.ok(Date.now() - t0 < 1200, String(Date.now() - t0));
});

test('existing: sin nadie mirando se para el screencast', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  await new Promise(resolve => setTimeout(resolve, 4300));
  assert.equal(trace().filter(x => x.method === 'Page.stopScreencast').length, 1);
  assert.equal((await request({action:'snapshot', tab:'fixture-tab', width:900, height:600})).image, 'fixture-image');
  assert.equal(trace().filter(x => x.method === 'Page.startScreencast').length, 2);
});

test('existing: pestaña oculta se captura a pedido sin clip, la rueda no se manda y tab-state lo avisa', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none', '1280x800', 'hidden');
  const t0 = Date.now();
  const shot = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  assert.ok(Date.now() - t0 < 400, 'oculta no espera un cuadro que Chrome no va a empujar');
  assert.deepEqual([shot.width, shot.height, shot.image, shot.hidden], [1280, 800, 'fixture-image', true]);
  const capture = trace().filter(x => x.method === 'Page.captureScreenshot').at(-1).params;
  assert.deepEqual(capture, {format:'jpeg', quality:90, captureBeyondViewport:false});
  const before = trace().length;
  const wheel = {kind:'mouse', type:'mouseWheel', button:'none', buttons:0, x:10, y:10, modifiers:0, clickCount:0, deltaX:0, deltaY:100};
  const rejected = await request({action:'input', tab:'fixture-tab', basis:{width:1280, height:800}, events:[wheel]});
  assert.equal(rejected.status, 409);
  assert.match(rejected.error, /no está pintando.*la rueda no se envió/);
  assert.equal(trace().slice(before).some(x => x.method.startsWith('Input.')), false);
  const click = {kind:'mouse', type:'mousePressed', button:'left', buttons:1, x:10, y:10, modifiers:0, clickCount:1};
  assert.equal((await request({action:'input', tab:'fixture-tab', basis:{width:1280, height:800}, events:[click]})).ok, true);
  const state = await request({action:'tab-state', tab:'fixture-tab'});
  assert.equal(state.hidden, true);
  assert.match(state.hiddenMessage, /minimizada/);
});

test('existing: oculta y sin cambios, la captura a pedido se espacia hasta 1 s; una entrada la vuelve a acelerar', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none', '1280x800', 'hidden');
  const shot = () => request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  await shot();
  const t0 = Date.now();
  for (let i = 0; i < 4; i++) await shot(); // misma imagen: esperas de 100, 200, 400 y 800 ms
  assert.ok(Date.now() - t0 >= 1450, String(Date.now() - t0));
  const click = {kind:'mouse', type:'mousePressed', button:'left', buttons:1, x:10, y:10, modifiers:0, clickCount:1};
  await request({action:'input', tab:'fixture-tab', events:[click]});
  const t1 = Date.now();
  await shot();
  assert.ok(Date.now() - t1 < 400, String(Date.now() - t1));
  assert.equal(trace().filter(x => x.method === 'Page.captureScreenshot').length, 6);
});

test('mouseMoved no espera confirmación: el clic sale enseguida, detrás del último move guardado', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Input.dispatchMouseEvent');
  const move = x => ({kind:'mouse', type:'mouseMoved', button:'none', buttons:0, x, y:10, modifiers:0, clickCount:0});
  const click = {kind:'mouse', type:'mousePressed', button:'left', buttons:1, x:50, y:10, modifiers:0, clickCount:1};
  // el primer move nunca se confirma (pestaña oculta): el lote igual termina y el clic no queda detrás
  const result = await request({action:'input', tab:'fixture-tab', events:[move(1), move(2), move(3), click]});
  assert.equal(result.ok, true);
  await new Promise(resolve => setTimeout(resolve, 120)); // vence el move colgado
  const sent = trace().filter(x => x.method === 'Input.dispatchMouseEvent').map(x => `${x.params.type}@${x.params.x}`);
  // el 2 se reemplazó por el 3, que sale antes del clic sin esperar al 1 colgado
  assert.deepEqual(sent, ['mouseMoved@1', 'mouseMoved@3', 'mousePressed@50']);
});

test('mouseMoved: con uno en vuelo gana el último, sin cola', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'Input.dispatchMouseEvent');
  const move = x => ({kind:'mouse', type:'mouseMoved', button:'none', buttons:0, x, y:10, modifiers:0, clickCount:0});
  for (const x of [1, 2, 3, 4]) assert.equal((await request({action:'input', tab:'fixture-tab', events:[move(x)]})).ok, true);
  await new Promise(resolve => setTimeout(resolve, 120));
  const sent = trace().filter(x => x.method === 'Input.dispatchMouseEvent').map(x => x.params.x);
  assert.deepEqual(sent, [1, 4]);
});
test('existing: una pestaña 4K se informa a su tamaño y acepta coordenadas hasta 3840x2160', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none', '3840x2160');
  assert.deepEqual(await request({action:'viewport', tab:'fixture-tab', width:1280, height:800, requestId:911}), {width:3840, height:2160, requestId:911});
  const move = {kind:'mouse', type:'mouseMoved', button:'none', buttons:0, x:3839, y:2159, modifiers:0, clickCount:0};
  assert.equal((await request({action:'input', tab:'fixture-tab', basis:{width:3840, height:2160}, events:[move], requestId:912})).ok, true);
  assert.deepEqual(trace().filter(x => x.method === 'Input.dispatchMouseEvent').map(x => [x.params.x, x.params.y]), [[3839, 2159]]);
});

test('existing: entrada mapeada sobre un tamaño viejo se rechaza sin enviar nada', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  await request({action:'viewport', tab:'fixture-tab', width:900, height:600, requestId:921});
  const before = trace().length;
  const move = {kind:'mouse', type:'mouseMoved', button:'none', buttons:0, x:10, y:10, modifiers:0, clickCount:0};
  const stale = await request({action:'input', tab:'fixture-tab', basis:{width:1000, height:800}, events:[move], requestId:922});
  assert.equal(stale.status, 409);
  assert.match(stale.error, /cambió de tamaño/);
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Runtime.evaluate']);
  assert.equal((await request({action:'input', tab:'fixture-tab', basis:{width:1280, height:800}, events:[move], requestId:923})).ok, true);
});

test('B08: métricas cambian después del cuadro y la base cacheada no autoriza entrada', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'resize-before-input');
  const shot = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  assert.deepEqual([shot.width, shot.height], [1280, 800]);
  const before = trace().length;
  const move = {kind:'mouse', type:'mouseMoved', button:'none', buttons:0, x:10, y:10, modifiers:0, clickCount:0};
  const result = await request({action:'input', tab:'fixture-tab', basis:{width:1280, height:800}, events:[move]});
  assert.equal(result.status, 409);
  assert.match(result.error, /cambió de tamaño/);
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Runtime.evaluate']);
});

test('B08: acepta base actual sin otro cuadro y libera teclas y botones aun con base vieja', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'resize-before-input');
  await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  const key = {kind:'key', type:'keyDown', key:'a', code:'KeyA', keyCode:65, modifiers:0};
  const mouse = {kind:'mouse', type:'mousePressed', button:'left', buttons:1, x:10, y:10, modifiers:0, clickCount:1};
  const before = trace().length;
  assert.equal((await request({action:'input', tab:'fixture-tab', basis:{width:900, height:600}, events:[key, mouse]})).ok, true);
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Runtime.evaluate', 'Input.dispatchKeyEvent', 'Input.dispatchMouseEvent']);
  const releaseStart = trace().length;
  assert.equal((await request({action:'release-input', tab:'fixture-tab', basis:{width:1280, height:800},
    events:[{...key, type:'keyUp'}, {...mouse, type:'mouseReleased', buttons:0, clickCount:0}]})).ok, true);
  const released = trace().slice(releaseStart);
  assert.deepEqual(released.map(x => x.method), ['Input.dispatchKeyEvent', 'Input.dispatchMouseEvent']);
  assert.equal(released[0].params.type, 'keyUp');
  assert.equal(released[1].params.clickCount, 0);
  assert.equal(trace().some(x => ['Target.activateTarget', 'Page.navigate', 'Emulation.setDeviceMetricsOverride'].includes(x.method)), false);
});
