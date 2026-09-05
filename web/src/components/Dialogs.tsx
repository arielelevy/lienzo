import { Forward } from "./Forward";
import type { Session } from "../types";

/** Fondo que cierra al click y con Esc (Esc lo maneja App, que sabe que esta abierto). */
function Gate({ onClose, className = "", children }: { onClose: () => void; className?: string; children: React.ReactNode }) {
  return (
    <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`gate-box ${className}`}>{children}</div>
    </div>
  );
}

export function HelpDialog({ onClose }: { onClose: () => void }) {
  const rows: [string, string][] = [
    ["Esc", "cierra el panel, el diálogo de conectar o esta ayuda; en la búsqueda, la limpia"],
    ["Tab", "en la caja de envío, acepta la sugerencia gris leída de la terminal"],
    ["/", "enfoca la búsqueda (repo, título, último pedido)"],
    ["?", "muestra u oculta esta ayuda"],
    ["Enter", "sobre una tarjeta enfocada, abre su panel"],
    ["arrastrar", "una tarjeta sobre otra abre el diálogo de conectar con ese destino"],
    ["click", "en el título de una columna la colapsa a una tira; en la tira, la expande"],
  ];
  return (
    <Gate onClose={onClose} className="help">
      <h1>Atajos</h1>
      <dl>
        {rows.map(([k, d]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k.length <= 5 ? <kbd>{k}</kbd> : k}</dt>
            <dd>{d}</dd>
          </div>
        ))}
      </dl>
      <div className="row">
        <span className="sp" />
        <button onClick={onClose}>Cerrar</button>
      </div>
    </Gate>
  );
}

interface ConnectProps {
  sessions: Record<string, Session>;
  from: string;
  to: string;
  toast: (msg: string, err?: boolean) => void;
  onClose: () => void;
}

/** Dialogo de conectar (por arrastre o desde el panel): flotante, sin abrir nada mas. */
export function ConnectDialog({ sessions, from, to, toast, onClose }: ConnectProps) {
  const a = sessions[from];
  const b = to ? sessions[to] : undefined;
  if (!a) return null;
  return (
    <Gate onClose={onClose} className="wide connect">
      <h1>
        <span className={`badge ${a.agent}`}>{a.agent}</span>
        {a.title || a.repo}
        {b && (
          <>
            <span className="dim">→</span>
            <span className={`badge ${b.agent}`}>{b.agent}</span>
            {b.title || b.repo}
          </>
        )}
      </h1>
      <Forward
        from={a}
        others={Object.values(sessions).filter((s) => s.session_id !== from && s.alive && s.pid)}
        initialTarget={to || undefined}
        toast={toast}
        onDone={onClose}
      />
    </Gate>
  );
}
