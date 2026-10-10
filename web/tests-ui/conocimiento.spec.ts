import { expect, test, type Page, type Route } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

// Se ejecutan contra el bundle real. Sólo la API de conocimiento usa fixtures;
// ninguna prueba crea proyectos, cambia estados ni escribe en sesiones reales.
const node = (texto: string, estado = "propuesto") => ({
  id: "hallazgo-api", tipo: "hallazgo", texto, estado, autor: "frente H",
  estado_por: null, datos: { donde: "lienzo/server.py:dispatch", gravedad: "media" },
  origen: { sesion: "fixture-H" }, fecha: "2026-10-08T20:00:00Z", ronda: null,
  procedencia: ["bm25:API"], puntaje: -0.2, salto: 0,
  vinculos: [{ de: "hallazgo-api", relacion: "apoya", a: "evidencia-1", motivo: "Prueba declarada" }],
});
const projectList = [{ id: "lienzo", nombre: "Lienzo" }, { id: "demo", nombre: "Otro proyecto" }];
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const defaults = (path: string) => {
  if (path === "/conocimiento/proyectos") return projectList;
  if (path.endsWith("/temas")) return { temas: [{ id: "tema-api", texto: "API", aliases: [], nodos: 3 }] };
  if (path.endsWith("/briefing")) return { proyecto: "lienzo", vigente: [node("**Ruta validada**", "confirmado")], abierto: [node("Falta medir el caso real")], otros: [], temas_sin_resolver: [], cambios: { cambios: [], truncado: false }, avisos: { disponible: true, apoyos_rechazados: [], reglas_cuestionadas: [], recurrencias: [] } };
  if (path.endsWith("/preguntar")) return { total: 1, offset: 0, limite: 100, siguientes: null, candidatos: [node("El resultado con su evidencia")], temas_sin_resolver: ["tema ausente"] };
  if (path.endsWith("/vista")) return { tema: "tema-api", texto: "API", markdown: "## API\n\n### Vigente\n\n- **Ruta validada** (nodo:hallazgo-api)\n\n| Estado | Motivo |\n|---|---|\n| vigente | contrato verificado |\n\n[Referencia](https://example.com/evidencia)\n\n<script>window.knowledgeUnsafe = true</script>\n\n![Remota](https://example.com/image.png)" };
  if (path.endsWith("/pendientes")) return { ronda: null, total: 1, pendientes: [{ ...node("Entrega que espera revisión"), tardia: true }] };
  if (path.endsWith("/avisos")) return [{ id: "decision-1", texto: "Decisión con apoyo rechazado", tipo: "decision", estado: "vigente", respaldos_caidos: ["hallazgo-0"], cadenas: [["decision-1", "hallazgo-0"]] }];
  return { error: "fixture sin ruta" };
};
async function prepare(page: Page) {
  const requests: { method: string; url: string }[] = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/conocimiento")) requests.push({ method: request.method(), url: request.url() }); });
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route("**/conocimiento/**", async route => {
    if (route.request().method() !== "GET") return json(route, { error: "la prueba no escribe" }, 403);
    return json(route, defaults(new URL(route.request().url()).pathname));
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "más opciones", exact: true }).click();
  await page.getByRole("menuitem", { name: /Memoria/ }).click();
  await expect(page.getByRole("dialog", { name: "Memoria del proyecto" })).toBeVisible();
  return requests;
}
async function selectProject(page: Page, id = "lienzo") {
  await page.getByLabel("Proyecto", { exact: true }).selectOption(id);
  await expect(page.getByRole("button", { name: "Leer briefing", exact: true })).toBeVisible();
}

