import { expect, test, type Page } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

/** Vista Etapas de Memoria (Etapas.tsx, encargo L, decisión 15): cada encargo con su etapa, su
 *  evidencia y las acciones de una persona. Rutas de /conocimiento fijas; las escrituras se contestan
 *  acá y se cuentan, ninguna llega al server. */
const enc = (id: string, letra: string, estado: string, extra: Record<string, unknown> = {}) => ({
  id, texto: '# Encargo ' + letra, estado, estado_por: estado === 'pendiente' ? null : 'server', estado_fecha: '2026-10-22T12:00:00.000Z',
  ronda: 'r1', fecha: '2026-10-22T11:00:00.000Z', datos: { letra, ...extra },
});
const ENCARGOS = { total: 5, desde: 0, nodos: [enc('a', 'A', 'pendiente'), enc('b', 'B', 'enviado', { devuelto_revision: 1 }), enc('c', 'C', 'entregado'), enc('d', 'D', 'verificando'), enc('e', 'E', 'sin_entrega')] };
const RONDAS = { total: 1, desde: 0, nodos: [{ id: 'r1', texto: 'Ronda de etapas', estado: 'abierta', fecha: '2026-10-22T10:00:00.000Z', datos: {} }] };
const EVIDENCIA = { total: 2, desde: 0, nodos: [{ id: 'ev0', texto: 'vieja.md', estado: null, fecha: '2026-10-22T11:30:00.000Z', datos: {} }, { id: 'ev1', texto: 'suite-focal.txt', estado: null, fecha: '2026-10-22T12:30:00.000Z', datos: {} }] };
const INFORMES = { total: 1, desde: 0, nodos: [{ id: 'i1', texto: 'informe D r1', estado: 'recibido', fecha: '2026-10-22T12:10:00.000Z', datos: {} }] };
const DETALLE_D = { ...enc('d', 'D', 'verificando'), vinculos: { salen: [{ de: 'd', relacion: 'apoya', a: 'ev1', fecha: '2026-10-22T12:20:00.000Z', autor: 'persona:Ariel' }], entran: [{ de: 'i1', relacion: 'responde_a', a: 'd', fecha: '2026-10-22T12:10:00.000Z', autor: 'frente:x' }] },
  cambios: [{ seq: 7, accion: 'estado', autor: 'persona:Ariel', motivo: 'revisión sin hallazgos', fecha: '2026-10-22T12:21:00.000Z', nuevo: { estado: 'verificando' }, origen: { evidencia: ['ev1'] } }] };

async function prepare(page: Page) {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const reads: string[] = [];
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === 'POST') {
      writes.push({ path: url.pathname, body: req.postDataJSON() });
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    }
    reads.push(url.pathname + url.search);
    const tipo = url.searchParams.get('tipo');
    const body = url.pathname.endsWith('/proyectos') ? [{ id: 'uno', nombre: 'Uno' }]
      : url.pathname.endsWith('/temas') ? { temas: [] }
      : url.pathname.endsWith('/nodos/d') ? DETALLE_D
      : tipo === 'encargo' ? ENCARGOS : tipo === 'ronda' ? RONDAS : tipo === 'evidencia' ? EVIDENCIA : tipo === 'informe' ? INFORMES
      : { vigente: [], abierto: [], otros: [] };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.evaluate(() => { try { localStorage.removeItem('lienzo.persona'); } catch { /* */ } });
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Etapas', exact: true }).click();
  await page.getByRole('button', { name: 'Leer encargos', exact: true }).click();
  return { writes, reads };
}
const card = (page: Page, letra: string) => page.locator('li.etapas-card').filter({ hasText: `${letra} · Encargo ${letra}` });
const actual = (page: Page, letra: string) => card(page, letra).locator('[aria-current="step"]');

