import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** Una imagen corresponde al texto y tamaño actuales; una respuesta tardía se descarta. */
export function useQr(text: string | null, width = 240) {
  const [result, setResult] = useState<{ text: string; width: number; image: string } | null>(null);
  useEffect(() => {
    if (!text) return;
    let active = true;
    QRCode.toDataURL(text, { width, margin: 1 })
      .then(image => { if (active) setResult({ text, width, image }); })
      .catch(() => { if (active) setResult(null); });
    return () => { active = false; };
  }, [text, width]);
  return result?.text === text && result.width === width ? result.image : null;
}
