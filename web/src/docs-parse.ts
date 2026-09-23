/** El markdown de un documento partido en bloques, uno por encabezado, para la referencia de /docs.
 *  Puro y sin dependencias: se testea con Node igual que la geometria (docs-parse.test.ts). */

export interface Block {
  /** 1 a 4: el nivel del encabezado. El bloque 0 puede ser nivel 1 (el titulo del documento) */
  level: number;
  title: string;
  /** ancla estilo GitHub, unica en el documento: la que usan los links `#...` del propio markdown */
  slug: string;
  /** el cuerpo sin la linea del encabezado */
  body: string;
  /** indice del bloque de nivel 1 o 2 al que pertenece: la "seccion" que se muestra entera */
  section: number;
}

/** Ancla como la arma GitHub: minusculas, se va la puntuacion salvo guiones y guion bajo, los
 *  espacios pasan a guion. Los acentos se quedan (GitHub tambien los deja) */
export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .trim()
    .replace(/\s/g, "-");
}

/** Parte en bloques por encabezado `#` a `####`, sin confundir un `#` de adentro de un bloque de
 *  codigo con un encabezado. Lo que viene antes del primer encabezado va a un bloque sin titulo */
export function parseDoc(md: string): Block[] {
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  const seen = new Map<string, number>();
  let fence: string | null = null;
  let cur: Block = { level: 1, title: "", slug: "", body: "", section: 0 };
  let buf: string[] = [];
  const flush = () => {
    cur.body = buf.join("\n").trim();
    if (cur.title || cur.body) out.push(cur);
    buf = [];
  };
  for (const line of lines) {
    const f = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (f) {
      if (!fence) fence = f[1][0];
      else if (f[1][0] === fence) fence = null;
    }
    const h = !fence && !f ? line.match(/^(#{1,4})\s+(.+?)\s*#*\s*$/) : null;
    if (!h) {
      buf.push(line);
      continue;
    }
    flush();
    const title = h[2];
    const base = slugify(title);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    const level = h[1].length;
    const idx = out.length; // el lugar que va a ocupar: flush ya guardo el anterior
    const section = level <= 2 || !out.length ? idx : out[out.length - 1].section;
    cur = { level, title, slug: n ? `${base}-${n}` : base, body: "", section };
  }
  flush();
  return out;
}

/** minusculas y sin acentos, para comparar lo que se busca contra el texto */
export const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Los terminos de una busqueda, ya plegados. Vacio si no hay nada que buscar */
export const terms = (q: string) => fold(q).split(/\s+/).filter((t) => t.length > 0);

/** Regex que encuentra cualquiera de los terminos en el texto original, con o sin acento: "diseno"
 *  encuentra "diseño" y "pestana" encuentra "pestaña". Para resaltar, no para filtrar */
export function markRe(ts: string[]): RegExp | null {
  if (!ts.length) return null;
  const cls: Record<string, string> = { a: "aáàäâ", e: "eéèëê", i: "iíìïî", o: "oóòöô", u: "uúùüû", n: "nñ", c: "cç" };
  const one = (t: string) =>
    [...t].map((ch) => (cls[ch] ? `[${cls[ch]}]` : ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))).join("");
  return new RegExp(`(${ts.map(one).join("|")})`, "giu");
}

/** Cuantas veces aparecen los terminos en el bloque, o 0 si falta alguno (se exigen todos, en el
 *  titulo o en el cuerpo, y cada uno puede estar en cualquier parte) */
export function hits(b: Block, ts: string[]): number {
  if (!ts.length) return 0;
  const txt = fold(`${b.title}\n${b.body}`);
  let n = 0;
  for (const t of ts) {
    let k = 0;
    for (let i = txt.indexOf(t); i >= 0; i = txt.indexOf(t, i + t.length)) k++;
    if (!k) return 0;
    n += k;
  }
  return n;
}
