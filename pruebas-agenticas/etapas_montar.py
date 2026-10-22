"""Monta la vista Etapas en el Knowledge.tsx de la copia temporal de etapas_e2e.ps1 mientras la coordinadora
no integre .temp/resultados/2026-10-22-L/Knowledge-montaje.diff. Ya montada, no hace nada. Uso: etapas_montar.py <ruta>"""

import sys

p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    s = f.read()
if 'from "./Etapas"' in s:
    sys.exit(0)
cambios = [
    (
        'import { Learning } from "./Learning";\n',
        'import { Etapas } from "./Etapas";\nimport { Learning } from "./Learning";\n',
    ),
    ('| "capturas" | "aprendizaje";', '| "capturas" | "aprendizaje" | "etapas";'),
    (
        '{ id: "aprendizaje", label: "Aprendizaje" },\n',
        '{ id: "aprendizaje", label: "Aprendizaje" },\n  { id: "etapas", label: "Etapas" },\n',
    ),
    (
        '{view === "aprendizaje" ? <Learning base={base} /> : <div',
        '{view === "aprendizaje" ? <Learning base={base} /> : view === "etapas" ? <Etapas base={base} /> : <div',
    ),
]
for viejo, nuevo in cambios:
    assert s.count(viejo) == 1, viejo
    s = s.replace(viejo, nuevo)
with open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)
