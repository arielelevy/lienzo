# Code review — noche D (2026-10-22)

Delta revisado: `lienzo/codex_observation.py` (+2 líneas: `_footer` pasa `env={"PYTHONIOENCODING": "utf-8"}`)
y `tests/test_codex_new_clear.py` (nuevo, 7 pruebas). Skill `code-review`, nivel low.

## Hallazgos

Ninguno confirmado.

- Duda del revisor: si `subproc.correr` pasara `env` tal cual, el hijo perdería PATH/SYSTEMROOT.
  Descartada: `lienzo/subproc.py:125` arma `{**os.environ, **(env or {})}`. Medido en vivo
  (`.temp/resultados/noche-D/footer-utf8-vivo.txt`): sin el env, `screen.py` sale 1 con
  `UnicodeEncodeError`; con el env, 0 y `ok: true`.

## Verificación

- Rojo: `test_footer_reader_forces_utf8_output` falla contra `codex_observation.py` de HEAD.
- Verde: 128 passed (Codex y plugins) en copia de HEAD con los archivos de D.
- `ruff format` / `ruff check` sólo sobre las dos rutas: sin cambios, sin avisos.
