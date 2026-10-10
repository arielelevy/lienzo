import { useSyncExternalStore } from "react";
import type { ConsultaResumen } from "./types";

/** Las consultas entre investigadores (lienzo/consulta.py), compartidas entre el tablero y las
 *  tarjetas sin pasarlas por props: las alimenta useLienzoData (GET /consultas y el SSE `consulta`). */
let estado: Record<string, ConsultaResumen> = {};
const oyentes = new Set<() => void>();

export function setConsultas(lista: ConsultaResumen[]): void {
  estado = Object.fromEntries(lista.map((c) => [c.id, c]));
  oyentes.forEach((f) => f());
}

export function upsertConsulta(c: ConsultaResumen): void {
  estado = { ...estado, [c.id]: c };
  oyentes.forEach((f) => f());
}

function suscribir(f: () => void): () => void {
  oyentes.add(f);
  return () => oyentes.delete(f);
}

export function useConsultas(): Record<string, ConsultaResumen> {
  return useSyncExternalStore(suscribir, () => estado);
}

export const ABIERTA = (c: ConsultaResumen) => c.estado === "abierta" || c.estado === "sintetizando" || c.estado === "revisando";

export type RolConsulta = { rol: "investigador" | "revisor" | "coordinador"; consulta: ConsultaResumen; coordina?: boolean };

/** El papel de una tarjeta en una consulta, o null. Vale mientras la consulta está abierta y, ya cerrada,
 *  mientras la tarjeta no se reusó: su último pedido sigue siendo uno de esa consulta (empieza con su
 *  marca). Una tarjeta borrada no tiene sesión y no pasa por acá. Gana la consulta más nueva. */
export function rolDe(consultas: Record<string, ConsultaResumen>, sid: string, lastPrompt?: string | null): RolConsulta | null {
  const orden = Object.values(consultas).sort((a, b) => b.creada.localeCompare(a.creada));
  for (const c of orden) {
    const vigente = ABIERTA(c) || (lastPrompt ?? "").trimStart().startsWith(`[consulta ${c.id}`);
    if (!vigente) continue;
    if (c.investigadores.includes(sid) && !(sid in c.fuera)) {
      // sin revisor aparte, el primer investigador sintetiza: mientras sintetiza se lo muestra como revisor
      const sintetiza = c.revisor === sid && c.estado === "sintetizando";
      return { rol: sintetiza ? "revisor" : "investigador", consulta: c };
    }
    if (c.revisor === sid) return { rol: "revisor", consulta: c, coordina: c.coordinador === sid };
    if (c.coordinador === sid) return { rol: "coordinador", consulta: c };
  }
  return null;
}

/** «vuelta 2 de 3 · esperando a Codex», «síntesis · esperando a Claude», en palabras. */
export function avance(c: ConsultaResumen): string {
  const etapa =
    c.estado === "abierta" ? `vuelta ${c.vuelta} de ${c.vueltas}` : c.estado === "sintetizando" ? "síntesis" : c.estado === "revisando" ? "revisión de la síntesis" : c.estado;
  return c.esperando.length ? `${etapa} · esperando a ${c.esperando.join(", ")}` : etapa;
}
