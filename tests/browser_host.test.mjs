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
  assert.deepEqual(trace().slice(start).map(x=>x.method), ['Page.captureScreenshot']);
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

async function worker(t, scenario) {
  const folder = mkdtempSync(join(tmpdir(), 'lienzo-host-fixture-'));
  const data = process.platform === 'win32' ? join(folder, 'Google/Chrome/User Data')
    : process.platform === 'darwin' ? join(folder, 'Library/Application Support/Google/Chrome')
      : join(folder, '.config/google-chrome');
  mkdirSync(data, {recursive:true});
  writeFileSync(join(data, 'DevToolsActivePort'), '9222\n/devtools/browser/fixture\n');
  const traceFile = join(folder, 'cdp.jsonl');
  const child = spawn(process.execPath, ['--import', pathToFileURL(preload).href, host, join(folder, 'profile')], {
    env: {...process.env, LOCALAPPDATA:folder, HOME:folder, USERPROFILE:folder, TEST_BROWSER_HOST_SCENARIO:scenario, TEST_BROWSER_HOST_TRACE:traceFile},
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

for (const method of ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.setDeviceMetricsOverride', 'Page.captureScreenshot', 'Page.getNavigationHistory']) {
  test(`frame: vence ${method}; state y el siguiente frame siguen usables`, {timeout:15000}, async t => {
    const {request, methods} = await worker(t, method);
    const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
    const failed = await request(frame);
    assert.equal(failed.status, 504);
    assert.equal(failed.error, `Chrome tardó demasiado en responder (${method})`);
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

test('frame frío usa siete comandos CDP; frame caliente usa cuatro sin tocar foco Win32', {timeout:15000}, async t => {
  const {request, trace} = await worker(t, 'healthy');
  const frame = {action:'frame', tab:'fixture-tab', width:800, height:600};
  const before = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const cold = trace().slice(before);
  assert.deepEqual(cold.map(item => item.method), ['Target.getTargets', 'Target.attachToTarget', 'Page.enable', 'Emulation.setDeviceMetricsOverride', 'Page.captureScreenshot', 'Page.getNavigationHistory', 'Target.getTargets']);
  const next = trace().length;
  assert.equal((await request(frame)).image, 'fixture-image');
  const warm = trace().slice(next);
  assert.deepEqual(warm.map(item => item.method), ['Target.getTargets', 'Page.captureScreenshot', 'Page.getNavigationHistory', 'Target.getTargets']);
  t.diagnostic(JSON.stringify({cold:cold.map(item => item.method), warm:warm.map(item => item.method), timing:'fixture; no es medición de Chrome remoto'}));
});
