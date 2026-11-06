#!/usr/bin/env bash
# Essai de l'image Open2Nec : construction, démarrage, santé, calcul d'un dipôle de référence.
# Usage (depuis n'importe où) : bash docker/smoke-test.sh [--down]
#   --down : arrête le conteneur à la fin (sinon il reste lancé sur http://localhost:8080)
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE=(docker compose -f compose.yaml)
URL=http://127.0.0.1:${OPEN2NEC_PORT:-8080}

echo "1/4 Construction et démarrage (la première fois : quelques minutes)…"
"${COMPOSE[@]}" up -d --build

echo "2/4 Attente du service…"
for _ in $(seq 1 30); do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "$URL/api/health" >/dev/null || {
  echo "ÉCHEC : le service ne répond pas"
  "${COMPOSE[@]}" logs --tail 30
  exit 1
}

echo "3/4 Page et en-têtes de sécurité…"
curl -fsS -o /dev/null "$URL/"
curl -fsSI "$URL/" | grep -qi "^content-security-policy: default-src 'self'" || {
  echo "ÉCHEC : politique de sécurité absente"
  exit 1
}

echo "4/4 Dipôle demi-onde en espace libre, 14,2 MHz (attendu : 2,0 à 2,3 dBi)…"
BODY='{"wires":[{"tag":1,"segments":21,"start":[0,"-L/2",0],"end":[0,"L/2",0],"radius":0.001}],
"symbols":[{"name":"L","formula":"0.475*299.79/14.2"}],"excitations":[{"tag":1,"segment":11}],
"ground":{"kind":"free"},"frequency_mhz":14.2}'
GAIN=$(curl -fsS -X POST "$URL/api/pattern" -H 'content-type: application/json' -d "$BODY" |
  python3 -c 'import sys, json; print(json.load(sys.stdin)["summary"]["max_gain_db"])')
python3 -c "import sys; g = float('$GAIN'); sys.exit(0 if 2.0 <= g <= 2.3 else 1)" || {
  echo "ÉCHEC : gain $GAIN dBi"
  exit 1
}
echo "OK : gain $GAIN dBi. Open2Nec tourne sur $URL"

if [[ "${1:-}" == "--down" ]]; then
  "${COMPOSE[@]}" down
  echo "Conteneur arrêté."
fi
