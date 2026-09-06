import type { Session } from "./types";

/** Interpretar una frase corta como conexion. Sin modelo: patrones de castellano rioplatense.
 *
 *   mandá "continuá" a las 16:00            -> at, texto continuá, a esta sesion
 *   a las 4pm continuá                       -> at
 *   en 30 minutos decile seguí              -> at (ahora + 30 min)
 *   cada 30 min continuá                     -> at periodica: primera en 30 min, cada 30 min, 5 veces
 *   cada 2 horas decile continuá hasta 6 veces -> at periodica, tope 6
 *   todos los días a las 9 continuá         -> at periodica: primera a las 9, cada 24 h
 *   en 10 min cada 30 min seguí hasta las 18:00 -> primera en 10 min, cada 30, tantas como entren hasta las 18
 *   cuando termine mandale la respuesta a MAPO   -> on_stop, destino MAPO
 *   cuando termine avisame                   -> on_stop, destino la coordinadora (coordinatorOf)
 *   cada vez que termine pasale a Teorema, hasta 5 veces -> on_stop repeat
 *   ahora a Teorema                          -> now
 */
export type Parsed =
  | {
      kind: "at";
      at: Date;
      text: string;
      to: Session | null;
      toSelf: boolean;
      toMe: boolean;
      /** periodica: segundos entre disparos (>= 60); null = una sola vez */
      every: number | null;
      /** tope de disparos (1..50); sin periodicidad es 1 */
      maxFires: number;
      summary: string;
    }
  | { kind: "on_stop"; to: Session | null; toMe: boolean; repeat: boolean; maxFires: number; summary: string }
  | { kind: "now"; to: Session | null; toMe: boolean; summary: string }
  | { kind: "none"; summary: string };

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** La coordinadora de un repo: la sesion marcada `coordinator` (estrella en la tarjeta) del mismo
 *  repo; si no hay ninguna, la primera sesion de Claude del mismo repo. `exclude` es la sesion que
 *  pregunta (no se coordina a si misma). Lo usan el checkbox "avisarme" del SendBox, el `me` de
 *  Conectar y el "avisame" del parser: una sola definicion. */
export function coordinatorOf(repo: string, sessions: Session[], exclude?: string): Session | undefined {
  const same = sessions.filter((o) => o.repo === repo && o.session_id !== exclude);
  return same.find((o) => o.coordinator) ?? same.find((o) => o.agent === "claude");
}

/** Ajustes del resumen: `current` es como se llama el destino que ya tiene el dialogo (para las frases
 *  que no nombran destino), `name` como se muestra una sesion (Forward pasa shortName; por defecto el repo). */
export interface ParseOpts {
  current?: string;
  name?: (s: Session) => string;
}

/** HH:MM en hora local, con ceros a la izquierda. */
export const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/** "30 min", "2 h", "1 día": para resumenes y toasts. */
export function fmtEvery(sec: number): string {
  if (sec % 86400 === 0) return sec === 86400 ? "día" : `${sec / 86400} días`;
  if (sec % 3600 === 0) return `${sec / 3600} h`;
  return `${Math.round(sec / 60)} min`;
}

/** La proxima vez que sean las h:m: hoy si todavia no paso, si no manana. */
export function nextAt(h: number, m: number): Date {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d;
}

/** Cuantos disparos entran entre `at` y la proxima vez que sean las h:m, inclusive el primero. */
export function firesUntil(at: Date, every: number, h: number, m: number): number {
  const end = new Date(at);
  end.setHours(h, m, 0, 0);
  if (end.getTime() < at.getTime()) end.setDate(end.getDate() + 1);
  return Math.min(50, Math.max(1, Math.floor((end.getTime() - at.getTime()) / (every * 1000)) + 1));
}

const ME_RE = /(^|\s)(avisame|avisarme|decime|avisa|avisar)(?=\s|$)/i;

