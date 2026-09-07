/** Mediciones que las pruebas hacen dentro de la página. Todo lo que se afirma sale de un número
 *  leído del DOM pintado: rects, paths muestreados, colores calculados. Nada de `toBeVisible()`
 *  decorativo. */
import type { Page } from "@playwright/test";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Rect de cada tarjeta, por session_id, redondeado a 0,5 px (el subpíxel del layout no es señal). */
export async function rectsDeTarjetas(page: Page): Promise<Record<string, Rect>> {
  return page.evaluate(() => {
    const r2 = (n: number) => Math.round(n * 2) / 2;
    const out: Record<string, { x: number; y: number; width: number; height: number }> = {};
    for (const el of document.querySelectorAll<HTMLElement>(".card[data-sid]")) {
      const r = el.getBoundingClientRect();
      out[el.dataset.sid!] = { x: r2(r.x), y: r2(r.y), width: r2(r.width), height: r2(r.height) };
    }
    return out;
  });
}

/** Ancho de más. Dos números distintos, y hacen falta los dos:
 *   - `scroll`: cuántos píxeles se puede scrollear de costado. 0 es lo correcto.
 *   - `culpables`: qué elementos tienen su borde derecho fuera de la pantalla. Un elemento en
 *     `position: fixed` (el panel) no agranda `scrollWidth`: si se va para la derecha no hay barra
 *     ni scroll, simplemente no se ve y no hay forma de llegar. Mirar sólo `scrollWidth` deja pasar
 *     justo el caso peor. */
export async function desborde(page: Page) {
  return page.evaluate(() => {
    const de = document.documentElement;
    const ancho = de.clientWidth;
    const culpables: { sel: string; right: number; fuera: number }[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (r.right > ancho + 1) {
        const sel = `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).join(".") : ""}`;
        culpables.push({ sel, right: Math.round(r.right), fuera: Math.round(r.right - ancho) });
      }
    }
    // el más profundo primero: el que se sale de verdad, no sus padres
    culpables.sort((a, b) => b.fuera - a.fuera);
    return { scrollWidth: de.scrollWidth, clientWidth: ancho, scroll: Math.max(0, de.scrollWidth - ancho), culpables: culpables.slice(0, 4) };
  });
}

/** Cada flecha, muestreada cada 2 px con `getPointAtLength`, contra el rect de cada tarjeta.
 *  Se descartan los 6 px de cada punta (la flecha nace y muere pegada al borde de su tarjeta, ahí
 *  tiene que tocarla) y se exige que el punto entre 2 px para adentro del rect: es la misma
 *  tolerancia que usa la geometría (`inside(..., eps)`), no un margen inventado para pasar. */
export async function crucesDeFlechas(page: Page) {
  return page.evaluate(() => {
    const svg = document.querySelector<SVGSVGElement>("svg.arrows");
    const board = document.querySelector<HTMLElement>(".board");
    if (!svg || !board) return { flechas: 0, cruces: [] as { tarjeta: string; en: string; x: number; y: number; adentro: number }[] };
    const b = svg.getBoundingClientRect();
    const cards = [...document.querySelectorAll<HTMLElement>(".card[data-sid]")].map((el) => {
      const r = el.getBoundingClientRect();
      return { sid: el.dataset.sid!, l: r.left, t: r.top, r: r.right, b: r.bottom };
    });
    const EPS = 2;      // px hacia adentro del rect: menos que esto es "roza el borde"
    const PUNTA = 6;    // px de cada extremo, donde la flecha se apoya en su tarjeta
    const cruces: { tarjeta: string; en: string; x: number; y: number; adentro: number }[] = [];
    const paths = [...svg.querySelectorAll<SVGPathElement>("path.line")].filter((p) => !p.classList.contains("native-outer"));
    for (const p of paths) {
      const largo = p.getTotalLength();
      const idArrow = p.closest("g")?.getAttribute("data-ids") ?? p.getAttribute("class") ?? "?";
      for (let d = PUNTA; d <= largo - PUNTA; d += 2) {
        const pt = p.getPointAtLength(d);
        const x = b.left + pt.x;
        const y = b.top + pt.y;
        for (const c of cards) {
          const adentro = Math.min(x - c.l, c.r - x, y - c.t, c.b - y);
          if (adentro > EPS) cruces.push({ tarjeta: c.sid, en: idArrow, x: Math.round(x), y: Math.round(y), adentro: Math.round(adentro) });
        }
      }
    }
    // una flecha que cruza deja decenas de puntos: uno por tarjeta cruzada alcanza para el informe
    const vistos = new Set<string>();
    const unicos = cruces.filter((c) => {
      const k = `${c.en}->${c.tarjeta}`;
      if (vistos.has(k)) return false;
      vistos.add(k);
      return true;
    });
    return { flechas: paths.length, cruces: unicos };
  });
}

