"""Contratos del agregado: ejecución trazable no equivale a calidad."""

import conocimiento as k
import patrones_desarrollo as patrones
import patrones_evidencia as evidencia
import pytest


@pytest.fixture
def encargo():
    k.registrar_proyecto('ronda4-b')
    return k.crear_nodo('ronda4-b', 'encargo', 'cambio', {
        'contexto_desarrollo': {'tipo_trabajo': 'bugfix'},
        'controles_declarados': ['pruebas'],
    }, autor='server')


def test_agregado_conserva_fallo_y_retiro(encargo):
    proof = k.crear_nodo('ronda4-b', 'evidencia', 'prueba fallida', {
        'clase': 'control_desarrollo', 'control': 'pruebas',
        'estado': 'ejecutada', 'resultado': '1 failed', 'referencia': 'prueba.log',
        'pendientes': ['corregir'],
    }, autor='server')
    k.vincular('ronda4-b', encargo['id'], 'apoya', proof['id'], autor='server')
    group, = patrones.analizar('ronda4-b')['patrones']
    item, = group['controles_evidencia']
    assert item == evidencia.controles('ronda4-b', encargo['id'])
    assert item['ejecutados'][0]['datos']['resultado'] == '1 failed'
    assert item['ejecutados'][0]['datos']['pendientes'] == ['corregir']
    assert item['verificados'] == []
    assert group['calidad'].startswith('no inferida')
    k.retirar_vinculo('ronda4-b', encargo['id'], 'apoya', proof['id'],
                      por='persona:Ariel', motivo='retirado')
    assert patrones.analizar('ronda4-b')['patrones'][0]['controles_evidencia'][0]['ejecutados'] == []


def test_lote_vacio_y_encargos_invalidos(encargo):
    assert evidencia.controles_lote('ronda4-b', []) == {}
    with pytest.raises(k.Rechazo):
        evidencia.controles_lote('otro', [encargo])
    with pytest.raises(k.Rechazo):
        evidencia.controles_lote('ronda4-b', [encargo] * 501)


def test_lote_500_una_consulta_y_aislamiento(encargo, monkeypatch):
    from contextlib import contextmanager

    other = k.crear_nodo('ronda4-b', 'encargo', 'otro', {}, autor='server')
    proof = k.crear_nodo('ronda4-b', 'evidencia', 'review', {
        'clase': 'control_desarrollo', 'control': 'claude_review_local',
        'estado': 'verificada', 'resultado': 'hallazgos pendientes', 'referencia': 'review.log',
        'verificada_por': 'persona:Ariel', 'verificacion': 'revision.md',
    }, autor='server')
    k.vincular('ronda4-b', other['id'], 'apoya', proof['id'], autor='server')
    queries = []
    original = k._abrir

    @contextmanager
    def abrir(pid):
        with original(pid) as con:
            con.set_trace_callback(queries.append)
            yield con

    monkeypatch.setattr(k, '_abrir', abrir)
    result = evidencia.controles_lote('ronda4-b', [encargo, other] + [encargo] * 498)
    assert result[encargo['id']]['verificados'] == []
    assert result[other['id']]['verificados'][0]['evidencia'] == proof['id']
    assert sum(q.startswith('SELECT v.de AS encargo_origen') for q in queries) == 1


def test_agregado_declaracion_sin_ejecucion_no_es_verificacion(encargo):
    group, = patrones.analizar('ronda4-b')['patrones']
    item, = group['controles_evidencia']
    assert item['declarados'] == ['pruebas']
    assert item['ejecutados'] == item['verificados'] == item['sin_acreditar'] == []
