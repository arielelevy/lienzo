import { expect, test } from "@playwright/test";
import { abrirTablero, esperarQuietud, sesiones, SID } from "./tablero-fijo";
import { desborde } from "./medidas";
import type { Page } from "@playwright/test";
import type { Peer, Session } from "../src/types";

const iso = (minAgo: number) => new Date(Date.now() - minAgo * 60_000).toISOString();

/** Las diez sesiones de siempre, repartidas en dos PCs: lienzo y demo en "oficina" (la PC local,
 *  sin `pc`: asi se prueba tambien el caso sin ese campo, que es lo que hay hasta que el frente B
 *  lo agregue), teorema y viejo en "notebook". 6 y 4, para que "Todas 10" y los dos chips midan
 *  contra numeros distintos entre si. */
function sesionesConDosPc(): Session[] {
  return sesiones().map((s) => (s.repo === "teorema" || s.repo === "viejo" ? { ...s, pc: "note-1" } : s));
}

/** Se abre a lo ancho (abrirTablero espera las tres columnas, que a 390 px son una sola) y despues
 *  se achica, como las pruebas de ancho de tablero.spec.ts. */
async function angosta(page: Page) {
  await page.setViewportSize({ width: 390, height: 800 });
  await esperarQuietud(page);
  const d = await desborde(page);
  expect(d.scroll).toBe(0);
  expect(d.culpables).toEqual([]);
}

/** Con pedido, ninguna es "libre": las libres del mismo repo y agente se pliegan en una sola
 *  tarjeta, y estas pruebas cuentan tarjetas como si fueran sesiones. */
function sinLibres(list: Session[]): Session[] {
  return list.map((s) => (s.last_prompt || s.last_reply ? s : { ...s, last_prompt: "pedido de prueba" }));
}

const PEER_LOCAL: Peer = {
  pc_id: "local-1",
  name: "oficina",
  color: "#5b9cff",
  alive: true,
  last_seen: iso(0),
  local: true,
  health: { mem_free_gb: 3.4, mem_total_gb: 16, cpu_pct: 22, temp_c: 68 },
};

/** La de al lado, caida: cubre a la vez "con dos PCs, la tira muestra..." y "un peer caido deja sus
 *  tarjetas grises", que son casos independientes (nada impide que ademas este caida). */
const PEER_NOTEBOOK_CAIDA: Peer = {
  pc_id: "note-1",
  name: "notebook",
  color: "#f0b429",
  alive: false,
  last_seen: iso(42),
  local: false,
  health: { mem_free_gb: 2.1, mem_total_gb: 16, cpu_pct: 40, temp_c: 71 },
};

const PEER_NOTEBOOK_VIVA: Peer = { ...PEER_NOTEBOOK_CAIDA, alive: true, last_seen: iso(0) };

