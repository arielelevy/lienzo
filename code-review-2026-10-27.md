# Code review 2026-10-27

## Permiso de coda ya contestado que volvía a la tarjeta

- Alcance: `lienzo/sessions.py` (`answer_coda_ask`), comentario en `lienzo/hooks_eventos.py`, test nuevo en `tests/test_coda.py`.
- Nivel: low (skill `code-review`).
- Resultado: sin hallazgos. Marcar `coda_fondo_hecho` también para el permiso del turno hace que `coda_log_activity` ignore ese `at` mientras el log lo siga mostrando.
- Verificación: `test_permiso_del_turno_ya_contestado_no_vuelve_mientras_corre_el_comando` falla sin el arreglo y pasa con él.
