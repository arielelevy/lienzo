import { expect, test } from "@playwright/test";
import { SID, abrirTablero } from "./tablero-fijo";

const settings = { preferences: { brief: false, rtk: false }, tools: [
  { id: "breve", nombre: "Respuestas breves", tipo: "mejora", origen: "https://github.com/JuliusBrussee/caveman", descripcion: "Sin proxy ni compresión de archivos", version: null, costo: "gratis", modos: ["general", "ingenieria-reversa"], preferencia: "brief", instalar: null, estado: { disponible: true } },
  { id: "rtk", nombre: "RTK", tipo: "mejora", origen: "https://github.com/rtk-ai/rtk", descripcion: "Salidas de comandos", version: "0.51.0", costo: "gratis", modos: ["general", "ingenieria-reversa"], preferencia: "rtk", instalar: null, estado: { disponible: true } },
  { id: "rea", nombre: "REA", tipo: "trabajo", origen: "https://github.com/morluto/rea", descripcion: "Ingeniería reversa", version: null, costo: "gratis", modos: ["ingenieria-reversa"], preferencia: null, instalar: "rea setup", estado: { disponible: false, detalle: "no instalada" } },
], scope: "esta PC; nuevas sesiones" };
const report = (sid: string) => ({ session_id: sid, snapshot: "reviewed", agent: "codex", model: null, quality: "no evaluada", note: null,
  jev_available: true, jev_max_cost_usd: .001, evidence: { scope: "ultimos 10 turnos", counts: { turns: 2, closed: 1, tools: 3, errors: 1, known_results: 2, missing_results: 1 } }, suggestions: [] });
const json = (data: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(data) });

test("catálogo distingue tools, plugins de Claude y extensiones locales sin tools", async ({ page }, testInfo) => {
  await abrirTablero(page);
  const additions = [
    { id: "anatomy", nombre: "Anatomy", tipo: "documentacion", formato: "skill", descripcion: "Figuras de documentación visual", limitaciones: ["No sustituye pruebas ni review."] },
    { id: "commit", nombre: "Commit", tipo: "trabajo", formato: "plugin-claude", descripcion: "Agrupa commits", limitaciones: ["En modo no interactivo hace commit y push."] },
  ].map(t => ({ ...t, origen: "https://github.com/midudev/better-claude", version: null, costo: "gratis", modos: ["general"], preferencia: null, instalar: "instalación explícita", compatible_con: t.formato === "plugin-claude" ? ["claude"] : [], estado: { disponible: false, detalle: "instalación sin verificar" } }));
  const data = { ...settings, tools: [...settings.tools, ...additions], plugins: [
    { id: "stepwise", nombre: "Stepwise", origen: "local", cargado: true, capacidades: ["lectura HTTP"], detalle: "Cargado; conexión no verificada." },
  ] };
  let writes = 0;
  await page.route("**/agent-improvements", route => {
    if (route.request().method() !== "GET") writes++;
    return route.fulfill(json(data));
  });
  await page.route("**/agent-improvements/scheduler", route => route.fulfill(json({ enabled: true, reason: "pausado para prueba", projects: [], jobs: [] })));
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const catalog = page.getByRole("list", { name: "Catálogo de tools" });
  await expect(catalog.getByRole("listitem").filter({ has: page.locator(".tool-card-cabecera") })).toHaveCount(5);
  await expect(catalog.getByText("plugin de Claude Code", { exact: true })).toHaveCount(1);
  await expect(catalog.getByText("documentación", { exact: true })).toBeVisible();
  await expect(catalog.getByText("En modo no interactivo hace commit y push.")).toBeVisible();
  await expect(catalog.getByRole("switch", { name: "Commit", exact: true })).toHaveCount(0);
  const local = page.getByRole("region", { name: "Plugins locales de Lienzo" });
  await expect(local.getByText("Stepwise", { exact: true })).toBeVisible();
  await expect(local.getByText("Cargado; conexión no verificada.")).toBeVisible();
  await page.getByRole("region", { name: "Mejoras de agentes", exact: true }).getByRole("button", { name: "Actualizar", exact: true }).click();
  await expect(local.getByText("Stepwise", { exact: true })).toBeVisible();
  expect(writes).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("catalogo-comunidad.png"), fullPage: true });
});

