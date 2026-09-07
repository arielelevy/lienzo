import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Link, Pending, Rule, ServerEvent, Session } from "../types";

interface Options {
  /** se llama al abrir o cortar el stream: la URL del tunel o la cookie pueden haber cambiado */
  refreshAuth: () => void;
  /** tarjeta abierta ahora (ref, para no re-suscribir el stream cuando cambia) */
  selectedRef: React.RefObject<string | null>;
  /** una sesion desaparecio del tablero */
  onRemoved: (sid: string) => void;
}

/** El tablero dibuja flechas entre sesiones: lo que mando el usuario desde el SendBox (from null,
 *  kind "user") no tiene origen y queda solo en la pestana Conexiones del panel. */
const boardLinks = (ls: Link[]): Link[] => ls.filter((l) => !!l.from);

/** Estado del tablero: sesiones, permisos pendientes, vinculos y reglas, alimentados por el
 *  stream SSE del server. Carga directa al entrar y sondeo cada 4 s mientras el stream no
 *  entregue nada (un proxy que retiene el SSE no deja el tablero vacio). */
export function useLienzoData({ refreshAuth, selectedRef, onRemoved }: Options) {
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const [pending, setPending] = useState<Record<string, Pending>>({});
  const [links, setLinks] = useState<Link[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [connected, setConnected] = useState(false);
  const [polling, setPolling] = useState(false);
  /** sube cuando la transcripcion de la tarjeta abierta cambio: el panel recarga */
  const [transcriptTick, setTranscriptTick] = useState(0);
  const lastMsgRef = useRef(0);
  /** sello del bundle que sirvio esta pagina, y si ya vimos uno distinto (ver `verBuild`) */
  const buildRef = useRef<string | null>(null);
  const pendienteRef = useRef(false);
  const onRemovedRef = useRef(onRemoved);
  onRemovedRef.current = onRemoved;

  useEffect(() => {
    const byId = <T,>(xs: T[], key: (x: T) => string) => Object.fromEntries(xs.map((x) => [key(x), x]));
    const load = () =>
      Promise.all([api.get<Session[]>("/sessions"), api.get<Pending[]>("/pending"), api.get<Link[]>("/links"), api.get<Rule[]>("/rules")])
        .then(([ss, ps, ls, rs]) => {
          setSessions(byId(ss, (s) => s.session_id));
          setPending(byId(ps, (p) => p.request_id));
          setLinks(boardLinks(ls));
          setRules(rs);
          if (selectedRef.current) setTranscriptTick((t) => t + 1);
        })
        .catch(() => null);
    load();
    const poll = setInterval(() => {
      const stale = Date.now() - lastMsgRef.current > 20000;
      setPolling(stale);
      if (stale) load();
    }, 4000);

    /** El lienzo es una pagina sola: despues de un `npm run build` seguia corriendo el bundle
     *  viejo y los cambios parecian no aplicarse hasta un Ctrl+R a mano. El server manda el sello
     *  del bundle en cada latido; cuando cambia, esto recarga. No recarga en el momento si el foco
     *  esta en una caja de texto o hay algo escrito a medias: se anota y recarga en el proximo
     *  latido en que la pantalla este quieta, porque perder un mensaje a medio escribir es peor
     *  que ver el tablero viejo quince segundos mas. */
    const verBuild = (build?: string) => {
      if (!build) return;
      if (!buildRef.current) {
        buildRef.current = build; // el primero que se ve es el de esta pagina
        return;
      }
      if (build === buildRef.current && !pendienteRef.current) return;
      pendienteRef.current = true;
      const el = document.activeElement as HTMLElement | null;
      const escribiendo =
        !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      const conTexto = [...document.querySelectorAll("textarea")].some((t) => t.value.trim() !== "");
      // eslint-disable-next-line no-console
      if (escribiendo || conTexto) console.info("lienzo: hay una version nueva; se recarga al terminar de escribir");
      if (escribiendo || conTexto) return;
      window.location.reload();
    };

    // cada 30 s: el latido del SSE no sirve de portador porque sale solo cuando la cola esta en
    // silencio 15 s, y con el tablero activo casi nunca lo esta
    const mirarBuild = () => api.get<{ build: string }>("/build").then((r) => verBuild(r.build)).catch(() => null);
    mirarBuild(); // el primero fija el sello de esta pagina; sin esto el sello se tomaba recien a
    // los 30 s, o sea ya con el bundle nuevo, y la comparacion no detectaba nunca un cambio
    const buildPoll = window.setInterval(mirarBuild, 30000);

    const es = new EventSource("/events");
    es.onopen = () => {
      setConnected(true);
      refreshAuth();
    };
    es.onerror = () => {
      setConnected(false);
      refreshAuth();
    };
    es.onmessage = (ev) => {
      lastMsgRef.current = Date.now();
      const m = JSON.parse(ev.data) as ServerEvent;
      switch (m.type) {
        case "snapshot":
          setSessions(byId(m.sessions, (s) => s.session_id));
          setPending(byId(m.pending, (p) => p.request_id));
          if (m.links) setLinks(boardLinks(m.links));
          if (m.rules) setRules(m.rules);
          setTranscriptTick((t) => t + 1);
          break;
        case "links":
          setLinks(boardLinks(m.links));
          break;
        case "rules":
          setRules(m.rules);
          break;
        case "session":
          setSessions((prev) => ({ ...prev, [m.session.session_id]: m.session }));
          break;
        case "removed":
          setSessions((prev) => {
            const next = { ...prev };
            delete next[m.session_id];
            return next;
          });
          onRemovedRef.current(m.session_id);
          break;
        case "pending":
          setPending(byId(m.pending, (p) => p.request_id));
          break;
        case "transcript":
          if (selectedRef.current === m.session_id) setTranscriptTick((t) => t + 1);
          break;
      }
    };
    return () => {
      es.close();
      clearInterval(poll);
      clearInterval(buildPoll);
    };
  }, [refreshAuth, selectedRef]);

  return { sessions, pending, links, rules, connected, polling, transcriptTick };
}