function findTarget(phrase: string, from: Session, others: Session[]): { to: Session | null; toSelf: boolean; toMe: boolean; rest: string } {
  const n = norm(phrase);
  // \b en JS es ASCII: "acá" no cierra palabra, por eso los limites se escriben a mano (\s|$)
  if (/(^|\s)(a esta( misma)?( sesion)?|a si misma|aca|a mi misma)(\s|$)/.test(n)) {
    return { to: from, toSelf: true, toMe: false, rest: phrase.replace(/(^|\s)(a esta( misma)?( sesi[oó]n)?|a s[ií] misma|ac[aá]|a m[ií] misma)(?=\s|$)/i, " ") };
  }
  // nombre de repo o de titulo despues de "a " / "para " / "hacia ": todos los candidatos, no solo
  // el primero ("a las 16 mandale el texto para MAPO" tiene "a las" antes de "para MAPO")
  for (const m of n.matchAll(/(?:^|\s)(?:a|para|hacia|pasale a|mandale a|decile a)\s+([a-z0-9_.-]+)/g)) {
    const word = m[1];
    if (/^(las?|los?|una?|esta|esa|el)$/.test(word)) continue;
    const hit = others.find((o) => norm(o.repo) === word) || others.find((o) => norm(o.repo).includes(word) || norm(o.title || "").includes(word));
    if (hit) return { to: hit, toSelf: false, toMe: false, rest: phrase.replace(new RegExp(`(^|\\s)(?:a|para|hacia|pasale a|mandale a|decile a)\\s+${word}`, "i"), " ") };
  }
  // "avisame" / "decime": la coordinadora del repo del origen (coordinatorOf); si no hay, queda sin destino
  if (ME_RE.test(norm(phrase))) return { to: coordinatorOf(from.repo, others, from.session_id) ?? null, toSelf: false, toMe: true, rest: phrase.replace(ME_RE, " ") };
  return { to: null, toSelf: false, toMe: false, rest: phrase };
}

/** Periodicidad: "cada 30 min", "cada 2 horas", "cada hora", "cada media hora", "cada día",
 *  "todos los días". Sobre minusculas con acentos (el texto conserva "continuá"). */
function parseEvery(n: string): { every: number; rest: string } | null {
  let m = n.match(/\b(cada|todos los|todas las)\s+(\d+)\s*(min(?:utos?)?|m|h(?:oras?)?|d[ií]as?)\b/);
  if (m) {
    const qty = Number(m[2]);
    const u = m[3];
    const sec = u.startsWith("d") ? qty * 86400 : u.startsWith("h") ? qty * 3600 : qty * 60;
    return { every: Math.max(60, sec), rest: n.replace(m[0], " ") };
  }
  m = n.match(/\b(cada|todos los|todas las)\s+(media\s+hora|hora|d[ií]as?)\b/);
  if (m) return { every: m[2].startsWith("media") ? 1800 : m[2] === "hora" ? 3600 : 86400, rest: n.replace(m[0], " ") };
  return null;
}

/** Tope: "hasta N veces" o "hasta las HH:MM" (este se convierte a cantidad despues, con `at` y `every`). */
function parseLimit(n: string): { count?: number; untilH?: number; untilM?: number; rest: string } | null {
  let m = n.match(/\bhasta\s+(\d+)\s*(veces|vez)\b/);
  if (m) return { count: Math.min(50, Math.max(1, Number(m[1]))), rest: n.replace(m[0], " ") };
  m = n.match(/\bhasta\s+las?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|hs|h)?\b/);
  if (m) {
    let h = Number(m[1]);
    const min = Number(m[2] || 0);
    if (m[3] === "pm" && h < 12) h += 12;
    if (m[3] === "am" && h === 12) h = 0;
    if (h > 23 || min > 59) return null;
    return { untilH: h, untilM: min, rest: n.replace(m[0], " ") };
  }
  return null;
}

function parseTime(n: string): { at: Date; rest: string } | null {
  // en 30 minutos / en 2 horas
  let m = n.match(/\ben\s+(\d+)\s*(min(?:utos?)?|m|h(?:oras?)?)\b/);
  if (m) {
    const qty = Number(m[1]);
    const ms = m[2].startsWith("h") ? qty * 3600e3 : qty * 60e3;
    return { at: new Date(Date.now() + ms), rest: n.replace(m[0], " ") };
  }
  // a las 16:00 / a las 4 pm / a las 4 / 16:30 / 4pm
  m = n.match(/\b(?:a\s+las?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|hs|h)?\b/);
  if (m && (m[2] || m[3] || /\ba\s+las?\s+/.test(n))) {
    let h = Number(m[1]);
    const min = Number(m[2] || 0);
    if (m[3] === "pm" && h < 12) h += 12;
    if (m[3] === "am" && h === 12) h = 0;
    if (h > 23 || min > 59) return null;
    return { at: nextAt(h, min), rest: n.replace(m[0], " ") };
  }
  return null;
}

function quoted(phrase: string): string | null {
  const m = phrase.match(/["“']([^"”']+)["”']/);
  return m ? m[1].trim() : null;
}