test("fichas de plugins: manifiesto, permisos declarados, errores y salud a pedido", async ({ page }, testInfo) => {
  await abrirTablero(page);
  const permisos = (extra = {}) => ({ lectura: [], escritura: [], ejecucion: [], red: [], efectos_externos: [], ...extra });
  const base = { origen: "local", url: null, version: null, descripcion: null, capacidades: [], puntos: [], ciclo_de_vida: [], configuracion: null, relaciones: { tools: [], sistemas: [] }, errores: [], advertencias: [], salud: null };
  const plugins = [
    { ...base, id: "notas", nombre: "Notas de ronda", version: "1.0.0", manifiesto: "valido", estado: "declarado", cargado: false, capacidades: ["forma-de-trabajo"], permisos: permisos(), detalle: "Forma de trabajo declarada, sin código en el server." },
    { ...base, id: "malo", nombre: "Malo", manifiesto: "invalido", estado: "error", cargado: false, permisos: null, errores: ["manifiesto inválido: permisos: obligatorio"], detalle: "No se cargó o falló al iniciar; ver errores." },
    { ...base, id: "orq", nombre: "Orquestador", version: "0.3.0", manifiesto: "valido", estado: "sin-configurar", cargado: true, capacidades: ["integracion"], puntos: ["get"], ciclo_de_vida: ["salud"], permisos: permisos({ red: ["127.0.0.1:3000"], efectos_externos: ["cancela corridas"] }), configuracion: { completa: false, faltan: ["token_env (variable ORQ_TOKEN no definida)"], errores: [] }, detalle: "Módulo cargado con configuración incompleta." },
    { ...base, id: "puente", nombre: "Puente", version: "1.0.0", manifiesto: "valido", estado: "cargado", cargado: true, ciclo_de_vida: ["salud"], permisos: permisos(), salud: { ok: true, conectado: false, detalle: "servicio en espera", ts: 2 }, detalle: "Módulo cargado; no acredita conexión ni salud del sistema integrado." },
    { ...base, id: "futuro", nombre: "Futuro", manifiesto: "valido", estado: "detenido", cargado: false, permisos: permisos(), detalle: "Estado de un backend más nuevo." },
    { ...base, id: "stepwise", nombre: "Stepwise", manifiesto: "ausente", estado: "cargado", cargado: true, permisos: null, puntos: ["get", "post", "runners_externos"], ciclo_de_vida: ["iniciar"], detalle: "Módulo cargado; no acredita conexión ni salud del sistema integrado." },
  ];
  await page.route("**/agent-improvements", route => route.fulfill(json({ ...settings, plugins })));
  await page.route("**/agent-improvements/scheduler", route => route.fulfill(json({ enabled: true, reason: "pausado para prueba", projects: [], jobs: [] })));
  const checks: string[] = [];
  await page.route("**/ext/*/_salud", route => {
    checks.push(route.request().method());
    return checks.length === 1
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "orq", salud: { ok: false, detalle: "sin respuesta en 5 s", conectado: null, ts: 1 } }) })
      : route.fulfill({ status: 409, contentType: "application/json", body: '{"error":"la comprobación anterior todavía no terminó"}' });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const local = page.getByRole("region", { name: "Plugins locales de Lienzo" });
  const card = (name: string) => local.getByRole("listitem", { name: `Plugin ${name}` });
  await expect(card("Notas de ronda").getByText("declarado", { exact: true })).toBeVisible();
  await expect(card("Notas de ronda").getByText("forma de trabajo", { exact: true })).toBeVisible();
  await expect(card("Notas de ronda").getByText("No declara permisos ni efectos externos.")).toBeVisible();
  await expect(card("Notas de ronda").getByRole("button")).toHaveCount(0);
  await expect(card("Malo").getByText("con error", { exact: true })).toBeVisible();
  await expect(card("Malo").getByText("manifiesto inválido", { exact: true })).toBeVisible();
  await expect(card("Malo").getByText("sin manifiesto", { exact: true })).toHaveCount(0);
  await expect(card("Malo").getByRole("list", { name: "Errores de Malo" })).toHaveText("manifiesto inválido: permisos: obligatorio");
  await expect(card("Stepwise").getByText("sin manifiesto", { exact: true })).toBeVisible();
  await expect(card("Stepwise").getByText("Permisos no declarados.")).toBeVisible();
  await expect(card("Stepwise").getByText(/no acredita conexión/)).toBeVisible();
  await expect(card("Stepwise").getByRole("button", { name: "Comprobar salud" })).toHaveCount(0);
  await expect(card("Puente").getByText("sin conexión", { exact: true })).toBeVisible();
  await expect(card("Puente").getByText("Salud: servicio en espera")).toBeVisible();
  await expect(card("Futuro").getByText("detenido", { exact: true })).toBeVisible();
  const orq = card("Orquestador");
  await expect(orq.getByText("sin configurar", { exact: true })).toBeVisible();
  await expect(orq.getByText(/falta token_env \(variable ORQ_TOKEN no definida\)/)).toBeVisible();
  await expect(orq.getByText(/no aplicados por Lienzo: red \(127\.0\.0\.1:3000\); efectos externos \(cancela corridas\)/)).toBeVisible();
  await expect(orq.getByText("conectado", { exact: true })).toHaveCount(0);
  await orq.getByRole("button", { name: "Comprobar salud" }).click();
  await expect(orq.getByText("comprobación fallida", { exact: true })).toBeVisible();
  await expect(orq.getByText("Salud: sin respuesta en 5 s")).toBeVisible();
  await orq.getByRole("button", { name: "Comprobar salud" }).click();
  await expect(orq.getByRole("alert")).toHaveText("la comprobación anterior todavía no terminó");
  await expect(orq.getByText("comprobación fallida", { exact: true })).toBeVisible();
  expect(checks).toEqual(["GET", "GET"]);
  await local.screenshot({ path: testInfo.outputPath("plugins-locales.png") });
});

