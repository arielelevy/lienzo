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
  // existing: lee el tamaño real (solo lectura) y captura; nunca emula
  assert.deepEqual(trace().slice(start).map(x=>x.method), ['Page.getLayoutMetrics', 'Page.captureScreenshot']);
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

async function worker(t, scenario, view = '1280x800') {
  const folder = mkdtempSync(join(tmpdir(), 'lienzo-host-fixture-'));
  const data = process.platform === 'win32' ? join(folder, 'Google/Chrome/User Data')
    : process.platform === 'darwin' ? join(folder, 'Library/Application Support/Google/Chrome')
      : join(folder, '.config/google-chrome');
  mkdirSync(data, {recursive:true});
  writeFileSync(join(data, 'DevToolsActivePort'), '9222\n/devtools/browser/fixture\n');
  const traceFile = join(folder, 'cdp.jsonl');
  const child = spawn(process.execPath, ['--import', pathToFileURL(preload).href, host, join(folder, 'profile')], {
    env: {...process.env, LOCALAPPDATA:folder, HOME:folder, USERPROFILE:folder, TEST_BROWSER_HOST_SCENARIO:scenario, TEST_BROWSER_HOST_TRACE:traceFile, TEST_BROWSER_HOST_VIEW:view},
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

for (const method of ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.clearDeviceMetricsOverride', 'Page.getLayoutMetrics', 'Page.captureScreenshot', 'Page.getNavigationHistory']) {
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

test('frame frío usa ocho comandos CDP; frame caliente usa cinco sin tocar foco Win32', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'healthy');
  const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
  const before = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const cold = trace().slice(before);
  assert.deepEqual(cold.map(item => item.method), ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.clearDeviceMetricsOverride', 'Page.getLayoutMetrics', 'Page.captureScreenshot', 'Page.getNavigationHistory', 'Target.getTargets']);
  const next = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const warm = trace().slice(next);
  assert.deepEqual(warm.map(item => item.method), ['Target.getTargets', 'Page.getLayoutMetrics', 'Page.captureScreenshot', 'Page.getNavigationHistory', 'Target.getTargets']);
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

test('existing: la captura arranca en el scroll actual y escala la imagen, no la página', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'none');
  const shot = await request({action:'snapshot', tab:'fixture-tab', width:900, height:600, requestId:901});
  assert.deepEqual([shot.width, shot.height], [1280, 800]); // tamaño CSS real, no el del visor
  const clip = trace().filter(x => x.method === 'Page.captureScreenshot').at(-1).params.clip;
  assert.deepEqual({x:clip.x, y:clip.y, width:clip.width, height:clip.height}, {x:0, y:1600, width:1280, height:800});
  assert.equal(clip.scale, Math.min(900 / 1280, 600 / 800));
  assert.equal(trace().filter(x => ['Emulation.setDeviceMetricsOverride', 'Runtime.evaluate'].includes(x.method)).length, 0);
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
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Page.getLayoutMetrics']);
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
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Page.getLayoutMetrics']);
});

test('B08: acepta base actual sin otro cuadro y libera teclas y botones aun con base vieja', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'resize-before-input');
  await request({action:'snapshot', tab:'fixture-tab', width:900, height:600});
  const key = {kind:'key', type:'keyDown', key:'a', code:'KeyA', keyCode:65, modifiers:0};
  const mouse = {kind:'mouse', type:'mousePressed', button:'left', buttons:1, x:10, y:10, modifiers:0, clickCount:1};
  const before = trace().length;
  assert.equal((await request({action:'input', tab:'fixture-tab', basis:{width:900, height:600}, events:[key, mouse]})).ok, true);
  assert.deepEqual(trace().slice(before).map(x => x.method), ['Page.getLayoutMetrics', 'Input.dispatchKeyEvent', 'Input.dispatchMouseEvent']);
  const releaseStart = trace().length;
  assert.equal((await request({action:'release-input', tab:'fixture-tab', basis:{width:1280, height:800},
    events:[{...key, type:'keyUp'}, {...mouse, type:'mouseReleased', buttons:0, clickCount:0}]})).ok, true);
  const released = trace().slice(releaseStart);
  assert.deepEqual(released.map(x => x.method), ['Input.dispatchKeyEvent', 'Input.dispatchMouseEvent']);
  assert.equal(released[0].params.type, 'keyUp');
  assert.equal(released[1].params.clickCount, 0);
  assert.equal(trace().some(x => ['Target.activateTarget', 'Page.navigate', 'Emulation.setDeviceMetricsOverride'].includes(x.method)), false);
});
