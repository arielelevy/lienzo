import { useCallback, useEffect, useState } from "react";
import { CUOTAS_VIGENCIA_MS, leerCuotas, type AgenteCuota, type CuotaAgente, type CuotasResponse, type RecursoMensual } from "../api";
import { AGENTS } from "../agents";
import "../cuotas.css";

type AgenteVisible = AgenteCuota | "claude_smartbi" | "kiro";
const AGENTES: AgenteVisible[] = ["claude", "claude_smartbi", "codex", "kiro"];
const SIN_KIRO: CuotaAgente = { ok: false, plan: null, weekly: null, five_hour: null, read_at: null, error: "el servidor no informó el uso de Kiro" };
const mensual = (nombre: string, r: RecursoMensual | null | undefined) => !r ? `${nombre}: no informado` :
  `${nombre}: ${cantidades(r)}`;
// en la tarjeta de Kiro, sólo los números: el rótulo «Créditos por mes» queda en el aria-label (pedido de Ariel)
const cantidades = (r: RecursoMensual) =>
  `${r.used} usados · ${r.available === null ? "disponibles no informados" : `${r.available} disponibles`}${r.limit === null ? "" : ` de ${r.limit}`}`;

const etiquetaAgente = (a: string) => (AGENTS as Record<string, { label: string } | undefined>)[a === "claude_smartbi" ? "claude" : a]?.label ?? a;

const fecha = (iso: string | null | undefined) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

const pct = (n: number) => `${Math.round(n)} %`;
const gasto = (s: NonNullable<CuotaAgente["spend"]>) => `Créditos: USD ${s.used.toFixed(2)} usados${s.limit === null ? " · límite no informado" : ` de USD ${s.limit.toFixed(2)}`}`;

/** Codex en plan prolite no informa ventana de 5 h (medido 2026-10-17): se dice, no se inventa. */
const SIN_5H = "el plan no informa 5 h";

function detalle(a: AgenteVisible, c: CuotaAgente, data: CuotasResponse): string {
  const lineas = [etiquetaAgente(a) + (c.plan ? ` (plan ${c.plan})` : "")];
  if (!c.ok) lineas.push(`No se pudo leer: ${c.error || "sin detalle"}`);
  if (c.weekly) lineas.push(`Semana: ${pct(c.weekly.used_pct)} usado${fecha(c.weekly.resets_at) ? `, reinicia ${fecha(c.weekly.resets_at)}` : ""}`);
  if (c.five_hour) lineas.push(`5 h: ${pct(c.five_hour.used_pct)} usado${fecha(c.five_hour.resets_at) ? `, reinicia ${fecha(c.five_hour.resets_at)}` : ""}`);
  else if (c.ok && a !== "kiro" && c.weekly) lineas.push(`5 h: ${SIN_5H}`);
  if ((a === "claude" || a === "claude_smartbi") && !c.weekly && c.spend) lineas.push(gasto(c.spend));
  if (a === "kiro") {
    lineas.push(mensual("Créditos por mes", c.credits), mensual("Mensajes por mes", c.messages));
    lineas.push(c.resets_at ? `Renueva ${c.resets_at}` : "Renovación: no informada");
  }
  lineas.push(fecha(c.read_at) ? `Medido ${fecha(c.read_at)}` : "Sin medición");
  if (data.sugerido === a) lineas.push(`Conviene ahora: ${data.motivo}`);
  else if (!data.sugerido) lineas.push(`Ninguno con margen: ${data.motivo}`);
  lineas.push("Click: medir de nuevo");
  return lineas.join("\n");
}

/** Indicador abajo a la derecha (pedido de Ariel, 2026-10-17): Claude y Codex lado a lado, con el %
 *  semanal (y 5 h si hay), la hora de la medición y cuál conviene. Click en cualquiera mide de nuevo.
 *  Sin respuesta válida de /cuotas (server sin la ruta) no se muestra: no hay nada que decir. */
