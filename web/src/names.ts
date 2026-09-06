import { ago } from "./api";
import { hhmm } from "./nl";
import { periodLabel, periodicCount } from "./arrows-geometry";
import type { Link, Rule, Session } from "./types";

/** Nombres y textos que comparten la tarjeta, el panel, las flechas y Conectar: como se llama una
 *  sesion, como se lee una regla, como se pliega un pedido. Sin React ni DOM. `periodLabel` vive en
 *  arrows-geometry (modulo puro con tests) y se reexporta desde aca. */
export { periodLabel };

/** Nombre corto de una sesion: "repo · titulo" (titulo cortado a 24) o "repo · id" si no tiene. */
export function shortName(o: Session | undefined, fallback = "otra sesión"): string {
  if (!o) return fallback;
  const t = (o.title || "").trim();
  if (!t) return `${o.repo} · ${o.session_id.slice(0, 8)}`;
  return `${o.repo} · ${t.length > 24 ? t.slice(0, 23).trimEnd() + "…" : t}`;
}

/** viva, con terminal propia y no huerfana: se le puede escribir */
export const canWrite = (s: Session): boolean => !!s.alive && !s.orphan && !s.no_console;

/** libre: con consola y sin ningun pedido ni respuesta todavia (sesion recien abierta) */
export const isFree = (s: Session): boolean => canWrite(s) && !(s.last_prompt || "").trim() && !(s.last_reply || "").trim();

/** Hora de un instante ISO. Corto: "22:19" si es hoy, "vie 11/9 22:19" si es otro dia (chips).
 *  Largo: "a las 22:19" / "el vie 11/9 a las 22:19" (fila de programadas del panel). Un
 *  "Continuar" programado para dentro de cinco dias no puede leerse como si fuera esta noche. */
export function whenLabel(iso: string, long = false, now = new Date()): string {
  const d = new Date(iso);
  const t = hhmm(d);
  if (d.toDateString() === now.toDateString()) return long ? `a las ${t}` : t;
  const day = `${d.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "")} ${d.getDate()}/${d.getMonth() + 1}`;
  return long ? `el ${day} a las ${t}` : `${day} ${t}`;
}

/** minuto (ms truncados) en que dispara una regla "at"; null si no tiene hora */
const minuteOf = (r: Rule): number | null => (r.kind === "at" && r.at ? Math.floor(new Date(r.at).getTime() / 60_000) : null);

/** Reglas "at" que le escriben a esta sesion y caen en el mismo minuto que otra: dos inyecciones
 *  a la misma consola en el mismo minuto (el server no lo impide todavia; la tarjeta lo marca). */
export function clashingAt(rules: Rule[], sid: string): Set<string> {
  const byMinute = new Map<number, string[]>();
  for (const r of rules) {
    if (!r.enabled || r.to !== sid) continue;
    const m = minuteOf(r);
    if (m === null) continue;
    const arr = byMinute.get(m);
    if (arr) arr.push(r.id);
    else byMinute.set(m, [r.id]);
  }
  const out = new Set<string>();
  for (const ids of byMinute.values()) if (ids.length > 1) ids.forEach((id) => out.add(id));
  return out;
}

/** Etiqueta del chip de una regla vista desde la tarjeta `sid`. Una "at" periodica dice el periodo,
 *  la proxima hora si esta en el futuro y cuantas veces fue: `↻ cada 30 min · próx. 09:30 → "Continuá" (1/5)`. */
export function ruleLabel(r: Rule, sid: string, sessions: Record<string, Session>, now = Date.now()): string {
  const other = (id: string | null) => shortName(id ? sessions[id] : undefined, "?");
  if (r.kind === "at") {
    let head: string;
    let tail = "";
    if (r.every_s) {
      const next = r.at && new Date(r.at).getTime() > now ? ` · próx. ${whenLabel(r.at)}` : "";
      head = `↻ ${periodLabel(r.every_s)}${next}`;
      tail = ` ${periodicCount(r.fired, r.max_fires, null)}`;
    } else {
      head = `⏰ ${r.at ? whenLabel(r.at) : "?"}`;
    }
    if (r.to === sid) return r.from && r.from !== sid ? `${head} → "${r.text}"${tail} (desde ${other(r.from)})` : `${head} → "${r.text}"${tail}`;
    return `${head} → "${r.text}"${tail} a ${other(r.to)}`;
  }
  const count = r.repeat ? ` (${r.fired}/${r.max_fires})` : "";
  return r.from === sid ? `⏹ al terminar → ${other(r.to)}${count}` : `⏹ recibe de ${other(r.from)} al terminar${count}`;
}

