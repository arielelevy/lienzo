"""Vista de controles respaldados por vínculos activos del grafo existente.

El productor registra evidencia clase=control_desarrollo, control, estado,
resultado y referencia. Verificada exige además verificada_por=persona:<nombre>
y verificacion (referencia revisable). No acredita calidad ni aprueba tareas.
"""

import conocimiento as k
from patrones_desarrollo import CONTROLES


def controles(pid, nid):
    """Lee un encargo y separa declaraciones de evidencia ejecutada/verificada."""
    with k._abrir(pid) as con:
        node = k._nodo(con, pid, nid)
        if node['tipo'] != 'encargo':
            raise k.Rechazo('se requiere un encargo')
        rows = con.execute(
            "SELECT e.* FROM vinculo v JOIN nodo e ON e.id=v.a "
            "WHERE v.de=? AND v.relacion='apoya' AND v.activo=1 "
            "AND e.proyecto=? AND e.tipo='evidencia' ORDER BY e.fecha,e.id",
            (nid, pid),
        ).fetchall()
    return _resultado(node, rows)


def controles_lote(pid, encargos):
    """Proyecta hasta 500 encargos ya leídos, con una consulta de evidencia."""
    if len(encargos) > 500:
        raise k.Rechazo('máximo 500 encargos')
    if any(node['tipo'] != 'encargo' or node['proyecto'] != pid for node in encargos):
        raise k.Rechazo('se requieren encargos del mismo proyecto')
    if not encargos:
        return {}
    agrupados = {node['id']: [] for node in encargos}
    marcas = ','.join('?' for _ in agrupados)
    with k._abrir(pid) as con:
        rows = con.execute(
            'SELECT v.de AS encargo_origen, e.* FROM vinculo v JOIN nodo e ON e.id=v.a '
            'JOIN nodo origen ON origen.id=v.de '
            f'WHERE v.de IN ({marcas}) AND origen.proyecto=? AND v.relacion=\'apoya\' AND v.activo=1 '
            "AND e.proyecto=? AND e.tipo='evidencia' ORDER BY e.fecha,e.id",
            (*agrupados, pid, pid),
        ).fetchall()
    for row in rows:
        agrupados[row['encargo_origen']].append(row)
    return {node['id']: _resultado(node, agrupados[node['id']]) for node in encargos}


def _resultado(node, rows):
    declared = node['datos'].get('controles_declarados', [])
    if not isinstance(declared, list):
        declared = []
    result = {
        'encargo': node['id'],
        'declarados': sorted({x for x in declared if isinstance(x, str) and x in CONTROLES}),
        'ejecutados': [], 'verificados': [], 'sin_acreditar': [],
        'calidad': 'no inferida',
    }
    for row in rows:
        evidence = k._fila(row)
        data = evidence['datos']
        if data.get('clase') != 'control_desarrollo':
            continue
        level = _nivel(data)
        result[level].append({'evidencia': evidence['id'], 'datos': data})
    return result


def _nivel(data):
    control = data.get('control')
    state = data.get('estado')
    if (not isinstance(control, str) or control not in CONTROLES
            or state not in ('ejecutada', 'verificada')
            or not _texto(data.get('referencia')) or not _texto(data.get('resultado'))):
        return 'sin_acreditar'
    if state == 'verificada':
        person = data.get('verificada_por')
        if (not isinstance(person, str) or not person.startswith('persona:')
                or not person[8:].strip() or not _texto(data.get('verificacion'))):
            return 'sin_acreditar'
        return 'verificados'
    return 'ejecutados'


def _texto(value):
    return isinstance(value, str) and bool(value.strip())
