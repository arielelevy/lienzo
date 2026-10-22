import { expect, test } from '@playwright/test';
import { BASE } from './tablero-fijo';

/** Recorrido real de las etapas (encargo L): una instancia aislada sembrada con encargos en cada etapa
 *  (proyecto `etapas`), con la API y la base reales. Sin rutas interceptadas. Sólo corre con
 *  LIENZO_DEMO_L=etapas: nunca contra el 7321, porque escribe en la memoria. */
const DEMO = process.env.LIENZO_DEMO_L;
test.skip(!DEMO || BASE.endsWith(':7321'), 'requiere la instancia aislada sembrada (LIENZO_DEMO_L)');

test('revisión, verificación con evidencia propia, aprobación y devolución con motivo', async ({ page }, info) => {
  await page.goto(BASE);
  await page.evaluate(() => { try { localStorage.setItem('lienzo.persona', 'Ariel'); } catch { /* */ } });
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  await dialog.getByLabel('Proyecto', { exact: true }).selectOption(DEMO!);
  await dialog.getByRole('button', { name: 'Etapas', exact: true }).click();
  await dialog.getByRole('button', { name: 'Leer encargos', exact: true }).click();
  const card = (letra: string, texto: string) => dialog.locator('li.etapas-card').filter({ hasText: `${letra} · ${texto}` });
  const D = card('D', 'Encargo en verificacion'), C = card('C', 'Encargo en revision');
  await expect(D.locator('[aria-current="step"]')).toHaveText('Verificación');
  await expect(C.locator('[aria-current="step"]')).toHaveText('Revisión');
  await dialog.screenshot({ path: info.outputPath('etapas-real-antes.png') });

  // la evidencia de la revisión no se ofrece para la verificación; la abierta se relee al aprobar
  await D.getByText('Ver evidencia · D', { exact: true }).click();
  await expect(D.getByText(/Verificación · coordinadora:sid-coord · revision sin hallazgos/)).toBeVisible();
  const opciones = D.getByLabel('Evidencia de esta etapa').locator('option');
  await expect(opciones.filter({ hasText: 'suite-focal-D.txt' })).toHaveCount(1);
  await expect(opciones.filter({ hasText: 'code-review-D.md' })).toHaveCount(0);
  await D.getByLabel('Evidencia de esta etapa').selectOption({ label: 'suite-focal-D.txt' });
  await D.getByRole('button', { name: 'Aprobar' }).click();
  await expect(D.locator('[aria-current="step"]')).toHaveText('Aprobado');
  await expect(D.getByText(/Aprobado · persona:Ariel · evidencia: suite-focal-D\.txt/)).toBeVisible();
  await expect(D.getByRole('button', { name: 'Aprobar' })).toHaveCount(0);

  // revisión: devolver exige motivo y deja la marca de la revisión devuelta
  await C.getByLabel('Motivo').fill('code review: falta la prueba en rojo');
  await C.getByRole('button', { name: 'Devolver a implementación' }).click();
  await expect(C.locator('[aria-current="step"]')).toHaveText('Implementación');
  await expect(C).toContainText('devuelto tras el informe r1');
  await dialog.screenshot({ path: info.outputPath('etapas-real-despues.png') });
});
