import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { BASE, SID, instalarTablero, sesiones } from "./tablero-fijo";

test("conectar sólo la Desktop elegida, mostrar comando público y esperar disponibilidad real", async ({ page }) => {
  const lista = sesiones().map((s): Session => s.session_id !== SID.mapas ? s : {
    ...s, agent: "claude", no_console: true, pid: 3568, title_source: "prompt", needs: null, pending_id: null,
    external: { kind: "claude-desktop", via: "registro", desktop: true, canal: "elegida" },
    envio: { puede: false, motivo: "falta conectar el adaptador", transporte: "claude_pipe" },
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
        setTimeout(() => { this.onopen?.(new Event("open")); deliver?.({ type: "snapshot", sessions, pending: [], links: [], rules: [] }); }, 0);
      }
      close() {}
    }
    Object.defineProperty(window, "EventSource", { configurable: true, get: () => Stream, set: () => {} });
    Object.assign(window, { __claudeEvent: (ev: unknown) => deliver?.(ev) });
  }, lista);
  await instalarTablero(page, lista);
  const chosen: string[] = [];
  await page.route(`**/sessions/${SID.mapas}/claude-pipe`, async (route) => {
    chosen.push(route.request().url());
    await route.fulfill({ json: { session_id: SID.mapas, command: "public --bootstrap address session server-pid filetime", expires_at: Date.now() / 1000 + 120, connected: false } });
  });
  await page.route(`**/sessions/${SID.mapas}/send`, async (route) => route.fulfill({ json: {
    chars: 4, estado: "encolado", motivo: "escrito al pipe; falta transcript", transporte: "claude_pipe",
  } }));
  await page.goto(BASE);
  const card = page.locator(`.card[data-sid="${SID.mapas}"]`);
  await card.locator(".title").dblclick();
  const panel = page.locator(".panel");
  await panel.getByRole("button", { name: "Conectar esta sesión Claude" }).click();
  const command = panel.getByRole("textbox", { name: "Comando público para conectar Claude" });
  await expect(command).toHaveValue("public --bootstrap address session server-pid filetime");
  await expect(command).toHaveAttribute("readonly", "");
  expect(chosen).toHaveLength(1);
  await expect(panel.locator(".send button.primary")).toHaveCount(0);
  const s = lista.find((s) => s.session_id === SID.mapas)!;
  const connected = { ...s, envio: { puede: true, motivo: null, transporte: "claude_pipe" } };
  await page.evaluate((session) => {
    (window as unknown as { __claudeEvent: (e: unknown) => void }).__claudeEvent({ type: "session", session });
  }, connected);
  const box = panel.locator(".send textarea");
  await expect(box).toBeEnabled();
  await box.fill("hola");
  await panel.getByRole("button", { name: "Enviar", exact: true }).click();
  await expect(page.getByText("Encolado; espera confirmación", { exact: true })).toBeVisible();
  await page.evaluate((session) => {
    (window as unknown as { __claudeEvent: (e: unknown) => void }).__claudeEvent({ type: "session", session });
  }, { ...connected, envio_claude: { estado: "entregado", transporte: "claude_pipe", motivo: null } });
  await expect(card.getByRole("status")).toHaveText("Último envío: entregado");
  await card.locator(".kebab").click();
  await expect(card.getByRole("menuitem", { name: "Cerrar proceso a la fuerza…" })).toHaveCount(0);
});

test("el hook Claude se solicita sólo al elegirlo en un lanzamiento", async ({ page }) => {
  await instalarTablero(page);
  let body: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto(BASE);
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("claude");
  const optIn = dialog.getByRole("checkbox", { name: /Conectar sólo esta sesión Claude/ });
  await expect(optIn).not.toBeChecked();
  await optIn.check();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(body).toMatchObject({ agent: "claude", claude_pipe: true });
});
