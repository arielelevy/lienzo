import { expect, test } from '@playwright/test';
import { BASE } from './tablero-fijo';

/** Recorrido real del checklist sostenido (encargo J): una instancia aislada sembrada por
 *  `pruebas-agenticas/checklist_motor_sembrar.py` (lo lanza `checklist_motor_e2e.ps1`) con la API real y el motor SWI-Prolog real. Sin
 *  fixtures ni rutas interceptadas. Sólo corre con LIENZO_DEMO_J=demo-j: nunca contra el 7321. */
const DEMO = process.env.LIENZO_DEMO_J;
test.skip(!DEMO || BASE.endsWith(':7321'), 'requiere la instancia aislada sembrada (LIENZO_DEMO_J)');

test('de la tira al checklist: sostenida con su prueba, cuestionada por la regla y otro contexto vacío', async ({ page }, info) => {
  const writes: string[] = [];
  // el tablero avisa su actividad al scheduler; lo que importa es que la memoria no se escriba
  page.on('request', r => { if (r.method() !== 'GET' && new URL(r.url()).pathname.startsWith('/conocimiento')) writes.push(r.method() + ' ' + new URL(r.url()).pathname); });
  await page.goto(BASE);
  const chip = page.getByRole('list', { name: 'aprendizaje por proyecto' }).getByRole('button', { name: /Demo J/ });
  await expect(chip).toContainText('2 vigentes · 1 regla cuestionada');
  await page.reload();  // recarga: la tira se vuelve a leer del server
  await chip.click();
  const dialog = page.getByRole('dialog', { name: 'Memoria del proyecto' });
  await expect(dialog.getByLabel('Proyecto', { exact: true })).toHaveValue(DEMO!);
  // abre leyendo sola, con lo que vas a hacer completado desde el encargo en curso (bugfix · claude)
  await expect(dialog.getByText(/^Lo que vas a hacer: Tipo de trabajo: bugfix · Agente: claude · completado desde encargo [AB] \(pendiente\)$/)).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByRole('region', { name: 'Creencias del proyecto' }).getByText('Aplica · sostenida por el motor')).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByText(/Cada aplicable está sostenida por el motor lógico, con su prueba\. motor-logico/)).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByText('Escribir la prueba en rojo antes del arreglo', { exact: true })).toBeVisible();
  await dialog.getByText('Sostenida por el motor lógico: ver la prueba', { exact: true }).click();
  await expect(dialog.getByText(/^sostenida\([0-9a-f]{32}\) · regla sostenida/).first()).toBeVisible();
  const cuestionadas = dialog.getByRole('heading', { name: 'Cuestionadas', exact: true }).locator('..');
  await expect(cuestionadas.getByText('Adjuntar el log del fallo al informe', { exact: true })).toBeVisible();
  await cuestionadas.getByText(/^Regla cuestionada [0-9a-f]{8}: ver la prueba$/).click();
  await expect(cuestionadas.getByText(/^cuestionada\([0-9a-f]{32}, [0-9a-f]{32}\) · regla cuestionada_directa/).first()).toBeVisible();
  await dialog.screenshot({ path: info.outputPath('checklist-motor-real.png'), animations: 'disabled' });
  // otro contexto: lo validado para bugfix no aplica a refactor
  await dialog.getByText(/^Lo que vas a hacer:/).click();
  await dialog.getByLabel('Tipo de trabajo', { exact: true }).fill('refactor');
  await dialog.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await expect(dialog.getByText('0 aplicables.', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByRole('heading', { name: 'No aplica, y por qué', exact: true }).locator('..').getByText('Otro contexto', { exact: true })).toHaveCount(2);
  expect(writes).toEqual([]);  // leer el aprendizaje no escribe
});


test('un proyecto real sin creencias abre explicando de dónde salen', async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('vacio-j');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Creencias del proyecto' })).toContainText('Este proyecto todavía no tiene creencias', { timeout: 30_000 });
  await expect(page.getByText('Qué aprendió este proyecto y qué aplica a lo que vas a hacer.', { exact: true })).toBeVisible();
});