/** Conexiones de la tarjeta en un contador chico, para el modo compacto: `⏰1 ⏹3`, con la lista
 *  completa en el `title`. null si no hay ninguna. */
export function ruleSummary(rules: Rule[], sid: string, sessions: Record<string, Session>): { text: string; title: string } | null {
  if (!rules.length) return null;
  const n = new Map<string, number>();
  for (const r of rules) {
    const g = r.kind === "at" ? (r.every_s ? "↻" : "⏰") : "⏹";
    n.set(g, (n.get(g) ?? 0) + 1);
  }
  return {
    text: ["⏰", "↻", "⏹"].filter((g) => n.has(g)).map((g) => `${g}${n.get(g)}`).join(" "),
    title: rules.map((r) => ruleLabel(r, sid, sessions)).join("\n"),
  };
}

const cap = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t);

/** La misma conexion que el chip, pero en una frase: es lo que muestra la tarjeta seleccionada,
 *  donde hay lugar para leerla. "Al terminar le manda su respuesta a lienzo · Coordinadora.
 *  Van 3 de 20." */
export function ruleSentence(r: Rule, sid: string, sessions: Record<string, Session>): string {
  const other = (id: string | null) => shortName(id ? sessions[id] : undefined, "otra sesión");
  if (r.kind === "on_stop") {
    const count = r.max_fires > 1 ? ` Van ${r.fired} de ${r.max_fires}.` : "";
    return r.from === sid
      ? `Al terminar le manda su respuesta a ${other(r.to)}.${count}`
      : `Cuando ${other(r.from)} termine, le llega su respuesta.${count}`;
  }
  const what = r.to === sid ? "se le escribe" : `se le escribe a ${other(r.to)}`;
  // quien la dejo armada: el server solo (limite de uso) u otra sesion
  const by = r.auto ? " La programó el lienzo solo." : r.from && r.from !== sid ? ` La programó ${other(r.from)}.` : "";
  const quoted = `«${r.text}»`;
  if (r.every_s) {
    const next = r.at ? ` La próxima, ${whenLabel(r.at, true)}.` : "";
    return `${cap(periodLabel(r.every_s))} ${what} ${quoted}. Van ${r.fired} de ${r.max_fires}.${next}${by}`;
  }
  return r.at ? `${cap(whenLabel(r.at, true))} ${what} ${quoted}.${by}` : `Sin hora fijada, ${what} ${quoted}.${by}`;
}

/** Lo que ya recibio esta sesion, agrupado por remitente y en una frase por cada uno:
 *  "Recibió 4 mensajes de lienzo · Encargo R1. El último, hace 22 min." */
export function linkSentences(links: Link[], sid: string, sessions: Record<string, Session>): string[] {
  const groups = new Map<string, { from: string; n: number; last: string; native: boolean }>();
  for (const l of links) {
    if (l.to !== sid || !l.from) continue;
    const native = l.kind === "native";
    const k = `${native ? "n" : "s"}|${l.from}`;
    const g = groups.get(k);
    if (!g) groups.set(k, { from: l.from, n: 1, last: l.ts, native });
    else {
      g.n++;
      if (l.ts > g.last) g.last = l.ts;
    }
  }
  return [...groups.values()].map((g) => {
    const name = shortName(sessions[g.from]);
    if (g.native) return `Tiene un canal nativo con ${name}, abierto hace ${ago(g.last)}.`;
    return g.n === 1 ? `Recibió un mensaje de ${name}, hace ${ago(g.last)}.` : `Recibió ${g.n} mensajes de ${name}. El último, hace ${ago(g.last)}.`;
  });
}

export interface RuleGroup {
  label: string;
  kind: Rule["kind"];
  ids: string[];
  /** alguna de sus reglas comparte minuto con otra de la tarjeta */
  clash: boolean;
}

