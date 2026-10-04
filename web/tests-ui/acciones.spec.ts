import { expect, test, type Page } from "@playwright/test";
import type { Peer } from "../src/types";
import { BASE, SID, abrirTablero, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

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

test("F7: un doble click en Permitir manda un solo POST, en la tarjeta y en el panel", async ({ page }) => {
  await abrirTablero(page);
  const posts: unknown[] = [];
  await page.route("**/pending/p1", async (route) => {
    posts.push(route.request().postDataJSON());
    // lento a proposito: el segundo click llega con el primero en vuelo
    await new Promise((r) => setTimeout(r, 400));
    await route.fulfill(json(200, { ok: true }));
  });
  const card = page.locator(`.card[data-sid="${SID.permiso}"]`);
  await card.getByRole("button", { name: "Permitir" }).dblclick();
  await expect(page.getByText("Permitido")).toBeVisible();
  expect(posts).toEqual([{ decision: "allow" }]);

  // el panel tiene su propio bloque (la tarjeta queda atras): el mismo freno
  posts.length = 0;
  await card.locator(".title").dblclick();
  const panel = page.locator(".panel");
  await panel.getByRole("button", { name: "Denegar" }).click();
  await panel.getByRole("button", { name: "Denegar" }).click({ force: true });
  await expect(page.getByText("Denegado", { exact: true })).toBeVisible();
  expect(posts).toEqual([{ decision: "deny" }]);
});

/** /config servido por la prueba: `valores` se consume de a uno por GET (el ultimo se repite); un
 *  numero es un status de error */
async function configServida(page: Page, valores: (Record<string, boolean> | number)[]) {
  let i = 0;
  await page.route("**/config", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const v = valores[Math.min(i++, valores.length - 1)];
    return route.fulfill(typeof v === "number" ? json(v, { error: "reiniciando" }) : json(200, v));
  });
}

test("F1: la config se refresca sola y un error pasajero no apaga la barra de auto-aprobar", async ({ page }) => {
  await page.clock.install();
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await configServida(page, [{ auto_continue: false, auto_retry: false, auto_aprobar: false }, { auto_continue: false, auto_retry: false, auto_aprobar: true }, 502]);
  await page.goto(BASE);
  await expect(page.locator(".card").first()).toBeVisible();
  await expect(page.locator(".auto-aprobar-aviso")).toHaveCount(0);
  // otra PC lo prendio: al siguiente refresco aparece la barra, sin recargar
  await page.clock.fastForward(20_000);
  await expect(page.locator(".auto-aprobar-aviso")).toBeVisible();
  // el server se esta reiniciando: la barra se queda (antes volvia a null y desaparecia)
  await page.clock.fastForward(20_000);
  await page.clock.fastForward(20_000);
  await expect(page.locator(".auto-aprobar-aviso")).toBeVisible();
});

test("F1: si otra PC no tomó auto-aprobar, el toast dice cuál", async ({ page }) => {
  const peers = [
    { pc_id: "pcA", name: "escritorio", local: true, alive: true, color: "#c00", last_seen: new Date().toISOString() },
    { pc_id: "pcB", name: "notebook", local: false, alive: true, color: "#0c0", last_seen: new Date().toISOString() },
  ] as Peer[];
  await abrirTablero(page, undefined, peers);
  let puesto: unknown = null;
  await page.route("**/config", (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    puesto = route.request().postDataJSON();
    return route.fulfill(json(200, { auto_continue: false, auto_retry: false, auto_aprobar: true, peers: { pcB: "timed out" } }));
  });
  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "más opciones" }).click();
  await page.getByRole("menuitemcheckbox", { name: /Auto-aprobar TODO/ }).click();
  expect(puesto).toEqual({ auto_aprobar: true });
  await expect(page.getByText(/notebook no lo tomó \(timed out\)/)).toBeVisible();
  await expect(page.locator(".auto-aprobar-aviso")).toBeVisible();
});
