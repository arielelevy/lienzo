import { expect, test } from "@playwright/test";
import { SID, abrirTablero, esperarQuietud } from "./tablero-fijo";
import { desborde } from "./medidas";

/** Correr una tarjeta con el mouse y devolverla al orden automático.
 *
 *  El gesto sin Alt mueve; con Alt conecta (y el agarre ⇢ también, que es la forma que funciona con
 *  el dedo). Las dos cosas salen del mismo pointerdown sobre el título, así que se prueban juntas:
 *  lo que se puede romper es justamente que una se lleve puesta a la otra. */

/** Centro del título de una tarjeta, que es de donde se agarra. */
async function agarre(page: import("@playwright/test").Page, sid: string) {
  const r = await page.locator(`.card[data-sid="${sid}"] .title`).boundingBox();
  if (!r) throw new Error(`sin título visible en ${sid}`);
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

async function caja(page: import("@playwright/test").Page, sid: string) {
  const r = await page.locator(`.card[data-sid="${sid}"]`).boundingBox();
  if (!r) throw new Error(`sin tarjeta ${sid}`);
  return r;
}

/** Arrastra desde el título de una tarjeta hasta un punto, en varios pasos (el tablero solo
 *  arranca el gesto después de 8 px). */
async function arrastrar(page: import("@playwright/test").Page, sid: string, dx: number, dy: number, alt = false) {
  const p = await agarre(page, sid);
  if (alt) await page.keyboard.down("Alt");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + dx / 2, p.y + dy / 2, { steps: 5 });
  await page.mouse.move(p.x + dx, p.y + dy, { steps: 5 });
  await page.mouse.up();
  if (alt) await page.keyboard.up("Alt");
}

test("arrastrar una tarjeta la deja donde la soltaste", async ({ page }) => {
  await abrirTablero(page);
  const antes = await caja(page, SID.mapas);
  await arrastrar(page, SID.mapas, 180, 120);
  await esperarQuietud(page);

  const despues = await caja(page, SID.mapas);
  // 2 px de tolerancia: el redondeo del layout, no un salto
  expect(Math.abs(despues.x - (antes.x + 180))).toBeLessThan(2);
  expect(Math.abs(despues.y - (antes.y + 120))).toBeLessThan(2);
  // no se encogió al salir del flujo
  expect(Math.abs(despues.width - antes.width)).toBeLessThan(2);
  await expect(page.locator(`.capa-libre > div .card[data-sid="${SID.mapas}"]`)).toBeVisible();
});

test("el hueco se cierra: las de abajo suben", async ({ page }) => {
  await abrirTablero(page);
  const vecinas = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>(".card[data-sid]")].map((c) => ({ sid: c.dataset.sid!, y: Math.round(c.getBoundingClientRect().top) })),
  );
  await arrastrar(page, SID.mapas, 200, 60);
  await esperarQuietud(page);
  const ahora = await page.evaluate(() =>
    Object.fromEntries([...document.querySelectorAll<HTMLElement>(".card[data-sid]")].map((c) => [c.dataset.sid!, Math.round(c.getBoundingClientRect().top)])),
  );
  // alguna de las que estaban debajo de la movida ocupó su lugar
  const subio = vecinas.filter((v) => v.sid !== SID.mapas).some((v) => ahora[v.sid] < v.y - 4);
  expect(subio).toBe(true);
});

test("«Ordenar» las devuelve a todas", async ({ page }) => {
  await abrirTablero(page);
  const antes = await caja(page, SID.mapas);
  // sin tarjetas corridas el botón no existe
  await expect(page.locator(".board .ordenar")).toHaveCount(0);

  await arrastrar(page, SID.mapas, 150, 100);
  await esperarQuietud(page);
  await expect(page.locator(".board .ordenar")).toBeVisible();

  await page.locator(".board .ordenar").click();
  await esperarQuietud(page);
  const despues = await caja(page, SID.mapas);
  expect(Math.abs(despues.x - antes.x)).toBeLessThan(2);
  expect(Math.abs(despues.y - antes.y)).toBeLessThan(2);
  await expect(page.locator(".board .ordenar")).toHaveCount(0);
});

test("Esc durante el arrastre la devuelve a donde estaba", async ({ page }) => {
  await abrirTablero(page);
  const antes = await caja(page, SID.mapas);
  const p = await agarre(page, SID.mapas);
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(p.x + 160, p.y + 90, { steps: 8 });
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await esperarQuietud(page);

  const despues = await caja(page, SID.mapas);
  expect(Math.abs(despues.x - antes.x)).toBeLessThan(2);
  expect(Math.abs(despues.y - antes.y)).toBeLessThan(2);
});

test("la posición sobrevive al refresco", async ({ page }) => {
  await abrirTablero(page);
  const antes = await caja(page, SID.mapas);
  await arrastrar(page, SID.mapas, 170, 110);
  await esperarQuietud(page);

  await page.reload();
  await page.waitForSelector(".card", { state: "visible" });
  await esperarQuietud(page);
  const despues = await caja(page, SID.mapas);
  expect(Math.abs(despues.x - (antes.x + 170))).toBeLessThan(2);
  expect(Math.abs(despues.y - (antes.y + 110))).toBeLessThan(2);
});

test("con Alt el mismo gesto conecta y no mueve", async ({ page }) => {
  await abrirTablero(page);
  const antes = await caja(page, SID.mapas);
  const destino = await caja(page, SID.capas);
  const p = await agarre(page, SID.mapas);
  await page.keyboard.down("Alt");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(destino.x + destino.width / 2, destino.y + destino.height / 2, { steps: 10 });
  await page.mouse.up();
  await page.keyboard.up("Alt");

  // se abrió el diálogo de reenvío, y la tarjeta no se movió ni un pixel
  await expect(page.locator(".fwd")).toBeVisible();
  const despues = await caja(page, SID.mapas);
  expect(Math.abs(despues.x - antes.x)).toBeLessThan(2);
  expect(Math.abs(despues.y - antes.y)).toBeLessThan(2);
  await expect(page.locator(".capa-libre > div")).toHaveCount(0);
});

test("una corrida no estrena scroll horizontal al angostar la ventana", async ({ page }) => {
  await abrirTablero(page);
  // contra el borde derecho del tablero, que es el peor caso
  const t = await page.locator(`.card[data-sid="${SID.mapas}"] .title`).boundingBox();
  await page.mouse.move(t!.x + t!.width / 2, t!.y + t!.height / 2);
  await page.mouse.down();
  await page.mouse.move(page.viewportSize()!.width - 10, t!.y + 200, { steps: 8 });
  await page.mouse.up();
  await esperarQuietud(page);

  for (const w of [1152, 960]) {
    await page.setViewportSize({ width: w, height: 900 });
    await esperarQuietud(page);
    const d = await desborde(page);
    expect(`${w}: scroll ${d.scroll}px, ${d.culpables.map((c) => c.sel).join(" ") || "nada fuera"}`).toBe(`${w}: scroll 0px, nada fuera`);
  }
});

test("la ayuda al pie nombra los dos gestos", async ({ page }) => {
  await abrirTablero(page);
  await expect(page.locator(".ayuda")).toContainText("Arrastrá una tarjeta desde su título para moverla");
  await expect(page.locator(".ayuda b")).toHaveText("Alt");
});
