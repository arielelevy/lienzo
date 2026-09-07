import { expect, test } from "@playwright/test";
import { SID, abrirTablero, esperarQuietud } from "./tablero-fijo";
import { altoDeTarjeta, rectsDeTarjetas } from "./medidas";

/** PICK_MS de Card.tsx: el click simple espera esto antes de elegir, por si llega el segundo. */
const PICK_MS = 240;
const sel = (sid: string) => `.card[data-sid="${sid}"]`;

test.describe("click, doble click y elección", () => {
  test("un click elige la tarjeta y no abre el panel", async ({ page }) => {
    await abrirTablero(page);
    const card = page.locator(sel(SID.mapas));
    await card.locator(".title").click();
    await expect(card).toHaveClass(/\bpicked\b/);
    // el panel no aparece ni después del tiempo que tardaría en abrirse
    await page.waitForTimeout(PICK_MS + 200);
    await expect(page.locator(".panel")).toHaveCount(0);
    await expect(card).not.toHaveClass(/\bsel\b/);
  });

  test("el doble click abre el panel y no deja la tarjeta elegida", async ({ page }) => {
    await abrirTablero(page);
    const card = page.locator(sel(SID.mapas));
    await card.locator(".title").dblclick();
    await expect(page.locator(".panel")).toHaveCount(1);
    // el click simple del medio no tiene que elegir: se espera a que su temporizador venza
    await page.waitForTimeout(PICK_MS + 200);
    await expect(card).not.toHaveClass(/\bpicked\b/);
    await expect(card).toHaveClass(/\bsel\b/);
  });

  test("el alto de la tarjeta no cambia entre el click y el doble click", async ({ page }) => {
    await abrirTablero(page);
    const card = page.locator(sel(SID.coordinadora));
    const quieta = await altoDeTarjeta(page, SID.coordinadora);

    await card.locator(".title").click();
    await expect(card).toHaveClass(/\bpicked\b/);
    await esperarQuietud(page);
    const elegida = await altoDeTarjeta(page, SID.coordinadora);

    await card.locator(".title").dblclick();
    await expect(page.locator(".panel")).toHaveCount(1);
    await esperarQuietud(page);
    const abierta = await altoDeTarjeta(page, SID.coordinadora);

    expect({ quieta, elegida, abierta }).toEqual({ quieta, elegida: quieta, abierta: quieta });
  });
});

test("el reparto por subcolumna no se mueve al elegir una tarjeta", async ({ page }) => {
  await abrirTablero(page);
  const antes = await rectsDeTarjetas(page);
  expect(Object.keys(antes).length).toBeGreaterThan(4);

  // una tarjeta con conexiones: al elegirla se escriben sus frases, que es lo que antes empujaba
  // a las demás de subcolumna
  await page.locator(sel(SID.coordinadora)).locator(".title").click();
  await expect(page.locator(sel(SID.coordinadora))).toHaveClass(/\bpicked\b/);
  await esperarQuietud(page);
  const despues = await rectsDeTarjetas(page);

  const movidas = Object.keys(antes).filter((k) => JSON.stringify(antes[k]) !== JSON.stringify(despues[k]));
  expect(movidas.map((k) => `${k}: ${JSON.stringify(antes[k])} -> ${JSON.stringify(despues[k])}`)).toEqual([]);
});

test("Esc pela una capa por vez: primero el panel, después la elección", async ({ page }) => {
  await abrirTablero(page);
  const card = page.locator(sel(SID.mapas));

  await card.locator(".title").click();
  await expect(card).toHaveClass(/\bpicked\b/);
  await page.waitForTimeout(PICK_MS + 100);

  await card.locator(".title").dblclick();
  await expect(page.locator(".panel")).toHaveCount(1);
  await expect(card).toHaveClass(/\bpicked\b/); // la elección sobrevive a abrir el panel

  await page.keyboard.press("Escape");
  await expect(page.locator(".panel")).toHaveCount(0);
  await expect(card).toHaveClass(/\bpicked\b/); // primera capa: sólo el panel

  await page.keyboard.press("Escape");
  await expect(card).not.toHaveClass(/\bpicked\b/); // segunda capa: la elección
});
