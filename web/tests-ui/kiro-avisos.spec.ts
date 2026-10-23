import { expect, test, type Page } from "@playwright/test";
import { abrirTablero, pendientes, sesiones } from "./tablero-fijo";
import type { Pending, Session } from "../src/types";

/** Encargo O (2026-10-22): Kiro no tiene hooks. Lo que el auto-aprobar le contesta y el diálogo que
 *  espera en su terminal tienen que verse en el tablero y avisar en el navegador, como con Claude. */

const KIRO = "o1";

const kiro = (o: Partial<Session> = {}): Session => ({
  ...sesiones()[0],
  session_id: KIRO,
  agent: "kiro",
  repo: "source",
  title: "Checkout Branch From Main",
  coordinator: false,
  source: "sweep",
  in_vscode: false,
  state: "corriendo",
  last_reply: "Pensando…",
  ...o,
});

/** Notificaciones del navegador concedidas y anotadas en `window.__avisos`, y el SSE falso a mano
 *  (`window.__sse`) para empujar cambios después del snapshot. Va antes de abrir el tablero: el
 *  init script de acá corre después del de tablero-fijo y envuelve su EventSource. */
async function prepararAvisos(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __avisos: { title: string; body?: string; tag?: string }[]; __sse?: unknown; EventSource: new (u: string) => unknown };
    w.__avisos = [];
    class Aviso {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: (() => void) | null = null;
      constructor(title: string, opts?: { body?: string; tag?: string }) {
        w.__avisos.push({ title, body: opts?.body, tag: opts?.tag });
      }
      close() {}
    }
    (window as unknown as { Notification: unknown }).Notification = Aviso;
    try {
      localStorage.setItem("lienzo.notify", "1");
    } catch {
      /* sin storage */
    }
    // este script corre antes que el de tablero-fijo, que reemplaza EventSource: se envuelve lo que asigne
    let actual = w.EventSource;
    Object.defineProperty(window, "EventSource", {
      configurable: true,
      get: () => actual,
      set: (Base: new (u: string) => object) => {
        actual = class extends Base {
          constructor(u: string) {
            super(u);
            w.__sse = this;
          }
        } as unknown as typeof actual;
      },
    });
  });
}

async function empujar(page: Page, mensaje: unknown) {
  await page.evaluate((data) => {
    const sse = (window as unknown as { __sse: { onmessage: (e: MessageEvent) => void } }).__sse;
    sse.onmessage(new MessageEvent("message", { data }));
  }, JSON.stringify(mensaje));
}

const avisos = (page: Page) => page.evaluate(() => (window as unknown as { __avisos: { title: string; tag?: string }[] }).__avisos);

const DIALOGO = {
  question: "Build core.api solution requires approval",
  detail: "shell → dotnet build",
  options: [
    { n: 1, text: "Allow" },
    { n: 2, text: "Always allow" },
    { n: 3, text: "Deny" },
    { n: 4, text: "Always deny" },
  ],
  selected: 1,
};

test("la tarjeta muestra lo que el auto-aprobar le contestó, con la hora", async ({ page }) => {
  // reciente: el aviso caduca a los 3 min (card-notices.ts)
  const at = new Date(Date.now() - 60_000);
  const hora = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  const lista = [kiro({ auto_aprobado: { que: "Build core.api solution requires approval shell → dotnet build", at: at.toISOString(), via: "dialogo" } }), ...sesiones().slice(1)];
  await abrirTablero(page, lista);
  const linea = page.locator(`.card[data-sid="${KIRO}"] .auto-aprobado`);
  await expect(linea).toHaveText(`auto-aprobado ${hora}: Build core.api solution requires approval shell → dotnet build`);
});

test("el diálogo que Kiro espera en su terminal avisa en el navegador una sola vez", async ({ page }) => {
  await prepararAvisos(page);
  await abrirTablero(page, [kiro(), ...sesiones().slice(1)]);
  const antes = (await avisos(page)).length;
  const espera = kiro({ state: "te_necesita", needs: { kind: "dialog", detail: DIALOGO.question, where: "terminal", since: "2026-10-22T15:11:45-03:00" }, dialog: DIALOGO });
  await empujar(page, { type: "session", session: espera });
  await expect(page.locator(`.card[data-sid="${KIRO}"] .needs.tui`)).toContainText("Espera que elijas en la terminal");
  await expect.poll(async () => (await avisos(page)).length - antes).toBe(1);
  const [aviso] = (await avisos(page)).slice(antes);
  expect(aviso).toMatchObject({ title: "source espera que elijas en la terminal", tag: `lienzo-${KIRO}` });
  // el mismo diálogo redibujado no vuelve a avisar
  await empujar(page, { type: "session", session: { ...espera, last_reply: "redibujado" } });
  await page.waitForTimeout(300);
  expect((await avisos(page)).length - antes).toBe(1);
});

test("un permiso de hook avisa por su pendiente y el diálogo de la misma tarjeta no lo duplica", async ({ page }) => {
  await prepararAvisos(page);
  const claude = sesiones()[0];
  await abrirTablero(page);
  const antes = (await avisos(page)).length;
  const nuevo: Pending = { request_id: "p9", session_id: claude.session_id, agent: "claude", tool_name: "Bash", tool_input: { command: "git push" }, expires_at: new Date(Date.now() + 60_000).toISOString() };
  await empujar(page, { type: "pending", pending: [...pendientes(), nuevo] });
  await empujar(page, {
    type: "session",
    session: { ...claude, state: "te_necesita", pending_id: "p9", needs: { kind: "dialog", detail: "Do you want to proceed?", where: "terminal", since: "2026-10-22T15:11:45-03:00" } },
  });
  await expect.poll(async () => (await avisos(page)).length - antes).toBe(1);
  await page.waitForTimeout(300);
  const nuevos = (await avisos(page)).slice(antes);
  expect(nuevos).toHaveLength(1);
  expect(nuevos[0].title).toContain("pide permiso: Bash");
});
