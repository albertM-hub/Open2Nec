"""CLI minimale : `open2nec run modele.nec`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import EngineError
from .simulate import simulate_deck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="open2nec", description="Simulation d'antennes NEC-2")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="simuler un fichier .nec")
    run.add_argument("deck", type=Path)
    run.add_argument("--z0", type=float, default=50.0, help="impédance de référence (Ω)")
    args = parser.parse_args(argv)

    try:
        deck = args.deck.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"Erreur : lecture de {args.deck} impossible ({exc.strerror})", file=sys.stderr)
        return 1
    try:
        res = simulate_deck(deck)
    except EngineError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    print(f"{'f (MHz)':>9} {'R (Ω)':>9} {'X (Ω)':>9} {'ROS':>7} {'Gmax (dBi)':>11}")
    for fr in res.frequencies:
        for fp in fr.feedpoints:
            gmax = fr.max_gain_db
            g = f"{gmax:11.2f}" if gmax is not None else f"{'-':>11}"
            print(
                f"{fr.frequency_mhz:9.3f} {fp.impedance.real:9.2f} {fp.impedance.imag:9.2f} "
                f"{fp.swr(args.z0):7.2f} {g}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
