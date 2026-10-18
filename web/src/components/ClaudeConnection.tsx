import { useEffect, useRef, useState } from "react";
import { sessionsApi } from "../api";
import type { Session } from "../types";

/** La autorización ocurre en Claude; el tablero sólo ofrece el comando público. */
export function ClaudeConnection({ session: s, toast }: { session: Session; toast: (text: string, error?: boolean) => void }) {
  const [connection, setConnection] = useState<Awaited<ReturnType<typeof sessionsApi.claudePipe>>>();
  const [busy, setBusy] = useState(false);
  const [expired, setExpired] = useState(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!connection) return;
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, connection.expires_at * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [connection]);
  const connect = async () => {
    setBusy(true);
    try {
      const result = await sessionsApi.claudePipe(s.session_id, true);
      if (mounted.current) { setExpired(false); setConnection(result); }
    } catch (error) {
      if (mounted.current) toast(`No se pudo conectar: ${(error as Error).message}`, true);
    } finally { if (mounted.current) setBusy(false); }
  };
  return <div className="send">
    <p role="status">{s.envio?.motivo || "Falta conectar el adaptador de esta sesión Claude"}</p>
    <button disabled={busy || !s.alive || !s.pid || !!s.pending_id || !!s.stopped_by} onClick={() => { void connect(); }}>
      {busy ? "Preparando conexión…" : connection ? "Generar otro comando" : "Conectar esta sesión Claude"}
    </button>
    {connection?.connected && <p role="status">Adaptador conectado. Esperando la capacidad actual de la sesión.</p>}
    {connection && !connection.connected && <div>
      <p>Ejecutá este comando público desde esta sesión Claude y aprobalo allí. No contiene secretos.</p>
      <p>En PowerShell empieza con &amp;. Si la caja ya está en modo bash, no agregues otro !. El adaptador reconecta al reiniciar el server mientras siga vivo el mismo proceso Claude. Un cierre explícito del enlace requiere conectarlo de nuevo.</p>
      {expired ? <p role="status">El comando venció. Generá otro antes de ejecutarlo.</p> : <>
        <textarea readOnly aria-label="Comando público para conectar Claude" value={connection.command} />
        <button onClick={() => {
          if (!navigator.clipboard) { toast("Este navegador no permite copiar; seleccioná el comando y copialo.", true); return; }
          void navigator.clipboard.writeText(connection.command).then(() => toast("Comando copiado"), () => toast("No se pudo copiar el comando; podés seleccionarlo y copiarlo.", true));
        }}>Copiar comando</button>
        <p>Válido hasta {new Date(connection.expires_at * 1000).toLocaleTimeString()}. La escritura se habilita sólo al confirmar el adaptador vivo.</p>
      </>}
    </div>}
  </div>;
}
