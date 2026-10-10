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

export type RolConsulta = { rol: "investigador" | "revisor" | "coordinador"; consulta: ConsultaResumen };

/** El papel de una tarjeta en la consulta abierta en que participa, o null. */
export function rolDe(consultas: Record<string, ConsultaResumen>, sid: string): RolConsulta | null {
  for (const c of Object.values(consultas)) {
    if (!ABIERTA(c)) continue;
    if (c.investigadores.includes(sid) && !(sid in c.fuera)) {
      // sin revisor aparte, el primer investigador sintetiza: mientras sintetiza se lo muestra como revisor
      const sintetiza = c.revisor === sid && c.estado === "sintetizando";
      return { rol: sintetiza ? "revisor" : "investigador", consulta: c };
    }
    if (c.revisor === sid) return { rol: "revisor", consulta: c };
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
