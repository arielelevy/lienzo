import { expect, test } from "@playwright/test";
import { BASE, bloquearEscrituras, esperarQuietud } from "./tablero-fijo";
import { desborde } from "./medidas";

/** Prueba de humo contra los datos de verdad: sin interceptar nada, el tablero del 7321 tal como
 *  está en este momento. No mide posiciones (el tablero cambia todo el tiempo): mira que la app
 *  arranque, dibuje sus tres columnas, no tire errores y no desborde a lo ancho. Sigue sin
 *  escribir: `bloquearEscrituras` corta todo lo que no sea GET. */
test("el tablero real carga, dibuja sus columnas y no tira errores", async ({ page }) => {
  const errores: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errores.push(`console.error: ${m.text()}`);
  });
  page.on("pageerror", (e) => errores.push(`excepción: ${e.message}`));

  await bloquearEscrituras(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(BASE);

  await expect(page.locator("header")).toBeVisible();
  await expect(page.locator(".board .col")).toHaveCount(3);
  // el server contesta con datos: o hay tarjetas, o las columnas dicen que están vacías
  await page.waitForFunction(() => document.querySelectorAll(".card").length > 0 || document.querySelectorAll(".board .col .empty").length === 3);

  const tarjetas = await page.locator(".card").count();
  const sesiones = (await (await fetch(`${BASE}/sessions`)).json()) as unknown[];
  // lo que pinta el tablero no puede ser más que lo que dice el server (la columna Muerta arranca
  // colapsada, así que suele ser menos)
  expect(tarjetas).toBeLessThanOrEqual(sesiones.length);

  await esperarQuietud(page);
  const d = await desborde(page);
  expect(`scroll ${d.scroll}px, ${d.culpables.map((c) => `${c.sel} se sale ${c.fuera}px`).join(" · ") || "nada fuera de pantalla"}`).toBe("scroll 0px, nada fuera de pantalla");

  expect(errores).toEqual([]);
});