function cleanText(rest: string): string {
  return rest
    .replace(/\b(manda(le|me)?|mand[aá](le|me)?|envi[aá](le)?|decile|pasale|escribile|avisame|avisarme|decime|que diga|el texto|un mensaje|mensaje|con)\b/gi, " ")
    .replace(/\s+/g, " ")
    .replace(/^[\s,:.-]+|[\s,:.-]+$/g, "")
    .trim();
}

export function parseConnection(phrase: string, from: Session, others: Session[], opts: ParseOpts = {}): Parsed {
  const raw = phrase.trim();
  if (!raw) return { kind: "none", summary: "" };
  const n = norm(raw);
  const target = findTarget(raw, from, others);
  const name = (s: Session | null) => (s ? (opts.name ?? ((x: Session) => x.repo))(s) : null);

  if (/\b(cuando|al|cada vez que)\b.*\b(termin|acab|cierr)/.test(n) || /\b(al terminar|al acabar)\b/.test(n)) {
    const repeat = /\bcada vez\b|\bsiempre\b/.test(n);
    const mm = n.match(/\bhasta\s+(\d+)\s*(veces)?/);
    const maxFires = mm ? Math.min(50, Math.max(1, Number(mm[1]))) : repeat ? 5 : 1;
    const to = target.to && !target.toSelf ? target.to : null;
    const dest = to ? name(to) : target.toMe ? "la coordinadora (no hay ninguna viva)" : null;
    return {
      kind: "on_stop", to, toMe: target.toMe, repeat, maxFires,
      summary: dest
        ? `Cuando ${from.repo} termine → su respuesta a ${dest}${repeat ? ` (hasta ${maxFires} veces)` : " (una vez)"}`
        : "¿A qué sesión? Agregá “a <nombre>” al final",
    };
  }

  // la hora se detecta sobre minusculas sin quitar acentos (el texto conserva "continuá") y sin el
  // texto entrecomillado, para que un "PR 42" adentro no se tome como hora. La periodicidad y el
  // tope se sacan antes: "cada 2 h" o "hasta las 18:00" no son la hora del primer disparo
  const q = quoted(raw);
  let low = (q ? target.rest.replace(q, " ") : target.rest).toLowerCase();
  const ev = parseEvery(low);
  if (ev) low = ev.rest;
  const lim = parseLimit(low);
  if (lim) low = lim.rest;
  const t = parseTime(low);
  if (t || ev) {
    const every = ev ? ev.every : null;
    // periodica sin hora: la primera en un intervalo
    const at = t ? t.at : new Date(Date.now() + (every ?? 0) * 1000);
    const rest = t ? t.rest : low;
    const text = q || cleanText(rest.replace(/\b(a las?|hs|pm|am|desde|y despues|después|luego)\b/g, " ")) || "Continuá";
    let maxFires = 1;
    if (every) {
      if (lim?.count) maxFires = lim.count;
      else if (lim?.untilH !== undefined) maxFires = firesUntil(at, every, lim.untilH, lim.untilM ?? 0);
      else maxFires = 5;
    }
    // sin destino explicito, el dialogo conserva el que ya tenia (la tarjeta donde se solto): opts.current
    const dest = target.toSelf
      ? "a esta sesión"
      : target.to
        ? `a ${name(target.to)}`
        : target.toMe
          ? "a la coordinadora (no hay ninguna viva)"
          : opts.current
            ? `a ${opts.current}`
            : "al destino elegido";
    const summary = every
      ? `Cada ${fmtEvery(every)} desde las ${hhmm(at)} → "${text}" ${dest} (hasta ${maxFires} ${maxFires === 1 ? "vez" : "veces"})`
      : `A las ${hhmm(at)} → "${text}" ${dest}`;
    return { kind: "at", at, text, to: target.to, toSelf: target.toSelf, toMe: target.toMe, every, maxFires, summary };
  }

  if (/\b(ahora|ya)\b/.test(n) || target.to || target.toMe) {
    const to = target.to && !target.toSelf ? target.to : null;
    const dest = to ? name(to) : target.toMe ? "la coordinadora (no hay ninguna viva)" : null;
    return { kind: "now", to, toMe: target.toMe, summary: dest ? `Ahora → última respuesta de ${from.repo} a ${dest}` : "¿A qué sesión? Agregá “a <nombre>”" };
  }
  return {
    kind: "none",
    summary: "No lo entendí (los controles de abajo quedan como estaban). Probá: “continuá a las 16:00”, “cada 30 min seguí”, “cuando termine mandale a MAPO”",
  };
}
