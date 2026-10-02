import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { abrirTablero, esperarQuietud, sesiones, SID } from "./tablero-fijo";
import type { Peer, Session } from "../src/types";

/** PICK_MS de Card.tsx: el click simple espera esto antes de elegir, por si llega el segundo. */
const PICK_MS = 240;
const Ctrl = { modifiers: ["Control" as const] };
const card = (page: Page, sid: string) => page.locator(`.card[data-sid="${sid}"]`);
const titulo = (page: Page, sid: string) => card(page, sid).locator(".title");
const marcadas = (page: Page) => page.locator(".card.marked");
const barra = (page: Page) => page.getByRole("region", { name: "selección de tarjetas" });
const iso = (minAgo: number) => new Date(Date.now() - minAgo * 60_000).toISOString();

/** Con pedido, ninguna es "libre": las libres del mismo repo y agente se pliegan en una sola tarjeta. */
function sinLibres(list: Session[]): Session[] {
  return list.map((s) => (s.last_prompt || s.last_reply ? s : { ...s, last_prompt: "pedido de prueba" }));
}
/** lienzo y demo en "oficina" (la local), teorema y viejo en "notebook" */
function conDosPc(): Session[] {
  return sinLibres(sesiones()).map((s) => (s.repo === "teorema" || s.repo === "viejo" ? { ...s, pc: "note-1" } : s));
}
const OFICINA: Peer = { pc_id: "local-1", name: "oficina", color: "#5b9cff", alive: true, last_seen: iso(0), local: true, health: { mem_free_gb: 3.4, mem_total_gb: 16, cpu_pct: 22, temp_c: 68 } };
const NOTEBOOK: Peer = { pc_id: "note-1", name: "notebook", color: "#f0b429", alive: true, last_seen: iso(0), local: false, health: { mem_free_gb: 2.1, mem_total_gb: 16, cpu_pct: 40, temp_c: 71 } };

/** cualquier cosa que no sea GET: Ctrl + click no tiene que escribirle a nadie */
function vigilarEscrituras(page: Page): string[] {
  const out: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET") out.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return out;
}

