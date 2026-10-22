import { expect, test } from "@playwright/test";
import type { Peer } from "../src/types";
import { abrirTablero } from "./tablero-fijo";

/** Las tarjetas de las extensiones de Chrome arrancan ocultas (pedido de Ariel, 2026-10-21) y el
 *  chip «chrome» del encabezado las muestra y las vuelve a ocultar. */
const PEER: Peer = {
  pc_id: "local-1",
  name: "oficina",
  color: "#5b9cff",
  alive: true,
  last_seen: new Date().toISOString(),
  local: true,
  health: {
    mem_free_gb: 3.4,
    mem_total_gb: 16,
    cpu_pct: 22,
    temp_c: 68,
    chrome_conexiones: [{ agent: "claude", host: "desktop", pids: [1], desde: new Date().toISOString() }],
  },
};

test("las tarjetas de extensiones de Chrome arrancan ocultas y el chip las muestra", async ({ page }) => {
  await abrirTablero(page, undefined, [PEER]);
  const chip = page.locator(".chip.chromeext");
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".card.chromeext")).toHaveCount(0);

  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".card.chromeext")).toHaveCount(1);

  await chip.click();
  await expect(page.locator(".card.chromeext")).toHaveCount(0);
});
