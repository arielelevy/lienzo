import { useEffect, useState } from "react";
import { api } from "../api";
import { ABIERTA, avance, useConsultas } from "../consultas";
import type { ConsultaEntera, ConsultaResumen } from "../types";

/** La tira de consultas arriba del tablero: las abiertas (y las tres últimas cerradas, apagadas),
 *  cada una con su pregunta y en qué va. Un click abre la consulta entera. */
// las cerradas que la persona sacó de la tira con la cruz: solo en este navegador (la consulta sigue en disco)
const OCULTAS = "lienzo.consultas.ocultas";
const CERRADA_VISIBLE_MS = 30 * 60_000;
function leerOcultas(): string[] {
  try {
    return JSON.parse(localStorage.getItem(OCULTAS) || "[]") as string[];
  } catch {
    return [];
  }
}

export function ConsultasBar() {
  const consultas = useConsultas();
  const [abierta, setAbierta] = useState<string | null>(null);
  const [ocultas, setOcultas] = useState<string[]>(leerOcultas);
  const [ahora, setAhora] = useState(Date.now);
  useEffect(() => {
    const t = window.setInterval(() => setAhora(Date.now()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  const ocultar = (id: string) => {
    const nuevas = [...ocultas, id].slice(-50);
    setOcultas(nuevas);
    try {
      localStorage.setItem(OCULTAS, JSON.stringify(nuevas));
    } catch {
      /* sin almacenamiento (ventana privada): se oculta hasta recargar */
    }
  };
  const lista = Object.values(consultas).sort((a, b) => b.creada.localeCompare(a.creada));
  const vivas = lista.filter(ABIERTA);
  // una cerrada se va sola de la tira a los 30 min de cerrar (o antes, con la cruz); sigue en disco.
  // El reloj avanza desde un timer, no en el render (como en Card)
  const reciente = (c: ConsultaResumen) => !c.cerrada || ahora - new Date(c.cerrada).getTime() < CERRADA_VISIBLE_MS;
  const viejas = lista.filter((c) => !ABIERTA(c) && !ocultas.includes(c.id) && reciente(c)).slice(0, 3);
  if (!vivas.length && !viejas.length) return null;
  return (
    <>
      <div className="consultas-bar" role="list" aria-label="consultas entre investigadores">
        {[...vivas, ...viejas].map((c) => (
          <span key={c.id} role="listitem" className={`consulta-chip ${ABIERTA(c) ? "viva" : "vieja"}`}>
            <button className="consulta-abrir" onClick={() => setAbierta(c.id)} title={c.pregunta}>
              <span className="consulta-icono" aria-hidden>🔬</span>
              <span className="consulta-pregunta">{c.pregunta}</span>
              <span className="consulta-avance">{avance(c)}</span>
            </button>
            {!ABIERTA(c) && (
              <button className="consulta-quitar" onClick={() => ocultar(c.id)} aria-label="sacar de la tira" title="sacar de la tira (la consulta queda guardada)">
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      {abierta && <ConsultaVista id={abierta} resumen={consultas[abierta]} onClose={() => setAbierta(null)} />}
    </>
  );
}

/** Una consulta entera: una columna por investigador, una fila por vuelta, la síntesis al pie. */
function ConsultaVista({ id, resumen, onClose }: { id: string; resumen?: ConsultaResumen; onClose: () => void }) {
  const [c, setC] = useState<ConsultaEntera | null>(null);
  const [error, setError] = useState<string | null>(null);
  // se relee cuando cambia el resumen (llegó una respuesta por el SSE)
  const marca = resumen ? `${resumen.estado}|${resumen.vuelta}|${resumen.esperando.join(",")}` : "";
  useEffect(() => {
    api.get<ConsultaEntera>(`/consultas/${id}`).then(setC, (e) => setError(String(e)));
  }, [id, marca]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const cancelar = async () => {
    if (!confirm("¿Cancelar la consulta? Lo que ya respondieron queda guardado.")) return;
    await api.post(`/consultas/${id}/cancelar`, {});
  };
  return (
    <div className="consulta-fondo" onClick={onClose}>
      <section className="consulta-vista" role="dialog" aria-modal="true" aria-label="consulta entre investigadores" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>🔬 {c?.pregunta ?? resumen?.pregunta ?? "consulta"}</h2>
          <button className="consulta-cerrar" onClick={onClose} aria-label="cerrar">×</button>
        </header>
        {error && <p className="consulta-error">{error}</p>}
        {c && (
          <>
            <p className="consulta-meta">
              {resumen ? avance(resumen) : c.estado}
              {" — revisor: "}
              {c.nombres[c.revisor] ?? c.revisor.slice(0, 8)}
              {Object.keys(c.fuera).length > 0 && ` — salieron: ${Object.entries(c.fuera).map(([s, m]) => `${c.nombres[s] ?? s.slice(0, 8)} (${m})`).join(", ")}`}
              {c.motivo && ` — ${c.motivo}`}
            </p>
            <div className="consulta-tabla" style={{ gridTemplateColumns: `repeat(${c.investigadores.length}, minmax(0, 1fr))` }}>
              {c.investigadores.map((s) => (
                <div key={s} className="consulta-col-titulo">{c.nombres[s] ?? s.slice(0, 8)}</div>
              ))}
              {Object.keys(c.respuestas)
                .sort((a, b) => Number(a) - Number(b))
                .flatMap((n) =>
                  c.investigadores.map((s) => (
                    <article key={`${n}-${s}`} className="consulta-respuesta">
                      <h3>vuelta {n}</h3>
                      <div className="consulta-texto">{c.respuestas[n][s]?.texto ?? (c.pendientes[s] ? "…pensando" : "—")}</div>
                    </article>
                  )),
                )}
            </div>
            {c.sintesis && (
              <article className="consulta-sintesis">
                <h3>Síntesis de {c.nombres[c.revisor] ?? "el revisor"}</h3>
                <div className="consulta-texto">{c.sintesis}</div>
                {Object.entries(c.objeciones).length > 0 && (
                  <ul className="consulta-objeciones">
                    {Object.entries(c.objeciones).map(([s, t]) => (
                      <li key={s}><b>{c.nombres[s] ?? s.slice(0, 8)}:</b> {t}</li>
                    ))}
                  </ul>
                )}
              </article>
            )}
            {ABIERTA(c as unknown as ConsultaResumen) && (
              <footer>
                <button onClick={cancelar}>Cancelar la consulta</button>
              </footer>
            )}
          </>
        )}
      </section>
    </div>
  );
}
