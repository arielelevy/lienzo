import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { abrirTablero, SID, sesiones } from "./tablero-fijo";
import type { Peer, Session } from "../src/types";

const iso = (minAgo: number) => new Date(Date.now() - minAgo * 60_000).toISOString();

const PEER_LOCAL: Peer = {
  pc_id: "local-1",
  name: "oficina",
  color: "#5b9cff",
  alive: true,
  last_seen: iso(0),
  local: true,
  health: null,
};

const PEER_NOTEBOOK: Peer = {
  pc_id: "note-1",
  name: "notebook",
  color: "#f0b429",
  alive: true,
  last_seen: iso(0),
  local: false,
  health: null,
};

const PEER_NOTEBOOK_CAIDA: Peer = { ...PEER_NOTEBOOK, alive: false, last_seen: iso(50) };

/** Le pone `pc: "note-1"` a las sesiones de teorema (mismo criterio que pcs.spec.ts): sirve para
 *  probar el canal nativo entre PCs distintas sobre el tablero fijo de siempre. */
function conDosPc(): Session[] {
  return sesiones().map((s) => (s.repo === "teorema" ? { ...s, pc: "note-1" } : s));
}

const dialogo = (page: Page) => page.getByRole("dialog", { name: "Varias PCs" });

async function abrirVariasPcs(page: Page) {
  await page.locator('header .icon[aria-label="más opciones"]').click();
  await page.getByRole("menuitem", { name: /Varias PCs/ }).click();
}

async function agarre(page: Page, sid: string) {
  const r = await page.locator(`.card[data-sid="${sid}"] .title`).boundingBox();
  if (!r) throw new Error(`sin título visible en ${sid}`);
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}
async function caja(page: Page, sid: string) {
  const r = await page.locator(`.card[data-sid="${sid}"]`).boundingBox();
  if (!r) throw new Error(`sin tarjeta ${sid}`);
  return r;
}
/** Alt + arrastrar de una tarjeta a otra abre el diálogo de reenvío con ese destino (mover.spec.ts). */
async function conectar(page: Page, from: string, to: string) {
  const p = await agarre(page, from);
  const destino = await caja(page, to);
  await page.keyboard.down("Alt");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move(destino.x + destino.width / 2, destino.y + destino.height / 2, { steps: 10 });
  await page.mouse.up();
  await page.keyboard.up("Alt");
}

test.describe('pantalla "Varias PCs" (menú ⋯ del header, plan §3.1 y §3.9)', () => {
  test("En esta red lista las PCs de la LAN y Emparejar precarga su IP y puerto", async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    // registrada despues de abrirTablero: gana sobre el [] del tablero fijo
    await page.route("**/peers/lan", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{ pc_id: "0123456789ab", name: "notebook", ip: "192.168.1.20", port: 7322, last_seen: iso(0) }]),
      }),
    );
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await expect(d.getByText("En esta red")).toBeVisible();
    await expect(d.locator(".pairing-lan")).toContainText("192.168.1.20:7322");
    await d.locator(".pairing-lan").getByRole("button", { name: "Emparejar" }).click();
    await expect(d.getByLabel("Host o IP")).toHaveValue("192.168.1.20");
    await expect(d.getByLabel("Puerto")).toHaveValue("7322");
  });

  test("sin nada emparejado, muestra el nombre propio y explica en dos líneas qué hace falta", async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await expect(d).toBeVisible();
    await expect(d).toContainText("oficina");
    await expect(d).toContainText("Sin ninguna PC emparejada todavía");
    await expect(d).toContainText("install.py --peer");
    await expect(d.locator(".pairing-peer")).toHaveCount(0);
  });

  test("con una PC emparejada, la lista muestra su estado", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    await abrirVariasPcs(page);
    const fila = dialogo(page).locator(".pairing-peer", { hasText: "notebook" });
    await expect(fila).toContainText("conectada");
  });

  test("una PC caída se distingue en la lista", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK_CAIDA]);
    await abrirVariasPcs(page);
    const fila = dialogo(page).locator(".pairing-peer", { hasText: "notebook" });
    await expect(fila).toContainText("sin conexión hace");
  });

  test("Quitar pide confirmar y, aceptado, borra DELETE /peers/<pc_id>", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    const borrados: string[] = [];
    await page.route("**/peers/*", async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      borrados.push(new URL(route.request().url()).pathname);
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await abrirVariasPcs(page);
    const fila = dialogo(page).locator(".pairing-peer", { hasText: "notebook" });

    page.once("dialog", (d) => d.dismiss());
    await fila.getByRole("button", { name: "Quitar" }).click();
    expect(borrados).toHaveLength(0);

    page.once("dialog", (d) => d.accept());
    await fila.getByRole("button", { name: "Quitar" }).click();
    await expect.poll(() => borrados).toEqual(["/peers/note-1"]);
  });

  test('"Mostrar frase" pide POST /peers/offer y muestra las seis palabras y la vigencia', async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    await page.route("**/peers/offer", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ phrase: "uno dos tres cuatro cinco seis", expires: Date.now() / 1000 + 300 }),
      }),
    );
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await d.getByRole("button", { name: "Mostrar frase" }).click();
    await expect(d.locator(".pairing-phrase")).toHaveText("uno dos tres cuatro cinco seis");
    await expect(d).toContainText(/vale \d+ s más/);
  });

  test('"Unirme a otra PC" manda phrase, host y el puerto 7322 por defecto, y el error del server se ve tal cual', async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    let body: Record<string, unknown> | null = null;
    await page.route("**/peers/join", async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "proof invalido" }) });
    });
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await d.getByRole("button", { name: "Unirme a otra PC" }).click();
    await expect(d.getByLabel("Puerto")).toHaveValue("7322");
    await d.getByLabel("Host o IP").fill("192.168.1.20");
    await d.getByLabel("Frase (seis palabras)").fill("uno dos tres cuatro cinco seis");
    await d.getByRole("button", { name: "Unirme", exact: true }).click();
    await expect(d).toContainText("proof invalido");
    expect(body).toMatchObject({ phrase: "uno dos tres cuatro cinco seis", host: "192.168.1.20", port: 7322 });
  });

  test("el nombre de esta PC se edita con ✎ y PUT /peers/self", async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    let body: Record<string, unknown> | null = null;
    await page.route("**/peers/self", async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pc_id: PEER_LOCAL.pc_id, name: "cocina", color: PEER_LOCAL.color }) });
    });
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await expect(d).toContainText("oficina");
    await d.getByRole("button", { name: "renombrar esta PC" }).click();
    await d.getByLabel("nuevo nombre de esta PC").fill("cocina");
    await d.getByRole("button", { name: "Guardar" }).click();
    await expect(d).toContainText("cocina");
    expect(body).toMatchObject({ name: "cocina" });
  });

  test("el error del server al renombrar se muestra tal cual", async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    await page.route("**/peers/self", (route) =>
      route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "el nombre no puede quedar vacio" }) }),
    );
    await abrirVariasPcs(page);
    const d = dialogo(page);
    await d.getByRole("button", { name: "renombrar esta PC" }).click();
    await d.getByLabel("nuevo nombre de esta PC").fill("x");
    await d.getByRole("button", { name: "Guardar" }).click();
    await expect(d).toContainText("el nombre no puede quedar vacio");
    // el error no aplica el borrador: al cancelar, sigue el nombre de antes
    await d.getByRole("button", { name: "Cancelar" }).click();
    await expect(d).toContainText("oficina");
  });
});