export function Cuotas() {
  const [data, setData] = useState<CuotasResponse | null>(null);
  const [midiendo, setMidiendo] = useState(false);
  const [fallo, setFallo] = useState("");
  const cargar = useCallback((forzar: boolean) => leerCuotas(forzar)
    .then(d => { setData(d); setFallo(""); })
    .catch(e => setFallo((e as Error).message)), []);
  useEffect(() => {
    void cargar(false);
    const id = setInterval(() => void cargar(false), CUOTAS_VIGENCIA_MS);
    return () => clearInterval(id);
  }, [cargar]);
  const medir = () => {
    setMidiendo(true);
    void cargar(true).finally(() => setMidiendo(false));
  };
  if (!data) return null;
  return <div className="cuotas" role="group" aria-label="Cuotas de Claude, Codex y Kiro" aria-busy={midiendo}>
    {AGENTES.map(a => {
      if (a === "claude_smartbi" && !data.claude_smartbi) return null;
      const c = data[a] ?? SIN_KIRO;
      const anterior = !c.ok && !!(c.weekly || c.spend || c.credits || c.messages);
      const esClaude = a === "claude" || a === "claude_smartbi";
      const sugerido = data.sugerido === a;
      const alta = !!c.ok && ((c.weekly?.used_pct ?? 0) >= 90 || (c.five_hour?.used_pct ?? 0) >= 90);
      const medido = fecha(c.read_at);
      const uso = !c.ok && !anterior ? (a === "claude_smartbi" && c.error?.startsWith("SmartBI sin iniciar sesión") ? "sin iniciar sesión" : "sin lectura") : a === "kiro" ? (c.credits ? cantidades(c.credits) : "créditos no informados") : c.weekly ? `${pct(c.weekly.used_pct)} usado semanal${c.five_hour ? ` · ${pct(c.five_hour.used_pct)} usado 5 h` : ""}` : esClaude && c.spend ? gasto(c.spend) : "sin dato semanal";
      return <button key={a} type="button" className={`cuota ${a}${sugerido ? " sugerido" : ""}${c.ok ? "" : " fallida"}${alta ? " alta" : ""}`}
        disabled={midiendo} title={detalle(a, c, data) + (fallo ? `\nÚltimo intento falló: ${fallo}` : "")}
        aria-label={`${etiquetaAgente(a)}: ${a === "kiro" ? mensual("Créditos por mes", c.credits) : uso}${c.ok && !c.five_hour && a !== "kiro" && c.weekly ? `, ${SIN_5H}` : ""}${a === "kiro" ? `; ${mensual("Mensajes por mes", c.messages)}; renueva ${c.resets_at ?? "no informado"}` : ""}${anterior ? ", última lectura; actualización fallida" : ""}${sugerido ? ", conviene ahora" : ""}. ${medido ? `Medido ${medido}` : "Sin medición"}. Medir de nuevo`}
        onClick={medir}>
        <span className="cuota-fila"><span className="cuota-nombre">{etiquetaAgente(a)}</span>{sugerido && <span className="cuota-sugerido">conviene</span>}</span>
        {(c.ok || anterior) && esClaude && !c.weekly && c.spend ? <>
          <span className="cuota-uso">Créditos: USD {c.spend.used.toFixed(2)} usados </span>
          <span className="cuota-uso">{c.spend.limit === null ? "límite no informado" : `de USD ${c.spend.limit.toFixed(2)}`}</span>
        </> : (c.ok || anterior) && c.weekly && c.five_hour ? <>
          <span className="cuota-uso">{pct(c.weekly.used_pct)} usado semanal</span>
          <span className="cuota-uso">{pct(c.five_hour.used_pct)} usado 5 h</span>
        </> : <span className="cuota-uso">{uso}</span>}
        {a === "kiro" && <>{c.messages && <span className="cuota-uso">{mensual("Mensajes por mes", c.messages)}</span>}<span className="cuota-medido">Renueva {c.resets_at ?? "no informado"}</span></>}
        <span className="cuota-medido">{midiendo ? "midiendo…" : fallo ? "no se pudo medir" : medido ?? "sin medición"}</span>
        {anterior && <span className="cuota-medido" role="status">Última lectura · actualización fallida</span>}
      </button>;
    })}
  </div>;
}
