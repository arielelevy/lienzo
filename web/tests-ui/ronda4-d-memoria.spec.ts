import { expect, test, type Page } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

async function prepare(page: Page) {
  const requests: string[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    requests.push(req.method() + ' ' + new URL(req.url()).pathname);
    const path = new URL(req.url()).pathname;
    const body = path.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }, { id: 'dos', nombre: 'Dos' }]
      : path.endsWith('/temas') ? { temas: [] }
      : path.endsWith('/creencias') ? [{ id: 'b1', texto: 'Propuesta sin promover', tipo: 'decision', estado: 'propuesto', datos: { resultado: 'pendiente', evidencia: ['e1'], contexto: { agente: 'codex' } }, origen: { informe: 'informe-1' } }]
      : path.endsWith('/checklist') ? { contexto: { agente: 'codex' }, total: 21, items: [{ creencia: 'b2', accion: 'Verificar el respaldo antes de aplicar', evidencia: 'e-validada', dimension: 'pruebas', excepciones: ['Sin servidor'], vigente_hasta: '2027-01-01T00:00:00Z' }] }
      : path.endsWith('/patrones-desarrollo') ? { revisados: 500, sin_clasificar: 9, muestra_parcial: true, patrones: [{ contexto: { tipo_trabajo: 'bugfix' }, encargos: 2, fuentes: ['encargo-1'], controles_declarados: { pruebas: 2 }, controles_evidencia: [{ estado: 'desconocido', evidencia: 'Sin ejecución acreditada' }], calidad: 'no inferida' }] }
      : { vigente: [], abierto: [], otros: [] };
    return route.fulfill({ status: req.method() === 'GET' ? 200 : 403, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  return requests;
}

test('creencias conserva propuesta, estado y respaldo sin escrituras', async ({ page }) => {
  const requests = await prepare(page);
  await page.getByRole('button', { name: 'Creencias', exact: true }).click();
  expect(requests.some(r => r.endsWith('/creencias'))).toBe(false);
  await page.getByRole('button', { name: 'Leer creencias', exact: true }).click();
  await expect(page.getByText('Propuesta sin promover', { exact: true })).toBeVisible();
  await expect(page.getByText('propuesto', { exact: true })).toBeVisible();
  await page.getByText('Origen y respaldo · b1', { exact: true }).click();
  await expect(page.getByText('informe-1', { exact: true })).toBeVisible();
  await expect(page.getByText('e1', { exact: true })).toBeVisible();
  expect(requests.every(r => r.startsWith('GET '))).toBe(true);
});

test('checklist envía contexto exacto y muestra vigencia, excepciones y recorte', async ({ page }) => {
  const requests = await prepare(page);
  await page.getByRole('button', { name: 'Checklist contextual', exact: true }).click();
  await page.getByLabel('Agente', { exact: true }).fill(' codex ');
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill('bugfix');
  await page.getByLabel('Tecnología', { exact: true }).fill('React');
  const req = page.waitForRequest(r => new URL(r.url()).pathname.endsWith('/checklist'));
  await page.getByRole('button', { name: 'Consultar checklist', exact: true }).click();
  const params = new URL((await req).url()).searchParams;
  expect(Object.fromEntries(params)).toEqual({ agente: 'codex', tipo_trabajo: 'bugfix', tecnologia: 'React', limite: '20' });
  await expect(page.getByText('21 acciones aplicables; mostrando 1.', { exact: true })).toBeVisible();
  await page.getByText('Origen y respaldo · b2', { exact: true }).click();
  await expect(page.getByText('e-validada', { exact: true })).toBeVisible();
  await expect(page.getByText('Sin servidor', { exact: true })).toBeVisible();
  await expect(page.getByText('2027-01-01T00:00:00Z', { exact: true })).toBeVisible();
  expect(requests.every(r => r.startsWith('GET '))).toBe(true);
});

test('checklist descarta respuesta tardía al editar contexto y al cambiar proyecto', async ({ page }) => {
  await prepare(page);
  let release!: () => void;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/conocimiento/uno/checklist?**', async route => {
    await delay;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ contexto: {}, total: 1, items: [{ creencia: 'vieja', accion: 'Respuesta antigua', evidencia: 'e', vigente_hasta: '2027-01-01T00:00:00Z' }] }) });
  });
  await page.getByRole('button', { name: 'Checklist contextual', exact: true }).click();
  const req = page.waitForRequest(r => new URL(r.url()).pathname.endsWith('/checklist'));
  await page.getByRole('button', { name: 'Consultar checklist', exact: true }).click(); await req;
  await page.getByLabel('Agente', { exact: true }).fill('pi');
  await expect(page.getByRole('button', { name: 'Consultar checklist', exact: true })).toBeEnabled();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('dos');
  release();
  await page.getByRole('button', { name: 'Checklist contextual', exact: true }).click();
  await page.getByRole('button', { name: 'Consultar checklist', exact: true }).click();
  await expect(page.getByText('Verificar el respaldo antes de aplicar', { exact: true })).toBeVisible();
  await expect(page.getByText('Respuesta antigua', { exact: true })).toHaveCount(0);
});

test('patrones conserva muestra parcial y evidencia en móvil con foco contenido', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await prepare(page);
  await page.getByRole('button', { name: 'Patrones de desarrollo', exact: true }).click();
  await page.getByRole('button', { name: 'Consultar patrones', exact: true }).click();
  await expect(page.getByText('500 encargos revisados · 9 sin clasificar.', { exact: true })).toBeVisible();
  await expect(page.getByText(/Muestra parcial:/)).toBeVisible();
  await expect(page.getByText('encargo-1', { exact: true })).toBeVisible();
  await expect(page.getByText('Sin ejecución acreditada', { exact: true })).toBeVisible();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  expect(await dialog.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole('button', { name: 'Cerrar memoria' }).focus();
  await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  await page.screenshot({ path: info.outputPath('patrones-movil.png') });
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(requests.every(r => r.startsWith('GET '))).toBe(true);
});

test('creencias inválidas y error HTTP visibles; nueva consulta vacía recupera', async ({ page }) => {
  await prepare(page);
  let attempt = 0;
  await page.route('**/conocimiento/uno/creencias?**', route => {
    attempt++;
    return route.fulfill({ status: attempt === 2 ? 503 : 200, contentType: 'application/json', body: JSON.stringify(attempt === 1 ? {} : attempt === 2 ? { error: 'memoria no disponible' } : []) });
  });
  await page.getByRole('button', { name: 'Creencias', exact: true }).click();
  const read = page.getByRole('button', { name: 'Leer creencias', exact: true });
  await read.click(); await expect(page.getByRole('alert')).toContainText('formato esperado');
  await read.click(); await expect(page.getByRole('alert')).toContainText('memoria no disponible');
  await read.click(); await expect(page.getByText('No hay creencias registradas en este proyecto.', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