test.describe("tira de PCs (§3.9 del plan)", () => {
  test("sin peers emparejados no hay tira, aunque haya varias PCs en las sesiones", async ({ page }) => {
    // GET /peers todavia no existe (404) o no viene: en los dos casos, nada cambia a la vista
    await abrirTablero(page, sinLibres(sesionesConDosPc()));
    await expect(page.locator(".pcstrip")).toHaveCount(0);
  });

  test("con un solo peer (la propia PC) tampoco aparece", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()), [PEER_LOCAL]);
    await expect(page.locator(".pcstrip")).toHaveCount(0);
  });

  test("con dos, muestra Todas N y un chip por PC con conteo, memoria y temperatura", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    const strip = page.locator(".pcstrip");
    await expect(strip.locator(".pcchip.all")).toHaveText("Todas10");
    const oficina = strip.locator(".pcchip", { hasText: "oficina" });
    await expect(oficina).toContainText("6");
    await expect(oficina).toContainText("3.4 GB");
    await expect(oficina).toContainText("68 °C");
    const notebook = strip.locator(".pcchip", { hasText: "notebook" });
    await expect(notebook).toContainText("4");
    await expect(notebook).toContainText("2.1 GB");
    await expect(notebook).toContainText("71 °C");
    await expect(oficina).toContainText("CPU 22%");
    await expect(oficina).not.toHaveClass(/alerta/);
  });

  test("una PC caliente o sin memoria para otro agente se marca en rojo y dice por que", async ({ page }) => {
    const caliente: Peer = {
      ...PEER_NOTEBOOK_VIVA,
      latencia_ms: 120,
      health: {
        mem_free_gb: 1.2,
        mem_total_gb: 16,
        cpu_pct: 90,
        temp_c: 95,
        agentes_libres: 0,
        git_auth: { "https://git.ejemplo.com/a.git": "vencida" },
      },
    };
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, caliente]);
    const notebook = page.locator(".pcstrip .pcchip", { hasText: "notebook" });
    await expect(notebook).toHaveClass(/alerta/);
    await expect(notebook).toContainText("120 ms");
    await expect(notebook).toHaveAttribute("title", /a 95 °C y sin memoria para otro agente — git: vencida \(git\.ejemplo\.com\)/);
  });

  test("la credencial de git va aparte, en violeta y con el motivo, sin marcar la PC en rojo", async ({ page }) => {
    const sinGit: Peer = {
      ...PEER_NOTEBOOK_VIVA,
      health: {
        mem_free_gb: 6,
        mem_total_gb: 16,
        cpu_pct: 20,
        temp_c: 50,
        agentes_libres: 3,
        git_auth: { "https://git.ejemplo.com/a.git": "timeout", "https://otro.ejemplo.com/b.git": "sin_red" },
      },
    };
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, sinGit]);
    const notebook = page.locator(".pcstrip .pcchip", { hasText: "notebook" });
    await expect(notebook).not.toHaveClass(/alerta/);
    const git = notebook.locator(".git");
    await expect(git).toContainText("git: timeout (git.ejemplo.com), sin red (otro.ejemplo.com)");
    await expect(git).toHaveCSS("color", "rgb(217, 70, 239)");
    await expect(page.locator(".pcstrip .pcchip", { hasText: "oficina" }).locator(".git")).toHaveCount(0);
  });

  test("click en un chip filtra a esa PC y nada mas; se vuelve con Todas", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    await expect(page.locator(".card")).toHaveCount(8);

    await page.locator(".pcchip", { hasText: "notebook" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(2);
    await expect(page.locator(`.card[data-sid="${SID.reglas}"]`)).toBeVisible();
    await expect(page.locator(`.card[data-sid="${SID.coordinadora}"]`)).toHaveCount(0);
    await expect(page.locator(".pcchip", { hasText: "notebook" })).toHaveClass(/\bon\b/);

    await page.locator(".pcchip", { hasText: "notebook" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(2);
    await page.locator(".pcchip.all").click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(8);
    await expect(page.locator(".pcchip.all")).toHaveClass(/\bon\b/);
  });

  test("el filtro de PC persiste al refrescar", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    await page.locator(".pcchip", { hasText: "oficina" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(6);

    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(6);
    await expect(page.locator(".pcchip", { hasText: "oficina" })).toHaveClass(/\bon\b/);
  });

  test("con un filtro guardado y /peers caido, el tablero no queda vacio", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    await page.locator(".pcchip", { hasText: "notebook" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(2);

    // la ruta registrada despues gana: ahora /peers no responde, y sin tira no hay filtro posible
    await page.route("**/peers", (route) => route.fulfill({ status: 404, body: "{}" }));
    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".pcstrip")).toHaveCount(0);
    await expect(page.locator(".card")).toHaveCount(8);
  });

  test("un peer caido deja sus tarjetas grises, con 'sin conexión hace X' y sin botones de acción", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_CAIDA]);
    // una tarjeta de "notebook" (caida): gris, sin conexión, sin ningún botón
    const migracion = page.locator(`.card[data-sid="${SID.migracion}"]`);
    await expect(migracion).toHaveClass(/\bpeerdown\b/);
    await expect(migracion).toContainText("sin conexión hace");
    await expect(migracion.locator("button")).toHaveCount(0);
    // el chip de esa PC se distingue de una viva
    await expect(page.locator(".pcchip", { hasText: "notebook" })).toHaveClass(/\bdown\b/);
    // la de "oficina" (viva) sigue con sus botones de siempre
    const coordinadora = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
    await expect(coordinadora).not.toHaveClass(/\bpeerdown\b/);
    await expect(coordinadora.locator("button").first()).toBeVisible();
  });

  test("cada tarjeta lleva el color de su PC", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    const oficina = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
    const notebook = page.locator(`.card[data-sid="${SID.reglas}"]`);
    await expect(oficina).toHaveClass(/\bhaspc\b/);
    await expect(notebook).toHaveClass(/\bhaspc\b/);
    const colorDe = (loc: typeof oficina) => loc.evaluate((el) => (el as HTMLElement).style.getPropertyValue("--pc-color"));
    expect(await colorDe(oficina)).toBe(PEER_LOCAL.color);
    expect(await colorDe(notebook)).toBe(PEER_NOTEBOOK_VIVA.color);
  });

  test("nada se sale de la pantalla a 390 px de ancho", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesionesConDosPc()), [PEER_LOCAL, PEER_NOTEBOOK_VIVA]);
    await angosta(page);
  });
});

