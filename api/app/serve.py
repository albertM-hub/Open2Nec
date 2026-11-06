"""Service complet pour l'image Docker : interface construite sous `/`, API sous `/api`.

Même découpage que le proxy de Vite en développement (`/api/...` → API sans préfixe) : le front
n'a rien à changer. Lancement : `uvicorn --factory app.serve:create_app` avec OPEN2NEC_WEB_DIST
pointant sur le dossier `web/dist` (par défaut : celui du dépôt).

La politique de sécurité du contenu (CSP) interdit à la page tout appel hors de son origine :
l'application ne contacte aucun service extérieur (RGPD), et un contenu injecté ne le pourrait
pas non plus.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .main import app as api

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# uPlot et Svelte posent des styles en ligne ; le lien d'enregistrement .nec est une URL blob:
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)


SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
]


class SecurityHeaders:
    """Ajoute les en-têtes de sécurité à chaque réponse HTTP. Middleware ASGI pur : il ne touche
    pas au corps, le flux SSE de l'optimiseur passe sans mise en tampon."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in SECURITY_HEADERS if k not in names]
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(dist: Path | None = None) -> FastAPI:
    """Application complète. Sans `dist` : OPEN2NEC_WEB_DIST, puis web/dist du dépôt.

    Rien n'est créé à l'import : seul le lancement exige l'interface construite.
    """
    if dist is None:
        dist = Path(os.environ.get("OPEN2NEC_WEB_DIST", DEFAULT_DIST))
    if not (dist / "index.html").is_file():
        raise RuntimeError(
            f"interface introuvable : {dist}/index.html (construire le front : cd web && npm run "
            "build, ou définir OPEN2NEC_WEB_DIST)"
        )
    root = FastAPI(title="Open2Nec", docs_url=None, redoc_url=None, openapi_url=None)
    root.add_middleware(SecurityHeaders)
    root.mount("/api", api)
    root.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return root

