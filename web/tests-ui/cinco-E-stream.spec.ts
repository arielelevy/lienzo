import { test, expect, type Page } from '@playwright/test';

async function prepare(page: Page) {
  await page.route('**/auth', r => r.fulfill({ json: { configured: false, authenticated: true, local: true } }));
  await page.route('**/peers', r => r.fulfill({ json: [
    { pc_id: 'uno', name: 'Uno', alive: true, local: false },
    { pc_id: 'dos', name: 'Dos', alive: true, local: false },
  ] }));
  await page.route('**/browser', r => r.fulfill({ json: r.request().postDataJSON().action === 'windows'
    ? { windows: [{ id: '1', title: 'Ventana' }] } : { profiles: [] } }));
}
function frame() {
  const header = Buffer.alloc(17);
  header.writeUInt32BE(1); for (const offset of [8, 10, 12, 14]) header.writeUInt16BE(1, offset);
  header[16] = 1;
  return Buffer.concat([header, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4AWP4z8AAAAMBAQDbfS68AAAAAElFTkSuQmCC', 'base64')]);
}
for (const [name, message, error] of [
  ['JSON roto', '{', 'Mensaje de Chrome remoto inválido'],
  ['JSON nulo', 'null', 'Mensaje de Chrome remoto inválido'],
  ['error con mensaje inválido', '{"t":"error","message":123}', 'Mensaje de Chrome remoto inválido'],
  ['cuadro corto', Buffer.alloc(3), 'Cuadro de Chrome remoto incompleto'],
  ['dimensiones vacías', Buffer.alloc(18), 'Dimensiones de Chrome remoto inválidas'],
] as const) {
  test(`informa ${name} sin excepción sin capturar`, async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    await prepare(page);
    await page.routeWebSocket('**/browser/stream*', ws => ws.onMessage(m => {
      if (JSON.parse(String(m)).t === 'open') ws.send(message);
    }));
    await page.goto('/chrome');
    await expect(page.getByRole('alert')).toContainText(error);
    expect(errors).toEqual([]);
  });
}

test('libera bitmap decodificado después de cambiar PC sin dibujar ni acusar el cuadro viejo', async ({ page }) => {
  await prepare(page);
  await page.addInitScript(() => {
    const state = window as unknown as { release: () => void; decoding: boolean; eClosed: number; drawn: number };
    state.eClosed = 0; state.drawn = 0;
    HTMLCanvasElement.prototype.getContext = (() => ({ drawImage: () => { state.drawn++; } })) as typeof HTMLCanvasElement.prototype.getContext;
    window.createImageBitmap = (() => { state.decoding = true; return new Promise(resolve => {
      state.release = () => resolve({ close: () => { state.eClosed++; } } as ImageBitmap);
    }); }) as typeof createImageBitmap;
  });
  const acks: string[] = [];
  await page.routeWebSocket('**/browser/stream*', ws => ws.onMessage(m => {
    const data = JSON.parse(String(m));
    if (data.t === 'open' && ws.url().includes('pc=uno')) ws.send(frame());
    if (data.t === 'ack') acks.push(ws.url());
  }));
  await page.goto('/chrome?pc=uno');
  await expect.poll(() => page.evaluate(() => (window as unknown as { decoding: boolean }).decoding)).toBe(true);
  await page.getByRole('button', { name: 'Controles de Chrome remoto' }).click();
  await page.getByRole('combobox', { name: 'PC del navegador' }).selectOption('dos');
  await expect(page.getByRole('combobox', { name: 'PC del navegador' })).toHaveValue('dos');
  await page.evaluate(() => (window as unknown as { release: () => void }).release());
  await expect.poll(() => page.evaluate(() => (window as unknown as { eClosed: number }).eClosed)).toBe(1);
  expect(await page.evaluate(() => (window as unknown as { drawn: number }).drawn)).toBe(0);
  expect(acks).toEqual([]);
});