test("selección explícita, navegación, recarga y cierre sin escrituras", async ({ page }) => {
  const requests = await prepare(page);
  await expect(page.getByLabel("Proyecto", { exact: true })).toHaveValue("");
  expect(requests.every(r => new URL(r.url).pathname === "/conocimiento/proyectos")).toBe(true);
  await selectProject(page);
  await page.getByRole("button", { name: "Leer briefing", exact: true }).click();
  await expect(page.getByText("Ruta validada", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cerrar memoria" }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("dialog")).toContainText("Ruta validada");
  expect(await page.evaluate(() => document.querySelector('[role="dialog"]')?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Memoria del proyecto" })).toHaveCount(0);
  expect(await page.locator("#root").evaluate(el => (el as HTMLElement).inert)).toBe(false);
  await page.reload();
  await page.getByRole("button", { name: "más opciones", exact: true }).click();
  await page.getByRole("menuitem", { name: /Memoria/ }).click();
  await expect(page.getByLabel("Proyecto", { exact: true })).toHaveValue("");
  expect(requests.every(r => r.method === "GET")).toBe(true);
});

test("catálogo fallido y vacío se muestran y permiten reintentar", async ({ page }) => {
  let attempt = 0;
  await page.route("**/conocimiento/proyectos", route => json(route, ++attempt === 1 ? { error: "base inaccesible" } : [], attempt === 1 ? 503 : 200));
  // Este caso monta el tablero sin el catálogo por defecto de prepare.
  await bloquearEscrituras(page); await instalarTablero(page);
  await page.goto(BASE);
  await page.getByRole("button", { name: "más opciones", exact: true }).click();
  await page.getByRole("menuitem", { name: /Memoria/ }).click();
  await expect(page.getByRole("alert")).toContainText("base inaccesible");
  await page.getByRole("button", { name: "Actualizar proyectos" }).click();
  await expect(page.getByText(/No hay proyectos registrados/)).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("briefing conserva consultas repetidas, estado, origen y vínculos", async ({ page }) => {
  await prepare(page); await selectProject(page);
  await page.getByLabel("Consultas, una por línea").fill('"base compartida"\nAPI OR permisos');
  await page.getByText("Filtrar por archivos o temas", { exact: true }).click();
  await page.getByLabel("Archivos o carpetas, uno por línea").fill("web/src/\nlienzo/server.py");
  await page.getByLabel("Temas, uno por línea").fill("API\nseguridad");
  const requested = page.waitForRequest(r => new URL(r.url()).pathname === "/conocimiento/lienzo/briefing");
  await page.getByRole("button", { name: "Leer briefing", exact: true }).click();
  const url = new URL((await requested).url());
  expect(url.searchParams.getAll("q")).toEqual(['"base compartida"', "API OR permisos"]);
  expect(url.searchParams.getAll("archivos")).toEqual(["web/src/", "lienzo/server.py"]);
  expect(url.searchParams.getAll("temas")).toEqual(["API", "seguridad"]);
  await expect(page.getByRole("heading", { name: "Vigente", exact: true })).toBeVisible();
  await expect(page.getByText("confirmado", { exact: true })).toBeVisible();
  await page.getByText("Origen y respaldo · hallazgo-api", { exact: true }).first().click();
  await expect(page.getByText("lienzo/server.py:dispatch", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Prueba declarada", { exact: true }).first()).toBeVisible();
});

test("búsqueda valida vacío y exceso, muestra error FTS y acepta sólo la respuesta nueva", async ({ page }) => {
  const requests = await prepare(page); await selectProject(page);
  await page.getByRole("button", { name: "Buscar", exact: true }).first().click();
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByRole("alert")).toContainText("Escribí una consulta");
  expect(requests.some(r => new URL(r.url).pathname.endsWith("/preguntar"))).toBe(false);
  await page.getByLabel("Consultas, una por línea").fill(Array.from({ length: 11 }, (_, i) => "q" + i).join("\n"));
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByRole("alert")).toContainText("hasta 10 consultas");
  await page.route("**/conocimiento/lienzo/preguntar?**", route => {
    const q = new URL(route.request().url()).searchParams.get("q");
    return q === '"' ? json(route, { error: "consulta FTS invalida: cadena sin cerrar" }, 400) : json(route, defaults("/preguntar"));
  });
  await page.getByLabel("Consultas, una por línea").fill('"');
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByRole("alert")).toContainText("consulta FTS invalida");
  await page.getByLabel("Consultas, una por línea").fill("API");
  await page.getByLabel("Saltos de relaciones").selectOption("2");
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByText("El resultado con su evidencia", { exact: true })).toBeVisible();
  await expect(page.getByText("tema ausente", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(new URL(requests.at(-1)!.url).searchParams.get("saltos")).toBe("2");
});

test("cambiar proyecto durante una lectura descarta el resultado tardío", async ({ page }) => {
  await prepare(page); await selectProject(page);
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/conocimiento/lienzo/briefing?**", async route => {
    await delayed;
    await json(route, { ...defaults("/briefing"), vigente: [node("Respuesta antigua del proyecto Lienzo")] });
  });
  const requested = page.waitForRequest(r => new URL(r.url()).pathname === "/conocimiento/lienzo/briefing");
  await page.getByRole("button", { name: "Leer briefing", exact: true }).click(); await requested;
  await selectProject(page, "demo");
  release();
  await page.getByRole("button", { name: "Leer briefing", exact: true }).click();
  await expect(page.getByText("Ruta validada", { exact: true })).toBeVisible();
  await expect(page.getByText("Respuesta antigua del proyecto Lienzo", { exact: true })).toHaveCount(0);
});

test("vista Markdown legible y segura en móvil sin desbordes", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await prepare(page); await selectProject(page);
  const closeButton = page.getByRole("button", { name: "Cerrar memoria" });
  await closeButton.click({ trial: true });
  const headingTop = await page.getByRole("heading", { name: "Memoria del proyecto", exact: true }).evaluate(el => el.getBoundingClientRect().top);
  expect(headingTop).toBeGreaterThanOrEqual(8);
  await page.getByRole("button", { name: "Vista por tema", exact: true }).click();
  await page.getByRole("button", { name: "Generar vista", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Elegí un tema");
  await page.getByLabel("Tema de la vista").selectOption("tema-api");
  await page.getByRole("button", { name: "Generar vista", exact: true }).click();
  await expect(page.getByRole("heading", { name: "API", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "contrato verificado", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Referencia" })).toHaveAttribute("href", "https://example.com/evidencia");
  expect(await page.evaluate(() => (window as unknown as { knowledgeUnsafe?: boolean }).knowledgeUnsafe)).toBeUndefined();
  await expect(page.getByRole("dialog").locator("img")).toHaveCount(0);
  const overflow = await page.getByRole("dialog").evaluate(el => ({ inner: el.scrollWidth - el.clientWidth, right: el.getBoundingClientRect().right, viewport: window.innerWidth }));
  expect(overflow.inner).toBeLessThanOrEqual(1); expect(overflow.right).toBeLessThanOrEqual(overflow.viewport);
  expect(requests.every(r => r.method === "GET")).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("memoria-movil.png") });
});

test("pendientes preservados aunque fallen los avisos", async ({ page }, testInfo) => {
  await prepare(page); await selectProject(page);
  await page.route("**/conocimiento/lienzo/avisos", route => json(route, { error: "no se pudieron leer los respaldos" }, 503));
  await page.getByRole("button", { name: "Pendientes y avisos", exact: true }).click();
  await page.getByRole("button", { name: "Leer pendientes y avisos", exact: true }).click();
  await expect(page.getByText("Entrega que espera revisión", { exact: true })).toBeVisible();
  await expect(page.getByText("Entrega tardía", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("no se pudieron leer los respaldos");
  await page.screenshot({ path: testInfo.outputPath("memoria-pendientes.png") });
});


test("paginación mantiene filtros, vuelve atrás y descarta páginas de una búsqueda anterior", async ({ page }) => {
  const requests = await prepare(page); await selectProject(page);
  let release!: () => void;
  let delayNext = false;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/conocimiento/lienzo/preguntar?**", async route => {
    const params = new URL(route.request().url()).searchParams;
    const offset = Number(params.get("offset"));
    if (offset === 100 && delayNext) await delayed;
    const text = params.get("q") === "nueva" ? "Resultado de búsqueda nueva" : "Página " + offset;
    await json(route, { offset, limite: 100, siguientes: offset === 0 ? 100 : null, total: 101, candidatos: [node(text)], temas_sin_resolver: [] });
  });
  await page.getByRole("button", { name: "Buscar", exact: true }).first().click();
  await page.getByLabel("Consultas, una por línea").fill("API\npermisos");
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByText("Página 0", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Anterior", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Más resultados", exact: true }).click();
  await expect(page.getByText("Página 100", { exact: true })).toBeVisible();
  await expect(page.getByText("Mostrando 101–101 de 101", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Más resultados", exact: true })).toBeDisabled();
  const last = new URL(requests.at(-1)!.url);
  expect(last.searchParams.getAll("q")).toEqual(["API", "permisos"]);
  expect(last.searchParams.get("limite")).toBe("100");
  await page.getByRole("button", { name: "Anterior", exact: true }).click();
  await expect(page.getByText("Página 0", { exact: true })).toBeVisible();
  delayNext = true;
  const pending = page.waitForRequest(r => new URL(r.url()).searchParams.get("offset") === "100");
  await page.getByRole("button", { name: "Más resultados", exact: true }).click(); await pending;
  await page.getByLabel("Consultas, una por línea").fill("nueva");
  await expect(page.getByRole("navigation", { name: "Páginas de resultados" })).toHaveCount(0);
  release();
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByText("Resultado de búsqueda nueva", { exact: true })).toBeVisible();
  await expect(page.getByText("Página 100", { exact: true })).toHaveCount(0);
  expect(new URL(requests.at(-1)!.url).searchParams.get("offset")).toBe("0");
});

test("capturado y prosa: lo que pasó por el lienzo se ve aparte, sin estado de veredicto", async ({ page }) => {
  await prepare(page); await selectProject(page);
  await page.route("**/conocimiento/lienzo/capturas?**", route => json(route, { total: 1, capturas: [{ id: "c1", clase: "pedido", estado: "observado", texto: "Medí la cola de captura", agente: "codex", modelo: "gpt-5", session_id: "s1", fecha: "2026-10-09T12:00:00Z", origen: { via: "terminal" } }] }));
  await page.route("**/conocimiento/lienzo/preguntar?**", route => {
    const prosa = new URL(route.request().url()).searchParams.get("prosa") === "1";
    return json(route, { ...defaults("/preguntar"), ...(prosa ? { prosa: [{ fuente: "informe", marca: "prosa, no declarado", nodo: "inf-1", fragmento: "la [cola] tarda 2 ms", puntaje: -1 }] } : {}) });
  });
  await page.getByRole("button", { name: "Capturado", exact: true }).click();
  await page.getByLabel("Clase de captura").selectOption("pedido");
  const pedido = page.waitForRequest(r => new URL(r.url()).pathname === "/conocimiento/lienzo/capturas");
  await page.getByRole("button", { name: "Leer lo capturado", exact: true }).click();
  expect(new URL((await pedido).url()).searchParams.get("clase")).toBe("pedido");
  await expect(page.getByText("Medí la cola de captura", { exact: true })).toBeVisible();
  await expect(page.getByText("captura: pedido", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Buscar", exact: true }).first().click();
  await page.getByLabel("Consultas, una por línea").fill("cola");
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Prosa (no declarado)" })).toHaveCount(0);
  await page.getByLabel(/Buscar también en la prosa/).check();
  const conProsa = page.waitForRequest(r => new URL(r.url()).pathname === "/conocimiento/lienzo/preguntar");
  await page.getByRole("button", { name: "Buscar", exact: true }).last().click();
  expect(new URL((await conProsa).url()).searchParams.get("prosa")).toBe("1");
  await expect(page.getByRole("heading", { name: "Prosa (no declarado)" })).toBeVisible();
  await expect(page.getByText(/tarda 2 ms/).first()).toBeVisible();
});
