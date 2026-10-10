# Tareas: réplica y tamaño de respuestas en la consulta

- [x] 1. Endpoint `replica` en `consulta.py`
  - Validar (404/409/400), armar el pedido con la marca `[consulta <cid> · réplica]`, mandarlo con un
    helper nuevo `_enviar_uno(cid, sid, texto, de)` extraído de `_mandar_vuelta` (sin pendientes ni
    `_sacar`; `_mandar_vuelta` lo usa para cada tarjeta), y anotarlo en `c["replicas"]` (con
    `setdefault` para las consultas viejas de disco).
  - _Requisitos: 1.1, 1.2, 1.3, 1.5, 1.6_
  - _Archivos: lienzo/consulta.py, tests/test_consulta_replica.py_
  - _Leer: lienzo/consulta.py: `_mandar_vuelta`, `_rechazo`, `_participantes`, `cancelar`; design.md §Componentes/lienzo/consulta.py_
- [x] 2. Ruta en `server.py` y `consulta_replica` en `coordinar.py`
  - Agregar la ruta `POST /consultas/<id>/replica` junto a la de cancelar, y en `coordinar.py` la
    función `consulta_replica(cid, para, de, vuelta)` al lado de `consulta_estado`.
  - _Depende de: 1_
  - _Requisitos: 1.1_
  - _Archivos: lienzo/server.py, skills/lienzo/coordinar.py_
  - _Leer: lienzo/server.py: `consulta_enviar`, rutas `consultas` (GET/POST, cancelar); skills/lienzo/coordinar.py: `consulta`, `consulta_estado`_
- [x] 3. Línea en `SKILL.md`
  - Una línea en «Consulta entre investigadores» que documente `c.consulta_replica(cid, para, de, vuelta)`.
  - _Depende de: 2_
  - _Requisitos: 5.1 (de consulta-replica: la función documentada)_
  - _Archivos: skills/lienzo/SKILL.md_
  - _Leer: skills/lienzo/SKILL.md: sección «Consulta entre investigadores»_
- [x] 4. Tamaño de las respuestas en la vista
  - En `Consulta.tsx`, el tamaño formateado junto a cada respuesta y a la síntesis; en `types.ts`,
    `replicas` en `ConsultaEntera`.
  - _Requisitos: 2.1, 2.2_
  - _Archivos: web/src/components/Consulta.tsx, web/src/types.ts_
  - _Leer: web/src/components/Consulta.tsx (todo), web/src/types.ts: `ConsultaEntera`_
- [x] 5. Comprobación final
  - Batería completa de pruebas y build del front (`npm run build` en `web/`), lint si el repo lo corre.
  - _Depende de: 1, 2, 3, 4_
  - _Requisitos: 3.1, 3.2_
  - _Archivos: ninguno_
  - _Leer: nada_
