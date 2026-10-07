# Notas del frente D (ronda 3) — fuera de mis archivos

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

- Resuelto en la segunda vuelta: las dos cosas que había anotado acá (renombrar esta PC y que
  el selector de destino descartara una PC caída) las pidió la coordinadora después de verificar,
  con `PUT /peers/self` ya agregado por el frente C en `server.py`. Quedaron en `Pairing.tsx` y
  `App.tsx`, ver `informe-D.md`.

- **`GET /peers` sin ruta (server viejo) vs. sin nada emparejado son estados distintos** y los
  distinguí en `Pairing.tsx` (`peers.length === 0` vs. `=== 1`), pero recién lo vi al leer
  `pcs.spec.ts`: el mismo cuidado no está en `PcStrip.tsx` (ahí los dos casos se tratan igual, "no
  se dibuja nada", que para la tira es correcto). Nada para cambiar, solo lo dejo escrito porque no
  es obvio a la primera lectura.
