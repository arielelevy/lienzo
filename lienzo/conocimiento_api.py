"""La API HTTP del conocimiento por proyecto (v5 §7.2, etapa 1), como rules_api: funciones que
devuelven (codigo, cuerpo) y no saben de HTTP. `dispatch(metodo, partes, cuerpo, query)` recibe la
ruta ya sin el primer tramo `conocimiento`.

    GET  /conocimiento/proyectos                      lista
    POST /conocimiento/proyectos                      {id, nombre?, remotes?, carpetas?}
    GET  /conocimiento/resolver?repo_key=&cwd=&pc=    {proyecto|null}
    GET  /conocimiento/<p>                            resumen
    POST /conocimiento/<p>/rondas                     {objetivo, coordinadora?, autor?}
    POST /conocimiento/<p>/rondas/<id>/estado         {estado, por, motivo?}   (cerrada hace el cierre)
    POST /conocimiento/<p>/encargos                   {ronda, letra, texto, archivos?, autor?}
    POST /conocimiento/<p>/encargos/<id>/enviado      {session_id, agent?, model?, pc?, cwd?}
    POST /conocimiento/<p>/encargos/<id>/estado       {estado, por, motivo?}
    POST /conocimiento/<p>/entregas                   {encargo, revision, cuerpo, autor?, origen?}
    POST /conocimiento/<p>/nodos                      {tipo, texto, datos, ronda?, autor, origen?}  (solo tipos de conocimiento, con sus campos)
    POST /conocimiento/<p>/nodos/<id>/estado          {estado, por, motivo?}
    POST /conocimiento/<p>/vinculos                   {de, relacion, a, autor, motivo?, origen?}
    POST /conocimiento/<p>/vinculos/retirar           {de, relacion, a, por, motivo?}
    GET  /conocimiento/<p>/nodos?tipo=&estado=&ronda=&limite=&desde=
    GET  /conocimiento/<p>/nodos/<id>                 nodo + vinculos + cambios
    GET  /conocimiento/<p>/buscar?q=&tipo=&saltos=    BM25 + expansion por grafo
    GET  /conocimiento/<p>/cambios?desde=
    GET  /conocimiento/<p>/cuerpo?ruta=               el texto de un encargo o informe
    GET  /conocimiento/carpeta?cwd=&pc=               {proyecto|null} de esa carpeta (sin crear)
    POST /conocimiento/carpeta                        {cwd, pc?} el proyecto de la carpeta, creado si falta
    GET  /conocimiento/<p>/capturas?session_id=&clase=&desde=&limite=   lo capturado solo (anexo A de v5)
    GET  /conocimiento/<p>/prosa?q=&limite=           BM25 en cuerpos y capturas, «prosa, no declarado»
    GET  /conocimiento/<p>/texto/roto                 U+FFFD y mojibake en nodos, cuerpos, cambios y capturas
    POST /conocimiento/<p>/texto/reparar              {por, aplicar?} repara el mojibake con un cambio por nodo
    POST /conocimiento/<p>/informes/<id>/reincorporar {por} vuelve a validar un bloque pendiente
    POST /conocimiento/<p>/evidencia                  {nombre, clase, texto?, contenido_base64 | contenido_texto, autor?}
    POST /conocimiento/<p>/respaldo                   respaldo con la API de backup y los artefactos
"""

from __future__ import annotations

import base64
import binascii

import aprendizaje_api
import conocimiento as k
import identity
import sessions as ses
import veredictos_api
from conocimiento import Rechazo


def _tarjeta(d: dict) -> dict:
    """La tarjeta real de `session_id`, local o espejada de otra PC. Un id que el lienzo no conoce es
    404: antes se creaba un nodo sesion para un id inventado y el encargo quedaba `enviado` esperando
    observaciones que nunca llegarian (code review 2026-10-08)."""
    sid = k._texto(d.get("session_id"), "session_id", 100)
    with ses.lock:
        s = ses.sessions.get(sid)
    if s is None:
        if ses.find_session(sid) is not None:
            # la tarjeta es de otra PC: la base es por PC hasta la etapa 5 (base compartida) y las
            # observaciones (cierre, permisos, errores) las haria el server de alla, que no tiene el proyecto
            raise Rechazo(
                f"la sesion {sid} es de otra PC: hasta la base compartida, el encargo se vincula desde la PC duena", 409
            )
        raise Rechazo(f"el lienzo no conoce la sesion {sid}", 404)
    return {k2: s.get(k2) for k2 in ("session_id", "agent", "model", "pc", "cwd")}


def _q(query: dict, nombre: str, defecto=None):
    v = query.get(nombre)
    if isinstance(v, list):
        v = v[0] if v else None
    return v if v not in (None, "") else defecto


