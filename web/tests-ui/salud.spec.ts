import { expect, test, type Page } from "@playwright/test";
import { SID, abrirTablero, esperarQuietud } from "./tablero-fijo";
import { contrasteMalo, linea, type FalloContraste } from "./medidas";

/** Recorrido completo: lo que hace alguien en un rato de uso. Sirve de guion para las dos pruebas
 *  de acá, que miran cosas distintas del mismo paseo. */
async function recorrido(page: Page) {
  const card = (sid: string) => page.locator(`.card[data-sid="${sid}"]`);

  // elegir una tarjeta y leer sus conexiones en palabras
  await card(SID.coordinadora).locator(".title").click();
  await expect(card(SID.coordinadora)).toHaveClass(/\bpicked\b/);
  await esperarQuietud(page);

  // abrir el panel y pasar por sus cuatro pestañas
  await card(SID.mapas).locator(".title").dblclick();
  await expect(page.locator(".panel")).toHaveCount(1);
  for (const t of ["Conversación", "Conexiones", "Pantalla", "Destacados"]) {
    await page.locator(".panel .tabs button", { hasText: t }).click();
    await expect(page.locator(".panel .body")).toBeVisible();
  }
  await page.locator(".panel button.x").click();
  await expect(page.locator(".panel")).toHaveCount(0);

  // abrir la columna Muerta y volver a cerrarla
  await page.locator(".board .col.muerta .vlabel").click();
  await esperarQuietud(page);
  await page.locator(".board .col.muerta h2").click();
  await esperarQuietud(page);

  // colapsar Te necesita y expandirla
  await page.locator(".board .col.te_necesita h2").click();
  await esperarQuietud(page);
  await page.locator(".board .col.te_necesita .vlabel").click();
  await esperarQuietud(page);

  // la ayuda con ?, cerrada con Esc
  await page.locator(".board").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("?");
  await expect(page.locator(".gate-box.help")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".gate-box.help")).toHaveCount(0);

  // la búsqueda con /, escribir y limpiar
  await page.keyboard.press("/");
  await page.keyboard.type("mapo");
  await esperarQuietud(page);
  await expect(page.locator(".card")).toHaveCount(3); // mapo: dos en Trabajo y una en Te necesita
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Backspace");
  await esperarQuietud(page);

  // y achicar la ventana
  await page.setViewportSize({ width: 1152, height: 800 });
  await esperarQuietud(page);
}

test("cero errores de consola en un recorrido completo", async ({ page }) => {
  const errores: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errores.push(`console.error: ${m.text()}`);
  });
  page.on("pageerror", (e) => errores.push(`excepción: ${e.message}`));
  page.on("requestfailed", (r) => errores.push(`pedido caído: ${r.method()} ${r.url()} (${r.failure()?.errorText})`));

  await page.setViewportSize({ width: 1440, height: 900 });
  await abrirTablero(page);
  await recorrido(page);

  expect(errores).toEqual([]);
});

/** Deuda de contraste que ya tenía la app cuando se escribió esta batería, con el número medido.
 *  No es una excusa: es un trinquete. Un texto nuevo que no llegue al mínimo hace fallar la prueba,
 *  y uno de estos que empeore, también. Si alguno se arregla, la prueba avisa para sacarlo de acá.
 *
 *  Las dos son de `opacity` encima de un color que solo, sin transparencia, sí llegaría:
 *  `--acc` (#5b9cff) sobre `--card` (#1d212b) da 5.15:1, y `--dim` (#8b93a7) da 4.79:1. */
const DEUDA = [
  { sel: "span.f", ratio: 3.91, donde: "card.css · .card .activity .f: var(--acc) con opacity .75" },
  { sel: "button.copy", ratio: 2.55, donde: "card.css · .card .copy y .dg .copy: var(--dim) con opacity .55" },
];

test("todo el texto llega al mínimo de contraste de WCAG AA", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await abrirTablero(page);

  const puntos: { donde: string; medidos: number; fallos: FalloContraste[] }[] = [];
  const medir = async (donde: string) => {
    const r = await contrasteMalo(page);
    puntos.push({ donde, medidos: r.medidos, fallos: r.fallos });
  };

  await medir("tablero");
  await page.locator(`.card[data-sid="${SID.coordinadora}"] .title`).click();
  await expect(page.locator(`.card[data-sid="${SID.coordinadora}"]`)).toHaveClass(/\bpicked\b/);
  await esperarQuietud(page);
  await medir("tarjeta elegida");

  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await expect(page.locator(".panel")).toHaveCount(1);
  await esperarQuietud(page);
  await medir("panel abierto");

  await page.locator(".panel .tabs button", { hasText: "Conexiones" }).click();
  await esperarQuietud(page);
  await medir("panel · Conexiones");

  // que haya medido de verdad: si el recorrido no encontró texto, la prueba no dice nada
  for (const p of puntos) expect(p.medidos, `${p.donde}: no se midió ningún texto`).toBeGreaterThan(30);

  const nuevos: string[] = [];
  const empeorados: string[] = [];
  const vistos = new Set<string>();
  for (const p of puntos) {
    for (const f of p.fallos) {
      const d = DEUDA.find((x) => x.sel === f.sel);
      if (!d) nuevos.push(`${p.donde}: ${linea(f)}`);
      else {
        vistos.add(d.sel);
        if (f.ratio < d.ratio - 0.05) empeorados.push(`${p.donde}: ${linea(f)} · era ${d.ratio}:1`);
      }
    }
  }
  const arreglados = DEUDA.filter((d) => !vistos.has(d.sel)).map((d) => `${d.sel} ya llega al mínimo (${d.donde}): sacalo de DEUDA en salud.spec.ts`);

  const total = puntos.reduce((a, p) => a + p.medidos, 0);
  console.log(`contraste: ${total} textos medidos en ${puntos.length} pantallas · deuda conocida: ${DEUDA.map((d) => `${d.sel} ${d.ratio}:1`).join(", ")}`);

  expect(nuevos, "texto nuevo por debajo del mínimo de WCAG AA").toEqual([]);
  expect(empeorados, "un contraste que ya era flojo empeoró").toEqual([]);
  expect(arreglados, "deuda de contraste saldada").toEqual([]);
});
