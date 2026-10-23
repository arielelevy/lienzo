import type { Session, Turno } from "./types";

export const NOTICE_MS = 3 * 60_000;

/** Avisos efímeros: el historial conserva el dato, la tarjeta sólo muestra lo vigente. */
export function freshNotice(at: string | undefined, now: number): boolean {
  const age = now - Date.parse(at ?? "");
  return age >= 0 && age < NOTICE_MS;
}

export function showApproval(s: Session, now: number): boolean {
  const at = s.auto_aprobado?.at;
  return s.alive !== false && freshNotice(at, now)
    && !(Date.parse(s.prompt_ts ?? "") > Date.parse(at ?? ""))
    && (s.state !== "termino" || Date.parse(at ?? "") >= Date.parse(s.state_since));
}

export function showSendNotice(s: Session, now: number): boolean {
  if (s.needs?.kind !== "sin_enviar" && s.needs?.kind !== "sin_transcripcion") return true;
  const since = s.needs.since ?? s.state_since;
  if (!freshNotice(since, now) || s.alive === false || Date.parse(s.prompt_ts ?? "") > Date.parse(since)) return false;
  const receipt = s.agent === "claude" ? s.envio_claude : s.envio_codex;
  return !(receipt?.estado === "entregado" && receipt.confirmacion_final === true
    && (receipt.at ?? 0) * 1000 >= Date.parse(since));
}

export function showTurnPrompt(s: Session, turnos: Record<string, Turno>, now: number): boolean {
  const match = /^\[lienzo\] te toca el turno de «([^»]+)»/.exec(s.last_prompt);
  if (!match) return true;
  const owner = turnos[match[1]]?.dueno;
  return !!owner && owner.session_id === s.session_id && Date.parse(owner.vence) > now
    && freshNotice(owner.desde, now);
}
