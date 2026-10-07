/** Propuesta de aceptación: UI real, peer y Chrome simulados explícitamente. */
import { test, expect } from "@playwright/test";

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
