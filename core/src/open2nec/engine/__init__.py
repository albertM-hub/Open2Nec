"""Localisation et exécution du moteur `onec` (OpenNEC) en sous-processus."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class EngineError(RuntimeError):
    """Erreur de lancement ou d'exécution de onec."""


class ModelRejected(EngineError):
    """onec a tourné mais n'a rien calculé : c'est le modèle qui est en cause, pas le moteur."""


def find_onec() -> str:
    """Cherche onec : variable OPEN2NEC_ONEC, puis bin/ du dépôt, puis PATH."""
    env = os.environ.get("OPEN2NEC_ONEC")
    if env and Path(env).is_file():
        return env

    # <racine du dépôt>/bin/onec (core/src/open2nec/engine/__init__.py → 4 niveaux au-dessus).
    # Installé hors du dépôt (pip non éditable), ce niveau peut ne pas exister.
    parents = Path(__file__).resolve().parents
    if len(parents) > 4:
        repo_bin = parents[4] / "bin"
        for name in ("onec", "onec.exe"):
            candidate = repo_bin / name
            if candidate.is_file():
                return str(candidate)

    found = shutil.which("onec")
    if found:
        return found
    raise EngineError(
        "onec introuvable : définir OPEN2NEC_ONEC, le placer dans bin/ ou dans le PATH "
        "(https://github.com/maurymarkowitz/OpenNEC/releases)"
    )


def run_onec(deck: str, timeout: float = 120.0) -> str:
    """Écrit le deck dans un dossier temporaire, lance onec et renvoie la sortie texte."""
    onec = find_onec()
    with tempfile.TemporaryDirectory(prefix="open2nec_") as tmp:
        deck_path = Path(tmp) / "model.nec"
        out_path = Path(tmp) / "model.out"
        deck_path.write_text(deck, encoding="utf-8")
        try:
            proc = subprocess.run(
                [onec, "-o", str(out_path), str(deck_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,  # on juge sur la présence du fichier de sortie, pas sur le code retour
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(f"onec : délai dépassé ({timeout:g} s)") from exc
        except OSError as exc:  # binaire non exécutable, format incompatible…
            raise EngineError(f"onec : lancement impossible ({exc})") from exc
        if not out_path.is_file():
            message = proc.stderr.strip()
            # onec refuse un modèle invalide en l'expliquant sur stderr, sans écrire de sortie
            # (OpenNEC 2.3.x plante même juste après, code -11 : le code retour ne sert à rien).
            # Sans aucun message, c'est le moteur lui-même qui est en cause.
            if message:
                raise ModelRejected(f"onec a refusé le modèle : {message}")
            raise EngineError(f"onec s'est arrêté sans sortie ni message (code {proc.returncode})")
        return out_path.read_text(encoding="utf-8", errors="replace")
