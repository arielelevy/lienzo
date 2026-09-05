import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** QR de la URL del tunel para abrir el lienzo desde el celular. */
export function UrlQr({ url, onClose }: { url: string; onClose: () => void }) {
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    QRCode.toDataURL(url, { width: 260, margin: 1 }).then(setQr).catch(() => setQr(null));
  }, [url]);
  return (
    <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="gate-box">
        <h1>Abrir en el celular</h1>
        {qr && <img src={qr} alt="QR URL" width={260} height={260} style={{ alignSelf: "center" }} />}
        <pre className="pass small">{url}</pre>
        <div className="small dim">Pide passphrase y código de Authenticator. La URL cambia cada vez que arranca el túnel.</div>
        <div className="row">
          <span className="sp" />
          <button onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </div>
  );
}
