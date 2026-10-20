import { expect, test, type Page } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

/** Vista Aprendizaje de Memoria (Learning.tsx): reemplaza Creencias, Checklist y Patrones. Leer no
 *  escribe; veredicto y uso son POST explícitos firmados por una persona y después se vuelve a leer. */
const item = (id: string, estado: string, extra: Record<string, unknown> = {}) => ({
  creencia: id, texto: 'Creencia ' + id, accion: 'Acción ' + id, dimension: 'pruebas', estado,
  motivo: 'Motivo ' + estado, evidencia: estado === 'sin_veredicto' ? null : 'ev-' + id, excepciones: '',
  vigente_hasta: '2027-01-01T00:00:00+00:00', contexto: { tipo_trabajo: 'bugfix' },
  usos: { sirvio: 0, no_aplico: 0, ya_sabido: 0 }, revisar: false, ...extra,
});
const CHECKLIST = {
  contexto: { tipo_trabajo: 'bugfix' }, total: 1, items: [item('b1', 'aplicable')], no_aplican_total: 2,
  no_aplican: [
    item('b2', 'respaldo_caido', { cadenas: [[{ id: 'h9', texto: 'hallazgo rechazado', relacion: 'motivada_por' }]] }),
    item('b3', 'sin_veredicto'),
  ],
};
const BELIEFS = [{ id: 'b3', texto: 'Propuesta b3', estado: 'propuesta', tipo: 'decision', datos: { accion: 'Probar antes', contexto: { tipo_trabajo: 'bugfix' }, fuentes: ['h1'] } },
  { id: 'b1', texto: 'Ya vigente', estado: 'vigente', tipo: 'decision', datos: {} }];
const EVIDENCE = { total: 1, nodos: [{ id: 'ev-nueva', texto: 'Comparación revisada' }] };
const PATTERNS = { revisados: 6, sin_clasificar: 2, muestra_parcial: false, patrones: [{ contexto: { tipo_trabajo: 'bugfix' }, encargos: 4, fuentes: ['e1', 'e2'], controles_declarados: { pruebas: 4 }, controles_evidencia: [{ ejecutados: [{}], verificados: [] }, { ejecutados: [], verificados: [] }] }] };

async function prepare(page: Page, override: (path: string) => unknown = () => undefined) {
  const requests: { method: string; path: string; query: string; body: unknown }[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const url = new URL(req.url());
    requests.push({ method: req.method(), path: url.pathname, query: url.search, body: req.postDataJSON?.() ?? null });
    const path = url.pathname;
    const custom = override(path);
    const body = custom !== undefined ? custom
      : path.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }, { id: 'dos', nombre: 'Dos' }]
      : path.endsWith('/temas') ? { temas: [] }
      : path.endsWith('/checklist') ? CHECKLIST
      : path.endsWith('/creencias') ? BELIEFS
      : path.endsWith('/nodos') ? EVIDENCE
      : path.endsWith('/patrones-desarrollo') ? PATTERNS
      : req.method() === 'POST' ? { id: 'ok' }
      : { vigente: [], abierto: [], otros: [] };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  return requests;
}

test('una sola vista reemplaza creencias, checklist y patrones', async ({ page }) => {
  await prepare(page);
  for (const old of ['Creencias', 'Checklist contextual', 'Patrones de desarrollo'])
    await expect(page.getByRole('button', { name: old, exact: true })).toHaveCount(0);
});

