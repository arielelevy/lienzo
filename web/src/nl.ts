import type { Session } from "./types";

/** Interpretar una frase corta como conexion. Sin modelo: patrones de castellano rioplatense.
 *
 *   mandá "continuá" a las 16:00            -> at, texto continuá, a esta sesion
 *   a las 4pm continuá                       -> at
 *   en 30 minutos decile seguí              -> at (ahora + 30 min)
 *   cuando termine mandale la respuesta a MAPO   -> on_stop, destino MAPO
 *   cada vez que termine pasale a Teorema, hasta 5 veces -> on_stop repeat
 *   ahora a Teorema                          -> now
 */
export type Parsed =
  | { kind: "at"; at: Date; text: string; to: Session | null; toSelf: boolean; summary: string }
  | { kind: "on_stop"; to: Session | null; repeat: boolean; maxFires: number; summary: string }
  | { kind: "now"; to: Session | null; summary: string }
  | { kind: "none"; summary: string };

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function findTarget(phrase: string, from: Session, others: Session[]): { to: Session | null; toSelf: boolean; rest: string } {
  const n = norm(phrase);
  // \b en JS es ASCII: "acá" no cierra palabra, por eso los limites se escriben a mano (\s|$)
  if (/(^|\s)(a esta( misma)?( sesion)?|a si misma|aca|a mi misma)(\s|$)/.test(n)) {
    return { to: from, toSelf: true, rest: phrase.replace(/(^|\s)(a esta( misma)?( sesi[oó]n)?|a s[ií] misma|ac[aá]|a m[ií] misma)(?=\s|$)/i, " ") };
  }
  // nombre de repo o de titulo despues de "a " / "para " / "hacia ": todos los candidatos, no solo
  // el primero ("a las 16 mandale el texto para MAPO" tiene "a las" antes de "para MAPO")
  for (const m of n.matchAll(/(?:^|\s)(?:a|para|hacia|pasale a|mandale a|decile a)\s+([a-z0-9_.-]+)/g)) {
    const word = m[1];
    if (/^(las?|los?|una?|esta|esa|el)$/.test(word)) continue;
    const hit = others.find((o) => norm(o.repo) === word) || others.find((o) => norm(o.repo).includes(word) || norm(o.title || "").includes(word));
    if (hit) return { to: hit, toSelf: false, rest: phrase.replace(new RegExp(`(^|\\s)(?:a|para|hacia|pasale a|mandale a|decile a)\\s+${word}`, "i"), " ") };
  }
  return { to: null, toSelf: false, rest: phrase };
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
    const d = new Date();
    d.setHours(h, min, 0, 0);
    if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
    return { at: d, rest: n.replace(m[0], " ") };
  }
  return null;
}

function quoted(phrase: string): string | null {
  const m = phrase.match(/["“']([^"”']+)["”']/);
  return m ? m[1].trim() : null;
}

function cleanText(rest: string): string {
  return rest
    .replace(/\b(manda(le|me)?|mand[aá](le|me)?|envi[aá](le)?|decile|pasale|escribile|que diga|el texto|un mensaje|mensaje|con)\b/gi, " ")
    .replace(/\s+/g, " ")
    .replace(/^[\s,:.-]+|[\s,:.-]+$/g, "")
    .trim();
}

export function parseConnection(phrase: string, from: Session, others: Session[]): Parsed {
  const raw = phrase.trim();
  if (!raw) return { kind: "none", summary: "" };
  const n = norm(raw);
  const target = findTarget(raw, from, others);
  const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const name = (s: Session | null) => (s ? s.repo : null);

  if (/\b(cuando|al|cada vez que)\b.*\b(termin|acab|cierr)/.test(n) || /\b(al terminar|al acabar)\b/.test(n)) {
    const repeat = /\bcada vez\b|\bsiempre\b/.test(n);
    const mm = n.match(/\bhasta\s+(\d+)\s*(veces)?/);
    const maxFires = mm ? Math.min(50, Math.max(1, Number(mm[1]))) : repeat ? 5 : 1;
    const to = target.to && !target.toSelf ? target.to : null;
    return {
      kind: "on_stop", to, repeat, maxFires,
      summary: to
        ? `Cuando ${from.repo} termine → su respuesta a ${name(to)}${repeat ? ` (hasta ${maxFires} veces)` : " (una vez)"}`
        : "¿A qué sesión? Agregá “a <nombre>” al final",
    };
  }

  // la hora se detecta sobre minusculas sin quitar acentos (el texto conserva "continuá") y sin el
  // texto entrecomillado, para que un "PR 42" adentro no se tome como hora
  const q = quoted(raw);
  const t = parseTime((q ? target.rest.replace(q, " ") : target.rest).toLowerCase());
  if (t) {
    const text = q || cleanText(t.rest.replace(/\b(a las?|hs|pm|am)\b/g, " ")) || "Continuá";
    // sin destino explicito, el dialogo conserva el que ya tenia (la tarjeta donde se solto)
    const dest = target.toSelf ? "esta sesión" : target.to ? name(target.to) : "el destino elegido";
    return { kind: "at", at: t.at, text, to: target.to, toSelf: target.toSelf, summary: `A las ${hhmm(t.at)} → "${text}" a ${dest}` };
  }

  if (/\b(ahora|ya)\b/.test(n) || target.to) {
    const to = target.to && !target.toSelf ? target.to : null;
    return { kind: "now", to, summary: to ? `Ahora → última respuesta de ${from.repo} a ${name(to)}` : "¿A qué sesión? Agregá “a <nombre>”" };
  }
  return { kind: "none", summary: "No lo entendí. Probá: “continuá a las 16:00”, “en 30 min seguí”, “cuando termine mandale a MAPO”" };
}
