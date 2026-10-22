import {expect, test, type Page} from '@playwright/test';
import {bloquearEscrituras} from './tablero-fijo';

// La PC de Chrome se bloquea: la ventana completa no sirve (Windows no deja capturar ni mandar
// entrada) y la vista pasa sola a «Vista por pestañas» de la pestaña activa; al desbloquear vuelve.
async function lockFlow(page: Page) {
  await bloquearEscrituras(page);
  await page.route('**/auth', r => r.fulfill({json:{configured:false,authenticated:true,local:true}}));
  await page.route('**/peers', r => r.fulfill({json:[{pc_id:'flow',name:'Fixture',alive:true,local:false}]}));
  await page.route('**/browser', r => {
    const action = r.request().postDataJSON().action;
    if (action === 'windows') return r.fulfill({json:{windows:[{id:'123',title:'Pestaña activa - Google Chrome'}]}});
    if (action === 'profiles') return r.fulfill({json:{profiles:[{id:'Default',name:'Fixture'}]}});
    return r.fulfill({json:{running:true, tabs:[{id:'a',title:'Otra pestaña',url:'https://a.test/'},{id:'b',title:'Pestaña activa',url:'https://b.test/'}]}});
  });
  const commands: {t:string; desktop?:boolean}[] = [];
  let reply: (message:string) => void = () => {};
  const header = Buffer.alloc(17);
  header.writeUInt32BE(1); header.writeUInt16BE(1,8); header.writeUInt16BE(1,10);
  header.writeUInt16BE(1280,12); header.writeUInt16BE(800,14); header.writeUInt8(1,16);
  const frame = Buffer.concat([header, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4AWP4z8AAAAMBAQDbfS68AAAAAElFTkSuQmCC','base64')]);
  await page.routeWebSocket('**/browser/stream*', ws => {
    if (ws.url().includes('mode=tabs')) return;
    reply = message => ws.send(message);
    ws.onMessage(message => { const d = JSON.parse(String(message)); commands.push(d); if (d.t === 'open') ws.send(frame); });
  });
  await page.goto('/chrome');
  await expect(page.getByRole('application', {name:'Página remota: mouse y teclado'})).toBeVisible();
  const desktop = (locked: boolean) => reply(JSON.stringify({t:'desktop', locked}));
  const windowButton = page.getByRole('button', {name:'Chrome real · ventana completa', includeHidden:true});
  const tabsButton = page.getByRole('button', {name:'Vista por pestañas', includeHidden:true});
  return {commands, desktop, windowButton, tabsButton};
}

test('al bloquearse pasa a la pestaña activa con aviso y al desbloquear vuelve a la ventana', async ({page}) => {
  const {commands, desktop, windowButton, tabsButton} = await lockFlow(page);
  expect(commands.find(d => d.t === 'open')?.desktop).toBe(true);
  desktop(true);
  await expect(tabsButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('status').filter({hasText:'Fixture está bloqueada'})).toBeVisible();
  await expect(page.getByRole('tab', {name:'Pestaña activa'})).toHaveAttribute('aria-selected', 'true');
  // la ventana completa queda en espera para enterarse del desbloqueo, sin capturar
  await expect.poll(() => commands.at(-1)?.t).toBe('pause');
  const before = commands.length;
  desktop(false);
  await expect(windowButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('status').filter({hasText:'Fixture se desbloqueó'})).toBeVisible();
  // retoma la captura (al volver a verse, el visor también puede mandar su tamaño después)
  await expect.poll(() => commands.slice(before).some(d => d.t === 'resume')).toBe(true);
  await expect(page.getByRole('application', {name:'Página remota: mouse y teclado'})).toBeVisible();
});

test('si la persona elige pestañas durante el bloqueo, al desbloquear se queda ahí', async ({page}) => {
  const {desktop, windowButton, tabsButton} = await lockFlow(page);
  desktop(true);
  await expect(tabsButton).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', {name:'Quedarme en pestañas'}).click();
  desktop(false);
  await page.waitForTimeout(300);
  await expect(tabsButton).toHaveAttribute('aria-pressed', 'true');
  await expect(windowButton).toHaveAttribute('aria-pressed', 'false');
});

test('si la persona vuelve a la ventana durante el bloqueo, no se la vuelve a sacar', async ({page}) => {
  const {commands, desktop, windowButton} = await lockFlow(page);
  desktop(true);
  await expect.poll(() => commands.at(-1)?.t).toBe('pause');
  await page.getByRole('button', {name:'Controles de Chrome remoto'}).click();
  await windowButton.click();
  await expect(windowButton).toHaveAttribute('aria-pressed', 'true');
  // la imagen queda quieta hasta desbloquear: se dice, para que no parezca colgada (revisión 2026-10-22)
  await expect(page.getByRole('status').filter({hasText:'Fixture sigue bloqueada'})).toBeVisible();
  desktop(true);  // otro aviso del mismo bloqueo (p. ej. tras reconectar) no la saca de nuevo
  await page.waitForTimeout(300);
  await expect(windowButton).toHaveAttribute('aria-pressed', 'true');
});
