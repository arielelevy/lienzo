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
    };
  }, [refreshAuth, selectedRef]);

  return { sessions, pending, links, rules, connected, polling, transcriptTick };
}
