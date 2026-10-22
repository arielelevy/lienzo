import { expect, test, type Page } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

/** Contraste lógico de candidatos (Learning.tsx): acción explícita, sólo lectura, con prueba por
 *  observación, diferencias e indisponibilidad visibles. Fixtures: nunca toca el server real. */
const leaf = (args: string[]) => ({ by: 'given', fact: { pred: 'nodo', args }, sources: ['grafo'] });
const proof = { by: 'rule', rule: 'respaldo_caido', fact: { pred: 'respaldo_caido', args: ['c1', 'h9'] },
  premises: [{ by: 'rule', rule: 'candidato_decision', fact: { pred: 'candidato', args: ['c1'] }, premises: [leaf(['c1', 'decision', 'propuesta'])] },
    { by: 'truncated', fact: { pred: 'alcanza', args: ['c1', 'h9'] } }] };
const listo = { by: 'rule', rule: 'listo_para_revision', fact: { pred: 'listo_para_revision', args: ['c2'] },
  premises: [{ not: { pred: 'observado', args: ['c2'] } }] };
const contrast = (concluyente = true) => ({
  autoridad: 'observación; no promueve, no rechaza ni cierra', concluyente, reglas: 'contraste-1',
  motor: { name: 'motor-logico', version: '0.2.0' }, program_hash: 'sha256:abc', snapshot: 'snap', proyecto: 'uno',
  cobertura: { nodos: 4, vinculos: 3, candidatos: 3 },
  candidatos: {
    c1: { observaciones: [{ tipo: 'respaldo_caido', con: ['h9'], prueba: proof, fuentes: ['grafo'], prueba_truncada: true }],
      evidencia_independiente: 'ausente', listo_para_revision: concluyente ? false : null, justificacion_listo: null },
    c2: { observaciones: [], evidencia_independiente: 'humana', listo_para_revision: concluyente ? true : null,
      justificacion_listo: concluyente ? { prueba: listo, fuentes: ['grafo'], prueba_truncada: false } : null },
    c3: { observaciones: [], evidencia_independiente: 'no_verificada', listo_para_revision: concluyente ? false : null, justificacion_listo: null },
  },
  nodos: {
    c1: { tipo: 'decision', estado: 'propuesta', clase: 'propuesta_investigacion', texto: 'Usar RTK en pytest' },
    c2: { tipo: 'decision', estado: 'propuesta', clase: null, texto: 'Probar antes de entregar' },
    c3: { tipo: 'hallazgo', estado: 'propuesto', clase: 'optimizacion_trabajo', texto: 'Acuses repetidos' },
    h9: { tipo: 'hallazgo', estado: 'rechazado', clase: null, texto: 'Fuente rechazada' },
  },
  diferencias_python: concluyente ? [] : [{ consulta: 'listo_para_revision', solo_prolog: [['c2']], solo_python: [] }],
});

async function prepare(page: Page, reply: () => { status: number; body: unknown }) {
  const requests: { method: string; path: string }[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    requests.push({ method: req.method(), path });
    if (path.endsWith('/candidatos/contraste')) {
      const r = reply();
      return route.fulfill({ status: r.status, contentType: 'application/json', body: JSON.stringify(r.body) });
    }
    const body = path.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }, { id: 'dos', nombre: 'Dos' }]
      : path.endsWith('/temas') ? { temas: [] }
      // Aprendizaje abre leyendo solo: un proyecto sin creencias, para que el contraste sea lo único en juego
      : path.endsWith('/checklist') ? { contexto: {}, total: 0, items: [], no_aplican_total: 0, no_aplican: [] }
      : path.endsWith('/creencias') ? []
      : path.endsWith('/nodos') ? { total: 0, nodos: [] }
      : path.endsWith('/patrones-desarrollo') ? { revisados: 0, sin_clasificar: 0, muestra_parcial: false, patrones: [] }
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

