# Revisión: cuenta de Claude según la carpeta al lanzar

Alcance: `lienzo/launch.py`, `tests/test_launch.py`, `docs/claude-dos-cuentas.md`. Pedido de Ariel (2026-10-29): todo Claude lanzado bajo `D:/Apps` usa la cuenta SmartBI.

Revisión manual del diff, sin subagentes.

- La ruta del perfil entra al `.cmd` con `set "CLAUDE_CONFIG_DIR=..."`. Se rechazan `" % ! & | < > ^` y los saltos de línea. Se exige cp1252, una ruta absoluta y que exista. Prueba: `test_regla_que_aplica_y_esta_mal_no_lanza_con_otra_cuenta`.
- Una regla que aplica y es inválida no lanza. No hay vuelta silenciosa al perfil de siempre.
- La contención reutiliza `_cwd_allowed`, con ruta física y `commonpath`. Una carpeta hermana con el mismo prefijo, como `D:/Apps2`, no entra.
- WSL y `claude_pipe` con regla se rechazan. El adaptador del pipe lee el registro de sesiones del perfil del server.
- Restaurar: si el id sólo existe en el perfil de siempre, se retoma ahí y se avisa. Sin esto, `--resume` fallaría con «No conversation found». El id ya viene validado por `_resume_args`.
- Límite: el perfil de siempre se toma del entorno del server. Si el entorno de explorer.exe trae otro `CLAUDE_CONFIG_DIR`, el `.cmd` sin regla lo hereda, igual que antes del cambio.

Verificación: `uv run --extra dev pytest tests/test_launch.py tests/test_launch_improvements.py tests/test_launch_limpieza.py` dio 60 passed, de los cuales 12 son nuevos. `ruff check` y `ruff format --check` pasan. No se corrió la suite global.
