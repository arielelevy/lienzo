import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { hits, markRe, parseDoc, terms, type Block } from "../docs-parse";
import "../docs.css";

/** La referencia en /docs: el README y el documento de diseño leidos del server en cada visita (el
 *  server los lee del repo en cada pedido, asi que nunca quedan atras del archivo), partidos por
 *  encabezado. Sin busqueda muestra una seccion por vez con su indice; con busqueda, todos los
 *  bloques que tienen todos los terminos, con lo encontrado resaltado. La ruta va en el hash
 *  (`#readme/api`) para poder pasar el link de una seccion. */

const DOCS = [
  { key: "readme", file: "README.md", label: "README" },
  { key: "diseno", file: "DISENO.es.md", label: "Diseño" },
] as const;
type DocKey = (typeof DOCS)[number]["key"];
const REPO = "https://github.com/arielelevy/lienzo/blob/main/";

function readHash(): { doc: DocKey; slug: string } {
  const [d, ...rest] = decodeURIComponent(window.location.hash.slice(1)).split("/");
  const doc = DOCS.find((x) => x.key === d)?.key ?? "readme";
  return { doc, slug: rest.join("/") };
}

/** Plugin de rehype que envuelve en <mark> lo que encuentra `re` en los nodos de texto */
interface HNode {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HNode[];
}
function rehypeMark(re: RegExp | null) {
  return () => (tree: HNode) => {
    if (!re) return;
    const walk = (n: HNode) => {
      if (!n.children) return;
      n.children = n.children.flatMap((c) => {
        if (c.type !== "text" || !c.value) {
          walk(c);
          return [c];
        }
        return c.value.split(re).map((part, i) =>
          i % 2 ? { type: "element", tagName: "mark", properties: {}, children: [{ type: "text", value: part }] } : { type: "text", value: part },
        );
      });
    };
    walk(tree);
  };
}

