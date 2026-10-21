"""Activación/una observación autorizada; sin reiniciar servidor ni lanzar CLI."""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import agent_evaluation
import jev
import optimization_experiment
import optimization_memory
import optimization_pilot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--session", help="Una muestra real explícita; consulta paga con cota USD.002688")
    args = parser.parse_args()
    if args.activate:
        print(json.dumps({"activation": optimization_pilot.activate()}))
    if args.session:
        with urllib.request.urlopen("http://127.0.0.1:7321/sessions", timeout=5) as response:
            sessions = json.load(response)
        session = next((s for s in sessions if s["session_id"] == args.session), None)
        if session is None:
            raise ValueError("sesión ausente")
        report = agent_evaluation.evaluate(session)
        counts = report["evidence"]["counts"]
        if not counts.get("closed") or not counts.get("tools"):
            raise ValueError("muestra real insuficiente")
        sample = optimization_pilot.sample(report, optimization_experiment.manifest())
        decision = jev.pilot_decide(sample["state"], sample["snapshot"])
        artifact = optimization_pilot.save(sample, decision)
        evidence = optimization_memory.record_jev(session["repo"], artifact, decision)
        print(
            json.dumps(
                {
                    "artifact": artifact,
                    "decision": decision,
                    "project": session["repo"],
                    "memory_evidence": evidence,
                    "profile": "unknown",
                    "quality": "sin etiquetas independientes",
                }
            )
        )


if __name__ == "__main__":
    main()