test("investigador Codex: cuota de suscripción, bloqueo, candidatos y cancelación", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  const evaluacion = (enabled: boolean) => ({ enabled, state: enabled ? "enabled" : "blocked", reasons: enabled ? [] : ["uso semanal 85 % supera el máximo 80 %"],
    runs_today: 1, project: "lienzo", limits: { max_runs_per_day: 6, max_weekly_used_pct: 80 },
    adapter: { name: "codex", consumption_bound: { weekly_used_pct: enabled ? 35 : 85 } }, authorization: { autorizado_por: "Ariel", fecha: "2026-10-16" }, budget_granted_usd: "0" });
  const job = { id: "inv1", project: "lienzo", state: "running", cursor: 0, results: [], kind: "research", attempts: 1, case: { case_key: "c-42", area: "retrabajo" }, last_run: null };
  let status: Record<string, unknown> = { enabled: true, reason: "quieto", projects: [{ id: "lienzo", name: "Lienzo" }], jobs: [job], budget: { limit_usd: "2", spent_usd: "0", reserved_usd: "0", available_usd: "2", blocked: false },
    research: { last_evaluation: null, scope: "sólo lectura; propuestas sin promoción", note: "sin evaluar en este proceso" } };
  const writes: unknown[] = [];
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() === "PUT") {
      const data = route.request().postDataJSON();
      if (data.action !== "activity") writes.push(data);
      if (data.action === "research_check") {
        status = { ...status, research: { ...(status.research as object), last_evaluation: evaluacion(writes.length > 1), note: null } };
        return route.fulfill(json({ ...status, research_preview: [{ case_key: "c-7", area: "esperas" }] }));
      }
      if (data.action === "cancel_research") status = { ...status, jobs: [{ ...job, state: "cancelled", reason: "cancelado por el usuario" }] };
    }
    return route.fulfill(json(status));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const inv = page.getByRole("region", { name: "Aprendizaje en segundo plano" }).getByLabel("Investigador Codex");
  await expect(inv.getByText(/no el presupuesto en USD de Jev/)).toBeVisible();
  await expect(inv.getByText(/sin evaluar en este proceso/)).toBeVisible();
  await expect(inv.getByRole("button", { name: "Encolar investigación" })).toBeDisabled();
  await page.getByRole("region", { name: "Aprendizaje en segundo plano" }).getByRole("combobox").selectOption("lienzo");
  await inv.getByRole("button", { name: "Revisar investigador" }).click();
  await expect(inv.getByText("bloqueado", { exact: true })).toBeVisible();
  await expect(inv.getByRole("list", { name: "Motivos de bloqueo" })).toHaveText("uso semanal 85 % supera el máximo 80 %");
  await expect(inv.getByText(/Uso semanal 85 % · corre hasta 80 % usado · ejecuciones hoy 1\/6/)).toBeVisible();
  await expect(inv.getByText("Casos candidatos: esperas (c-7)")).toBeVisible();
  await expect(inv.getByRole("button", { name: "Encolar investigación" })).toBeDisabled();
  await inv.getByRole("button", { name: "Revisar investigador" }).click();
  await expect(inv.getByText("habilitado", { exact: true })).toBeVisible();
  await expect(inv.getByRole("button", { name: "Encolar investigación" })).toBeEnabled();
  const trabajos = page.getByRole("list", { name: "Trabajos" });
  await expect(trabajos.getByText("Caso retrabajo · c-42 · intentos 1")).toBeVisible();
  await trabajos.getByRole("button", { name: "Cancelar investigación" }).click();
  await expect(trabajos.getByText("lienzo · cancelled")).toBeVisible();
  await expect(trabajos.getByRole("button", { name: "Cancelar investigación" })).toHaveCount(0);
  expect(writes).toEqual([{ action: "research_check", project: "lienzo" }, { action: "research_check", project: "lienzo" }, { action: "cancel_research", job: "inv1" }]);
});

