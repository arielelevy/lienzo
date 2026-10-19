import conocimiento as k
import creencias as c
import patrones_evidencia as p
import pytest


@pytest.fixture
def encargo():
    k.registrar_proyecto('backlog-e')
    return k.crear_nodo('backlog-e', 'encargo', 'cambio', {
        'controles_declarados': ['pruebas', 'auditoria_skill']}, autor='server')


def evidencia(encargo, **fields):
    data = {'clase': 'control_desarrollo', 'control': 'pruebas', 'estado': 'ejecutada',
                'referencia': 'salidas/test.log', 'resultado': 'fallo: 1 caso'}
    data.update(fields)
    node = k.crear_nodo('backlog-e', 'evidencia', 'control', data, autor='server')
    k.vincular('backlog-e', encargo['id'], 'apoya', node['id'], autor='server')
    return node


def test_declaracion_no_acredita_ejecucion(encargo):
    result = p.controles('backlog-e', encargo['id'])
    assert result['declarados'] == ['auditoria_skill', 'pruebas']
    assert result['ejecutados'] == result['verificados'] == []


def test_ejecucion_fallida_y_verificacion_separadas(encargo):
    failed = evidencia(encargo)
    verified = evidencia(encargo, control='auditoria_skill', estado='verificada',
                         verificada_por='persona:Ariel', verificacion='review.md',
                         hallazgos=['pendiente'], correcciones_verificadas=[])
    result = p.controles('backlog-e', encargo['id'])
    assert [e['evidencia'] for e in result['ejecutados']] == [failed['id']]
    assert [e['evidencia'] for e in result['verificados']] == [verified['id']]
    assert result['verificados'][0]['datos']['hallazgos'] == ['pendiente']
    assert result['calidad'] == 'no inferida'


@pytest.mark.parametrize('fields', [{'referencia': ''}, {'resultado': None},
    {'control': []}, {'estado': 'verificada', 'verificada_por': 'server'},
    {'estado': 'verificada', 'verificada_por': 'persona:', 'verificacion': 'x'},
    {'estado': 'verificada', 'verificada_por': 'persona:Ariel'}])
def test_evidencia_incompleta_no_acredita(encargo, fields):
    evidencia(encargo, **fields)
    result = p.controles('backlog-e', encargo['id'])
    assert len(result['sin_acreditar']) == 1
    assert result['ejecutados'] == result['verificados'] == []


def test_retirar_apoyo_y_separacion_proyectos(encargo):
    node = evidencia(encargo)
    k.retirar_vinculo('backlog-e', encargo['id'], 'apoya', node['id'],
                      por='persona:Ariel', motivo='retirado')
    assert p.controles('backlog-e', encargo['id'])['ejecutados'] == []
    k.registrar_proyecto('otro-e')
    with pytest.raises(k.Rechazo):
        p.controles('otro-e', encargo['id'])


def test_refutacion_no_crea_apoyo_y_conserva_evidencia(encargo):
    proof = evidencia(encargo)
    belief = c.proponer('backlog-e', {'texto': 'hipótesis', 'accion': 'investigar',
        'dimension': 'pruebas', 'contexto': {'version_modelo': '1'}, 'fuentes': [proof['id']]}, autor='server')
    c.resolver('backlog-e', belief['id'], {'por': 'persona:Ariel', 'motivo': 'refutada',
        'resultado': 'refutada', 'evidencia': proof['id']})
    node = k.nodo('backlog-e', belief['id'])
    assert node['estado'] == 'revertida'
    assert node['datos']['evidencia_veredicto'] == proof['id']
    assert node['vinculos']['salen'] == []
    assert c.checklist('backlog-e', {'version_modelo': '1'})['items'] == []
