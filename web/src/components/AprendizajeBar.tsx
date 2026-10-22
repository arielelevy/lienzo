import { useEffect, useState } from "react";
import { api } from "../api";

const CADA_MS = 120_000;

export interface ResumenAprendizaje {
  proyecto: string; nombre: string; creencias: Record<string, number>;
  reglas_cuestionadas: number; encargos_clasificados: number; encargos_sin_clasificar: number;
}

/** La tira del aprendizaje: por proyecto, cuántas creencias esperan el veredicto de una persona,
 *  cuántas están vigentes y cuántas reglas quedaron cuestionadas. Un click abre la memoria de ese
 *  proyecto en Aprendizaje, donde el checklist dice qué sostiene el motor lógico. Sólo lee. */
export function AprendizajeBar({ onOpen }: { onOpen: (proyecto: string) => void }) {
  const [filas, setFilas] = useState<ResumenAprendizaje[]>([]);
  useEffect(() => {
    let vivo = true;
    const mirar = () => api.get<ResumenAprendizaje[]>("/conocimiento/aprendizaje-resumen").then((r) => vivo && Array.isArray(r) && setFilas(r), () => null);
    mirar();
    const t = window.setInterval(mirar, CADA_MS);
    return () => {
      vivo = false;
      window.clearInterval(t);
    };
  }, []);
  const visibles = filas.filter((f) => (f.creencias.propuesta ?? 0) || (f.creencias.vigente ?? 0) || f.reglas_cuestionadas);
  if (!visibles.length) return null;
  return (
    <div className="rondas-bar" role="list" aria-label="aprendizaje por proyecto">
      {visibles.map((f) => {
        const propuestas = f.creencias.propuesta ?? 0, vigentes = f.creencias.vigente ?? 0;
        const partes = [propuestas && `${propuestas} por validar`, vigentes && `${vigentes} vigente${vigentes === 1 ? "" : "s"}`, f.reglas_cuestionadas && `${f.reglas_cuestionadas} regla${f.reglas_cuestionadas === 1 ? "" : "s"} cuestionada${f.reglas_cuestionadas === 1 ? "" : "s"}`].filter(Boolean);
        return (
          <span key={f.proyecto} role="listitem">
            <button type="button" className="ronda-chip aprendizaje" onClick={() => onOpen(f.proyecto)}
              title={`Aprendizaje de ${f.nombre}: ${partes.join(", ")}. ${f.encargos_clasificados} encargos con tipo de trabajo y ${f.encargos_sin_clasificar} sin clasificar. Abrir en la memoria.`}>
              <span aria-hidden>🧠</span>
              <span className="ronda-texto">{f.nombre}</span>
              <span className="ronda-avance">{partes.join(" · ")}</span>
            </button>
          </span>
        );
      })}
    </div>
  );
}