test.describe("selección múltiple de tarjetas (Ctrl + click)", () => {
  test("Ctrl + click suma y saca tarjetas, sin elegir, abrir el panel ni copiar o pegar", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    const escrituras = vigilarEscrituras(page);
    await expect(barra(page)).toHaveCount(0);

    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await expect(marcadas(page)).toHaveCount(2);
    await expect(card(page, SID.mapas)).toHaveAttribute("aria-pressed", "true");
    await expect(card(page, SID.reglas)).toHaveAttribute("aria-pressed", "false");
    await expect(barra(page)).toContainText("2 tarjetas");
    // es una marca propia: ni elegida (.picked) ni con el panel abierto (.sel)
    await page.waitForTimeout(PICK_MS + 200);
    await expect(card(page, SID.mapas)).not.toHaveClass(/\bpicked\b/);
    await expect(card(page, SID.mapas)).not.toHaveClass(/\bsel\b/);
    await expect(page.locator(".panel")).toHaveCount(0);
    await expect(page.locator(".workpreview")).toHaveCount(0);

    // el segundo Ctrl + click sobre una marcada la saca
    await titulo(page, SID.mapas).click(Ctrl);
    await expect(marcadas(page)).toHaveCount(1);
    await expect(card(page, SID.mapas)).not.toHaveClass(/\bmarked\b/);
    await expect(card(page, SID.mapas)).toHaveAttribute("aria-pressed", "false");
    await expect(barra(page)).toContainText("1 tarjeta");
    await expect(barra(page)).not.toContainText("1 tarjetas");

    // sacando la ultima, la barra se va
    await titulo(page, SID.capas).click(Ctrl);
    await expect(marcadas(page)).toHaveCount(0);
    await expect(barra(page)).toHaveCount(0);
    expect(escrituras).toEqual([]);
  });

  test("dos Ctrl + click seguidos cuentan los dos y no abren el panel", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click({ ...Ctrl, clickCount: 2, delay: 20 });
    // dos marcas sobre la misma tarjeta: queda sin marcar, y el doble click no abrio nada
    await expect(marcadas(page)).toHaveCount(0);
    await page.waitForTimeout(PICK_MS + 200);
    await expect(page.locator(".panel")).toHaveCount(0);
  });

  test("Ctrl + Espacio con la tarjeta enfocada la marca (teclado)", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await card(page, SID.mapas).focus();
    await page.keyboard.press("Control+Space");
    await expect(card(page, SID.mapas)).toHaveClass(/\bmarked\b/);
    await page.keyboard.press("Control+Space");
    await expect(marcadas(page)).toHaveCount(0);
  });

  test("un click simple conserva su efecto (elige) y limpia la selección múltiple", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await expect(marcadas(page)).toHaveCount(2);

    await titulo(page, SID.reglas).click();
    await expect(card(page, SID.reglas)).toHaveClass(/\bpicked\b/);
    await expect(marcadas(page)).toHaveCount(0);
    await expect(barra(page)).toHaveCount(0);
    await page.waitForTimeout(PICK_MS + 200);
    await expect(page.locator(".panel")).toHaveCount(0);
  });

  test("un click simple justo antes de un Ctrl + click no borra la selección que arranca", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.reglas).click();
    await titulo(page, SID.mapas).click(Ctrl); // dentro de los PICK_MS del click anterior
    await page.waitForTimeout(PICK_MS + 250);
    await expect(card(page, SID.mapas)).toHaveClass(/\bmarked\b/);
    await expect(barra(page)).toContainText("1 tarjeta");
  });

  test("Esc limpia la selección, una capa por vez", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.reglas).click(); // elegida
    await expect(card(page, SID.reglas)).toHaveClass(/\bpicked\b/);
    await page.waitForTimeout(PICK_MS + 100);
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await expect(marcadas(page)).toHaveCount(2);

    // primero la selección múltiple; la elegida se queda
    await page.keyboard.press("Escape");
    await expect(marcadas(page)).toHaveCount(0);
    await expect(barra(page)).toHaveCount(0);
    await expect(card(page, SID.reglas)).toHaveClass(/\bpicked\b/);
    // el siguiente Esc suelta la elegida
    await page.keyboard.press("Escape");
    await expect(card(page, SID.reglas)).not.toHaveClass(/\bpicked\b/);
  });

  test("con el panel abierto, el primer Esc cierra el panel y la selección sigue", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await titulo(page, SID.reglas).dblclick();
    await expect(page.locator(".panel")).toHaveCount(1);
    await expect(marcadas(page)).toHaveCount(2);

    await page.keyboard.press("Escape");
    await expect(page.locator(".panel")).toHaveCount(0);
    await expect(marcadas(page)).toHaveCount(2);
    await page.keyboard.press("Escape");
    await expect(marcadas(page)).toHaveCount(0);
  });

  test("Limpiar vacía la selección", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click(Ctrl);
    await barra(page).getByRole("button", { name: "Limpiar" }).click();
    await expect(marcadas(page)).toHaveCount(0);
    await expect(barra(page)).toHaveCount(0);
  });

  test("la barra es una región con aria-live y no se sale de la pantalla a 390 px", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click(Ctrl);
    await expect(barra(page).locator('[aria-live="polite"]').first()).toContainText("1 tarjeta");
    await page.setViewportSize({ width: 390, height: 800 });
    await esperarQuietud(page);
    const caja = await barra(page).boundingBox();
    expect(caja).not.toBeNull();
    expect(caja!.x).toBeGreaterThanOrEqual(0);
    expect(caja!.x + caja!.width).toBeLessThanOrEqual(390);
  });
});