test('contraste explícito muestra observaciones con su prueba y nunca escribe', async ({ page }) => {
  const requests = await prepare(page, () => ({ status: 200, body: contrast() }));
  await expect(page.getByRole('region', { name: 'Contraste de candidatos' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Contrastar candidatos' }).click();
  const section = page.getByRole('region', { name: 'Contraste de candidatos' });
  await expect(section).toContainText('motor-logico 0.2.0 · 3 candidatos · 0 diferencias con Python');
  await expect(section).toContainText('no promueve, no rechaza ni cierra');
  const c1 = section.getByRole('listitem').filter({ hasText: 'Usar RTK en pytest' }).first();
  await expect(c1).toContainText('Respaldo caído: Fuente rechazada');
  await expect(c1).toContainText('Sin evidencia independiente');
  await c1.getByText('¿Por qué?').click();
  await expect(c1).toContainText('respaldo_caido(c1, h9) · regla respaldo_caido');
  await expect(c1).toContainText('nodo(c1, decision, propuesta) · hecho del grafo');
  await expect(c1).toContainText('la prueba se recortó por profundidad');
  const c2 = section.getByRole('listitem').filter({ hasText: 'Probar antes de entregar' }).first();
  await expect(c2).toContainText('listo para revisar');
  await c2.getByText('¿Por qué está listo para revisar?').click();
  await expect(c2).toContainText('no observado(c2)');
  await expect(section.getByRole('listitem').filter({ hasText: 'Acuses repetidos' }).first()).toContainText('procedencia no verificada');
  await expect(page.getByRole('alert')).toHaveCount(0);
  const posts = requests.filter(r => r.method !== 'GET');
  expect(posts).toEqual([{ method: 'POST', path: '/conocimiento/uno/candidatos/contraste' }]);
});

test('con diferencias no declara nada listo y lo avisa', async ({ page }) => {
  await prepare(page, () => ({ status: 200, body: contrast(false) }));
  await page.getByRole('button', { name: 'Contrastar candidatos' }).click();
  const section = page.getByRole('region', { name: 'Contraste de candidatos' });
  await expect(section.getByRole('alert')).toContainText('no es concluyente');
  // ninguna tarjeta queda marcada: el texto del aviso nombra el estado, las tarjetas no
  for (const card of await section.getByRole('listitem').filter({ has: page.locator('.learning-action') }).all()) {
    await expect(card).not.toContainText('listo para revisar');
    await expect(card).toContainText('sin conclusión');
  }
  await expect(section.locator('.learning-card')).toHaveCount(3);
  await section.getByText('Huella y comparación').click();
  await expect(section).toContainText('listo_para_revision: sólo Prolog [["c2"]]');
});

test('motor ausente o respuesta inválida se ven como error, no como vacío', async ({ page }) => {
  let reply = { status: 503, body: { error: 'Motor Prolog no disponible o respuesta inválida (FileNotFoundError)', code: 'prolog_unavailable' } as unknown };
  await prepare(page, () => reply);
  await page.getByRole('button', { name: 'Contrastar candidatos' }).click();
  await expect(page.getByRole('alert')).toContainText('Motor Prolog no disponible');
  await expect(page.getByRole('region', { name: 'Contraste de candidatos' })).toHaveCount(0);
  await expect(page.getByText('No hay candidatos que esperen veredicto')).toHaveCount(0);
  reply = { status: 200, body: { ...contrast(), candidatos: { c1: { observaciones: 'x' } } } };
  await page.getByRole('button', { name: 'Contrastar candidatos' }).click();
  await expect(page.getByRole('alert')).toContainText('formato esperado');
  await expect(page.getByRole('region', { name: 'Contraste de candidatos' })).toHaveCount(0);
});

test('cambiar de proyecto descarta el contraste anterior', async ({ page }) => {
  await prepare(page, () => ({ status: 200, body: contrast() }));
  await page.getByRole('button', { name: 'Contrastar candidatos' }).click();
  await expect(page.getByRole('region', { name: 'Contraste de candidatos' })).toBeVisible();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('dos');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Contraste de candidatos' })).toHaveCount(0);
});
