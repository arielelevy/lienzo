/** Propuesta de aceptación: UI real, peer y Chrome simulados explícitamente. */
import { test, expect, type Page } from "@playwright/test";
import { bloquearEscrituras } from "./tablero-fijo";
test.use({hasTouch: true});

const WORKER_BUSY = 'Chrome está atendiendo otro pedido; esperá un momento';
type BrowserCommand = Record<string, unknown>;
type BrowserFixture = {status?: number; json: Record<string, unknown>};

/** Intercepta cada comando; no consulta ni controla Chrome o PCs reales. */
async function busyFixture(page: Page, reply: (command: BrowserCommand) => BrowserFixture | undefined) {
  const calls: BrowserCommand[] = [];
  await bloquearEscrituras(page);
  await page.route('**/auth', r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route('**/peers', r => r.fulfill({json: [
    {pc_id: 'busy-peer', name: 'PC ocupada', alive: true, local: false},
    {pc_id: 'other-peer', name: 'Otra PC', alive: true, local: false},
  ]}));
  await page.routeWebSocket('**/browser/stream*', ws => ws.onMessage(() => {}));
  await page.route('**/browser', r => {
    const command = r.request().postDataJSON() as BrowserCommand;
    calls.push(command);
    return r.fulfill(reply(command) ?? {json: command.action === 'profiles' ? {profiles: [{id: 'Default', name: 'Fixture'}]}
      : command.action === 'windows' ? {windows: [{id: 'fixture-window', title: 'Fixture'}]}
      : {running: true, mode: 'existing', tabs: [{id: 'fixture-tab', title: String(command.pc), url: 'about:blank'}], image: '/9j/2Q==', width: 1280, height: 800}});
  });
  await page.goto('/chrome?pc=busy-peer');
  await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click();
  await page.getByRole('button', {name: 'Vista por pestañas', exact: true}).click();
  return calls;
}

test('worker ocupado en state es temporal y recupera la vista sin reconectar', async ({page}) => {
  let states = 0;
  const calls = await busyFixture(page, d => d.action === 'state' && ++states <= 2
    ? {status: 409, json: {error: WORKER_BUSY}} : undefined);
  await expect(page.getByRole('status')).toContainText('Reintentando lectura');
  await expect(page.getByRole('heading', {name: 'No se pudo conectar con Chrome'})).toHaveCount(0);
  await expect(page.getByRole('tab', {name: 'busy-peer', exact: true})).toBeVisible();
  await expect(page.getByRole('application', {name: 'Página remota: mouse y teclado'})).toBeVisible();
  expect(states).toBe(3);
  expect(calls.some(d => ['connect', 'start', 'stop'].includes(String(d.action)))).toBeFalsy();
});

test('worker ocupado al leer perfiles reintenta sólo la lectura', async ({page}) => {
  let profiles = 0;
  const calls = await busyFixture(page, d => d.action === 'profiles' && ++profiles === 2
    ? {status: 409, json: {error: WORKER_BUSY}} : undefined); // la primera lectura pertenece al modo ventana
  await expect(page.getByRole('status')).toContainText('Reintentando lectura');
  await expect(page.getByRole('status')).toHaveCount(0);
  expect(profiles).toBe(3);
  expect(calls.some(d => d.action === 'connect' || d.action === 'start')).toBeFalsy();
});

test('worker ocupado durante conexión conserva el permiso pendiente y recupera sin reenviar connect', async ({page}) => {
  let connecting = false;
  let polls = 0;
  const calls = await busyFixture(page, d => {
    if (d.action === 'connect') { connecting = true; return {json: {connecting: true, running: false}}; }
    if (d.action === 'state') {
      if (!connecting) return {json: {connecting: false, running: false}};
      if (++polls <= 2) return {status: 409, json: {error: WORKER_BUSY}};
      return {json: {connecting: false, running: true, tabs: [{id: 'fixture-tab', title: 'busy-peer', url: 'about:blank'}]}};
    }
  });
  await page.getByRole('button', {name: 'Conectar Chrome abierto', exact: true}).click();
  await expect(page.getByRole('status')).toContainText('Reintentando lectura');
  await expect(page.getByRole('heading', {name: 'Aceptá la conexión en Chrome'})).toBeVisible();
  await expect(page.getByRole('tab', {name: 'busy-peer', exact: true})).toBeVisible();
  expect(calls.filter(d => d.action === 'connect')).toHaveLength(1);
});

test('worker ocupado en frame conserva imagen, limita reintentos y permite recuperar manualmente', async ({page}) => {
  let occupied = false;
  let rejected = 0;
  const calls = await busyFixture(page, d => {
    if (d.action === 'frame' && occupied) { rejected++; return {status: 409, json: {error: WORKER_BUSY}}; }
  });
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  occupied = true;
  await expect(page.getByRole('status')).toContainText('Reintentando lectura');
  await expect(screen).toBeVisible();
  await expect(page.getByRole('button', {name: 'Actualizar vista', exact: true})).toBeVisible({timeout: 10000});
  expect(rejected).toBe(4); // un intento y tres reintentos, nunca el polling ilimitado de cualquier 409
  await page.waitForTimeout(800);
  expect(rejected).toBe(4);
  expect(calls.some(d => d.action === 'stop')).toBeFalsy();
  occupied = false;
  await page.getByRole('button', {name: 'Actualizar vista', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Actualizar vista', exact: true})).toHaveCount(0);
  await expect(screen).toBeVisible();
});

for (const {status, error} of [
  {status: 409, error: 'Chrome está cerrado. Abrilo desde Chrome remoto'},
  {status: 504, error: WORKER_BUSY},
]) {
  test(`no reintenta error definitivo ${status}: ${error}`, async ({page}) => {
    let frames = 0;
    await busyFixture(page, d => {
      if (d.action === 'frame') { frames++; return {status, json: {error}}; }
    });
    await expect(page.getByRole('heading', {name: 'No se pudo conectar con Chrome'})).toBeVisible();
    await expect(page.getByText(error, {exact: true})).toBeVisible();
    await page.waitForTimeout(800);
    expect(frames).toBe(1);
  });
}

test('worker ocupado no reenvía teclas ni desconecta la imagen', async ({page}) => {
  const calls = await busyFixture(page, d => d.action === 'input' ? {status: 409, json: {error: WORKER_BUSY}} : undefined);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  await screen.focus();
  await screen.press('a');
  await expect(page.getByRole('alert')).toContainText('El pedido no se reintentó');
  await expect(screen).toBeVisible();
  const inputs = calls.filter(d => d.action === 'input').length;
  expect(inputs).toBeGreaterThan(0);
  await page.waitForTimeout(1000);
  expect(calls.filter(d => d.action === 'input')).toHaveLength(inputs);
  expect(calls.some(d => d.action === 'stop' || d.action === 'connect')).toBeFalsy();
});

for (const change of ['pc', 'modo'] as const) {
  test(`cancela lectura ocupada al cambiar ${change}`, async ({page}) => {
    const calls = await busyFixture(page, d => d.pc === 'busy-peer' && d.action === 'state'
      ? {status: 409, json: {error: WORKER_BUSY}} : undefined);
    await expect(page.getByRole('status')).toContainText('Reintentando lectura');
    if (change === 'pc') {
      await page.getByRole('combobox', {name: 'PC del navegador'}).selectOption('other-peer');
      await expect(page.getByRole('tab', {name: 'other-peer', exact: true})).toBeVisible();
    } else {
      await page.getByRole('button', {name: 'Chrome real · ventana completa', exact: true}).click();
      await expect(page.getByRole('combobox', {name: 'Ventana de Chrome'})).toHaveValue('fixture-window');
    }
    const oldStates = calls.filter(d => d.pc === 'busy-peer' && d.action === 'state').length;
    await page.waitForTimeout(1800);
    expect(calls.filter(d => d.pc === 'busy-peer' && d.action === 'state')).toHaveLength(oldStates);
    await expect(page.getByRole('heading', {name: 'No se pudo conectar con Chrome'})).toHaveCount(0);
  });
}

async function streamFixture(page: Page, automaticFrames = true) {
  const http: BrowserCommand[] = [];
  const channels: {commands: BrowserCommand[]; send: (message: string | Buffer) => void; close: () => void}[] = [];
  // 'server': contesta release-input como browser_stream.TabWorker (rechaza una generación no abierta en este canal)
  const control = {input: 'ack' as 'ack' | 'hold' | 'uncertain', release: 'ack' as 'ack' | 'hold' | 'server', state: true};
  const owned = {buttons: new Set<string>(), keys: new Set<string>()};
  const releases: {generation: number; reason: string; buttons: string[]; keys: string[]}[] = [];
  const releaseOwned = (generation: number, reason: string) => {
    releases.push({generation, reason, buttons: [...owned.buttons], keys: [...owned.keys]}); owned.buttons.clear(); owned.keys.clear();
  };
  await bloquearEscrituras(page);
  await page.route('**/auth', r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route('**/peers', r => r.fulfill({json: [{pc_id: 'stream-fixture', name: 'PC stream', alive: true, local: false, health: {capabilities: ['browser.tabs.stream.v1']}}]}));
  const tabs = [{id: 'a', title: 'Pestaña A', url: 'about:blank'}, {id: 'b', title: 'Pestaña B', url: 'about:blank'}];
  await page.route('**/browser', r => {
    const d = r.request().postDataJSON(); http.push(d);
    return r.fulfill({json: d.action === 'windows' ? {windows: [{id: 'fixture', title: 'Fixture'}]}
      : d.action === 'profiles' ? {profiles: []} : {running: d.action !== 'stop', mode: 'existing', tabs}});
  });
  const images = await page.evaluate(() => ['#ff0000', '#0000ff'].map(color => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
    const ctx = canvas.getContext('2d')!; ctx.fillStyle = color; ctx.fillRect(0, 0, 320, 240);
    return canvas.toDataURL('image/jpeg', .8).split(',')[1];
  }));
  const packet = (generation: number, seq: number, blue = false) => {
    const header = Buffer.alloc(12);
    header.writeUInt32BE(generation, 0); header.writeUInt32BE(seq, 4); header.writeUInt16BE(320, 8); header.writeUInt16BE(240, 10);
    return Buffer.concat([header, Buffer.from(images[blue ? 1 : 0], 'base64')]);
  };
  await page.routeWebSocket('**/browser/stream*', ws => {
    if (!ws.url().includes('mode=tabs')) { ws.onMessage(() => {}); return; }
    const channel = {commands: [] as BrowserCommand[], send: (message: string | Buffer) => ws.send(message), close: () => ws.close({code: 1011, reason: 'corte fixture'})};
    channels.push(channel);
    let currentGeneration = 0;
    ws.onMessage(message => {
      const d = JSON.parse(String(message)); channel.commands.push(d);
      if (d.t === 'open') {
        if (currentGeneration) releaseOwned(currentGeneration, 'open');
        currentGeneration = d.generation;
        ws.send(JSON.stringify({t: 'opened', generation: d.generation, tab: d.tab, width: 320, height: 240, format: 'jpeg'}));
        if (control.state) ws.send(JSON.stringify({t: 'state', generation: d.generation, tabs, back: true, forward: false, dialog: null}));
        if (automaticFrames) ws.send(packet(d.generation, 1, d.tab === 'b'));
      }
      if (d.t === 'input') for (const event of d.events) {
        if (event.type === 'mousePressed') owned.buttons.add(String(event.button));
        if (event.type === 'mouseReleased') owned.buttons.delete(String(event.button));
        const key = String(event.code || event.key || event.keyCode);
        if (event.type === 'keyDown') owned.keys.add(key);
        if (event.type === 'keyUp') owned.keys.delete(key);
      }
      if (d.t === 'release-input') {
        releaseOwned(d.generation, 'release-input');
        if (control.release === 'ack' || (control.release === 'server' && currentGeneration && d.generation === currentGeneration)) ws.send(JSON.stringify({t: 'input', n: d.n, generation: d.generation}));
        else if (control.release === 'server') ws.send(JSON.stringify({t: 'error', input: true, n: d.n, generation: d.generation, outcome: 'rejected', message: 'Entrada de una selección vencida o repetida; no se envió'}));
      }
      if (d.t === 'input' && control.input !== 'hold') ws.send(JSON.stringify(control.input === 'ack'
        ? {t: 'input', n: d.n, generation: d.generation}
        : {t: 'error', input: true, n: d.n, generation: d.generation, outcome: 'uncertain', message: 'CDP sin respuesta fixture'}));
    });
  });
  await page.goto('/chrome?pc=stream-fixture');
  await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click();
  await page.getByRole('button', {name: 'Vista por pestañas', exact: true}).click();
  await expect.poll(() => channels.length).toBe(1);
  await expect.poll(() => channels[0].commands.filter(d => d.t === 'open').length).toBeGreaterThan(0);
  return {channels, http, packet, control, owned, releases};
}

async function holdFirstDecode(page: Page, at = 1) {
  await page.addInitScript(at => {
    const original = window.createImageBitmap.bind(window);
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const stats = {calls: 0, active: 0, max: 0, release: () => release()};
    Object.assign(window, {decodeFixture: stats});
    window.createImageBitmap = (async (image: ImageBitmapSource, options?: ImageBitmapOptions) => {
      stats.calls++; stats.active++; stats.max = Math.max(stats.max, stats.active);
      try { if (stats.calls === at) await gate; return await original(image, options); }
      finally { stats.active--; }
    }) as typeof createImageBitmap;
  }, at);
}

test('tabs stream hover avanza sin esperar cada ACK y conserva la última posición', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.input = 'hold';
  const box = (await screen.boundingBox())!;
  const events = () => f.channels[0].commands.filter(d => d.t === 'input');
  for (let i = 0; i < 12; i++) {
    await page.mouse.move(box.x + box.width / 2 + i, box.y + box.height / 2);
    await page.waitForTimeout(20);
  }
  await expect.poll(() => events().length).toBeGreaterThan(1);
  expect(events().length).toBeLessThanOrEqual(4);
  const before = [...events()];
  f.control.input = 'ack';
  for (const [i, d] of before.entries()) f.channels[0].send(JSON.stringify({t: 'input', n: d.n, generation: d.generation, ...(i === 1 ? {outcome: 'superseded'} : {})}));
  await expect.poll(() => events().length).toBeGreaterThan(before.length);
  const last = events().at(-1)!;
  const moves = last.events as Record<string, unknown>[];
  const scale = Math.min(box.width / 320, box.height / 240);
  expect(moves.at(-1)!.x).toBe(Math.round(160 + 11 / scale));
  expect(moves.at(-1)!.buttons).toBe(0);
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
});

test('tabs stream no acepta confirmar una tecla como movimiento reemplazado', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.input = 'hold';
  await screen.focus(); await screen.press('a');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  const sent = f.channels[0].commands.filter(d => d.t === 'input');
  const d = sent[0];
  f.channels[0].send(JSON.stringify({t: 'input', n: d.n, generation: d.generation, outcome: 'superseded'}));
  await expect(screen).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('alert').filter({hasText: 'Confirmación de reemplazo inválida'})).toBeVisible();
  expect(f.channels[0].commands.filter(d => d.t === 'input')).toHaveLength(sent.length);
});

