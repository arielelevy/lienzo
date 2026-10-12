# Revisión de actualización de harness

Alcance: cambios de este encargo en `lienzo/harness_updates.py`, `lienzo/launch.py`,
`lienzo/server.py`, `lienzo/subproc.py` y `tests/test_harness_updates.py`.
Sin auditoría del resto del repositorio.

Se revisaron ejecución de comandos, rutas Windows y WSL, concurrencia, intervalos,
errores y límites de tiempo. La prueba real detectó que el escape automático de una lista
rompía `.cmd` con espacios. Se corrigió pasando una línea explícita a CreateProcess,
sin `shell=True`; `subproc.correr` admite esa entrada y conserva diagnósticos y límites.
La regresión reproduce la ejecución con un helper real. No quedan defectos bloqueantes.
Los comandos se contrastaron con la ayuda de los cinco ejecutables instalados; Pi usa
`update --self --no-approve`, sin instalar extensiones ni confiar en proyectos locales.
Las rutas `.cmd` rechazan caracteres de expansión; WSL recibe argumentos sin shell.
El helper existente mata el árbol tras 120 segundos y los fallos se registran y retornan
como aviso del lanzamiento. Hay exclusión por harness y entorno y reintento tras 15 minutos.

Validación focal final: 40 pruebas aprobadas; reloj y actualizadores controlados, y un `.cmd`
real que imprime una marca. Primera corrida del backend: 1400 pruebas aprobadas;
la corrida final verifica además la corrección de CreateProcess. Ruff sin hallazgos.
No se actualizó ninguna instalación real como parte de esas pruebas. La comprobación real
se verificará tras el reinicio autorizado; una sesión abierta conserva su versión en memoria.

Limitaciones: no se audita el contenido de los actualizadores externos; versiones antiguas
que no admitan estos comandos darán aviso de error. No se certificó mutación del código nuevo
ni se aceptaron baselines o documentos de pruebas.

Verificación en vivo: el primer arranque actualizó Kiro a 2.29.1 y comprobó Claude,
Pi y CODA sin errores. Codex tenía una copia 0.160.1 en `.local/bin` y una instalación
oficial distinta. Se actualizó esta última a 0.162.1 y se corrigió el resolver para
priorizar la entrada oficial en LocalAppData/Programs/OpenAI/Codex/bin.
Una regresión crea ambas rutas y exige elegir la instalación administrada.
Verificación del ajuste final: 162 pruebas de actualizaciones, lanzamiento, reanudación y
WSL aprobadas; Ruff sin hallazgos. El resolver real devuelve la entrada oficial actualizada.
