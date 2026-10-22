import { expect, test, type Page } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

/** Vista Aprendizaje de Memoria (Learning.tsx). Pedido de Ariel (2026-10-22): «el aprendizaje es por
 *  proyecto». Abre mostrando todas las creencias del proyecto y las de proceso de Lienzo, con el veredicto en
 *  un clic; el contexto es un filtro opcional y plegado que se completa solo, y la IA lo puede leer de un texto
 *  libre sin guardar nada. Veredicto y uso son POST explícitos firmados por una persona y se vuelve a leer. */
const item = (id: string, estado: string, extra: Record<string, unknown> = {}) => ({
  creencia: id, texto: 'Creencia ' + id, accion: 'Acción ' + id, dimension: 'pruebas', estado,
  motivo: 'Motivo ' + estado, evidencia: estado === 'sin_veredicto' ? null : 'ev-' + id, excepciones: '',
  vigente_hasta: '2027-01-01T00:00:00+00:00', contexto: { tipo_trabajo: 'bugfix' }, alcance: 'proyecto',
  usos: { sirvio: 0, no_aplico: 0, ya_sabido: 0 }, revisar: false, ...extra,
});
const PROJECT = {
  id: 'uno',
  proyecto: { total: 3, items: [item('b3', 'sin_veredicto'), item('b1', 'vigente'), item('b9', 'refutada')] },
  lienzo: { total: 1, items: [item('p1', 'sin_veredicto', { alcance: 'proceso_lienzo', accion: 'Verificar en uso real' })] },
};
const LIENZO = {
  id: 'lienzo',
  proyecto: { total: 1, items: [item('l1', 'sin_veredicto')] },
  lienzo: { total: 1, items: [item('p1', 'vigente', { alcance: 'proceso_lienzo' })] },
};
const CHECKLIST = {
  contexto: { tipo_trabajo: 'bugfix' }, total: 1, items: [item('b1', 'aplicable')], no_aplican_total: 2,
  no_aplican: [
    item('b2', 'respaldo_caido', { cadenas: [[{ id: 'h9', texto: 'hallazgo rechazado', relacion: 'motivada_por' }]] }),
    item('b3', 'sin_veredicto'),
  ],
};
const SUGERIDO = {
  contexto: { tipo_trabajo: 'feature', tecnologia: 'react', agente: 'claude', modelo: 'claude-opus-5-5', version_agente: '2.9.1' },
  encargo: 'e1', fuente: 'encargo Q (enviado)', session_id: 'abcdef1234',
  fuentes: { tipo_trabajo: 'encargo Q (enviado)', tecnologia: 'encargo Q (enviado)', agente: 'la sesión abcdef12', modelo: 'la sesión abcdef12', version_agente: 'la sesión abcdef12' },
};
const EVIDENCE = { total: 1, nodos: [{ id: 'ev-nueva', texto: 'Comparación revisada' }] };
const PATTERNS = { revisados: 6, sin_clasificar: 2, muestra_parcial: false, patrones: [{ contexto: { tipo_trabajo: 'bugfix' }, encargos: 4, fuentes: ['e1', 'e2'], controles_declarados: { pruebas: 4 }, controles_evidencia: [{ ejecutados: [{}], verificados: [] }, { ejecutados: [], verificados: [] }] }] };

type Req = { method: string; path: string; query: string; body: unknown };
async function prepare(page: Page, override: (path: string, method: string) => unknown = () => undefined, project = 'uno') {
  const requests: Req[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const url = new URL(req.url());
    requests.push({ method: req.method(), path: url.pathname, query: url.search, body: req.postDataJSON?.() ?? null });
    const path = url.pathname;
    const custom = override(path, req.method());
    const body = custom !== undefined ? custom
      : path.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }, { id: 'dos', nombre: 'Dos' }, { id: 'lienzo', nombre: 'Lienzo' }]
      : path.endsWith('/temas') ? { temas: [] }
      : path.endsWith('/creencias-proyecto') ? (path.includes('/lienzo/') ? LIENZO : PROJECT)
      : path.endsWith('/contexto-sugerido') ? SUGERIDO
      : path.endsWith('/checklist') ? CHECKLIST
      : path.endsWith('/nodos') ? EVIDENCE
      : path.endsWith('/patrones-desarrollo') ? PATTERNS
      : req.method() === 'POST' ? { id: 'ok' }
      : { vigente: [], abierto: [], otros: [] };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption(project);
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  return requests;
}
const own = (page: Page) => page.getByRole('region', { name: 'De este proyecto' });
const proc = (page: Page) => page.getByRole('region', { name: 'De cómo se trabaja con Lienzo' });
const filter = (page: Page) => page.locator('details.knowledge-context');
const openFilter = async (page: Page) => { if (!(await filter(page).evaluate(el => (el as HTMLDetailsElement).open))) await filter(page).locator('summary').click(); };
const signed = async (page: Page) => page.getByLabel('Tu nombre (firma veredictos y uso)').fill('Ariel');