test('tabs stream negocia JPEG, acusa después de dibujar y manda teclado sin HTTP frame/input', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'ack').length).toBe(1);
  await screen.focus(); await screen.press('a');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  expect(f.http.some(d => d.action === 'frame' || d.action === 'input' || d.action === 'connect')).toBeFalsy();
  const rgb = await page.locator('canvas').evaluate(c => Array.from((c as HTMLCanvasElement).getContext('2d')!.getImageData(10, 10, 1, 1).data));
  expect(rgb[0]).toBeGreaterThan(200); expect(rgb[2]).toBeLessThan(30);
  await page.getByRole('button', {name: 'Atrás', exact: true}).click();
  expect(f.http.some(d => d.action === 'history')).toBeTruthy();
  const before = f.channels[0].commands.filter(d => d.t === 'open').length;
  const releasesBefore = f.channels[0].commands.filter(d => d.t === 'release-input').length; // el blur de «Atrás» ya soltó
  await page.setViewportSize({width: 1200, height: 750});
  // el visor cambió de tamaño: sólo la escala de la captura; sin open, sin release ni generación nueva
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'size').length).toBeGreaterThan(0);
  expect(f.channels[0].commands.filter(d => d.t === 'open')).toHaveLength(before);
  const size = f.channels[0].commands.filter(d => d.t === 'size').at(-1)!;
  expect(size.generation).toBe(f.channels[0].commands.filter(d => d.t === 'open').at(-1)!.generation);
  expect(f.channels[0].commands.filter(d => d.t === 'release-input')).toHaveLength(releasesBefore);
});

