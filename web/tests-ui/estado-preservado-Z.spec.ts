import { expect, test, type Page } from "@playwright/test";
import type { ConsultaResumen, Session } from "../src/types";
import { BASE, bloquearEscrituras, instalarTablero, pendientes, sesiones } from "./tablero-fijo";

async function stream(page: Page, seeds: Session[]) {
  await page.addInitScript(({ sessions, pending }) => {
    let deliver: (ev: unknown) => void = () => {};
    class Stream {
      onmessage: ((e: MessageEvent) => void) | null = null;
      onopen: ((e: Event) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        deliver = ev => this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(ev) }));
        setTimeout(() => { this.onopen?.(new Event("open")); deliver({ type: "snapshot", sessions, pending, links: [], rules: [] }); }, 0);
      }
      close() {}
    }
    Object.defineProperty(window, "EventSource", { configurable: true, get: () => Stream, set: () => {} });
    Object.assign(window, { __zEvent: (ev: unknown) => deliver(ev) });
  }, { sessions: seeds, pending: pendientes() });
  await bloquearEscrituras(page);
  await instalarTablero(page, seeds);
}

async function event(page: Page, value: unknown) {
  await page.evaluate(ev => (window as unknown as { __zEvent: (ev: unknown) => void }).__zEvent(ev), value);
}

test("T10 conserva nodo y borrador al cambiar miembros, repo_key y modo", async ({ page }) => {
  const seeds = sesiones().filter(s => ["t1", "n2"].includes(s.session_id));
  const s = seeds.find(s => s.session_id === "n2")!;
  s.repo_key = "z-demo";
  await stream(page, seeds);
  await page.goto(BASE);
  const input = page.locator('.card[data-sid="n2"] input.otro');
  await input.fill("borrador Z sin enviar");
  await input.evaluate(node => Object.assign(window, { __zInput: node }));
  const conserved = async () => {
    await expect(input).toHaveValue("borrador Z sin enviar");
    expect(await input.evaluate(node => (window as unknown as { __zInput: Element }).__zInput === node)).toBe(true);
  };
  await page.getByRole("button", { name: "Por proyecto", exact: true }).click();
  await conserved();
  await event(page, { type: "session", session: { ...s, session_id: "nuevo-demo", repo_key: "a-demo", pending_id: null, needs: null } });
  await expect(page.locator('.card[data-sid="nuevo-demo"]')).toBeVisible();
  await conserved();
  await event(page, { type: "removed", session_id: "nuevo-demo" });
  await expect(page.locator('.card[data-sid="nuevo-demo"]')).toHaveCount(0);
  await conserved();
  await event(page, { type: "session", session: { ...s, repo_key: "0-demo" } });
  await expect(page.locator('[data-project="0-demo"] .card[data-sid="n2"]')).toBeVisible();
  await conserved();
  await page.getByRole("button", { name: "Orden habitual", exact: true }).click();
  await conserved();
});

for (const domain of ["consultas", "rondas"]) test(`T6 GET tardío no pisa SSE de ${domain}`, async ({ page }) => {
  const seeds = sesiones();
  await stream(page, seeds);
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  let requested = 0;
  let completed = 0;
  const oldConsulta: ConsultaResumen = { id: "Z-consulta", pregunta: "Consulta vieja Z", estado: "abierta", vuelta: 1, vueltas: 2, investigadores: ["t1"], revisor: "t2", coordinador: "t1", nombres: {}, esperando: [], pendientes: [], fuera: {}, motivo: null, creada: new Date().toISOString(), cerrada: null };
  const oldRondas = { avisos: [], politicas: {}, turnos: { "motores-Z": { dueno: { session_id: "t1", motivo: "viejo Z", desde: new Date().toISOString(), vence: new Date(Date.now() + 300000).toISOString() }, cola: [] } } };
  await page.route(domain === "consultas" ? "**/consultas" : "**/avisos", async route => {
    requested++;
    await wait;
    await route.fulfill({ json: domain === "consultas" ? [oldConsulta] : oldRondas });
    completed++;
  });
  await page.goto(BASE);
  await expect(page.locator(".card").first()).toBeVisible();
  await expect.poll(() => requested).toBeGreaterThan(0);
  if (domain === "consultas") {
    await event(page, { type: "consulta", consulta: { ...oldConsulta, pregunta: "Consulta nueva Z", estado: "cerrada", cerrada: new Date().toISOString() } });
    await expect(page.getByText("Consulta nueva Z", { exact: false })).toBeVisible();
  } else {
    await event(page, { type: "rondas", ...oldRondas, turnos: { "motores-Z": { ...oldRondas.turnos["motores-Z"], dueno: { ...oldRondas.turnos["motores-Z"].dueno, session_id: "t2" } } } });
  }
  release();
  await expect.poll(() => completed).toBe(requested);
  // Dos frames aseguran que React haya aplicado cualquier respuesta HTTP equivocada.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  if (domain === "consultas") {
    await expect(page.getByText("Consulta vieja Z", { exact: false })).toHaveCount(0);
  } else {
    await expect(page.locator('.ronda-chip').filter({ hasText: "motores-Z" })).toContainText("Flechas y glifos");
  }
});
