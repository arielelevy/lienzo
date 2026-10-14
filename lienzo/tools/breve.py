"""Respuestas breves, inspiradas en Caveman. Solo una instruccion: no instala su proxy ni comprime
archivos."""

from __future__ import annotations

from . import Tool

TEXTO = (
    "Responde breve y en el idioma del usuario. Primero el resultado; despues solo lo necesario. "
    "Una idea por frase. Conserva negaciones, numeros, rutas, comandos y errores exactos. "
    "La brevedad no reduce el trabajo, las pruebas, la revision, la seguridad ni la accesibilidad. "
    "Respeta las instrucciones del usuario y del proyecto. No comprimas archivos ni uses un proxy Caveman."
)


def _instruccion(agent: str, distro: str | None) -> tuple[str | None, str | None]:
    return TEXTO, None


TOOL = Tool(
    id="breve",
    nombre="Respuestas breves",
    tipo="mejora",
    origen="https://github.com/JuliusBrussee/caveman",
    descripcion="Instrucción de respuestas breves al lanzar; sin el proxy de Caveman ni compresión de archivos.",
    preferencia="brief",
    modos=("general", "ingenieria-reversa"),
    estado=lambda distro: {"disponible": True, "detalle": "instrucciones breves, sin proxy"},
    instruccion=_instruccion,
)