test('cada encargo muestra su etapa y sólo revisión y verificación tienen acciones', async ({ page }, info) => {
  const { writes } = await prepare(page);
  await expect(page.getByRole('heading', { name: 'Ronda de etapas', exact: true })).toBeVisible();
  for (const [letra, etapa] of [['A', 'Pendiente'], ['B', 'Implementación'], ['C', 'Revisión'], ['D', 'Verificación']])
    await expect(actual(page, letra)).toHaveText(etapa);
  await expect(card(page, 'B')).toContainText('devuelto tras el informe r1');
  await expect(card(page, 'E')).toContainText('Sin entrega');
  for (const letra of ['A', 'B', 'E']) await expect(card(page, letra).getByRole('button', { name: 'Devolver a implementación' })).toHaveCount(0);
  await expect(card(page, 'C').getByRole('button', { name: 'Pasar a verificación' })).toBeDisabled();
  await expect(card(page, 'D').getByRole('button', { name: 'Aprobar' })).toBeDisabled();
  await page.getByRole('dialog', { name: 'Memoria del proyecto' }).screenshot({ path: info.outputPath('etapas.png') });
  expect(writes).toEqual([]);
});

test('ver evidencia muestra informes, evidencia vinculada e historial', async ({ page }) => {
  await prepare(page);
  await card(page, 'D').getByText('Ver evidencia · D', { exact: true }).click();
  await expect(card(page, 'D').getByText('informe D r1', { exact: false })).toBeVisible();
  await expect(card(page, 'D').getByText(/suite-focal\.txt · persona:Ariel/)).toBeVisible();
  await expect(card(page, 'D').getByText(/Verificación · persona:Ariel · revisión sin hallazgos · evidencia: suite-focal\.txt/)).toBeVisible();
});

test('sólo ofrece evidencia recibida en la etapa actual', async ({ page }) => {
  await prepare(page);
  const opciones = card(page, 'D').getByLabel('Evidencia de esta etapa').locator('option');
  await expect(opciones).toHaveText(['Elegí una evidencia', 'suite-focal.txt']);
});

test('aprobar exige nombre, cita la evidencia en una sola escritura y relee la evidencia abierta', async ({ page }) => {
  const { writes, reads } = await prepare(page);
  const d = card(page, 'D');
  await d.getByText('Ver evidencia · D', { exact: true }).click();
  await expect(d.getByText('informe D r1', { exact: false })).toBeVisible();
  await d.getByLabel('Evidencia de esta etapa').selectOption('ev1');
  await d.getByRole('button', { name: 'Aprobar' }).click();
  await expect(page.getByRole('alert')).toContainText('Escribí tu nombre');
  expect(writes).toEqual([]);
  await page.getByLabel('Tu nombre (firma las etapas)').fill('Ariel');
  await d.getByRole('button', { name: 'Aprobar' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'pasó a aprobado' })).toBeVisible();
  expect(writes).toEqual([{ path: '/conocimiento/uno/nodos/d/estado', body: { estado: 'aprobado', por: 'persona:Ariel', motivo: '', origen: { evidencia: 'ev1' } } }]);
  await expect.poll(() => reads.filter(r => r === '/conocimiento/uno/nodos/d').length).toBe(2);
  await expect(d.getByText('informe D r1', { exact: false })).toBeVisible();
});

test('devolver exige motivo y no cita evidencia', async ({ page }) => {
  const { writes } = await prepare(page);
  await page.getByLabel('Tu nombre (firma las etapas)').fill('Ariel');
  const c = card(page, 'C');
  const devolver = c.getByRole('button', { name: 'Devolver a implementación' });
  await expect(devolver).toBeDisabled();
  await c.getByLabel('Motivo').fill('code review: 2 hallazgos');
  await devolver.click();
  await expect(page.getByRole('status').filter({ hasText: 'volvió a implementación' })).toBeVisible();
  expect(writes).toEqual([{ path: '/conocimiento/uno/nodos/c/estado', body: { estado: 'enviado', por: 'persona:Ariel', motivo: 'code review: 2 hallazgos' } }]);
});
