import { expect, test } from "@playwright/test";
import { abrirTablero, SID, sesiones } from "./tablero-fijo";

test("varias candidatas: proponer sin marcar ni renombrar al leer", async ({ page }) => {
  const lista = sesiones().filter(s => s.session_id === SID.coordinadora);
  lista[0].coordinator = false;
  lista[0].coordinator_proposal = { kind: "role", title: "lienzo | coordinadora", reason: "Hay varias candidatas; elegí cuál coordina." };
  const cambios: unknown[] = [];
  await abrirTablero(page, lista);
  await page.route(`**/sessions/${SID.coordinadora}/coordinator`, async route => {
    cambios.push(route.request().postDataJSON());
    await route.fulfill({ json: { ok: true, coordinator: true } });
  });
  const propuesta = page.getByRole("region", { name: "Propuesta de coordinadora" });
  await expect(propuesta).toContainText("Hay varias candidatas");
  expect(cambios).toEqual([]);
  await expect(propuesta.getByRole("button", { name: "Usar título propuesto" })).toHaveCount(0);
  await propuesta.getByRole("button", { name: "Marcar coordinadora" }).click();
  await expect.poll(() => cambios).toEqual([{ on: true }]);
});

test("marca reconocida: conservar título y aceptar el propuesto con un clic", async ({ page }) => {
  const lista = sesiones().filter(s => s.session_id === SID.coordinadora);
  lista[0].coordinator = true;
  lista[0].title = "Título de Ariel";
  lista[0].coordinator_proposal = { kind: "title", title: "lienzo | coordinadora", reason: "Se reconoció su trabajo de coordinación." };
  await abrirTablero(page, lista);
  const cambios: unknown[] = [];
  await page.route(`**/sessions/${SID.coordinadora}/title`, async route => {
    cambios.push(route.request().postDataJSON());
    await route.fulfill({ json: { ok: true } });
  });
  await expect(page.locator(`.card[data-sid="${SID.coordinadora}"] .title`)).toContainText("Título de Ariel");
  expect(cambios).toEqual([]);
  await page.getByRole("button", { name: "Usar título propuesto" }).click();
  await expect.poll(() => cambios).toEqual([{ title: "lienzo | coordinadora" }]);
});

test("descartar: mostrar error del servidor sin esconder la propuesta", async ({ page }) => {
  const lista = sesiones().filter(s => s.session_id === SID.coordinadora);
  lista[0].coordinator_proposal = { kind: "title", title: "lienzo | coordinadora", reason: "Se reconoció su trabajo." };
  await abrirTablero(page, lista);
  const cambios: unknown[] = [];
  await page.route(`**/sessions/${SID.coordinadora}/orphan`, async route => {
    cambios.push(route.request().postDataJSON());
    await route.fulfill({ status: 409, json: { error: "la sesión cambió" } });
  });
  await page.getByRole("button", { name: "Descartar propuesta" }).click();
  await expect.poll(() => cambios).toEqual([{ dismiss_proposal: true }]);
  await expect(page.getByRole("alert")).toContainText("la sesión cambió");
  await expect(page.getByRole("region", { name: "Propuesta de coordinadora" })).toBeVisible();
});
