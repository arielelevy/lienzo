import { expect, test } from "@playwright/test";
import { BASE, SID, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

/** Aviso de tarjeta estancada (encargo C, ronda 2026-10-21): figura `corriendo` y su pantalla no
 *  cambió en N minutos (5 por defecto, se elige en el menú ⋯). El reloj del navegador es falso y
 *  la pantalla la sirve la prueba: nada toca sesiones de verdad. */
test("la tarjeta que corre con la pantalla quieta avisa a los 5 min y el aviso se va cuando la pantalla cambia", async ({ page }) => {
  await page.clock.install();
  await bloquearEscrituras(page);
  await instalarTablero(page);
  let pantalla = ["✻ Pensando… (12s · esc to interrupt)", "> repartí los encargos"];
  const lecturas: string[] = [];
  await page.route(/\/sessions\/[^/]+\/screen$/, (route) => {
    const sid = new URL(route.request().url()).pathname.split("/")[2];
    lecturas.push(sid);
    // la otra que corre (Codex) se mueve sola; la coordinadora queda quieta
    const lines = sid === SID.coordinadora ? pantalla : [`paso ${lecturas.length}`];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, lines }) });
  });
  await page.goto(BASE);
  const coordinadora = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  const flechas = page.locator(`.card[data-sid="${SID.flechas}"]`);
  await expect(coordinadora).toBeVisible();
  await expect.poll(() => lecturas.filter((s) => s === SID.coordinadora).length).toBeGreaterThan(0);
  // sólo se leen las que corren con consola: ni las que terminaron, ni la muerta, ni la huérfana (corre sin terminal)
  await expect.poll(() => new Set(lecturas).size).toBe(3);
  expect([...new Set(lecturas)].sort()).toEqual([SID.coordinadora, SID.flechas, SID.reglas].sort());
  const aviso = coordinadora.getByRole("status").filter({ hasText: "pantalla quieta" });

  await page.clock.fastForward("04:00");
  await expect(aviso).toHaveCount(0);
  // a los 5 min: sólo cambió el reloj del spinner, que no cuenta
  pantalla = ["✶ Pensando… (312s · esc to interrupt)", "> repartí los encargos"];
  await page.clock.fastForward("01:10");
  await expect(aviso).toHaveText("pantalla quieta · 5 min");
  await expect(flechas.getByRole("status").filter({ hasText: "pantalla quieta" })).toHaveCount(0);

  // la pantalla cambia de verdad: en la próxima lectura (≤ 60 s) el aviso se va
  pantalla = ["✻ Pensando… (340s · esc to interrupt)", "Ocho encargos repartidos.", "> repartí los encargos"];
  await page.clock.fastForward("01:00");
  await expect(aviso).toHaveCount(0);

  // los minutos se eligen en el menú ⋯ y valen para todas las tarjetas
  await coordinadora.getByRole("button", { name: "más acciones de la tarjeta" }).click();
  const opcion = page.getByRole("menuitem", { name: /Pantalla quieta/ });
  await expect(opcion).toHaveText("Pantalla quieta: aviso a los 5 min");
  await opcion.click();
  await expect(opcion).toHaveText("Pantalla quieta: aviso a los 10 min");
  await page.keyboard.press("Escape");
  await page.clock.fastForward("06:10");
  await expect(aviso).toHaveCount(0);
  await page.clock.fastForward("04:00");
  await expect(aviso).toHaveText(/pantalla quieta · 1\d min/);
  expect(await page.evaluate(() => localStorage.getItem("lienzo.pantallaQuietaMin"))).toBe("10");
});