test('tabs stream descarta decode de generación vieja al cambiar pestaña', async ({page}) => {
  await holdFirstDecode(page);
  const f = await streamFixture(page);
  await expect.poll(() => page.evaluate(() => (window as unknown as {decodeFixture: {calls: number}}).decodeFixture.calls)).toBe(1);
  await page.getByRole('tab', {name: 'Pestaña B', exact: true}).click();
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'open').length).toBe(2);
  await page.evaluate(() => (window as unknown as {decodeFixture: {release: () => void}}).decodeFixture.release());
  await expect(page.locator('canvas')).toBeVisible();
  const current = Number(f.channels[0].commands.filter(d => d.t === 'open').at(-1)!.generation);
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'ack').map(d => d.generation)).toEqual([current]);
  const rgb = await page.locator('canvas').evaluate(c => Array.from((c as HTMLCanvasElement).getContext('2d')!.getImageData(10, 10, 1, 1).data));
  expect(rgb[2]).toBeGreaterThan(200); expect(rgb[0]).toBeLessThan(30);
});

test('tabs stream conserva un decoder y un slot latest ante ráfaga', async ({page}) => {
  await holdFirstDecode(page);
  const f = await streamFixture(page);
  await expect.poll(() => page.evaluate(() => (window as unknown as {decodeFixture: {calls: number}}).decodeFixture.calls)).toBe(1);
  const gen = Number(f.channels[0].commands.find(d => d.t === 'open')!.generation);
  for (let n = 2; n <= 6; n++) f.channels[0].send(f.packet(gen, n, true));
  await page.waitForTimeout(100); // dejar llegar la ráfaga al slot, manteniendo decode detenido
  expect(f.channels[0].commands.filter(d => d.t === 'ack')).toHaveLength(0);
  await page.evaluate(() => (window as unknown as {decodeFixture: {release: () => void}}).decodeFixture.release());
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'ack').map(d => d.n)).toEqual([1, 6]);
  expect(await page.evaluate(() => { const s = (window as unknown as {decodeFixture: {calls: number; max: number}}).decodeFixture; return {calls: s.calls, max: s.max}; })).toEqual({calls: 2, max: 1});
});

