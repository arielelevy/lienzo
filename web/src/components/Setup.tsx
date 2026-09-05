import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { api, type AuthInfo } from "../api";

interface SetupResult {
  mode: "code" | "full";
  passphrase: string | null;
  totp_secret: string;
  otpauth: string;
  enroll_token: string;
  enroll_expires_s: number;
}

interface Props {
  onClose: (configured: boolean) => void;
}

export function useQr(text: string | null, width = 240) {
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    if (!text) return;
    QRCode.toDataURL(text, { width, margin: 1 }).then(setQr).catch(() => setQr(null));
  }, [text, width]);
  return qr;
}

/** Alta del acceso desde el celular, solo desde la PC y una sola vez. Dos QR, cero tipeo:
 *  1) el otpauth, que se escanea DESDE ADENTRO de Microsoft Authenticator (la app no toma
 *     enlaces otpauth:// con datos; solo su propio escaner);
 *  2) la URL del tunel, que se escanea con la camara y abre el lienzo en el telefono. */
export function Setup({ onClose }: Props) {
  const [res, setRes] = useState<SetupResult | null>(null);
  const [remoteUrl, setRemoteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const totpQr = useQr(res?.otpauth ?? null, 230);
  const urlQr = useQr(remoteUrl, 230);

  useEffect(() => {
    if (!res || remoteUrl) return;
    const poll = () => api.get<AuthInfo>("/auth").then((a) => a.remote_url && setRemoteUrl(a.remote_url)).catch(() => null);
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, [res, remoteUrl]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      setRes(await api.post<SetupResult>("/setup", { mode: "code" }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gate">
      <div className="gate-box wide">
        <h1>Acceso desde el celular</h1>
        {!res ? (
          <>
            <p>
              Se genera una clave para Microsoft Authenticator. Desde afuera el lienzo pide el código de 6 dígitos;
              en esta PC sigue sin pedir nada. El server tiene que estar corriendo con <code>--remote</code>.
            </p>
            {error && <div className="gate-err">{error}</div>}
            <div className="row">
              <button onClick={() => onClose(false)}>Cancelar</button>
              <button className="primary" disabled={busy} onClick={create}>Generar</button>
            </div>
          </>
        ) : (
          <>
            <div className="two">
              <div>
                <div className="k">1 · En Microsoft Authenticator</div>
                <p className="small">Agregar cuenta → Otra cuenta (Google, Facebook, etc.) → escanear este QR.</p>
                {totpQr && <img src={totpQr} alt="QR Authenticator" width={230} height={230} />}
                <details>
                  <summary className="small dim pointer">clave para cargar a mano</summary>
                  <pre className="pass small">{res.totp_secret}</pre>
                  <div className="small dim">Nombre: Lienzo · basado en tiempo · 6 dígitos · 30 s</div>
                </details>
              </div>
              <div>
                <div className="k">2 · Con la cámara del celular</div>
                <p className="small">Abre el lienzo en el teléfono. Te pide el código de Authenticator y listo.</p>
                {remoteUrl ? (
                  <>
                    {urlQr && <img src={urlQr} alt="QR URL" width={230} height={230} />}
                    <pre className="pass small">{remoteUrl}</pre>
                  </>
                ) : (
                  <div className="small dim">Esperando la URL del túnel…</div>
                )}
              </div>
            </div>
            {res.passphrase && (
              <>
                <div className="k">Passphrase (una sola vez)</div>
                <pre className="pass">{res.passphrase}</pre>
              </>
            )}
            <div className="small dim">Esta pantalla no se cierra sola. El QR de Authenticator se puede volver a ver desde el botón del encabezado.</div>
            <div className="row">
              <span className="sp" />
              <button className="primary" onClick={() => onClose(true)}>Listo</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Volver a mostrar el QR de Authenticator para un acceso ya configurado (solo local). */
export function TotpQr({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ otpauth: string; totp_secret: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ otpauth: string; totp_secret: string }>("/totp").then(setData).catch((e) => setError((e as Error).message));
  }, []);
  const qr = useQr(data?.otpauth ?? null, 260);
  return (
    <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="gate-box">
        <h1>QR para Authenticator</h1>
        <p className="small">En Microsoft Authenticator: Agregar cuenta → Otra cuenta → escanear.</p>
        {error && <div className="gate-err">{error}</div>}
        {qr && <img src={qr} alt="QR Authenticator" width={260} height={260} style={{ alignSelf: "center" }} />}
        {data && (
          <details>
            <summary className="small dim pointer">clave para cargar a mano</summary>
            <pre className="pass small">{data.totp_secret}</pre>
          </details>
        )}
        <div className="row">
          <span className="sp" />
          <button onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </div>
  );
}
