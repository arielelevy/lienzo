"""La memoria del proyecto desde cualquier terminal: para el agente que esta trabajando (Claude, Codex,
coda, Pi), no solo para la coordinadora. Deduce el proyecto por la carpeta actual y devuelve texto legible
con los ids citables (`nodo:<id>`).

    py memoria.py                         lo vigente, lo abierto, los avisos y lo cambiado (briefing)
    py memoria.py "cola" "captura OR replica"   busca: conocimiento declarado y, aparte, la prosa
    py memoria.py --archivo lienzo/captura.py   lo que se sabe de un archivo o carpeta
    py memoria.py --tema memoria          la vista de un tema
    py memoria.py --por-que <id>          por que se descarto una alternativa
    py memoria.py --capturas [--clase respuesta]   lo ultimo que paso por el lienzo en esta carpeta

Opciones: --proyecto <id> (si no, el de la carpeta), --cwd <carpeta>, --sin-prosa, --json.
Solo lee: nunca crea el proyecto ni cambia estados. Sale con 0 si respondio, 1 si el proyecto no tiene
memoria todavia y 2 si el lienzo no contesta.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coordinar as c

# la consola de Windows en cp1252 imprime las tildes como caracteres de reemplazo (asi se vio texto
# «roto» que en la base estaba sano, ronda 3): siempre UTF-8
for flujo in (sys.stdout, sys.stderr):
    try:
        flujo.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError, OSError:
        pass


def _get(ruta: str):
    code, res = c.pedir("GET", "/conocimiento" + ruta)
    if code == 0:
        raise ConnectionError(res)
    if code != 200:
        raise LookupError(res.get("error") if isinstance(res, dict) else res)
    return res


def proyecto(args) -> str | None:
    if args.proyecto:
        return args.proyecto
    cwd = os.path.abspath(args.cwd or os.getcwd())
    return _get("/carpeta?" + urllib.parse.urlencode({"cwd": cwd})).get("proyecto")


def _linea(n: dict) -> str:
    estado = f", {n['estado']}" if n.get("estado") else ""
    d = n.get("datos") or {}
    extra = ""
    if n.get("tipo") == "decision" and d.get("motivo"):
        extra = f" — motivo: {d['motivo']}"
    elif n.get("tipo") == "hallazgo" and d.get("donde"):
        extra = f" — en {d['donde']}"
    aviso = " ⚠ apoyo rechazado" if n.get("apoyo_rechazado") else ""
    return f"- [{n.get('tipo')}{estado}] {n.get('texto')}{extra}{aviso} (nodo:{n.get('id')})"


def preguntar(pid: str, args) -> str:
    q = {"q": args.consultas, "archivos": args.archivo, "temas": args.tema_filtro, "saltos": 1, "limite": 40}
    if not args.sin_prosa and args.consultas:
        q["prosa"] = 1
    r = _get(f"/{pid}/preguntar?" + urllib.parse.urlencode({k: v for k, v in q.items() if v}, doseq=True))
    if args.json:
        return json.dumps(r, ensure_ascii=False, indent=1)
    out = [f"## Memoria de {pid}: {', '.join(args.consultas + args.archivo) or 'consulta'}"]
    out.append(f"{r['total']} candidatos (una búsqueda vacía no prueba que algo no exista).")
    out += [_linea(n) for n in r["candidatos"]] or ["_sin coincidencias en el conocimiento declarado_"]
    if r.get("prosa"):
        out.append("\n### Prosa (no declarado: no tiene estado ni veredicto)")
        for p in r["prosa"][:15]:
            donde = p.get("ruta") or f"{p.get('fuente')} de {str(p.get('session_id'))[:8]} {p.get('fecha', '')[:16]}"
            out.append(f"- {donde}: {p.get('fragmento')}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="La memoria del proyecto de esta carpeta.")
    ap.add_argument("consultas", nargs="*", help='consultas FTS5: palabras, "frase", a OR b, prefijo*')
    ap.add_argument("--proyecto")
    ap.add_argument("--cwd")
    ap.add_argument("--archivo", action="append", default=[])
    ap.add_argument("--tema", help="la vista de un tema")
    ap.add_argument("--tema-filtro", action="append", default=[], help="filtrar la busqueda por tema")
    ap.add_argument("--por-que", metavar="ALTERNATIVA")
    ap.add_argument("--capturas", action="store_true")
    ap.add_argument("--clase", choices=("pedido", "respuesta", "envio", "regla"))
    ap.add_argument("--sin-prosa", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        pid = proyecto(args)
        if not pid:
            print("Esta carpeta todavía no tiene memoria: se crea sola cuando una sesión pasa por el lienzo.")
            return 1
        if args.por_que:
            r = _get(f"/{pid}/alternativas/{args.por_que}/por_que")
            texto = (
                json.dumps(r, ensure_ascii=False, indent=1)
                if args.json
                else "\n".join(
                    [f"## Por qué se descartó «{r['alternativa']['texto']}»"]
                    + [_linea(n) + f" — motivo del descarte: {n.get('motivo_descarte')}" for n in r["descartada_por"]]
                    + ["### Fundamentos"]
                    + ([_linea(n) for n in r["fundamentos"]] or ["_sin fundamentos vinculados_"])
                    + (
                        ["### La eligen (en otro contexto)"] + [_linea(n) for n in r["elegida_por"]]
                        if r["elegida_por"]
                        else []
                    )
                )
            )
        elif args.tema:
            r = _get(f"/{pid}/vista?" + urllib.parse.urlencode({"tema": args.tema}))
            texto = json.dumps(r, ensure_ascii=False, indent=1) if args.json else r["markdown"]
        elif args.capturas:
            q = {"limite": 20, "clase": args.clase}
            r = _get(f"/{pid}/capturas?" + urllib.parse.urlencode({k: v for k, v in q.items() if v}))
            texto = (
                json.dumps(r, ensure_ascii=False, indent=1)
                if args.json
                else "\n".join(
                    [f"## Lo último que pasó por el lienzo en {pid} ({r['total']} en total)"]
                    + [
                        f"- {x['fecha'][:16]} {x['clase']} · {x.get('agente') or '?'} {x['session_id'][:8]}: "
                        + " ".join(x["texto"].split())[:300]
                        for x in r["capturas"]
                    ]
                )
            )
        elif args.consultas or args.archivo or args.tema_filtro:
            texto = preguntar(pid, args)
        else:
            r = _get(f"/{pid}/briefing?markdown=1")
            texto = json.dumps(r, ensure_ascii=False, indent=1) if args.json else r["markdown"]
    except ConnectionError as e:
        print(f"El lienzo no contesta en {c.BASE}: {e}", file=sys.stderr)
        return 2
    except LookupError as e:
        print(f"La memoria respondió con un error: {e}", file=sys.stderr)
        return 1
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