test('una sola vista reemplaza creencias, checklist y patrones', async ({ page }) => {
  await prepare(page);
  for (const old of ['Creencias', 'Checklist contextual', 'Patrones de desarrollo'])
    await expect(page.getByRole('button', { name: old, exact: true })).toHaveCount(0);
});

test('abre desde el menú sin tarjeta elegida: lo aprendido sin pedir contexto y el contexto completo plegado', async ({ page }, info) => {
  const requests = await prepare(page);
  await expect(own(page).getByText('Acción b3', { exact: true })).toBeVisible();
  await expect(own(page).getByText('3 creencias · 1 espera tu veredicto.')).toBeVisible();
  await expect(proc(page).getByText('Verificar en uso real', { exact: true })).toBeVisible();
  await expect(own(page).getByRole('group', { name: 'Veredicto de b3' }).getByRole('button', { name: 'Aceptar' })).toBeVisible();
  await expect(own(page).getByRole('group', { name: 'Veredicto de b1' }).getByRole('button', { name: 'Renovar' })).toBeVisible();
  await expect(own(page).getByRole('group', { name: 'Veredicto de b9' })).toHaveCount(0);  // refutada: no se revisa
  await expect(page.getByText('Patrones de trabajo', { exact: true })).toBeVisible();
  // sin pedir contexto: no se consultó el checklist; el contexto sugerido, sin sesión elegida
  expect(requests.filter(r => r.path.endsWith('/checklist'))).toHaveLength(0);
  const sug = requests.find(r => r.path.endsWith('/contexto-sugerido'))!;
  expect(sug.query).toBe('');
  // plegado, pero con el contexto completo a la vista y de dónde salió cada dato al abrirlo
  await expect(filter(page)).not.toHaveAttribute('open', '');
  await expect(filter(page).locator('summary')).toContainText('Tipo de trabajo: feature · Tecnología: react · Agente: claude · Modelo: claude-opus-5-5 · Versión del agente: 2.9.1');
  await expect(filter(page).locator('summary')).toContainText('completado desde encargo Q (enviado)');
  await openFilter(page);
  await expect(page.getByLabel('Versión del agente', { exact: true })).toHaveValue('2.9.1');
  await expect(filter(page).getByText('de la sesión abcdef12').first()).toBeVisible();
  await expect(filter(page).getByText('de encargo Q (enviado)').first()).toBeVisible();
  await page.getByRole('dialog', { name: 'Memoria del proyecto' }).screenshot({ path: info.outputPath('aprendizaje.png') });
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('aceptar en un clic exige nombre, firma como persona y vuelve a leer', async ({ page }) => {
  const requests = await prepare(page);
  await page.evaluate(() => { try { localStorage.removeItem('lienzo.persona'); } catch { /* */ } });
  await page.getByLabel('Tu nombre (firma veredictos y uso)').fill('');
  await own(page).getByRole('group', { name: 'Veredicto de b3' }).getByRole('button', { name: 'Aceptar' }).click();
  await expect(page.getByRole('alert')).toContainText('Escribí tu nombre');
  expect(requests.some(r => r.method === 'POST')).toBe(false);
  await signed(page);
  const reads = requests.filter(r => r.path.endsWith('/creencias-proyecto')).length;
  await own(page).getByRole('group', { name: 'Veredicto de b3' }).getByRole('button', { name: 'Aceptar' }).click();
  await expect(page.getByText('Aceptada: ya cuenta como vigente.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b3/revision');
  expect(post.body).toEqual({ accion: 'aceptar', por: 'persona:Ariel' });
  expect(requests.filter(r => r.path.endsWith('/creencias-proyecto')).length).toBe(reads + 1);
});

test('rechazar una de proceso de Lienzo va al proyecto lienzo', async ({ page }) => {
  const requests = await prepare(page);
  await signed(page);
  await proc(page).getByRole('group', { name: 'Veredicto de p1' }).getByRole('button', { name: 'Rechazar' }).click();
  await expect(page.getByText('Rechazada: deja de aplicar.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/lienzo/creencias/p1/revision');
  expect(post.body).toEqual({ accion: 'rechazar', por: 'persona:Ariel' });
  await expect(proc(page).getByRole('button', { name: 'Pasar a este proyecto' })).toHaveCount(0);  // el alcance se cambia en lienzo
});

test('corregir abre el texto, guarda la versión nueva y no cambia el alcance fuera de lienzo', async ({ page }) => {
  const requests = await prepare(page);
  await signed(page);
  await own(page).getByRole('group', { name: 'Veredicto de b3' }).getByRole('button', { name: 'Corregir' }).click();
  const card = own(page).getByRole('listitem').filter({ hasText: 'Acción b3' });
  await expect(card.getByLabel('Alcance')).toHaveCount(0);
  await card.getByLabel('Qué hay que hacer').fill('Diagnosticar y medir antes de corregir');
  await card.getByRole('button', { name: 'Guardar corrección' }).click();
  await expect(page.getByText(/Corregida: la nueva versión quedó vigente/)).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b3/revision');
  expect(post.body).toEqual({ accion: 'corregir', accion_nueva: 'Diagnosticar y medir antes de corregir', por: 'persona:Ariel' });
});

test('en lienzo se ven los dos bloques marcados y se cambia el alcance sin recrear', async ({ page }) => {
  const requests = await prepare(page, () => undefined, 'lienzo');
  await signed(page);
  await expect(own(page).getByText(/Contexto: .*de este proyecto/)).toBeVisible();
  await expect(proc(page).getByText(/Contexto: .*proceso de Lienzo/)).toBeVisible();
  await own(page).getByRole('group', { name: 'Veredicto de l1' }).getByRole('button', { name: 'Pasar a proceso de Lienzo' }).click();
  await expect(page.getByText('Ahora vale para todos los proyectos.', { exact: true })).toBeVisible();
  let post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/lienzo/creencias/l1/alcance');
  expect(post.body).toEqual({ alcance: 'proceso_lienzo', por: 'persona:Ariel' });
  // corregir en lienzo deja elegir el alcance
  await proc(page).getByRole('group', { name: 'Veredicto de p1' }).getByRole('button', { name: 'Corregir' }).click();
  const card = proc(page).getByRole('listitem').filter({ hasText: 'Acción p1' });
  await card.getByLabel('Alcance').selectOption('proyecto');
  await card.getByRole('button', { name: 'Guardar corrección' }).click();
  await expect(page.getByText(/Corregida/)).toBeVisible();
  post = requests.filter(r => r.method === 'POST').at(-1)!;
  expect(post.body).toEqual({ accion: 'corregir', accion_nueva: 'Acción p1', alcance: 'proyecto', por: 'persona:Ariel' });
});

test('el filtro consulta con contexto y muestra aplicable, por qué no aplica y cadena caída sin escribir', async ({ page }) => {
  const requests = await prepare(page);
  await openFilter(page);
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill(' bugfix ');
  for (const key of ['Tecnología', 'Agente', 'Modelo', 'Versión del agente']) await page.getByLabel(key, { exact: true }).fill('');
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  const applies = page.getByRole('region', { name: 'Aplica a lo que vas a hacer' });
  await expect(applies.getByText('Acción b1', { exact: true })).toBeVisible();
  const check = requests.filter(r => r.path.endsWith('/checklist')).at(-1)!;
  expect(Object.fromEntries(new URLSearchParams(check.query))).toEqual({ tipo_trabajo: 'bugfix', limite: '20' });
  await expect(page.getByRole('heading', { name: 'No aplica, y por qué', exact: true }).locator('..').getByText('Respaldo caído', { exact: true })).toBeVisible();
  await page.getByText('Ver evidencia · b2', { exact: true }).click();
  await expect(page.getByText('b2 → h9 (hallazgo rechazado)', { exact: true })).toBeVisible();
  await expect(page.getByText('4 encargos · 4 controles declarados · 1 con evidencia de ejecución.', { exact: true })).toBeVisible();
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('uso desde el filtro firma como persona y vuelve a leer el filtro', async ({ page }) => {
  const requests = await prepare(page);
  await signed(page);
  await openFilter(page);
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  await expect.poll(() => requests.filter(r => r.path.endsWith('/checklist')).length).toBe(1);
  await page.getByRole('group', { name: 'Uso de b1' }).getByRole('button', { name: 'No aplicó' }).click();
  await expect(page.getByText('Uso registrado: No aplicó.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b1/uso');
  expect(post.body).toEqual({ resultado: 'no_aplico', por: 'persona:Ariel' });
  await expect.poll(() => requests.filter(r => r.path.endsWith('/checklist')).length).toBe(2);
});

test('la IA completa los campos desde el texto libre sin consultar ni guardar', async ({ page }) => {
  let sent: unknown;
  const requests = await prepare(page);
  await page.route('**/conocimiento/uno/interpretar-contexto', route => {
    sent = route.request().postDataJSON();
    return route.fulfill({ json: { contexto: { tipo_trabajo: 'bugfix', area: 'aprendizaje' }, descartados: { fase: 'cerca del final' }, via: 'claude' } });
  });
  await openFilter(page);
  const ask = page.getByRole('button', { name: 'Completar con IA' });
  await expect(ask).toBeDisabled();
  await page.getByLabel('¿Qué vas a hacer? (texto libre)').fill('Arreglar el filtro de la pestaña de aprendizaje');
  await ask.click();
  await expect(page.getByLabel('Tipo de trabajo', { exact: true })).toHaveValue('bugfix');
  await expect(page.getByLabel('Área', { exact: true })).toHaveValue('aprendizaje');
  await expect(page.getByLabel('Tecnología', { exact: true })).toHaveValue('react');  // lo que no propuso queda
  await expect(page.getByText(/La IA completó 2 campos\. Revisalos y consultá; no se guardó nada\. Descartó fase/)).toBeVisible();
  await expect(filter(page).getByText('de la IA (Claude), desde tu texto').first()).toBeVisible();
  expect(sent).toEqual({ texto: 'Arreglar el filtro de la pestaña de aprendizaje' });
  expect(requests.filter(r => r.path.endsWith('/checklist'))).toHaveLength(0);
});

test('si la IA no responde se dice y los campos quedan para completar a mano', async ({ page }) => {
  await prepare(page);
  await page.route('**/conocimiento/uno/interpretar-contexto', route => route.fulfill({ status: 504, json: { error: 'la IA no respondió en 45 s: completá los campos a mano', contexto: {} } }));
  await openFilter(page);
  await page.getByLabel('¿Qué vas a hacer? (texto libre)').fill('algo');
  await page.getByRole('button', { name: 'Completar con IA' }).click();
  await expect(page.getByRole('alert')).toContainText('completá los campos a mano');
  await expect(page.getByLabel('Tipo de trabajo', { exact: true })).toHaveValue('feature');
  await expect(page.getByLabel('Tipo de trabajo', { exact: true })).toBeEditable();
});

test('veredicto con una evidencia registrada sigue disponible y valida con vigencia', async ({ page }) => {
  const requests = await prepare(page);
  await signed(page);
  const card = own(page).getByRole('listitem').filter({ hasText: 'Acción b3' });
  await card.getByText('Veredicto con una evidencia registrada').click();
  const save = card.getByRole('button', { name: 'Guardar veredicto de b3' });
  await expect(save).toBeDisabled();
  await card.getByLabel('Evidencia que lo sostiene').selectOption('ev-nueva');
  await card.getByLabel('Motivo').fill('comparé dos rondas');
  await save.click();
  await expect(page.getByText('Veredicto guardado.', { exact: true })).toBeVisible();
  const post = requests.find(r => r.method === 'POST')!;
  expect(post.path).toBe('/conocimiento/uno/creencias/b3/veredicto');
  const body = post.body as Record<string, string>;
  expect(body).toMatchObject({ evidencia: 'ev-nueva', resultado: 'validada', motivo: 'comparé dos rondas', por: 'persona:Ariel' });
  expect(Date.parse(body.vigente_hasta)).toBeGreaterThan(Date.now());
});

test('respuesta tardía del filtro se descarta al editar el contexto y al cambiar de proyecto', async ({ page }) => {
  await prepare(page);
  let release!: () => void;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/conocimiento/uno/checklist?**', async route => {
    await delay;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...CHECKLIST, items: [item('vieja', 'aplicable')] }) });
  });
  await openFilter(page);
  const req = page.waitForRequest(r => new URL(r.url()).pathname.endsWith('/checklist'));
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click(); await req;
  await page.getByLabel('Agente', { exact: true }).fill('pi');
  await expect(page.getByRole('button', { name: 'Ver qué aplica', exact: true })).toBeEnabled();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('dos');
  release();
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await openFilter(page);
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Aplica a lo que vas a hacer' }).getByText('Acción b1', { exact: true })).toBeVisible();
  await expect(page.getByText('Acción vieja', { exact: true })).toHaveCount(0);
});

test('formato inválido o error HTTP se ven; proyecto vacío muestra vacío honesto en móvil', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  // en desarrollo React monta dos veces: el formato roto va por proyecto, no por intento
  await prepare(page, path => {
    if (!path.endsWith('/creencias-proyecto')) return undefined;
    return path.includes('/uno/') ? { proyecto: { total: 'x' } } : { id: 'dos', proyecto: { total: 0, items: [] }, lienzo: { total: 0, items: [] } };
  });
  await expect(page.getByRole('alert')).toContainText('formato esperado');  // la lectura al abrir
  await page.getByLabel('Proyecto', { exact: true }).selectOption('dos');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByText(/todavía no tiene creencias propias/)).toBeVisible();
  await expect(page.getByText(/Todavía no hay creencias de proceso de Lienzo/)).toBeVisible();
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
  await openFilter(page);
  for (const key of ['Tecnología', 'Agente', 'Modelo', 'Versión del agente']) await page.getByLabel(key, { exact: true }).fill('');
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
  await openFilter(page);
  await page.getByRole('button', { name: 'Contrastar con Prolog' }).click();
  await expect(page.getByRole('alert')).toContainText('Prolog no disponible en WSL');
  await expect(page.getByRole('region', { name: 'Razonamiento Prolog' })).toHaveCount(0);
});