/** Cada glifo (el círculo clickeable de una flecha, con su letra) tiene que caer en el área útil de
 *  las columnas: adentro de una columna, o en el canal entre dos, y siempre por debajo del
 *  encabezado y por encima del piso de la columna. Afuera de eso queda flotando sobre el relleno
 *  del tablero, o encima de un título, y no se entiende de qué es. Tampoco puede caer sobre una
 *  tira colapsada: le taparía la etiqueta. Es el mismo criterio que la geometría dice cumplir
 *  (`allowed` + `strips` en arrows-geometry.ts), medido sobre lo que quedó pintado. */
export async function glifosFueraDeColumnas(page: Page) {
  return page.evaluate(() => {
    const bandas = [...document.querySelectorAll<HTMLElement>(".board .col")].map((el) => {
      const r = el.getBoundingClientRect();
      const h2 = el.querySelector<HTMLElement>(":scope > h2");
      return { clase: el.className.split(/\s+/)[1], l: r.left, t: h2 ? h2.getBoundingClientRect().bottom : r.top, r: r.right, b: r.bottom };
    });
    const tiras = [...document.querySelectorAll<HTMLElement>(".board .col.collapsed")].map((el) => {
      const r = el.getBoundingClientRect();
      return { l: r.left, r: r.right };
    });
    // franja vertical permitida en esa x: dentro de una columna, la suya; en el canal entre dos, la
    // más restrictiva de las dos; fuera de todas (el relleno del tablero), ninguna
    const franja = (x: number): [number, number] => {
      const hit = bandas.filter((b) => x >= b.l && x <= b.r);
      if (hit.length) return [Math.max(...hit.map((b) => b.t)), Math.min(...hit.map((b) => b.b))];
      const izq = bandas.filter((b) => b.r < x).sort((a, b) => b.r - a.r)[0];
      const der = bandas.filter((b) => b.l > x).sort((a, b) => a.l - b.l)[0];
      if (!izq || !der) return [Infinity, -Infinity];
      return [Math.max(izq.t, der.t), Math.min(izq.b, der.b)];
    };
    const fuera: { glifo: string; x: number; y: number; motivo: string }[] = [];
    const dots = [...document.querySelectorAll<SVGCircleElement>("svg.arrows circle.dot")];
    for (const c of dots) {
      const r = c.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y = r.top + r.height / 2;
      const glifo = c.parentElement?.querySelector("text")?.textContent ?? "?";
      const [t, b] = franja(x);
      if (!(y >= t - 1 && y <= b + 1)) {
        const motivo = t === Infinity ? "sobre el relleno del tablero, fuera de toda columna" : y < t ? `${Math.round(t - y)}px por encima del techo de la columna` : `${Math.round(y - b)}px por debajo del piso de la columna`;
        fuera.push({ glifo, x: Math.round(x), y: Math.round(y), motivo });
      } else if (tiras.some((s) => x > s.l + 1 && x < s.r - 1)) {
        fuera.push({ glifo, x: Math.round(x), y: Math.round(y), motivo: "encima de una columna colapsada, tapándole la etiqueta" });
      }
    }
    return { glifos: dots.length, fuera };
  });
}

export interface FalloContraste {
  texto: string;
  sel: string;
  color: string;
  fondo: string;
  ratio: number;
  minimo: number;
  px: number;
}

/** Contraste WCAG 2.1 de todo el texto pintado: 4.5:1, o 3:1 si el texto es grande (≥24 px, o
 *  ≥18.7 px en negrita). El fondo efectivo se compone subiendo por los ancestros hasta el primer
 *  color opaco, y la opacidad heredada entra en la cuenta (un `.dim` con opacity 0.6 contrasta
 *  menos de lo que dice su `color`). Quedan afuera los controles deshabilitados y lo marcado
 *  `aria-hidden`, que WCAG exceptúa. */
