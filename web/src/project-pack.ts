/** Vista por proyecto: dónde va la caja de cada proyecto en la grilla de una columna.
 *
 *  Antes cada proyecto arrancaba una fila entera, y uno de una o dos tarjetas dejaba vacío el resto
 *  del ancho (pedido de Ariel, 2026-10-23: «si hay espacio podrían usar el ancho»). Ahora cada
 *  proyecto es una caja de `k` subcolumnas (sus frentes, con tope en las que entran) y las cajas se
 *  acomodan en estantes: cada una va al primer estante donde le queda lugar (first fit). La
 *  coordinadora ocupa la última fila de su caja, sola y centrada.
 *
 *  Las tarjetas siguen siendo hijas directas de `.cards` (con su key): la ubicación es explícita
 *  (grid-column / grid-row), así reacomodar no las remonta ni pierde lo que tengan a medio escribir. */

export interface ProjectBox {
  key: string;
  /** tarjetas del proyecto, con la coordinadora incluida */
  n: number;
  coordinator: boolean;
}

export interface Placement {
  /** primera subcolumna (1 en adelante) y cuántas ocupa */
  col: number;
  k: number;
  /** fila del título; las de tarjetas siguen abajo */
  row: number;
  /** filas de tarjetas, sin el título (la de la coordinadora incluida) */
  rows: number;
}

export function packProjects(boxes: ProjectBox[], lanes: number): Map<string, Placement> {
  const L = Number.isFinite(lanes) ? Math.max(1, Math.floor(lanes)) : 1; // sin dato, una subcolumna
  const estantes: { usado: number; alto: number; miembros: { key: string; col: number; k: number; rows: number }[] }[] = [];
  for (const b of boxes) {
    const frentes = Math.max(0, b.n - (b.coordinator ? 1 : 0));
    const k = Math.min(Math.max(frentes, 1), L);
    const rows = Math.ceil(frentes / k) + (b.coordinator ? 1 : 0);
    let estante = estantes.find((e) => e.usado + k <= L);
    if (!estante) {
      estante = { usado: 0, alto: 0, miembros: [] };
      estantes.push(estante);
    }
    estante.miembros.push({ key: b.key, col: estante.usado + 1, k, rows });
    estante.usado += k;
    estante.alto = Math.max(estante.alto, 1 + rows);
  }
  const out = new Map<string, Placement>();
  let fila = 1;
  for (const e of estantes) {
    for (const m of e.miembros) out.set(m.key, { col: m.col, k: m.k, row: fila, rows: m.rows });
    fila += e.alto;
  }
  return out;
}

/** La celda de la tarjeta `i` (0 en adelante, frentes primero y la coordinadora última) de una caja. */
export function cardCell(p: Placement, i: number, n: number, coordinator: boolean): { col: string; row: number } {
  if (coordinator && i === n - 1) return { col: `${p.col} / span ${p.k}`, row: p.row + p.rows };
  return { col: String(p.col + (i % p.k)), row: p.row + 1 + Math.floor(i / p.k) };
}