def _entero(v, nombre: str, defecto: int) -> int:
    if v is None:
        return defecto
    try:
        return int(v)
    except (TypeError, ValueError) as e:
        raise Rechazo(f"{nombre} debe ser un entero") from e


def dispatch(metodo: str, partes: list[str], cuerpo: dict | None, query: dict | None) -> tuple[int, dict | list]:
    cuerpo = {} if cuerpo is None else cuerpo
    query = query or {}
    try:
        if not isinstance(cuerpo, dict):
            raise Rechazo("cuerpo debe ser un objeto")
        return _dispatch(metodo, partes, cuerpo, query)
    except Rechazo as e:
        return e.codigo, {"error": str(e)}


def _dispatch(metodo: str, partes: list[str], d: dict, query: dict) -> tuple[int, dict | list]:
    if partes == ["lecciones"]:
        return aprendizaje_api.dispatch(metodo, partes, d, query)
    resto = partes[1:]
    if veredictos_api.es_mia(resto):
        return veredictos_api.dispatch(metodo, partes, d, query)
    if resto and (
        resto[0] in ("incidentes", "reglas", "avisos")
        or (len(resto) == 3 and resto[0] == "nodos" and resto[2] in ("aviso", "dependencias"))
    ):
        return aprendizaje_api.dispatch(metodo, partes, d, query)
    if partes == ["proyectos"]:
        if metodo == "GET":
            return 200, k.proyectos()
        if metodo == "POST":
            p = k.registrar_proyecto(d.get("id"), d.get("nombre"), d.get("remotes"), d.get("carpetas"))
            return 200, p
    if partes == ["carpeta"]:
        pc = (_q(query, "pc") if metodo == "GET" else d.get("pc")) or identity.pc_id()
        cwd = _q(query, "cwd") if metodo == "GET" else d.get("cwd")
        k._texto(cwd, "cwd", 1000)
        if metodo == "GET":
            return 200, {"proyecto": k.resolver_proyecto(cwd=cwd, pc=pc), "carpeta": k.carpeta_de(cwd)}
        if metodo == "POST":
            url = identity.origin_url(cwd)
            remote = identity._normalize_remote(url) if url else None
            return 200, {"proyecto": k.proyecto_de_carpeta(cwd, pc, remote), "carpeta": k.carpeta_de(cwd)}
    if partes == ["resolver"] and metodo == "GET":
        return 200, {"proyecto": k.resolver_proyecto(_q(query, "repo_key"), _q(query, "cwd"), _q(query, "pc"))}
    if not partes:
        return 404, {"error": "ruta desconocida"}
    pid, resto = partes[0], partes[1:]
    k.proyecto(pid)  # 404 si no existe
    autor = d.get("autor") or "coordinadora"
    if not resto and metodo == "GET":
        return 200, k.resumen(pid)
    if resto == ["rondas"] and metodo == "POST":
        return 200, k.abrir_ronda(
            pid,
            k._texto(d.get("objetivo"), "objetivo", 2000),
            autor=autor,
            coordinadora=d.get("coordinadora"),
            origen=d.get("origen"),
        )
    if len(resto) == 3 and resto[0] == "rondas" and resto[2] == "estado" and metodo == "POST":
        estado, por = k._texto(d.get("estado"), "estado", 40), k._texto(d.get("por"), "por", 200)
        if estado == "cerrada":
            code, resultado = veredictos_api.dispatch(
                metodo, [pid, "rondas", resto[1], "cerrar"], {**d, "por": por}, query
            )
            return code, resultado["ronda"] if code == 200 else resultado
        return 200, k.cambiar_estado(pid, resto[1], estado, por=por, motivo=d.get("motivo") or "")
    if resto == ["encargos"] and metodo == "POST":
        return 200, k.crear_encargo(
            pid,
            k._texto(d.get("ronda"), "ronda", 64),
            d.get("letra"),
            d.get("texto"),
            autor=autor,
            archivos=d.get("archivos"),
            origen=d.get("origen"),
        )
    if len(resto) == 3 and resto[0] == "encargos" and metodo == "POST":
        if resto[2] == "enviado":
            return 200, k.encargo_enviado(pid, resto[1], _tarjeta(d))
        if resto[2] == "estado":
            return 200, k.cambiar_estado(
                pid,
                resto[1],
                k._texto(d.get("estado"), "estado", 40),
                por=k._texto(d.get("por"), "por", 200),
                motivo=d.get("motivo") or "",
            )
    if resto == ["entregas"] and metodo == "POST":
        return 200, k.entregar(
            pid,
            k._texto(d.get("encargo"), "encargo", 64),
            d.get("cuerpo"),
            revision=d.get("revision"),
            autor=d.get("autor") or "frente",
            origen=d.get("origen"),
        )
    if resto == ["nodos"] and metodo == "POST":
        return 200, k.declarar_nodo(
            pid,
            d.get("tipo"),
            d.get("texto"),
            d.get("datos"),
            autor=k._texto(d.get("autor"), "autor", 200),
            origen=d.get("origen"),
            ronda=d.get("ronda"),
            motivo=d.get("motivo") or "",
        )
    if len(resto) == 3 and resto[0] == "nodos" and resto[2] == "estado" and metodo == "POST":
        return 200, k.cambiar_estado(
            pid,
            resto[1],
            k._texto(d.get("estado"), "estado", 40),
            por=k._texto(d.get("por"), "por", 200),
            motivo=d.get("motivo") or "",
            origen=d.get("origen"),
        )
    if resto == ["vinculos"] and metodo == "POST":
        return 200, k.vincular(
            pid,
            d.get("de"),
            d.get("relacion"),
            d.get("a"),
            autor=k._texto(d.get("autor"), "autor", 200),
            origen=d.get("origen"),
            motivo=d.get("motivo"),
        )
    if resto == ["vinculos", "retirar"] and metodo == "POST":
        return 200, k.retirar_vinculo(
            pid,
            d.get("de"),
            d.get("relacion"),
            d.get("a"),
            por=k._texto(d.get("por"), "por", 200),
            motivo=d.get("motivo") or "",
        )
    if resto == ["nodos"] and metodo == "GET":
        return 200, k.nodos(
            pid,
            tipo=_q(query, "tipo"),
            estado=_q(query, "estado"),
            ronda=_q(query, "ronda"),
            limite=_entero(_q(query, "limite"), "limite", k.LIMITE_PAGINA),
            desde=_entero(_q(query, "desde"), "desde", 0),
        )
    if len(resto) == 2 and resto[0] == "nodos" and metodo == "GET":
        return 200, k.nodo(pid, resto[1])
    if resto == ["buscar"] and metodo == "GET":
        semillas = k.buscar(pid, _q(query, "q", ""), tipo=_q(query, "tipo"), limite=k.LIMITE_BUSQUEDA)
        saltos = _entero(_q(query, "saltos"), "saltos", 0)
        expandidos = k.expandir(pid, [s["id"] for s in semillas], saltos=saltos) if saltos else []
        return 200, {"semillas": semillas, "expandidos": expandidos}
    if resto == ["cambios"] and metodo == "GET":
        return 200, k.cambios(pid, desde=_entero(_q(query, "desde"), "desde", 0))
    if resto == ["capturas"] and metodo == "GET":
        return 200, k.capturas(
            pid,
            session_id=_q(query, "session_id"),
            clase=_q(query, "clase"),
            desde=_q(query, "desde"),
            limite=_entero(_q(query, "limite"), "limite", 100),
        )
    if resto == ["prosa"] and metodo == "GET":
        return 200, k.buscar_prosa(pid, _q(query, "q", ""), limite=_entero(_q(query, "limite"), "limite", 30))
    if resto == ["texto", "roto"] and metodo == "GET":
        return 200, k.texto_roto_proyecto(pid)
    if resto == ["texto", "reparar"] and metodo == "POST":
        return 200, k.reparar_texto(pid, por=d.get("por"), aplicar=d.get("aplicar") is True)
    if len(resto) == 3 and resto[0] == "informes" and resto[2] == "reincorporar" and metodo == "POST":
        return 200, k.reincorporar(pid, resto[1], por=d.get("por"))
    if resto == ["evidencia"] and metodo == "POST":
        if isinstance(d.get("contenido_base64"), str):
            try:
                contenido = base64.b64decode(d["contenido_base64"], validate=True)
            except (ValueError, binascii.Error) as e:
                raise Rechazo("contenido_base64 invalido") from e
        elif isinstance(d.get("contenido_texto"), str):
            contenido = d["contenido_texto"].encode("utf-8")
        else:
            raise Rechazo("falta contenido_base64 o contenido_texto")
        return 200, k.recibir_evidencia(
            pid,
            d.get("nombre"),
            contenido,
            clase=d.get("clase"),
            texto=d.get("texto") if isinstance(d.get("texto"), str) else None,
            autor=d.get("autor") or "coordinadora",
            origen=d.get("origen"),
        )
    if resto == ["respaldo"] and metodo == "POST":
        return 200, k.respaldar(pid)
    if resto == ["cuerpo"] and metodo == "GET":
        return 200, {"ruta": _q(query, "ruta"), "texto": k.leer_cuerpo(pid, k._texto(_q(query, "ruta"), "ruta", 300))}
    return 404, {"error": "ruta desconocida"}