export async function contrasteMalo(page: Page): Promise<{ medidos: number; noMedibles: number; fallos: FalloContraste[] }> {
  return page.evaluate(() => {
    type RGBA = { r: number; g: number; b: number; a: number };
    const parse = (c: string): RGBA | null => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const over = (f: RGBA, b: RGBA): RGBA => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
    const lum = (c: RGBA) => {
      const ch = [c.r, c.g, c.b].map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
    };
    const ratio = (a: RGBA, b: RGBA) => { const l1 = lum(a); const l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
    const hex = (c: RGBA) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
    const sel = (el: Element) => `${el.tagName.toLowerCase()}${typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).slice(0, 3).join(".") : ""}`;

    let noMedibles = 0;
    const fondoDe = (el: Element): RGBA | null => {
      const capas: RGBA[] = [];
      let n: Element | null = el;
      while (n) {
        const cs = getComputedStyle(n);
        if (cs.backgroundImage && cs.backgroundImage !== "none") return null; // degradé o imagen: no se mide con un número
        const c = parse(cs.backgroundColor);
        if (c && c.a > 0) {
          capas.push(c);
          if (c.a >= 0.999) break;
        }
        n = n.parentElement;
      }
      let base: RGBA = { r: 255, g: 255, b: 255, a: 1 }; // el lienzo del navegador, si nada abajo era opaco
      for (let i = capas.length - 1; i >= 0; i--) base = over(capas[i], base);
      return base;
    };
    const opacidad = (el: Element) => {
      let o = 1;
      let n: Element | null = el;
      while (n) {
        o *= parseFloat(getComputedStyle(n).opacity || "1");
        n = n.parentElement;
      }
      return o;
    };

    const fallos: { texto: string; sel: string; color: string; fondo: string; ratio: number; minimo: number; px: number }[] = [];
    let medidos = 0;
    // sólo pictogramas (un 📋 o un ⏰ solos): Chromium los pinta con la fuente de color y no
    // respeta `color`, así que medir su contraste da un número que no es el que se ve
    const soloPicto = (t: string) => !t.replace(/[\p{Extended_Pictographic}\p{Emoji_Presentation}️‍\s]/gu, "");
    const todo = [...document.querySelectorAll<HTMLElement>("body *")];
    for (const el of todo) {
      // el texto SVG (los glifos de las flechas) se mide aparte: su color va en `fill`, no en `color`
      if (el.namespaceURI !== "http://www.w3.org/1999/xhtml") continue;
      if (el.closest("[aria-hidden='true']")) continue;
      if (el.matches(":disabled") || el.closest("[disabled]")) continue;
      const propio = [...el.childNodes].filter((n) => n.nodeType === 3 && (n.textContent ?? "").trim()).map((n) => n.textContent!.trim()).join(" ");
      if (!propio || soloPicto(propio)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const o = opacidad(el);
      if (o < 0.02) continue; // invisible a propósito (menú cerrado, botón que aparece al pasar el mouse)
      const col = parse(cs.color);
      const fondo = fondoDe(el);
      if (!col || !fondo) { noMedibles++; continue; }
      const fg = over({ ...col, a: col.a * o }, fondo);
      const px = parseFloat(cs.fontSize);
      const peso = parseInt(cs.fontWeight, 10) || 400;
      const grande = px >= 24 || (px >= 18.66 && peso >= 700);
      const minimo = grande ? 3 : 4.5;
      const rr = ratio(fg, fondo);
      medidos++;
      if (rr < minimo - 0.005) {
        fallos.push({ texto: propio.slice(0, 40), sel: sel(el), color: hex(fg), fondo: hex(fondo), ratio: Math.round(rr * 100) / 100, minimo, px });
      }
    }
    // el glifo de una flecha es texto SVG sobre el círculo de la propia flecha: mismo criterio,
    // pero los colores salen de `fill` y no de `color`/`background-color`
    for (const g of document.querySelectorAll<SVGGElement>("svg.arrows g.arrow")) {
      const t = g.querySelector<SVGTextElement>("text.lbl");
      const c = g.querySelector<SVGCircleElement>("circle.dot");
      if (!t || !c || !(t.textContent ?? "").trim()) continue;
      const fg = parse(getComputedStyle(t).fill);
      const bg = parse(getComputedStyle(c).fill);
      if (!fg || !bg) { noMedibles++; continue; }
      const fondo = over(bg, { r: 17, g: 19, b: 24, a: 1 });
      const px = parseFloat(getComputedStyle(t).fontSize);
      const minimo = px >= 24 ? 3 : 4.5;
      const rr = ratio(over(fg, fondo), fondo);
      medidos++;
      if (rr < minimo - 0.005) fallos.push({ texto: t.textContent!.trim(), sel: "svg text.lbl", color: hex(over(fg, fondo)), fondo: hex(fondo), ratio: Math.round(rr * 100) / 100, minimo, px });
    }
    return { medidos, noMedibles, fallos };
  });
}

/** Alto de una tarjeta, medido del rect pintado. */
export async function altoDeTarjeta(page: Page, sid: string): Promise<number> {
  return page.evaluate((s) => {
    const el = document.querySelector<HTMLElement>(`.card[data-sid="${s}"]`);
    if (!el) throw new Error(`no hay tarjeta ${s}`);
    return Math.round(el.getBoundingClientRect().height * 2) / 2;
  }, sid);
}

/** Texto plano de un fallo de contraste, para que el reporte diga el número y no "falló". */
export const linea = (f: FalloContraste) => `${f.ratio}:1 (min ${f.minimo}) ${f.color} sobre ${f.fondo} · ${f.sel} · "${f.texto}"`;
