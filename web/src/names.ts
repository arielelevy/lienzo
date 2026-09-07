import { useEffect, useRef, useState } from "react";
import { ago } from "./api";
import { hhmm } from "./nl";
import { periodLabel } from "./arrows-geometry";
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

/** Texto sobre el que busca el filtro del header. El agente va primero porque su nombre ("codex",
 *  "claude") es lo primero que uno escribe, y hasta ahora sólo se filtraba por los chips; despues
 *  van repo, rama, titulo y ultimo pedido. El `cwd` queda afuera a proposito: casi toda ruta de
 *  una sesion de Claude lleva `.claude` adentro y "claude" pasaria a matchear cualquier cosa. */
export function searchText(s: Session): string {
  return [s.agent, s.repo, s.branch ?? "", s.title ?? "", s.last_prompt ?? ""].join(" ");
}

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

const FENCE_RE = /^[ \t]*(`{3,}|~{3,})\s*(\S*)/;

/** Un bloque cercado de varias lineas volcado como prosa es lo que peor se lee en la tarjeta: los
 *  espacios se colapsan y una tabla alineada a mano queda en palabras sueltas. Medido en el informe
 *  de Z4: cinco lineas de columnas que en la tarjeta se leen "ANTES DESPUÉS" y nada mas. Se
 *  reemplaza por una linea que dice que es. El de una sola linea se deja tal cual, que casi siempre
 *  es un comando o un valor y se entiende (9 de 34 bloques reales). Corre antes que el resto, con
 *  los cercos todavia puestos, y aguanta el bloque sin cerrar: `last_reply` llega cortado a 600. */
function foldFenced(t: string): string {
  const lines = t.split("\n");
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const open = lines[i].match(FENCE_RE);
    if (!open) {
      out.push(lines[i]);
      continue;
    }
    const ch = open[1][0];
    let j = i + 1;
    for (; j < lines.length; j++) {
      const s = lines[j].trim();
      if (s.length >= 3 && s === ch.repeat(s.length)) break; // el cerco de cierre
    }
    const body = lines.slice(i + 1, j).filter((l) => l.trim());
    const lang = /^[\w+#-]+$/.test(open[2]) ? ` ${open[2]}` : "";
    out.push(body.length === 1 ? body[0].trim() : body.length ? `código${lang}, ${body.length} líneas` : "");
    i = j; // la linea de cierre tambien se consume
  }
  return out.join("\n");
}

const TABLE_COLS = 60;
const isTableSep = (l: string) => /^[\s|:-]+$/.test(l) && l.includes("-") && l.includes("|");

/** Una tabla de markdown en la tarjeta queda como los encabezados sueltos, sin columnas ni datos:
 *  peor que no mostrarla. Se reemplaza por una linea que dice que es y de que: "tabla de 5 filas:
 *  ventana · ancho". Los encabezados se ganan el lugar porque dicen de que habla la tabla (de 18
 *  tablas reales de ~/.lienzo/adjuntos, 17 los tienen); cuando la primera columna es la de las
 *  etiquetas y viene vacia, se saltea. Corre al final, con el markdown de las celdas ya limpio. */
function foldTables(t: string): string {
  const lines = t.split("\n");
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].includes("|") || !isTableSep(lines[i + 1] ?? "")) {
      out.push(lines[i]);
      continue;
    }
    let j = i + 2;
    while (j < lines.length && lines[j].includes("|") && lines[j].trim()) j++;
    const n = j - i - 2;
    const que = `tabla de ${n} fila${n === 1 ? "" : "s"}`;
    const cols = lines[i]
      .split("|")
      .map((c) => c.trim())
      .filter(Boolean)
      .join(" · ");
    out.push(cols ? `${que}: ${cols.length > TABLE_COLS ? cols.slice(0, TABLE_COLS - 1) + "…" : cols}` : que);
    i = j - 1;
  }
  return out.join("\n");
}

/** Markdown a texto plano legible para la tarjeta (que no renderiza markdown, por peso y altura):
 *  resume tablas y bloques de codigo de varias lineas en una linea que dice que son, saca `**`,
 *  `__`, `*`, `_`, `` ` ``, `#` de encabezados, marcadores de lista al inicio de linea (`- `, `* `,
 *  `1. `), citas `>` (todos los niveles), reglas `---`, deja el texto de los links `[texto](url)`, y
 *  colapsa lineas en blanco repetidas. Los tres usos son la tarjeta (pedido, respuesta y el tooltip
 *  del chip de informe recibido), donde hay dos o tres lineas: por eso resume en vez de aplanar, y
 *  por eso no necesita parametro. La vista Conversacion del panel no la usa: ahi se renderiza con
 *  react-markdown y la tabla se ve entera. */
export function plainText(md: string): string {
  let t = (md || "").replace(/\r\n?/g, "\n");
  t = foldFenced(t); // primero: necesita los cercos, y se come las tablas que vengan adentro
  t = t.replace(/^\s*[-*_]{3,}\s*$/gm, ""); // reglas horizontales
  t = t.replace(/^#{1,6}\s+/gm, ""); // encabezados
  t = t.replace(/^(\s*)(?:[-*+]|\d+[.)])\s+/gm, "$1"); // marcadores de lista, con su sangria
  t = t.replace(/^\s*(?:>\s?)+/gm, ""); // citas, incluidas las anidadas
  t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1"); // links e imagenes: queda el texto
  t = t.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2"); // negrita
  t = t.replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?![*\w])/g, "$1$2"); // italica con *
  t = t.replace(/(^|[^_\w])_(?=\S)([^_\n]*?\S)_(?![_\w])/g, "$1$2"); // italica con _, sin tocar snake_case
  t = t.replace(/`([^`\n]*)`/g, "$1"); // codigo inline
  t = foldTables(t); // al final: las celdas ya vienen sin markdown
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

/** Por qué una sesión figura "corriendo" pero no está trabajando, o null si sí lo está. Dos casos
 *  medidos: se quedó sin cupo (el turno no cierra nunca, el hook Stop no llega y la tarjeta queda
 *  verde para siempre) y hace rato que no se mueve. El segundo puede ser una tarea larga y
 *  legítima, por eso el texto sólo dice lo que se midió: cuánto hace que no pasa nada. */
export const STALL_MIN = 15;

export function stalledReason(s: Session, now = Date.now()): string | null {
  if (s.state !== "corriendo") return null;
  const until = s.limit_until ? new Date(s.limit_until).getTime() : 0;
  if (until > now) return `sin cupo hasta ${whenLabel(s.limit_until!, true, new Date(now))}`;
  const since = s.state_since ? now - new Date(s.state_since).getTime() : 0;
  return since > STALL_MIN * 60_000 ? "sin actividad" : null;
}

/** Botón que copia y avisa solo, cambiando su texto dos segundos: lo usan el Copiar de un turno y
 *  el de la URL del túnel, que no tienen el toast global a mano. Devuelve el estado y la acción. */
export function useCopyState(): { state: "idle" | "ok" | "err"; copy: (text: string) => Promise<void> } {
  const [state, setState] = useState<"idle" | "ok" | "err">("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setState("ok");
    } catch {
      setState("err");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 2000);
  };
  return { state, copy };
}

/** El texto del botón según el estado, para que los dos digan lo mismo. */
export const copyLabel = (state: "idle" | "ok" | "err", idle = "Copiar") =>
  state === "ok" ? "Copiado ✓" : state === "err" ? "No se pudo" : idle;
