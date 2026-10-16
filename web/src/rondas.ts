import { useSyncExternalStore } from "react";
import type { Aviso, RondasEstado } from "./types";

/** Avisos coordinados y turnos de recursos (lienzo/rondas.py), como las consultas: los alimenta
 *  useLienzoData (GET /avisos y el SSE `rondas`) y los lee la tira sin pasar por props. */
let estado: RondasEstado = { avisos: [], turnos: {}, politicas: {} };
const oyentes = new Set<() => void>();

export function setRondas(r: RondasEstado): void {
  estado = { avisos: r.avisos ?? [], turnos: r.turnos ?? {}, politicas: r.politicas ?? {} };
  oyentes.forEach((f) => f());
}

function suscribir(f: () => void): () => void {
  oyentes.add(f);
  return () => oyentes.delete(f);
}

export function useRondas(): RondasEstado {
  return useSyncExternalStore(suscribir, () => estado);
}

/** «2 de 3 confirmaron», contando sólo las confirmadas. */
export function confirmaciones(a: Aviso): { hechas: number; total: number; faltan: string[] } {
  const ds = Object.entries(a.destinos);
  const faltan = ds.filter(([, d]) => d.estado !== "confirmado").map(([sid]) => sid);
  return { hechas: ds.length - faltan.length, total: ds.length, faltan };
}
