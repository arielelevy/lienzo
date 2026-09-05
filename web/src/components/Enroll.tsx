import { useEffect, useState } from "react";
import { api } from "../api";

interface EnrollData {
  passphrase: string | null;
  otpauth: string;
  expires_in: number;
}

interface Props {
  token: string;
  onReady: (passphrase: string) => void;
}

/** Se abre en el celular al escanear el QR de la URL. Si Authenticator ya tiene la cuenta
 *  (escaneada desde la app en la PC), va directo al login. Si no, ofrece la clave para
 *  cargarla a mano con copiar y pegar: Microsoft Authenticator no toma enlaces otpauth://. */
export function Enroll({ token, onReady }: Props) {
  const [data, setData] = useState<EnrollData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const secret = data ? new URL(data.otpauth).searchParams.get("secret") ?? "" : "";

  useEffect(() => {
    api.get<EnrollData>(`/enroll?token=${encodeURIComponent(token)}`).then(setData).catch((e) => setError((e as Error).message));
  }, [token]);

  const copy = async (what: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(what);
    } catch {
      setCopied(null);
    }
  };

  return (
    <div className="gate">
      <div className="gate-box">
        <h1>Lienzo en este teléfono</h1>
        {error && (
          <>
            <div className="gate-err">{error}</div>
            <button className="primary" onClick={() => onReady("")}>Ir al login</button>
          </>
        )}
        {data && (
          <>
            <p className="small">Si ya escaneaste el QR de Authenticator en la PC, entrá directo.</p>
            <button className="primary" onClick={() => onReady(data.passphrase ?? "")}>Ir al login</button>
            <details>
              <summary className="small dim pointer">Todavía no cargué la cuenta en Authenticator</summary>
              <p className="small">
                En Authenticator: Agregar cuenta → Otra cuenta → "Introducir código manualmente". Nombre: Lienzo.
                Clave: la de abajo (copiar y pegar).
              </p>
              <pre className="pass small">{secret}</pre>
              <button onClick={() => copy("secret", secret)}>{copied === "secret" ? "Clave copiada" : "Copiar clave"}</button>
            </details>
            {data.passphrase && (
              <>
                <div className="k">Passphrase</div>
                <pre className="pass">{data.passphrase}</pre>
                <button onClick={() => copy("pass", data.passphrase!)}>{copied === "pass" ? "Copiada" : "Copiar passphrase"}</button>
              </>
            )}
            <div className="small dim">Este enlace vence en {Math.round(data.expires_in / 60)} min.</div>
          </>
        )}
      </div>
    </div>
  );
}
