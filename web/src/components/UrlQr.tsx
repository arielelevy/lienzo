import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { copyLabel, useCopyState } from "../names";

/** URL navegable (link en pestaña nueva) con boton Copiar al lado. El boton avisa solo,
 *  cambiando su texto dos segundos, para no depender del toast global. */
export function UrlLink({ url }: { url: string }) {
  const { state, copy } = useCopyState();
  return (
    <div className="row" style={{ alignItems: "center", gap: 8 }}>
      <a href={url} target="_blank" rel="noopener" className="small" style={{ wordBreak: "break-all", flex: "1 1 auto", minWidth: 0 }}>
        {url}
      </a>
      <button type="button" onClick={() => copy(url)} title="copiar la URL" style={{ flex: "0 0 auto" }}>
        {copyLabel(state)}
      </button>
    </div>
  );
}

/** QR de la URL del tunel para abrir el lienzo desde el celular. */
export function UrlQr({ url, onClose, mode = "code" }: { url: string; onClose: () => void; mode?: "code" | "full" }) {
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    QRCode.toDataURL(url, { width: 260, margin: 1 }).then(setQr).catch(() => setQr(null));
  }, [url]);
  return (
    <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="gate-box">
        <h1>Abrir en el celular</h1>
        {qr && <img src={qr} alt="QR URL" width={260} height={260} style={{ alignSelf: "center" }} />}
        <UrlLink url={url} />
        <div className="small dim">
          {mode === "full" ? "Pide la passphrase y el código de Authenticator." : "Pide el código de Authenticator."} La URL cambia
          cada vez que arranca el túnel.
        </div>
        <div className="row">
          <span className="sp" />
          <button onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </div>
  );
}
