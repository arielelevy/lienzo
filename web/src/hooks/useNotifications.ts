import { useCallback, useEffect, useRef, useState } from "react";
import { detail } from "../api";
import type { Pending, Session } from "../types";

interface Options {
  sessions: Record<string, Session>;
  pending: Record<string, Pending>;
  onOpen: (sid: string) => void;
  toast: (msg: string, err?: boolean) => void;
}

const KEY = "lienzo.notify";
const granted = () => typeof Notification !== "undefined" && Notification.permission === "granted";

/** Notificaciones del navegador cuando una sesion pide permiso: por pending nuevo, o por tarjeta
 *  que pasa a "te necesita" por permiso. Se detectan por transicion contra el estado anterior;
 *  lo que ya estaba al abrir la pestana no es novedad. */
export function useNotifications({ sessions, pending, onOpen, toast }: Options) {
  const [notify, setNotify] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1" && granted();
    } catch {
      return false;
    }
  });
  const remember = (v: boolean) => {
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* sin storage, no importa */
    }
  };
  const toggleNotify = useCallback(async () => {
    if (typeof Notification === "undefined") {
      toast("Este navegador no tiene notificaciones", true);
      return;
    }
    if (notify) {
      setNotify(false);
      remember(false);
      return;
    }
    const perm = granted() ? "granted" : await Notification.requestPermission();
    if (perm !== "granted") {
      toast("El navegador no dio permiso para notificar", true);
      return;
    }
    setNotify(true);
    remember(true);
    toast("Notificaciones activadas");
  }, [notify, toast]);

  const notifyRef = useRef(notify);
  notifyRef.current = notify;
  const fire = useCallback(
    (sid: string, title: string, body: string) => {
      if (!notifyRef.current || !granted()) return;
      try {
        const n = new Notification(title, { body, tag: `lienzo-${sid}` });
        n.onclick = () => {
          window.focus();
          onOpen(sid);
          n.close();
        };
      } catch {
        /* sin notificaciones (contexto inseguro, etc.) */
      }
    },
    [onOpen],
  );

  // recien despues del primer render con datos se empieza a comparar
  const armedRef = useRef(false);
  const seenPendingRef = useRef<Set<string> | null>(null);
  const permNeedRef = useRef<Set<string> | null>(null);
  const hasData = Object.keys(sessions).length > 0 || Object.keys(pending).length > 0;

  useEffect(() => {
    const ids = new Set(Object.keys(pending));
    const prev = seenPendingRef.current;
    seenPendingRef.current = ids;
    if (!prev || !armedRef.current) return;
    for (const p of Object.values(pending)) {
      if (prev.has(p.request_id)) continue;
      const who = sessions[p.session_id]?.repo ?? p.agent;
      fire(p.session_id, `${who} pide permiso: ${p.tool_name}`, detail(p.tool_input).slice(0, 200));
    }
  }, [pending, sessions, fire]);

  useEffect(() => {
    const now = new Set<string>();
    for (const s of Object.values(sessions)) if (s.state === "te_necesita" && s.needs?.kind === "permission") now.add(s.session_id);
    const prev = permNeedRef.current;
    permNeedRef.current = now;
    const armed = armedRef.current;
    if (hasData) armedRef.current = true;
    if (!prev || !armed) return;
    for (const sid of now) {
      if (prev.has(sid)) continue;
      const s = sessions[sid];
      if (!s || s.pending_id) continue; // el pending ya avisa con mas detalle
      fire(sid, `${s.repo} pide permiso: ${s.needs?.tool ?? ""}`.trim(), (s.needs?.detail ?? "").slice(0, 200));
    }
  }, [sessions, hasData, fire]);

  return { notify, toggleNotify };
}
