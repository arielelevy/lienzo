import assert from "node:assert/strict";
import { test } from "node:test";
// @ts-ignore TS5097: Node necesita extensión en ejecución de tests TypeScript.
import { sendNotice } from "./api.ts";
import type { SendResult } from "./api";

test("aceptación e incertidumbre no cuentan como entrega ni dicen Enviado", () => {
  for (const estado of ["encolado", "pendiente", "sin_confirmacion", "rechazado"] as const) {
    const notice = sendNotice({ chars: 4, estado, motivo: "detalle" }, "destino");
    assert.equal(notice.confirmed, false);
    assert.equal(notice.attention, true);
    assert.doesNotMatch(notice.text, /Enviado|Entregado/);
  }
  assert.equal(sendNotice({ chars: 4, estado: "entregado" }).text, "Entregado");
  assert.equal(sendNotice({ chars: 4 }).text, "Enviado (4 caracteres)");
  assert.equal(sendNotice({ chars: 4, estado: "entregado", handover_error: "pendiente" }).attention, true);
  const unknown = sendNotice({ chars: 4, estado: "future-state" } as unknown as SendResult);
  assert.equal(unknown.confirmed, false);
  assert.match(unknown.text, /sin confirmar/);
});
