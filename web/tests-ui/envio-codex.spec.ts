import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { BASE, SID, instalarTablero, sesiones } from "./tablero-fijo";

/** UI real servida por Vite; API y SSE son fixtures explícitos. SSE de sockets reales se mide en pytest. */
for (const { result, desktop } of [
  { result: "encolado", desktop: false },
  ...(["encolado", "entregado", "sin_confirmacion"] as const).map(result => ({ result, desktop: true })),
] as const) {
  test(`abrir Codex ${desktop ? "Desktop" : "CLI"}, enviar y observar ${result} y actualización SSE`, async ({ page }) => {
    const transport = desktop ? "codex_queue" : "tecleo";
    const lista = sesiones().map((s): Session => s.session_id !== SID.capas ? s : {
      ...s, agent: "codex", pid: desktop ? null : 4242, source: desktop ? "desktop" : "sweep", no_console: desktop,
      pending_id: null, needs: null, stopped_by: null,
      external: desktop ? { kind: "codex-desktop", via: "rollout", desktop: true } : null,
      envio: { puede: true, motivo: null, transporte: transport },
    });
    await page.addInitScript((sessions) => {
      let deliver: ((ev: unknown) => void) | undefined;
      class Stream {
        onopen: ((e: Event) => void) | null = null;
        onmessage: ((e: MessageEvent) => void) | null = null;
        onerror: (() => void) | null = null;
        readyState = 1;
        constructor() {
          deliver = (ev) => this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(ev) }));
          setTimeout(() => {
            this.onopen?.(new Event("open"));
            deliver?.({ type: "snapshot", sessions, pending: [], links: [], rules: [] });
          }, 0);
        }
        close() {}
      }
      Object.defineProperty(window, "EventSource", { configurable: true, get: () => Stream, set: () => {} });
      Object.assign(window, { __envioEvent: (ev: unknown) => deliver?.(ev) });
    }, lista);
    await instalarTablero(page, lista);
    const requests: unknown[] = [];
    await page.route(`**/sessions/${SID.capas}/send`, async (route) => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, chars: 4, estado: result, motivo: result === "sin_confirmacion" ? "resultado incierto; no se reintenta" : null, transporte: transport } });
    });
    await page.goto(BASE);
    const card = page.locator(`.card[data-sid="${SID.capas}"]`);
    await card.locator(".title").dblclick();
    const panel = page.locator(".panel");
    await expect(panel).toBeVisible();
    const box = panel.locator("textarea").last();
    await expect(box).toBeEnabled();
    await box.fill("hola");
    await panel.getByRole("button", { name: "Enviar", exact: true }).click();
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ text: "hola", attachments: [] });
    await expect(page.getByText(result === "entregado" ? "Entregado" : result === "encolado" ? "Encolado; espera confirmación" : "Sin confirmación: resultado incierto; no se reintenta", { exact: true })).toBeVisible();
    const s = lista.find((s) => s.session_id === SID.capas)!;
    await page.evaluate((session) => {
      (window as unknown as { __envioEvent: (ev: unknown) => void }).__envioEvent({ type: "session", session });
    }, { ...s, envio_codex: { estado: "entregado", motivo: null, transporte: transport } });
    await expect(card.getByRole("status")).toHaveText("Último envío: entregado");
    // La capacidad de enviar no habilita operaciones de consola.
    await card.locator("button.kebab").click();
    if (desktop) await expect(card.getByRole("menuitem", { name: "Cerrar proceso a la fuerza…" })).toHaveCount(0);
    else await expect(card.getByRole("menuitem", { name: "Cerrar proceso a la fuerza…" })).toBeVisible();
  });
}

test("app sin capacidad muestra motivo y expiración", async ({ page }) => {
  const lista = sesiones().map((s): Session => s.session_id !== SID.capas ? s : {
    ...s, agent: "codex", pid: null, source: "desktop", no_console: true, pending_id: null, needs: null,
    external: { kind: "codex-desktop", via: "rollout", desktop: true },
    envio: { puede: false, motivo: "la app de Codex no está abierta", transporte: null },
    envio_codex: { estado: "sin_confirmacion", motivo: "venció; no se reintenta" },
  });
  await instalarTablero(page, lista);
  await page.goto(BASE);
  const card = page.locator(`.card[data-sid="${SID.capas}"]`);
  await expect(card.getByRole("status")).toHaveText("Último envío: sin confirmación · venció; no se reintenta");
  await card.locator(".title").dblclick();
  await expect(page.locator(".panel").getByText("la app de Codex no está abierta", { exact: true })).toBeVisible();
  await expect(page.locator(".panel .send textarea")).toHaveCount(0);
});

