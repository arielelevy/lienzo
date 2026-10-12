# Prueba manual OFF/ON de RTK

Ariel autorizó ejecutar ahora y forzar la prueba. Se declaró el override manual de inactividad; las señales del scheduler no se falsearon. Solo se ejecutaron contratos locales, con costo de servicios cero y sin agentes/modelos pagos.

El primer intento se conserva en resultados/scheduler/off-on-manual-now.json: OFF aprobó 25 tests; ON venció el timeout de 10 segundos, código 124. No se presentó como mejora ni se borró esa evidencia.

La ayuda del binario mostró que `rtk pytest` recibe argumentos de pytest, no un comando Python completo. El arreglo usa el mismo `sys.executable -m pytest` en ambos perfiles y filtra la salida ON con `rtk pipe --filter pytest`, como argv literal sin shell. Conserva stdout original para auditoría y propaga los fallos del comando o filtro. El ensayo diferido se renueva únicamente mediante un encolado explícito y si todavía no ejecutó perfiles.

Comparación posterior con fuentes intactas, resultados/scheduler/off-on-manual-fixed.json:

| Perfil | Tests | Código | Tiempo | Caracteres de salida | Costo de servicios |
|---|---:|---:|---:|---:|---:|
| OFF | 25 aprobados | 0 | 1,776 s | 533 | USD 0 |
| ON | 25 aprobados | 0 | 1,633 s | 26 | USD 0 |

La salida fue 95,1% menor en esta muestra. El tiempo de una corrida por perfil no prueba una mejora de rendimiento; no se midieron tokens, calidad de agentes o Caveman. La salida original quedó archivada.

Veintitrés regresiones y Ruff aprobaron. La corrida completa de los dos casos aprobados de scheduler.json devolvió código 0, igual al baseline, sin fijarlo otra vez. Los cinco roles secuenciales están registrados en resultados/scheduler/roles-manual-rtk.json. La compuerta general sigue sin certificarse por mutaciones no medidas.
