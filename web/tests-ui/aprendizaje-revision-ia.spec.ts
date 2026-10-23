import { expect, test } from '@playwright/test';
import { BASE, bloquearEscrituras, instalarTablero } from './tablero-fijo';

test('revisión delegada conserva la vista, aplica y deshace uno y toda la tanda', async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  const batch = { id: 'tanda-ab', agente: 'codex', items: [
    { id: 'a', proyecto: 'uno', accion: 'aceptar', motivo: 'Evidencia suficiente', deshecho: false },
    { id: 'b', proyecto: 'lienzo', accion: 'rechazar', motivo: 'No respalda el principio', deshecho: false },
  ] };
  const requests: { path: string; body: Record<string, string> }[] = [];
  let applied = false;
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    let body: unknown = {};
    if (path.endsWith('/proyectos')) body = [{ id: 'uno', nombre: 'Uno' }];
    else if (path.endsWith('/creencias-proyecto')) body = { id: 'uno', proyecto: { total: 0, items: [] }, lienzo: { total: 0, items: [] } };
    else if (path.endsWith('/contexto-sugerido')) body = { contexto: {}, fuentes: {} };
    else if (path.endsWith('/patrones-desarrollo')) body = { revisados: 0, sin_clasificar: 0, muestra_parcial: false, patrones: [] };
    else if (path.endsWith('/nodos')) body = { total: 0, nodos: [] };
    else if (path.endsWith('/revision-ia') && req.method() === 'GET') body = applied ? [batch] : [];
    else if (req.method() === 'POST') {
      const data = req.postDataJSON() as Record<string, string>;
      requests.push({ path, body: data });
      applied = true;
      if (path.endsWith('/deshacer')) for (const item of batch.items) if (!data.creencia || item.id === data.creencia) item.deshecho = true;
      body = batch;
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByRole('region', { name: 'De este proyecto', exact: true })).toBeVisible();
  await page.getByLabel('IA que revisa').selectOption('codex');
  await page.getByRole('button', { name: 'Revisar todo con IA', exact: true }).click();
  await expect(page.getByText('Revisión con codex · 2 propuestas.')).toBeVisible();
  expect(requests[0].body).toEqual({ agente: 'codex' });
  await page.getByRole('button', { name: 'Deshacer a', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Deshacer a', exact: true })).toBeDisabled();
  expect(requests[1].body).toEqual({ creencia: 'a' });
  await page.getByRole('button', { name: 'Deshacer toda la tanda', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Deshacer b', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Deshacer toda la tanda', exact: true })).toBeDisabled();
  await page.reload();
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Deshacer a', exact: true })).toBeDisabled();
});

test('«Revisar todo» sigue tanda tras tanda hasta que no quedan propuestas', async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  const tandas = [
    { id: 't1', agente: 'claude', hay_mas: true, items: [
      { id: 'a', proyecto: 'uno', accion: 'aceptar', motivo: 'Respaldada', deshecho: false },
      { id: 'b', proyecto: 'uno', accion: 'rechazar', motivo: 'Sin evidencia', deshecho: false },
    ] },
    { id: 't2', agente: 'claude', hay_mas: false, items: [
      { id: 'c', proyecto: 'uno', accion: 'aceptar', motivo: 'Respaldada', deshecho: false },
    ] },
  ];
  let posts = 0;
  await page.route('**/conocimiento/**', route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    let body: unknown = {};
    if (path.endsWith('/proyectos')) body = [{ id: 'uno', nombre: 'Uno' }];
    else if (path.endsWith('/creencias-proyecto')) body = { id: 'uno', proyecto: { total: 0, items: [] }, lienzo: { total: 0, items: [] } };
    else if (path.endsWith('/contexto-sugerido')) body = { contexto: {}, fuentes: {} };
    else if (path.endsWith('/patrones-desarrollo')) body = { revisados: 0, sin_clasificar: 0, muestra_parcial: false, patrones: [] };
    else if (path.endsWith('/nodos')) body = { total: 0, nodos: [] };
    else if (path.endsWith('/revision-ia') && req.method() === 'GET') body = [];
    else if (path.endsWith('/revision-ia') && req.method() === 'POST') body = tandas[Math.min(posts++, 1)];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE);
  await page.getByRole('button', { name: 'más opciones', exact: true }).click();
  await page.getByRole('menuitem', { name: /Memoria/ }).click();
  await page.getByLabel('Proyecto', { exact: true }).selectOption('uno');
  await page.getByRole('button', { name: 'Aprendizaje', exact: true }).click();
  await page.getByRole('button', { name: 'Revisar todo con IA', exact: true }).click();
  await expect(page.getByText('Revisadas 3 propuestas.')).toBeVisible();
  expect(posts).toBe(2);
  await expect(page.getByRole('group', { name: 'Tanda t1' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Tanda t2' })).toBeVisible();
});