/** Reglas con la misma etiqueta agrupadas (×N), como maximo `max` grupos; el resto se cuenta. */
export function groupRules(rules: Rule[], sid: string, sessions: Record<string, Session>, max = 3): { shown: RuleGroup[]; hidden: number } {
  const clashing = clashingAt(rules, sid);
  const groups = new Map<string, RuleGroup>();
  for (const r of rules) {
    const label = ruleLabel(r, sid, sessions);
    const g = groups.get(label);
    if (g) {
      g.ids.push(r.id);
      g.clash ||= clashing.has(r.id);
    } else groups.set(label, { label, kind: r.kind, ids: [r.id], clash: clashing.has(r.id) });
  }
  const all = [...groups.values()];
  return { shown: all.slice(0, max), hidden: all.slice(max).reduce((n, g) => n + g.ids.length, 0) };
}

/** Fila de programadas del panel: una regla "at" habilitada hacia esa sesion, en una linea.
 *  `auto` cuando la creo el server por un limite de uso. */
export function schedLabel(r: Pick<Rule, "text" | "at" | "every_s" | "fired" | "max_fires" | "auto">, now = new Date()): { text: string; auto: boolean } {
  const auto = !!r.auto;
  if (r.every_s) {
    const next = r.at ? ` · próx. ${whenLabel(r.at, true, now).replace(/^a las /, "").replace(/^el /, "")}` : "";
    return { text: `↻ ${r.text} ${periodLabel(r.every_s)}${next} (${r.fired}/${r.max_fires})`, auto };
  }
  return { text: `⏰ ${r.text} ${r.at ? whenLabel(r.at, true, now) : "sin hora"}`, auto };
}

/** Markdown a texto plano legible para la tarjeta (que no renderiza markdown, por peso y altura):
 *  saca `**`, `__`, `` ` `` y cercos de codigo, `#` de encabezados, marcadores de lista al inicio
 *  de linea (`- `, `* `, `1. `), citas `>`, reglas `---`, deja el texto de los links
 *  `[texto](url)`, y colapsa lineas en blanco repetidas. La vista Conversacion del panel no la
 *  usa: ahi si se renderiza con react-markdown. */
export function plainText(md: string): string {
  let t = (md || "").replace(/\r\n?/g, "\n");
  t = t.replace(/^\s*```[^\n]*$/gm, ""); // cercos de codigo (la linea entera)
  t = t.replace(/^\s*[-*_]{3,}\s*$/gm, ""); // reglas horizontales
  t = t.replace(/^#{1,6}\s+/gm, ""); // encabezados
  t = t.replace(/^(\s*)(?:[-*+]|\d+[.)])\s+/gm, "$1"); // marcadores de lista, con su sangria
  t = t.replace(/^\s*>\s?/gm, ""); // citas
  t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1"); // links e imagenes: queda el texto
  t = t.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2"); // negrita
  t = t.replace(/`([^`\n]*)`/g, "$1"); // codigo inline
  t = t.replace(/[ \t]+$/gm, "").replace(/\n{3,}/g, "\n\n"); // lineas en blanco repetidas
  return t.trim();
}

const PROMPT_CHARS = 90;

/** Primera linea del pedido, o los primeros 90 caracteres; `cut` dice si quedo algo afuera. */
export function foldPrompt(p: string): { head: string; cut: boolean } {
  const text = (p || "").trim();
  const nl = text.indexOf("\n");
  let head = nl >= 0 ? text.slice(0, nl) : text;
  let cut = nl >= 0;
  if (head.length > PROMPT_CHARS) {
    head = head.slice(0, PROMPT_CHARS - 1) + "…";
    cut = true;
  }
  return { head, cut };
}

/** Primera oracion (hasta el primer . ! ? seguido de espacio o fin), tope de 90 caracteres. */
export function foldSentence(text: string): { head: string; cut: boolean } {
  const t = (text || "").trim();
  const m = t.match(/^(.*?[.!?])(?:\s|$)/s);
  let head = m ? m[1] : t.split("\n")[0];
  if (head.length > PROMPT_CHARS) head = head.slice(0, PROMPT_CHARS - 1) + "…";
  return { head, cut: head.length < t.length };
}

/** El titulo salio del pedido (el server lo marca con title_source, o coincide con su primera
 *  linea, aun cortada): la linea "› pedido" diria lo mismo. */
export function titleIsPrompt(s: Session): boolean {
  const title = (s.title || "").trim();
  if (!title) return false;
  if (s.title_source === "prompt") return true;
  const first = (s.last_prompt || "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  if (!first) return false;
  const t = title.replace(/…$/, "").replace(/\.\.\.$/, "").trimEnd();
  return first === title || (t.length >= 8 && first.startsWith(t));
}
