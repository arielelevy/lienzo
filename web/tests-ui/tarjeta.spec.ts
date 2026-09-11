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

  test("con el panel abierto, el doble click sobre el título lo edita en el lugar", async ({ page }) => {
    await abrirTablero(page);
    const card = page.locator(sel(SID.mapas));
    const titulo = card.locator(".title");
    await titulo.dblclick(); // cerrada: abre el panel, como siempre
    await expect(page.locator(".panel")).toHaveCount(1);
    await expect(titulo.locator("input")).toHaveCount(0);

    await titulo.dblclick(); // abierta: el mismo gesto renombra, y el panel no se cierra
    const caja = titulo.locator('input[aria-label="nuevo título"]');
    await expect(caja).toHaveValue("Tablero de mapas");
    await expect(page.locator(".panel")).toHaveCount(1);

    await page.keyboard.press("Escape"); // sale de la edición sin tocar el nombre
    await expect(titulo.locator("input")).toHaveCount(0);
    await expect(titulo).toContainText("Tablero de mapas");
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

test("Destacados muestra lo que el agente fue diciendo, no solo la respuesta", async ({ page }) => {
  await abrirTablero(page);
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await expect(page.locator(".panel")).toHaveCount(1);

  // Destacados es la pestaña con la que abre el panel
  const dg = page.locator(".panel .dg").first();
  await expect(dg.locator(".f")).toContainText("la capa de calor sale de la vista");
  const dichos = dg.locator(".said .md");
  await expect(dichos).toHaveCount(2);
  await expect(dichos.first()).toContainText("Miro cómo está armada la vista");
  await expect(dichos.last()).toContainText("La vista no tiene la columna");
});

test("Destacados no corta la respuesta: va entera y se llega al final con el scroll", async ({ page }) => {
  // ventana baja a propósito: así el texto no entra en el panel y el scroll es el que tiene que
  // resolverlo, que es el caso del pedido ("si hay scroll que muestre todo")
  await page.setViewportSize({ width: 1440, height: 600 });
  await abrirTablero(page);
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  const body = page.locator(".panel .body");
  const f = page.locator(".panel .dg .f").first();

  // el final del tablero fijo mide más de 900 caracteres: con el recorte viejo (600) se cortaba
  const texto = (await f.textContent()) ?? "";
  expect(texto.length).toBeGreaterThan(900);
  expect(texto).not.toContain("…");
  await expect(f).toContainText("Y con esto cierra el pedido.");

  // el cuerpo scrollea en vertical y no desborda a lo ancho
  const m = await body.evaluate((el) => ({ v: el.scrollHeight > el.clientHeight, h: el.scrollWidth - el.clientWidth }));
  expect(m.v, "con la ventana baja el cuerpo del panel tiene que scrollear").toBe(true);
  expect(m.h, "y no desbordar a lo ancho").toBeLessThanOrEqual(1);

  // y el último párrafo se alcanza de verdad: scrolleando queda a la vista
  const ultimo = f.locator("p").last();
  await ultimo.scrollIntoViewIfNeeded();
  await expect(ultimo).toBeInViewport();
  await expect(ultimo).toContainText("Y con esto cierra el pedido.");
});
