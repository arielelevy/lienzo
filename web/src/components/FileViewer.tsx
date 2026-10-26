import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fileLink } from "../file-links";
import "../knowledge.css";

type FileData = { path: string; text: string; markdown: boolean };

export function FileViewer() {
  const path = new URLSearchParams(location.search).get("path") ?? decodeURIComponent(location.pathname).replace(/^\/([a-z]:\/)/i, "$1");
  const [data, setData] = useState<FileData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/file-content?path=${encodeURIComponent(path)}`, { signal: controller.signal })
      .then(async response => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error ?? `Error ${response.status}`);
        setData(result);
      }).catch((err: Error) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [path]);
  return <main style={{ padding: 24, maxWidth: 1100, margin: "auto" }}>
    <header style={{ position: "sticky", top: 0, background: "var(--bg)", padding: "12px 0", borderBottom: "1px solid var(--line)", zIndex: 1 }}>
      <a href="/">← Lienzo</a>
      <div style={{ overflowWrap: "anywhere", marginTop: 8 }}><strong>Ruta física: </strong><code>{data?.path ?? path}</code></div>
    </header>
    {error ? <p role="alert">{error}</p> : !data ? <p>Cargando archivo…</p> : data.markdown ?
      <article className="knowledge-markdown"><ReactMarkdown urlTransform={(href) => fileLink(href, data.path.replace(/\\/g, "/"))} remarkPlugins={[remarkGfm]} components={{
        a: ({ href = "", children }) => <a href={href}>{children}</a>,
        img: ({ alt }) => <span>[Imagen: {alt ?? "sin descripción"}]</span>,
      }}>{data.text}</ReactMarkdown></article> : <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{data.text}</pre>}
  </main>;
}