test("piloto distingue habilitado de apto y pausa llamadas automáticas", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  let enabled = true;
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() === "PUT") {
      const action = route.request().postDataJSON();
      if (action.action === "configure") enabled = action.enabled;
    }
    return route.fulfill(json({ enabled, pilot_enabled: true, paid_enabled: false,
      reason: enabled ? "cooldown" : "pausado por el usuario", projects: [], jobs: [],
      budget: { limit_usd: "2", spent_usd: ".00002268", reserved_usd: ".037418892", available_usd: "1.962558428", unknown_charges: 1, blocked: false,
        pilot: { deadline: 1791993600, attempts: 1, maximum_calls: 24, cooldown_seconds: 3600, within_window: true } } }));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const section = page.getByRole("region", { name: "Aprendizaje en segundo plano" });
  await expect(section.getByText(/llamadas pagas acotadas/)).toBeVisible();
  await expect(section.getByText(/intentos 1\/24/)).toBeVisible();
  await expect(section.getByText(/cooldown 60 min/)).toBeVisible();
  await expect(section.getByText(/cota permanece reservada/)).toBeVisible();
  await expect(section.getByText(/Sin envío automático ahora/)).toBeVisible();
  await section.getByRole("button", { name: "Pausar aprendizaje" }).click();
  await expect(section.getByText("pausado por el usuario", { exact: true })).toBeVisible();
  await expect(section.getByRole("button", { name: "Habilitar aprendizaje" })).toBeVisible();
});

test("scheduler informa bloqueo y encola solo análisis local", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  let status = { enabled: true, reason: "actividad del usuario", projects: [{ id: "lienzo", name: "Lienzo" }], jobs: [] as object[], paid_enabled: false, new_agents_enabled: false, budget: { limit_usd: "2", spent_usd: "0.00002268", reserved_usd: "0", available_usd: "0", unknown_charges: 1, blocked: true } };
  const writes: unknown[] = [];
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() !== "GET") {
      const data = route.request().postDataJSON();
      if (data.action === "enqueue") { writes.push(data); status = { ...status, jobs: [{ id: "job", project: "lienzo", state: "queued", cursor: 0, results: [] }] }; }
      else if (data.action === "configure") { writes.push(data); status = { ...status, enabled: data.enabled }; }
    }
    return route.fulfill(json(status));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const section = page.getByRole("region", { name: "Aprendizaje en segundo plano" });
  await expect(section.getByText("actividad del usuario", { exact: true })).toBeVisible();
  await expect(section.getByText(/Presupuesto total USD 2/)).toBeVisible();
  await expect(section.getByText(/Cargos previos sin conciliar/)).toBeVisible();
  await expect(section.getByRole("button", { name: "Encolar análisis local" })).toBeDisabled();
  await section.getByRole("combobox").selectOption("lienzo");
  await section.getByRole("button", { name: "Encolar análisis local" }).click();
  await expect(section.getByText("lienzo · queued")).toBeVisible();
  await section.getByRole("button", { name: "Pausar aprendizaje" }).click();
  await expect(section.getByRole("button", { name: "Habilitar aprendizaje" })).toBeVisible();
  expect(writes).toEqual([{ action: "enqueue", project: "lienzo" }, { action: "configure", enabled: false }]);
});