test('consulta con contexto y muestra aplicable, por qué no aplica y cadena caída sin escribir', async ({ page }, info) => {
  const requests = await prepare(page);
  expect(requests.some(r => r.path.endsWith('/checklist'))).toBe(false);
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill(' bugfix ');
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await expect(page.getByText('Acción b1', { exact: true })).toBeVisible();
  const check = requests.find(r => r.path.endsWith('/checklist'))!;
  expect(Object.fromEntries(new URLSearchParams(check.query))).toEqual({ tipo_trabajo: 'bugfix', limite: '20' });
  await expect(page.getByText('Respaldo caído', { exact: true })).toBeVisible();
  await page.getByText('Ver evidencia · b2', { exact: true }).click();
  await expect(page.getByText('b2 → h9 (hallazgo rechazado)', { exact: true })).toBeVisible();
  await expect(page.getByText('Propuesta b3', { exact: false })).toBeVisible();
  await expect(page.getByText('Ya vigente')).toHaveCount(0);  // sólo propuestas esperan veredicto
  await expect(page.getByText('4 encargos · 4 controles declarados · 1 con evidencia de ejecución.', { exact: true })).toBeVisible();
  await page.getByRole('dialog', { name: 'Memoria del proyecto' }).screenshot({ path: info.outputPath('aprendizaje.png') });
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('uso exige nombre, firma como persona y vuelve a leer', async ({ page }) => {
  const requests = await prepare(page);
  await page.evaluate(() => { try { localStorage.removeItem('lienzo.persona'); } catch { /* */ } });
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await page.getByRole('group', { name: 'Uso de b1' }).getByRole('button', { name: 'Sirvió' }).click();
  await expect(page.getByRole('alert')).toContainText('Escribí tu nombre');
  expect(requests.some(r => r.method === 'POST')).toBe(false);
  await page.getByLabel('Tu nombre (firma veredictos y uso)').fill('Ariel');
  const reads = requests.filter(r => r.path.endsWith('/checklist')).length;
  await page.getByRole('group', { name: 'Uso de b1' }).getByRole('button', { name: 'No aplicó' }).click();
  await expect(page.getByText('Uso registrado: No aplicó.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b1/uso');
  expect(post.body).toEqual({ resultado: 'no_aplico', por: 'persona:Ariel' });
  expect(requests.filter(r => r.path.endsWith('/checklist')).length).toBe(reads + 1);
});

test('veredicto pide evidencia y motivo, y valida con vigencia', async ({ page }) => {
  const requests = await prepare(page);
  await page.getByLabel('Tu nombre (firma veredictos y uso)').fill('Ariel');
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  const save = page.getByRole('button', { name: 'Guardar veredicto de b3' });
  await expect(save).toBeDisabled();
  await page.getByLabel('Evidencia que lo sostiene').selectOption('ev-nueva');
  await page.getByLabel('Motivo').fill('comparé dos rondas');
  await save.click();
  await expect(page.getByText('Veredicto guardado.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b3/veredicto');
  const body = post.body as Record<string, string>;
  expect(body).toMatchObject({ evidencia: 'ev-nueva', resultado: 'validada', motivo: 'comparé dos rondas', por: 'persona:Ariel' });
  expect(Date.parse(body.vigente_hasta)).toBeGreaterThan(Date.now());
});

test('respuesta tardía se descarta al editar el contexto y al cambiar de proyecto', async ({ page }) => {
  await prepare(page);
  let release!: () => void;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/conocimiento/uno/checklist?**', async route => {
    await delay;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...CHECKLIST, items: [item('vieja', 'aplicable')] }) });
  });
  const req = page.waitForRequest(r => new URL(r.url()).pathname.endsWith('/checklist'));
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click(); await req;
  await page.getByLabel('Agente', { exact: true }).fill('pi');
  await expect(page.getByRole('button', { name: 'Consultar aprendizaje', exact: true })).toBeEnabled();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('dos');
  release();
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await expect(page.getByText('Acción b1', { exact: true })).toBeVisible();
  await expect(page.getByText('Acción vieja', { exact: true })).toHaveCount(0);
});

test('formato inválido o error HTTP se ven; proyecto vacío muestra vacío honesto en móvil', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let attempt = 0;
  await prepare(page, path => {
    if (!path.endsWith('/checklist')) return undefined;
    attempt++;
    return attempt === 1 ? { total: 'x' } : { contexto: {}, total: 0, items: [], no_aplican_total: 0, no_aplican: [] };
  });
  const read = page.getByRole('button', { name: 'Consultar aprendizaje', exact: true });
  await read.click(); await expect(page.getByRole('alert')).toContainText('formato esperado');
  await read.click();
  await expect(page.getByText(/Nada validado aplica a este contexto todavía/)).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  expect(await dialog.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath('aprendizaje-movil.png'), fullPage: true });
});

test('Prolog muestra cadenas y contraste sin validar ni modificar creencias', async ({ page }) => {
  await prepare(page);
  let sent: unknown;
  await page.route('**/conocimiento/uno/razonamiento', route => {
    sent = route.request().postDataJSON();
    return route.fulfill({ json: { motor: 'SWI-Prolog · WSL', snapshot: 'snapshot-prueba',
      conclusiones: [{ id: 'b1', status: 'respaldo_caido', chains: [['b1', 'h9']] }], diferencias: [] } });
  });
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill(' bugfix ');
  await page.getByRole('button', { name: 'Contrastar con Prolog' }).click();
  const result = page.getByRole('region', { name: 'Razonamiento Prolog' });
  await expect(result).toContainText('1 creencias analizadas · 0 diferencias con Python');
  await expect(result).toContainText('b1 → h9');
  expect(sent).toEqual({ contexto: { tipo_trabajo: 'bugfix' } });
  await page.getByLabel('Agente', { exact: true }).fill('codex');
  await expect(result).toHaveCount(0);
});

test('Prolog ausente se informa como error y no como resultado vacío', async ({ page }) => {
  await prepare(page);
  await page.route('**/conocimiento/uno/razonamiento', route => route.fulfill({ status: 503, json: { error: 'Prolog no disponible en WSL' } }));
  await page.getByRole('button', { name: 'Contrastar con Prolog' }).click();
  await expect(page.getByRole('alert')).toContainText('Prolog no disponible en WSL');
  await expect(page.getByRole('region', { name: 'Razonamiento Prolog' })).toHaveCount(0);
});