// revisión V (2026-10-22): V-4, el motor se ve al abrir; V-5, el proceso de Lienzo entra en el filtro
test('al abrir se distingue lo que el motor sostuvo, contradijo o no pudo contrastar, aparte del veredicto', async ({ page }) => {
  const vista = {
    id: 'uno', lienzo: { total: 0, items: [] },
    proyecto: { total: 4, items: [
      item('s1', 'sin_veredicto', { contraste: { resultado: 'sostenida', fecha: '2026-10-22T20:00:00Z' }, reglas_cuestionadas: [] }),
      item('c1', 'sin_veredicto', { contraste: { resultado: 'contradice', observaciones: ['contradice'], fecha: '2026-10-22T20:00:00Z' }, reglas_cuestionadas: [] }),
      item('m1', 'sin_veredicto', { contraste: { resultado: 'sin_motor', motivo: 'WSL no respondió', fecha: '2026-10-22T20:00:00Z' }, reglas_cuestionadas: [] }),
      item('v1', 'vigente', { reglas_cuestionadas: ['r9abcdef00'] }),
    ] },
  };
  await prepare(page, path => path.endsWith('/creencias-proyecto') ? vista : undefined);
  const card = (id: string) => own(page).getByRole('listitem').filter({ hasText: 'Acción ' + id });
  await expect(card('s1')).toContainText('Motor lógico: la sostuvo (contraste del 2026-10-22)');
  await expect(card('c1')).toContainText('Motor lógico: contradice una decisión vigente (contraste del 2026-10-22)');
  await expect(card('m1')).toContainText('Motor lógico: no se pudo contrastar: WSL no respondió (2026-10-22)');
  await expect(card('v1')).toContainText('Cuestionada: la regla r9abcdef derivada de ella quedó cuestionada');
  await expect(card('v1').getByText('Vigente', { exact: true })).toBeVisible();  // el veredicto humano sigue a la vista
  await expect(card('c1').getByRole('button', { name: 'Aceptar' })).toBeVisible();  // decide la persona
});

test('el filtro trae las de proceso de Lienzo marcadas y su uso se registra en lienzo', async ({ page }) => {
  const check = { ...CHECKLIST, items: [item('b1', 'aplicable', { proyecto: 'uno' }), item('p1', 'aplicable', { proyecto: 'lienzo', alcance: 'proceso_lienzo' })], total: 2,
    motor_proceso: { estado: 'no_disponible', error: 'Motor lógico no encontrado' } };
  const requests = await prepare(page, path => path.endsWith('/checklist') ? check : undefined);
  await signed(page);
  await openFilter(page);
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  const applies = page.getByRole('region', { name: 'Aplica a lo que vas a hacer' });
  await expect(applies.getByRole('listitem').filter({ hasText: 'Acción p1' })).toContainText('De cómo se trabaja con Lienzo');
  await expect(applies).toContainText('Proceso de Lienzo: El motor lógico no respondió');
  await page.getByRole('group', { name: 'Uso de p1' }).getByRole('button', { name: 'Sirvió' }).click();
  await expect(page.getByText('Uso registrado: Sirvió.', { exact: true })).toBeVisible();
  expect(requests.find(r => r.method === 'POST')!.path).toBe('/conocimiento/lienzo/creencias/p1/uso');
});