test("menú contextual ofrece preferencias y conserva estado ante error", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements/scheduler", route => route.fulfill(json({ enabled: true, reason: "actividad del usuario", projects: [], jobs: [] })));
  let writes = 0;
  await page.route("**/agent-improvements", async route => {
    if (route.request().method() === "GET") return route.fulfill(json(settings));
    writes++;
    return route.fulfill(writes === 1 ? { status: 500, contentType: "application/json", body: '{"error":"no se pudo guardar"}' } : json({ ...settings, preferences: { brief: true, rtk: false } }));
  });
  await page.locator(".board").evaluate(el => el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 1435, clientY: 895 })));
  const menu = page.getByRole("menu", { name: "Área libre" });
  await expect(menu.getByRole("menuitem", { name: "Mejoras de agentes…", exact: true })).toBeVisible();
  const bounds = await menu.boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(900);
  await menu.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const dialog = page.getByRole("dialog", { name: "Mejoras de agentes", exact: true });
  const brief = dialog.getByRole("switch", { name: "Respuestas breves" });
  // la casilla nativa está oculta: se toca el interruptor, como lo haría una persona
  const toggle = dialog.locator("label.tool-switch").filter({ hasText: "Respuestas breves" });
  await expect(dialog.getByRole("list", { name: "Catálogo de tools" }).getByRole("listitem")).toHaveCount(3);
  await expect(dialog.getByText(/no instalada/)).toBeVisible();
  await toggle.click();
  await expect(dialog.getByRole("alert")).toHaveText("no se pudo guardar");
  await expect(brief).not.toBeChecked();
  await toggle.click();
  await expect(brief).toBeChecked();
  expect(writes).toBe(2);
  await dialog.getByRole("button", { name: "Cerrar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("Jev exige autorizar costo y una falla no queda como éxito", async ({ page }) => {
  await abrirTablero(page);
  let paid = 0;
  await page.route("**/sessions/*/improvements", route => route.fulfill(json(report(SID.migracion))));
  await page.route("**/sessions/*/improvements/jev", async route => {
    paid++;
    expect(route.request().postDataJSON()).toEqual({ snapshot: "reviewed", allow_cost: true });
    await route.fulfill({ status: 409, contentType: "application/json", body: '{"error":"la muestra cambio"}' });
  });
  await page.locator(`.card[data-sid="${SID.migracion}"] .title`).dblclick();
  const panel = page.locator(".panel");
  await panel.getByRole("button", { name: "Mejoras", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Consultar Jev" })).toBeDisabled();
  await panel.getByRole("checkbox", { name: /Autorizar una consulta/ }).check();
  await panel.getByRole("button", { name: "Consultar Jev" }).click();
  await expect(panel.getByRole("alert")).toHaveText("la muestra cambio");
  await expect(panel.getByRole("checkbox", { name: /Autorizar una consulta/ })).not.toBeChecked();
  expect(paid).toBe(1);
});

test("una consulta tardía no aparece en otra sesión", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/sessions/*/improvements", route => {
    const sid = route.request().url().split("/").at(-2)!;
    return route.fulfill(json(report(sid)));
  });
  let release: (() => void) | undefined;
  const held = new Promise<void>(resolve => { release = resolve; });
  let pending = false;
  await page.route("**/sessions/*/improvements/jev", async route => {
    pending = true;
    await held;
    await route.fulfill(json({ session_id: SID.migracion, decision: { choice: "rtk", note: "resultado anterior", model: "test", usage: { cost: .00001 } } }));
  });
  await page.locator(`.card[data-sid="${SID.migracion}"] .title`).dblclick();
  await page.locator(".panel").getByRole("button", { name: "Mejoras", exact: true }).click();
  await page.locator(".panel").getByRole("checkbox", { name: /Autorizar una consulta/ }).check();
  await page.locator(".panel").getByRole("button", { name: "Consultar Jev" }).click();
  await expect.poll(() => pending).toBe(true);
  await page.getByRole("button", { name: "cerrar panel" }).click();
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await page.locator(".panel").getByRole("button", { name: "Mejoras", exact: true }).click();
  release!();
  await expect(page.locator(".panel").getByText("2 turnos · 3 herramientas")).toBeVisible();
  await expect(page.getByText("resultado anterior")).toHaveCount(0);
});

test("un lanzamiento muestra el aviso de mejoras no disponibles", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/sessions/launch", route => route.fulfill(json({ ok: true, aviso: "RTK no esta instalado en el entorno elegido" })));
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByRole("combobox", { name: "Proyecto", exact: true }).selectOption("");
  await dialog.getByRole("textbox", { name: "Carpeta", exact: true }).fill("D:/Apps/lienzo");
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(page.getByText("CLI lanzada. RTK no esta instalado en el entorno elegido", { exact: true })).toBeVisible();
});