/** El tablero fijo de siempre junta cuatro repos (lienzo 3, demo 3, teorema 2, viejo 2) y una sola
 *  coordinadora (en lienzo). De las diez se ven ocho: las dos de "viejo" las esconde el tablero por
 *  su cuenta (una muerta en la columna colapsada, otra vieja), asi que los conteos parten de 8. */
test.describe("chips de proyecto: repo y ★ Coordinadoras (pedido de Ariel)", () => {
  const card = (page: Page, sid: string) => page.locator(`.card[data-sid="${sid}"]`);

  test("con un solo repo en el tablero no aparecen", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()).map((s) => ({ ...s, repo: "lienzo" })));
    await expect(page.locator(".pjstrip")).toHaveCount(0);
  });

  test("van en el header, afuera del fondo del buscador, uno por repo con su conteo", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await expect(page.locator("header .search .pjchip")).toHaveCount(0);
    const strip = page.locator("header > .pjstrip");
    await expect(strip.locator(".pjchip", { hasText: "lienzo" })).toContainText("3");
    await expect(strip.locator(".pjchip", { hasText: "demo" })).toContainText("3");
    await expect(strip.locator(".pjchip", { hasText: "teorema" })).toContainText("2");
    await expect(strip.locator(".pjchip.star")).toHaveText("★ Coordinadoras");
  });

  test("por defecto no hay ninguno elegido y se ve todo; el click elige y nada mas", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await expect(page.locator(".pjchip.on")).toHaveText(["Todos"]);
    await expect(page.locator(".card")).toHaveCount(8);

    await page.locator(".pjchip", { hasText: "demo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".pjchip", { hasText: "demo" })).toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(3);
    await expect(card(page, SID.mapas)).toBeVisible();
    await expect(card(page, SID.coordinadora)).toHaveCount(0);

    // otro click sobre el elegido no lo suelta
    await page.locator(".pjchip", { hasText: "demo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(3);

    // elegir otro lo reemplaza: un proyecto por vez
    await page.locator(".pjchip", { hasText: "teorema" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".pjchip.on")).toHaveText([/teorema/]);
    await expect(page.locator(".card")).toHaveCount(2);

    // se vuelve con Todos
    await page.locator(".pjchip.all").click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(8);
    await expect(page.locator(".pjchip.on")).toHaveText(["Todos"]);
  });

  test("★ Coordinadoras muestra las coordinadoras de los proyectos elegidos", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    // sin proyecto elegido: todas las coordinadoras (en el tablero fijo, solo la de lienzo)
    await page.locator(".pjchip.star").click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(1);
    await expect(card(page, SID.coordinadora)).toBeVisible();

    // eligiendo demo, que no tiene coordinadora: no queda ninguna
    await page.locator(".pjchip", { hasText: "demo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(0);

    // eligiendo lienzo vuelve la suya
    await page.locator(".pjchip", { hasText: "lienzo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(1);
    await expect(card(page, SID.coordinadora)).toBeVisible();
  });

  test("la elección persiste al refrescar", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await page.locator(".pjchip", { hasText: "demo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(3);

    await page.reload();
    await page.waitForSelector(".card");
    await esperarQuietud(page);
    await expect(page.locator(".pjchip", { hasText: "demo" })).toHaveClass(/\bon\b/);
    await expect(page.locator(".card")).toHaveCount(3);
  });

  test("se combina con los chips de agente (Y lógico)", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await page.locator(".pjchip", { hasText: "demo" }).click();
    await esperarQuietud(page);
    await expect(page.locator(".card")).toHaveCount(3);

    await page.locator("header .chip.codex").click();
    await esperarQuietud(page);
    await expect(card(page, SID.mapas)).toBeVisible();
    const quedan = await page.locator(".card").count();
    expect(quedan).toBeLessThan(3);
  });

  test("nada se sale de la pantalla a 390 px de ancho", async ({ page }) => {
    await abrirTablero(page, sinLibres(sesiones()));
    await angosta(page);
  });
});