for (const mode of ["legacy", "orquestador"] as const) {
  test(`${mode}: una capacidad ausente o ajena no abre envío`, async ({ page }) => {
    const lista = sesiones().map((s): Session => s.session_id !== SID.capas ? s : {
      ...s, agent: "codex", pid: null, source: "desktop", no_console: true, needs: null, pending_id: null,
      external: mode === "legacy" ? { kind: "codex-desktop", via: "rollout", desktop: true } : { kind: "stepwise" },
      envio: mode === "legacy" ? undefined : { puede: true, motivo: null, transporte: "codex_queue" },
      envio_codex: { estado: mode === "legacy" ? "encolado" : "rechazado", motivo: "fixture de resultado" },
    });
    await instalarTablero(page, lista);
    await page.goto(BASE);
    const card = page.locator(`.card[data-sid="${SID.capas}"]`);
    await expect(card.getByRole("status")).toContainText(mode === "legacy" ? "encolado" : "rechazado");
    await card.locator(".title").dblclick();
    await expect(page.locator(".panel .send textarea")).toHaveCount(0);
  });
}

test("Desktop scratch muestra nombre de canal o nombre neutro; conserva título del usuario y proyecto CLI", async ({ page }) => {
  const desktop = { kind: "claude-desktop", via: "registro", desktop: true } as const;
  const lista = sesiones().map((s): Session => {
    if (s.session_id === SID.mapas) return { ...s, repo: "scratch-2026-10-17-38ca50", title: "scratch-viejo", title_source: "prompt", external: { ...desktop, canal: "Archivo de sesiones inactivas/cerradas" }, no_console: true };
    if (s.session_id === SID.capas) return { ...s, repo: "scratch-sin-nombre", agent: "claude", title: null, title_source: "prompt", external: desktop, no_console: true };
    if (s.session_id === SID.migracion) return { ...s, repo: "scratch-usuario", title: "Mi título elegido", title_source: "user", external: { ...desktop, canal: "Eliminar sesiones inactivas" }, no_console: true };
    return s;
  });
  await instalarTablero(page, lista);
  await page.goto(BASE);
  const card = (sid: string) => page.locator(`.card[data-sid="${sid}"]`);
  await expect(card(SID.mapas).locator(".repo")).toHaveText("Claude Desktop");
  await expect(card(SID.mapas).locator(".title")).toHaveText("Archivo de sesiones inactivas/cerradas");
  await expect(card(SID.capas).locator(".title")).toHaveText("Sesión de Claude Desktop");
  await expect(card(SID.migracion).locator(".title")).toHaveText("Mi título elegido");
  await expect(card(SID.migracion).locator(".warn.external.desktop")).toContainText("Eliminar sesiones inactivas");
  const cli = lista.find((s) => s.session_id === SID.coordinadora)!;
  await expect(card(SID.coordinadora).locator(".repo")).toHaveText(cli.repo);
});

test("selección distingue aceptación pendiente de éxito, sin volver a enviar", async ({ page }) => {
  await instalarTablero(page, sesiones().map(s => ({ ...s, last_prompt: "pedido" })));
  let calls = 0;
  await page.route("**/sessions/*/send", async route => {
    calls++;
    await route.fulfill({ json: { chars: 4, estado: "sin_confirmacion", motivo: "timeout; no se reintenta" } });
  });
  await page.goto(BASE);
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).click({ modifiers: ["Control"] });
  const bar = page.getByRole("region", { name: "selección de tarjetas" });
  await bar.getByRole("button", { name: "Enviar a todas" }).click();
  await bar.getByRole("textbox").fill("hola");
  await bar.getByRole("button", { name: "Enviar a 1", exact: true }).click();
  await expect(bar).toContainText("0 ok / 1 pendientes / 0 fallaron");
  await expect(bar).toContainText("No reenvíes el texto");
  expect(calls).toBe(1);
});

test("pegar trabajo incierto conserva origen y no ofrece reenvío del mismo texto", async ({ page }) => {
  await instalarTablero(page);
  let calls = 0;
  await page.route(`**/sessions/${SID.coordinadora}/send`, async route => {
    calls++;
    await route.fulfill({ json: { chars: 4, estado: "sin_confirmacion", motivo: "timeout", handover_error: "el origen conserva su trabajo" } });
  });
  await page.goto(BASE);
  await page.locator(`.card[data-sid="${SID.mapas}"]`).focus();
  await page.keyboard.press("Control+c");
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await page.locator(`.card[data-sid="${SID.coordinadora}"]`).focus();
  await page.keyboard.press("Control+v");
  const dialog = page.getByRole("dialog", { name: "Pegar trabajo", exact: true });
  await dialog.getByRole("button", { name: "Enviar y detener origen" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(/Sin confirmación.*Traspaso pendiente.*No reenvíes el texto/)).toBeVisible();
  await expect(page.getByText(/El mensaje llegó/)).toHaveCount(0);
  expect(calls).toBe(1);
});