test('tabs stream input no espera el decode de la captura siguiente', async ({page}) => {
  await holdFirstDecode(page, 2);
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  const gen = Number(f.channels[0].commands.find(d => d.t === 'open')!.generation);
  f.channels[0].send(f.packet(gen, 2, true));
  await expect.poll(() => page.evaluate(() => (window as unknown as {decodeFixture: {calls: number}}).decodeFixture.calls)).toBe(2);
  await screen.focus(); await screen.press('a');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  expect(f.channels[0].commands.some(d => d.t === 'ack' && d.n === 2)).toBeFalsy();
  await page.evaluate(() => (window as unknown as {decodeFixture: {release: () => void}}).decodeFixture.release());
  await expect.poll(() => f.channels[0].commands.some(d => d.t === 'ack' && d.n === 2)).toBeTruthy();
  expect(f.http.some(d => d.action === 'frame' || d.action === 'input')).toBeFalsy();
});

test('tabs stream reconecta sólo lectura y requiere habilitar entrada incierta sin replay', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.input = 'hold';
  await screen.focus(); await screen.press('a');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  f.channels[0].close();
  await expect(page.getByRole('alert')).toContainText('Entrada sin confirmación');
  f.control.input = 'ack';
  await expect.poll(() => f.channels.length).toBe(2);
  await expect(screen).toHaveAttribute('aria-disabled', 'true');
  expect(f.channels[1].commands.some(d => d.t === 'input')).toBeFalsy();
  await page.getByRole('button', {name: 'Habilitar entrada sin reenviar'}).click();
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  expect(f.channels[1].commands.some(d => d.t === 'input')).toBeFalsy();
  await screen.focus(); await screen.press('b');
  await expect.poll(() => f.channels[1].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  expect(f.http.some(d => d.action === 'input' || d.action === 'frame')).toBeFalsy();
});

test('tabs stream reconecta sin mandar al canal nuevo un release de la generación del canal viejo', async ({page}) => {
  const f = await streamFixture(page);
  f.control.release = 'server';
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.channels[0].close(); // la PC remota se actualizó y reinició: worker nuevo, sin generación abierta
  await expect.poll(() => f.channels.length).toBe(2);
  await expect.poll(() => f.channels[1].commands.filter(d => d.t === 'open').length).toBeGreaterThan(0);
  const first = f.channels[1].commands.findIndex(d => d.t === 'open');
  expect(f.channels[1].commands.slice(0, first).filter(d => d.t === 'release-input')).toEqual([]);
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByText('selección vencida o repetida')).toHaveCount(0);
  await expect(page.getByRole('button', {name: 'Habilitar entrada sin reenviar'})).toHaveCount(0);
  await screen.focus(); await screen.press('b');
  await expect.poll(() => f.channels[1].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
});

test('tabs stream: el arrastre táctil manda rueda con un botón que el host acepta', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  const box = (await screen.boundingBox())!;
  const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2);
  const touch = await page.context().newCDPSession(page);
  await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x, y}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x, y: y - 60}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x, y: y - 120}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await touch.detach();
  const events = () => f.channels[0].commands.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]);
  await expect.poll(() => events().filter(e => e.type === 'mouseWheel').length).toBeGreaterThan(0);
  // browser_host.mjs rechaza cualquier botón fuera de esta lista («Acción de mouse inválida»)
  expect(events().filter(e => e.type === 'mouseWheel').map(e => e.button)).toEqual(events().filter(e => e.type === 'mouseWheel').map(() => 'none'));
  expect(events().some(e => e.type === 'mousePressed')).toBeFalsy();
});

test('tabs stream activa la pestaña sólo al elegirla; tamaño y reconexión no la activan', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  const activations = () => f.http.filter(d => d.action === 'activate');
  expect(activations()).toHaveLength(0);
  await page.setViewportSize({width: 1200, height: 750});
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'size').length).toBeGreaterThan(0);
  f.channels[0].close();
  await expect.poll(() => f.channels.length).toBe(2);
  await expect.poll(() => f.channels[1].commands.filter(d => d.t === 'open').length).toBeGreaterThan(0);
  expect(activations()).toHaveLength(0);
  await page.getByRole('tab', {name: 'Pestaña B', exact: true}).click();
  await expect.poll(() => activations().map(d => d.tab)).toEqual(['b']);
});

