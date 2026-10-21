import { test, expect } from '@playwright/test';
import { bloquearEscrituras, instalarTablero } from './tablero-fijo';

// La vista Aprendizaje reemplazó a Creencias (Learning.tsx): el recorrido cancela ahí la consulta.
test('cancelar consulta descarta respuesta tardía y permite consultar de nuevo', async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let count = 0;
  const item = (id: string) => ({ creencia: id, texto: 'Creencia ' + id, accion: id, dimension: 'pruebas', estado: 'aplicable',
    motivo: 'Motivo', evidencia: 'ev-' + id, excepciones: '', vigente_hasta: '2027-01-01T00:00:00+00:00', contexto: {},
    usos: { sirvio: 0, no_aplico: 0, ya_sabido: 0 }, revisar: false });
  await page.route('**/conocimiento/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/proyectos')) return route.fulfill({ json: [{ id: 'uno', nombre: 'Uno' }] });
    if (path.endsWith('/temas')) return route.fulfill({ json: { temas: [] } });
    if (path.endsWith('/checklist')) {
      count++;
      const first = count === 1;
      if (first) await pending;
      return route.fulfill({ json: { contexto: {}, total: 1, items: [item(first ? 'Resultado cancelado' : 'Resultado vigente')], no_aplican_total: 0, no_aplican: [] } });
    }
    if (path.endsWith('/creencias')) return route.fulfill({ json: [] });
    if (path.endsWith('/nodos')) return route.fulfill({ json: { total: 0, nodos: [] } });
    if (path.endsWith('/patrones-desarrollo')) return route.fulfill({ json: { revisados: 0, sin_clasificar: 0, muestra_parcial: false, patrones: [] } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await expect.poll(() => count).toBe(1);
  await page.getByRole('button', { name: 'Cancelar consulta' }).click();
  release();
  await expect(page.getByRole('button', { name: 'Consultar aprendizaje', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Consultar aprendizaje', exact: true }).click();
  await expect(page.getByText('Resultado vigente', { exact: true })).toBeVisible();
  await expect(page.getByText('Resultado cancelado', { exact: true })).toHaveCount(0);
});