test.describe('"Coordinadora solo de esta PC" (menú ⋯ de la tarjeta, plan §3.6)', () => {
  test("no aparece con una sola PC", async ({ page }) => {
    await abrirTablero(page, sesiones(), [PEER_LOCAL]);
    const card = page.locator(`.card[data-sid="${SID.reglas}"]`);
    await card.locator(".kebab").click();
    await expect(card.getByRole("menuitem", { name: /Coordinadora solo de esta PC/ })).toHaveCount(0);
  });

  test("con más de una PC, aparece al lado de la coordinadora federada y manda scope: pc", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    const card = page.locator(`.card[data-sid="${SID.reglas}"]`);
    let body: Record<string, unknown> | null = null;
    await page.route(`**/sessions/${SID.reglas}/coordinator`, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, coordinator: true }) });
    });
    await card.locator(".kebab").click();
    await expect(card.getByRole("menuitem", { name: /☆ Coordinadora del repo/ })).toBeVisible();
    await card.getByRole("menuitem", { name: /Coordinadora solo de esta PC/ }).click();
    await expect.poll(() => body).toMatchObject({ on: true, scope: "pc" });
  });
});

test.describe("el selector de destino descarta las sesiones de una PC caída (App.tsx, ronda 3)", () => {
  test("una sesión de la PC caída no aparece como destino de Conectar", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK_CAIDA]);
    await conectar(page, SID.coordinadora, SID.mapas);
    await expect(page.locator(".fwd")).toBeVisible();
    const opciones = await page.locator(".fwd select option").allTextContents();
    expect(opciones.some((t) => t.includes("teorema"))).toBe(false);
    expect(opciones.some((t) => t.includes("demo"))).toBe(true);
  });

  test("con la PC de nuevo viva, sus sesiones vuelven a ofrecerse", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    await conectar(page, SID.coordinadora, SID.mapas);
    await expect(page.locator(".fwd")).toBeVisible();
    const opciones = await page.locator(".fwd select option").allTextContents();
    expect(opciones.some((t) => t.includes("teorema"))).toBe(true);
  });
});

test.describe("canal nativo entre PCs distintas (plan §3.5)", () => {
  test("no se ofrece entre dos sesiones de Claude Code de PCs distintas", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    // coordinadora (lienzo, PC local, claude) -> reglas (teorema, "note-1", claude): mismo agente, distinta PC
    await conectar(page, SID.coordinadora, SID.reglas);
    await expect(page.locator(".fwd")).toBeVisible();
    const nativo = page.locator(".fwd .modes label", { hasText: "Canal nativo" });
    await expect(nativo.locator("input")).toBeDisabled();
    await expect(page.locator(".fwd")).toContainText("ListAgents solo ve su propia PC");
  });

  test("se sigue ofreciendo entre dos sesiones de Claude Code de la misma PC", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [PEER_LOCAL, PEER_NOTEBOOK]);
    // coordinadora (lienzo) y mapas (demo): las dos sin `pc` (PC local), las dos claude
    await conectar(page, SID.coordinadora, SID.mapas);
    await expect(page.locator(".fwd")).toBeVisible();
    const nativo = page.locator(".fwd .modes label", { hasText: "Canal nativo" });
    await expect(nativo.locator("input")).toBeEnabled();
  });
});
