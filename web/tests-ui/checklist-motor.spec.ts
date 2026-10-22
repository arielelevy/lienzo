import { expect, test, type Page } from '@playwright/test';
import { BASE, SID, bloquearEscrituras, instalarTablero } from './tablero-fijo';

/** Checklist sostenido por el motor lógico y tira de aprendizaje (encargo J, 2026-10-22), con
 *  fixtures: la aplicable muestra la prueba del motor, lo cuestionado va aparte con su regla, sin
 *  motor se dice que no hubo contraste, y la tira abre la memoria del proyecto en Aprendizaje. */
const leaf = (pred: string, args: unknown[]) => ({ by: 'given', fact: { pred, args }, sources: ['grafo'] });
const proof = (pred: string, rule: string, args: unknown[]) => ({ prueba: { by: 'rule', rule, fact: { pred, args }, premises: [leaf('ctx_ok', args)] }, fuentes: ['grafo'], prueba_truncada: false });
const item = (id: string, estado: string, extra: Record<string, unknown> = {}) => ({
  creencia: id, texto: 'Creencia ' + id, accion: 'Acción ' + id, dimension: 'pruebas', estado,
  motivo: 'Motivo ' + estado, evidencia: 'ev-' + id, excepciones: '', vigente_hasta: '2027-01-01T00:00:00+00:00',
  contexto: { tipo_trabajo: 'bugfix' }, usos: { sirvio: 0, no_aplico: 0, ya_sabido: 0 }, revisar: false, ...extra,
});
const SOSTENIDO = {
  contexto: { tipo_trabajo: 'bugfix' }, total: 1, items: [item('b1', 'aplicable', { sostenida: proof('sostenida', 'sostenida', ['b1']) })],
  no_aplican_total: 1, no_aplican: [item('b3', 'vencida')],
  motor: { estado: 'sostenido', motor: { name: 'motor-logico', version: '0.2.0' }, program_hash: 'sha256:x', hechos: 40, diferencias: [] },
  cuestionadas_total: 1,
  cuestionadas: [item('b2', 'cuestionada', { motivo: 'Una regla que deriva de ella quedó cuestionada', cuestionada_por: [{ regla: 'r9abcdef00', ...proof('cuestionada', 'cuestionada_directa', ['b2', 'r9abcdef00']) }] })],
};
const SIN_MOTOR = {
  ...SOSTENIDO, items: [item('b1', 'aplicable', { sostenida: null })], cuestionadas_total: 0, cuestionadas: [],
  motor: { estado: 'no_disponible', error: 'Motor lógico no encontrado' },
};
const RESUMEN = [{ proyecto: 'dos', nombre: 'Dos', creencias: { propuesta: 2, vigente: 1 }, reglas_cuestionadas: 1, encargos_clasificados: 3, encargos_sin_clasificar: 1 },
  { proyecto: 'nada', nombre: 'Nada', creencias: { revertida: 1 }, reglas_cuestionadas: 0, encargos_clasificados: 2, encargos_sin_clasificar: 0 }];

const SUGERIDO = { contexto: { tipo_trabajo: 'bugfix', agente: 'claude' }, encargo: 'e1', fuente: 'encargo B (enviado)', fuentes: { tipo_trabajo: 'encargo B (enviado)', agente: 'la sesión 0000aaaa' } };
// la vista del proyecto (encargo Q): todas sus creencias sin contexto; las de proceso de Lienzo, aparte
const VISTA = { id: 'dos', proyecto: { total: 3, items: [item('b4', 'sin_veredicto'), item('b1', 'vigente'), item('b3', 'vencida')] }, lienzo: { total: 0, items: [] } };
const VACIA = { id: 'uno', proyecto: { total: 0, items: [] }, lienzo: { total: 0, items: [] } };
const NADA = { contexto: { tipo_trabajo: 'bugfix' }, total: 0, items: [], no_aplican_total: 0, no_aplican: [], motor: { estado: 'sin_creencias' }, cuestionadas_total: 0, cuestionadas: [] };

async function prepare(page: Page, checklist: unknown = SOSTENIDO, sugerido: unknown = { contexto: {}, encargo: null, fuente: null }, vista: unknown = VISTA) {
  const requests: { method: string; path: string; query: string }[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const url = new URL(req.url()), path = url.pathname;
    requests.push({ method: req.method(), path, query: url.search });
    const body = path.endsWith('/aprendizaje-resumen') ? RESUMEN
      : path.endsWith('/contexto-sugerido') ? sugerido
      : path.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }, { id: 'dos', nombre: 'Dos' }]
      : path.endsWith('/temas') ? { temas: [] }
      : path.endsWith('/checklist') ? checklist
      : path.endsWith('/creencias-proyecto') ? vista
      : path.endsWith('/nodos') ? { total: 0, nodos: [] }
      : path.endsWith('/patrones-desarrollo') ? { revisados: 0, sin_clasificar: 0, muestra_parcial: false, patrones: [] }
      : { vigente: [], abierto: [], otros: [] };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  return requests;
}