test('tabs stream: un arrastre táctil largo con la remota lenta suma ruedas y no agota las entradas pendientes', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.input = 'hold'; // ningún ACK: cada pedido queda pendiente, como con una remota lenta
  const box = (await screen.boundingBox())!;
  const x = Math.round(box.x + box.width / 2), y0 = Math.round(box.y + box.height - 40);
  const touch = await page.context().newCDPSession(page);
  await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x, y: y0}]});
  for (let i = 1; i <= 60; i++) await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x, y: y0 - i * 5}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await touch.detach();
  await page.waitForTimeout(300);
  const wheels = f.channels[0].commands.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).filter(e => e.type === 'mouseWheel');
  expect(wheels.length).toBeGreaterThan(0);
  // sin ACK sale un solo pedido; el resto espera sumado, sin agotar las 32 pendientes
  expect(f.channels[0].commands.filter(d => d.t === 'input')).toHaveLength(1);
  await expect(page.getByText('Demasiadas entradas pendientes')).toHaveCount(0);
});

test('tabs stream: con ACK el arrastre táctil llega entero, sumado en pocos pedidos', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  const box = (await screen.boundingBox())!;
  const x = Math.round(box.x + box.width / 2), y0 = Math.round(box.y + box.height - 40);
  const touch = await page.context().newCDPSession(page);
  await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x, y: y0}]});
  for (let i = 1; i <= 60; i++) await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x, y: y0 - i * 5}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await touch.detach();
  const sent = () => f.channels[0].commands.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).filter(e => e.type === 'mouseWheel');
  // 60 movimientos de 5 px menos el umbral de 8 px: el desplazamiento total llega aunque vaya sumado
  await expect.poll(() => sent().reduce((sum, e) => sum + Number(e.deltaY), 0)).toBeGreaterThanOrEqual(280);
  expect(f.channels[0].commands.filter(d => d.t === 'input').length).toBeLessThanOrEqual(60);
});

test('tabs stream con el tamaño quieto no reabre ni cambia el tamaño pedido (sin bucle de layout)', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  // cuadros con otro tamaño que el pedido: no deben disparar el ResizeObserver ni otro open
  const gen = Number(f.channels[0].commands.filter(d => d.t === 'open').at(-1)!.generation);
  for (let n = 2; n <= 8; n++) { f.channels[0].send(f.packet(gen, n, n % 2 === 0)); await page.waitForTimeout(150); }
  const opens = f.channels[0].commands.filter(d => d.t === 'open');
  const sizes = new Set(opens.map(d => `${d.width}x${d.height}`));
  expect(opens, JSON.stringify(opens)).toHaveLength(1);
  expect(sizes.size).toBe(1);
});

test('tabs stream muestra captura inválida sin ocultar el último cuadro ni degradar a HTTP', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible();
  f.channels[0].send(Buffer.alloc(4));
  await expect(page.getByRole('alert')).toContainText('Cuadro JPEG de Chrome inválido');
  await expect(screen).toBeVisible();
  expect(f.http.some(d => d.action === 'frame')).toBeFalsy();
  const previous = Number(f.channels[0].commands.find(d => d.t === 'open')!.generation);
  await page.getByRole('button', {name: 'Actualizar captura', exact: true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  const next = Number(f.channels[0].commands.filter(d => d.t === 'open').at(-1)!.generation);
  expect(next).toBeGreaterThan(previous);
  f.channels[0].send(f.packet(previous, 20, true));
  await page.waitForTimeout(150);
  expect(f.channels[0].commands.some(d => d.t === 'ack' && d.generation === previous && d.n === 20)).toBeFalsy();
});

test('tabs stream pausa/resume al ocultar y release no cierra Chrome al salir del modo', async ({page}) => {
  const f = await streamFixture(page);
  await expect(page.locator('canvas')).toBeVisible();
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', {value: true, configurable: true}); document.dispatchEvent(new Event('visibilitychange')); });
  await expect.poll(() => f.channels[0].commands.some(d => d.t === 'pause')).toBeTruthy();
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', {value: false, configurable: true}); document.dispatchEvent(new Event('visibilitychange')); });
  await expect.poll(() => f.channels[0].commands.some(d => d.t === 'resume')).toBeTruthy();
  const controls = page.getByRole('button', {name: 'Controles de Chrome remoto'});
  if (await controls.getAttribute('aria-expanded') !== 'true') await controls.click();
  await page.getByRole('button', {name: 'Chrome real · ventana completa', exact: true}).click();
  await expect.poll(() => f.channels[0].commands.some(d => d.t === 'release')).toBeTruthy();
  expect(f.http.some(d => d.action === 'stop')).toBeFalsy();
});

test('tabs stream timeout de input y ACK tardío no habilitan entrada ni reenvían', async ({page}) => {
  await page.clock.install();
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.input = 'hold'; await screen.focus(); await screen.press('a');
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  const inputs = f.channels[0].commands.filter(d => d.t === 'input');
  await page.clock.runFor(10100);
  await expect(page.getByRole('alert')).toContainText('Entrada sin confirmación');
  for (const d of inputs) f.channels[0].send(JSON.stringify({t: 'input', n: d.n, generation: d.generation}));
  await expect(screen).toHaveAttribute('aria-disabled', 'true');
  expect(f.channels[0].commands.filter(d => d.t === 'input')).toHaveLength(inputs.length);
});

test('tabs stream held mouse resize up conserva foco y el botón sin open ni release', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  const original = await screen.elementHandle();
  const box = (await screen.boundingBox())!;
  // dentro de la imagen encajada: las franjas del letterbox no mandan clics
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await expect.poll(() => f.owned.buttons.size).toBe(1);
  await page.setViewportSize({width: 1100, height: 720});
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'size').length).toBeGreaterThan(0);
  expect(f.channels[0].commands.filter(d => d.t === 'open')).toHaveLength(1);
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  expect(await original!.evaluate(element => element.isConnected)).toBeTruthy();
  await expect(screen).toBeFocused();
  expect(f.owned.buttons.size).toBe(1); // el cambio de tamaño no suelta el botón: sigue el mismo arrastre
  await page.mouse.up();
  await expect.poll(() => f.owned.buttons.size).toBe(0);
  expect(f.channels[0].commands.some(d => d.t === 'release-input')).toBeFalsy();
  expect(f.channels[0].commands.filter(d => d.t === 'input').flatMap(d => d.events as BrowserCommand[]).filter(e => e.type === 'mousePressed')).toHaveLength(1);
});

