"""Catalogo de tools: las integraciones de Lienzo que usan un repo o servicio externo. El codigo de la
herramienta no vive aca (RTK, Caveman, Jev, pruebas agenticas y REA son repos aparte); cada modulo
declara de donde sale, que version usa, como se instala y verifica, y que hace Lienzo con ella.

Tipos:
- "mejora": se inyecta al lanzar un agente para que rinda mejor (RTK, respuestas breves). Se prende o
  apaga por PC en "Mejoras de agentes" (agent_improvements.py, clave `preferencia`).
- "evaluacion": mide o juzga el trabajo de los agentes (Jev).
- "pruebas": verifica cambios de codigo (pruebas agenticas).
- "trabajo": una capacidad para un tipo de tarea. Solo aplica en su modo (REA, ingenieria reversa).

Modos: un lanzamiento corre en un modo ("general" por defecto). Una tool se inyecta solo si su modo
es el del lanzamiento: REA no aparece en un lanzamiento normal.

Este paquete es distinto de los plugins locales (plugins.py): las tools van en Git y viajan a todas
las PCs; un plugin vive solo en la PC que lo tiene.
Las fichas pueden describir una tool distribuida como skill o plugin de un harness. Su formato no
convierte a las extensiones de Lienzo en colecciones de tools: se inventarían por separado.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

TIPOS = ("mejora", "evaluacion", "pruebas", "trabajo", "documentacion")
MODOS = ("general", "ingenieria-reversa")
AGENTES_CON_INSTRUCCIONES = ("claude", "codex", "pi", "coda")


@dataclass(frozen=True)
class Tool:
    id: str
    nombre: str
    tipo: str
    origen: str  # repo o servicio externo
    descripcion: str
    version: str | None = None  # la que usa Lienzo, si la fija
    costo: str = "gratis"  # "gratis" | "pago"
    modos: tuple[str, ...] = ("general",)
    preferencia: str | None = None  # clave de agent-improvements.json que la prende, si es una mejora
    instalar: str | None = None  # comando o paso para instalarla en una PC
    estado: Callable[[str | None], dict] = field(default=lambda distro: {"disponible": True})
    # (agente, distro) -> (instruccion o None, aviso o None). Solo las que se inyectan al lanzar.
    instruccion: Callable[[str, str | None], tuple[str | None, str | None]] | None = None
    formato: str = "tool"
    compatible_con: tuple[str, ...] = ()
    limitaciones: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS or not set(self.modos) <= set(MODOS):
            raise ValueError(f"tool {self.id}: tipo o modo desconocido")
        if self.formato not in ("tool", "skill", "plugin-claude"):
            raise ValueError(f"tool {self.id}: formato desconocido")


def _catalogo() -> list[Tool]:
    from . import anatomy, better_claude, breve, jev, pruebas_agenticas, rea, rtk

    return [breve.TOOL, rtk.TOOL, jev.TOOL, pruebas_agenticas.TOOL, rea.TOOL, anatomy.TOOL, *better_claude.TOOLS]


def catalogo() -> list[Tool]:
    return _catalogo()


def por_id(tool_id: str) -> Tool | None:
    return next((t for t in _catalogo() if t.id == tool_id), None)


def resumen(distro: str | None = None) -> list[dict]:
    """GET /tools: cada tool con su estado en esta PC. Un estado que no se puede averiguar queda
    como no disponible con el motivo, sin frenar al resto."""
    out = []
    for t in _catalogo():
        try:
            estado = t.estado(distro)
        except Exception as e:
            estado = {"disponible": False, "detalle": f"no se pudo verificar: {e}"}
        out.append(
            {
                "id": t.id,
                "nombre": t.nombre,
                "tipo": t.tipo,
                "origen": t.origen,
                "descripcion": t.descripcion,
                "version": t.version,
                "costo": t.costo,
                "modos": list(t.modos),
                "preferencia": t.preferencia,
                "instalar": t.instalar,
                "estado": estado,
                "formato": t.formato,
                "compatible_con": list(t.compatible_con),
                "limitaciones": list(t.limitaciones),
            }
        )
    return out


def instrucciones(agent: str, distro: str | None, preferencias: dict, modo: str = "general") -> tuple[str, list[str]]:
    """Lo que se le agrega a un agente al lanzarlo: las tools del modo con instruccion, y de esas las
    mejoras solo si su preferencia esta prendida. Devuelve (texto, avisos)."""
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo}")
    textos, avisos = [], []
    for t in _catalogo():
        if t.instruccion is None or modo not in t.modos:
            continue
        if t.preferencia is not None and not preferencias.get(t.preferencia):
            continue
        texto, aviso = t.instruccion(agent, distro)
        if texto:
            textos.append(texto)
        if aviso:
            avisos.append(aviso)
    if textos and agent not in AGENTES_CON_INSTRUCCIONES:
        avisos.append(f"{agent} no admite estas mejoras verificadas; se lanza sin instrucciones adicionales")
        textos = []
    return " ".join(textos), avisos
