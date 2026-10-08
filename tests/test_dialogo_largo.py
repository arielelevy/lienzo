"""screen.dialog con la pregunta lejos de las opciones (medido el 2026-10-08 en Teorema): Codex
dibuja el comando entero entre «Would you like to run the following command?» y «1. Yes, proceed»,
y con un `python -c` largo la pregunta quedaba mas de 12 lineas arriba. La tarjeta decia
«smartBI/claude-skills/lienzo');import coordinar as» y el auto-aprobar no lo reconocia."""

import screen

PANTALLA = """
  Would you like to run the following command?

  Environment: local

  Reason: ¿Autorizás guardar el informe de D y enviarle la continuación concreta del endgame por Lienzo?

  $ python -u -c "import sys,pathlib,json;sys.path.insert(0,'C:/Users/ArielLevy/OneDrive -
  smartBI/claude-skills/lienzo');import coordinar as
  c;c.YO='01a11bac-121b-71c1-8b0d-8469ba81a0c5';fs=c.frentes('Teorema');r=c.informe(fs['D']);print('INFORME',b
  =pathlib.Path('documentos/equipo_2026-10-08/D');p.mkdir(exist_ok=True);(p/'respuesta_01_lienzo.json').write_
  .dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');msg='D: la cota voraz no cambia el mapa. Ataca el ca
  central directamente: H tiene grados d+b(v), b en {0,1}. Borrar W deja grado d-c exactamente si |N(v) inter
  para todo v fuera de W. Verifica esta equivalencia y busca condiciones estructurales que permitan W pequeno,
  asumir independencia de restricciones ni que spread 1 permita recortar libremente. Entrega un lema no tautol
  una obstruccion explicita. Sin herramientas: marca no verificado por
  codigo.';print(c.enviar_seguro(fs['D'],msg,proyecto='Teorema',letra='D'));print(c.pedir('GET','/sessions/'+f
  ession_id']+'/screen'))"


› 1. Yes, proceed (y)
  2. Yes, and don't ask again for commands that start with `python -u -c "import sys,pathlib,json;sys.path.ins
     Users/ArielLevy/OneDrive - smartBI/claude-skills/lienzo');import coordinar as c;c.YO='01a11bac-121b-71c1-
     8469ba81a0c5';fs=c.frentes('Teorema');r=c.informe(fs['D']);print('INFORME',bool(r));p=pathlib.Path('docum
     equipo_2026-10-08/D');p.mkdir(exist_ok=True);
↓
  Press enter to confirm or esc to cancel
"""


def test_la_pregunta_se_busca_hacia_arriba_cuando_el_comando_es_largo():
    d = screen.dialog(PANTALLA.splitlines())
    assert d is not None
    assert d["question"] == "Would you like to run the following command?"
    assert d["detail"].startswith("Environment: local Reason:")
    assert [o["text"][:16] for o in d["options"]] == ["Yes, proceed (y)", "Yes, and don't a"]
    assert d["selected"] == 1 and d.get("teclas") == "flechas"


def test_un_dialogo_corto_sigue_igual():
    lineas = ["  Switch model?", "  Elegí uno", "", "› 1. Default", "  2. Opus", "", "  Enter to confirm"]
    d = screen.dialog(lineas)
    assert d and d["question"] == "Switch model?" and d["detail"] == "Elegí uno"


def test_la_ultima_pregunta_gana_sobre_una_vieja_mas_arriba():
    lineas = [
        "  Would you like to run the following command?",
        "  $ viejo",
        "  ✔ You approved",
        "",
    ] + PANTALLA.splitlines()
    d = screen.dialog(lineas)
    assert d and d["detail"].startswith("Environment: local")
