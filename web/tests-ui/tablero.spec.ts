import { expect, test } from "@playwright/test";
import { SID, abrirTablero, esperarQuietud } from "./tablero-fijo";
import { desborde } from "./medidas";

/** Los cuatro anchos que se probaron a mano una y otra vez: la pantalla grande, el portátil, la
 *  ventana a medias y el límite de abajo (por debajo de 900 el tablero pasa a una columna, que es
 *  otro diseño). */
const ANCHOS = [2560, 1440, 1152, 960];

/** Una línea por ancho, con los dos números: cuánto se puede scrollear de costado y qué quedó
 *  fuera de la pantalla (un `position: fixed` que se va para la derecha no genera scroll: no se ve
 *  y no hay manera de llegar). */
const resumen = (w: number, d: Awaited<ReturnType<typeof desborde>>) =>
  `${w}: scroll ${d.scroll}px, ${d.culpables.length ? d.culpables.map((c) => `${c.sel} se sale ${c.fuera}px`).join(" · ") : "nada fuera de pantalla"}`;

test.describe("nada de scroll horizontal", () => {
  for (const w of ANCHOS) {
    test(`a ${w} px de ancho`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: 900 });
      await abrirTablero(page);
      const d = await desborde(page);
      expect(resumen(w, d)).toBe(`${w}: scroll 0px, nada fuera de pantalla`);
    });
  }

  test("tampoco después de achicar la ventana, con el panel abierto", async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 900 });
    await abrirTablero(page);
    // el panel se ancla a la tarjeta que lo abre: abierto a lo ancho y medido después de achicar es
    // donde se salía por la derecha
    await page.locator(`.card[data-sid="${SID.migracion}"] .title`).dblclick();
    await expect(page.locator(".panel")).toHaveCount(1);

    const anchos = [1440, 1152, 960, 2560];
    const medido: string[] = [];
    for (const w of anchos) {
      await page.setViewportSize({ width: w, height: 900 });
      await esperarQuietud(page);
      medido.push(resumen(w, await desborde(page)));
    }
    expect(medido).toEqual(anchos.map((w) => `${w}: scroll 0px, nada fuera de pantalla`));
  });
});

test.describe("columnas", () => {
  test("Trabajo con tarjetas no se colapsa", async ({ page }) => {
    await abrirTablero(page);
    const trabajo = page.locator(".board .col.trabajo");
    const antes = await trabajo.locator(".card").count();
    expect(antes).toBe(6);

    await trabajo.locator("h2").click();
    await esperarQuietud(page);

    await expect(trabajo).not.toHaveClass(/\bcollapsed\b/);
    expect(await trabajo.locator(".card").count()).toBe(antes);
    // y lo dice: el título está marcado como fijo, con su explicación
    await expect(trabajo.locator("h2")).toHaveClass(/\bfixed\b/);
  });

  test("Muerta arranca colapsada aunque tenga tarjetas, y se abre con un click", async ({ page }) => {
    await abrirTablero(page);
    const muerta = page.locator(".board .col.muerta");
    await expect(muerta).toHaveClass(/\bcollapsed\b/);
    // colapsada pero no vacía: la tira cuenta las que esconde
    await expect(muerta.locator(".vlabel .n")).toHaveText("2");
    expect(await muerta.locator(".card").count()).toBe(0);

    await muerta.locator(".vlabel").click();
    await esperarQuietud(page);
    await expect(muerta).not.toHaveClass(/\bcollapsed\b/);
    expect(await muerta.locator(".card").count()).toBe(2);
    await expect(page.locator(`.card[data-sid="${SID.huerfana}"]`)).toBeVisible();

    // y la elección se recuerda: al recargar sigue abierta
    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".board .col.muerta")).not.toHaveClass(/\bcollapsed\b/);
  });

  test("Te necesita se adelanta en el DOM cuando alguien pide permiso", async ({ page }) => {
    await abrirTablero(page);
    // el orden del Tab es el del DOM: la columna con el permiso va primera, y `order` repone el
    // orden visual
    const clases = await page.locator(".board .col").evaluateAll((els) => els.map((e) => (e as HTMLElement).className.split(/\s+/)[1]));
    expect(clases[0]).toBe("te_necesita");
    await expect(page.locator(".board")).toHaveClass(/\breordered\b/);

    const x = await page.locator(".board .col").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().left)));
    // visualmente Trabajo sigue a la izquierda de Te necesita
    expect(x[1]).toBeLessThan(x[0]);
  });
});
