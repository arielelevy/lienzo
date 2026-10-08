/** Propuesta de aceptación: UI real, peer y Chrome simulados explícitamente. */
import { test, expect } from "@playwright/test";
test.use({hasTouch: true});

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
  await screen.dispatchEvent('keydown', {key: 'a', code: 'KeyA', keyCode: 0, ctrlKey: true});
  await screen.dispatchEvent('keyup', {key: 'a', code: 'KeyA', keyCode: 0, ctrlKey: true});
  await screen.dispatchEvent('keydown', {key: 'ñ', keyCode: 0});
  await expect.poll(() => stream.filter(d => d.t === 'input').flatMap(d => d.events as Record<string, unknown>[])).toEqual([
    expect.objectContaining({kind: 'key', type: 'keyDown', keyCode: 65, modifiers: 2}),
    expect.objectContaining({kind: 'key', type: 'keyUp', keyCode: 65, modifiers: 2}),
    {kind: 'text', text: 'ñ'},
  ]);
});
