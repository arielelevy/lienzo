import { useState } from "react";

type Decision = "allow" | "deny";

/** Permitir / Denegar, con su propio "ocupado": mientras el POST de la decision esta en vuelo los
 *  dos botones quedan deshabilitados. Antes cada boton llamaba a onDecide directo y un doble click
 *  (o Permitir y enseguida Denegar) mandaba dos POST al mismo pedido; el segundo llegaba a un
 *  pendiente ya contestado y su error salia como toast rojo despues del "Permitido".
 *
 *  Lo usan la tarjeta y el panel, para el permiso del hook y para el de CODA que se teclea en su
 *  terminal. `onDecide` tiene que devolver la promesa del pedido (y atrapar sus errores: el toast
 *  es de quien llama). Los botones llevan `data-always-tab` (en la tarjeta quedan en el orden de
 *  tabulacion aunque el foco no este adentro, porque el permiso vence) y frenan la propagacion:
 *  el click no elige ni abre la tarjeta. */
export function PermissionButtons({ onDecide, note }: { onDecide: (d: Decision) => Promise<void>; note?: string }) {
  const [busy, setBusy] = useState(false);
  const decide = async (e: React.MouseEvent, d: Decision) => {
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      await onDecide(d);
    } finally {
      // contestado, el pendiente se va por SSE y el bloque se desmonta; si fallo, se puede reintentar
      setBusy(false);
    }
  };
  return (
    <div className="btns">
      <button className="allow" data-always-tab="" disabled={busy} onClick={(e) => void decide(e, "allow")}>Permitir</button>
      <button className="deny" data-always-tab="" disabled={busy} onClick={(e) => void decide(e, "deny")}>Denegar</button>
      {note && <span className="dim small">{note}</span>}
    </div>
  );
}

/** El bloque "Pide permiso" de un pendiente del hook, igual en la tarjeta y en el panel. */
export function PermissionPrompt({ tool, detail, note, onDecide }: { tool: string; detail: string; note: string; onDecide: (d: Decision) => Promise<void> }) {
  return (
    // no se frena la propagacion del bloque entero: es la mitad de la tarjeta y frenarlo dejaba
    // el doble click sin abrir el panel. Los dos botones la frenan por su cuenta
    <div className="needs">
      <b>Pide permiso: {tool}</b>
      <code>{detail}</code>
      <PermissionButtons onDecide={onDecide} note={note} />
    </div>
  );
}