/** El checklist es un filtro opcional y plegado (encargo Q): se despliega, se completa y se consulta. */
async function consultar(page: Page) {
  await page.getByText(/^Filtrar por lo que vas a hacer/).click();
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill('bugfix');
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
}

test('la tira muestra sólo proyectos con algo para mirar y abre su memoria en Aprendizaje', async ({ page }) => {
  const requests = await prepare(page);
  const tira = page.getByRole('list', { name: 'aprendizaje por proyecto' });
  await expect(tira.getByRole('button')).toHaveCount(1);  // «Nada» sólo tiene una refutada
  const chip = tira.getByRole('button', { name: /Dos/ });
  await expect(chip).toContainText('2 por validar · 1 vigente · 1 regla cuestionada');
  await chip.click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  await expect(dialog.getByLabel('Proyecto', { exact: true })).toHaveValue('dos');
  await expect(dialog.getByRole('button', { name: 'Aprendizaje', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByRole('heading', { name: 'Aprendizaje', exact: true })).toBeVisible();
  // cerrar y abrir desde el menú: sin proyecto elegido, como siempre
  await dialog.getByRole('button', { name: 'Cerrar memoria' }).click();
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await expect(page.getByLabel('Proyecto', { exact: true })).toHaveValue('');
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('la aplicable trae la prueba del motor y la cuestionada va aparte con su regla', async ({ page }, info) => {
  const requests = await prepare(page);
  await page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Dos/ }).click();
  await consultar(page);
  await expect(page.getByText('Cada aplicable está sostenida por el motor lógico, con su prueba. motor-logico 0.2.0')).toBeVisible();
  await page.getByText('Sostenida por el motor lógico: ver la prueba', { exact: true }).click();
  await expect(page.getByText(/^sostenida\(b1\) · regla sostenida/).first()).toBeVisible();
  const cuestionadas = page.getByRole('heading', { name: 'Cuestionadas', exact: true }).locator('..');
  await expect(cuestionadas.getByText('Acción b2', { exact: true })).toBeVisible();
  await cuestionadas.getByText('Regla cuestionada r9abcdef: ver la prueba', { exact: true }).click();
  await expect(cuestionadas.getByText(/^cuestionada\(b2, r9abcdef00\) · regla cuestionada_directa/).first()).toBeVisible();
  // la cuestionada no se repite entre las que no aplican
  const noAplican = page.getByRole('heading', { name: 'No aplica, y por qué', exact: true }).locator('..');
  await expect(noAplican.getByText('Acción b2', { exact: true })).toHaveCount(0);
  await expect(noAplican.getByText('Acción b3', { exact: true })).toBeVisible();
  await page.getByRole('dialog', { name: 'Memoria del proyecto' }).screenshot({ path: info.outputPath('checklist-motor.png') });
  expect(requests.filter(r => r.path.endsWith('/checklist')).length).toBe(1);  // sólo la del botón: abrir no lo pide
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('sin motor la aplicable se muestra y dice que no tuvo contraste', async ({ page }) => {
  await prepare(page, SIN_MOTOR);
  await page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Dos/ }).click();
  await consultar(page);
  await expect(page.getByRole('region', { name: 'Aplica a lo que vas a hacer' }).getByText('Acción b1', { exact: true })).toBeVisible();
  await expect(page.getByText('El motor lógico no respondió: las aplicables se muestran sin contraste. (Motor lógico no encontrado)')).toBeVisible();
  await expect(page.getByText('Sin contraste del motor lógico.', { exact: true })).toBeVisible();
  await expect(page.getByText('Sostenida por el motor lógico: ver la prueba')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Cuestionadas', exact: true })).toHaveCount(0);
});

test('un checklist viejo sin datos del motor se sigue leyendo', async ({ page }) => {
  const { motor: _m, cuestionadas: _c, cuestionadas_total: _t, ...viejo } = SOSTENIDO;
  await prepare(page, { ...viejo, items: [item('b1', 'aplicable')] });
  await page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Dos/ }).click();
  await consultar(page);
  await expect(page.getByRole('region', { name: 'Aplica a lo que vas a hacer' }).getByText('Acción b1', { exact: true })).toBeVisible();
  await expect(page.getByText('Sin contraste del motor lógico.')).toHaveCount(0);
});

test('sin resumen válido la tira no aparece', async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/aprendizaje-resumen', route => route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"x"}' }));
  await page.goto(BASE);
  await expect(page.getByRole('list', { name: 'aprendizaje por proyecto' })).toHaveCount(0);
});


