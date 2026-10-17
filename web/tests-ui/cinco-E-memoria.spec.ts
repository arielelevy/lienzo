import { test, expect } from '@playwright/test';
import { bloquearEscrituras, instalarTablero } from './tablero-fijo';

test('cancelar consulta descarta respuesta tardía y permite consultar de nuevo', async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let count = 0;
  await page.route('**/conocimiento/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/proyectos')) return route.fulfill({ json: [{ id: 'uno', nombre: 'Uno' }] });
    if (path.endsWith('/temas')) return route.fulfill({ json: { temas: [] } });
    if (path.endsWith('/creencias')) {
      count++;
      const first = count === 1;
      if (first) await pending;
      return route.fulfill({ json: [{ id: 'b', texto: first ? 'Resultado cancelado' : 'Resultado vigente', estado: 'propuesto', datos: {} }] });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Creencias', exact: true }).click();
  await page.getByRole('button', { name: 'Leer creencias', exact: true }).click();
  await expect.poll(() => count).toBe(1);
  await page.getByRole('button', { name: 'Cancelar consulta' }).click();
  release();
  await expect(page.getByRole('button', { name: 'Leer creencias', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Leer creencias', exact: true }).click();
  await expect(page.getByText('Resultado vigente', { exact: true })).toBeVisible();
  await expect(page.getByText('Resultado cancelado', { exact: true })).toHaveCount(0);
});
