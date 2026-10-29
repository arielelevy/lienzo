import type { Session } from "./types";

/** Un `claude -p` sin transcripción no tiene conversación que mostrar: al menos quién lo lanzó, entre
 *  paréntesis. Si el agente de arriba tiene tarjeta en esta PC, va su título; si no, su PID. Puro, con
 *  tests (lanzado-por.test.ts); el título lo da quien llama para no traer React. */
export function lanzadoPor(s: Session, sessions: Record<string, Session>, titulo: (s: Session) => string): string {
  const l = s.external?.launcher;
  if (s.external?.kind !== "batch" || s.transcript_path || !l || (!l.tool && !l.pid)) return "";
  const card = l.pid ? Object.values(sessions).find((o) => o.pid === l.pid && o.pc === s.pc && o.session_id !== s.session_id) : undefined;
  const quien = l.pid ? [l.agent ?? "agente", l.cuenta, card ? `«${titulo(card)}»` : `PID ${l.pid}`].filter(Boolean).join(" ") : "";
  return ` (${[l.tool, quien && `lanzado por ${quien}`].filter(Boolean).join(" · ")})`;
}
