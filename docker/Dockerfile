# syntax=docker/dockerfile:1.7
# Open2Nec : image locale complète (interface + API + moteur onec). Voir docker/README.md.
# Construction depuis la racine du dépôt : docker compose -f docker/compose.yaml up -d --build

ARG ONEC_VERSION=2.3.3
# Empreinte de l'archive officielle onec-linux-x86_64.zip de cette version (à changer avec elle)
ARG ONEC_SHA256=74c6d0e664e58689a9cd022c866ab0779fbe08ab3356fcb53f7f951b9cd8c75f

# --- 1. Interface : fichiers statiques ------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- 2. Moteur onec : release officielle d'OpenNEC, empreinte contrôlée --------------------
FROM python:3.13-slim-trixie AS onec
ARG ONEC_VERSION
ARG ONEC_SHA256
ADD --checksum=sha256:${ONEC_SHA256} \
    https://github.com/maurymarkowitz/OpenNEC/releases/download/v.${ONEC_VERSION}/onec-linux-x86_64.zip \
    /tmp/onec.zip
RUN python -m zipfile -e /tmp/onec.zip /tmp/onec \
    && install -m 0755 /tmp/onec/onec-linux-x86_64/bin/onec /usr/local/bin/onec \
    && /usr/local/bin/onec -v

# --- 3. Image finale ------------------------------------------------------------------------
# Debian 13 « trixie » : onec demande glibc ≥ 2.38 (Debian 12 n'a que 2.36)
FROM python:3.13-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPEN2NEC_ONEC=/usr/local/bin/onec \
    OPEN2NEC_WEB_DIST=/app/web

COPY --from=onec /usr/local/bin/onec /usr/local/bin/onec
COPY core/ /src/core/
COPY api/ /src/api/
RUN pip install "/src/core[optim]" /src/api && rm -rf /src
COPY --from=web /web/dist /app/web

# Utilisateur sans privilèges ; onec écrit seulement dans un dossier temporaire (/tmp)
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin open2nec
USER open2nec
WORKDIR /tmp

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"]

# Un seul processus : l'optimiseur n'accepte qu'une recherche à la fois (état en mémoire)
CMD ["uvicorn", "--factory", "app.serve:create_app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-server-header"]