test('tabs stream held key blur libera propia sin reenviar downs', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(() => f.owned.keys.size).toBe(1);
  await page.getByRole('textbox', {name: 'Dirección o búsqueda'}).focus();
  await expect.poll(() => f.owned.keys.size).toBe(0);
  await page.keyboard.up('Shift');
  expect(f.releases.filter(r => r.reason === 'release-input').flatMap(r => r.keys)).toEqual(['ShiftLeft']);
  expect(f.channels[0].commands.filter(d => d.t === 'input').flatMap(d => d.events as BrowserCommand[]).filter(e => e.type === 'keyDown')).toHaveLength(1);
});

test('tabs stream diálogo A no oculta frame B antes del state B', async ({page}) => {
  const f = await streamFixture(page);
  const gen = f.channels[0].commands.find(d => d.t === 'open')!.generation;
  f.channels[0].send(JSON.stringify({t: 'state', generation: gen, dialog: {type: 'prompt', message: 'Prompt A', defaultPrompt: ''}}));
  await expect(page.getByText('Prompt A', {exact: true})).toBeVisible();
  f.control.state = false;
  await page.getByRole('tab', {name: 'Pestaña B', exact: true}).click();
  await expect(page.getByRole('application', {name: 'Página remota: mouse y teclado'})).toBeVisible();
  await expect(page.getByText('Prompt A', {exact: true})).toHaveCount(0);
});

test('tabs stream release lento no absorbe otro blur después de un down nuevo', async ({page}) => {
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  f.control.release = 'hold';
  const address = page.getByRole('textbox', {name: 'Dirección o búsqueda'});
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(() => f.owned.keys.size).toBe(1);
  await address.focus();
  await expect.poll(() => f.owned.keys.size).toBe(0);
  await page.keyboard.up('Shift');
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(() => f.owned.keys.size).toBe(1);
  await address.focus();
  await expect.poll(() => f.owned.keys.size).toBe(0);
  expect(f.channels[0].commands.filter(d => d.t === 'release-input')).toHaveLength(2);
  expect(f.releases.flatMap(r => r.keys)).toEqual(['ShiftLeft', 'ShiftLeft']);
  await page.keyboard.up('Shift');
});

test('tabs stream held key cambio tab correlaciona ACK de release viejo', async ({page}) => {
  await page.clock.install();
  const f = await streamFixture(page);
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await expect(screen).toBeVisible(); await expect(screen).not.toHaveAttribute('aria-disabled', 'true');
  await screen.focus(); await page.keyboard.down('Shift');
  await expect.poll(() => f.owned.keys.size).toBe(1);
  f.control.release = 'hold';
  await page.getByRole('tab', {name: 'Pestaña B', exact: true}).click();
  await expect.poll(() => f.channels[0].commands.filter(d => d.t === 'open').length).toBe(2);
  const release = f.channels[0].commands.find(d => d.t === 'release-input')!;
  expect(release).toBeTruthy();
  const next = f.channels[0].commands.filter(d => d.t === 'open').at(-1)!;
  expect(Number(release.generation)).toBeLessThan(Number(next.generation));
  // Blur y selección liberan por separado: confirmar todos los pedidos realmente enviados.
  for (const d of f.channels[0].commands.filter(d => d.t === 'release-input')) {
    f.channels[0].send(JSON.stringify({t: 'input', n: d.n, generation: d.generation}));
  }
  await page.clock.runFor(10100);
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(f.owned.keys.size).toBe(0);
  await page.keyboard.up('Shift');
  const ids = f.channels[0].commands.filter(d => d.t === 'input' || d.t === 'release-input').map(d => Number(d.n));
  expect(new Set(ids).size).toBe(ids.length);
});