test.describe("«Enviar a todas», «Interrumpir» y «Marcar las visibles»", () => {
  test("Enviar a todas manda el texto a cada una, de a una", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    const envios: { sid: string; body: unknown }[] = [];
    await page.route("**/sessions/*/send", async (route) => {
      const sid = new URL(route.request().url()).pathname.split("/")[2];
      envios.push({ sid, body: route.request().postDataJSON() });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ chars: 9 }) });
    });
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await titulo(page, SID.reglas).click(Ctrl);

    await barra(page).getByRole("button", { name: "Enviar a todas" }).click();
    const caja = barra(page).getByRole("textbox");
    await caja.fill("Continuá con lo tuyo");
    await barra(page).getByRole("button", { name: "Enviar a 3" }).click();

    await expect(barra(page)).toContainText("3 ok / 0 fallaron");
    expect(envios.map((e) => e.sid)).toEqual([SID.mapas, SID.capas, SID.reglas]);
    for (const e of envios) expect(e.body).toEqual({ text: "Continuá con lo tuyo", attachments: [] });
    // todo salió bien: la caja se cierra y la selección sigue (para poder interrumpir o seguir)
    await expect(barra(page).getByRole("textbox")).toHaveCount(0);
    await expect(marcadas(page)).toHaveCount(3);
  });

  test("si una falla, las demás siguen y se cuenta «N ok / M fallaron» con el motivo", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    const llamadas: string[] = [];
    await page.route("**/sessions/*/send", async (route) => {
      const sid = new URL(route.request().url()).pathname.split("/")[2];
      llamadas.push(sid);
      const falla = sid === SID.capas;
      await route.fulfill({ status: falla ? 409 : 200, contentType: "application/json", body: JSON.stringify(falla ? { error: "ocupada" } : { chars: 4 }) });
    });
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.capas).click(Ctrl);
    await titulo(page, SID.reglas).click(Ctrl);
    await barra(page).getByRole("button", { name: "Enviar a todas" }).click();
    await barra(page).getByRole("textbox").fill("hola");
    await barra(page).getByRole("button", { name: "Enviar a 3" }).click();

    await expect(barra(page)).toContainText("2 ok / 1 fallaron");
    await expect(barra(page).getByRole("listitem")).toHaveCount(1);
    await expect(barra(page).getByRole("listitem")).toContainText("Importador de capas");
    await expect(barra(page).getByRole("listitem")).toContainText("ocupada");
    expect(llamadas).toEqual([SID.mapas, SID.capas, SID.reglas]);
    // con una falla la caja queda abierta, con el texto, para reintentar
    await expect(barra(page).getByRole("textbox")).toHaveValue("hola");
  });

  test("Esc dentro de la caja cierra la caja y no la selección", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await titulo(page, SID.mapas).click(Ctrl);
    await barra(page).getByRole("button", { name: "Enviar a todas" }).click();
    await barra(page).getByRole("textbox").press("Escape");
    await expect(barra(page).getByRole("textbox")).toHaveCount(0);
    await expect(marcadas(page)).toHaveCount(1);
  });

  test("Interrumpir llama a interrupt de cada tarjeta marcada", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    const llamadas: string[] = [];
    await page.route("**/sessions/*/interrupt", async (route) => {
      llamadas.push(new URL(route.request().url()).pathname.split("/")[2]);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });
    await titulo(page, SID.mapas).click(Ctrl);
    await titulo(page, SID.reglas).click(Ctrl);
    await barra(page).getByRole("button", { name: "Interrumpir" }).click();
    await expect(barra(page)).toContainText("2 ok / 0 fallaron");
    expect(llamadas).toEqual([SID.mapas, SID.reglas]);
  });

  test("las de otra PC entran igual en el envío", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [OFICINA, NOTEBOOK]);
    const llamadas: string[] = [];
    await page.route("**/sessions/*/send", async (route) => {
      llamadas.push(new URL(route.request().url()).pathname.split("/")[2]);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ chars: 2 }) });
    });
    await titulo(page, SID.coordinadora).click(Ctrl); // oficina
    await titulo(page, SID.reglas).click(Ctrl); // notebook
    await barra(page).getByRole("button", { name: "Enviar a todas" }).click();
    await barra(page).getByRole("textbox").fill("ok");
    await barra(page).getByRole("button", { name: "Enviar a 2" }).click();
    await expect(barra(page)).toContainText("2 ok / 0 fallaron");
    expect(llamadas).toEqual([SID.coordinadora, SID.reglas]);
  });

  test("Marcar las visibles respeta los filtros: proyectos y PC, de a varios", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [OFICINA, NOTEBOOK]);
    // dos proyectos a la vez: lienzo (3, oficina) y teorema (2, notebook)
    await page.locator(".pjchip", { hasText: "lienzo" }).click(Ctrl);
    await page.locator(".pjchip", { hasText: "teorema" }).click(Ctrl);
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(5);

    await titulo(page, SID.coordinadora).click(Ctrl); // una para que aparezca la barra
    await barra(page).getByRole("button", { name: "Marcar las visibles" }).click();
    await expect(marcadas(page)).toHaveCount(5);
    await expect(barra(page)).toContainText("5 tarjetas");
    await expect(card(page, SID.mapas)).toHaveCount(0); // demo no se ve, y tampoco se marcó
    await expect(barra(page).getByRole("button", { name: "Marcar las visibles" })).toBeDisabled();

    // con la PC notebook sola, las visibles son solo las de teorema; las de antes siguen marcadas
    await barra(page).getByRole("button", { name: "Limpiar" }).click();
    await page.locator(".pcchip", { hasText: "notebook" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(2);
    await titulo(page, SID.reglas).click(Ctrl);
    await barra(page).getByRole("button", { name: "Marcar las visibles" }).click();
    await expect(barra(page)).toContainText("2 tarjetas");
    await expect(card(page, SID.migracion)).toHaveClass(/\bmarked\b/);
    await expect(card(page, SID.reglas)).toHaveClass(/\bmarked\b/);
  });

  test("Marcar las visibles deja afuera las tarjetas a las que no se puede escribir", async ({ page }) => {
    const lista = sinLibres(sesiones()).map((s) => (s.session_id === SID.mapas ? { ...s, no_console: true } : s));
    await abrirTablero(page, lista);
    await expect(card(page, SID.mapas)).toHaveCount(1); // se ve...
    await titulo(page, SID.coordinadora).click(Ctrl);
    await barra(page).getByRole("button", { name: "Marcar las visibles" }).click();
    await expect(card(page, SID.mapas)).not.toHaveClass(/\bmarked\b/); // ...pero no se marca
    await expect(card(page, SID.capas)).toHaveClass(/\bmarked\b/);
    await expect(barra(page).getByRole("button", { name: "Marcar las visibles" })).toBeDisabled();
  });
});

