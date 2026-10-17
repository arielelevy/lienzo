# Revisión focal del diagnóstico de bootstrap

Alcance autorizado: fallo `claude_pipe_adapter_failed` reportado por Ariel después del reinicio.
Archivos: `lienzo/claude_pipe_adapter.py`, `tests/test_bootstrap_diagnostico.py`.

Se conserva el código 2 y toda validación de identidad, parentesco y credenciales. La salida usa
mensajes constantes; nunca interpola cuerpos de excepciones, rutas de pipes, HTTP ni entorno.
La clasificación de identidad usa códigos exactos y la de pipes códigos Windows conocidos;
errores desconocidos conservan diagnóstico genérico con recuperación, sin atribuir causa falsa.
Los modos hook y serve conservan el diagnóstico genérico. El modo correcto devuelve 0.

Sin hallazgos pendientes en este delta. Ruff y formato pasan. Runner focal: 14 pruebas pasan,
incluidas las pruebas Windows existentes del bootstrap real; son pruebas de kernel y dobles,
no reconexión de la conversación de Claude Desktop del usuario.

Recorrido secuencial Explorer → Analyser → Designer → Executor → Detective registrado en
`.temp/coordinacion/2026-10-17/bootstrap-bug/roles.json`. Runner ejecuta el caso con código 0,
pero termina 1 por falta de baseline; compuerta termina 2 por el mismo motivo. Sin PASS de
aceptación, sin baseline fijado ni mutaciones nuevas aprobadas.

Límites: no se cambia la caducidad del bootstrap ni se reconecta automáticamente Desktop.
El comando anterior continúa rechazándose; hace falta generar y ejecutar uno nuevo allí.
No se modificó la UI compartida ni el runtime reservado por otro frente. No se reinició el servidor.
