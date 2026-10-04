import { expect, test, type Page } from "@playwright/test";
import { SID, abrirTablero } from "./tablero-fijo";

/** Acciones contra el server y como se cuentan sus fallas (plan de refactor 2026-10-04, puntos F). */

const json = (status: number, body: unknown) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

/** el ⋯ de la coordinadora y su item de coordinadora: un PUT /coordinator con una sola tarjeta */
async function quitarCoordinadora(page: Page) {
  const card = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  await card.locator(".kebab").click();
  await card.getByRole("menuitem", { name: /Quitarle el rol de coordinadora/ }).click();
}

test("F4: un 404 de ruta desconocida pide reiniciar el server", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/sessions/*/coordinator", (route) => route.fulfill(json(404, { error: "ruta desconocida" })));
  await quitarCoordinadora(page);
  await expect(page.getByText(/no tiene esta ruta todavía: reiniciá el server/)).toBeVisible();
});

test("F4: un 404 de tarjeta desconocida no es una ruta que falta", async ({ page }) => {
  await abrirTablero(page);
  // server.py no_session: el code es lo que distingue a la tarjeta que se fue de la ruta que falta
  await page.route("**/sessions/*/coordinator", (route) => route.fulfill(json(404, { error: "sesion desconocida", code: "unknown_session" })));
  await quitarCoordinadora(page);
  await expect(page.getByText("No se pudo: sesion desconocida")).toBeVisible();
  await expect(page.getByText(/reiniciá el server/)).toHaveCount(0);
});

test("F4: el panel reconoce la ruta que falta aunque el server conteste JSON", async ({ page }) => {
  await abrirTablero(page);
  let pedidos = 0;
  await page.route("**/sessions/*/connections", (route) => {
    pedidos++;
    return route.fulfill(json(404, { error: "ruta desconocida" }));
  });
  const warns: string[] = [];
  page.on("console", (m) => m.type() === "warning" && warns.push(m.text()));
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await expect(page.locator(".panel")).toBeVisible();
  await expect.poll(() => pedidos).toBeGreaterThan(0);
  // con "old" no es una falla de red: no se anota como tal en la consola
  await page.waitForTimeout(300);
  expect(warns.filter((w) => w.startsWith("connections:"))).toEqual([]);
});
