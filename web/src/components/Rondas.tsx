import { useEffect, useState } from "react";
import { api } from "../api";
import { confirmaciones, useRondas } from "../rondas";
import type { PresionMemoria, Session } from "../types";

const CERRADO_VISIBLE_MS = 30 * 60_000;
const MEMORIA_CADA_MS = 30_000;

const hora = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** La tira de rondas largas, al lado de la de consultas: los avisos coordinados con sus
 *  confirmaciones, los turnos de recursos con dueño y cola, y la memoria baja con la sesión quieta
 *  que conviene cerrar. Sólo informa: las acciones van por la API o `coordinar.py`. */
export function RondasBar({ sessions }: { sessions: Record<string, Session> }) {
  const { avisos, turnos } = useRondas();
  const [memoria, setMemoria] = useState<PresionMemoria | null>(null);
  const [ahora, setAhora] = useState(Date.now);
  useEffect(() => {
    let vivo = true;
    const mirar = () => {
      api.get<PresionMemoria>("/memoria").then((m) => vivo && setMemoria(m), () => null);
      setAhora(Date.now());
    };
    mirar();
    const t = window.setInterval(mirar, MEMORIA_CADA_MS);
    return () => {
      vivo = false;
      window.clearInterval(t);
    };
  }, []);
  const nombre = (sid: string) => sessions[sid]?.title || sessions[sid]?.repo || sid.slice(0, 8);
  const visibles = avisos.filter((a) => a.estado === "abierto" || (a.cerrado && ahora - new Date(a.cerrado).getTime() < CERRADO_VISIBLE_MS));
  const ocupados = Object.entries(turnos).filter(([, t]) => t.dueno || t.cola.length);
  const bajo = memoria?.bajo ? memoria : null;
  if (!visibles.length && !ocupados.length && !bajo) return null;
  return (
    <div className="rondas-bar" role="list" aria-label="avisos coordinados, turnos y memoria">
      {bajo && (
        <span role="listitem" className="ronda-chip memoria" title={`umbral ${bajo.umbral_gb} GB${bajo.max_sesiones_por_repo ? ` · tope ${bajo.max_sesiones_por_repo} sesiones por repo` : ""}`}>
          <span aria-hidden>⚠</span>
          <span>memoria {bajo.mem_free_gb?.toFixed(1)} GB libres</span>
          {bajo.cerrar[0] && <span className="ronda-dim">· cerrar «{bajo.cerrar[0].title || bajo.cerrar[0].repo}»{bajo.cerrar[0].quieta_desde ? `, quieta desde las ${hora(bajo.cerrar[0].quieta_desde)}` : ""}</span>}
        </span>
      )}
      {visibles.map((a) => {
        const c = confirmaciones(a);
        const detalle = a.estado === "abierto" ? (c.faltan.length ? `falta ${c.faltan.map(nombre).join(", ")}` : "") : a.estado;
        const titulo = `${a.texto}\n\n${Object.entries(a.destinos)
          .map(([sid, d]) => `${nombre(sid)}: ${d.estado}${d.nota ? ` (${d.nota})` : ""}`)
          .join("\n")}`;
        return (
          <span key={a.id} role="listitem" className={`ronda-chip aviso ${a.estado}`} title={titulo}>
            <span aria-hidden>📣</span>
            <span className="ronda-texto">{a.texto}</span>
            <span className="ronda-avance">
              {c.hechas}/{c.total} ack{detalle ? ` · ${detalle}` : ""}
            </span>
          </span>
        );
      })}
      {ocupados.map(([recurso, t]) => (
        <span key={recurso} role="listitem" className="ronda-chip turno" title={t.cola.map((x, i) => `${i + 1}. ${nombre(x.session_id)}${x.motivo ? ` — ${x.motivo}` : ""}`).join("\n") || "sin cola"}>
          <span aria-hidden>🔒</span>
          <span>{recurso}</span>
          <span className="ronda-avance">
            {t.dueno ? `${nombre(t.dueno.session_id)} hasta las ${hora(t.dueno.vence)}` : "libre"}
            {t.cola.length ? ` · ${t.cola.length} en cola` : ""}
          </span>
        </span>
      ))}
    </div>
  );
}