test.describe("Ctrl + click en los chips de proyecto y de PC: filtro de varios a la vez", () => {
  test("proyectos: Ctrl + click suma y saca; el click simple deja uno solo", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    const chip = (t: string) => page.locator(".pjchip", { hasText: t });

    await chip("demo").click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(3);

    await chip("teorema").click(Ctrl);
    await esperarQuietud(page);
    await expect(chip("demo")).toHaveClass(/\bon\b/);
    await expect(chip("teorema")).toHaveClass(/\bon\b/);
    await expect(chip("demo")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".pjchip.all")).not.toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(5);

    // sumar un tercero y sacar uno
    await chip("lienzo").click(Ctrl);
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(8);
    await chip("demo").click(Ctrl);
    await esperarQuietud(page);
    await expect(chip("demo")).not.toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(5);

    // el click simple deja solo ese
    await chip("teorema").click();
    await esperarQuietud(page);
    await expect(page.locator(".pjchip.on")).toHaveText([/teorema/]);
    await expect(page.locator(".card")).toHaveCount(2);

    // sacar el último vuelve a «todos»
    await chip("teorema").click(Ctrl);
    await esperarQuietud(page);
    await expect(page.locator(".pjchip.on")).toHaveText(["Todos"]);
    await expect(page.locator(".card")).toHaveCount(8);
  });

  test("la elección de varios proyectos persiste al refrescar", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await page.locator(".pjchip", { hasText: "demo" }).click();
    await page.locator(".pjchip", { hasText: "teorema" }).click(Ctrl);
    await esperarQuietud(page);
    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".pjchip.on")).toHaveText([/demo/, /teorema/]);
    await expect(page.locator(".card")).toHaveCount(5);
  });

  test("PCs: Ctrl + click suma y saca; el click simple deja una sola", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [OFICINA, NOTEBOOK]);
    const chip = (t: string) => page.locator(".pcchip", { hasText: t });

    await chip("notebook").click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(2);

    await chip("oficina").click(Ctrl);
    await esperarQuietud(page);
    await expect(chip("notebook")).toHaveClass(/\bon\b/);
    await expect(chip("oficina")).toHaveClass(/\bon\b/);
    await expect(chip("oficina")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".pcchip.all")).not.toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(8);

    await chip("notebook").click(Ctrl);
    await esperarQuietud(page);
    await expect(chip("notebook")).not.toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(6);

    // el click simple deja solo esa
    await chip("oficina").click(Ctrl);
    await chip("notebook").click();
    await esperarQuietud(page);
    await expect(chip("oficina")).not.toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(2);

    // sacar la última vuelve a «Todas»
    await chip("notebook").click(Ctrl);
    await esperarQuietud(page);
    await expect(page.locator(".pcchip.all")).toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(8);
  });

  test("PCs: la elección de varias persiste, y el valor viejo (un pc_id suelto) se migra", async ({ page }) => {
    await abrirTablero(page, conDosPc(), [OFICINA, NOTEBOOK]);
    await page.locator(".pcchip", { hasText: "notebook" }).click();
    await page.locator(".pcchip", { hasText: "oficina" }).click(Ctrl);
    await esperarQuietud(page);
    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".pcchip.on")).toHaveCount(2);
    await expect(page.locator(".card")).toHaveCount(8);

    // formato anterior: un string suelto en lienzo.pcFilter
    await page.evaluate(() => {
      localStorage.removeItem("lienzo.pcFilters");
      localStorage.setItem("lienzo.pcFilter", "note-1");
    });
    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".pcchip.on")).toHaveText([/notebook/]);
    await expect(page.locator(".card")).toHaveCount(2);
  });
});
