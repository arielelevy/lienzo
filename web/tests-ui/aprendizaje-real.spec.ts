import { expect, test } from '@playwright/test';
import { BASE } from './tablero-fijo';

/** Recorrido real del aprendizaje por proyecto (encargo Q, 2026-10-22): una instancia aislada sembrada por
 *  `pruebas-agenticas/aprendizaje_sembrar_Q.py` (lo lanza `aprendizaje_e2e_Q.ps1`) con la API real, una sesión
 *  viva entregada por el hook real y, si se pide, Claude real para el texto libre. Sin fixtures ni rutas
 *  interceptadas. Sólo corre con LIENZO_DEMO_Q=demo-q: nunca contra el 7321. */
const DEMO = process.env.LIENZO_DEMO_Q;
test.skip(!DEMO || BASE.endsWith(':7321'), 'requiere la instancia aislada sembrada (LIENZO_DEMO_Q)');

const api = async (path: string) => (await fetch(BASE + path, { headers: { 'X-Lienzo': '1' } })).json();

test('desde el menú, sin tarjeta elegida: lo aprendido, el contexto completo y el veredicto en un clic', async ({ page }, info) => {
  await page.goto(BASE);
  await page.evaluate(() => { try { localStorage.setItem('lienzo.persona', 'Ariel'); } catch { /* */ } });
  await page.reload();
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption(DEMO!);
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  const own = dialog.getByRole('region', { name: 'De este proyecto' });
  const proc = dialog.getByRole('region', { name: 'De cómo se trabaja con Lienzo' });
  await expect(own.getByText('Mostrar las creencias del proyecto al abrir', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(proc.getByText('Verificar en uso real antes de cerrar un frente', { exact: true })).toBeVisible();
  // el contexto completo, plegado: del encargo en curso y de la sesión viva más reciente
  const summary = dialog.locator('details.knowledge-context > summary');
  await expect(summary).toContainText('Tipo de trabajo: feature · Tecnología: react · Agente: claude', { timeout: 30_000 });
  await expect(summary).toContainText('Versión del agente: 2.9.1');
  await summary.click();
  await expect(dialog.getByText(/^de la sesión q0e2e000$/).first()).toBeVisible();
  await expect(dialog.getByText(/^de encargo Q \(pendiente\)$/).first()).toBeVisible();
  await dialog.screenshot({ path: info.outputPath('aprendizaje-real-abre.png'), animations: 'disabled' });
  await summary.click();
  // aceptar en un clic: queda vigente, firmado, con la revisión como evidencia
  await own.getByRole('button', { name: 'Aceptar' }).click();
  await expect(dialog.getByText('Aceptada: ya cuenta como vigente.', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(own.getByText('Vigente', { exact: true })).toBeVisible();
  const vista = await api(`/conocimiento/${DEMO}/creencias-proyecto`);
  expect(vista.proyecto.items[0].estado).toBe('vigente');
  const nodo = await api(`/conocimiento/${DEMO}/nodos/${vista.proyecto.items[0].creencia}`);
  expect(nodo.datos.veredicto_por).toBe('persona:Ariel');
  const ev = await api(`/conocimiento/${DEMO}/nodos/${nodo.datos.evidencia_veredicto}`);
  expect(ev.datos.clase).toBe('revision_humana');
  // corregir la de proceso desde otro proyecto: se guarda en lienzo
  await proc.getByRole('button', { name: 'Corregir' }).click();
  await proc.getByLabel('Qué hay que hacer').fill('Verificar en uso real, con evidencia, antes de cerrar un frente');
  await proc.getByRole('button', { name: 'Guardar corrección' }).click();
  await expect(dialog.getByText(/Corregida: la nueva versión quedó vigente/)).toBeVisible({ timeout: 30_000 });
  await expect(proc.getByText('Verificar en uso real, con evidencia, antes de cerrar un frente', { exact: true })).toBeVisible();
  const lienzo = await api('/conocimiento/lienzo/creencias-proyecto');
  expect(lienzo.lienzo.items.map((x: { estado: string }) => x.estado).sort()).toEqual(['refutada', 'vigente']);
  await dialog.screenshot({ path: info.outputPath('aprendizaje-real-veredicto.png'), animations: 'disabled' });
});

test('el texto libre lo interpreta Claude real y sólo llena los campos', async ({ page }, info) => {
  test.skip(!process.env.LIENZO_IA_REAL, 'la llamada real a Claude se pide con LIENZO_IA_REAL=1');
  test.setTimeout(120_000);
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption(DEMO!);
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  const antes = await api(`/conocimiento/${DEMO}/cambios`);
  await dialog.locator('details.knowledge-context > summary').click();
  await dialog.getByLabel('¿Qué vas a hacer? (texto libre)').fill('Voy a corregir un bug en el componente React de la pestaña de aprendizaje');
  await dialog.getByRole('button', { name: 'Completar con IA' }).click();
  await expect(dialog.getByText(/La IA completó \d+ campos|La IA no reconoció|completá los campos a mano/)).toBeVisible({ timeout: 90_000 });
  await dialog.screenshot({ path: info.outputPath('aprendizaje-real-ia.png'), animations: 'disabled' });
  const tipo = await dialog.getByLabel('Tipo de trabajo', { exact: true }).inputValue();
  test.info().annotations.push({ type: 'ia', description: `tipo_trabajo=${tipo}` });
  expect(await api(`/conocimiento/${DEMO}/cambios`)).toEqual(antes);  // nada se guardó
});
