import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { SID, abrirTablero, sesiones } from "./tablero-fijo";

/** Apps de escritorio (ronda 2026-10-17): una sesión de Claude Desktop y un hilo de Codex desktop se
 *  ven como tarjetas de sólo lectura, con el nombre del canal nativo de la de Claude. Los datos son
 *  los medidos en vivo ese día (motor 3568 «Sesión de prueba», hilo 01a14a5d sin proceso). */
test("las sesiones de las apps de escritorio se marcan y no se pueden cerrar desde la tarjeta", async ({ page }, testInfo) => {
  const lista = sesiones().map((s): Session => {
    if (s.session_id === SID.mapas) {
      return { ...s, pid: 3568, no_console: true, external: { kind: "claude-desktop", via: "registro", desktop: true, canal: "Sesión de prueba" } as const };
    }
    if (s.session_id === SID.capas) {
      return { ...s, pid: null, source: "desktop" as const, no_console: true, external: { kind: "codex-desktop", via: "rollout", desktop: true } as const };
    }
    return s;
  });
  await abrirTablero(page, lista);
  const claude = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const codex = page.locator(`.card[data-sid="${SID.capas}"]`);

  const marcaClaude = claude.locator(".warn.external.desktop");
  await expect(marcaClaude).toHaveText("app de escritorio · Claude Desktop · canal «Sesión de prueba» · solo lectura");
  await expect(marcaClaude).toHaveAttribute("title", /Para escribirle: canal nativo, con SendMessage.*Nombre en el canal: «Sesión de prueba»/);
  const marcaCodex = codex.locator(".warn.external.desktop");
  // un server sin puede_enviar: no se inventa que no se le puede escribir
  await expect(marcaCodex).toHaveText("app de escritorio · Codex desktop · envío sin informar");
  await expect(marcaCodex).toHaveAttribute("title", /Sus permisos no llegan acá.*El server no informa si se le puede escribir/);
  await expect(marcaCodex).not.toHaveAttribute("title", /no le manda mensajes/);
  // ni el «sin consola» genérico ni el aviso de ejecución externa de un orquestador
  await expect(claude.getByText("sin consola", { exact: true })).toHaveCount(0);
  await expect(claude.getByText(/ejecución de claude-desktop/)).toHaveCount(0);

  // una CLI de verdad sigue sin marca
  await expect(page.locator(`.card[data-sid="${SID.coordinadora}"] .warn.external`)).toHaveCount(0);

  for (const card of [claude, codex]) {
    await card.locator("button.kebab").click();
    const menu = card.getByRole("menu");
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Cerrar proceso a la fuerza…" })).toHaveCount(0);
    await page.keyboard.press("Escape");
  }
  await page.screenshot({ path: testInfo.outputPath("escritorio.png") });
});

test("la marca de envío sale de lo que el server devuelve en `envio`", async ({ page }) => {
  const codex = { kind: "codex-desktop", via: "rollout", desktop: true } as const;
  const claude = { kind: "claude-desktop", via: "registro", desktop: true, canal: "Sesión de prueba" } as const;
  const lista = sesiones().map((s): Session => {
    if (s.session_id === SID.capas) return { ...s, pid: null, source: "desktop" as const, no_console: true, external: codex, envio: { puede: true, motivo: null, transporte: "codex_queue" as const } };
    if (s.session_id === SID.migracion) return { ...s, pid: null, source: "desktop" as const, no_console: true, external: codex, envio: { puede: false, motivo: "la tarjeta está detenida", transporte: "codex_queue" as const } };
    if (s.session_id === SID.mapas) return { ...s, pid: 3568, no_console: true, external: claude, envio: { puede: false, motivo: "escribile por el canal nativo desde una sesión de Claude (SendMessage a «Sesión de prueba»)", transporte: "canal_nativo" as const } };
    return s;
  });
  await abrirTablero(page, lista);
  const marca = (sid: string) => page.locator(`.card[data-sid="${sid}"] .warn.external.desktop`);
  await expect(marca(SID.capas)).toHaveText("app de escritorio · Codex desktop · se le escribe por codex queue");
  await expect(marca(SID.capas)).toHaveAttribute("title", /Envío: sí, por codex queue\./);
  await expect(marca(SID.migracion)).toHaveText("app de escritorio · Codex desktop · solo lectura");
  await expect(marca(SID.migracion)).toHaveAttribute("title", /Envío: no\. la tarjeta está detenida/);
  await expect(marca(SID.mapas)).toHaveText("app de escritorio · Claude Desktop · canal «Sesión de prueba» · solo lectura");
  await expect(marca(SID.mapas)).toHaveAttribute("title", /Envío: no\. escribile por el canal nativo.*SendMessage a «Sesión de prueba»/);
});
