"""Siembra un proyecto con encargos en cada etapa en el LIENZO_HOME del entorno (copia L, puerto 7356).
Uso: LIENZO_HOME=<temporal lienzo-L-> py -I etapas_sembrar.py <carpeta lienzo de la copia> (lo lanza etapas_e2e.ps1)"""

import os
import sys

assert os.environ.get("LIENZO_HOME") and "lienzo-L-" in os.environ["LIENZO_HOME"], "solo sobre la copia temporal"
sys.path.insert(0, sys.argv[1])
import conocimiento as k

C = "coordinadora:sid-coord"
k.registrar_proyecto("etapas", "Etapas", [], [])
r = k.abrir_ronda("etapas", "Ronda de prueba L", autor=C)


def encargo(letra, texto):
    e = k.crear_encargo("etapas", r["id"], letra, f"# {texto}", autor=C)
    return e["id"]


def enviado(eid, letra):
    k.encargo_enviado("etapas", eid, {"session_id": f"sid-{letra}", "agent": "claude"})


encargo("A", "Encargo pendiente")
b = encargo("B", "Encargo en implementacion")
enviado(b, "B")
c = encargo("C", "Encargo en revision")
enviado(c, "C")
k.entregar("etapas", c, "## Informe C r1", revision=1, autor="frente:sid-C")
d = encargo("D", "Encargo en verificacion")
enviado(d, "D")
k.entregar("etapas", d, "## Informe D r1", revision=1, autor="frente:sid-D")
ev = k.recibir_evidencia("etapas", "code-review-D.md", b"revision D", clase="revision", autor=C)
k.vincular("etapas", d, "apoya", ev["id"], autor=C)
k.cambiar_estado("etapas", d, "verificando", por=C, motivo="revision sin hallazgos")
k.recibir_evidencia("etapas", "suite-focal-D.txt", b"9 passed", clase="prueba", autor=C)
k.recibir_evidencia("etapas", "code-review-C.md", b"revision C", clase="revision", autor=C)
print("sembrado", r["id"], b, c, d)