export function Docs() {
  const [{ doc, slug }, setLoc] = useState(readHash);
  const [md, setMd] = useState<Record<string, string | Error>>({});
  const [q, setQ] = useState("");
  const [navOpen, setNavOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const file = DOCS.find((d) => d.key === doc)!.file;

  useEffect(() => {
    const on = () => setLoc(readHash());
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);

  useEffect(() => {
    if (md[file]) return;
    fetch(`/docs/${file}`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status === 401 ? "hace falta iniciar sesión en el tablero" : `error ${r.status}`))))
      .then((t) => setMd((m) => ({ ...m, [file]: t })))
      .catch((e: Error) => setMd((m) => ({ ...m, [file]: e })));
  }, [file, md]);

  // "/" busca y Esc limpia, como en el tablero
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== searchRef.current) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener("keydown", on);
    return () => document.removeEventListener("keydown", on);
  }, []);

  const src = md[file];
  const blocks = useMemo(() => (typeof src === "string" ? parseDoc(src) : []), [src]);
  const ts = useMemo(() => terms(q), [q]);
  const re = useMemo(() => markRe(ts), [ts]);
  const found = useMemo(() => (ts.length ? blocks.map((b, i) => ({ b, i, n: hits(b, ts) })).filter((x) => x.n > 0) : []), [blocks, ts]);
  const perSection = useMemo(() => {
    const m = new Map<number, number>();
    for (const f of found) m.set(f.b.section, (m.get(f.b.section) ?? 0) + f.n);
    return m;
  }, [found]);

  const target = blocks.findIndex((b) => b.slug === slug);
  const section = target >= 0 ? blocks[target].section : 0;
  const shown = blocks.map((b, i) => ({ b, i })).filter((x) => x.b.section === section);

  // al cambiar de seccion (o al llegar con un link), ir al bloque pedido
  useEffect(() => {
    if (ts.length) return;
    const el = slug ? document.getElementById(`b-${slug}`) : null;
    if (el) el.scrollIntoView({ block: "start" });
    else mainRef.current?.scrollTo({ top: 0 });
  }, [slug, section, ts.length, blocks]);

  const go = (d: DocKey, s: string) => {
    setQ("");
    setNavOpen(false);
    // pushState y no location.hash: igual queda en el historial para volver con Atras
    const h = `#${d}/${s}`;
    if (window.location.hash !== h) window.history.pushState(null, "", h);
    setLoc({ doc: d, slug: s });
  };

  const components: Components = {
    a: ({ href = "", children }) => {
      if (href.startsWith("#")) {
        return (
          <a href={`#${doc}/${href.slice(1)}`} onClick={() => setQ("")}>
            {children}
          </a>
        );
      }
      const other = DOCS.find((d) => href === d.file || href.startsWith(`${d.file}#`));
      if (other) return <a href={`#${other.key}/${href.split("#")[1] ?? ""}`}>{children}</a>;
      const ext = /^[a-z]+:/i.test(href) ? href : REPO + href.replace(/^\.\//, "");
      return (
        <a href={ext} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
    img: ({ src: s = "", alt }) => <img src={/^[a-z]+:|^\//i.test(s) ? s : `/${s.replace(/^\.\//, "")}`} alt={alt ?? ""} loading="lazy" />,
  };
  const plugins = [rehypeMark(re)];
  const Title = ({ b }: { b: Block }): ReactNode => (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={plugins} components={{ ...components, p: ({ children }) => <>{children}</> }}>
      {b.title}
    </ReactMarkdown>
  );
  const render = (b: Block, crumb?: string) => {
    const H = `h${Math.min(b.level + 1, 5)}` as "h2";
    return (
      <section key={b.slug || "intro"} id={`b-${b.slug}`} className="dblock">
        {crumb && <div className="crumb">{crumb}</div>}
        {b.title && (
          <H className="dh">
            <Title b={b} />
            <a className="anchor" href={`#${doc}/${b.slug}`} title="link a esta sección" aria-label="link a esta sección" onClick={() => setQ("")}>
              #
            </a>
          </H>
        )}
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={plugins} components={components}>
          {b.body}
        </ReactMarkdown>
      </section>
    );
  };

  // el indice llega hasta el nivel 3: los #### del diseño son demasiados para la barra
  const nav = blocks.map((b, i) => ({ b, i })).filter(({ b }) => b.title && b.level <= 3);

  return (
    <div className="docs">
      <header>
        <a className="home" href="/" title="volver al tablero">
          <h1>Lienzo</h1>
        </a>
        <nav className="dtabs" aria-label="documento">
          {DOCS.map((d) => (
            <button key={d.key} className={d.key === doc ? "on" : ""} aria-pressed={d.key === doc} onClick={() => go(d.key, "")}>
              {d.label}
            </button>
          ))}
        </nav>
        <div className="search" role="search">
          <input
            ref={searchRef}
            type="search"
            value={q}
            placeholder="buscar en la referencia  /"
            aria-label="buscar en el documento"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setQ("");
                (e.target as HTMLInputElement).blur();
              }
            }}
          />
        </div>
        {ts.length > 0 && (
          <span className="dim small count">
            {found.length ? `${found.length} ${found.length === 1 ? "bloque" : "bloques"}` : "nada"}
          </span>
        )}
        <span className="sp" />
        <button className="icon navtoggle" aria-expanded={navOpen} aria-label="índice" onClick={() => setNavOpen(!navOpen)}>
          ☰
        </button>
      </header>
      <div className="dbody">
        <aside className={`toc ${navOpen ? "open" : ""}`} aria-label="índice">
          {nav.map(({ b, i }) => {
            const n = b.level <= 2 ? perSection.get(i) : found.find((f) => f.i === i)?.n;
            const on = !ts.length && (b.level <= 2 ? i === section : i === target);
            const off = ts.length > 0 && !n;
            return (
              <a
                key={i}
                href={`#${doc}/${b.slug}`}
                className={`l${b.level} ${on ? "on" : ""} ${off ? "off" : ""}`}
                onClick={(e) => {
                  e.preventDefault();
                  go(doc, b.slug);
                }}
              >
                <span className="t">{b.title.replace(/`/g, "")}</span>
                {n ? <span className="n">{n}</span> : null}
              </a>
            );
          })}
        </aside>
        <main ref={mainRef}>
          {src instanceof Error && <p className="derr">No se pudo leer {file}: {src.message}.</p>}
          {src === undefined && <p className="dim">cargando {file}…</p>}
          {typeof src === "string" &&
            (ts.length ? (
              found.length ? (
                found.map(({ b }) => render(b, b.level > 2 ? blocks[b.section]?.title.replace(/`/g, "") : undefined))
              ) : (
                <p className="dim">Nada con “{q}” en {file}.</p>
              )
            ) : (
              shown.map(({ b }) => render(b))
            ))}
          {typeof src === "string" && !ts.length && <Pager blocks={blocks} section={section} go={(s) => go(doc, s)} />}
        </main>
      </div>
    </div>
  );
}

/** Anterior y siguiente al pie de cada seccion, para leer de corrido */
function Pager({ blocks, section, go }: { blocks: Block[]; section: number; go: (slug: string) => void }) {
  const heads = blocks.map((b, i) => ({ b, i })).filter(({ b, i }) => b.section === i);
  const k = heads.findIndex((h) => h.i === section);
  const prev = heads[k - 1];
  const next = heads[k + 1];
  return (
    <div className="pager">
      {prev ? <button onClick={() => go(prev.b.slug)}>← {prev.b.title.replace(/`/g, "") || "Inicio"}</button> : <span />}
      {next ? <button onClick={() => go(next.b.slug)}>{next.b.title.replace(/`/g, "")} →</button> : <span />}
    </div>
  );
}
