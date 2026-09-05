import { useState, type FormEvent } from "react";
import { api } from "../api";

interface Props {
  onDone: () => void;
  mode: "code" | "full";
  initialPassphrase?: string;
}

/** Login desde afuera. Modo "code" (el elegido): solo el codigo de Authenticator.
 *  Modo "full": ademas la passphrase de seis palabras. */
export function Login({ onDone, mode, initialPassphrase = "" }: Props) {
  const [passphrase, setPassphrase] = useState(initialPassphrase);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const needPass = mode === "full";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/login", { passphrase, code });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gate">
      <form className="gate-box" onSubmit={submit}>
        <h1>Lienzo</h1>
        {needPass && (
          <label>
            Passphrase
            <input
              type="password"
              autoComplete="current-password"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              placeholder="seis palabras separadas por espacio"
              autoFocus={!initialPassphrase}
            />
          </label>
        )}
        <label>
          Código de Authenticator
          <input
            inputMode="numeric"
            pattern="[0-9 ]*"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="6 dígitos"
            autoFocus={!needPass || !!initialPassphrase}
            className="code"
          />
        </label>
        {error && <div className="gate-err">{error}</div>}
        <button className="primary" disabled={busy || (needPass && !passphrase) || code.replace(/\s/g, "").length !== 6}>
          Entrar
        </button>
        <div className="small dim">La sesión dura 7 días en este dispositivo. Cinco intentos fallidos bloquean el login 15 minutos.</div>
      </form>
    </div>
  );
}
