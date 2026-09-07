import { expect, test } from "@playwright/test";
import { abrirTablero, esperarQuietud } from "./tablero-fijo";
import { crucesDeFlechas, glifosFueraDeColumnas } from "./medidas";

/** Por debajo de 900 px no hay flechas (Arrows.tsx sale temprano), así que se mide donde las hay. */
const ANCHOS = [2560, 1440, 1152, 960];

for (const w of ANCHOS) {
  test(`a ${w} px ninguna flecha cruza el rect de una tarjeta`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: 900 });
    await abrirTablero(page);
    await esperarQuietud(page);

    const r = await crucesDeFlechas(page);
    expect(r.flechas, "el tablero fijo tiene que dibujar flechas: sin flechas la prueba no mide nada").toBeGreaterThan(2);
    expect(r.cruces.map((c) => `${c.en} entra ${c.adentro}px en la tarjeta ${c.tarjeta} (${c.x},${c.y})`)).toEqual([]);
  });

  test(`a ${w} px ningún glifo cae fuera de las columnas`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: 900 });
    await abrirTablero(page);
    await esperarQuietud(page);

    const g = await glifosFueraDeColumnas(page);
    expect(g.glifos, "cada flecha lleva su glifo: sin glifos la prueba no mide nada").toBeGreaterThan(2);
    expect(g.fuera.map((f) => `glifo "${f.glifo}" en (${f.x},${f.y})`)).toEqual([]);
  });
}

test("con una tarjeta elegida las flechas se recalculan y siguen sin cruzar tarjetas", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { sessions } = await abrirTablero(page);
  const sid = sessions[0].session_id;

  await page.locator(`.card[data-sid="${sid}"] .title`).click();
  await expect(page.locator(`.card[data-sid="${sid}"]`)).toHaveClass(/\bpicked\b/);
  await esperarQuietud(page);

  const r = await crucesDeFlechas(page);
  expect(r.cruces.map((c) => `${c.en} entra ${c.adentro}px en la tarjeta ${c.tarjeta}`)).toEqual([]);
  const g = await glifosFueraDeColumnas(page);
  expect(g.fuera).toEqual([]);
});