for (const saved of ['', 'Profile 1']) {
  test(`abre Chrome automáticamente sin ventanas y recuerda el perfil ${saved || 'predeterminado'}`, async ({page}) => {
    const calls: Record<string, unknown>[] = [];
    let opened = false;
    await page.route('**/auth', r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
    await page.route('**/peers', r => r.fulfill({json: [{pc_id: 'auto-peer', name: 'PC automática', alive: true, local: false}]}));
    if (saved) await page.addInitScript(profile => localStorage.setItem('chrome-profile:auto-peer', profile), saved);
    await page.route('**/browser', r => {
      const d = r.request().postDataJSON(); calls.push(d);
      if (d.action === 'prepare') opened = true;
      return r.fulfill({json: d.action === 'profiles'
        ? {profiles: [{id: 'Default', name: 'globant.com'}, {id: 'Profile 1', name: 'Ariel'}]}
        : d.action === 'windows' ? {windows: opened ? [{id: '456', title: 'Chrome automático'}] : []} : {prepared: true}});
    });
    await page.routeWebSocket('**/browser/stream*', ws => ws.onMessage(() => {}));
    await page.goto('/chrome');
    await expect.poll(() => calls.filter(d => d.action === 'prepare')).toEqual([
      {pc: 'auto-peer', action: 'prepare', profile: saved || 'Default', setup: false},
    ]);
    await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click();
    await expect(page.getByRole('combobox', {name: 'Ventana de Chrome'})).toHaveValue('456');
    await page.reload();
    await expect.poll(() => calls.filter(d => d.action === 'windows').length).toBeGreaterThanOrEqual(3);
    expect(calls.filter(d => d.action === 'prepare')).toHaveLength(1);
    expect(calls.every(d => d.pc === 'auto-peer')).toBeTruthy();
  });
}

test("abre una pestaña de Chrome remoto, navega y mantiene el destino", async ({page}) => {
  const calls: Record<string, unknown>[] = [];
  let running = false;
  let url = "about:blank";
  await page.route("**/auth", r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route("**/peers", r => r.fulfill({json: [
    {pc_id: "remote-test", name: "PC sin monitor", alive: true, local: false, health: null},
    {pc_id: "local-test", name: "Esta PC", alive: true, local: true, health: null},
  ]}));
  await page.route("**/browser", async r => {
    const d = r.request().postDataJSON();
    calls.push(d);
    if (d.action === "start") running = true;
    if (d.action === "navigate") url = d.url;
    if (d.action === "stop") running = false;
    await r.fulfill({json: {running, mode: 'lienzo', profiles: [], tabs: running ? [{id: "test-tab", title: "Prueba remota", url}] : [], image: "/9j/2Q==", width: 1280, height: 800, back: false, forward: false}});
  });
  await page.goto("/chrome");
  await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click(); // el menú ⋮ está cerrado al entrar
  await page.getByRole('button', {name: 'Vista por pestañas', exact: true}).click();
  await expect(page.getByRole("heading", {name: "Chrome en PC sin monitor"})).toBeVisible();
  await page.getByText('Usar un perfil separado de Lienzo', {exact: true}).click();
  await page.getByRole("button", {name: "Abrir Chrome", exact: true}).click();
  await expect(page.getByRole("tab", {name: "Prueba remota"})).toBeVisible();
  await page.getByRole("textbox", {name: "Dirección o búsqueda"}).fill("localhost:8765/prueba");
  await page.getByRole("textbox", {name: "Dirección o búsqueda"}).press("Enter");
  await expect.poll(() => calls.find(d => d.action === "navigate")?.url).toBe("http://localhost:8765/prueba");
  await page.getByRole("button", {name: "Cerrar Chrome", exact: true}).click();
  await page.getByText('Usar un perfil separado de Lienzo', {exact: true}).click();
  await expect(page.getByRole("button", {name: "Abrir Chrome", exact: true})).toBeVisible();
  expect(calls.every(d => d.pc === "remote-test")).toBeTruthy();
});

test("una PC caída no abre Chrome en esta PC", async ({page}) => {
  const calls: string[] = [];
  await page.route("**/auth", r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route("**/peers", r => r.fulfill({json: [
    {pc_id: "offline", name: "PC sin monitor", alive: false, local: false, health: null, diagnostico: "No responde el puerto"},
    {pc_id: "local-test", name: "Esta PC", alive: true, local: true, health: null},
  ]}));
  await page.route("**/browser", r => { calls.push(r.request().postData() ?? ""); return r.fulfill({status: 500, json: {error: "No se debe llamar"}}); });
  await page.goto("/chrome?pc=offline");
  await expect(page.getByRole("heading", {name: "PC sin monitor está desconectada"})).toBeVisible();
  await expect(page.getByRole("button", {name: "Abrir Chrome", exact: true})).toHaveCount(0);
  expect(calls).toHaveLength(0);
});

test('ofrece perfiles reales, espera permiso y desconecta sin cerrar Chrome', async ({page}) => {
  const calls: Record<string, unknown>[] = [];
  let connecting = false;
  let running = false;
  await page.route('**/auth', r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route('**/peers', r => r.fulfill({json: [{pc_id: 'remote', name: 'Otra PC', alive: true, local: false}]}));
  await page.route('**/browser', async r => {
    const d = r.request().postDataJSON();
    calls.push(d);
    if (d.action === 'connect') connecting = true;
    if (d.action === 'stop') { running = false; connecting = false; }
    await r.fulfill({json: {profiles: [{id: 'Default', name: 'globant.com'}, {id: 'Profile 1', name: 'Ariel'}],
      running, connecting, mode: 'existing', prepared: d.action === 'prepare',
      tabs: running ? [{id: 'one', title: 'Sesión habitual', url: 'about:blank'}] : [], image: '/9j/2Q=='}});
  });
  await page.goto('/chrome');
  await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click();
  await page.getByRole('button', {name: 'Vista por pestañas', exact: true}).click();
  await expect(page.getByRole('combobox', {name: 'Perfil de Chrome'})).toHaveValue('Default');
  await page.getByRole('button', {name: 'Abrir perfil en esa PC'}).click();
  expect(calls.find(d => d.action === 'prepare')).toEqual({pc: 'remote', action: 'prepare', profile: 'Default'});
  await page.getByRole('button', {name: 'Conectar Chrome abierto'}).click();
  await expect(page.getByRole('heading', {name: 'Aceptá la conexión en Chrome'})).toBeVisible();
  running = true; connecting = false;
  await expect(page.getByRole('tab', {name: 'Sesión habitual'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Cerrar Chrome', exact: true})).toHaveCount(0);
  await page.getByRole('button', {name: 'Desconectar', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Conectar Chrome abierto'})).toBeVisible();
  expect(calls.some(d => d.action === 'start')).toBeFalsy();
});

test('muestra la ventana completa por el canal vivo y manda el mouse sin pedir depuración remota', async ({page}) => {
  const calls: Record<string, unknown>[] = [];
  const stream: Record<string, unknown>[] = [];
  const urls: string[] = [];
  await page.route('**/auth', r => r.fulfill({json: {configured: false, authenticated: true, local: true}}));
  await page.route('**/peers', r => r.fulfill({json: [{pc_id: 'native-peer', name: 'Globant PC', alive: true, local: false}]}));
  await page.route('**/browser', r => {
    const d = r.request().postDataJSON(); calls.push(d);
    const response = d.action === 'windows' ? {windows: [{id: '123', title: 'Chrome Globant'}]}
      : d.action === 'profiles' ? {profiles: [{id: 'Default', name: 'globant.com'}]} : {ok: true};
    return r.fulfill({json: response});
  });
  // un cuadro completo de 1280 × 800 con un PNG válido de 1 × 1 (browser_window.png): cabecera >IHHHHHHB (seq, x, y, ancho, alto, total, flags)
  const header = Buffer.alloc(17);
  header.writeUInt32BE(1, 0); header.writeUInt16BE(0, 4); header.writeUInt16BE(0, 6); header.writeUInt16BE(1, 8); header.writeUInt16BE(1, 10);
  header.writeUInt16BE(1280, 12); header.writeUInt16BE(800, 14); header.writeUInt8(1, 16);
  const frame = Buffer.concat([header, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4AWP4z8AAAAMBAQDbfS68AAAAAElFTkSuQmCC', 'base64')]);
  await page.routeWebSocket('**/browser/stream*', ws => {
    urls.push(ws.url());
    ws.onMessage(message => {
      const d = JSON.parse(String(message)) as Record<string, unknown>;
      stream.push(d);
      if (d.t === 'open') { ws.send(JSON.stringify({t: 'opened', window: d.window})); ws.send(frame); }
      if (d.t === 'input') { ws.send(JSON.stringify({t: 'input', n: d.n})); ws.send(JSON.stringify({t: 'cursor', cursor: 'pointer'})); }
      if (d.t === 'copy') ws.send(JSON.stringify({t: 'clipboard', text: 'Texto remoto · ñ 🧉'}));
    });
  });
  await page.goto('/chrome');
  await page.getByRole('button', {name: 'Controles de Chrome remoto'}).click();
  await expect(page.getByRole('combobox', {name: 'Perfil del Chrome real'})).toHaveValue('Default');
  await expect(page.getByRole('combobox', {name: 'Ventana de Chrome'})).toHaveValue('123');
  await expect(page.getByRole('application', {name: 'Página remota: mouse y teclado'})).toBeVisible();
  await expect.poll(() => stream.some(d => d.t === 'ack' && d.n === 1)).toBeTruthy();
  await page.getByRole('application', {name: 'Página remota: mouse y teclado'}).click({position: {x: 50, y: 50}});
  await expect.poll(() => stream.filter(d => d.t === 'input').length).toBeGreaterThan(0);
  await expect(page.getByRole('application', {name: 'Página remota: mouse y teclado'})).toHaveCSS('cursor', 'pointer');
  const open = stream.find(d => d.t === 'open') as {window: string; width: number; height: number};
  expect(open.window).toBe('123');
  expect(open.width).toBeGreaterThanOrEqual(320);
  expect(urls[0]).toContain('pc=native-peer');
  expect(calls.some(d => d.action === 'connect' || d.action === 'start' || d.action === 'window-frame')).toBeFalsy();
  expect(calls.every(d => d.pc === 'native-peer')).toBeTruthy();
  stream.length = 0;
  await page.touchscreen.tap(500, 400);
  await expect.poll(() => stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).map(e => e.type)).toEqual(['mousePressed', 'mouseReleased']);
  stream.length = 0;
  const touch = await page.context().newCDPSession(page);
  await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: 500, y: 400}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: 500, y: 300}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: 500, y: 200}]});
  await touch.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await expect.poll(() => stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).filter(e => e.type === 'mouseWheel').length).toBeGreaterThan(0);
  expect(stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).some(e => e.type === 'mousePressed')).toBeFalsy();
  await touch.detach();
  stream.length = 0;
  const screen = page.getByRole('application', {name: 'Página remota: mouse y teclado'});
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await screen.focus();
  await screen.press('Control+c');
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('Texto remoto · ñ 🧉');
  expect(stream.filter(d => d.t === 'copy')).toHaveLength(1);
  expect(stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[]).some(e => e.key === 'c')).toBeFalsy();
  // HTTP por LAN: comprobar también la copia sin Clipboard API.
  await page.evaluate(() => navigator.clipboard.writeText('portapapeles anterior'));
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true}));
  await screen.press('Control+c');
  await expect.poll(() => stream.filter(d => d.t === 'copy').length).toBe(2);
  await expect.poll(() => page.evaluate(() => {
    Reflect.deleteProperty(navigator, 'clipboard');
    return navigator.clipboard.readText();
  })).toBe('Texto remoto · ñ 🧉');
  stream.length = 0;
  await screen.dispatchEvent('keydown', {key: 'a', code: 'KeyA', keyCode: 0, ctrlKey: true});
  await screen.dispatchEvent('keyup', {key: 'a', code: 'KeyA', keyCode: 0, ctrlKey: true});
  await screen.dispatchEvent('keydown', {key: 'ñ', keyCode: 0});
  await expect.poll(() => stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[])).toEqual([
    expect.objectContaining({kind: 'key', type: 'keyDown', keyCode: 65, modifiers: 2}),
    expect.objectContaining({kind: 'key', type: 'keyUp', keyCode: 65, modifiers: 2}),
    {kind: 'text', text: 'ñ'},
  ]);
});