test('si hay más cuestionadas que las mostradas lo dice', async ({ page }) => {
  await prepare(page, { ...SOSTENIDO, cuestionadas_total: 70 });
  await page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Dos/ }).click();
  await consultar(page);
  await expect(page.getByText('Se muestran 1 de 70.', { exact: true })).toBeVisible();
});

test('abre con lo aprendido del proyecto y el contexto de la tarjeta elegida plegado en el filtro', async ({ page }, info) => {
  const requests = await prepare(page, SOSTENIDO, SUGERIDO);
  await page.locator(`.card[data-sid="${SID.coordinadora}"]`).click();
  await expect(page.locator('.card.picked')).toHaveAttribute('data-sid', SID.coordinadora);
  await page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Dos/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  await expect(dialog.getByText('Lo que aprendió este proyecto.', { exact: true })).toBeVisible();
  const own = dialog.getByRole('region', { name: 'De este proyecto' });
  await expect(own.getByText('Espera tu veredicto', { exact: true })).toBeVisible();
  await expect(own.getByText('Vigente', { exact: true })).toBeVisible();
  await expect(own.getByText('Vencida', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Filtrar por lo que vas a hacer (opcional) · Tipo de trabajo: bugfix · Agente: claude · completado desde encargo B (enviado)')).toBeVisible();
  await expect(dialog.getByLabel('Tipo de trabajo', { exact: true })).toBeHidden();  // el filtro queda plegado
  const sug = requests.find(r => r.path.endsWith('/contexto-sugerido'))!;
  expect(new URLSearchParams(sug.query).get('session_id')).toBe(SID.coordinadora);
  expect(requests.filter(r => r.path.endsWith('/checklist'))).toHaveLength(0);  // abrir no pide contexto
  await dialog.screenshot({ path: info.outputPath('aprendizaje-abre-solo.png') });
  // desplegar el filtro: el contexto sugerido ya está, se edita y se consulta
  await dialog.getByText(/^Filtrar por lo que vas a hacer/).click();
  await expect(dialog.getByText('de la sesión 0000aaaa')).toBeVisible();
  await dialog.getByLabel('Tipo de trabajo', { exact: true }).fill('refactor');
  await expect(dialog.getByText(/^Filtrar por lo que vas a hacer \(opcional\) · Tipo de trabajo: refactor · Agente: claude$/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  await expect.poll(() => requests.filter(r => r.path.endsWith('/checklist')).at(-1)?.query).toContain('tipo_trabajo=refactor');
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('un proyecto sin creencias abre explicando de dónde salen', async ({ page }) => {
  const requests = await prepare(page, NADA, undefined, VACIA);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByRole('region', { name: 'De este proyecto' })).toContainText('Este proyecto todavía no tiene creencias propias');
  await page.getByText(/^Filtrar por lo que vas a hacer/).click();
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  await expect(page.getByText('No hay creencias que contrastar.')).toBeVisible();
  const sug = requests.find(r => r.path.endsWith('/contexto-sugerido'))!;
  expect(sug.query).toBe('');  // sin tarjeta elegida no se manda sesión
});

test('una sugerencia tardía no pisa lo que la persona ya escribió', async ({ page }) => {
  const requests = await prepare(page, NADA, undefined, VACIA);
  let release!: () => void;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/conocimiento/uno/contexto-sugerido**', async route => {
    await delay;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(SUGERIDO) }).catch(() => undefined);
  });
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await page.getByText(/^Filtrar por lo que vas a hacer/).click();  // mientras llega la sugerencia
  await page.getByLabel('Tipo de trabajo', { exact: true }).fill('refactor');
  release();
  await page.getByRole('button', { name: 'Ver qué aplica', exact: true }).click();
  await expect.poll(() => requests.filter(r => r.path.endsWith('/checklist')).at(-1)?.query ?? '').toContain('tipo_trabajo=refactor');
  await expect(page.getByLabel('Tipo de trabajo', { exact: true })).toHaveValue('refactor');
  await expect(page.getByText(/completado desde/)).toHaveCount(0);
});
