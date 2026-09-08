import { expect, test } from "@playwright/test";
import { BASE, SID, bloquearEscrituras, esperarQuietud, instalarTablero } from "./tablero-fijo";

/** Pregunta con opciones (AskUserQuestion) en la tarjeta.
 *
 *  Llega por el mismo hook que un permiso, y hasta el 2026-09-08 la tarjeta la mostraba como tal:
 *  "Pide permiso: AskUserQuestion" con Permitir y Denegar. Permitir no contestaba nada — devolvía
 *  la pregunta al selector de la terminal — así que desde el celular la sesión quedaba trabada
 *  hasta que el pedido vencía. Lo que se mide acá es que la tarjeta muestre las opciones del
 *  agente y que tocar una mande la elegida por `POST /pending/<id>`.
 *
 *  Es la única prueba de interfaz que escribe, y escribe contra una ruta interceptada: el
 *  `bloquearEscrituras` del tablero fijo sigue puesto para todo lo demás. */
const sel = `.card[data-sid="${SID.pregunta}"]`;

async function tableroConCaptura(page: import("@playwright/test").Page) {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  const enviados: unknown[] = [];
  // se registra al final: el último handler es el primero en atender, así este le gana al de
  // bloquearEscrituras, que contesta 403 a todo lo que no sea GET
  await page.route("**/pending/**", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    enviados.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.goto(BASE);
  await page.waitForSelector(".card", { state: "visible" });
  await esperarQuietud(page);
  return enviados;
}

test("la tarjeta muestra la pregunta y sus opciones, no Permitir/Denegar", async ({ page }) => {
  await tableroConCaptura(page);
  const card = page.locator(sel);
  await expect(card.locator(".needs.ask b")).toHaveText("Te hace una pregunta");
  await expect(card.locator(".needs.ask .qtext")).toHaveText("¿La leyenda va arriba o abajo?");
  await expect(card.locator(".needs.ask .opt")).toHaveCount(2);
  await expect(card.locator(".needs.ask .opt").first().locator(".olabel")).toHaveText("Arriba, sobre el mapa");
  await expect(card.locator(".needs.ask .opt").first().locator(".odesc")).toContainText("Flota sobre la esquina");
  await expect(card.locator("button.deny")).toHaveCount(0);
});

test("tocar una opción la manda como respuesta de esa pregunta", async ({ page }) => {
  const enviados = await tableroConCaptura(page);
  await page.locator(sel).locator(".needs.ask .opt").nth(1).click();
  await expect.poll(() => enviados.length).toBe(1);
  expect(enviados[0]).toEqual({
    decision: "allow",
    answers: { "¿La leyenda va arriba o abajo?": "Abajo, fuera del mapa" },
  });
});

test("lo escrito a mano le gana a la opción tocada", async ({ page }) => {
  const enviados = await tableroConCaptura(page);
  const ask = page.locator(sel).locator(".needs.ask");
  // con algo escrito, el toque ya no contesta solo: marca la opción y espera al botón
  await ask.locator("input.otro").fill("ninguna de las dos: adentro, plegable");
  await ask.locator(".opt").first().click();
  await expect(ask.locator(".opt").first()).toHaveClass(/\bon\b/);
  expect(enviados).toHaveLength(0);
  await ask.locator("button.allow").click();
  await expect.poll(() => enviados.length).toBe(1);
  expect(enviados[0]).toEqual({
    decision: "allow",
    answers: { "¿La leyenda va arriba o abajo?": "ninguna de las dos: adentro, plegable" },
  });
});

test("la salida a la terminal sigue siendo un allow pelado", async ({ page }) => {
  const enviados = await tableroConCaptura(page);
  await page.locator(sel).locator(".needs.ask button.term").click();
  await expect.poll(() => enviados.length).toBe(1);
  expect(enviados[0]).toEqual({ decision: "allow" });
});
